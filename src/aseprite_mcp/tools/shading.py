"""Shading: palette-aware operations that keep a sprite on its ramp.

The tools a model reaches for when told to shade something, `adjust_brightness_contrast`
and friends, are image filters: they move every pixel to a colour that is probably not on
the palette. On a correctly shaded five-step sphere of 477 pixels, a brightness of -28
left **none** of them on the ramp, while every structural measure of the sprite was
unchanged. That is why generated pixel art stops looking like pixel art the moment it is
shaded, and it is invisible to anything except a palette check.

Shading in pixel art is a ramp-stepping operation, not a colour-arithmetic one. This is
the mechanic behind Aseprite's own Shading ink, which cannot be used here: invoking
`app.useTool{ink=Ink.SHADING}` hard-crashes batch Aseprite (exit 0xC0000005, no file
written), so it is implemented as palette index arithmetic instead.
"""

from __future__ import annotations

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import MAX_COLOR_LIST_LENGTH, check_list_length
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path

# Shared by every ramp-aware tool here: find the ramp entry a pixel belongs to.
#
# Weighted rather than plain RGB distance because the eye is far more sensitive to green
# than to blue, so an unweighted nearest-match picks visibly wrong neighbours on a
# hue-shifted ramp, which is exactly the kind of ramp pixel art uses.
_RAMP_LUA = r"""
local function ramp_match(ramp, r, g, b)
  local best, best_d2 = nil, nil
  for i = 1, #ramp do
    local c = ramp[i]
    local dr, dg, db = r - c.r, g - c.g, b - c.b
    local d2 = 0.299 * dr * dr + 0.587 * dg * dg + 0.114 * db * db
    if best_d2 == nil or d2 < best_d2 then best, best_d2 = i, d2 end
  end
  return best, math.sqrt(best_d2)
end
"""


