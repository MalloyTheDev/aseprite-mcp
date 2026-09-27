"""Run Lua scripts and CLI commands against Aseprite, returning structured data."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import threading
from collections import deque

from . import config
from .errors import (  # noqa: F401  (AsepriteError re-exported for back-compat)
    AsepriteCLIError,
    AsepriteError,
    AsepriteNotFoundError,
    AsepriteTimeoutError,
    LuaToolError,
    strip_script_location,
)
from .limits import MAX_PROCESS_OUTPUT_CHARS
from .luagen import assemble_script, error_prefix, new_nonce, result_prefix

# Size of each read from a child pipe. Peak retention per stream is the character
# cap plus at most one of these.
_READ_CHUNK = 64 * 1024

# Serializes every Aseprite invocation in this process.
#
# An Aseprite run is a read-modify-write on a sprite file: it opens the document,
# edits it, and saves over the original. Two runs touching one file therefore race on
# the whole file, and the loser does not merely lose its own edit. Measured over eight
# trials of two concurrent single-layer additions to one sprite: three silently kept
# only one edit, five left a file that no longer decodes ("ZLib error -3 in inflate()"),
# and all eight reported success to the caller. Destroying the user's art and reporting
# ok is the worst failure this server can have, so the bound has to hold by default.
#
# FastMCP dispatches sync tools through anyio's worker threads, and all but one tool
# here is sync, so overlap needs nothing more than a client that batches calls.
#
# This is deliberately one global lock rather than a per-path one. Locking per path
# would keep unrelated files parallel, but it has to derive the path from tool arguments,
# and a tool whose argument key is not recognised would silently get no lock at all,
# which reintroduces exactly this bug in a form that looks fixed. Sequential callers,
# the common case, never contend for this lock; concurrent callers on different files
# pay serialization they can measure, which is the right way round. Refining it is
# tracked as a follow-up rather than guessed at here.
#
# Reentrant so a tool that internally calls another tool's helper on the same thread
# cannot deadlock against itself.
_ASEPRITE_LOCK = threading.RLock()


def _drain_tail(stream, limit: int, box: dict) -> None:
    """Read `stream` to EOF, retaining only its final `limit` characters.

    The tail is the part worth keeping: the RESULT/ERROR sentinels are printed last,
    and a traceback ends with its cause. Whole chunks are discarded from the front as
    soon as the remainder still covers the limit, so memory stays bounded however much
    the child emits.
    """
    chunks: deque[str] = deque()
    held = 0
    dropped = 0
    try:
        while True:
            chunk = stream.read(_READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
            held += len(chunk)
            while chunks and held - len(chunks[0]) >= limit:
                first = chunks.popleft()
                held -= len(first)
                dropped += len(first)
    except (OSError, ValueError):  # pipe closed underneath us (e.g. after a kill)
        pass
    finally:
        with contextlib.suppress(Exception):
            stream.close()

    text = "".join(chunks)
    if len(text) > limit:
        dropped += len(text) - limit
        text = text[-limit:]
    if dropped:
        # Dropping from the front cuts mid-line, and that surviving fragment is worse
        # than useless: the cut can fall inside a sentinel, hiding a real result, and it
        # can equally fall just after caller data so that the fragment *begins* with
        # text the caller chose. Offsets here are deterministic, so that second case is
        # computable rather than lucky. Discard the fragment and keep whole lines only.
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else ""
        text = f"[... {dropped} characters truncated ...]\n" + text
    box["text"] = text


def _run_bounded(
    argv: list[str], timeout: float, limit: int = MAX_PROCESS_OUTPUT_CHARS
) -> subprocess.CompletedProcess:
    """Run `argv`, retaining at most `limit` characters of each output stream.

    `subprocess.run(capture_output=True)` accumulates the whole of stdout and stderr
    in memory before it returns, so truncating afterwards cannot prevent a runaway
    script from exhausting the host: by then the memory has been spent. Draining each
    pipe in its own thread into a bounded tail buffer keeps peak usage proportional to
    the cap instead of to whatever the child decides to print. Two threads, because
    reading one pipe to EOF before the other deadlocks as soon as the child fills the
    one that is not being read.

    Held under `_ASEPRITE_LOCK` for its whole duration, so one Aseprite process touches
    the sprite files at a time. Waiting for the lock is deliberately outside `timeout`:
    the timeout bounds how long Aseprite may run, not how long a queue may be.
    """
    with _ASEPRITE_LOCK:
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Without this the child inherits the server's stdin, which under the
                # stdio transport is the client's JSON-RPC stream. Batch-mode Aseprite
                # does not read stdin today, so this is latent rather than live, but a
                # child that ever did would silently eat protocol frames.
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            # A path that exists but cannot be executed (a .txt, a script, a file with
            # no execute bit) reaches here as a bare OSError, which is outside the typed
            # hierarchy and surfaces to the model as an unhandled error.
            raise AsepriteNotFoundError(
                f"Could not execute Aseprite at '{argv[0]}': {exc}. Check that "
                "ASEPRITE_PATH points at the Aseprite binary itself."
            ) from exc

        out_box: dict = {}
        err_box: dict = {}
        readers = [
            threading.Thread(target=_drain_tail, args=(proc.stdout, limit, out_box), daemon=True),
            threading.Thread(target=_drain_tail, args=(proc.stderr, limit, err_box), daemon=True),
        ]
        for reader in readers:
            reader.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise
        finally:
            # One join, in the one place that always runs. Joining again in the except
            # branch only added another 5s per stream to the timeout path.
            for reader in readers:
                reader.join(timeout=5)

        return subprocess.CompletedProcess(
            argv, proc.returncode, out_box.get("text", ""), err_box.get("text", "")
        )


def run_lua(body: str, args: dict | None = None, timeout: float | None = None) -> dict:
    """Assemble + run a Lua tool body, returning the parsed RESULT table.

    Raises AsepriteError with the Lua error message on failure.
    """
    nonce = new_nonce()
    script = assemble_script(body, args, nonce=nonce)
    exe = config.find_aseprite()

    fd, path = tempfile.mkstemp(suffix=".lua", prefix="asemcp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(script)
        proc = _run_bounded([exe, "-b", "--script", path], timeout or config.timeout())
    except subprocess.TimeoutExpired as exc:
        raise AsepriteTimeoutError(
            f"Aseprite timed out after {exc.timeout:.0f}s. Increase ASEPRITE_MCP_TIMEOUT "
            "or split the operation into smaller steps."
        ) from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)

    return _parse_result(proc, nonce=nonce)


def _truncate(text: str, limit: int = MAX_PROCESS_OUTPUT_CHARS) -> str:
    """Bound a captured stream so a runaway Aseprite script can't blow up the
    error path it feeds. Keeps the tail, which is where the failure usually is.

    The bound is in characters, matching MAX_PROCESS_OUTPUT_CHARS; see the note on
    that constant for why the decoded length is the right unit here.

    Retained as a standalone utility, but no longer applied on the way out of a real
    run: `_drain_tail` already bounds both streams at read time, and applying this on
    top of that output truncated the truncation marker, so the reported count became
    the marker's own length (1,048,598 characters dropped, reported as 39).
    """
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} characters truncated ...]\n" + text[-limit:]


def _parse_result(proc: subprocess.CompletedProcess, *, nonce: str) -> dict:
    """Extract the RESULT table from one run's stdout, keyed on that run's `nonce`.

    Both streams are already bounded by `_drain_tail`, so nothing here re-truncates:
    applying a second bound on top of the first replaced the real dropped-character
    count with one computed from the length of the first marker.
    """
    ok_prefix = result_prefix(nonce)
    err_prefix = error_prefix(nonce)
    out = proc.stdout or ""

    # split("\n"), not splitlines(): splitlines() also breaks on U+0085, U+2028, U+2029
    # and several other characters that are legal inside a JSON string, so it sees line
    # boundaries the Lua side never wrote.
    lines = [line.strip() for line in out.split("\n")]
    results = [line[len(ok_prefix):] for line in lines if line.startswith(ok_prefix)]
    errors = [line[len(err_prefix):] for line in lines if line.startswith(err_prefix)]

    # The harness prints exactly one sentinel. More than one means something other than
    # the harness wrote one, so there is no honest way to pick; refuse instead of
    # guessing, which is what "last one wins" silently did.
    if len(results) > 1 or len(errors) > 1 or (results and errors):
        raise LuaToolError(
            "Aseprite produced more than one result line for this run; refusing to "
            "choose between them."
        )

    if errors:
        raise LuaToolError(_decode_error(errors[0]))

    if not results:
        detail = (proc.stderr or "").strip() or out.strip() or (
            f"Aseprite exited with code {proc.returncode} and produced no result."
        )
        raise LuaToolError(detail)

    try:
        parsed = json.loads(results[0])
    except json.JSONDecodeError as exc:
        raise LuaToolError(f"Could not parse Aseprite result as JSON: {exc}") from exc

    # The Lua side encodes an empty result table as a JSON array; normalize to {}.
    if isinstance(parsed, list) and not parsed:
        return {}
    # Declared `-> dict`, so make that true. A bare scalar or list here would otherwise
    # reach the tool functions, which index into the result and raise TypeError.
    if not isinstance(parsed, dict):
        raise LuaToolError(
            f"Aseprite returned a JSON {type(parsed).__name__} where an object was "
            "expected."
        )
    return parsed


def _decode_error(payload: str) -> str:
    """Decode the json_encoded Lua error message, tolerating a malformed one.

    The script location is stripped here rather than at each call site. Lua's `error()`
    prepends `<script>:<line>:` at level 1, and the prelude's helpers use the default
    level, so a caller asking for a layer that does not exist was told
    `C:\\...\\Temp\\asemcp_i5f2dp0f.lua:264: No layer named 'ghost'`. The path names a
    temporary file that no longer exists by the time anyone reads it, and the line number
    refers to generated code, so both are noise to the caller and a host path leak.
    Doing it at this one seam covers every tool, not only the batch runner.
    """
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return strip_script_location(payload)
    text = decoded if isinstance(decoded, str) else str(decoded)
    return strip_script_location(text)


def run_cli(cli_args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run a raw Aseprite CLI command (used for exports / rendering)."""
    exe = config.find_aseprite()
    try:
        proc = _run_bounded([exe, "-b", *cli_args], timeout or config.timeout())
    except subprocess.TimeoutExpired as exc:
        raise AsepriteTimeoutError(f"Aseprite CLI timed out after {exc.timeout:.0f}s.") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or (
            f"Aseprite CLI failed with exit code {proc.returncode}."
        )
        raise AsepriteCLIError(detail)

    # Aseprite's CLI exits 0 for arguments it rejected. `-b --totally-bogus-flag` prints
    # "Invalid option" to stderr and exits 0; so does exporting a file that does not
    # exist ("File not found", then "A document is needed before --save-as"). Trusting
    # the exit code alone therefore turns a refused export into a reported success, and
    # the caller has no way to tell. A successful batch run is silent on stderr, so a
    # non-empty stderr is the signal the exit code fails to give.
    stderr = (proc.stderr or "").strip()
    if stderr:
        raise AsepriteCLIError(
            f"Aseprite CLI reported a problem (exit code {proc.returncode}): {stderr}"
        )
    return proc
