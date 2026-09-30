"""Cel-level operations: inspect, reposition, opacity, copy, link, delete.

A *cel* is the image of one layer at one frame. Frames and layers are 1-based.

Every `frame` argument here must name a frame that already exists: an out-of-range
number is rejected with the sprite's valid range rather than clamped into it, so the
frame reported back is always the frame acted on.

Several frames can share one image rather than each holding a copy, which is how a held
pose is authored: editing any of them edits all of them, and the file stores the image
once. `get_cel` reports which frames a cel shares its image with, `link_cels` makes that
sharing, and `unlink_cels` gives a frame its own copy back.
"""

from __future__ import annotations

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import MAX_MOTION_FRAMES, check_list_length
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.runner import run_lua
from .common import lua_path, resolve_path


def _frame_list(frames: list[int], field: str, *, minimum: int) -> list[int]:
    """Validate a list of frame numbers before anything is launched."""
    if len(frames) < minimum:
        raise ValidationFailed(
            f"{field} needs at least {minimum} frame(s); got {len(frames)}."
        )
    check_list_length(field, frames, MAX_MOTION_FRAMES,
                      remedy="Work on fewer frames per call.")
    numbered = [FrameRef.arg(f"{field}[{i}]", f) for i, f in enumerate(frames)]
    duplicates = sorted({f for f in numbered if numbered.count(f) > 1})
    if duplicates:
        raise ValidationFailed(f"{field} lists {duplicates} more than once.")
    return numbered


