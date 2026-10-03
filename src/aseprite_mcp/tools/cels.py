"""Cel-level operations: inspect, reposition, opacity, z-index, copy, link, delete,
plus the custom-property store every object in a sprite carries.

A *cel* is the image of one layer at one frame. Frames and layers are 1-based.

The property tools (`set_properties`, `get_properties`) live here rather than in a module
of their own because a cel is one of the six kinds of object that carry properties, and
because the two that are hardest to address, a cel and a tile, are both reached through a
layer and a frame the way everything else in this module is.

Every `frame` argument here must name a frame that already exists: an out-of-range
number is rejected with the sprite's valid range rather than clamped into it, so the
frame reported back is always the frame acted on.

Several frames can share one image rather than each holding a copy, which is how a held
pose is authored: editing any of them edits all of them, and the file stores the image
once. `get_cel` reports which frames a cel shares its image with, `link_cels` makes that
sharing, and `unlink_cels` gives a frame its own copy back.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from ..app import mcp
from ..core import metadata
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
        -- Reported so `set_cel_z_index` has something to be read back against: a
        -- z-index that is only visible by rendering the frame is one a caller cannot
        -- confirm. 0 means "wherever this cel's layer sits in the stack".
        z_index = cel.zIndex,
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


# The render order a z-index competes in, measured where the cels are.
#
# `zIndex` offsets a cel within its layer's *parent* stack, so a layer inside a group is
# ordered against that group's other children and not against the whole sprite: measured,
# a grouped layer's stackIndex is 1 inside its group while a top-level layer's is its
# position in the sprite. Reporting the siblings is therefore both the useful scope and
# the only one that is correct.
#
# Aseprite draws a cel at `stackIndex + zIndex`, and when two cels land on the same number
# the one with the larger zIndex draws later. Measured on two overlapping full-canvas
# layers: with no z-index the upper layer shows; the lower layer at z = +1 covers it; the
# upper layer at z = -1 is covered by it; and with both at z = +1 the upper one shows
# again.
_RENDER_ORDER_LUA = r"""
local function render_order(spr, layer, framenum)
  local rows = {}
  for _, lyr in ipairs(layer.parent.layers) do
    local cel = (not lyr.isGroup) and lyr:cel(framenum) or nil
    if cel ~= nil then
      rows[#rows + 1] = { layer = lyr.name, z_index = cel.zIndex,
                          draws_at = lyr.stackIndex + cel.zIndex }
    end
  end
  table.sort(rows, function(a, b)
    if a.draws_at ~= b.draws_at then return a.draws_at < b.draws_at end
    return a.z_index < b.z_index
  end)
  return rows
