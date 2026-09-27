"""Locating the Aseprite executable, the workspace directory, and run settings.

All of these can be overridden with environment variables so the same server
works on any machine:

    ASEPRITE_PATH            Absolute path to Aseprite.exe (or `aseprite` binary).
    ASEPRITE_MCP_WORKSPACE   Directory where relative sprite paths are resolved. Unset,
                             it defaults to `<repo>/workspace` from a source checkout and
                             to a per-user data directory otherwise (see
                             `_source_checkout_root`), never to a path inside the Python
                             installation.
    ASEPRITE_MCP_TIMEOUT     Per-invocation timeout in seconds (default 90). A numeric
                             value outside 1-3600 is clamped to the nearest bound; an
                             unparseable, empty or non-finite value falls back to the
                             default. Neither case can disable the timeout.
    ASEPRITE_MCP_ALLOW_ABSOLUTE  Set to 1/true to permit absolute paths and paths
                             that escape the workspace. Off by default (sandboxed).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .errors import AsepriteNotFoundError, WorkspaceError

# Project root = three levels up (src/aseprite_mcp/core/config.py -> repo root).
# Only meaningful in a source checkout; see `_source_checkout_root` for why the
# workspace default no longer trusts this arithmetic on an installed package.
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


def _source_checkout_root(module_file: str | Path | None = None) -> Path | None:
    """Repo root when this module is running from a `src/` checkout, else None.

    `PROJECT_ROOT` is `parents[3]` of this file, which is the repo root only for the
    `src/aseprite_mcp/core/config.py` layout. `pyproject.toml` ships an `aseprite-mcp`
    console script, so `uvx aseprite-mcp` is the normal setup for anyone who has not
    cloned the repo, and there the same arithmetic points *inside* the Python
    installation: `<venv>/Lib/workspace` on Windows, `/usr/lib/python3.12/workspace`
    on POSIX. Sprites written there are invisible to the user at best and a bare
    `PermissionError` at worst, so the sibling default is used only when the layout is
    genuinely a checkout.

    `module_file` exists so the installed layout can be simulated in a test instead of
    asserting on whatever layout the test run happens to use.
    """
    here = Path(module_file if module_file is not None else __file__).resolve()
    if len(here.parents) < 4:
        return None
    root = here.parents[3]
    # Both halves matter: a `src` directory name alone could occur inside a site-packages
    # tree, and pyproject.toml alone is not shipped in a wheel.
    if here.parents[2].name == "src" and (root / "pyproject.toml").is_file():
        return root
    return None


def _per_user_workspace() -> Path:
    """Per-user data directory used when there is no source checkout to sit beside.

    Standard library only, by design: the platform conventions are three `os.environ`
    lookups, not worth a dependency.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "aseprite-mcp" / "workspace"


def default_workspace() -> Path:
    """Where relative paths resolve when ASEPRITE_MCP_WORKSPACE is unset."""
    root = _source_checkout_root()
    return (root / "workspace") if root is not None else _per_user_workspace()


def workspace() -> Path:
    """Directory where relative sprite filenames are resolved. Created if missing."""
    env = os.environ.get("ASEPRITE_MCP_WORKSPACE")
    base = Path(env) if env and env.strip() else default_workspace()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # A raw PermissionError here reaches the client as an untyped failure with no
        # remedy in it, which is exactly how sprites ended up aimed at site-packages.
        raise WorkspaceError(
            f"Cannot use '{base}' as the workspace: {exc}. Set ASEPRITE_MCP_WORKSPACE "
            "to a directory you can write to."
        ) from exc
    return base


def allow_absolute() -> bool:
    """Whether absolute / workspace-escaping paths are permitted (off by default)."""
    return os.environ.get("ASEPRITE_MCP_ALLOW_ABSOLUTE", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


# Windows device names. Opening one of these talks to the device instead of creating a
# file: a write to NUL is discarded and reported as a success (silent data loss with a
# positive result), and COM1/LPT1 on a machine where the port exists would block until
# the invocation timeout. The check is on the *stem* because whether `NUL.png` is
# device-mapped varies by Windows build, and nothing here can tell which behaviour the
# host has.
_RESERVED_DEVICE_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"COM{d}" for d in "0123456789"]
    + [f"LPT{d}" for d in "0123456789"]
)


