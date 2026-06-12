"""Reference image import & rotoscoping helpers.

Aseprite's true "reference layer" flag is read-only via the API, so these create
a normal, dimmed, locked layer instead. Exclude it at export time with
`export_*`'s `ignore_layer="reference"` (or hide it).
"""

from __future__ import annotations

from ..app import mcp
from ..core.runner import run_lua
from .common import lua_path, resolve_path


@mcp.tool()
def add_reference_layer(
    filename: str,
    image_file: str,
    layer_name: str = "reference",
    opacity: int = 128,
    scale_to_fit: bool = False,
    x: int = 0,
    y: int = 0,
    frame: int = 1,
) -> dict:
    """Add a dimmed, locked layer holding a reference image to trace over.

    Args:
        image_file: The reference image/sprite.
        layer_name: Name for the new layer (default "reference").
        opacity: Layer opacity (0-255); dim it so your art stands out.
        scale_to_fit: Resize the reference to the canvas size (smooth).
        x, y: Placement when not scaling to fit.

    Exclude this layer from exports with ignore_layer="<layer_name>".
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "image": lua_path(resolve_path(image_file)),
        "layer_name": layer_name,
        "opacity": max(0, min(255, int(opacity))),
        "scale_to_fit": bool(scale_to_fit),
        "x": int(x), "y": int(y), "frame": int(frame),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local source = app.open(ARG.image)
    if source == nil then error("Could not open reference image: " .. ARG.image) end
    if ARG.scale_to_fit then
      app.sprite = source
      app.command.SpriteSize{ ui = false, width = spr.width, height = spr.height, method = "bilinear" }
      app.sprite = spr
    end
    local simg = Image(ImageSpec{ width = source.width, height = source.height, colorMode = spr.colorMode })
    simg:clear(); simg:drawSprite(source, 1)
    local layer = spr:newLayer()
    layer.name = ARG.layer_name
    layer.opacity = ARG.opacity
    local framenum = clamp_frame(spr, ARG.frame)
    spr:newCel(layer, framenum, simg, Point(ARG.x, ARG.y))
    layer.isEditable = false
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def import_reference_sequence(
    filename: str,
    images: list[str],
    layer_name: str = "rotoscope",
    opacity: int = 128,
    scale_to_fit: bool = False,
    start_frame: int = 1,
) -> dict:
    """Import a sequence of images as per-frame references for rotoscoping.

    Each image is placed on its own frame in a single dimmed, locked layer
    (frames are created as needed). Draw your animation on a layer above, then
    exclude this layer at export with ignore_layer="<layer_name>".
    """
    if not images:
        raise ValueError("images must be a non-empty list.")
    paths = [lua_path(resolve_path(p)) for p in images]
    args = {
        "src": lua_path(resolve_path(filename)),
        "images": paths,
        "layer_name": layer_name,
        "opacity": max(0, min(255, int(opacity))),
        "scale_to_fit": bool(scale_to_fit),
        "start_frame": max(1, int(start_frame)),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = spr:newLayer()
    layer.name = ARG.layer_name
    layer.opacity = ARG.opacity
    local needed = ARG.start_frame + #ARG.images - 1
    while #spr.frames < needed do spr:newEmptyFrame(#spr.frames + 1) end
    for i, path in ipairs(ARG.images) do
      local source = app.open(path)
      if source == nil then error("Could not open image: " .. path) end
      if ARG.scale_to_fit then
        app.sprite = source
        app.command.SpriteSize{ ui = false, width = spr.width, height = spr.height, method = "bilinear" }
        app.sprite = spr
      end
      local simg = Image(ImageSpec{ width = source.width, height = source.height, colorMode = spr.colorMode })
      simg:clear(); simg:drawSprite(source, 1)
      spr:newCel(layer, ARG.start_frame + i - 1, simg, Point(0, 0))
    end
    layer.isEditable = false
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)