end
"""


@mcp.tool()
def set_cel_z_index(filename: str, layer: str, frame: int, z: int) -> dict:
    """Reorder one cel against the other cels in its frame, without moving any layer.

    This is the fix for "the arm is in front of the body this frame and behind it the
    next". The alternatives are to restructure the layer stack, which changes every other
    frame too, or to duplicate the arm onto a second layer and hide one of them per
    frame; a z-index is per cel, so it says exactly what it means and only where it
    applies.

    `z` is an offset, not a position: 0 (the default for every cel) means "wherever this
    cel's layer sits in the stack", a positive number moves the cel towards the front and
    a negative one towards the back. A cel draws at its layer's stack position plus `z`,
    and when two cels land on the same number the one with the larger `z` draws in front.
    So `z=1` on a cel one layer below another is enough to put it in front of that one.

    The ordering is scoped to the layer's siblings: a layer inside a group is ordered
    against that group's other layers, and the group as a whole keeps its place. Returns
    `order`, the frame's competing cels back to front, which is the part a caller cannot
    see for themselves.

    A z-index is per cel even when the cel is linked: two frames sharing one image share
    their opacity and their properties, and do not share this. Verified against the
    editor, because the opposite is the reasonable guess.

    `z` must be between -32768 and 32767. The editor accepts a larger number in memory
    and then stores it in a 16-bit field, so saving and reopening would silently turn it
    into a different one, usually of the opposite sign.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": FrameRef.arg("frame", frame),
        "z": metadata.check_z_index(z),
    }
    body = FRAME_GUARD_LUA + _RENDER_ORDER_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = require_frame(spr, ARG.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then
      error("layer '" .. layer.name .. "' has no cel at frame " .. n ..
            ", so there is nothing there to reorder", 0)
    end
    cel.zIndex = ARG.z
    save_sprite(spr)
    -- Read back off the cel rather than echoed from ARG: the setter is the only thing
    -- that knows whether the editor took the number as given.
    RESULT = { ok = true, layer = layer.name, frame = n, z_index = cel.zIndex,
               order = render_order(spr, layer, n) }
    """
    return run_lua(body, args)


# --------------------------------------------------------------- custom properties
def _coerce_property_value(value: object) -> object:
    """JSON-encode a structured property value; hand anything else on untouched.

    Some clients parse a JSON-looking argument before the server ever sees it, so a
    hitbox sent as `{"x": 8, "y": 15}` arrives as a dict at a parameter declared `str`
    and is refused. Encoding it here keeps the advertised wire type a plain string (a
    parameter with no concrete type is the one thing strict function-calling clients
    cannot use) while the value still arrives; `core.metadata.parse_property_value` then
    reads it back to the structure the caller meant.

    A number or a boolean is encoded for the same reason, and comes back out as a number
    or a boolean because its JSON text parses as one.
    """
    if isinstance(value, (dict, list, bool, int, float)):
        return metadata.encode_property_value(value)
    return value


PropertyValue = Annotated[str | None, BeforeValidator(_coerce_property_value)]
"""A property value as a parameter: a string on the wire, leniently fed."""


# Resolving one of the six kinds of object that carry properties. Which selectors a kind
# needs is decided in `core.metadata`, in Python, where it is unit-tested without an
# editor; this only has to find the object or say why it cannot.
_PROPERTY_TARGET_LUA = r"""
local function known_names(names)
  if #names == 0 then return "none" end
  return "'" .. table.concat(names, "', '") .. "'"
end

local function find_property_target(spr, sel)
  local kind = sel.target
  if kind == "sprite" then
    return spr, "sprite"
  elseif kind == "layer" then
    local lyr = find_layer(spr, sel.layer)
    return lyr, "layer '" .. lyr.name .. "'"
  elseif kind == "cel" then
    local lyr = find_layer(spr, sel.layer)
    local n = require_frame(spr, sel.frame, "frame")
    local cel = lyr:cel(n)
    if cel == nil then
      error("layer '" .. lyr.name .. "' has no cel at frame " .. n ..
            ", so there is nothing there to carry a property", 0)
    end
    return cel, "cel on layer '" .. lyr.name .. "' at frame " .. n
  elseif kind == "tag" then
    local names = {}
    for _, tg in ipairs(spr.tags) do
      if tg.name == sel.name then return tg, "tag '" .. tg.name .. "'" end
      names[#names + 1] = tg.name
    end
    error("no tag named '" .. tostring(sel.name) .. "'; the sprite has: " ..
          known_names(names), 0)
  elseif kind == "slice" then
    local names = {}
    for _, sl in ipairs(spr.slices) do
      if sl.name == sel.name then return sl, "slice '" .. sl.name .. "'" end
      names[#names + 1] = sl.name
    end
    error("no slice named '" .. tostring(sel.name) .. "'; the sprite has: " ..
          known_names(names), 0)
  end
  local lyr = find_layer(spr, sel.layer)
  if not lyr.isTilemap then
    error("layer '" .. lyr.name .. "' is not a tilemap layer, so it has no tileset and " ..
          "no tiles to put a property on", 0)
  end
  local tile = lyr.tileset:tile(sel.tile)
  if tile == nil then
    error("tile " .. sel.tile .. " does not exist; the tileset of layer '" .. lyr.name ..
          "' holds " .. #lyr.tileset .. " tile(s), numbered 0-" .. (#lyr.tileset - 1) ..
          ", where 0 is the empty tile", 0)
  end
  return tile, "tile " .. sel.tile .. " of layer '" .. lyr.name .. "'"
end

-- The group to read or write: the unnamed one, or a namespace.
local function property_group(obj, ns)
  if ns == nil then return obj.properties end
  return obj.properties(ns)
end

-- A property value as something json_encode can carry. Aseprite stores a few types JSON
-- has no form for (a Point, a Rectangle, a UUID), and json_encode answers "null" for a
-- type it does not recognise, which would report a property that exists as one that does
-- not. Stringified instead, so the reader at least sees that something is there.
local function jsonable(v, depth)
  local tp = type(v)
  if tp == "table" then
    -- The same depth `core.metadata.MAX_PROPERTY_DEPTH` refuses on the way in. Repeated
    -- here because this reads values the editor or another tool wrote, which were never
    -- held to it.
    if depth > 8 then return "<nested deeper than this report goes>" end
    local out = {}
    for k, item in pairs(v) do
      -- A numeric key stays numeric. json_encode reads a table whose keys are 1..n as a
      -- JSON array, so stringifying them turned a stored list into an object keyed
      -- "1", "2", "3": a damage-frame list written as [2, 5] came back as {"1": 2,
      -- "2": 5} and no longer matched what was stored.
      local key = (type(k) == "number") and k or tostring(k)
      out[key] = jsonable(item, depth + 1)
    end
    return out
  elseif tp == "userdata" or tp == "function" then
    return tostring(v)
  end
  return v
end

local function read_group(obj, ns)
  local out, n = {}, 0
  for k, v in pairs(property_group(obj, ns)) do
    out[tostring(k)] = jsonable(v, 0)
    n = n + 1
  end
  return out, n
end

-- Which other frames a cel property write also reached. Properties live on the record a
-- linked cel shares, so writing one on a held pose writes it on every frame of the hold:
-- measured, a property set on frame 1 of a linked pair reads back from frame 2. Reported
-- rather than refused, because that is what linking means, but a result saying
-- `frame: 1` while four frames changed is not telling the caller what happened.
local function frames_sharing_cel(spr, sel)
  local out = {}
  if sel.target ~= "cel" then return out end
  local lyr = find_layer(spr, sel.layer)
  local n = require_frame(spr, sel.frame, "frame")
  local cel = lyr:cel(n)
  if cel == nil then return out end
  for f = 1, #spr.frames do
    local other = lyr:cel(f)
    if f ~= n and other ~= nil and other.image.id == cel.image.id then
      out[#out + 1] = f
    end
  end
  return out
end
"""


def _property_args(
    filename: str,
    target: str,
    *,
    layer: str | None,
    frame: int | None,
    name: str | None,
    tile: int | None,
    namespace: str | None,
) -> dict:
    """The validated ARG table shared by the property reader and writer."""
    selector = metadata.resolve_property_target(
        target, layer=layer, frame=frame, name=name, tile=tile
    )
    if "frame" in selector:
        selector["frame"] = FrameRef.arg("frame", selector["frame"])
    return {
        "src": lua_path(resolve_path(filename)),
        "sel": selector,
        "ns": metadata.normalise_namespace(namespace),
    }


def _as_mapping(value: object) -> dict:
    """An empty property group reaches Python as `[]`, because a Lua table has one shape
    for both and the JSON encoder reads an empty one as an array. Normalized here so
    `properties` is always an object to a caller."""
    return value if isinstance(value, dict) else {}


@mcp.tool()
def set_properties(
    filename: str,
    target: str,
    key: str,
    value: PropertyValue = None,
    layer: str | None = None,
    frame: int | None = None,
    name: str | None = None,
    tile: int | None = None,
    namespace: str | None = None,
    as_json: bool = False,
    delete: bool = False,
) -> dict:
    """Store a custom property on an object inside the sprite, in the .aseprite file.

    This is where game metadata belongs: a hitbox on a slice, an anchor point on a layer,
    "this frame deals damage" on a cel, a surface kind on a tile. It travels with the art
    instead of living in a sidecar file that the next edit desynchronises, and the editor
    shows it and keeps it.

    Args:
        target: Which kind of object: "sprite", "layer", "cel", "tag", "slice" or "tile".
        key: The property name, e.g. "hitbox".
        value: What to store. Text by default, so value="7" stores the two-character
            string "7". Pass as_json=True to store a number, a boolean or a structure:
            then "7" stores the number 7, "true" stores a boolean, and
            '{"x": 8, "y": 15}' stores a table. A value that begins like a JSON object or
            array is read as JSON either way, since there is no other reading of one.
        layer: The layer's name. Needed for target "layer", "cel" and "tile".
        frame: 1-based frame number, for target "cel" (default: the first frame).
        name: The tag's or slice's name, for target "tag" and "slice".
        tile: An index into the layer's tileset, for target "tile". 0 is the empty tile.
        namespace: Keep the property in a named group rather than in the unnamed one the
            editor's own property panel uses. Two tools can then both use the key
            "anchor" without colliding. Namespaces cannot be listed back, so a caller has
            to know the name to read one again.
        as_json: Parse `value` as JSON before storing it (see `value`).
        delete: Remove the property instead of setting it. `value` is then ignored, and
            removing a key that was not there is not an error.

    A selector the target does not use is refused rather than ignored, because the
    property would otherwise land on a different object than the one that was named.

    Properties live on the record that linked cels share, so setting one on a held pose
    sets it on every frame of the hold. The result says which frames those were.

    Returns the whole property group after the write, so the stored value is visible as
    the type it was stored as.
    """
    args = _property_args(
        filename, target,
        layer=layer, frame=frame, name=name, tile=tile, namespace=namespace,
    )
    args["key"] = metadata.check_property_key(key)
    args["delete"] = bool(delete)
    args["value"] = (
        None if delete else metadata.parse_property_value(value, as_json=bool(as_json))
    )
    body = FRAME_GUARD_LUA + _PROPERTY_TARGET_LUA + """
    local spr = open_sprite(ARG.src)
    local obj, described = find_property_target(spr, ARG.sel)
    local shared = frames_sharing_cel(spr, ARG.sel)
    local group = property_group(obj, ARG.ns)
    if ARG.delete then
      group[ARG.key] = nil
    else
      -- ARG.value cannot be nil here: a nil would be indistinguishable from a delete,
      -- and Python refuses the value that would produce one.
      group[ARG.key] = ARG.value
    end
    save_sprite(spr)
    local props, count = read_group(obj, ARG.ns)
    RESULT = { ok = true, target = ARG.sel.target, on = described, key = ARG.key,
               deleted = ARG.delete, properties = props, count = count }
    if ARG.ns ~= nil then RESULT.namespace = ARG.ns end
    if #shared > 0 then RESULT.linked_frames_also_changed = shared end
    """
    result = run_lua(body, args)
    result["properties"] = _as_mapping(result.get("properties"))
    return result


@mcp.tool()
def get_properties(
    filename: str,
    target: str,
    layer: str | None = None,
    frame: int | None = None,
    name: str | None = None,
    tile: int | None = None,
    namespace: str | None = None,
) -> dict:
    """Read the custom properties stored on one object inside the sprite.

    The counterpart to `set_properties`, and the only way to read that metadata back:
    neither `get_sprite_info` nor the sprite-sheet export reports custom properties.

    Args:
        target, layer, frame, name, tile: Which object, exactly as `set_properties`
            takes them.
        namespace: Read a named group instead of the unnamed one. Aseprite offers no way
            to list the namespaces an object has, so a group can only be read by a caller
            who knows its name; an unknown name reads as empty rather than as an error.

    Returns `properties` as an object of key to value, each value in the type it was
    stored as. A value of a type JSON cannot describe (the editor can store a point or a
    rectangle) is reported as text rather than dropped.
    """
    args = _property_args(
        filename, target,
        layer=layer, frame=frame, name=name, tile=tile, namespace=namespace,
    )
    body = FRAME_GUARD_LUA + _PROPERTY_TARGET_LUA + """
    local spr = open_sprite(ARG.src)
    local obj, described = find_property_target(spr, ARG.sel)
    local props, count = read_group(obj, ARG.ns)
    RESULT = { target = ARG.sel.target, on = described, properties = props,
               count = count }
    if ARG.ns ~= nil then RESULT.namespace = ARG.ns end
    """
    result = run_lua(body, args)
    result["properties"] = _as_mapping(result.get("properties"))
    return result
