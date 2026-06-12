"""Animation tags (named frame ranges with a playback direction)."""

from __future__ import annotations

from ..app import mcp
from ..runner import run_lua
from .common import lua_path, parse_color, resolve_path


@mcp.tool()
def add_tag(
    filename: str,
    name: str,
    from_frame: int,
    to_frame: int,
    direction: str = "forward",
    color: str | None = None,
) -> dict:
    """Create an animation tag spanning frames [from_frame, to_frame] (1-based).

    direction: "forward" (default), "reverse", "pingpong", or "pingpong_reverse".
    color: optional tag colour (shown in the timeline).
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "from": int(from_frame),
        "to": int(to_frame),
        "direction": direction,
        "color": parse_color(color) if color else None,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local a = clamp_frame(spr, ARG["from"])
    local b = clamp_frame(spr, ARG.to)
    if a > b then a, b = b, a end
    local tag = spr:newTag(a, b)
    tag.name = ARG.name
    tag.aniDir = anidir_from(ARG.direction)
    if ARG.color ~= nil then tag.color = mkcolor(ARG.color) end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def remove_tag(filename: str, name: str) -> dict:
    """Delete an animation tag by name."""
    args = {"src": lua_path(resolve_path(filename)), "name": name}
    body = """
    local spr = open_sprite(ARG.src)
    local found = nil
    for _, t in ipairs(spr.tags) do if t.name == ARG.name then found = t end end
    if found == nil then error("No tag named '" .. tostring(ARG.name) .. "'") end
    spr:deleteTag(found)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def set_tag(
    filename: str,
    name: str,
    from_frame: int | None = None,
    to_frame: int | None = None,
    new_name: str | None = None,
    direction: str | None = None,
    color: str | None = None,
) -> dict:
    """Update an existing tag. Only the arguments you pass are changed.

    Note: changing from_frame/to_frame recreates the tag in place to update its
    range reliably across Aseprite versions.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "from": from_frame,
        "to": to_frame,
        "new_name": new_name,
        "direction": direction,
        "color": parse_color(color) if color else None,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local tag = nil
    for _, t in ipairs(spr.tags) do if t.name == ARG.name then tag = t end end
    if tag == nil then error("No tag named '" .. tostring(ARG.name) .. "'") end

    local cur_from = tag.fromFrame.frameNumber
    local cur_to = tag.toFrame.frameNumber
    local cur_dir = tag.aniDir
    local cur_color = tag.color
    local cur_name = tag.name

    local new_from = ARG["from"] and clamp_frame(spr, ARG["from"]) or cur_from
    local new_to = ARG.to and clamp_frame(spr, ARG.to) or cur_to
    if new_from > new_to then new_from, new_to = new_to, new_from end

    if new_from ~= cur_from or new_to ~= cur_to then
      spr:deleteTag(tag)
      tag = spr:newTag(new_from, new_to)
      tag.aniDir = cur_dir
      tag.color = cur_color
      tag.name = cur_name
    end

    if ARG.new_name ~= nil then tag.name = ARG.new_name end
    if ARG.direction ~= nil then tag.aniDir = anidir_from(ARG.direction) end
    if ARG.color ~= nil then tag.color = mkcolor(ARG.color) end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)
