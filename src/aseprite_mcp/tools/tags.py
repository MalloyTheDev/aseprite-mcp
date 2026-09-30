"""Animation tags (named frame ranges with a playback direction)."""

from __future__ import annotations

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import MAX_TAG_REPEATS
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path


def _repeat_count(repeats: int | None) -> int | None:
    """Validate a tag's repeat count before Aseprite gets a chance to reinterpret it.

    Aseprite takes -1 and stores 0, which means "forever": the opposite of the one-shot
    anybody typing a negative number is after. It is refused here rather than quietly
    turned into its own opposite.
    """
    if repeats is None:
        return None
    count = int(repeats)
    if count < 0:
        raise ValidationFailed(
            f"repeats must be 0 or more; got {count}. Aseprite stores a negative count "
            "as 0, which means 'play forever', the opposite of a one-shot. Use 1 for a "
            "tag that plays once."
        )
    if count > MAX_TAG_REPEATS:
        raise ValidationFailed(
            f"repeats is {count}; the file format stores at most {MAX_TAG_REPEATS}. "
            "Use 0 for a tag that plays forever."
        )
    return count


@mcp.tool()
def add_tag(
    filename: str,
    name: str,
    from_frame: int,
    to_frame: int,
    direction: str = "forward",
    color: str | None = None,
    repeats: int = 0,
) -> dict:
    """Create an animation tag spanning frames [from_frame, to_frame] (1-based).

    Both frames must already exist: an out-of-range number is rejected with the sprite's
    valid range rather than clamped to it (which used to report a tag added while
    creating it over a different range).

    Args:
        direction: "forward" (default), "reverse", "pingpong", or "pingpong_reverse".
        color: Optional tag colour, shown in the timeline.
        repeats: How many times the tag plays. **0, the default, means forever**, which
            is how a cycle is marked in the file; 1 is a one-shot such as an attack, a
            hurt or a death. This is the sprite's own answer to whether these frames
            loop, and `validate_loop` reads it: a repeated last frame is an error for a
            cycle and only a warning for a one-shot.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "from": FrameRef.arg("from_frame", from_frame),
        "to": FrameRef.arg("to_frame", to_frame),
        "direction": direction,
        "color": parse_color(color) if color else None,
        "repeats": _repeat_count(repeats),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local a = require_frame(spr, ARG["from"], "from_frame")
    local b = require_frame(spr, ARG.to, "to_frame")
    if a > b then a, b = b, a end
    local tag = spr:newTag(a, b)
    tag.name = ARG.name
    tag.aniDir = anidir_from(ARG.direction)
    if ARG.color ~= nil then tag.color = mkcolor(ARG.color) end
    if ARG.repeats ~= nil then tag.repeats = ARG.repeats end
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
    if found == nil then error("No tag named '" .. tostring(ARG.name) .. "'", 0) end
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
    repeats: int | None = None,
) -> dict:
    """Update an existing tag. Only the arguments you pass are changed.

    Note: changing from_frame/to_frame recreates the tag in place to update its
    range reliably across Aseprite versions. A frame that does not exist is rejected
    with the sprite's valid range rather than clamped into it.

    `repeats` is how many times the tag plays, with 0 meaning forever. It survives the
    recreate above along with the name, direction and colour.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "from": None if from_frame is None else FrameRef.arg("from_frame", from_frame),
        "to": None if to_frame is None else FrameRef.arg("to_frame", to_frame),
        "new_name": new_name,
        "direction": direction,
        "color": parse_color(color) if color else None,
        "repeats": _repeat_count(repeats),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local tag = nil
    for _, t in ipairs(spr.tags) do if t.name == ARG.name then tag = t end end
    if tag == nil then error("No tag named '" .. tostring(ARG.name) .. "'", 0) end

    local cur_from = tag.fromFrame.frameNumber
    local cur_to = tag.toFrame.frameNumber
    local cur_dir = tag.aniDir
    local cur_color = tag.color
    local cur_name = tag.name
    local cur_repeats = tag.repeats

    local new_from = ARG["from"] and require_frame(spr, ARG["from"], "from_frame") or cur_from
    local new_to = ARG.to and require_frame(spr, ARG.to, "to_frame") or cur_to
    if new_from > new_to then new_from, new_to = new_to, new_from end

    if new_from ~= cur_from or new_to ~= cur_to then
      spr:deleteTag(tag)
      tag = spr:newTag(new_from, new_to)
      tag.aniDir = cur_dir
      tag.color = cur_color
      tag.name = cur_name
      -- The recreate above is why this is carried explicitly: a new tag starts at 0,
      -- so a one-shot would quietly become a loop on any range edit.
      if cur_repeats ~= nil then tag.repeats = cur_repeats end
    end

    if ARG.new_name ~= nil then tag.name = ARG.new_name end
    if ARG.direction ~= nil then tag.aniDir = anidir_from(ARG.direction) end
    if ARG.color ~= nil then tag.color = mkcolor(ARG.color) end
    if ARG.repeats ~= nil then tag.repeats = ARG.repeats end
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)
