"""GUI companion mode.

Opens sprites in the real Aseprite GUI window so a human can watch the work.
Because Aseprite's scripting sandbox has no networking or timers, the server can't
*stream* a live canvas into the GUI. Instead it relies on Aseprite's
"file changed on disk" detection: open the file once, keep editing it headlessly
with the other tools, and Aseprite will offer to reload when the file changes.

The GUI is launched **detached** (non-blocking) so it keeps running across tool calls.
"""

from __future__ import annotations

import os
import subprocess

from ..core import config
from ..app import mcp
from ..core.runner import AsepriteError
from .common import resolve_path


@mcp.tool()
def gui_available() -> dict:
    """Check whether the Aseprite GUI can be launched (executable resolvable)."""
    try:
        exe = config.find_aseprite()
        return {"available": True, "executable": exe}
    except FileNotFoundError as exc:
        return {"available": False, "reason": str(exc)}


@mcp.tool()
def open_in_editor(filename: str) -> dict:
    """Open a sprite in the Aseprite GUI window (non-blocking) for live viewing.

    The window stays open and runs independently of this server. Keep editing the
    file with the other tools — Aseprite detects the on-disk change and prompts to
    reload (or reloads automatically, depending on your Aseprite preferences), so
    you can watch edits land without re-opening.

    Returns the launched process id. To stop watching, just close the Aseprite
    window yourself.
    """
    path = resolve_path(filename)
    if not path.exists():
        raise AsepriteError(
            f"No such sprite: {path}. Create or save it first, then open_in_editor."
        )
    exe = config.find_aseprite()

    popen_kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        # Detach so the GUI survives this server process and never blocks.
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen([exe, str(path)], **popen_kwargs)
    except OSError as exc:
        raise AsepriteError(f"Failed to launch Aseprite GUI: {exc}") from exc

    return {
        "ok": True,
        "opened": str(path),
        "pid": proc.pid,
        "note": (
            "Aseprite is now showing this file. As you save further edits with other "
            "tools, Aseprite will prompt to reload (or auto-reloads per your settings). "
            "Close the window when done."
        ),
    }
