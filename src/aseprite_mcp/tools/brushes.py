"""Custom brushes, pattern tiling, and symmetry/mirror drawing."""

from __future__ import annotations

from ..app import mcp
from ..runner import run_lua
from .common import lua_path, parse_color, resolve_path
from .drawing import _draw


@mcp.tool()
def draw_brush(
    filename: str,
    brush: list[str],
    points: list[dict],
    color: str,
    anchor: str = "center",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Stamp a custom brush shape at a list of points.

    Args:
        brush: The brush as rows of characters. Any character other than space,
            '.', or '0' is a filled cell. e.g. a plus brush: ["010", "111", "010"].
        points: Positions to stamp at, list of {"x": int, "y": int}.
        color: Colour to stamp the brush in.
        anchor: "center" (default) or "topleft" — where each point sits in the brush.
    """
    if not brush or not points:
        raise ValueError("brush and points must be non-empty.")
    h = len(brush)
    w = max(len(r) for r in brush)
    cells = []
    for ry, rowtext in enumerate(brush):
        for cx, ch in enumerate(rowtext):
            if ch not in (" ", ".", "0"):
                cells.append((cx, ry))
    if not cells:
        raise ValueError("Brush has no filled cells.")
    ax = (w // 2) if anchor == "center" else 0
    ay = (h // 2) if anchor == "center" else 0
    offsets = [[cx - ax, ry - ay] for cx, ry in cells]
    pts = [[int(p["x"]), int(p["y"])] for p in points]
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "offsets": offsets, "points": pts,
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    for _, pt in ipairs(ARG.points) do
      for _, off in ipairs(ARG.offsets) do
        img_set(img, pt[1] + off[1], pt[2] + off[2], px)
      end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def stamp_pattern(
    filename: str,
    source: str,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    spacing_x: int = 0,
    spacing_y: int = 0,
    opacity: int = 255,
    blend_mode: str = "normal",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Tile an image/sprite across a region to fill it with a repeating pattern.

    Args:
        source: Image/sprite to tile.
        x, y, width, height: Region to fill (defaults to the whole canvas).
        spacing_x, spacing_y: Gap between tiles.
        opacity, blend_mode: Compositing of each tile.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "source": lua_path(resolve_path(source)),
        "layer": layer, "frame": int(frame),
        "x": int(x), "y": int(y), "width": width, "height": height,
        "sx": max(0, int(spacing_x)), "sy": max(0, int(spacing_y)),
        "opacity": max(0, min(255, int(opacity))),
        "blend_mode": blend_mode,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot stamp onto a group layer: " .. layer.name) end
    local framenum = clamp_frame(spr, ARG.frame)
    local img = get_draw_image(spr, layer, framenum)

    local source = app.open(ARG.source)
    if source == nil then error("Could not open pattern source: " .. ARG.source) end
    local tile = Image(ImageSpec{ width = source.width, height = source.height, colorMode = spr.colorMode })
    tile:clear(); tile:drawSprite(source, 1)

    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)
    local stepx = source.width + ARG.sx
    local stepy = source.height + ARG.sy
    local bm = blendmode_from(ARG.blend_mode)
    local placed = 0
    local py = ry
    while py < ry + rh do
      local cxp = rx
      while cxp < rx + rw do
        img:drawImage(tile, Point(cxp, py), ARG.opacity, bm)
        placed = placed + 1
        cxp = cxp + stepx
      end
      py = py + stepy
    end
    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = framenum, tiles = placed }
    """
    return run_lua(body, args)


@mcp.tool()
def mirror_layer(
    filename: str,
    layer: str,
    direction: str = "horizontal",
    source_side: str = "first",
    axis: int | None = None,
    frame: int = 1,
) -> dict:
    """Mirror one half of a layer onto the other (build symmetric artwork).

    Args:
        direction: "horizontal" (reflect left<->right) or "vertical" (top<->bottom).
        source_side: which half is copied: "first" (left/top) or "second" (right/bottom).
        axis: mirror line position (x for horizontal, y for vertical); default = centre.
    """
    if direction not in ("horizontal", "vertical"):
        raise ValueError('direction must be "horizontal" or "vertical"')
    if source_side not in ("first", "second"):
        raise ValueError('source_side must be "first" or "second"')
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "direction": direction, "source_side": source_side, "axis": axis,
    }
    snippet = """
    if ARG.direction == "horizontal" then
      local ax = ARG.axis or math.floor(img.width / 2)
      for y = 0, img.height - 1 do
        local lo, hi
        if ARG.source_side == "first" then lo, hi = 0, ax - 1 else lo, hi = ax, img.width - 1 end
        for x = lo, hi do
          local mx = 2 * ax - 1 - x
          if mx >= 0 and mx < img.width then img:drawPixel(mx, y, img:getPixel(x, y)) end
        end
      end
    else
      local ay = ARG.axis or math.floor(img.height / 2)
      for x = 0, img.width - 1 do
        local lo, hi
        if ARG.source_side == "first" then lo, hi = 0, ay - 1 else lo, hi = ay, img.height - 1 end
        for y = lo, hi do
          local my = 2 * ay - 1 - y
          if my >= 0 and my < img.height then img:drawPixel(x, my, img:getPixel(x, y)) end
        end
      end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def draw_symmetric_pixels(
    filename: str,
    pixels: list[dict],
    color: str,
    mode: str = "horizontal",
    axis_x: int | None = None,
    axis_y: int | None = None,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Plot pixels together with their mirror image(s).

    mode: "horizontal" (mirror across vertical axis_x), "vertical" (across axis_y),
    or "both" (4-way radial symmetry). Axes default to the canvas centre.
    """
    if mode not in ("horizontal", "vertical", "both"):
        raise ValueError('mode must be "horizontal", "vertical", or "both"')
    if not pixels:
        raise ValueError("pixels must be non-empty.")
    pts = [[int(p["x"]), int(p["y"])] for p in pixels]
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "points": pts, "mode": mode, "axis_x": axis_x, "axis_y": axis_y,
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    local ax = ARG.axis_x or math.floor(spr.width / 2)
    local ay = ARG.axis_y or math.floor(spr.height / 2)
    local hor = (ARG.mode == "horizontal" or ARG.mode == "both")
    local ver = (ARG.mode == "vertical" or ARG.mode == "both")
    for _, p in ipairs(ARG.points) do
      local x, y = p[1], p[2]
      img_set(img, x, y, px)
      if hor then img_set(img, 2 * ax - 1 - x, y, px) end
      if ver then img_set(img, x, 2 * ay - 1 - y, px) end
      if hor and ver then img_set(img, 2 * ax - 1 - x, 2 * ay - 1 - y, px) end
    end
    """
    return _draw(args, snippet)
