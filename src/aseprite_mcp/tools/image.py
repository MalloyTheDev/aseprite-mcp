"""Stamp external images onto a sprite — from a file path or inline base64 PNG."""

from __future__ import annotations

import base64
import binascii
import os
import tempfile

from ..app import mcp
from ..runner import run_lua
from .common import lua_path, resolve_path

_STAMP_BODY = """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
if layer.isGroup then error("Cannot stamp onto a group layer: " .. layer.name) end
local framenum = clamp_frame(spr, ARG.frame)
local img = get_draw_image(spr, layer, framenum)

local source = app.open(ARG.source)
if source == nil then error("Could not open source image: " .. ARG.source) end
local sframe = ARG.source_frame
if sframe < 1 then sframe = 1 end
if sframe > #source.frames then sframe = #source.frames end

local srcimg = Image(ImageSpec{ width = source.width, height = source.height, colorMode = spr.colorMode })
srcimg:clear()
srcimg:drawSprite(source, sframe)
img:drawImage(srcimg, Point(ARG.x, ARG.y), ARG.opacity, blendmode_from(ARG.blend_mode))

commit_image(spr, layer, framenum, img)
save_sprite(spr)
RESULT = { ok = true, layer = layer.name, frame = framenum,
           stamped = { width = source.width, height = source.height, x = ARG.x, y = ARG.y } }
"""


def _stamp(args: dict) -> dict:
    return run_lua(_STAMP_BODY, args)


@mcp.tool()
def stamp_file(
    filename: str,
    source: str,
    x: int,
    y: int,
    source_frame: int = 1,
    opacity: int = 255,
    blend_mode: str = "normal",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Composite another image/sprite file onto a layer at (x, y).

    Args:
        source: Path to a .aseprite/.png/.bmp/... to stamp in.
        x, y: Top-left placement on the target canvas.
        source_frame: Which frame of the source to use (1-based).
        opacity: 0-255.
        blend_mode: Blend mode for compositing (normal, multiply, …).
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "source": lua_path(resolve_path(source)),
        "layer": layer, "frame": int(frame),
        "source_frame": int(source_frame),
        "x": int(x), "y": int(y),
        "opacity": max(0, min(255, int(opacity))),
        "blend_mode": blend_mode,
    }
    return _stamp(args)


@mcp.tool()
def draw_image_base64(
    filename: str,
    image_base64: str,
    x: int,
    y: int,
    opacity: int = 255,
    blend_mode: str = "normal",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Composite an inline base64-encoded PNG (or other image) onto a layer at (x, y).

    Useful for pasting externally generated artwork. `image_base64` may include a
    `data:image/png;base64,` prefix.
    """
    data = image_base64.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"image_base64 is not valid base64: {exc}")

    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="asemcp_stamp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        args = {
            "src": lua_path(resolve_path(filename)),
            "source": lua_path(tmp),
            "layer": layer, "frame": int(frame),
            "source_frame": 1,
            "x": int(x), "y": int(y),
            "opacity": max(0, min(255, int(opacity))),
            "blend_mode": blend_mode,
        }
        return _stamp(args)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
