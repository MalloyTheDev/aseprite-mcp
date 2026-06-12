"""Locating the Aseprite executable, the workspace directory, and run settings.

All of these can be overridden with environment variables so the same server
works on any machine:

    ASEPRITE_PATH            Absolute path to Aseprite.exe (or `aseprite` binary).
    ASEPRITE_MCP_WORKSPACE   Directory where relative sprite paths are resolved.
    ASEPRITE_MCP_TIMEOUT     Per-invocation timeout in seconds (default 90).
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

_cached_exe: str | None = None


def find_aseprite() -> str:
    """Return the path to the Aseprite executable, or raise AsepriteNotFoundError
    (which is also a FileNotFoundError, for backwards compatibility)."""
    global _cached_exe
    if _cached_exe and Path(_cached_exe).exists():
        return _cached_exe

    env = os.environ.get("ASEPRITE_PATH")
    if env:
        if Path(env).exists():
            _cached_exe = env
            return env
        raise AsepriteNotFoundError(
            f"ASEPRITE_PATH is set to '{env}' but no file exists there."
        )

    on_path = shutil.which("aseprite") or shutil.which("Aseprite")
    if on_path:
        _cached_exe = on_path
        return on_path

    for candidate in _CANDIDATES:
        if Path(candidate).exists():
            _cached_exe = candidate
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


def timeout() -> float:
    try:
        return float(os.environ.get("ASEPRITE_MCP_TIMEOUT", "90"))
    except ValueError:
        return 90.0
