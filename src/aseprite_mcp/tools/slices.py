"""Slices — named rectangular regions, with optional 9-patch center and pivot.

Slices are exported in sprite-sheet JSON data and are handy for UI atlases,
9-patch widgets, and marking sub-regions of a sprite.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import BeforeValidator

from ..app import mcp
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path


def _coerce_slice_data(value: object) -> object:
    """JSON-encode structured slice user-data; hand anything else on untouched.

    Aseprite stores `Slice.data` as a string, and `export_slice_metadata` parses it back,
    deriving a slice's `type` and `id` from it. So `{"type": "hitbox", "id": "body"}` is
    the useful shape to send, and two client behaviours stopped it arriving: an argument
    that looks like JSON is parsed into an object before the tool is called, and some
    clients send structured user-data as an object to begin with. Either way the value
    reached a parameter declared `str` as a dict, and was refused or dropped; the slice
    then carried no data at all and exported as `type: "custom"`, `id: null`.

    A non-dict, non-list value is returned unchanged so the ordinary `str | None`
    validation still applies to it: `data=5` is a mistake and stays an error.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


SliceData = Annotated[str | None, BeforeValidator(_coerce_slice_data)]
"""Slice user-data as a parameter: a string on the wire, leniently fed.

The advertised schema stays a plain string. Declaring the parameter as the union it
accepts would cost it its concrete type, and a parameter with no concrete type is the
one thing strict function-calling clients cannot use; the coercion runs before
validation instead, so the leniency costs no portability.
"""


@mcp.tool()
def add_slice(
    filename: str,
    name: str,
    x: int,
    y: int,
    width: int,
    height: int,
    center_x: int | None = None,
    center_y: int | None = None,
    center_width: int | None = None,
    center_height: int | None = None,
    pivot_x: int | None = None,
    pivot_y: int | None = None,
    color: str | None = None,
    data: SliceData = None,
) -> dict:
    """Create a slice (named region) at (x, y, width, height).

    Args:
        center_*: Optional 9-patch center rectangle, **relative to the slice's
            top-left**. Provide all four to mark the stretchable middle.
        pivot_*: Optional pivot point (relative to the slice).
        color: Optional slice colour shown in the editor.
        data: Optional user data. A string is stored as it arrives; a dict or list is
            JSON-encoded, so {"type": "hitbox", "id": "body"} round-trips through
            export_slice_metadata, which derives the slice's type and id from it.
    """
    center = None
    if None not in (center_x, center_y, center_width, center_height):
        center = {"x": int(center_x), "y": int(center_y),
                  "width": int(center_width), "height": int(center_height)}
    pivot = None
    if pivot_x is not None and pivot_y is not None:
        pivot = {"x": int(pivot_x), "y": int(pivot_y)}
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "x": int(x), "y": int(y), "width": int(width), "height": int(height),
        "center": center, "pivot": pivot,
        "color": parse_color(color) if color else None,
        "data": _coerce_slice_data(data),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local sl = spr:newSlice(Rectangle(ARG.x, ARG.y, ARG.width, ARG.height))
    sl.name = ARG.name
    if ARG.center ~= nil then
      sl.center = Rectangle(ARG.center.x, ARG.center.y, ARG.center.width, ARG.center.height)
    end
    if ARG.pivot ~= nil then sl.pivot = Point(ARG.pivot.x, ARG.pivot.y) end
    if ARG.color ~= nil then sl.color = mkcolor(ARG.color) end
    if ARG.data ~= nil then sl.data = ARG.data end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def set_slice(
    filename: str,
    name: str,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
    new_name: str | None = None,
    color: str | None = None,
    data: SliceData = None,
) -> dict:
    """Update an existing slice's bounds, name, colour, or data.

    data: a string is stored as it arrives; a dict or list is JSON-encoded, so structured
    user-data round-trips through export_slice_metadata.
    """
    bounds = None
    if None not in (x, y, width, height):
        bounds = {"x": int(x), "y": int(y), "width": int(width), "height": int(height)}
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name, "bounds": bounds, "new_name": new_name,
        "color": parse_color(color) if color else None, "data": _coerce_slice_data(data),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local sl = nil
    for _, s in ipairs(spr.slices) do if s.name == ARG.name then sl = s end end
    if sl == nil then error("No slice named '" .. tostring(ARG.name) .. "'") end
    if ARG.bounds ~= nil then
      sl.bounds = Rectangle(ARG.bounds.x, ARG.bounds.y, ARG.bounds.width, ARG.bounds.height)
    end
    if ARG.new_name ~= nil then sl.name = ARG.new_name end
    if ARG.color ~= nil then sl.color = mkcolor(ARG.color) end
    if ARG.data ~= nil then sl.data = ARG.data end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def remove_slice(filename: str, name: str) -> dict:
    """Delete a slice by name."""
    args = {"src": lua_path(resolve_path(filename)), "name": name}
    body = """
    local spr = open_sprite(ARG.src)
    local sl = nil
    for _, s in ipairs(spr.slices) do if s.name == ARG.name then sl = s end end
    if sl == nil then error("No slice named '" .. tostring(ARG.name) .. "'") end
    spr:deleteSlice(sl)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def list_slices(filename: str) -> dict:
    """List all slices in the sprite with their bounds, center, and pivot."""
    body = """
    local spr = open_sprite(ARG.src)
    local info = sprite_info(spr)
    RESULT = { count = #info.slices, slices = info.slices }
    """
    return run_lua(body, {"src": lua_path(resolve_path(filename))})
