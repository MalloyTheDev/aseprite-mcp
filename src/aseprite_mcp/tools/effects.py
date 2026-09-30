"""Effects & adjustments: gradients, outline, drop shadow, colour replace,
invert, brightness/contrast, hue/saturation, desaturate, checkerboard.

The cel-editing tools reuse the drawing harness (open -> edit full-canvas image
-> commit -> save). Adjustments are implemented as deterministic per-pixel passes
so they are scoped exactly to the chosen layer + frame and behave identically on
every Aseprite version.
"""

from __future__ import annotations

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import MAX_OUTLINE_THICKNESS, check_count, check_region_size
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path
from .drawing import _draw

_GRAD_TYPES = {"linear", "radial"}


@mcp.tool()
def fill_gradient(
    filename: str,
    colors: list[str],
    gradient_type: str = "linear",
    angle: float = 0.0,
    dither: bool = False,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    layer: str | None = None,
    frame: int = 1,
    respect_alpha: bool = True,
) -> dict:
    """Fill a region with a gradient, by default only where pixels already exist.

    Args:
        colors: 2+ colour stops, e.g. ["#000000", "#ff004d", "#ffec27"], spread
            evenly. For dither=True, provide exactly 2 colours.
        gradient_type: "linear" or "radial".
        angle: Direction in degrees for linear gradients (0 = left->right).
        dither: Ordered (Bayer 4x4) dithering between 2 colours instead of smooth
            interpolation — great for limited palettes / retro looks.
        x, y, width, height: Region (defaults to the whole canvas).
        respect_alpha: Leave transparent pixels transparent (default). The gradient
            then shades the artwork inside the region rather than filling the region.
            Pass False to paint the whole rectangle, background included.

    Returns `pixels_written` and `pixels_skipped` so the caller can tell how much of
    the region was actually covered.
    """
    if gradient_type not in _GRAD_TYPES:
        raise ValidationFailed(f"gradient_type must be one of {sorted(_GRAD_TYPES)}")
    if len(colors) < 2:
        raise ValidationFailed("Provide at least 2 colour stops.")
    if dither and len(colors) != 2:
        raise ValidationFailed("Dithered gradients require exactly 2 colours.")
    check_region_size(width, height, field="gradient region")
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "colors": [parse_color(c) for c in colors],
        "gradient_type": gradient_type,
        "angle": float(angle),
        "dither": bool(dither),
        "x": int(x), "y": int(y), "width": width, "height": height,
        "respect_alpha": bool(respect_alpha),
    }
    snippet = """
    local stops = ARG.colors
    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)
    local function lerp(a, b, t) return a + (b - a) * t end
    local function color_at(t)
      if t < 0 then t = 0 elseif t > 1 then t = 1 end
      local n = #stops
      local seg = t * (n - 1)
      local i = math.floor(seg) + 1
      if i >= n then i = n - 1 end
      local f = seg - (i - 1)
      local a, b = stops[i], stops[i + 1]
      return { r = lerp(a.r, b.r, f), g = lerp(a.g, b.g, f),
               b = lerp(a.b, b.b, f), a = lerp(a.a or 255, b.a or 255, f) }
    end
    local rad = math.rad(ARG.angle)
    local dx, dy = math.cos(rad), math.sin(rad)
    local function proj(px, py) return px * dx + py * dy end
    local c1, c2 = proj(rx, ry), proj(rx + rw - 1, ry)
    local c3, c4 = proj(rx, ry + rh - 1), proj(rx + rw - 1, ry + rh - 1)
    local pmin = math.min(c1, c2, c3, c4)
    local pmax = math.max(c1, c2, c3, c4)
    local span = pmax - pmin
    if span == 0 then span = 1 end
    local cxp, cyp = rx + rw / 2, ry + rh / 2
    local maxr = math.sqrt((rw / 2) ^ 2 + (rh / 2) ^ 2)
    if maxr == 0 then maxr = 1 end
    local BAYER = { {0,8,2,10}, {12,4,14,6}, {3,11,1,9}, {15,7,13,5} }
    for yy = ry, ry + rh - 1 do
      for xx = rx, rx + rw - 1 do
        if xx >= 0 and yy >= 0 and xx < spr.width and yy < spr.height then
          local t
          if ARG.gradient_type == "radial" then
            t = math.sqrt((xx - cxp) ^ 2 + (yy - cyp) ^ 2) / maxr
          else
            t = (proj(xx, yy) - pmin) / span
          end
          if t < 0 then t = 0 elseif t > 1 then t = 1 end
          local px
          if ARG.dither then
            local thr = (BAYER[(yy % 4) + 1][(xx % 4) + 1] + 0.5) / 16
            px = to_pixel(spr, (t < thr) and stops[1] or stops[2])
          else
            px = to_pixel(spr, color_at(t))
          end
          -- Guarded on the pixel's existing alpha. Writing unconditionally filled
          -- the transparent area around the artwork as well as the artwork, so the
          -- most natural way to shade a sprite silently destroyed its silhouette:
          -- a 32x32 sphere of 477 opaque pixels came back with 584.
          if (not ARG.respect_alpha) or img_solid(spr, img, xx, yy) then
            img_set(img, xx, yy, px)
          else
            note_skipped()
          end
        end
      end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def add_outline(
    filename: str,
    color: str,
    thickness: int = 1,
    connectivity: int = 8,
    where: str = "outside",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Add a pixel outline around the artwork on a layer.

    Args:
        color: Outline colour.
        thickness: Outline width in pixels (default 1).
        connectivity: 4 (orthogonal only) or 8 (includes diagonals, default).
        where: "outside" (grow into transparency, default) or "inside"
            (recolour the shape's border pixels).
    """
    if connectivity not in (4, 8):
        raise ValidationFailed("connectivity must be 4 or 8")
    if where not in ("outside", "inside"):
        raise ValidationFailed('where must be "outside" or "inside"')
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "thickness": check_count(
            "thickness", max(1, int(thickness)), MAX_OUTLINE_THICKNESS, minimum=1,
            remedy="Each pixel of thickness is another full-canvas pass; outline in "
                   "several calls if you really need more.",
        ),
        "connectivity": connectivity,
        "where": where,
    }
    snippet = """
    local oc = to_pixel(spr, ARG.color)
    local conn8 = (ARG.connectivity == 8)
    local function neighbors(x, y)
      local n = { {x-1,y}, {x+1,y}, {x,y-1}, {x,y+1} }
      if conn8 then
        n[#n+1]={x-1,y-1}; n[#n+1]={x+1,y-1}; n[#n+1]={x-1,y+1}; n[#n+1]={x+1,y+1}
      end
      return n
    end
    for _pass = 1, ARG.thickness do
      local mark = {}
      for yy = 0, img.height - 1 do
        for xx = 0, img.width - 1 do
          local solid = img_solid(spr, img, xx, yy)
          if ARG.where == "inside" and solid then
            for _, nb in ipairs(neighbors(xx, yy)) do
              if not img_solid(spr, img, nb[1], nb[2]) then mark[#mark+1] = {xx, yy}; break end
            end
          elseif ARG.where == "outside" and not solid then
            for _, nb in ipairs(neighbors(xx, yy)) do
              if img_solid(spr, img, nb[1], nb[2]) then mark[#mark+1] = {xx, yy}; break end
            end
          end
        end
      end
      for _, p in ipairs(mark) do img:drawPixel(p[1], p[2], oc) end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def add_drop_shadow(
    filename: str,
    layer: str,
    offset_x: int = 1,
    offset_y: int = 1,
    color: str = "#00000080",
    opacity: int = 255,
    frame: int = 1,
) -> dict:
    """Add a hard drop shadow for a layer's artwork on a new layer placed beneath it.

    Args:
        layer: The layer casting the shadow.
        offset_x, offset_y: Shadow offset in pixels.
        color: Shadow colour (often semi-transparent black, the default).
        opacity: Opacity (0-255) of the shadow layer.
        frame: Frame to build the shadow for.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "dx": int(offset_x), "dy": int(offset_y),
        "color": parse_color(color),
        "opacity": max(0, min(255, int(opacity))),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local target = find_layer(spr, ARG.layer)
    if target.isGroup then error("Cannot shadow a group layer: " .. target.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local src = get_draw_image(spr, target, framenum)
    local shadow = Image(spr.spec); shadow:clear()
    local sc = to_pixel(spr, ARG.color)
    for yy = 0, src.height - 1 do
      for xx = 0, src.width - 1 do
        if img_solid(spr, src, xx, yy) then img_set(shadow, xx + ARG.dx, yy + ARG.dy, sc) end
      end
    end
    local slayer = spr:newLayer()
    slayer.name = target.name .. " shadow"
    slayer.opacity = ARG.opacity
    slayer.stackIndex = target.stackIndex
    spr:newCel(slayer, framenum, shadow, Point(0, 0))
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def replace_color(
    filename: str,
    from_color: str,
    to_color: str,
    tolerance: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Replace every pixel matching `from_color` (within `tolerance` per channel)
    with `to_color`, on the chosen layer + frame."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "from": parse_color(from_color),
        "to": parse_color(to_color),
        "tolerance": max(0, int(tolerance)),
    }
    snippet = """
    local fc = ARG["from"]
    local fr, fg, fb, fa
    if fc.index ~= nil then
      local col = spr.palettes[1]:getColor(fc.index)
      fr, fg, fb, fa = col.red, col.green, col.blue, col.alpha
    else
      fr, fg, fb, fa = fc.r, fc.g, fc.b, fc.a or 255
    end
    local tol = ARG.tolerance
    local tp = to_pixel(spr, ARG.to)
    for yy = 0, img.height - 1 do
      for xx = 0, img.width - 1 do
        local r, g, b, a = px_to_rgba(spr, img:getPixel(xx, yy))
        if math.abs(r-fr) <= tol and math.abs(g-fg) <= tol
           and math.abs(b-fb) <= tol and math.abs(a-fa) <= tol then
          img:drawPixel(xx, yy, tp)
        end
      end
    end
    """
    return _draw(args, snippet)


def _pixel_pass(snippet_inner: str) -> str:
    """Wrap a per-pixel transform that reads r,g,b,a and assigns nr,ng,nb,na."""
    return f"""
    for yy = 0, img.height - 1 do
      for xx = 0, img.width - 1 do
        local r, g, b, a = px_to_rgba(spr, img:getPixel(xx, yy))
        if a > 0 then
          local nr, ng, nb, na = r, g, b, a
          {snippet_inner}
          img:drawPixel(xx, yy, rgba_to_px(spr, nr, ng, nb, na))
        end
      end
    end
    """


@mcp.tool()
def invert_colors(filename: str, layer: str | None = None, frame: int = 1) -> dict:
    """Invert the RGB colours of a layer's pixels (alpha preserved)."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frame": int(frame)}
    return _draw(args, _pixel_pass("nr = 255 - r; ng = 255 - g; nb = 255 - b"))


@mcp.tool()
def adjust_brightness_contrast(
    filename: str,
    brightness: int = 0,
    contrast: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Adjust brightness (-255..255, additive) and contrast (-255..255) of a layer."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "brightness": max(-255, min(255, int(brightness))),
        "contrast": max(-255, min(255, int(contrast))),
    }
    inner = """
    local cf = (259 * (ARG.contrast + 255)) / (255 * (259 - ARG.contrast))
    nr = cf * (r - 128) + 128 + ARG.brightness
    ng = cf * (g - 128) + 128 + ARG.brightness
    nb = cf * (b - 128) + 128 + ARG.brightness
    """
    return _draw(args, _pixel_pass(inner))


@mcp.tool()
def adjust_hue_saturation(
    filename: str,
    hue: int = 0,
    saturation: int = 0,
    lightness: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Shift hue (degrees) and scale saturation/lightness (percent, -100..100)."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "hue": int(hue),
        "saturation": int(saturation),
        "lightness": int(lightness),
    }
    inner = """
    local mx = math.max(r, g, b) / 255
    local mn = math.min(r, g, b) / 255
    local L = (mx + mn) / 2
    local H, S = 0, 0
    local d = mx - mn
    if d > 0 then
      S = (L > 0.5) and (d / (2 - mx - mn)) or (d / (mx + mn))
      local rr, gg, bb = r / 255, g / 255, b / 255
      if mx == rr then H = (gg - bb) / d + (gg < bb and 6 or 0)
      elseif mx == gg then H = (bb - rr) / d + 2
      else H = (rr - gg) / d + 4 end
      H = H / 6
    end
    H = (H + ARG.hue / 360) % 1
    if H < 0 then H = H + 1 end
    S = S * (1 + ARG.saturation / 100); if S < 0 then S = 0 elseif S > 1 then S = 1 end
    L = L * (1 + ARG.lightness / 100); if L < 0 then L = 0 elseif L > 1 then L = 1 end
    local function h2(p, q, t)
      if t < 0 then t = t + 1 end
      if t > 1 then t = t - 1 end
      if t < 1/6 then return p + (q - p) * 6 * t end
      if t < 1/2 then return q end
      if t < 2/3 then return p + (q - p) * (2/3 - t) * 6 end
      return p
    end
    if S == 0 then
      nr = L * 255; ng = L * 255; nb = L * 255
    else
      local q = (L < 0.5) and (L * (1 + S)) or (L + S - L * S)
      local p = 2 * L - q
      nr = h2(p, q, H + 1/3) * 255
      ng = h2(p, q, H) * 255
      nb = h2(p, q, H - 1/3) * 255
    end
    """
    return _draw(args, _pixel_pass(inner))


@mcp.tool()
def desaturate(
    filename: str, amount: int = 100, layer: str | None = None, frame: int = 1
) -> dict:
    """Desaturate toward grayscale by `amount` percent (0-100)."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "amount": max(0, min(100, int(amount))),
    }
    inner = """
    local gray = 0.299 * r + 0.587 * g + 0.114 * b
    local f = ARG.amount / 100
    nr = r + (gray - r) * f
    ng = g + (gray - g) * f
    nb = b + (gray - b) * f
    """
    return _draw(args, _pixel_pass(inner))


