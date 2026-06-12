"""Layer management: add, group, remove, rename, properties, duplicate, merge."""

from __future__ import annotations

from ..app import mcp
from ..runner import run_lua
from .common import lua_path, parse_color, resolve_path


@mcp.tool()
def add_layer(
    filename: str,
    name: str,
    group: str | None = None,
    opacity: int = 255,
    blend_mode: str = "normal",
    visible: bool = True,
) -> dict:
    """Add a new (empty) normal layer on top of the stack.

    Args:
        name: Layer name.
        group: Optional name of an existing group layer to nest the new layer in.
        opacity: 0-255.
        blend_mode: normal, multiply, screen, overlay, darken, lighten,
            color_dodge, color_burn, hard_light, soft_light, difference,
            exclusion, hue, saturation, color, luminosity, addition, subtract, divide.
        visible: Initial visibility.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "group": group,
        "opacity": max(0, min(255, int(opacity))),
        "blend_mode": blend_mode,
        "visible": bool(visible),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = spr:newLayer()
    layer.name = ARG.name
    layer.opacity = ARG.opacity
    layer.blendMode = blendmode_from(ARG.blend_mode)
    layer.isVisible = ARG.visible
    if ARG.group ~= nil then
      local grp = find_layer(spr, ARG.group)
      if not grp.isGroup then error("'" .. tostring(ARG.group) .. "' is not a group layer") end
      layer.parent = grp
    end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def add_group_layer(filename: str, name: str) -> dict:
    """Add a new (empty) group layer on top of the stack. Nest layers into it
    with add_layer(group=...) or move_layer(group=...)."""
    args = {"src": lua_path(resolve_path(filename)), "name": name}
    body = """
    local spr = open_sprite(ARG.src)
    local grp = spr:newGroup()
    grp.name = ARG.name
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def remove_layer(filename: str, layer: str) -> dict:
    """Delete a layer (or group, including its children) by name or 1-based index."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer}
    body = """
    local spr = open_sprite(ARG.src)
    if #spr.layers <= 1 then error("Cannot delete the only layer.") end
    local layer = find_layer(spr, ARG.layer)
    spr:deleteLayer(layer)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def rename_layer(filename: str, layer: str, new_name: str) -> dict:
    """Rename a layer."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "new_name": new_name}
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    layer.name = ARG.new_name
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def set_layer_properties(
    filename: str,
    layer: str,
    opacity: int | None = None,
    blend_mode: str | None = None,
    visible: bool | None = None,
    editable: bool | None = None,
    name: str | None = None,
) -> dict:
    """Update one or more layer properties. Only the arguments you pass are changed."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "opacity": None if opacity is None else max(0, min(255, int(opacity))),
        "blend_mode": blend_mode,
        "visible": visible,
        "editable": editable,
        "name": name,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if ARG.opacity ~= nil then layer.opacity = ARG.opacity end
    if ARG.blend_mode ~= nil then layer.blendMode = blendmode_from(ARG.blend_mode) end
    if ARG.visible ~= nil then layer.isVisible = ARG.visible end
    if ARG.editable ~= nil then layer.isEditable = ARG.editable end
    if ARG.name ~= nil then layer.name = ARG.name end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def move_layer(filename: str, layer: str, to_index: int) -> dict:
    """Reorder a layer to a new 1-based stack index (1 = bottom-most).

    Note: moves within the layer's current parent group.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "to_index": int(to_index),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    local ok, err = pcall(function() layer.stackIndex = ARG.to_index end)
    if not ok then
      error("This Aseprite version does not allow setting layer.stackIndex (" ..
            tostring(err) .. ").")
    end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def duplicate_layer(filename: str, layer: str) -> dict:
    """Duplicate a layer (including its cels) as a new layer on top."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer}
    body = """
    local spr = open_sprite(ARG.src)
    app.layer = find_layer(spr, ARG.layer)
    app.command.DuplicateLayer()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def merge_layer_down(filename: str, layer: str) -> dict:
    """Merge a layer down into the layer directly beneath it."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer}
    body = """
    local spr = open_sprite(ARG.src)
    app.layer = find_layer(spr, ARG.layer)
    app.command.MergeDownLayer()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)