@mcp.tool()
def get_cel(filename: str, layer: str, frame: int = 1) -> dict:
    """Inspect a cel: whether it exists, its position, bounds, opacity, and links.

    `linked_with` lists the other frames sharing this cel's image, so a held pose is
    visible as what it is. An edit to any of them changes all of them.
    """
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frame": FrameRef.arg("frame", frame)}
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = require_frame(spr, ARG.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then
      RESULT = { exists = false, layer = layer.name, frame = n }
    else
      -- Image identity is what makes a cel linked. The id itself is per-session and
      -- means nothing to a caller, so report the frames it is shared with instead.
      local shared = {}
      for f = 1, #spr.frames do
        local other = layer:cel(f)
        if f ~= n and other ~= nil and other.image.id == cel.image.id then
          shared[#shared + 1] = f
        end
      end
      RESULT = {
        exists = true, layer = layer.name, frame = n,
        opacity = cel.opacity,
        position = { x = cel.position.x, y = cel.position.y },
        bounds = { x = cel.bounds.x, y = cel.bounds.y,
                   width = cel.bounds.width, height = cel.bounds.height },
        linked = #shared > 0,
        linked_with = shared,
      }
    end
    """
    return run_lua(body, args)


@mcp.tool()
def set_cel_position(filename: str, layer: str, frame: int, x: int, y: int) -> dict:
    """Move a cel's image to position (x, y) within the canvas."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": FrameRef.arg("frame", frame), "x": int(x), "y": int(y),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = require_frame(spr, ARG.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then error("No cel on layer '" .. layer.name .. "' at frame " .. n, 0) end
    cel.position = Point(ARG.x, ARG.y)
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = n,
               position = { x = cel.position.x, y = cel.position.y } }
    """
    return run_lua(body, args)


@mcp.tool()
def set_cel_opacity(filename: str, layer: str, frame: int, opacity: int) -> dict:
    """Set a cel's opacity (0-255)."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": FrameRef.arg("frame", frame),
        "opacity": max(0, min(255, int(opacity))),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = require_frame(spr, ARG.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then error("No cel on layer '" .. layer.name .. "' at frame " .. n, 0) end
    cel.opacity = ARG.opacity
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = n, opacity = cel.opacity }
    """
    return run_lua(body, args)


@mcp.tool()
def copy_cel(filename: str, layer: str, from_frame: int, to_frame: int) -> dict:
    """Copy a cel's image (and position) from one frame to another on the same layer."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "from": FrameRef.arg("from_frame", from_frame),
        "to": FrameRef.arg("to_frame", to_frame),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local a = require_frame(spr, ARG["from"], "from_frame")
    local b = require_frame(spr, ARG.to, "to_frame")
    local src_cel = layer:cel(a)
    if src_cel == nil then error("No cel to copy on layer '" .. layer.name .. "' at frame " .. a, 0) end
    local img = Image(src_cel.image)
    local dst = layer:cel(b)
    if dst ~= nil then
      dst.image = img
      dst.position = src_cel.position
    else
      spr:newCel(layer, b, img, src_cel.position)
    end
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, ["from"] = a, to = b }
    """
    return run_lua(body, args)


@mcp.tool()
def delete_cel(filename: str, layer: str, frame: int) -> dict:
    """Delete a cel (the layer becomes empty at that frame)."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frame": FrameRef.arg("frame", frame)}
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = require_frame(spr, ARG.frame, "frame")
    local cel = layer:cel(n)
    if cel ~= nil then spr:deleteCel(cel) end
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = n }
    """
    return run_lua(body, args)


# Frames sharing one image, reported as groups rather than as Aseprite's image ids: the
# ids are assigned per open and change on the next call, so they would look like state
# a caller could keep. Which frames move together is the fact that survives.
_GROUPS_LUA = """
local function link_groups(spr, layer)
  local groups, index = {}, {}
  for f = 1, #spr.frames do
    local cel = layer:cel(f)
    if cel ~= nil then
      local id = cel.image.id
      if index[id] == nil then
        groups[#groups + 1] = {}
        index[id] = #groups
      end
      local g = groups[index[id]]
      g[#g + 1] = f
    end
  end
  return groups
end
"""


@mcp.tool()
def link_cels(filename: str, layer: str, frames: list[int]) -> dict:
    """Make several frames share one image, which is how a held pose is authored.

    A linked cel is one image appearing on several frames: editing any of them edits all
    of them, and the file stores the image once instead of once per frame. Use it for a
    pose that genuinely repeats, such as the two extremes of a cycle that return to the
    same drawing.

    **The first listed frame's image is the one kept.** Every other listed frame loses
    whatever was drawn on it and shows the first frame's image instead, which is the point
    of linking and is not undoable from here, so check with `get_cel` first if the frames
    differ.

    To hold a pose for longer rather than to repeat a drawing, lengthen the frame instead
    (`set_frame_duration`, or `apply_timing_curve`): a duration costs nothing, while a
    repeated frame shifts every tag index.

    Returns the layer's link groups: the frames that now share an image, in groups.
    """
    numbered = _frame_list(frames, "frames", minimum=2)
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frames": numbered}
    body = FRAME_GUARD_LUA + _GROUPS_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local wanted = {}
    for i, f in ipairs(ARG.frames) do
      local n = require_frame(spr, f, "frames[" .. i .. "]")
      if layer:cel(n) == nil then
        error("layer '" .. tostring(ARG.layer) .. "' has no cel on frame " .. n ..
              "; there is nothing to link", 0)
      end
      wanted[i] = n
    end
    -- Aseprite links through the timeline selection, which exists headlessly too.
    app.range.layers = { layer }
    app.range.frames = wanted
    app.command.LinkCels()
    save_sprite(spr)
    RESULT = { layer = layer.name, frames = wanted, groups = link_groups(spr, layer) }
    """
    return run_lua(body, args)


@mcp.tool()
def unlink_cels(filename: str, layer: str, frames: list[int]) -> dict:
    """Give frames their own copy of a shared image again, so they can differ again.

    The reverse of `link_cels`: each listed frame keeps what it currently shows and stops
    following the others. Nothing is lost; the image is copied rather than moved.

    Returns the layer's link groups afterwards.
    """
    numbered = _frame_list(frames, "frames", minimum=1)
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frames": numbered}
    body = FRAME_GUARD_LUA + _GROUPS_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local wanted = {}
    for i, f in ipairs(ARG.frames) do
      local n = require_frame(spr, f, "frames[" .. i .. "]")
      if layer:cel(n) == nil then
        error("layer '" .. tostring(ARG.layer) .. "' has no cel on frame " .. n, 0)
      end
      wanted[i] = n
    end
    app.range.layers = { layer }
    app.range.frames = wanted
    app.command.UnlinkCel()
    save_sprite(spr)
    RESULT = { layer = layer.name, frames = wanted, groups = link_groups(spr, layer) }
    """
    return run_lua(body, args)