@mcp.tool()
def fill_checkerboard(
    filename: str,
    color1: str,
    color2: str,
    size: int = 1,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Fill a region with a 2-colour checkerboard of `size`-pixel squares."""
    check_region_size(width, height, field="checkerboard region")
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "c1": parse_color(color1), "c2": parse_color(color2),
        "size": max(1, int(size)),
        "x": int(x), "y": int(y), "width": width, "height": height,
    }
    snippet = """
    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)
    local p1 = to_pixel(spr, ARG.c1)
    local p2 = to_pixel(spr, ARG.c2)
    local s = ARG.size
    for yy = ry, ry + rh - 1 do
      for xx = rx, rx + rw - 1 do
        if xx >= 0 and yy >= 0 and xx < spr.width and yy < spr.height then
          local cell = (math.floor((xx - rx) / s) + math.floor((yy - ry) / s)) % 2
          img_set(img, xx, yy, (cell == 0) and p1 or p2)
        end
      end
    end
    """
    return _draw(args, snippet)


@mcp.tool()
def remove_stray_pixels(
    filename: str,
    layer: str | None = None,
    frame: int = 1,
    protect: list[str] | None = None,
) -> dict:
    """Replace pixels that have no neighbour of their own colour with the colour around them.

    A stray pixel is one whose eight neighbours are all a different colour. They are what
    a shading pass leaves behind at a band boundary, and at any zoom they read as dirt
    rather than as texture. `assess_sprite` counts them as `isolated_pixels`; this is what
    to do about the count.

    Each stray takes the most common colour among its opaque neighbours, so **no new
    colour can appear**: the result uses a subset of the colours already there, and art on
    a ramp stays on it. Transparent pixels are left alone, so the silhouette does not
    change.

    Args:
        protect: Colours never to replace. A one-pixel eye highlight or a specular dot is
            a stray by this definition and is meant to be there, so name its colour.

    A pixel whose only same-colour neighbour is **diagonal** is part of a dither pattern,
    not dirt, and is left alone. `assess_sprite` counts isolation orthogonally, which is
    the stricter reading, so a dithered sprite still reports some `isolated_pixels` after
    this has run and that count is the dithering rather than anything to fix.

    This is not Aseprite's own Despeckle, which is a median filter: that one averages
    neighbourhoods, introduces colours that were not in the palette, and on a measured
    test left *more* stray pixels than it found. This changes only the pixels that are
    strays, and only to colours already next to them.

    Returns how many were replaced, so a second call can be skipped when it says 0.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "protect": [parse_color(c) for c in (protect or [])],
    }
    snippet = """
    local protected = {}
    for _, colour in ipairs(ARG.protect) do
      protected[to_pixel(spr, colour)] = true
    end

    -- Read first, write after: a stray replaced mid-pass would become a neighbour that
    -- rescues the next one, and the result would depend on scan order.
    local w, h = img.width, img.height
    local replacements, count = {}, 0
    for y = 0, h - 1 do
      for x = 0, w - 1 do
        local here = img:getPixel(x, y)
        if img_solid(spr, img, x, y) and not protected[here] then
          local tally, best, best_n, alone = {}, nil, 0, true
          for dy = -1, 1 do
            for dx = -1, 1 do
              if not (dx == 0 and dy == 0) then
                local nx, ny = x + dx, y + dy
                if nx >= 0 and ny >= 0 and nx < w and ny < h then
                  local other = img:getPixel(nx, ny)
                  if other == here then
                    alone = false
                  elseif img_solid(spr, img, nx, ny) then
                    local n = (tally[other] or 0) + 1
                    tally[other] = n
                    if n > best_n then best, best_n = other, n end
                  end
                end
              end
            end
          end
          if alone and best ~= nil then
            count = count + 1
            replacements[count] = { x = x, y = y, px = best }
          end
        end
      end
    end

    for _, item in ipairs(replacements) do
      img_set(img, item.x, item.y, item.px)
    end
    _stray_replaced = count
    """
    return _draw(args, snippet)
