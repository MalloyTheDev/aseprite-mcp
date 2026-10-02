"""Run Lua scripts and CLI commands against Aseprite, returning structured data."""

from __future__ import annotations

import contextlib
import contextvars
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

# --------------------------------------------------------------------------- #
# Serializing Aseprite invocations                                            #
# --------------------------------------------------------------------------- #
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
# What gets serialized is a *claim*: either a set of sprite paths, or the whole editor
# when the paths are not known. Two runs overlap only when both claims are path sets and
# those sets are disjoint. This used to be a single process-wide lock, which is the same
# machinery with every claim being the whole editor; narrowing it keeps a client that
# batches calls across unrelated sprites parallel, where an Aseprite launch is about
# 0.3s and the global lock turned six of them into a queue (#66).
#
# The two ways of being wrong here are not symmetrical, and the design leans on that.
# Claiming more than a run touches costs serialization, which is exactly what the global
# lock already cost. Claiming less corrupts files. So every unknown resolves to the whole
# editor; `_claim_keys` is where that happens and names each case.
#
# Reentrant, in the sense that a thread already inside a claim does not wait for itself:
# a tool that reached the runner twice on one thread was safe under the RLock and stays
# safe here. One shape of that is worth naming rather than leaving implied. A thread that
# nests a claim on a path *another* thread holds waits while still holding its own, and
# two threads doing that in opposite orders would deadlock. Nothing can reach it today:
# `_run_bounded` is the only place a claim is taken, and nothing it calls re-enters the
# runner, so no thread is ever inside two claims. Whoever first makes a run nest inside
# another run has to answer this, and the answer is an ordering rule, not a wider claim.

# Guards the claim table, and nothing else. It is held for bookkeeping only, never across
# an Aseprite run: the exclusion between runs comes from the claims, not from holding
# this, which is why a narrowed run can proceed while another one is in flight.
_CLAIMS_LOCK = threading.RLock()
_CLAIMS_FREED = threading.Condition(_CLAIMS_LOCK)

# One (owning thread, claim) entry per invocation in flight. `None` as the claim means
# the whole editor. A list rather than a dict keyed on the thread, so a thread that
# re-enters holds two entries instead of overwriting the first and releasing a claim that
# is still in use.
_CLAIMS: list[tuple[int, frozenset[str] | None]] = []

# How many paths one call may record before the recording is abandoned. A call that hands
# Aseprite more paths than this is not what the narrowing is for, and abandoning the
# recording costs only the global claim. The cap is here so that nothing can grow this
# set without bound.
_MAX_RECORDED_PATHS = 256

# How many nodes of an argument structure `_claim_keys` will visit before giving up. The
# largest payload any tool accepts is a 65,536-entry pixel list, which is about 262,000
# nodes and measured 77ms to walk against the 290ms `to_lua` already spends serializing
# the same thing. The budget sits well clear of that; it exists so an argument structure
# that is cyclic or absurdly deep ends in the global claim rather than in a hang.
_MAX_ARG_NODES = 2_000_000

# Paths the current call has handed to Aseprite, recorded by `tools.common.lua_path`.
#
# A ContextVar rather than a thread-local because FastMCP dispatches sync tools through
# anyio's pooled worker threads: a thread-local would survive into the next call that
# reused the thread. anyio copies the context in per call, so what is set here is dropped
# when the call returns. Measured on this interpreter: three sequential tool-shaped calls
# landing on one pooled worker each saw only their own value.
_RECORDED_PATHS: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "aseprite_recorded_paths", default=None
)


def record_path(path: str) -> None:
    """Note a path the current call is about to hand to Aseprite.

    Called from `tools.common.lua_path`, the one seam every path reaching a Lua script
    passes through. Recording there rather than reading the tool's arguments is the whole
    point: ten different argument names are in use for paths (`src`, `source`, `dst`,
    `target`, `path`, `palfile`, `p`, `output`, `image`, `from_image`), so a runner that
    sniffed argument keys would claim nothing at all for a tool whose key it did not
    know, and a run that claims nothing looks exactly like a run that is correctly
    parallel.

    Nothing clears this, and nothing needs to: a leftover entry cannot be mistaken for a
    live one, because `_claim_keys` only claims a recorded path that is also an argument
    of the run in front of it.
    """
    seen = _RECORDED_PATHS.get()
    if seen is None:
        # A fresh set per context. The ContextVar's default is None rather than an empty
        # set because a mutable default is one object shared by every call in the
        # process, which is the leak the ContextVar is here to avoid.
        seen = set()
        _RECORDED_PATHS.set(seen)
    elif len(seen) >= _MAX_RECORDED_PATHS:
        # Dropping the recording only widens the next claim to the whole editor.
        seen.clear()
    seen.add(path)


