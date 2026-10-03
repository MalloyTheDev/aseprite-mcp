"""Drawing: pixels, lines, rectangles, ellipses, flood fill, clear/fill layer.

All coordinates are in sprite space (0,0 = top-left). Drawing targets a chosen
layer + frame; the layer's cel is created/extended to the full canvas so
coordinates are always predictable.
"""

from __future__ import annotations

import inspect

from ..app import mcp
from ..core import pixelmap
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_CURVE_STEPS,
    MAX_PIXEL_LIST_LENGTH,
    check_count,
    check_list_length,
)
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path

# Shared Lua preamble: open sprite, resolve a non-group layer + frame, build an
# editable full-canvas image, then run the per-tool drawing snippet, commit & save.
_OPEN = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
if layer.isGroup then error("Cannot draw on a group layer: " .. layer.name) end
local framenum = require_frame(spr, ARG.frame, "frame")
local img = get_draw_image(spr, layer, framenum)
"""

_CLOSE = """
commit_image(spr, layer, framenum, img)
save_sprite(spr)
RESULT = { ok = true, filename = spr.filename, layer = layer.name,
           frame = framenum, width = spr.width, height = spr.height }
-- A snippet that measured something it wants reported sets `_extra`, a table of fields
-- merged in here, rather than every drawing tool growing its own RESULT block. Leaving a
-- field out of `_extra` leaves it out of the result, which is the convention the counters
-- already follow: absent rather than zero, so a count that is present means the work it
-- describes was actually attempted.
if type(_extra) == "table" then
  for field, value in pairs(_extra) do RESULT[field] = value end
end
"""


def _draw(args: dict, snippet: str) -> dict:
    return run_lua(_OPEN + snippet + _CLOSE, args)


# These conventions lived only in this module's docstring, which never reaches the
# model: only a function's own docstring becomes its tool description. Most geometry
# tools documented no argument at all, and the two centring rules disagree by half a
# pixel, which is a visible defect at 16x16 rather than a rounding difference.
#
# Applied through a registration decorator rather than by editing seven docstrings, so
# one statement covers every geometry tool and they cannot drift apart. It has to run
# BEFORE mcp.tool(), because registration captures the description at that moment.
_GEOMETRY_NOTE = """
Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.
"""


def _geometry_tool(fn):
    """Register a drawing tool with the shared coordinate conventions appended.

    cleandoc first, because Python 3.13 dedents docstrings at compile time and 3.12
    does not, so appending at "the docstring's own level" yields different text per
    interpreter, and docs/TOOLS.md is generated from it.
    """
    base = inspect.cleandoc(fn.__doc__ or "").rstrip()
    fn.__doc__ = f"{base}\n\n{_GEOMETRY_NOTE.strip()}\n"
    return mcp.tool()(fn)


# The per-pixel write loop, shared by `draw_pixels` and `draw_pixel_map` so there is one
# definition of it. Both go through `img_set`, which is where the selection mask is
# consulted and where an off-canvas write is clipped and counted, so a map inherits every
# guarantee the dictionary form already had rather than growing a second write path.
_PIXEL_WRITE_LUA = """
    local default = nil
    if ARG.color ~= nil then default = to_pixel(spr, ARG.color) end
    for _, p in ipairs(ARG.pixels) do
      local px = default
      if p.c ~= nil then px = to_pixel(spr, p.c) end
      img_set(img, p.x, p.y, px)
    end
    """


@_geometry_tool
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
        raise ValidationFailed("pixels must be a non-empty list.")
    check_list_length("pixels", pixels, MAX_PIXEL_LIST_LENGTH)
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
            raise ValidationFailed(
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
    return _draw(args, _PIXEL_WRITE_LUA)


@_geometry_tool
def draw_pixel_map(
    filename: str,
    rows: list[str],
    legend: dict,
    x: int = 0,
    y: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw from a character grid, one character per pixel: the way pixel art is authored.

    This is the write side of `get_pixels(format="map")` and takes exactly the shape that
    returns, a `legend` plus one string per row, so a read, an edit and a write
    round-trip. Until this existed the server could *show* a caller per-pixel intent and
    could not receive it: the only way to author a figure was a list of
    `{"x", "y", "color"}` dictionaries, one per pixel.

    That asymmetry shaped the art it produced, which is the real reason this is here. A
    caller reaching for a thousand-entry dictionary list does not write a thousand
    considered pixels, it writes a formula that emits them, and a formula produces smooth
    monotone surfaces. Hand-placed pixel art is the opposite of that: a highlight nudged
    two pixels off the geometric centre, an outline that thickens on the shadow side,
    three pixels clustered to imply a chip in the stone. A grid is the notation those
    decisions can be written in, and it is about a tenth the size: a 16x16 of three
    colours is roughly 3,400 characters as dictionaries and 350 as a map.

    Args:
        rows: One string per row, one character per pixel, **every row the same length**.
            A ragged map is refused rather than padded, because padding would shift every
            pixel after the short row.
        legend: Symbol to colour, as `{"a": "#1b2b4a", "b": "red"}`. `"."` means leave
            that pixel alone and needs no entry; any other character can say the same
            with the value `"transparent"`, which is what the read side emits. A
            character the legend does not define is **refused**, not skipped: a typo in a
            grid would otherwise paint nothing and report success.
        x, y: Where the map's top-left corner lands on the canvas. Defaults to the
            canvas origin.
        layer: Target layer name or 1-based index (default: top layer).
        frame: Target frame, 1-based (default 1).

    Transparent cells are left untouched rather than erased, so a map can be stamped over
    existing art; clear the layer first if you want the map to be the whole of it.

    Returns the usual write counters plus `map_width`, `map_height`,
    `pixels_transparent` (cells deliberately left alone) and `colors_used`.
    """
    plan = pixelmap.expand(rows, legend, int(x), int(y))
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": None,
        # Colours are parsed here rather than in `core.pixelmap`, which stays free of
        # anything that knows what a colour is.
        "pixels": [{"x": p["x"], "y": p["y"], "c": parse_color(p["color"])}
                   for p in plan["pixels"]],
    }
    result = _draw(args, _PIXEL_WRITE_LUA)
    result["map_width"] = plan["width"]
    result["map_height"] = plan["height"]
    result["pixels_transparent"] = plan["transparent"]
    result["colors_used"] = len(plan["colors_used"])
    return result


