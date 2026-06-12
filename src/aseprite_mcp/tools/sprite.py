"""Sprite lifecycle: create, save, resize, crop, scale, flatten, colour mode."""

from __future__ import annotations

from ..app import mcp
from ..runner import run_lua
from .common import lua_path, parse_color, resolve_path


@mcp.tool()
def create_sprite(
    filename: str,
    width: int,
    height: int,
    color_mode: str = "rgb",
    background: str | None = None,
) -> dict:
    """Create a new sprite file and save it.

    Args:
        filename: Output path. Relative paths go in the workspace. Use a
            .aseprite/.ase extension to keep layers & frames editable.
        width, height: Canvas size in pixels (1-65535).
        color_mode: "rgb" (default), "indexed", or "gray".
        background: Optional fill colour for the first layer (e.g. "#1d2b53").
            Omit for a transparent canvas.

    Returns the new sprite's structured info.
    """
    if width < 1 or height < 1:
        raise ValueError("width and height must be >= 1")
    path = resolve_path(filename)
    args = {
        "path": lua_path(path),
        "width": int(width),
        "height": int(height),
        "color_mode": color_mode,
        "bg": parse_color(background) if background else None,
    }
    body = """
    local spr = Sprite(ARG.width, ARG.height, colormode_from(ARG.color_mode))
    spr.filename = ARG.path
    if ARG.bg ~= nil then
      local layer = spr.layers[1]
      local img = get_draw_image(spr, layer, 1)
      draw_rect_img(img, 0, 0, spr.width, spr.height, to_pixel(spr, ARG.bg), true)
      commit_image(spr, layer, 1, img)
    end
    spr:saveAs(ARG.path)
    RESULT = sprite_info(spr)
    """
    info = run_lua(body, args)
    info["path"] = str(path)
    return info


@mcp.tool()
def save_sprite_as(filename: str, new_filename: str, flatten: bool = False) -> dict:
    """Save a copy of a sprite under a new path (optionally flattened).

    The original file is left untouched. Useful for exporting an editable
    .aseprite to another .aseprite, or snapshotting a version.
    """
    src = resolve_path(filename)
    dst = resolve_path(new_filename)
    args = {"src": lua_path(src), "dst": lua_path(dst), "flatten": bool(flatten)}
    body = """
    local spr = open_sprite(ARG.src)
    local copy = Sprite(spr)
    if ARG.flatten then copy:flatten() end
    copy.filename = ARG.dst
    copy:saveAs(ARG.dst)
    RESULT = sprite_info(copy)
    """
    info = run_lua(body, args)
    info["path"] = str(dst)
    return info


@mcp.tool()
def set_color_mode(filename: str, color_mode: str, dithering: str = "none") -> dict:
    """Convert a sprite between colour modes ("rgb", "indexed", "gray").

    When converting to "indexed", dithering can be "none", "ordered", or
    "old" to control how RGB colours are mapped to the palette.
    """
    src = resolve_path(filename)
    args = {"src": lua_path(src), "mode": color_mode, "dither": dithering}
    body = """
    local spr = open_sprite(ARG.src)
    local fmt = ARG.mode
    if fmt == "grayscale" or fmt == "grey" then fmt = "gray" end
    app.command.ChangePixelFormat{ ui = false, format = fmt, dithering = ARG.dither }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def resize_canvas(
    filename: str, width: int, height: int, anchor: str = "top_left"
) -> dict:
    """Resize the canvas WITHOUT scaling the artwork (adds or trims space).

    anchor controls where existing content sits in the new canvas:
    "top_left" (default) or "center".
    """
    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "width": int(width),
        "height": int(height),
        "anchor": anchor,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local x, y = 0, 0
    if ARG.anchor == "center" then
      x = -math.floor((ARG.width - spr.width) / 2)
      y = -math.floor((ARG.height - spr.height) / 2)
    end
    spr:crop(x, y, ARG.width, ARG.height)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def crop_sprite(filename: str, x: int, y: int, width: int, height: int) -> dict:
    """Crop the canvas to the rectangle (x, y, width, height)."""
    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "x": int(x),
        "y": int(y),
        "width": int(width),
        "height": int(height),
    }
    body = """
    local spr = open_sprite(ARG.src)
    spr:crop(ARG.x, ARG.y, ARG.width, ARG.height)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def scale_sprite(
    filename: str,
    factor: float | None = None,
    width: int | None = None,
    height: int | None = None,
    method: str = "nearest",
) -> dict:
    """Scale the whole sprite (artwork included).

    Provide either `factor` (e.g. 2.0 to double) OR explicit `width`/`height`.
    method: "nearest" (crisp pixels, default) or "bilinear" (smooth).
    """
    src = resolve_path(filename)
    if factor is None and width is None and height is None:
        raise ValueError("Provide either factor or width/height.")
    args = {
        "src": lua_path(src),
        "factor": factor,
        "width": width,
        "height": height,
        "method": method,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local w = ARG.width
    local h = ARG.height
    if ARG.factor ~= nil then
      w = math.max(1, math.floor(spr.width * ARG.factor + 0.5))
      h = math.max(1, math.floor(spr.height * ARG.factor + 0.5))
    end
    w = w or spr.width
    h = h or spr.height
    app.command.SpriteSize{ ui = false, width = w, height = h, method = ARG.method }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def flatten_sprite(filename: str) -> dict:
    """Flatten all layers into a single layer (in place)."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    spr:flatten()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})


@mcp.tool()
def trim_sprite(filename: str) -> dict:
    """Auto-crop the canvas to the bounding box of all non-transparent content
    (across every frame)."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    local minx, miny, maxx, maxy
    for f = 1, #spr.frames do
      local flat = Image(spr.spec); flat:clear(); flat:drawSprite(spr, f)
      for y = 0, flat.height - 1 do
        for x = 0, flat.width - 1 do
          local _, _, _, a = px_to_rgba(spr, flat:getPixel(x, y))
          if a > 0 then
            if minx == nil or x < minx then minx = x end
            if miny == nil or y < miny then miny = y end
            if maxx == nil or x > maxx then maxx = x end
            if maxy == nil or y > maxy then maxy = y end
          end
        end
      end
    end
    if minx == nil then error("Sprite is fully transparent; nothing to trim.") end
    spr:crop(minx, miny, maxx - minx + 1, maxy - miny + 1)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})


@mcp.tool()
def convert_layer_to_background(filename: str, layer: str) -> dict:
    """Convert a normal layer into the sprite's opaque Background layer."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer}
    body = """
    local spr = open_sprite(ARG.src)
    app.layer = find_layer(spr, ARG.layer)
    app.command.BackgroundFromLayer()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def convert_background_to_layer(filename: str) -> dict:
    """Convert the Background layer back into a normal (transparent-capable) layer."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    app.command.LayerFromBackground()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})