def _claim_keys(args: dict | None) -> frozenset[str] | None:
    """The paths a run may be narrowed to, or None meaning the whole editor.

    This function is the safety argument, so it is worth stating in full:

      * A path reaches a Lua script only as a value inside `args`. No tool body embeds
        one, since not one of them is an f-string, so walking `args` sees every path the
        run names.
      * The one path a body builds for itself is the `.msk` selection sidecar, which the
        prelude derives from `ARG.src` by replacing the extension. It is covered without
        being seen: any two runs that could race on one sidecar both name the sprite it
        belongs to, so both claim that path.
      * `lua_path` is the only producer of those values and records what it returns, so a
        value that is not in the recording is one this function cannot account for.
      * Every path `lua_path` returns has been through `config.resolve`, so it is
        absolute and forward-slashed. An unaccounted value containing a separator of
        either kind therefore means the whole editor.

    The backslash half of that test is not redundant, and it is the difference between a
    safety property and a convention. A path reaching Lua is forward-slashed only because
    it came through `lua_path`, so testing for "/" alone makes the whole argument circular:
    it detects exactly the paths that are already recorded. A tool that passed a raw
    `str(resolved_path)` instead would hand Windows a backslash string that is neither
    recorded nor, under a "/"-only test, path-shaped, and the claim would narrow around a
    file it was about to write. Nothing does that today (every such site is on the
    `run_cli` route, which claims the whole editor), and an audit over the full
    --run-aseprite tier logged no narrowed claim that omitted a path-shaped value of
    either spelling, so this costs nothing measurable. It means the argument no longer
    depends on a convention that only CONTRIBUTING.md enforces.

    A false positive, a layer name or a text string carrying a backslash, costs the whole
    editor for that call, which is the safe direction and is what every other declining
    case here already does.

    Four things make it decline to narrow, and all four are the safe direction: nothing
    was recorded, a value could not be accounted for, the walk ran out of budget, or no
    path was named at all. A recording left over from an earlier call on the same pooled
    thread is not one of them, because such a path is claimed only when this run also
    names it, and a path this run names is a path this run may touch.
    """
    recorded = _RECORDED_PATHS.get()
    if not recorded:
        return None

    keys: set[str] = set()
    stack: list = [args]
    budget = _MAX_ARG_NODES
    while stack:
        budget -= 1
        if budget < 0:
            return None
        node = stack.pop()
        if isinstance(node, str):
            if node in recorded:
                # normcase, because two spellings differing only in case name one file on
                # Windows and two claims that fail to intersect is precisely the overlap
                # this exists to prevent.
                keys.add(os.path.normcase(node))
            elif "/" in node or "\\" in node:
                return None
        elif isinstance(node, dict):
            for key, value in node.items():
                stack.append(key)
                stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    # An empty set would claim nothing and overlap with everything, so a run that named
    # no path at all takes the whole editor instead.
    return frozenset(keys) or None


def _conflicts(keys: frozenset[str] | None, mine: int) -> bool:
    """Would a claim of `keys` overlap a claim another thread holds right now?

    Called with `_CLAIMS_LOCK` held. This thread's own entries are skipped: waiting for
    them would be waiting for ourselves, which is the deadlock the RLock used to rule
    out.
    """
    for owner, held in _CLAIMS:
        if owner == mine:
            continue
        if keys is None or held is None or keys & held:
            return True
    return False


@contextlib.contextmanager
def _claim(keys: frozenset[str] | None):
    """Hold `keys` (or the whole editor, for None) for the duration of the block."""
    mine = threading.get_ident()
    entry = (mine, keys)
    with _CLAIMS_FREED:
        while _conflicts(keys, mine):
            _CLAIMS_FREED.wait()
        _CLAIMS.append(entry)
    try:
        yield
    finally:
        with _CLAIMS_FREED:
            _CLAIMS.remove(entry)
            # notify_all rather than notify: waiters are queued on different paths, so
            # the single thread a targeted wake chose may well be one this release does
            # not unblock, leaving the rest asleep behind a claim that is already gone.
            _CLAIMS_FREED.notify_all()


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
    argv: list[str],
    timeout: float,
    limit: int = MAX_PROCESS_OUTPUT_CHARS,
    *,
    keys: frozenset[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run `argv`, retaining at most `limit` characters of each output stream.

    `subprocess.run(capture_output=True)` accumulates the whole of stdout and stderr
    in memory before it returns, so truncating afterwards cannot prevent a runaway
    script from exhausting the host: by then the memory has been spent. Draining each
    pipe in its own thread into a bounded tail buffer keeps peak usage proportional to
    the cap instead of to whatever the child decides to print. Two threads, because
    reading one pipe to EOF before the other deadlocks as soon as the child fills the
    one that is not being read.

    `keys` claims the sprite paths this run touches for its whole duration, so one
    Aseprite process at a time touches any given file. It defaults to None, the whole
    editor, so a caller that has not thought about which files it reaches gets the old
    process-wide behaviour rather than no exclusion. Waiting for the claim is deliberately
    outside `timeout`: the timeout bounds how long Aseprite may run, not how long a queue
    may be.
    """
    with _claim(keys):
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
    # Worked out before the script file exists, so the claim covers the whole window in
    # which this run can touch a sprite. The script's own temp path is unique per run and
    # needs no claim.
    keys = _claim_keys(args)

    fd, path = tempfile.mkstemp(suffix=".lua", prefix="asemcp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(script)
        proc = _run_bounded(
            [exe, "-b", "--script", path], timeout or config.timeout(), keys=keys
        )
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
    """Run a raw Aseprite CLI command (used for exports / rendering).

    Always claims the whole editor rather than a path set. Nothing on this route reaches
    Lua, so none of its paths go through `lua_path` and there is no recording to narrow
    against; picking them out of `cli_args` instead would be the argument-key mistake in
    a different costume, since that list interleaves paths with flags and the values of
    flags, and a misread entry claims the wrong file. An export is also not where a
    batching client spends its time: the Lua tools are.
    """
    exe = config.find_aseprite()
    try:
        proc = _run_bounded([exe, "-b", *cli_args], timeout or config.timeout(), keys=None)
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
