"""Locating the Aseprite executable, the workspace directory, and run settings.

All of these can be overridden with environment variables so the same server
works on any machine:

    ASEPRITE_PATH            Absolute path to Aseprite.exe (or `aseprite` binary).
    ASEPRITE_MCP_WORKSPACE   Directory where relative sprite paths are resolved.
    ASEPRITE_MCP_TIMEOUT     Per-invocation timeout in seconds (default 90, clamped
                             to 1-3600; an unparseable/out-of-range value falls back
                             to the nearest bound rather than disabling the timeout).
    ASEPRITE_MCP_ALLOW_ABSOLUTE  Set to 1/true to permit absolute paths and paths
                             that escape the workspace. Off by default (sandboxed).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .errors import AsepriteNotFoundError, WorkspaceError

# Project root = three levels up (src/aseprite_mcp/core/config.py -> repo root).
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Common install locations checked when ASEPRITE_PATH is not set and the binary
# is not on PATH. Steam, standalone installer, and scoop/winget layouts.
_CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe",
    r"C:\Program Files\Steam\steamapps\common\Aseprite\Aseprite.exe",
    r"C:\Program Files\Aseprite\Aseprite.exe",
    r"C:\Program Files (x86)\Aseprite\Aseprite.exe",
    # macOS / Linux fallbacks (harmless on Windows).
    "/Applications/Aseprite.app/Contents/MacOS/aseprite",
    "/usr/bin/aseprite",
    "/usr/local/bin/aseprite",
]

# Cache of the last successful lookup, keyed by the ASEPRITE_PATH value it was
# resolved under. Keying on the env var means a caller (or a test) that changes
# ASEPRITE_PATH is never served a stale executable from a previous value.
_cached_exe: str | None = None
_cached_for_env: str | None = None


def _is_executable_file(path: str) -> bool:
    """True if `path` names an existing file (a directory is not a binary)."""
    return Path(path).is_file()


def find_aseprite() -> str:
    """Return the path to the Aseprite executable, or raise AsepriteNotFoundError
    (which is also a FileNotFoundError, for backwards compatibility)."""
    global _cached_exe, _cached_for_env

    env = os.environ.get("ASEPRITE_PATH")
    if _cached_exe and _cached_for_env == env and _is_executable_file(_cached_exe):
        return _cached_exe

    if env:
        if Path(env).is_dir():
            raise AsepriteNotFoundError(
                f"ASEPRITE_PATH is set to '{env}', which is a directory. Point it at the "
                "Aseprite executable itself (e.g. .../Aseprite/Aseprite.exe)."
            )
        if _is_executable_file(env):
            _cached_exe, _cached_for_env = env, env
            return env
        raise AsepriteNotFoundError(
            f"ASEPRITE_PATH is set to '{env}' but no file exists there."
        )

    on_path = shutil.which("aseprite") or shutil.which("Aseprite")
    if on_path:
        _cached_exe, _cached_for_env = on_path, env
        return on_path

    for candidate in _CANDIDATES:
        if _is_executable_file(candidate):
            _cached_exe, _cached_for_env = candidate, env
            return candidate

    raise AsepriteNotFoundError(
        "Could not locate Aseprite. Set the ASEPRITE_PATH environment variable to "
        "the full path of Aseprite.exe (e.g. "
        r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe)."
    )


def workspace() -> Path:
    """Directory where relative sprite filenames are resolved. Created if missing."""
    env = os.environ.get("ASEPRITE_MCP_WORKSPACE")
    base = Path(env) if env else (PROJECT_ROOT / "workspace")
    base.mkdir(parents=True, exist_ok=True)
    return base


def allow_absolute() -> bool:
    """Whether absolute / workspace-escaping paths are permitted (off by default)."""
    return os.environ.get("ASEPRITE_MCP_ALLOW_ABSOLUTE", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def resolve(filename: str) -> Path:
    """Resolve a user-supplied filename to an absolute path, sandboxed to the workspace.

    By default the file capability is scoped to the workspace: relative paths only,
    and any path that escapes the workspace (absolute, or via ``..``) is rejected.
    Set ASEPRITE_MCP_ALLOW_ABSOLUTE=1 to opt out and allow arbitrary paths.

    Parent directories are created so saves never fail on a missing folder.
    """
    ws = workspace().resolve()
    p = Path(filename).expanduser()
    permissive = allow_absolute()

    if p.is_absolute():
        if not permissive:
            raise WorkspaceError(
                f"Absolute paths are disabled. Use a path relative to the workspace "
                f"({ws}), or set ASEPRITE_MCP_ALLOW_ABSOLUTE=1 to allow absolute paths."
            )
        full = p
    else:
        full = (ws / p).resolve()
        if not permissive:
            try:
                full.relative_to(ws)
            except ValueError:
                raise WorkspaceError(
                    f"Path '{filename}' escapes the workspace ({ws}). Remove '..' "
                    f"segments, or set ASEPRITE_MCP_ALLOW_ABSOLUTE=1 to allow it."
                ) from None

    full.parent.mkdir(parents=True, exist_ok=True)
    return full


# Per-invocation timeout bounds. A timeout is a safety device: a value of 0 or a
# negative number would make every call fail instantly, and inf/NaN would disable
# the guard entirely, so both ends are clamped rather than honoured.
DEFAULT_TIMEOUT = 90.0
MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 3600.0


def timeout() -> float:
    """Per-invocation Aseprite timeout in seconds, clamped to [MIN_TIMEOUT, MAX_TIMEOUT].

    An unset, unparseable, or non-finite ASEPRITE_MCP_TIMEOUT falls back to
    DEFAULT_TIMEOUT; anything outside the range is clamped to the nearest bound.
    """
    raw = os.environ.get("ASEPRITE_MCP_TIMEOUT")
    if raw is None or raw.strip() == "":
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    if value != value or value in (float("inf"), float("-inf")):  # NaN / +-inf
        return DEFAULT_TIMEOUT
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, value))
