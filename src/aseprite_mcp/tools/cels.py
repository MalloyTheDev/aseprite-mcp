"""Cel-level operations: inspect, reposition, opacity, copy between frames, delete.

A *cel* is the image of one layer at one frame. Frames and layers are 1-based.
"""

from __future__ import annotations

from ..app import mcp
from ..runner import run_lua
from .common import lua_path, resolve_path


@mcp.tool()
def get_cel(filename: str, layer: str, frame: int = 1) -> dict:
    """Inspect a cel: whether it exists, its position, bounds, and opacity."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frame": int(frame)}
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = clamp_frame(spr, ARG.frame)
    local cel = layer:cel(n)
    if cel == nil then
      RESULT = { exists = false, layer = layer.name, frame = n }
    else
      RESULT = {
        exists = true, layer = layer.name, frame = n,
        opacity = cel.opacity,
        position = { x = cel.position.x, y = cel.position.y },
        bounds = { x = cel.bounds.x, y = cel.bounds.y,
                   width = cel.bounds.width, height = cel.bounds.height },
      }
    end
    """
    return run_lua(body, args)


@mcp.tool()
def set_cel_position(filename: str, layer: str, frame: int, x: int, y: int) -> dict:
    """Move a cel's image to position (x, y) within the canvas."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame), "x": int(x), "y": int(y),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = clamp_frame(spr, ARG.frame)
    local cel = layer:cel(n)
    if cel == nil then error("No cel on layer '" .. layer.name .. "' at frame " .. n) end
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
        "layer": layer, "frame": int(frame),
        "opacity": max(0, min(255, int(opacity))),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = clamp_frame(spr, ARG.frame)
    local cel = layer:cel(n)
    if cel == nil then error("No cel on layer '" .. layer.name .. "' at frame " .. n) end
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
        "layer": layer, "from": int(from_frame), "to": int(to_frame),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local a = clamp_frame(spr, ARG["from"])
    local b = clamp_frame(spr, ARG.to)
    local src_cel = layer:cel(a)
    if src_cel == nil then error("No cel to copy on layer '" .. layer.name .. "' at frame " .. a) end
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
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frame": int(frame)}
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local n = clamp_frame(spr, ARG.frame)
    local cel = layer:cel(n)
    if cel ~= nil then spr:deleteCel(cel) end
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = n }
    """
    return run_lua(body, args)
