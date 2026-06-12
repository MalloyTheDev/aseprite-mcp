"""Drawing: pixels, lines, rectangles, ellipses, flood fill, clear/fill layer.

All coordinates are in sprite space (0,0 = top-left). Drawing targets a chosen
layer + frame; the layer's cel is created/extended to the full canvas so
coordinates are always predictable.
"""

from __future__ import annotations

from ..app import mcp
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path

# Shared Lua preamble: open sprite, resolve a non-group layer + frame, build an
# editable full-canvas image, then run the per-tool drawing snippet, commit & save.
_OPEN = """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
if layer.isGroup then error("Cannot draw on a group layer: " .. layer.name) end
local framenum = clamp_frame(spr, ARG.frame)
local img = get_draw_image(spr, layer, framenum)
"""

_CLOSE = """
commit_image(spr, layer, framenum, img)
save_sprite(spr)
RESULT = { ok = true, filename = spr.filename, layer = layer.name,
           frame = framenum, width = spr.width, height = spr.height }
"""


def _draw(args: dict, snippet: str) -> dict:
    return run_lua(_OPEN + snippet + _CLOSE, args)


@mcp.tool()
def draw_pixels(
    filename: str,
    pixels: list[dict],
    color: str | None = None,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Plot individual pixels.

    Args:
        pixels: List of {"x": int, "y": int, "color": "#hex"?}. If a pixel omits
            "color", the shared `color` argument is used.
        color: Default colour for pixels that don't specify their own.
        layer: Target layer name or 1-based index (default: top layer).
        frame: Target frame, 1-based (default 1).
    """
    if not pixels:
        raise ValueError("pixels must be a non-empty list.")
    default = parse_color(color) if color else None
    lua_pixels = []
    for p in pixels:
        x = int(p["x"])
        y = int(p["y"])
        c = p.get("color")
        item = {"x": x, "y": y}
        if c is not None:
            item["c"] = parse_color(c)
        elif default is None:
            raise ValueError(
                "Pixel without its own colour found, but no shared `color` was given."
            )
        lua_pixels.append(item)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": default,
        "pixels": lua_pixels,
    }
    snippet = """
    local default = nil
    if ARG.color ~= nil then default = to_pixel(spr, ARG.color) end
    for _, p in ipairs(ARG.pixels) do
      local px = default
      if p.c ~= nil then px = to_pixel(spr, p.c) end
      img_set(img, p.x, p.y, px)
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def draw_line(
    filename: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: str,
    pixel_perfect: bool = False,
    antialias: bool = False,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw a straight line from (x1,y1) to (x2,y2).

    Args:
        pixel_perfect: Remove L-shaped corner pixels for a clean 1px pixel-art line.
        antialias: Smooth (Xiaolin Wu) line with alpha blending — RGB sprites only;
            ignored on indexed/gray. Takes precedence over pixel_perfect.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
        "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
        "pixel_perfect": bool(pixel_perfect),
        "antialias": bool(antialias),
    }
    snippet = """
    local c = ARG.color
    if ARG.antialias and spr.colorMode == ColorMode.RGB then
      aa_line_img(spr, img, ARG.x1, ARG.y1, ARG.x2, ARG.y2, c.r, c.g, c.b)
    else
      local px = to_pixel(spr, c)
      if ARG.pixel_perfect then
        local pts = pp_prune(bresenham_points(ARG.x1, ARG.y1, ARG.x2, ARG.y2))
        for _, p in ipairs(pts) do img_set(img, p[1], p[2], px) end
      else
        draw_line_img(img, ARG.x1, ARG.y1, ARG.x2, ARG.y2, px)
      end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def draw_polyline(
    filename: str,
    points: list[dict],
    color: str,
    closed: bool = False,
    pixel_perfect: bool = False,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw connected line segments through a list of points.

    points: list of {"x": int, "y": int}. Set closed=True to connect the last
    point back to the first (outline a polygon). pixel_perfect removes L-corner
    pixels across the whole path for a clean pixel-art outline.
    """
    if len(points) < 2:
        raise ValueError("Need at least 2 points.")
    pts = [{"x": int(p["x"]), "y": int(p["y"])} for p in points]
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
        "points": pts,
        "closed": bool(closed),
        "pixel_perfect": bool(pixel_perfect),
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    local pts = ARG.points
    if ARG.pixel_perfect then
      local path = {}
      local function append_seg(x0, y0, x1, y1)
        local seg = bresenham_points(x0, y0, x1, y1)
        local startk = (#path > 0) and 2 or 1
        for k = startk, #seg do path[#path + 1] = seg[k] end
      end
      for i = 1, #pts - 1 do append_seg(pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y) end
      if ARG.closed and #pts > 2 then append_seg(pts[#pts].x, pts[#pts].y, pts[1].x, pts[1].y) end
      path = pp_prune(path)
      for _, p in ipairs(path) do img_set(img, p[1], p[2], px) end
    else
      for i = 1, #pts - 1 do
        draw_line_img(img, pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y, px)
      end
      if ARG.closed and #pts > 2 then
        draw_line_img(img, pts[#pts].x, pts[#pts].y, pts[1].x, pts[1].y, px)
      end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def draw_curve(
    filename: str,
    x0: int,
    y0: int,
    control_x: int,
    control_y: int,
    x1: int,
    y1: int,
    color: str,
    steps: int = 32,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw a quadratic Bézier curve from (x0,y0) to (x1,y1) bending toward the
    control point (control_x, control_y). `steps` controls smoothness."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "x0": int(x0), "y0": int(y0),
        "cx": int(control_x), "cy": int(control_y),
        "x1": int(x1), "y1": int(y1),
        "steps": max(2, int(steps)),
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    local function q(t, a, b, c) return (1 - t) ^ 2 * a + 2 * (1 - t) * t * b + t ^ 2 * c end
    local prevx, prevy
    for i = 0, ARG.steps do
      local t = i / ARG.steps
      local cxp = q(t, ARG.x0, ARG.cx, ARG.x1)
      local cyp = q(t, ARG.y0, ARG.cy, ARG.y1)
      if prevx ~= nil then draw_line_img(img, prevx, prevy, cxp, cyp, px) end
      prevx, prevy = cxp, cyp
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def draw_rectangle(
    filename: str,
    x: int,
    y: int,
    width: int,
    height: int,
    color: str,
    filled: bool = False,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw a rectangle. filled=False draws a 1px outline, True fills it."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
        "x": int(x), "y": int(y), "w": int(width), "h": int(height),
        "filled": bool(filled),
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    draw_rect_img(img, ARG.x, ARG.y, ARG.w, ARG.h, px, ARG.filled)
    """
    return _draw(args, snippet)


@mcp.tool()
def draw_ellipse(
    filename: str,
    center_x: int,
    center_y: int,
    radius_x: int,
    radius_y: int,
    color: str,
    filled: bool = False,
    antialias: bool = False,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw an ellipse centred at (center_x, center_y) with the given radii.

    For a circle, use the same value for radius_x and radius_y. filled=False
    draws a 1px outline. antialias smooths a *filled* ellipse with sub-pixel
    coverage (RGB sprites only; ignored otherwise).
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
        "cx": int(center_x), "cy": int(center_y),
        "rx": int(radius_x), "ry": int(radius_y),
        "filled": bool(filled),
        "antialias": bool(antialias),
    }
    snippet = """
    local c = ARG.color
    if ARG.antialias and ARG.filled and spr.colorMode == ColorMode.RGB then
      aa_ellipse_fill_img(spr, img, ARG.cx, ARG.cy, ARG.rx, ARG.ry, c.r, c.g, c.b)
    else
      draw_ellipse_img(img, ARG.cx, ARG.cy, ARG.rx, ARG.ry, to_pixel(spr, c), ARG.filled)
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def fill_area(
    filename: str,
    x: int,
    y: int,
    color: str,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Flood fill (paint bucket): replace the contiguous region of matching
    colour starting at (x,y) on the target layer with `color`."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
        "x": int(x), "y": int(y),
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    flood_fill_img(img, ARG.x, ARG.y, px)
    """
    return _draw(args, snippet)


@mcp.tool()
def fill_layer(
    filename: str,
    color: str,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Fill the entire target layer/frame cel with a solid colour."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    draw_rect_img(img, 0, 0, spr.width, spr.height, px, true)
    """
    return _draw(args, snippet)


@mcp.tool()
def clear_layer(
    filename: str,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Erase the target layer/frame cel to full transparency."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
    }
    snippet = """
    img:clear()
    """
    return _draw(args, snippet)