@mcp.tool()
def shift_along_ramp(
    filename: str,
    ramp: list[str],
    steps: int,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    tolerance: float = 48.0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Move pixels along a colour ramp, keeping every one of them on the palette.

    This is the operation to use for "put this in shadow", "make the night variant" or
    "deepen the shadow side". Each pixel is matched to its nearest ramp entry, moved
    `steps` along the ramp, and clamped at the ends, so the result uses only colours
    that were already on the ramp.

    Prefer this over `adjust_brightness_contrast` for anything that should still look
    like pixel art: that tool does colour arithmetic and lands almost every pixel
    between palette entries.

    Args:
        ramp: The ramp, darkest first, as produced by `generate_ramp`. Order matters:
            negative `steps` moves toward the front of this list.
        steps: How far to move. Negative darkens (toward the front of `ramp`), positive
            lightens. Pixels already at an end stay there rather than wrapping.
        x, y, width, height: Restrict the change to a region. Defaults to the whole
            canvas. Scope this when a sprite has several materials: one ramp applied to
            everything flattens steel, brass and leather into the same colours.
        tolerance: How far a pixel may be from a ramp entry and still be treated as
            belonging to it, as a weighted RGB distance. Pixels further away than this
            are left alone and counted in `pixels_skipped`, so shading one material does
            not disturb its neighbours.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    Returns `pixels_written` and `pixels_skipped`. A high skip count usually means the
    ramp does not match the artwork, not that the sprite was already correct.
    """
    if len(ramp) < 2:
        raise ValidationFailed("ramp needs at least 2 colours to shift along.")
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if steps == 0:
        raise ValidationFailed(
            "steps must be non-zero; a shift of 0 would rewrite every pixel to its "
            "nearest ramp entry, which is a palette snap rather than a shade. Use a "
            "negative value to darken or a positive one to lighten."
        )
    if tolerance < 0:
        raise ValidationFailed("tolerance must not be negative.")

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "steps": int(steps),
        "x": int(x), "y": int(y), "width": width, "height": height,
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)

    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)
    local ramp = ARG.ramp
    local matched = 0

    for yy = ry, ry + rh - 1 do
      for xx = rx, rx + rw - 1 do
        if xx >= 0 and yy >= 0 and xx < img.width and yy < img.height then
          local r, g, b, a = px_to_rgba(spr, img:getPixel(xx, yy))
          if a > 0 then
            local idx, dist = ramp_match(ramp, r, g, b)
            if dist <= ARG.tolerance then
              local target = idx + ARG.steps
              -- Clamped, not wrapped: a shadow that wraps to the highlight is never
              -- what was meant, and silently produces the opposite of the request.
              if target < 1 then target = 1 end
              if target > #ramp then target = #ramp end
              local c = ramp[target]
              -- Alpha is carried through untouched: shading must not alter a
              -- silhouette, including anti-aliased edge pixels.
              img_set(img, xx, yy, rgba_to_px(spr, c.r, c.g, c.b, a))
              matched = matched + 1
            else
              note_skipped()
            end
          end
        end
      end
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name,
               frame = framenum, steps = ARG.steps, ramp_size = #ramp,
               pixels_matched = matched }
    """
    return run_lua(body, args)


# Chamfer distance transform plus a Lambert term, shared by the form-shading tools.
#
# The distance field is what makes this follow the form rather than the outline. A naive
# "offset the silhouette inward" produces concentric bands, which is pillow shading: the
# classic amateur result, and the one you get from stacking offset ellipses, which is the
# most natural thing to reach for with the existing tools.
_FIELD_LUA = r"""
-- Two-pass chamfer with 3-4 weights. Exact Euclidean distance is not worth it here: the
-- field feeds a lighting term that is then quantised into a handful of ramp steps, so
-- sub-pixel accuracy is discarded immediately.
local function distance_field(mask, w, h)
  local INF = 1e9
  local d = {}
  for y = 0, h - 1 do
    d[y] = {}
    for x = 0, w - 1 do
      d[y][x] = mask[y][x] and INF or 0
    end
  end
  for y = 0, h - 1 do
    for x = 0, w - 1 do
      if d[y][x] > 0 then
        local best = d[y][x]
        if y > 0 then
          if d[y-1][x] + 3 < best then best = d[y-1][x] + 3 end
          if x > 0 and d[y-1][x-1] + 4 < best then best = d[y-1][x-1] + 4 end
          if x < w-1 and d[y-1][x+1] + 4 < best then best = d[y-1][x+1] + 4 end
        end
        if x > 0 and d[y][x-1] + 3 < best then best = d[y][x-1] + 3 end
        d[y][x] = best
      end
    end
  end
  local maxd = 0
  for y = h - 1, 0, -1 do
    for x = w - 1, 0, -1 do
      if d[y][x] > 0 then
        local best = d[y][x]
        if y < h-1 then
          if d[y+1][x] + 3 < best then best = d[y+1][x] + 3 end
          if x > 0 and d[y+1][x-1] + 4 < best then best = d[y+1][x-1] + 4 end
          if x < w-1 and d[y+1][x+1] + 4 < best then best = d[y+1][x+1] + 4 end
        end
        if x < w-1 and d[y][x+1] + 3 < best then best = d[y][x+1] + 3 end
        d[y][x] = best
        if best > maxd then maxd = best end
      end
    end
  end
  return d, maxd / 3.0
end
"""


@mcp.tool()
def shade_region_by_light(
    filename: str,
    ramp: list[str],
    base_color: str | None = None,
    light_angle: float = 135.0,
    light_z: float = 0.45,
    bulge: float = 1.0,
    ambient: float = 0.35,
    rim: float = 0.0,
    bias: float = 0.0,
    tolerance: float = 24.0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Shade a flat region as a lit form, using a ramp and a light direction.

    Turns a flat fill into a shaded one: an asymmetric terminator, a darker core away
    from the light, and optional rim light. Every output pixel comes from `ramp`.

    Scope this to one material. Shading a whole layer flattens materials together: a
    sword shaded in one pass turns steel, brass and leather into the same colours, where
    three scoped calls keep all three. Scope it by passing `base_color`, by making a
    selection first (`select_by_color` is the usual way), or both.

    What it cannot do: a distance field measures depth inside a silhouette, so it cannot
    invent form boundaries that are not in the outline. An overlapping head and torso
    drawn as one flat shape become one mass. Shade them as separate regions.

    Args:
        ramp: Colours darkest first, as from `generate_ramp`. Output uses only these.
        base_color: Only shade pixels near this colour. Defaults to every opaque pixel
            in scope, which is usually what you want once a selection is active.
        light_angle: Degrees. 0 is from the right, 90 from above, 135 from the upper
            left, which is the conventional pixel-art key light.
        light_z: How much the light comes from the viewer, 0 to 1. Higher flattens the
            terminator and lights more of the form.
        bulge: How rounded the form reads. 1.0 is sphere-like; lower is flatter, which
            suits cloth and flat panels; higher exaggerates the curvature.
        ambient: Floor brightness in shadow, 0 to 1. Pixel art rarely wants true black
            in shadow, so this sits well above zero by default.
        rim: Light wrapping the edge away from the key, 0 to 1. A little reads as a
            bounce; a lot reads as backlight.
        bias: Shift the whole result along the ramp, in steps. Use this when the result
            is uniformly a shade too dark or light, rather than re-tuning the lighting.
        tolerance: How close a pixel must be to `base_color` to count as part of the
            region, as a weighted RGB distance. Ignored when `base_color` is omitted.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    Refuses a region with no interior to shade: below roughly 6px across, the distance
    field never exceeds a pixel and there is no form to describe. The honest answer
    there is two hand-placed pixels, which `draw_pixels` already does.
    """
    if len(ramp) < 3:
        raise ValidationFailed(
            "ramp needs at least 3 colours to shade a form; with two there is nothing "
            "between the highlight and the shadow."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if not 0.0 <= ambient <= 1.0:
        raise ValidationFailed("ambient must be between 0 and 1.")
    if not 0.0 <= rim <= 1.0:
        raise ValidationFailed("rim must be between 0 and 1.")
    if not 0.0 <= light_z <= 1.0:
        raise ValidationFailed("light_z must be between 0 and 1.")
    if bulge <= 0:
        raise ValidationFailed("bulge must be greater than 0.")
    if tolerance < 0:
        raise ValidationFailed("tolerance must not be negative.")

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "base": parse_color(base_color) if base_color else None,
        "angle": float(light_angle),
        "light_z": float(light_z),
        "bulge": float(bulge),
        "ambient": float(ambient),
        "rim": float(rim),
        "bias": float(bias),
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + _FIELD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    local W, H = img.width, img.height
    local ramp = ARG.ramp
    local base = ARG.base

    -- The region: opaque, near base_color when one was given, and inside the selection
    -- when one is active. Restricting the field to the selection matters: a field over
    -- the whole silhouette would measure depth into pixels this call may not touch, and
    -- would light the wrong shape.
    local mask = {}
    local count = 0
    for y = 0, H - 1 do
      mask[y] = {}
      for x = 0, W - 1 do
        local inside = false
        local r, g, b, a = px_to_rgba(spr, img:getPixel(x, y))
        if a > 0 and (_sel == nil or _sel:contains(x, y)) then
          if base == nil then
            inside = true
          else
            local dr, dg, db = r - base.r, g - base.g, b - base.b
            local d = math.sqrt(0.299*dr*dr + 0.587*dg*dg + 0.114*db*db)
            inside = d <= ARG.tolerance
          end
        end
        mask[y][x] = inside
        if inside then count = count + 1 end
      end
    end

    if count == 0 then
      error("Nothing to shade: no pixel matched. Check base_color and tolerance, or " ..
            "whether a selection is excluding the region.")
    end

    local field, maxd = distance_field(mask, W, H)
    if maxd < 2.0 then
      error(string.format(
        "This region is too thin to shade: its deepest point is %.1f pixels from an " ..
        "edge, so there is no interior to describe. Place the highlight and shadow by " ..
        "hand with draw_pixels instead.", maxd))
    end

    -- Screen y grows downward, so an upward light is negative in y.
    local rad = math.rad(ARG.angle)
    local lx, ly, lz = math.cos(rad), -math.sin(rad), ARG.light_z
    local ll = math.sqrt(lx*lx + ly*ly + lz*lz)
    lx, ly, lz = lx/ll, ly/ll, lz/ll

    -- Height from the distance field, as a quarter-circle profile: steep near the edge
    -- and flat in the middle, which is what a round form does. The gradient of that
    -- gives a normal following the form rather than the outline, which is the whole
    -- difference between form shading and pillow shading.
    -- The chamfer field is integer-weighted, and those steps land straight in the
    -- gradient as single-pixel speckle along every band boundary. One box pass over the
    -- in-region neighbours costs nothing and removes most of it. This is not the
    -- cluster-smoothing pass that shaping band edges properly would need; it just stops
    -- the lighting term inheriting the distance metric's own quantisation.
    local smooth = {}
    for y = 0, H - 1 do
      smooth[y] = {}
      for x = 0, W - 1 do
        if mask[y][x] then
          local total, n = 0, 0
          for dy = -1, 1 do
            for dx = -1, 1 do
              local sx, sy = x + dx, y + dy
              if sx >= 0 and sy >= 0 and sx < W and sy < H and mask[sy][sx] then
                total = total + field[sy][sx]
                n = n + 1
              end
            end
          end
          smooth[y][x] = total / n
        else
          smooth[y][x] = 0
        end
      end
    end

    local function height(x, y)
      if x < 0 or y < 0 or x >= W or y >= H or not mask[y][x] then return 0.0 end
      local t = (smooth[y][x] / 3.0) / maxd
      if t > 1 then t = 1 end
      -- Scaled by maxd, not left as 0..1. Height has to be in the same units as x and
      -- y or the gradient is vanishingly small on any region bigger than a couple of
      -- pixels, every normal points straight up, and the whole form quantises to one
      -- or two ramp steps. At bulge = 1 this makes a region of radius R exactly R tall,
      -- which is a true sphere.
      return math.sqrt(math.max(0.0, 1.0 - (1.0 - t) * (1.0 - t))) * maxd * ARG.bulge
    end

    local steps = #ramp - 1
    local shaded = 0
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        if mask[y][x] then
          local dhdx = (height(x+1, y) - height(x-1, y)) * 0.5
          local dhdy = (height(x, y+1) - height(x, y-1)) * 0.5
          local nx, ny, nz = -dhdx, -dhdy, 1.0
          local nl = math.sqrt(nx*nx + ny*ny + nz*nz)
          nx, ny, nz = nx/nl, ny/nl, nz/nl

          local ndotl = nx*lx + ny*ly + nz*lz
          if ndotl < 0 then ndotl = 0 end
          local lit = ARG.ambient + (1.0 - ARG.ambient) * ndotl

          if ARG.rim > 0 then
            -- Rim reads where the surface turns away from the viewer AND away from the
            -- key light, which is where a bounce would actually catch.
            lit = lit + ARG.rim * (1.0 - nz) * (1.0 - ndotl)
          end

          local idx = math.floor(lit * steps + ARG.bias + 0.5) + 1
          if idx < 1 then idx = 1 end
          if idx > #ramp then idx = #ramp end
          local c = ramp[idx]
          local _, _, _, a = px_to_rgba(spr, img:getPixel(x, y))
          img_set(img, x, y, rgba_to_px(spr, c.r, c.g, c.b, a))
          shaded = shaded + 1
        end
      end
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               region_pixels = count, shaded_pixels = shaded,
               depth = maxd, ramp_size = #ramp }
    """
    return run_lua(body, args)
