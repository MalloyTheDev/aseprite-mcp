"""Whole-sprite transforms: flip and rotate (applied to every layer & frame)."""

from __future__ import annotations

from ..app import mcp
from ..core.runner import run_lua
from .common import lua_path, resolve_path


@mcp.tool()
def flip_sprite(filename: str, direction: str = "horizontal") -> dict:
    """Flip the entire sprite. direction: "horizontal" or "vertical"."""
    d = direction.lower()
    if d not in ("horizontal", "vertical"):
        raise ValueError('direction must be "horizontal" or "vertical"')
    args = {"src": lua_path(resolve_path(filename)), "dir": d}
    body = """
    local spr = open_sprite(ARG.src)
    app.command.Flip{ target = "sprite", orientation = ARG.dir }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def rotate_sprite(filename: str, angle: int) -> dict:
    """Rotate the entire sprite by 90, 180, or 270 degrees (clockwise)."""
    if int(angle) not in (90, 180, 270):
        raise ValueError("angle must be 90, 180, or 270")
    args = {"src": lua_path(resolve_path(filename)), "angle": int(angle)}
    body = """
    local spr = open_sprite(ARG.src)
    app.command.Rotate{ target = "sprite", angle = ARG.angle }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)
