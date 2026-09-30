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
from ..core.limits import (
    MAX_COLOR_LIST_LENGTH,
    MAX_OUTLINE_THICKNESS,
    check_list_length,
)
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


@mcp.tool()
def contact_shadow(
    filename: str,
    ramp: list[str],
    occluder_color: str,
    radius: int = 1,
    depth: int = 1,
    direction: float | None = None,
    tolerance: float = 24.0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Darken the pixels where one form meets another, along its ramp.

    Ambient occlusion as pixel artists actually draw it: a line one or two steps darker
    where two shapes touch. It is what stops a shaded object looking like it is floating
    in front of the thing it is standing on.

    Args:
        ramp: Colours darkest first. Darkened pixels stay on this ramp.
        occluder_color: The colour of the form casting the occlusion, for example the
            ground a character stands on, or the blade a crossguard meets.
        radius: How far the darkening reaches from the occluder, in pixels. 1 or 2 is
            usually right; beyond that it reads as a drop shadow rather than contact.
        depth: How many ramp steps darker, at the contact line. 1 is the common choice.
        direction: Degrees, restricting occlusion to one side. Omit for all directions,
            which is what you want for a contact line; set it when only one side of the
            form is actually touching something.
        tolerance: How close a pixel must be to a ramp entry to be darkened. Pixels
            further away are left alone, so this does not spill onto other materials.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.
    """
    if len(ramp) < 2:
        raise ValidationFailed("ramp needs at least 2 colours.")
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if not 1 <= radius <= MAX_OUTLINE_THICKNESS:
        raise ValidationFailed(
            f"radius must be between 1 and {MAX_OUTLINE_THICKNESS}; a contact shadow "
            "reaching further than a couple of pixels is a drop shadow."
        )
    if depth < 1:
        raise ValidationFailed("depth must be at least 1 ramp step.")
    if tolerance < 0:
        raise ValidationFailed("tolerance must not be negative.")

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "occluder": parse_color(occluder_color),
        "radius": int(radius),
        "depth": int(depth),
        "direction": None if direction is None else float(direction),
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    local W, H = img.width, img.height
    local ramp, occ = ARG.ramp, ARG.occluder
    local R = ARG.radius

    -- Which pixels are the occluder. Sampled once up front rather than per neighbour
    -- lookup, because the inner loop reads every pixel in the radius around every
    -- candidate and re-decoding each one is the whole cost of the tool.
    local is_occ = {}
    local occ_count = 0
    for y = 0, H - 1 do
      is_occ[y] = {}
      for x = 0, W - 1 do
        local r, g, b, a = px_to_rgba(spr, img:getPixel(x, y))
        local hit = false
        if a > 0 then
          local dr, dg, db = r - occ.r, g - occ.g, b - occ.b
          hit = math.sqrt(0.299*dr*dr + 0.587*dg*dg + 0.114*db*db) <= ARG.tolerance
        end
        is_occ[y][x] = hit
        if hit then occ_count = occ_count + 1 end
      end
    end

    if occ_count == 0 then
      error("No pixel matched occluder_color, so there is no contact to shade. " ..
            "Check the colour, or raise tolerance.")
    end

    local dirx, diry
    if ARG.direction ~= nil then
      local rad = math.rad(ARG.direction)
      dirx, diry = math.cos(rad), -math.sin(rad)
    end

    local darkened = 0
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        if not is_occ[y][x] then
          local r, g, b, a = px_to_rgba(spr, img:getPixel(x, y))
          if a > 0 then
            -- Nearest occluder within the radius, so the darkening falls off with
            -- distance instead of being a hard band.
            local nearest = nil
            for dy = -R, R do
              for dx = -R, R do
                local sx, sy = x + dx, y + dy
                if sx >= 0 and sy >= 0 and sx < W and sy < H and is_occ[sy][sx] then
                  local d = math.sqrt(dx*dx + dy*dy)
                  if d <= R and (nearest == nil or d < nearest) then
                    if dirx == nil then
                      nearest = d
                    elseif (dx * dirx + dy * diry) > 0 then
                      -- Only count occluders lying in the given direction, so a
                      -- character standing on ground is occluded from below and not
                      -- all round.
                      nearest = d
                    end
                  end
                end
              end
            end

            if nearest ~= nil then
              local idx, dist = ramp_match(ramp, r, g, b)
              if dist <= ARG.tolerance then
                -- Full depth at the contact line, tapering to nothing at the radius.
                local falloff = 1.0 - (nearest - 1) / math.max(1, R)
                if falloff > 1 then falloff = 1 end
                local steps = math.floor(ARG.depth * falloff + 0.5)
                if steps > 0 then
                  local target = idx - steps
                  if target < 1 then target = 1 end
                  if target ~= idx then
                    local c = ramp[target]
                    img_set(img, x, y, rgba_to_px(spr, c.r, c.g, c.b, a))
                    darkened = darkened + 1
                  end
                end
              else
                note_skipped()
              end
            end
          end
        end
      end
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               occluder_pixels = occ_count, darkened_pixels = darkened }
    """
    return run_lua(body, args)


@mcp.tool()
def outline_smart(
    filename: str,
    ramp: list[str],
    mode: str = "colormatched",
    darken_steps: int = 2,
    light_angle: float | None = None,
    tolerance: float = 32.0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Outline a shape in colours drawn from its own ramp, not one flat colour.

    `add_outline` paints a single colour all the way round, which reads as a sticker.
    Pixel artists vary the outline: darker where the form turns away from the light,
    and often dropped entirely on the lit side so the shape breathes.

    Args:
        ramp: Colours darkest first. Outline pixels come from here.
        mode: "colormatched" takes each outline pixel from the adjacent interior colour
            shifted `darken_steps` down the ramp. "selective" does the same but leaves
            the lit side unoutlined, which needs `light_angle`. "single" uses the
            darkest ramp entry all round, the classic look.
        darken_steps: How many ramp steps below the neighbouring interior colour.
        light_angle: Degrees, required for "selective". 135 is the usual key light.
        tolerance: How close an interior pixel must be to a ramp entry to be used as
            the source for its outline pixel.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    The outline is drawn outside the silhouette, into transparency, so it never eats
    into the artwork.
    """
    if mode not in ("colormatched", "selective", "single"):
        raise ValidationFailed(
            'mode must be "colormatched", "selective" or "single".'
        )
    if len(ramp) < 2:
        raise ValidationFailed("ramp needs at least 2 colours.")
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if mode == "selective" and light_angle is None:
        raise ValidationFailed(
            'mode="selective" needs light_angle: it drops the outline on the lit side, '
            "so it has to know which side that is."
        )
    if darken_steps < 1:
        raise ValidationFailed("darken_steps must be at least 1.")

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "mode": mode,
        "darken": int(darken_steps),
        "angle": None if light_angle is None else float(light_angle),
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot outline a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    local W, H = img.width, img.height
    local ramp = ARG.ramp

    local lx, ly
    if ARG.angle ~= nil then
      local rad = math.rad(ARG.angle)
      lx, ly = math.cos(rad), -math.sin(rad)
    end

    -- Collected first, written after: growing the silhouette while reading it would
    -- let the outline seed more outline and creep outwards.
    local pending = {}
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        if not img_solid(spr, img, x, y) then
          local best_c, best_dot = nil, nil
          for dy = -1, 1 do
            for dx = -1, 1 do
              if not (dx == 0 and dy == 0) then
                local sx, sy = x + dx, y + dy
                if img_solid(spr, img, sx, sy) then
                  -- dot > 0 means this neighbour lies toward the light from here, so
                  -- the outline pixel is on the shape's lit side.
                  local dot = 0
                  if lx ~= nil then dot = (-dx) * lx + (-dy) * ly end
                  if best_dot == nil or dot > best_dot then
                    best_dot = dot
                    local r, g, b = px_to_rgba(spr, img:getPixel(sx, sy))
                    best_c = { r = r, g = g, b = b }
                  end
                end
              end
            end
          end

          if best_c ~= nil then
            local skip = (ARG.mode == "selective" and best_dot ~= nil and best_dot > 0.35)
            if not skip then
              local col
              if ARG.mode == "single" then
                col = ramp[1]
              else
                local idx, dist = ramp_match(ramp, best_c.r, best_c.g, best_c.b)
                if dist <= ARG.tolerance then
                  local target = idx - ARG.darken
                  if target < 1 then target = 1 end
                  col = ramp[target]
                else
                  col = ramp[1]
                end
              end
              pending[#pending + 1] = { x = x, y = y, c = col }
            end
          end
        end
      end
    end

    for _, p in ipairs(pending) do
      img_set(img, p.x, p.y, rgba_to_px(spr, p.c.r, p.c.g, p.c.b, 255))
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               mode = ARG.mode, outline_pixels = #pending }
    """
    return run_lua(body, args)


@mcp.tool()
def dither_band(
    filename: str,
    ramp: list[str],
    from_step: int,
    to_step: int,
    pattern: str = "bayer4",
    width: int = 2,
    tolerance: float = 24.0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Dither the boundary between two adjacent ramp steps, widening the transition.

    Dithering in pixel art is a limited-palette necessity rather than a style: it buys
    an apparent extra shade between two you already have. It reads as dated when applied
    globally, which is why this is scoped to one boundary rather than offered as a
    filter over the whole sprite.

    Args:
        ramp: Colours darkest first.
        from_step, to_step: 1-based indices into `ramp`, and they must be adjacent.
            Dithering between distant steps produces visible noise, not a gradient.
        pattern: "bayer4" (finest, the usual choice), "bayer2" (chunkier) or "checker"
            (a hard 50/50 that suits a sharp material change).
        width: How far the dithered zone reaches into each band, in pixels. This is what
            widens the transition, which is the point of dithering: at width=1 only the
            seam itself alternates, and every pattern collapses to the same result
            because a one-pixel-deep band can only alternate.
        tolerance: How close a pixel must be to one of the two colours to take part.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    Only pixels of the two named colours that border each other are touched, so the
    rest of the sprite is untouched even where it uses the same ramp.
    """
    if pattern not in ("bayer4", "bayer2", "checker"):
        raise ValidationFailed('pattern must be "bayer4", "bayer2" or "checker".')
    if len(ramp) < 2:
        raise ValidationFailed("ramp needs at least 2 colours.")
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if not 1 <= from_step <= len(ramp) or not 1 <= to_step <= len(ramp):
        raise ValidationFailed(f"from_step and to_step must be between 1 and {len(ramp)}.")
    if not 1 <= width <= 16:
        raise ValidationFailed(
            "width must be between 1 and 16; a dithered zone wider than that is a "
            "texture rather than a transition."
        )
    if abs(from_step - to_step) != 1:
        raise ValidationFailed(
            "from_step and to_step must be adjacent. Dithering between distant ramp "
            "steps produces noise rather than an intermediate shade."
        )

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "from_step": int(from_step),
        "to_step": int(to_step),
        "pattern": pattern,
        "width": int(width),
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot dither a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    local W, H = img.width, img.height
    local ramp = ARG.ramp
    local a_col, b_col = ramp[ARG.from_step], ramp[ARG.to_step]

    local BAYER4 = { {0,8,2,10}, {12,4,14,6}, {3,11,1,9}, {15,7,13,5} }
    local BAYER2 = { {0,2}, {3,1} }

    local function threshold(x, y)
      if ARG.pattern == "checker" then
        return ((x + y) % 2 == 0) and 0.25 or 0.75
      elseif ARG.pattern == "bayer2" then
        return (BAYER2[(y % 2) + 1][(x % 2) + 1] + 0.5) / 4.0
      end
      return (BAYER4[(y % 4) + 1][(x % 4) + 1] + 0.5) / 16.0
    end

    local function which(x, y)
      if x < 0 or y < 0 or x >= W or y >= H then return nil end
      local r, g, b, al = px_to_rgba(spr, img:getPixel(x, y))
      if al == 0 then return nil end
      local da = math.sqrt(0.299*(r-a_col.r)^2 + 0.587*(g-a_col.g)^2 + 0.114*(b-a_col.b)^2)
      local db = math.sqrt(0.299*(r-b_col.r)^2 + 0.587*(g-b_col.g)^2 + 0.114*(b-b_col.b)^2)
      if da <= ARG.tolerance and da <= db then return "a" end
      if db <= ARG.tolerance then return "b" end
      return nil
    end

    -- Only near where the two bands meet. A pixel of the right colour in the middle of
    -- its own band has no transition to widen, and dithering it would be the global
    -- application that makes dithering look dated. `width` sets how far the zone
    -- reaches in, which is what actually widens the transition.
    local R = ARG.width
    local pending = {}
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        local here = which(x, y)
        if here ~= nil then
          local other = (here == "a") and "b" or "a"
          -- Distance to the nearest pixel of the other band. This is what makes the
          -- result a gradient rather than a texture: comparing the ordered-dither
          -- threshold against a fixed 0.5 gives a uniform 50/50 checkerboard across the
          -- whole zone, which is not what dithering is for. The mix has to vary with
          -- how far through the transition the pixel sits, so a pixel deep in its own
          -- band almost never flips and one at the seam flips about half the time.
          local nearest = nil
          for dy = -R, R do
            for dx = -R, R do
              local d2 = dx*dx + dy*dy
              if d2 <= R*R and which(x + dx, y + dy) == other then
                local d = math.sqrt(d2)
                if nearest == nil or d < nearest then nearest = d end
              end
            end
          end

          if nearest ~= nil then
            local flip_chance = 0.5 * (1.0 - (nearest - 1) / R)
            if flip_chance < 0 then flip_chance = 0 end
            if threshold(x, y) < flip_chance then
              pending[#pending + 1] = {
                x = x, y = y, c = (other == "a") and a_col or b_col,
              }
            end
          end
        end
      end
    end

    for _, p in ipairs(pending) do
      local _, _, _, al = px_to_rgba(spr, img:getPixel(p.x, p.y))
      img_set(img, p.x, p.y, rgba_to_px(spr, p.c.r, p.c.g, p.c.b, al))
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               pattern = ARG.pattern, dithered_pixels = #pending }
    """
    return run_lua(body, args)


@mcp.tool()
def gradient_map(
    filename: str,
    ramp: list[str],
    contrast: float = 1.0,
    bias: float = 0.0,
    dither: str | None = None,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Put every pixel on a ramp by its brightness, whatever it started as.

    The other shading tools all begin with art that is *already* on a ramp:
    `shift_along_ramp` moves pixels between steps they already belong to, and
    `shade_region_by_light` shades a flat region painted in one of the ramp's colours.
    This is the one that brings art onto a ramp in the first place, which is what an
    imported image, a photo traced over, or a gradient fill actually needs.

    Each pixel's luminance decides its step: darkest to `ramp[0]`, lightest to the last
    entry, the rest in between. Afterwards the art uses the ramp's colours and nothing
    else, so `assess_sprite(..., ramp=...)` reports a palette conformance of 1.0.

    Args:
        ramp: The ramp, darkest first. Order is the mapping, so a reversed ramp inverts
            the image.
        contrast: Stretch the mapping around mid-grey. Above 1.0 pushes pixels toward
            the ends of the ramp and drops the middle steps; below 1.0 crowds everything
            into the middle. The interesting control is not which colours are used but
            how much of the art each step takes.
        bias: Shift the whole mapping after contrast, from -1.0 to 1.0. Positive is
            lighter. Use it when an image maps too dark to read.
        dither: "bayer4", "bayer2" or "checker" to break the bands. A pixel landing
            between two steps takes the darker or the lighter one by an ordered pattern,
            which reads as a gradient without adding a colour.
        x, y, width, height: Restrict the change to a region.

    Luminance is weighted 0.299/0.587/0.114, the same weighting the ramp matching uses,
    so a saturated red and a dull red of the same weight land on the same step. Alpha is
    carried through untouched, so the silhouette does not move and anti-aliased edges
    keep their coverage, even though their colour is now a ramp entry.
    """
    if len(ramp) < 2:
        raise ValidationFailed("ramp needs at least 2 colours to map onto.")
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if contrast <= 0:
        raise ValidationFailed(
            f"contrast must be greater than 0; got {contrast}. A contrast of 0 would map "
            "every pixel to the same step, which is fill_layer."
        )
    if not -1.0 <= bias <= 1.0:
        raise ValidationFailed(f"bias must be between -1.0 and 1.0; got {bias}.")
    if dither is not None and dither not in ("bayer4", "bayer2", "checker"):
        raise ValidationFailed('dither must be "bayer4", "bayer2" or "checker".')

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "contrast": float(contrast),
        "bias": float(bias),
        "dither": dither,
        "x": int(x), "y": int(y), "width": width, "height": height,
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot map a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)

    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)
    local ramp = ARG.ramp
    local last = #ramp - 1

    local BAYER4 = { {0,8,2,10}, {12,4,14,6}, {3,11,1,9}, {15,7,13,5} }
    local BAYER2 = { {0,2}, {3,1} }
    local function threshold(x, y)
      if ARG.dither == "checker" then
        return ((x + y) % 2 == 0) and 0.25 or 0.75
      elseif ARG.dither == "bayer2" then
        return (BAYER2[(y % 2) + 1][(x % 2) + 1] + 0.5) / 4.0
      end
      return (BAYER4[(y % 4) + 1][(x % 4) + 1] + 0.5) / 16.0
    end

    local written, histogram = 0, {}
    for i = 1, #ramp do histogram[i] = 0 end

    for yy = ry, ry + rh - 1 do
      for xx = rx, rx + rw - 1 do
        if xx >= 0 and yy >= 0 and xx < img.width and yy < img.height then
          local r, g, b, a = px_to_rgba(spr, img:getPixel(xx, yy))
          if a > 0 then
            local t = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            -- Contrast about mid-grey, then bias. Stated in that order because the two
            -- do not commute and the caller has to know which it is.
            t = 0.5 + (t - 0.5) * ARG.contrast + ARG.bias
            if t < 0 then t = 0 elseif t > 1 then t = 1 end

            local scaled = t * last
            local index
            if ARG.dither ~= nil then
              -- The fraction between two steps becomes the odds of taking the lighter
              -- one, resolved by the ordered pattern rather than by rounding, which is
              -- what turns a band edge into a gradient.
              local low = math.floor(scaled)
              index = low + ((scaled - low) > threshold(xx, yy) and 1 or 0)
            else
              index = math.floor(scaled + 0.5)
            end
            if index < 0 then index = 0 elseif index > last then index = last end

            local c = ramp[index + 1]
            img_set(img, xx, yy, rgba_to_px(spr, c.r, c.g, c.b, a))
            written = written + 1
            histogram[index + 1] = histogram[index + 1] + 1
          end
        end
      end
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = framenum,
               pixels_written = written, steps = #ramp, per_step = histogram }
    """
    return run_lua(body, args)
