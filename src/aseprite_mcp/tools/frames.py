"""Frame management for animation: add, duplicate, remove, set durations."""

from __future__ import annotations

from ..app import mcp
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.runner import run_lua
from .common import lua_path, resolve_path


@mcp.tool()
def add_frame(
    filename: str,
    duration_ms: int = 100,
    copy_from: int | None = None,
) -> dict:
    """Append a new frame to the animation.

    Args:
        duration_ms: Frame duration in milliseconds (default 100).
        copy_from: If given (1-based), duplicate the content of that frame;
            otherwise the new frame is empty. Must name an existing frame -- an
            out-of-range number is rejected, not clamped.

    Returns the new frame number and updated frame count.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "duration_ms": int(duration_ms),
        "copy_from": None if copy_from is None else FrameRef.arg("copy_from", copy_from),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local fr
    if ARG.copy_from ~= nil then
      fr = spr:newFrame(require_frame(spr, ARG.copy_from, "copy_from"))
    else
      fr = spr:newEmptyFrame(#spr.frames + 1)
    end
    fr.duration = ARG.duration_ms / 1000.0
    save_sprite(spr)
    RESULT = { ok = true, newFrame = fr.frameNumber, frameCount = #spr.frames }
    """
    return run_lua(body, args)


@mcp.tool()
def duplicate_frame(filename: str, frame: int) -> dict:
    """Duplicate an existing frame (1-based); the copy is inserted after it.

    `frame` must already exist: an out-of-range number is rejected with the sprite's
    valid range rather than clamped to it.
    """
    args = {"src": lua_path(resolve_path(filename)), "frame": FrameRef.arg("frame", frame)}
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local fr = spr:newFrame(require_frame(spr, ARG.frame, "frame"))
    save_sprite(spr)
    RESULT = { ok = true, newFrame = fr.frameNumber, frameCount = #spr.frames }
    """
    return run_lua(body, args)


@mcp.tool()
def remove_frame(filename: str, frame: int) -> dict:
    """Delete a frame (1-based). The sprite must have more than one frame.

    `frame` must already exist: an out-of-range number is rejected with the sprite's
    valid range rather than clamped to it (which used to delete a different frame).
    """
    args = {"src": lua_path(resolve_path(filename)), "frame": FrameRef.arg("frame", frame)}
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    if #spr.frames <= 1 then error("Cannot delete the only frame.", 0) end
    spr:deleteFrame(require_frame(spr, ARG.frame, "frame"))
    save_sprite(spr)
    RESULT = { ok = true, frameCount = #spr.frames }
    """
    return run_lua(body, args)


@mcp.tool()
def set_frame_duration(filename: str, frame: int, duration_ms: int) -> dict:
    """Set a single frame's duration in milliseconds (1-based frame).

    `frame` must already exist: an out-of-range number is rejected with the sprite's
    valid range rather than clamped to it (which used to report the requested number
    while changing frame 1).
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "frame": FrameRef.arg("frame", frame),
        "duration_ms": int(duration_ms),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local n = require_frame(spr, ARG.frame, "frame")
    spr.frames[n].duration = ARG.duration_ms / 1000.0
    save_sprite(spr)
    RESULT = { ok = true, frame = n, duration_ms = ARG.duration_ms }
    """
    return run_lua(body, args)


@mcp.tool()
def set_all_frame_durations(filename: str, duration_ms: int) -> dict:
    """Set every frame's duration in milliseconds (uniform animation speed)."""
    args = {"src": lua_path(resolve_path(filename)), "duration_ms": int(duration_ms)}
    body = """
    local spr = open_sprite(ARG.src)
    for _, fr in ipairs(spr.frames) do fr.duration = ARG.duration_ms / 1000.0 end
    save_sprite(spr)
    RESULT = { ok = true, frameCount = #spr.frames, duration_ms = ARG.duration_ms }
    """
    return run_lua(body, args)
