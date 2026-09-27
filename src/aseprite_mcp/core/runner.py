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
    AsepriteTimeoutError,
    LuaToolError,
)
from .limits import MAX_PROCESS_OUTPUT_CHARS
from .luagen import ERROR_PREFIX, RESULT_PREFIX, assemble_script

# Size of each read from a child pipe. Peak retention per stream is the character
# cap plus at most one of these.
_READ_CHUNK = 64 * 1024


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
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
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
        for reader in readers:
            reader.join(timeout=5)
        raise
    finally:
        for reader in readers:
            reader.join(timeout=5)

    return subprocess.CompletedProcess(
        argv, proc.returncode, out_box.get("text", ""), err_box.get("text", "")
    )


def run_lua(body: str, args: dict | None = None, timeout: float | None = None) -> dict:
    """Assemble + run a Lua tool body, returning the parsed RESULT table.

    Raises AsepriteError with the Lua error message on failure.
    """
    script = assemble_script(body, args)
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

    return _parse_result(proc)


def _truncate(text: str, limit: int = MAX_PROCESS_OUTPUT_CHARS) -> str:
    """Bound a captured stream so a runaway Aseprite script can't blow up the
    error path it feeds. Keeps the tail, which is where the failure usually is.

    The bound is in characters, matching MAX_PROCESS_OUTPUT_CHARS; see the note on
    that constant for why the decoded length is the right unit here.
    """
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} characters truncated ...]\n" + text[-limit:]


def _parse_result(proc: subprocess.CompletedProcess) -> dict:
    out = _truncate(proc.stdout or "")
    result_json: str | None = None
    error_msg: str | None = None

    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith(RESULT_PREFIX):
            result_json = line[len(RESULT_PREFIX):]
        elif line.startswith(ERROR_PREFIX):
            error_msg = line[len(ERROR_PREFIX):]

    if error_msg is not None:
        raise LuaToolError(error_msg)

    if result_json is None:
        detail = _truncate((proc.stderr or "").strip()) or out.strip() or (
            f"Aseprite exited with code {proc.returncode} and produced no result."
        )
        raise LuaToolError(detail)

    try:
        parsed = json.loads(result_json)
    except json.JSONDecodeError as exc:
        raise LuaToolError(f"Could not parse Aseprite result as JSON: {exc}") from exc

    # The Lua side encodes an empty result table as a JSON array; normalize to {}.
    if isinstance(parsed, list) and not parsed:
        return {}
    return parsed


def run_cli(cli_args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run a raw Aseprite CLI command (used for exports / rendering)."""
    exe = config.find_aseprite()
    try:
        proc = _run_bounded([exe, "-b", *cli_args], timeout or config.timeout())
    except subprocess.TimeoutExpired as exc:
        raise AsepriteTimeoutError(f"Aseprite CLI timed out after {exc.timeout:.0f}s.") from exc

    if proc.returncode != 0:
        detail = _truncate((proc.stderr or proc.stdout or "").strip()) or (
            f"Aseprite CLI failed with exit code {proc.returncode}."
        )
        raise AsepriteCLIError(detail)
    return proc