def _check_component(component: str, filename: str) -> None:
    """Reject a path component that Windows interprets as something other than a file.

    Containment (`..`, absolute paths) is checked separately; this is about components
    that pass containment and then do not behave like the file the caller named. Gated on
    Windows because each of these is a legal POSIX filename, and rejecting them there
    would refuse work the sandbox has no reason to refuse.
    """
    if component in (".", ".."):
        return  # a navigation segment, not a name; containment handles these
    if os.name != "nt":
        return
    if component != component.rstrip(" ."):
        raise WorkspaceError(
            f"Path component {component!r} in '{filename}' ends with a space or a dot. "
            "Windows strips those when creating the file, so the path reported back to "
            "you would not be the path that exists on disk."
        )
    if ":" in component:
        raise WorkspaceError(
            f"Path component {component!r} in '{filename}' contains ':', which names an "
            "NTFS alternate data stream rather than a file. A stream is invisible to "
            "every listing and export tool here, so it is refused."
        )
    stem = component.split(".", 1)[0].rstrip(" ")
    if stem.upper() in _RESERVED_DEVICE_STEMS:
        raise WorkspaceError(
            f"Path component {component!r} in '{filename}' is the reserved Windows "
            f"device name {stem.upper()}. Writing to a device discards the data and "
            "still reports success, so the name is refused. Pick another filename."
        )


def resolve(filename: str, *, create_parent: bool = False) -> Path:
    """Resolve a user-supplied filename to an absolute path, sandboxed to the workspace.

    By default the file capability is scoped to the workspace: relative paths only,
    and any path that escapes the workspace (absolute, or via ``..``) is rejected.
    Set ASEPRITE_MCP_ALLOW_ABSOLUTE=1 to opt out and allow arbitrary paths.

    `create_parent` is off by default so a *read* creates nothing: resolving
    ``a/b/c/d/e/absent.png`` used to leave five directories behind whether or not the
    call went on to succeed, which let a caller build arbitrary trees inside the
    workspace out of nothing but failing calls. The output helpers in `core.paths` pass
    `create_parent=True` so saves still never fail on a missing folder.
    """
    ws = workspace().resolve()
    if not filename or not str(filename).strip():
        raise WorkspaceError(
            "No filename was given. Pass a path relative to the workspace "
            f"({ws}), e.g. 'sprites/hero.aseprite'."
        )
    # Rejected here, explicitly, rather than left to pathlib. Through Python 3.12 an
    # embedded NUL made `Path.resolve()` raise ValueError, so this failed closed as a
    # side effect; 3.13 resolves such a path without complaint and the sandbox then
    # returned it as accepted. A guard that holds only because of an implementation
    # detail of the standard library is not a guard, and this one had already stopped
    # holding on the newest interpreter the project supports.
    if "\x00" in str(filename):
        raise WorkspaceError(
            "Filenames may not contain a null byte. Remove it and use a plain path "
            f"relative to the workspace ({ws})."
        )
    p = Path(filename).expanduser()
    permissive = allow_absolute()

    if p.is_absolute() and not permissive:
        raise WorkspaceError(
            f"Absolute paths are disabled. Use a path relative to the workspace "
            f"({ws}), or set ASEPRITE_MCP_ALLOW_ABSOLUTE=1 to allow absolute paths."
        )

    # Skip the anchor ("C:\\", "/") so a drive letter's colon is not read as a stream.
    for component in p.parts[1:] if p.anchor else p.parts:
        _check_component(component, str(filename))

    try:
        # A relative path is joined to the workspace on both branches: permissive mode
        # widens what is *allowed*, it does not move the anchor to the process working
        # directory. Both branches canonicalise, though: skipping `.resolve()` under
        # ASEPRITE_MCP_ALLOW_ABSOLUTE handed back a path still containing '..' segments,
        # which then landed verbatim in manifests and in the mkdir below.
        full = p.resolve() if p.is_absolute() else (ws / p).resolve()
    except (OSError, ValueError) as exc:
        # An unusable name (embedded NUL, bad syntax) must still be a typed error.
        raise WorkspaceError(f"Path '{filename}' is not a usable filename: {exc}") from None

    if not permissive:
        try:
            full.relative_to(ws)
        except ValueError:
            raise WorkspaceError(
                f"Path '{filename}' escapes the workspace ({ws}). Remove '..' "
                f"segments, or set ASEPRITE_MCP_ALLOW_ABSOLUTE=1 to allow it."
            ) from None
        if full == ws:
            raise WorkspaceError(
                f"Path '{filename}' names the workspace directory itself, not a file "
                f"in it ({ws}). Include a filename."
            )

    if create_parent:
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(
                f"Cannot create the directory for '{full}': {exc}."
            ) from exc
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
