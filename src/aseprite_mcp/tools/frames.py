"""Frame management for animation: add, duplicate, remove, set durations."""

from __future__ import annotations

from ..app import mcp
from ..runner import run_lua
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
            otherwise the new frame is empty.

    Returns the new frame number and updated frame count.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "duration_ms": int(duration_ms),
        "copy_from": copy_from,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local fr
    if ARG.copy_from ~= nil then
      fr = spr:newFrame(clamp_frame(spr, ARG.copy_from))
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
    """Duplicate an existing frame (1-based); the copy is inserted after it."""
    args = {"src": lua_path(resolve_path(filename)), "frame": int(frame)}
    body = """
    local spr = open_sprite(ARG.src)
    local fr = spr:newFrame(clamp_frame(spr, ARG.frame))
    save_sprite(spr)
    RESULT = { ok = true, newFrame = fr.frameNumber, frameCount = #spr.frames }
    """
    return run_lua(body, args)


@mcp.tool()
def remove_frame(filename: str, frame: int) -> dict:
    """Delete a frame (1-based). The sprite must have more than one frame."""
    args = {"src": lua_path(resolve_path(filename)), "frame": int(frame)}
    body = """
    local spr = open_sprite(ARG.src)
    if #spr.frames <= 1 then error("Cannot delete the only frame.") end
    spr:deleteFrame(clamp_frame(spr, ARG.frame))
    save_sprite(spr)
    RESULT = { ok = true, frameCount = #spr.frames }
    """
    return run_lua(body, args)


@mcp.tool()
def set_frame_duration(filename: str, frame: int, duration_ms: int) -> dict:
    """Set a single frame's duration in milliseconds (1-based frame)."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "frame": int(frame),
        "duration_ms": int(duration_ms),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local n = clamp_frame(spr, ARG.frame)
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
