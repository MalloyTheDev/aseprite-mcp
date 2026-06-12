"""Run Lua scripts and CLI commands against Aseprite, returning structured data."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

from . import config
from .errors import (  # noqa: F401  (AsepriteError re-exported for back-compat)
    AsepriteCLIError,
    AsepriteError,
    AsepriteTimeoutError,
    LuaToolError,
)
from .luagen import ERROR_PREFIX, RESULT_PREFIX, assemble_script


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
        proc = subprocess.run(
            [exe, "-b", "--script", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or config.timeout(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AsepriteTimeoutError(
            f"Aseprite timed out after {exc.timeout:.0f}s. Increase ASEPRITE_MCP_TIMEOUT "
            "or split the operation into smaller steps."
        ) from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    return _parse_result(proc)


def _parse_result(proc: subprocess.CompletedProcess) -> dict:
    out = proc.stdout or ""
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
        detail = (proc.stderr or "").strip() or out.strip() or (
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
        proc = subprocess.run(
            [exe, "-b", *cli_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or config.timeout(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AsepriteTimeoutError(f"Aseprite CLI timed out after {exc.timeout:.0f}s.") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or (
            f"Aseprite CLI failed with exit code {proc.returncode}."
        )
        raise AsepriteCLIError(detail)
    return proc