@_geometry_tool
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
        antialias: Smooth (Xiaolin Wu) line with alpha blending, RGB sprites only;
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


@_geometry_tool
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
        raise ValidationFailed("Need at least 2 points.")
    check_list_length("points", points, MAX_PIXEL_LIST_LENGTH)
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


@_geometry_tool
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
    steps = check_count(
        "steps", max(2, int(steps)), MAX_CURVE_STEPS, minimum=2,
        remedy="Steps beyond the curve's length in pixels add no detail.",
    )
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "x0": int(x0), "y0": int(y0),
        "cx": int(control_x), "cy": int(control_y),
        "x1": int(x1), "y1": int(y1),
        "steps": steps,
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


@_geometry_tool
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


@_geometry_tool
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

    For a circle, use the same value for radius_x and radius_y. filled=False draws a 1px
    outline, and a filled ellipse is exactly that outline with its interior: the two are
    one shape rendered two ways, so a fill and an outline of the same call line up.
    antialias smooths a *filled* ellipse with sub-pixel coverage (RGB sprites only;
    ignored otherwise).
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


@_geometry_tool
def draw_ellipse_in_box(
    filename: str,
    x: int,
    y: int,
    width: int,
    height: int,
    color: str,
    filled: bool = False,
    antialias: bool = False,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw an ellipse that fills the given bounding box exactly.

    Takes the same box as draw_rectangle, so the two share a centre and an extent: this is
    how to draw a disc centred on an even canvas, or a circle that lines up with a
    rectangle. draw_ellipse takes a centre and radii instead, which can only ever be an odd
    2*radius+1 across.

    An even side is drawn the way it is drawn by hand: the odd ellipse one pixel smaller,
    with its middle row or column repeated. Give an odd width and height and the result is
    pixel for pixel what draw_ellipse produces for the same shape, because both use the
    same geometry.

    filled=False draws a 1px outline. antialias smooths a *filled* ellipse with sub-pixel
    coverage (RGB sprites only; ignored otherwise).
    """
    if int(width) < 1 or int(height) < 1:
        raise ValidationFailed(
            f"width and height must be at least 1; got {width}x{height}. They are pixel "
            "counts, like draw_rectangle's."
        )
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "color": parse_color(color),
        "x": int(x), "y": int(y), "w": int(width), "h": int(height),
        "filled": bool(filled),
        "antialias": bool(antialias),
    }
    snippet = """
    local c = ARG.color
    local w, h = ARG.w, ARG.h
    if ARG.antialias and ARG.filled and spr.colorMode == ColorMode.RGB then
      -- The antialiased fill samples in continuous coordinates, so a centre that falls
      -- between two pixels is nothing special to it: hand it the box's true centre.
      aa_ellipse_fill_img(spr, img, ARG.x + (w - 1) / 2, ARG.y + (h - 1) / 2,
                          w / 2, h / 2, c.r, c.g, c.b)
    else
      local px = to_pixel(spr, c)
      -- The largest odd ellipse that fits. An even side takes this one's middle row or
      -- column twice, which is the even circle a pixel artist draws.
      local rx = (w % 2 == 0) and ((w - 2) // 2) or ((w - 1) // 2)
      local ry = (h % 2 == 0) and ((h - 2) // 2) or ((h - 1) // 2)
      local function spread(o, size, r)
        if size % 2 == 1 then return o, nil end
        if o < r then return o, nil end
        if o == r then return r, r + 1 end
        return o + 1, nil
      end
      for _, pt in ipairs(ellipse_offsets(rx, ry, ARG.filled)) do
        local x1, x2 = spread(pt[1] + rx, w, rx)
        local y1, y2 = spread(pt[2] + ry, h, ry)
        img_set(img, ARG.x + x1, ARG.y + y1, px)
        if x2 ~= nil then img_set(img, ARG.x + x2, ARG.y + y1, px) end
        if y2 ~= nil then img_set(img, ARG.x + x1, ARG.y + y2, px) end
        if x2 ~= nil and y2 ~= nil then img_set(img, ARG.x + x2, ARG.y + y2, px) end
      end
    end
    """
    return _draw(args, snippet)


@_geometry_tool
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
