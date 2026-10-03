"""Frame management for animation: add, duplicate, remove, set durations."""

from __future__ import annotations

from ..app import mcp
from ..core import frameops
from ..core.errors import ValidationFailed
from ..core.limits import MAX_MOTION_FRAMES, check_list_length
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.runner import run_lua
from .common import lua_path, resolve_path

# Reordering goes through Aseprite's ReverseFrames command, which acts on the timeline
# selection and moves whole frames: every layer's cel, and the frame's duration with it.
# There is no move command to use instead, so a move is expressed as two reversals.
_REORDER_LUA = """
local function reverse_span(first, last)
  if last <= first then return end
  local list = {}
  for f = first, last do list[#list + 1] = f end
  app.range.frames = list
  app.command.ReverseFrames()
end

local function tag_summary(spr)
  local out = {}
  for i, tg in ipairs(spr.tags) do
    out[i] = { name = tg.name, from = tg.fromFrame.frameNumber,
               to = tg.toFrame.frameNumber }
  end
  return out
end
"""


@mcp.tool()
def add_frame(
    filename: str,
    duration_ms: int = 100,
    copy_from: int | None = None,
) -> dict:
    """Add a frame: appended when it is empty, inserted when it copies another.

    Args:
        duration_ms: Frame duration in milliseconds (default 100).
        copy_from: If given (1-based), duplicate the content of that frame; otherwise the
            new frame is empty and goes at the end. Must name an existing frame: an
            out-of-range number is rejected, not clamped. **A copy is inserted, not
            appended**, so every frame from that point on is renumbered: on a two-frame
            sprite, `copy_from=1` gives three frames whose second is the original first.
            Pass no `copy_from` and the sprite's existing frames keep their numbers.

    Returns the new frame number and updated frame count. With `copy_from`, `newFrame` is
    where the copy landed, which is also the number the frames after it shifted from.
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


@mcp.tool()
def reverse_frames(
    filename: str,
    tag: str | None = None,
    frames: list[int] | None = None,
) -> dict:
    """Reverse the order of a run of frames, keeping their timing with them.

    Reversing a walk to get its mirror, or a grow to get a shrink, is a normal move and
    otherwise means re-authoring the whole thing. Whole frames move: every layer's cel
    travels together, and each frame keeps its own duration.

    Args:
        tag: Reverse one tag's frames.
        frames: Reverse these frames instead. They must be one unbroken run, because
            Aseprite reverses everything between the first and the last: a gapped list
            would silently take in the frames in between.

    Defaults to the whole sprite when neither is given.

    **Tags mark positions, not pictures.** A tag over the reversed frames keeps its own
    range and now covers them in their new order, which is usually what was wanted for a
    tag that spans the whole run and rarely what was wanted for one that spans part of
    it. The result lists every tag that overlapped, so the ones worth revisiting are
    named rather than left to be discovered later.
    """
    if tag is not None and frames is not None:
        raise ValidationFailed(
            "give either tag or frames, not both: a tag already names its frames."
        )
    span = None
    if frames is not None:
        check_list_length("frames", frames, MAX_MOTION_FRAMES,
                          remedy="Reverse fewer frames per call.")
        numbered = [FrameRef.arg(f"frames[{i}]", f) for i, f in enumerate(frames)]
        try:
            span = frameops.check_contiguous(numbered)
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        if span[0] == span[1]:
            raise ValidationFailed(
                "frames needs at least two frames to reverse; one frame is already in "
                "the only order it has."
            )

    args = {
        "src": lua_path(resolve_path(filename)),
        "tag": tag,
        "first": span[0] if span else None,
        "last": span[1] if span else None,
    }
    body = FRAME_GUARD_LUA + _REORDER_LUA + """
    local spr = open_sprite(ARG.src)
    local first, last = ARG.first, ARG.last
    local tag_name = nil
    if ARG.tag ~= nil then
      local found = nil
      for _, t in ipairs(spr.tags) do if t.name == ARG.tag then found = t end end
      if found == nil then error("No tag named '" .. tostring(ARG.tag) .. "'", 0) end
      first, last = found.fromFrame.frameNumber, found.toFrame.frameNumber
      tag_name = found.name
    end
    if first == nil then first, last = 1, #spr.frames end
    first = require_frame(spr, first, "first frame")
    last = require_frame(spr, last, "last frame")
    if last <= first then
      error("There is nothing to reverse: the range covers one frame.", 0)
    end

    local before = tag_summary(spr)
    reverse_span(first, last)
    save_sprite(spr)
    RESULT = { ok = true, first = first, last = last, tag = tag_name,
               frame_count = #spr.frames, tags = before }
    """
    result = run_lua(body, args)
    touched = frameops.tags_touching(result["tags"], result["first"], result["last"])
    return {
        "ok": True,
        "first": result["first"],
        "last": result["last"],
        "tag": result.get("tag"),
        "frames_reversed": result["last"] - result["first"] + 1,
        "frame_count": result["frame_count"],
        "tags_affected": touched,
    }


@mcp.tool()
def move_frame(filename: str, frame: int, to: int) -> dict:
    """Move one frame to another position, taking its cels and its duration with it.

    Fixing an ordering mistake otherwise means deleting and redrawing. Nothing is copied:
    the frame keeps its identity, so linked cels stay linked.

    Args:
        frame: The frame to move, 1-based.
        to: Where it should end up, 1-based, in the numbering *after* the move. Moving
            frame 2 to 5 on a six-frame sprite gives 1, 3, 4, 5, 2, 6.

    **Tags mark positions, not pictures.** A tag between the two positions keeps its own
    range and now covers a different set of drawings. The result names every tag that
    overlapped the frames in between, because that is the part worth checking and it is
    invisible in the frame count.
    """
    first = FrameRef.arg("frame", frame)
    target = FrameRef.arg("to", to)
    if first == target:
        raise ValidationFailed(
            f"frame and to are both {first}; the frame is already there. Give the "
            "position it should end up in."
        )
    reversals = frameops.rotation_reversals(first, target)

    args = {
        "src": lua_path(resolve_path(filename)),
        "frame": first,
        "to": target,
        "reversals": [{"first": a, "last": b} for a, b in reversals],
    }
    body = FRAME_GUARD_LUA + _REORDER_LUA + """
    local spr = open_sprite(ARG.src)
    require_frame(spr, ARG.frame, "frame")
    require_frame(spr, ARG.to, "to")

    local before = tag_summary(spr)
    -- A move is a rotation of the block between the two positions, and a rotation is the
    -- block reversed then all but the frame that has arrived reversed again.
    for _, step in ipairs(ARG.reversals) do reverse_span(step.first, step.last) end
    save_sprite(spr)
    RESULT = { ok = true, frame_count = #spr.frames, tags = before }
    """
    result = run_lua(body, args)
    low, high = min(first, target), max(first, target)
    return {
        "ok": True,
        "frame": first,
        "to": target,
        "frame_count": result["frame_count"],
        "tags_affected": frameops.tags_touching(result["tags"], low, high),
    }
