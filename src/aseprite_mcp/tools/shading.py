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
from ..core import facets, lighting, occlusion
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_COLOR_LIST_LENGTH,
    MAX_FILL_LIGHT_STRENGTH,
    MAX_GLOW_RADIUS,
    MAX_OUTLINE_THICKNESS,
    MAX_SPECULAR_PIXELS,
    check_count,
    check_list_length,
    check_region_size,
)
from ..core.models import FRAME_GUARD_LUA
from .common import LANDED_LUA, lua_path, parse_color, resolve_path, run_ramp_lua
from .drawing import _write_map

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

    `pixels_matched` counts the pixels that both matched the ramp and were written, so it
    agrees with `pixels_written` rather than counting matches an active selection then
    refused.
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
    check_region_size(width, height, x=x, y=y, field="shade region")

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "steps": int(steps),
        "x": int(x), "y": int(y), "width": width, "height": height,
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)

    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)
    local ramp = ARG.ramp
    local mark = landed()

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
               pixels_matched = landed() - mark }
    """
    return run_ramp_lua(body, args)


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

# The three steps every form-shading tool takes before it has an opinion about light:
# decide which pixels are the region, check the region has an interior at all, and turn
# the distance field into a surface normal per pixel.
#
# Shared rather than copied because `specular_highlight` has to agree with
# `shade_region_by_light` about all three. A specular computed from a slightly different
# normal field lands in a slightly different place from the highlight it is supposed to
# sit inside, and a specular that refuses a thin region on a different threshold than the
# shading does is the "silently different result" the issue asking for this called out.
_FORM_LUA = r"""
-- The region: opaque, near base_color when one was given, and inside the selection when
-- one is active. Restricting the field to the selection matters: a field over the whole
-- silhouette would measure depth into pixels this call may not touch, and would light the
-- wrong shape.
local function build_region(spr, img, W, H, base, tolerance)
  local mask, count = {}, 0
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
          inside = d <= tolerance
        end
      end
      mask[y][x] = inside
      if inside then count = count + 1 end
    end
  end
  return mask, count
end

-- Where the region actually is, which a caller cannot otherwise find out. `base_color`
-- scopes by colour *distance*, and at the default tolerance of 24 two different materials
-- are often not two different colours: every step of a gold ramp is within 24 of a step of
-- a brass one, so a pass meant for one object matched another across the canvas and
-- reshaded it. `region_pixels` alone cannot tell a region in one place from a region in
-- four. A component count and a bounding box can, and both are one pass over a mask that
-- has already been built.
local function region_shape(mask, W, H)
  local seen, parts = {}, 0
  local x0, y0, x1, y1
  for y = 0, H - 1 do seen[y] = {} end
  for y = 0, H - 1 do
    for x = 0, W - 1 do
      if mask[y][x] then
        if x0 == nil or x < x0 then x0 = x end
        if x1 == nil or x > x1 then x1 = x end
        if y0 == nil or y < y0 then y0 = y end
        if y1 == nil or y > y1 then y1 = y end
        if not seen[y][x] then
          -- Flood filled with an explicit stack rather than recursively: a region can be
          -- the whole canvas, and Lua's C stack is not that deep.
          parts = parts + 1
          seen[y][x] = true
          local stack, top = { x, y }, 2
          while top > 0 do
            local py = stack[top]
            local px = stack[top - 1]
            top = top - 2
            for dy = -1, 1 do
              for dx = -1, 1 do
                local nx, ny = px + dx, py + dy
                if nx >= 0 and ny >= 0 and nx < W and ny < H
                   and mask[ny][nx] and not seen[ny][nx] then
                  seen[ny][nx] = true
                  stack[top + 1] = nx
                  stack[top + 2] = ny
                  top = top + 2
                end
              end
            end
          end
        end
      end
    end
  end
  if x0 == nil then return 0, nil end
  return parts, { x = x0, y = y0, width = x1 - x0 + 1, height = y1 - y0 + 1 }
end

-- The distance field, plus the one refusal both tools owe the caller. Below roughly 6px
-- across, the field never exceeds a pixel: there is no interior, so there is no form to
-- describe and nothing honest to do with a light direction.
local function require_interior(mask, W, H)
  local field, maxd = distance_field(mask, W, H)
  if maxd < 2.0 then
    error(string.format(
      "This region is too thin to shade: its deepest point is %.1f pixels from an " ..
      "edge, so there is no interior to describe. Place the highlight and shadow by " ..
      "hand with draw_pixels instead.", maxd), 0)
  end
  return field, maxd
end

-- A function giving the surface normal at a pixel, from the distance field.
--
-- Height from the distance field, as a quarter-circle profile: steep near the edge and
-- flat in the middle, which is what a round form does. The gradient of that gives a
-- normal following the form rather than the outline, which is the whole difference
-- between form shading and pillow shading.
--
-- Returned as a closure rather than as three filled tables: the caller reads each pixel
-- once, and three more full-canvas tables on top of the mask, the field and the smoothing
-- pass is the difference between a large sprite working and a large sprite exhausting
-- memory.
local function form_normals(mask, field, maxd, W, H, bulge)
  -- The chamfer field is integer-weighted, and those steps land straight in the gradient
  -- as single-pixel speckle along every band boundary. One box pass over the in-region
  -- neighbours costs nothing and removes most of it. This is not the cluster-smoothing
  -- pass that shaping band edges properly would need; it just stops the lighting term
  -- inheriting the distance metric's own quantisation.
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
    -- Scaled by maxd, not left as 0..1. Height has to be in the same units as x and y or
    -- the gradient is vanishingly small on any region bigger than a couple of pixels,
    -- every normal points straight up, and the whole form quantises to one or two ramp
    -- steps. At bulge = 1 this makes a region of radius R exactly R tall, which is a true
    -- sphere.
    return math.sqrt(math.max(0.0, 1.0 - (1.0 - t) * (1.0 - t))) * maxd * bulge
  end

  return function(x, y)
    local dhdx = (height(x+1, y) - height(x-1, y)) * 0.5
    local dhdy = (height(x, y+1) - height(x, y-1)) * 0.5
    local nx, ny, nz = -dhdx, -dhdy, 1.0
    local nl = math.sqrt(nx*nx + ny*ny + nz*nz)
    return nx/nl, ny/nl, nz/nl
  end
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
    fill_angle: float | None = None,
    fill_strength: float = 0.35,
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
        fill_angle: Degrees, a second light. Omitted by default, which leaves the result
            exactly as it was before this argument existed. Set it opposite `light_angle`
            for the fill or bounce light that keeps a shadow side readable instead of
            letting it go flat dark: the shadow side is where a sprite stops describing
            its form, and one light can only ever leave it at `ambient`.
        fill_strength: How strong the fill is next to the key, 0 to 1 and capped below 1.
            A fill that matches the key cancels the form entirely, because the two
            terminators land on opposite sides of the same shape and sum to a flat fill,
            so the cap refuses the value that destroys what the tool is for. A third to a
            half is the conventional choice.
        tolerance: How close a pixel must be to `base_color` to count as part of the
            region, as a weighted RGB distance. Ignored when `base_color` is omitted.
            **A distance between colours, not between materials.** Two ramps of different
            materials are routinely closer than the default 24: every step of a gold ramp
            generated by `generate_ramp` is within 24 of a step of a brass one, so a pass
            scoped to the brass matched the gold as readily. Art whose fills came from
            `generate_ramp` is exact, so scope it with a tolerance near zero and keep the
            wide default for hand-drawn art that varies.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    The two lights are summed and clamped, not averaged: averaging would dim the key side
    as the fill came up, so adding a fill light would make the whole sprite darker and
    quietly cost the ramp's top step. Clamping leaves the key side as it was and lightens
    only what the key did not reach, which is what a fill light is.

    `per_step` in the result counts pixels per ramp entry, which is how to check a fill
    actually lightened the shadow side rather than trusting that it did.

    `region_components` and `region_bounds` say whether the pass went where it was meant
    to, which `region_pixels` cannot: it counts matches without saying whether they are in
    one place or four. A call scoped to a 27px coin that comes back with a box spanning 200
    pixels of canvas has matched something else as well, and that is the mistake
    `tolerance` invites.

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
    if fill_angle is not None and not 0.0 <= fill_strength <= MAX_FILL_LIGHT_STRENGTH:
        raise ValidationFailed(
            f"fill_strength must be between 0 and {MAX_FILL_LIGHT_STRENGTH}; got "
            f"{fill_strength}. A fill light as strong as the key cancels the form: the "
            "two terminators fall on opposite sides of the shape and add up to the flat "
            "fill the shading was meant to replace. Lower it, or drop fill_angle to "
            "shade with one light."
        )

    key = lighting.light_vector(light_angle, light_z)
    fill = None if fill_angle is None else lighting.light_vector(fill_angle, light_z)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "base": parse_color(base_color) if base_color else None,
        "angle": float(light_angle),
        "light_z": float(light_z),
        "key": list(key),
        "fill": None if fill is None else list(fill),
        "fill_strength": float(fill_strength),
        "bulge": float(bulge),
        "ambient": float(ambient),
        "rim": float(rim),
        "bias": float(bias),
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + _FIELD_LUA + _FORM_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
    local W, H = img.width, img.height
    local ramp = ARG.ramp

    local mask, count = build_region(spr, img, W, H, ARG.base, ARG.tolerance)
    if count == 0 then
      error("Nothing to shade: no pixel matched. Check base_color and tolerance, or " ..
            "whether a selection is excluding the region.", 0)
    end

    local field, maxd = require_interior(mask, W, H)
    local normal_at = form_normals(mask, field, maxd, W, H, ARG.bulge)

    -- Both lights arrive already normalised from Python, where the sign convention for an
    -- upward light (negative in y, because screen y grows downward) is written down once.
    local lx, ly, lz = ARG.key[1], ARG.key[2], ARG.key[3]
    local fx, fy, fz
    if ARG.fill ~= nil then fx, fy, fz = ARG.fill[1], ARG.fill[2], ARG.fill[3] end

    local steps = #ramp - 1
    local shaded = 0
    local per_step = {}
    for i = 1, #ramp do per_step[i] = 0 end

    for y = 0, H - 1 do
      for x = 0, W - 1 do
        if mask[y][x] then
          local nx, ny, nz = normal_at(x, y)

          local ndotl = nx*lx + ny*ly + nz*lz
          if ndotl < 0 then ndotl = 0 end

          if fx ~= nil then
            -- The fill is a second diffuse term, summed with the key and clamped rather
            -- than averaged in. Averaging would scale the key down as the fill came up,
            -- so the brightest step would drop out of the result and adding a fill light
            -- would darken the sprite overall. Clamped, the key side is untouched (an
            -- opposing fill contributes nothing where the key peaks) and only the shadow
            -- side rises, which is the whole point of a fill.
            local ndotf = nx*fx + ny*fy + nz*fz
            if ndotf > 0 then ndotl = ndotl + ARG.fill_strength * ndotf end
            if ndotl > 1 then ndotl = 1 end
          end

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
          per_step[idx] = per_step[idx] + 1
          shaded = shaded + 1
        end
      end
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    local parts, box = region_shape(mask, W, H)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               region_pixels = count, shaded_pixels = shaded,
               region_components = parts, region_bounds = box,
               depth = maxd, ramp_size = #ramp, per_step = per_step,
               fill_light = (ARG.fill ~= nil) }
    """
    return run_ramp_lua(body, args)


@mcp.tool()
def specular_highlight(
    filename: str,
    ramp: list[str],
    light_angle: float = 135.0,
    light_z: float = 0.45,
    size: int = 2,
    tightness: float = 0.7,
    bulge: float = 1.0,
    highlight_color: str | None = None,
    base_color: str | None = None,
    tolerance: float = 24.0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Place a small specular highlight where the light actually reflects at the viewer.

    `shade_region_by_light` spreads the ramp's top step over the whole lit side, which is
    what a matte surface does and why its output reads as plastic. A specular is the other
    thing at the top of the ramp: a two or three pixel glint on the one part of the form
    whose normal sends the light straight back at you. It is the difference between a
    stone and a gem, and it is small by definition.

    Run this **after** `shade_region_by_light`, on the same region and the same light: it
    reuses that tool's region mask, distance field and surface normals, so the glint lands
    inside the highlight rather than beside it.

    **Reserve the top step for it.** Shade the form with the ramp *minus its last entry*
    and then call this with the whole ramp:

        shade_region_by_light(f, ramp[:-1], light_angle=135)
        specular_highlight(f, ramp, light_angle=135, size=2)

    Shading with the full ramp spreads its top step over the entire lit side, which leaves
    nothing above it for a glint to be: the specular then paints pixels the colour they
    already are, and that call is refused rather than reported as a success that changed
    nothing. The refusal says this and names the way out, so it is a reminder rather than
    a puzzle.

    Where it goes: on the normal closest to the half-vector between the light and the
    viewer, not on the normal closest to the light. That offset toward the viewer is what
    makes a specular sit inside the lit side instead of out on its shoulder, and it is the
    whole reason this is a separate tool rather than a brighter `bias`.

    What it will not do: touch an edge pixel. A specular on the silhouette's border reads
    as a hole punched in the form rather than as a shine, so only pixels with all eight
    neighbours inside the region are candidates. On a region with no such pixel there is
    nothing to put a glint on, and the call is refused with the same message
    `shade_region_by_light` gives for a region too thin to shade.

    Args:
        ramp: Colours darkest first, the same ramp the form was shaded with.
        light_angle: Degrees, and it must match the shading pass or the glint contradicts
            the form. 0 is from the right, 90 from above, 135 from the upper left.
        light_z: How much the light comes from the viewer, 0 to 1. Match the shading pass.
        size: How many pixels the glint covers. A count, not a radius: a specular is two
            or three pixels on most sprites, and the point of this tool is that it stays
            that small. The pixels are grown outward from the brightest one and stay
            touching, so the result is one glint rather than scattered dots.
        tightness: How narrowly the surface has to face the reflection to count, 0 to 1,
            as a threshold on the normal against the half-vector. High is a tiny hard
            glint on a polished surface; low lets a broader shoulder qualify, from which
            `size` still takes only the best pixels. If nothing clears it the call is
            refused and the message names the best alignment the form actually offers, so
            the number to lower it to is in the error rather than a guess.
        bulge: How rounded the form reads. Match the shading pass, or the normals this
            works from are not the normals the shading used.
        highlight_color: The glint's colour, defaulting to the ramp's top step so
            `palette_conformance` stays at 1.0. This is the flag for metal, which is the
            one material whose specular is genuinely brighter than its own ramp: name a
            near-white there. A colour that is not on `ramp` will drop conformance against
            that ramp, which is the honest trade rather than a bug, and the result says
            whether it happened.
        base_color: Only consider pixels near this colour, as for `shade_region_by_light`.
            Scope it the same way you scoped the shading.
        tolerance: How close a pixel must be to `base_color` to count as part of the
            region. Ignored when `base_color` is omitted.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    Returns `specular_pixels` (how many were placed, which is below `size` when the
    eligible area is smaller than the budget), `pixels` (where they went, so a later
    `remove_stray_pixels` can be told to protect them), `pixels_changed` (how many were
    not already that colour) and `peak_alignment`, the best normal against the
    half-vector found anywhere in the region.

    Also `region_components` and `region_bounds`, which say whether the region is where it
    was meant to be. Worth reading on this tool in particular: the normals come from the
    *whole* region, so scoping a glint to a compound object rather than to one of its parts
    puts it wherever that object's overall mass bulges. A sword scoped by its whole cell
    got its only glint on the leather grip, with none on the blade, and
    `specular_pixels: 2` said nothing about that.
    """
    if len(ramp) < 2:
        raise ValidationFailed("ramp needs at least 2 colours to take a highlight from.")
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if not 0.0 <= light_z <= 1.0:
        raise ValidationFailed("light_z must be between 0 and 1.")
    if not 0.0 <= tightness <= 1.0:
        raise ValidationFailed(
            "tightness must be between 0 and 1: it is a threshold on how closely the "
            "surface faces the reflection, and both ends of that are alignments."
        )
    if bulge <= 0:
        raise ValidationFailed("bulge must be greater than 0.")
    if tolerance < 0:
        raise ValidationFailed("tolerance must not be negative.")
    size = check_count(
        "size", size, MAX_SPECULAR_PIXELS, minimum=1,
        remedy="A specular wider than that is a second lit region, which "
               "shade_region_by_light describes better than a glint can.",
    )

    parsed_ramp = [parse_color(c) for c in ramp]
    spec_color = parse_color(highlight_color) if highlight_color else parsed_ramp[-1]
    half = lighting.specular_direction(light_angle, light_z)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": parsed_ramp,
        "spec": spec_color,
        "base": parse_color(base_color) if base_color else None,
        "half": list(half),
        "size": size,
        "tightness": float(tightness),
        "bulge": float(bulge),
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + _FIELD_LUA + _FORM_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name, 0) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
    local W, H = img.width, img.height

    local mask, count = build_region(spr, img, W, H, ARG.base, ARG.tolerance)
    if count == 0 then
      error("Nothing to highlight: no pixel matched. Check base_color and tolerance, " ..
            "or whether a selection is excluding the region.", 0)
    end

    local field, maxd = require_interior(mask, W, H)
    local normal_at = form_normals(mask, field, maxd, W, H, ARG.bulge)

    local hx, hy, hz = ARG.half[1], ARG.half[2], ARG.half[3]

    local function in_region(x, y)
      if x < 0 or y < 0 or x >= W or y >= H then return false end
      return mask[y][x]
    end

    -- A candidate needs all eight neighbours inside the region. That is exactly "not an
    -- edge pixel", which is the craft rule this tool exists to encode: a glint on the
    -- border reads as a hole, not as a shine. It also makes a canvas-edge pixel a
    -- non-candidate for free, since its off-canvas neighbours are not in the region.
    local function is_interior(x, y)
      for dy = -1, 1 do
        for dx = -1, 1 do
          if not in_region(x + dx, y + dy) then return false end
        end
      end
      return true
    end

    -- One table doing two jobs: the score of every pixel that clears the threshold, and
    -- the membership test for "could be part of the glint". `peak` is tracked over every
    -- interior pixel regardless of the threshold, because that is the number the refusal
    -- has to quote.
    local elig = {}
    local peak, interior_count = 0.0, 0
    for y = 0, H - 1 do
      elig[y] = {}
      for x = 0, W - 1 do
        if mask[y][x] and is_interior(x, y) then
          interior_count = interior_count + 1
          local nx, ny, nz = normal_at(x, y)
          local ndoth = nx*hx + ny*hy + nz*hz
          if ndoth < 0 then ndoth = 0 end
          if ndoth > peak then peak = ndoth end
          if ndoth >= ARG.tightness then elig[y][x] = ndoth end
        end
      end
    end

    if interior_count == 0 then
      error(string.format(
        "This region is too thin to shade: its deepest point is %.1f pixels from an " ..
        "edge, so there is no interior to describe. Place the highlight and shadow by " ..
        "hand with draw_pixels instead.", maxd), 0)
    end

    local sx, sy, best = nil, nil, nil
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        local s = elig[y][x]
        -- Strictly greater, so the first pixel in scan order wins a tie and the same
        -- sprite always gets the same glint in the same place.
        if s ~= nil and (best == nil or s > best) then sx, sy, best = x, y, s end
      end
    end

    if sx == nil then
      error(string.format(
        "No part of this form faces the reflection closely enough for a specular: the " ..
        "best alignment anywhere in the region is %.2f and tightness is %.2f. Lower " ..
        "tightness below %.2f, or change light_angle and light_z so the light actually " ..
        "reflects toward the viewer.", peak, ARG.tightness, peak), 0)
    end

    -- Grown outward from the brightest pixel, always taking the best neighbour of what is
    -- already chosen, so the glint is one connected blob. Picking the top `size` scores
    -- globally would scatter it across every part of the form that happens to face the
    -- light, which is not a specular.
    local chosen, picked = {}, {}
    local function take(x, y)
      if chosen[y] == nil then chosen[y] = {} end
      chosen[y][x] = true
      picked[#picked + 1] = { x = x, y = y }
    end
    take(sx, sy)
    while #picked < ARG.size do
      local cx, cy, cs = nil, nil, nil
      for _, p in ipairs(picked) do
        for dy = -1, 1 do
          for dx = -1, 1 do
            local nx2, ny2 = p.x + dx, p.y + dy
            if nx2 >= 0 and ny2 >= 0 and nx2 < W and ny2 < H then
              local s = elig[ny2][nx2]
              local already = chosen[ny2] ~= nil and chosen[ny2][nx2]
              if s ~= nil and not already and (cs == nil or s > cs) then
                cx, cy, cs = nx2, ny2, s
              end
            end
          end
        end
      end
      if cx == nil then break end
      take(cx, cy)
    end

    local c = ARG.spec
    local changed, coords = 0, {}
    for i, p in ipairs(picked) do
      -- Alpha carried through, so a glint on an anti-aliased edge pixel cannot change the
      -- silhouette. It cannot reach one anyway, but the invariant is cheaper to keep than
      -- to reason about.
      local old = img:getPixel(p.x, p.y)
      local _, _, _, a = px_to_rgba(spr, old)
      local new = rgba_to_px(spr, c.r, c.g, c.b, a)
      if new ~= old then changed = changed + 1 end
      img_set(img, p.x, p.y, new)
      coords[i] = { p.x, p.y }
    end

    -- A glint the same colour as what was already there is not a glint. This happens by
    -- default rather than rarely: shade_region_by_light spreads the ramp's top step over
    -- the whole lit side, which is the matte look the issue asking for this tool called
    -- out, and a specular painted in that same step lands invisibly on top of it. Saying
    -- "ok, 3 pixels" there would be a tool reporting success for a no-op, so it refuses
    -- and names both ways out.
    if changed == 0 then
      error(string.format(
        "This glint would be invisible: all %d pixels it covers are already the colour " ..
        "it would paint them. shade_region_by_light spreads the ramp's top step across " ..
        "the whole lit side, so there is nothing left at the top for a specular to be. " ..
        "Shade the form with the ramp minus its last entry, which reserves that step " ..
        "for this call, or pass highlight_color for a glint brighter than the ramp.",
        #picked), 0)
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    local parts, box = region_shape(mask, W, H)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               region_pixels = count, interior_pixels = interior_count,
               region_components = parts, region_bounds = box,
               specular_pixels = #picked, pixels_changed = changed,
               requested_size = ARG.size, pixels = coords,
               seat = { sx, sy }, peak_alignment = peak, depth = maxd }
    """
    result = run_ramp_lua(body, args)
    # Said in Python rather than Lua because only Python knows what the caller asked for:
    # the Lua is handed one colour and cannot tell a ramp step from a near-white glint.
    result["highlight_on_ramp"] = highlight_color is None or spec_color in parsed_ramp
    return result


def _ramp_entries_within(
    colour: dict, ramp: list[dict], tolerance: float
) -> list[tuple[int, str, float]]:
    """The ramp entries `colour` cannot be told apart from, as (index, hex, distance).

    A transcription of `ramp_match`'s weighted distance, which is the authority; the two
    have to agree or this would warn about an overlap the Lua does not have, or stay quiet
    about one it does. Weighted rather than plain RGB for the reason given at `_RAMP_LUA`.

    An indexed colour (`{"index": N}`) carries no channels here, so it is skipped rather
    than guessed at: the palette is only knowable with the file open.
    """
    if "r" not in colour:
        return []
    out: list[tuple[int, str, float]] = []
    for i, entry in enumerate(ramp):
        if "r" not in entry:
            continue
        dr = colour["r"] - entry["r"]
        dg = colour["g"] - entry["g"]
        db = colour["b"] - entry["b"]
        dist = (0.299 * dr * dr + 0.587 * dg * dg + 0.114 * db * db) ** 0.5
        if dist <= tolerance:
            hexed = f"#{entry['r']:02x}{entry['g']:02x}{entry['b']:02x}"
            out.append((i, hexed, dist))
    return out


@mcp.tool()
def contact_shadow(
    filename: str,
    ramp: list[str],
    occluder_color: str,
    radius: int = 1,
    depth: int = 1,
    direction: float | None = None,
    tolerance: float = 24.0,
    occluder_tolerance: float | None = None,
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
        occluder_tolerance: How close a pixel must be to `occluder_color` to count as the
            occluder, as a weighted RGB distance. Defaults to `tolerance`, which is what
            this did before it was a separate argument. It wants to be **tight**: the
            occluder is a flat fill you named, while `tolerance` has to stay loose enough
            for shaded art that varies, and one number cannot be both. At the shared
            default of 24 a ground colour within 24 of the subject's own ramp makes the
            subject its own occluder: measured on a 24x24 sprite with a subject painted
            `#5a5a7a` and ground `#60607e`, `occluder_pixels` came back as 312 (the 144
            ground pixels plus all 168 of the subject) and nothing was darkened at all.
            The result carries a warning naming any ramp entry this cannot be told apart
            from, because that overlap is invisible otherwise.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    Refuses a pass that darkened nothing rather than reporting `darkened_pixels: 0` as a
    success, and the refusal carries the three counts that say which of the possible
    causes it was. A contact shadow that changed no pixel is not a contact shadow.

    Run this **before** the passes that repaint the occluder, not after. The occluder is
    found by colour, so a `shade_region_by_light` or `shift_along_ramp` that has already
    moved the ground off `occluder_color` leaves this matching a handful of pixels and
    reporting the handful as a success.
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
    occ_tol = float(tolerance) if occluder_tolerance is None else float(occluder_tolerance)
    if occ_tol < 0:
        raise ValidationFailed("occluder_tolerance must not be negative.")

    parsed_ramp = [parse_color(c) for c in ramp]
    parsed_occ = parse_color(occluder_color)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": parsed_ramp,
        "occluder": parsed_occ,
        "radius": int(radius),
        "depth": int(depth),
        "direction": None if direction is None else float(direction),
        "tolerance": float(tolerance),
        "occluder_tolerance": occ_tol,
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
    local W, H = img.width, img.height
    local ramp, occ = ARG.ramp, ARG.occluder
    local R = ARG.radius

    -- Which pixels are the occluder. Sampled once up front rather than per neighbour
    -- lookup, because the inner loop reads every pixel in the radius around every
    -- candidate and re-decoding each one is the whole cost of the tool.
    local is_occ = {}
    local occ_count, opaque = 0, 0
    for y = 0, H - 1 do
      is_occ[y] = {}
      for x = 0, W - 1 do
        local r, g, b, a = px_to_rgba(spr, img:getPixel(x, y))
        local hit = false
        if a > 0 then
          opaque = opaque + 1
          local dr, dg, db = r - occ.r, g - occ.g, b - occ.b
          -- Its own tolerance, not the ramp's. One number for both made the subject its
          -- own occluder whenever the ground sat within 24 of any ramp step, which left
          -- nothing to darken and reported it as a success.
          hit = math.sqrt(0.299*dr*dr + 0.587*dg*dg + 0.114*db*db) <= ARG.occluder_tolerance
        end
        is_occ[y][x] = hit
        if hit then occ_count = occ_count + 1 end
      end
    end

    if occ_count == 0 then
      error("No pixel matched occluder_color, so there is no contact to shade. " ..
            "Check the colour, or raise occluder_tolerance.")
    end

    local dirx, diry
    if ARG.direction ~= nil then
      local rad = math.rad(ARG.direction)
      dirx, diry = math.cos(rad), -math.sin(rad)
    end

    local mark = landed()
    -- Counted so a pass that darkened nothing can say which of its reasons it was,
    -- instead of reporting `darkened_pixels: 0` as a success nobody reads.
    local in_reach, already_darkest = 0, 0
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
              in_reach = in_reach + 1
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
                  else
                    already_darkest = already_darkest + 1
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

    local darkened = landed() - mark
    -- Refused rather than reported, the way specular_highlight refuses a glint that
    -- would be invisible. A contact shadow that changed no pixel is not a contact
    -- shadow, and `ok: true, darkened_pixels: 0` is the result an agent reads as done.
    if darkened == 0 then
      error(string.format(
        "This contact shadow darkened nothing, so the sprite is unchanged. %d of the " ..
        "%d opaque pixels matched occluder_color (at occluder_tolerance %.1f), %d " ..
        "non-occluder pixels lay within %d of one, and %d of those were already at the " ..
        "ramp's darkest step. If the occluder count is most of the sprite, " ..
        "occluder_color is close enough to the artwork's own colours that the subject " ..
        "is being read as its own occluder: lower occluder_tolerance. If nothing lay " ..
        "within reach, the two forms are not touching: raise radius.",
        occ_count, opaque, ARG.occluder_tolerance, in_reach, R, already_darkest), 0)
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               occluder_pixels = occ_count, opaque_pixels = opaque,
               pixels_in_reach = in_reach, darkened_pixels = darkened }
    """
    result = run_ramp_lua(body, args)
    # Said in Python because only Python holds both lists. The occluder match and the ramp
    # match are two colour-distance tests over the same pixels, and where their radii
    # overlap a pixel of the artwork is classified as the thing occluding it. That is
    # invisible in the result otherwise: `occluder_pixels` is a number with nothing to
    # compare it to, and the pass simply darkens less than it should.
    overlap = _ramp_entries_within(parsed_occ, parsed_ramp, occ_tol)
    if overlap:
        named = ", ".join(f"ramp[{i}] {colour} at {dist:.1f}" for i, colour, dist in overlap)
        note = (
            f"occluder_color is within occluder_tolerance ({occ_tol:.1f}) of {named}, so "
            "pixels of those ramp steps are being treated as the occluder rather than as "
            "artwork to darken. Lower occluder_tolerance, or give the occluder a colour "
            "the ramp does not come near."
        )
        if isinstance(result, dict):
            existing = result.get("warnings")
            result["warnings"] = [*existing, note] if isinstance(existing, list) else [note]
    return result


@mcp.tool()
def seam_occlusion(
    filename: str,
    rows: list[str],
    legend: dict,
    ramp: list[str],
    radius: int = 2,
    depth: int = 2,
    tolerance: float = 24.0,
    x: int = 0,
    y: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Darken the seam where two masses of the **same** material overlap, along its ramp.

    `contact_shadow` does ambient occlusion already and finds the form doing the occluding
    by colour, which is the one case a figure never presents. An arm against a torso, a
    pauldron over a shoulder, a thigh against a hip: both sides are the same stone under
    the same light and no colour separates them, so there is nothing for `occluder_color`
    to match. Measured on this project's own golem, an armpit where an artist darkens the
    contact came out +131 in luminance, because nothing here could see the seam.

    What a colour cannot say, the caller can. The map is the same notation
    `draw_pixel_map` and `shade_facets` take, one character per pixel, except that the
    legend names **masses** instead of colours or directions, and gives each one a `z`.

    Args:
        rows: One string per row of the map, one character per pixel. "." is a pixel that
            belongs to no mass, and is neither darkened nor treated as an occluder.
        legend: {symbol: z}, where a **higher z is nearer the viewer**. `{"a": 1, "b": 0}`
            says mass "a" overlaps mass "b", so the seam darkens on "b" and not on "a".
            Occlusion is asymmetric and that is the whole point: darken both sides of a
            seam and you have drawn brickwork, darken the side behind and you have put one
            mass in front of another.
        ramp: Colours darkest first. Darkened pixels stay on this ramp, so conformance is
            preserved by construction.
        radius: How far the darkening reaches from the seam, in pixels. 2 is usually right
            and is what gives the falloff somewhere to happen.
        depth: How many ramp steps darker, against the seam itself, tapering to nothing at
            `radius`. Refused at or above the ramp's length, which would slam the seam to
            the darkest entry whatever was there.
        tolerance: How close a pixel must be to a ramp entry to be darkened, as a weighted
            RGB distance. A pixel further off is left alone, so a seam crossing another
            material does not drag it onto this ramp.
        x, y: Where the map's top-left corner lands on the canvas.
        layer: Target layer (default: top layer).
        frame: Target frame, 1-based.

    The darkening **falls off with distance** from the seam rather than being a hard line,
    on the same curve `contact_shadow` uses so the two cannot disagree about what a contact
    falloff is. That matters more here than it does there: the workaround this replaces, in
    this project's golem generator, read seam pixels back in Python and slammed them two
    steps down at a fixed width, and the result read as masonry. A combination that cannot
    produce a falloff, such as `depth=1` over `radius=2`, is reported as a flat band rather
    than passed off as one.

    Refuses rather than darkening nothing: a map with one mass, a map whose masses all sit
    at the same z, masses that do not come within `radius` of each other, and a pass where
    every pixel it reached was already at the ramp's darkest step are each their own
    refusal, and each one names the counts behind it.

    Reports `masses` (pixels per symbol), `depths` (the z each resolved to), `by_steps`
    (how many pixels moved how far, which is the falloff) and `darkened_pixels`.
    """
    if len(ramp) < 2:
        raise ValidationFailed(
            "ramp needs at least 2 colours: occlusion is a step down a ramp, and with one "
            "colour there is nowhere to step."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    radius = check_count(
        "radius", radius, MAX_OUTLINE_THICKNESS, minimum=1,
        remedy="Occlusion reaching further than a couple of pixels is a drop shadow, "
               "which add_drop_shadow and cast_shadow do properly.",
    )
    if depth >= len(ramp):
        raise ValidationFailed(
            f"depth is {depth} on a ramp of {len(ramp)}, so every pixel it reached would "
            f"land on the darkest entry whatever it started as, which is a drawn black "
            f"line rather than occlusion. The most this ramp can express is "
            f"{len(ramp) - 1}."
        )
    planned = occlusion.plan(
        rows, legend, radius=radius, depth=int(depth), origin_x=int(x), origin_y=int(y)
    )

    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "darken": planned["darken"],
        "tolerance": float(tolerance),
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot shade a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
    local W, H = img.width, img.height
    local ramp = ARG.ramp

    local mark = landed()
    -- Counted so a pass that darkened nothing can say which of its reasons it was,
    -- instead of reporting `darkened_pixels: 0` as a success nobody reads. The plan is
    -- geometry and knows where the seams are; only the open file knows what is painted
    -- there, so these four are the ways the two can disagree.
    local off_canvas, transparent, off_ramp, already_darkest = 0, 0, 0, 0
    for _, p in ipairs(ARG.darken) do
      if p.x < 0 or p.y < 0 or p.x >= W or p.y >= H then
        off_canvas = off_canvas + 1
      else
        local r, g, b, a = px_to_rgba(spr, img:getPixel(p.x, p.y))
        if a == 0 then
          transparent = transparent + 1
        else
          local idx, dist = ramp_match(ramp, r, g, b)
          if dist > ARG.tolerance then
            off_ramp = off_ramp + 1
            note_skipped()
          else
            local target = idx - p.steps
            if target < 1 then target = 1 end
            if target == idx then
              already_darkest = already_darkest + 1
            else
              local c = ramp[target]
              img_set(img, p.x, p.y, rgba_to_px(spr, c.r, c.g, c.b, a))
            end
          end
        end
      end
    end

    local darkened = landed() - mark
    if darkened == 0 then
      error(string.format(
        "This seam occlusion darkened nothing, so the sprite is unchanged. The map put " ..
        "%d pixels within reach of a nearer mass; of those %d are off the canvas, %d " ..
        "are transparent on this layer, %d are further than tolerance %.1f from any " ..
        "ramp entry, and %d were already at the ramp's darkest step. If most are " ..
        "transparent or off the canvas the map is not where the art is: check x, y and " ..
        "the layer. If most are off the ramp, this is not the ramp the masses are " ..
        "painted on.",
        #ARG.darken, off_canvas, transparent, off_ramp, ARG.tolerance,
        already_darkest), 0)
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               seam_pixels = #ARG.darken, darkened_pixels = darkened,
               pixels_off_ramp = off_ramp, pixels_already_darkest = already_darkest }
    """
    result = run_ramp_lua(body, args)
    if isinstance(result, dict):
        result["masses"] = planned["masses"]
        result["depths"] = planned["depths"]
        result["by_steps"] = planned["by_steps"]
        result["pixels_in_reach"] = planned["pixels_in_reach"]
        result["map_width"] = planned["width"]
        result["map_height"] = planned["height"]
        # Said in Python because only Python holds the step profile, and a flat band is
        # invisible in the picture: it looks like a line somebody meant to draw.
        note = occlusion.flat_band_note(
            planned["by_steps"], radius=radius, depth=int(depth)
        )
        if note:
            existing = result.get("warnings")
            result["warnings"] = [*existing, note] if isinstance(existing, list) else [note]
    return result


@mcp.tool()
def surface_emission(
    filename: str,
    ramp: list[str],
    source_color: str,
    radius: int = 4,
    depth: int = 3,
    falloff: str = "quadratic",
    tolerance: float = 24.0,
    source_tolerance: float | None = None,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Light an interior source onto the surface around it, up that surface's own ramp.

    `glow` builds a halo on a layer **below** the artwork, and its docstring says plainly
    that "a body blocks the halo of a gem inside it". So a glowing core inside a silhouette
    gets nothing at all: on this project's golem, `glow` contributed zero pixels to the
    export, which was confirmed by counting the colours in the committed PNG (nine: eight
    stone steps and one core colour), and the longest comment in the old generator defended
    a layer with nothing on it. What light from an interior source actually does is warm the
    surface it sits in, and that is this.

    It is neither a halo nor a gradient. Each pixel within `radius` of the source is moved
    **up the ramp it is already on**, by a number of steps that falls off with distance, so
    the surface keeps its own form: a crack near the core stays darker than the stone around
    it, and both brighten. Painting a colour per ring instead, which is what a hand-rolled
    bloom does, flattens every tone inside the radius to one value and reads as a gradient
    laid over the figure.

    Args:
        ramp: Colours darkest first, and **the ramp the surface is painted on**: this moves
            pixels along it, so a pixel further than `tolerance` from every entry is left
            alone rather than dragged onto a palette it was never on. The warmth therefore
            comes from the ramp's upper end, which is where a hue-shifted ramp is warm
            (`generate_ramp` with `light_hue`). To tint as well as brighten, hand it a ramp
            built from the surface's midtone up into the source's colour and the lift walks
            into that hue.
        source_color: The colour of the thing emitting, for example a gem or a molten core.
            Source pixels are never repainted; they are where the light comes from.
        radius: How many rings of surface the light reaches, in pixels.
        depth: How many ramp steps the ring touching the source is lifted. The outermost
            ring is always lifted by at least 1, because a ring that moves nothing should
            not be in the radius. Refused at or above the ramp's length.
        falloff: "quadratic" keeps the lift concentrated near the source, which is how light
            falls off and what reads as a source; "linear" spreads it evenly.
        tolerance: How close a pixel must be to a ramp entry to be lifted, as a weighted RGB
            distance.
        source_tolerance: How close a pixel must be to `source_color` to count as the
            source. Defaults to `tolerance`, and it wants to be **tight** for the reason
            `contact_shadow` documents at `occluder_tolerance`: the source is a flat colour
            you named, while `tolerance` has to stay loose enough for shaded art that
            varies, and one number cannot be both. The result warns when `source_color`
            cannot be told apart from a ramp entry, because then the surface is partly its
            own source and the light spreads from the wrong pixels.
        layer: The layer whose surface is lit, and the one written (default: top layer).
        frame: Target frame, 1-based.

    **Why this is not an argument to `glow`.** `glow` writes a new layer below the subject
    and promises the subject's cel is untouched, so deleting one layer removes the effect;
    this writes into the subject's cel, because light landing on a surface is part of that
    surface. `glow` paints only where the art is not; this paints only where the art is.
    `glow` refuses when it runs out of room outside the silhouette; this refuses when it
    finds no surface on the ramp inside it. An argument that reversed all three would be two
    tools sharing one name, and it would make `glow`'s central promise conditional on a flag.

    Refuses rather than reporting a pass that did nothing: no pixel matching `source_color`
    is an error, and so is a source with no surface on the declared ramp around it. The
    refusal carries the counts that say which it was.

    Reports `per_ring`, how many pixels were lifted at each distance, which is the number
    that says the falloff happened, alongside `lifts`, the steps each ring was given.
    """
    if len(ramp) < 2:
        raise ValidationFailed(
            "ramp needs at least 2 colours: emission is a step up a ramp, and with one "
            "colour there is nowhere to step."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if falloff not in lighting.FALLOFFS:
        raise ValidationFailed(
            f'falloff must be "linear" or "quadratic"; got {falloff!r}.'
        )
    radius = check_count(
        "radius", radius, MAX_GLOW_RADIUS, minimum=1,
        remedy="Light reaching further than a few pixels across a sprite is a fill, "
               "which fill_gradient does properly.",
    )
    if depth < 1:
        raise ValidationFailed(
            f"depth is {depth}; the minimum is 1 ramp step. A pass that moves a pixel "
            "zero steps along its ramp leaves the sprite exactly as it was."
        )
    if depth >= len(ramp):
        raise ValidationFailed(
            f"depth is {depth} on a ramp of {len(ramp)}, so every pixel it reached would "
            f"land on the brightest entry whatever it started as, which erases the form "
            f"it was supposed to light. The most this ramp can express is {len(ramp) - 1}."
        )
    if tolerance < 0:
        raise ValidationFailed("tolerance must not be negative.")
    source_tol = float(tolerance) if source_tolerance is None else float(source_tolerance)
    if source_tol < 0:
        raise ValidationFailed("source_tolerance must not be negative.")

    # Decided in Python so the Lua does a table lookup, and so the falloff is a list of
    # integers that can be asserted on rather than a bloom that can only be looked at.
    lifts = lighting.emission_lift(radius, int(depth), falloff)
    parsed_ramp = [parse_color(c) for c in ramp]
    parsed_source = parse_color(source_color)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": parsed_ramp,
        "source": parsed_source,
        "lifts": lifts,
        "radius": radius,
        "tolerance": float(tolerance),
        "source_tolerance": source_tol,
    }
    body = FRAME_GUARD_LUA + _RAMP_LUA + _FIELD_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then
      error("Cannot light a group layer: " .. layer.name ..
            ". Name one of the layers inside it.", 0)
    end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
    local W, H = img.width, img.height
    local ramp, source = ARG.ramp, ARG.source

    -- Two masks in one pass. The emitting set is stored already inverted, as `outside`,
    -- because the chamfer field measures distance out from whatever the mask is false at,
    -- so what it wants is a mask that is true where the source is not. Building it
    -- inverted here keeps one full-canvas table alive instead of two.
    local outside, opaque = {}, {}
    local sources, solid = 0, 0
    for y = 0, H - 1 do
      outside[y], opaque[y] = {}, {}
      for x = 0, W - 1 do
        local r, g, b, a = px_to_rgba(spr, img:getPixel(x, y))
        local is_solid = a > 0
        local is_source = false
        if is_solid then
          solid = solid + 1
          local dr, dg, db = r - source.r, g - source.g, b - source.b
          -- Its own tolerance, not the ramp's, for the reason contact_shadow documents:
          -- a surface that cannot be told apart from its own light source spreads the
          -- light from the wrong pixels.
          is_source =
            math.sqrt(0.299*dr*dr + 0.587*dg*dg + 0.114*db*db) <= ARG.source_tolerance
        end
        outside[y][x] = not is_source
        opaque[y][x] = is_solid
        if is_source then sources = sources + 1 end
      end
    end

    if sources == 0 then
      error("No pixel matched source_color, so there is no light to spread. Check the " ..
            "colour, or raise source_tolerance.", 0)
    end

    -- One O(canvas) pass whatever the radius, where scanning a neighbourhood per pixel
    -- would have been O(canvas * radius^2). The field counts 3 per orthogonal step and 4
    -- per diagonal one, so a pixel touching the source reads 3 and lands in ring 1.
    local dist = distance_field(outside, W, H)
    outside = nil

    local lifts = ARG.lifts
    local mark = landed()
    local per_ring = {}
    for i = 1, ARG.radius do per_ring[i] = 0 end
    local in_reach, off_ramp, already_brightest = 0, 0, 0
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        -- A distance of 0 is a source pixel: it is where the light comes from, so it is
        -- never repainted. Transparency is not a surface and takes no light, which is the
        -- whole difference between this and a halo.
        if opaque[y][x] and dist[y][x] > 0 then
          local ring = math.floor(dist[y][x] / 3.0 + 0.5)
          if ring >= 1 and ring <= ARG.radius then
            in_reach = in_reach + 1
            local r, g, b, a = px_to_rgba(spr, img:getPixel(x, y))
            local idx, d = ramp_match(ramp, r, g, b)
            if d > ARG.tolerance then
              off_ramp = off_ramp + 1
              note_skipped()
            else
              local target = idx + lifts[ring]
              if target > #ramp then target = #ramp end
              if target == idx then
                already_brightest = already_brightest + 1
              else
                local c = ramp[target]
                -- Tallied from what landed, not from the offer: `img_set` refuses a write
                -- outside the active selection, so counting the offer would report a
                -- falloff that was never painted.
                local before = landed()
                img_set(img, x, y, rgba_to_px(spr, c.r, c.g, c.b, a))
                if landed() > before then per_ring[ring] = per_ring[ring] + 1 end
              end
            end
          end
        end
      end
    end

    local lifted = landed() - mark
    if lifted == 0 then
      error(string.format(
        "This emission lit nothing, so the sprite is unchanged. %d of the %d opaque " ..
        "pixels matched source_color (at source_tolerance %.1f), %d surface pixels lay " ..
        "within %d rings of one, %d of those were further than tolerance %.1f from any " ..
        "ramp entry, and %d were already at the ramp's brightest step. If nothing lay " ..
        "within reach, the source is not inside anything: this lights a surface, and " ..
        "glow is the tool for a halo in open space. If most were off the ramp, this is " ..
        "not the ramp the surface is painted on.",
        sources, solid, ARG.source_tolerance, in_reach, ARG.radius, off_ramp,
        ARG.tolerance, already_brightest), 0)
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               source_pixels = sources, surface_pixels = solid,
               pixels_in_reach = in_reach, lifted_pixels = lifted, per_ring = per_ring,
               pixels_off_ramp = off_ramp,
               pixels_already_brightest = already_brightest }
    """
    result = run_ramp_lua(body, args)
    if isinstance(result, dict):
        result["lifts"] = lifts
        notes = []
        # Said in Python because only Python holds both lists, and the overlap is invisible
        # otherwise: the pass simply spreads light from pixels of the surface itself.
        overlap = _ramp_entries_within(parsed_source, parsed_ramp, source_tol)
        if overlap:
            named = ", ".join(
                f"ramp[{i}] {colour} at {dist:.1f}" for i, colour, dist in overlap
            )
            notes.append(
                f"source_color is within source_tolerance ({source_tol:.1f}) of {named}, "
                "so pixels of those ramp steps are being treated as the light source "
                "rather than as surface to light. Lower source_tolerance, or give the "
                "source a colour the ramp does not come near."
            )
        if radius > 1 and len(set(lifts)) == 1:
            notes.append(
                f"every ring lifts by the same {lifts[0]} step(s), so this is a flat band "
                f"{radius} pixels wide rather than light falling off: at depth {depth} "
                f"there is only one lift to give. Raise depth to at least {radius} so the "
                "surface near the source goes further up the ramp than the surface away "
                "from it."
            )
        if notes:
            existing = result.get("warnings")
            result["warnings"] = (
                [*existing, *notes] if isinstance(existing, list) else notes
            )
    return result


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
    body = FRAME_GUARD_LUA + _RAMP_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot outline a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
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

    local mark = landed()
    for _, p in ipairs(pending) do
      img_set(img, p.x, p.y, rgba_to_px(spr, p.c.r, p.c.g, p.c.b, 255))
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               mode = ARG.mode, outline_pixels = landed() - mark }
    """
    return run_ramp_lua(body, args)


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
            **1-based, while `ramp` is a list the caller indexes from 0**, so the pair
            that dithers `ramp[3]` against `ramp[4]` is `from_step=4, to_step=5`. The two
            conventions usually sit a line apart:

                shade_region_by_light(f, GOLD, base_color=GOLD[4], ...)
                dither_band(f, GOLD, from_step=5, to_step=6, ...)   # GOLD[4], GOLD[5]

            Off by one still names an adjacent pair, so the call succeeds and dithers the
            wrong boundary. The result reports `from_color` and `to_color` for that
            reason: it is the only way to check the intent from the output.
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

    Returns `dithered_pixels`, and `from_color`/`to_color`, the two colours the steps
    actually resolved to.
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
    body = FRAME_GUARD_LUA + _RAMP_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot dither a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)
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

    local mark = landed()
    for _, p in ipairs(pending) do
      local _, _, _, al = px_to_rgba(spr, img:getPixel(p.x, p.y))
      img_set(img, p.x, p.y, rgba_to_px(spr, p.c.r, p.c.g, p.c.b, al))
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
               pattern = ARG.pattern, dithered_pixels = landed() - mark }
    """
    result = run_ramp_lua(body, args)
    # Named in Python, because only Python knows what the caller asked for: the Lua is
    # handed two resolved colours and cannot tell a deliberate pair from an off-by-one.
    # `from_step` is 1-based and the caller's `ramp` is a 0-based list, which is two
    # conventions one line apart, and getting it wrong still names an adjacent pair. That
    # succeeds and dithers the wrong boundary, so the only thing that can catch it is the
    # output saying which colours it used.
    result["from_color"] = ramp[from_step - 1]
    result["to_color"] = ramp[to_step - 1]
    return result


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
    check_region_size(width, height, x=x, y=y, field="map region")

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
    body = FRAME_GUARD_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local layer = find_layer(spr, ARG.layer)
    if layer.isGroup then error("Cannot map a group layer: " .. layer.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img = get_draw_image(spr, layer, framenum)
    draw_target(spr, layer)

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

    local histogram = {}
    for i = 1, #ramp do histogram[i] = 0 end
    -- Kept so this tool still reports `pixels_written` on a region with nothing opaque in
    -- it, where the harness attaches no counters at all. Equal to the harness's number by
    -- construction, since nothing else in this body writes a pixel, and taken from the
    -- same counter so the two cannot drift.
    local mark = landed()

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
            -- Tallied from what landed, not from what was offered: an active selection
            -- refuses the write silently, and a histogram built beside the loop summed
            -- to twice the harness's own `pixels_written` on a half-selected canvas.
            local before = landed()
            img_set(img, xx, yy, rgba_to_px(spr, c.r, c.g, c.b, a))
            if landed() > before then
              histogram[index + 1] = histogram[index + 1] + 1
            end
          end
        end
      end
    end

    commit_image(spr, layer, framenum, img)
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, frame = framenum,
               pixels_written = landed() - mark,
               steps = #ramp, per_step = histogram }
    """
    return run_ramp_lua(body, args)


@mcp.tool()
def shade_facets(
    filename: str,
    rows: list[str],
    legend: dict,
    ramp: list[str],
    light_angle: float = 135.0,
    light_z: float = 0.5,
    fill_strength: float = 0.35,
    ambient: float = 0.16,
    x: int = 0,
    y: int = 0,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Shade a form built from flat planes, one tone per plane, from a map of directions.

    Args:
        rows: One string per row of the map, one character per pixel, as `draw_pixel_map`
            takes. "." leaves a pixel alone.
        legend: {symbol: facet direction}. A direction is an angle in degrees in the same
            convention as `light_angle` (0 faces right, 90 up, 135 up and to the left),
            the word "front" for a plane square to the viewer, or `[angle, z]` to tilt a
            plane toward the viewer as well, which is how a chamfer is said.
        ramp: Colours darkest first. Facet tones are entries of this and nothing else.
        light_angle, light_z: The key light.
        fill_strength: How much bounce comes back from roughly opposite, as a share of the
            key. Without it every plane facing away from the key clamps to the same
            ambient value and the whole shadow side comes out one flat colour.
        ambient: The floor, so a plane facing away is dark rather than black.
        x, y: Where the map's top-left corner lands.

    `shade_region_by_light` reads a surface normal out of how far each pixel sits from the
    silhouette's edge. That is right for anything round and wrong for everything hard: a
    distance field cannot know where an edge is, so it rounds the form over, and a crate
    comes out as a cushion. This takes the normals from the caller instead, because which
    way a plane faces is a fact about the drawing that only the person drawing it knows.

    Every pixel of one facet gets the same value. That flatness is the point: it is what
    reads as cut rather than inflated, and it is the thing a gradient cannot imitate.

    Returns the usual write counts plus `facet_steps`, the ramp step each symbol resolved
    to, so a caller can see the value structure it just asked for. A pass whose facets all
    land on the same step is refused rather than painting a flat fill.
    """
    if len(ramp) < facets.MIN_RAMP:
        raise ValidationFailed(
            f"ramp needs at least {facets.MIN_RAMP} colours to describe a form; got "
            f"{len(ramp)}."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    steps = facets.plan(
        legend, steps=len(ramp), light_angle=float(light_angle),
        light_z=float(light_z), fill_strength=float(fill_strength),
        ambient=float(ambient),
    )
    # Delegated rather than reimplemented: the expansion, every refusal a hand-written
    # grid earns, the selection mask and the clipping counters all already live on that
    # path. A second write path here would have had to grow its own and would have
    # forgotten one.
    result = _write_map(
        filename, rows, {symbol: ramp[step] for symbol, step in steps.items()},
        x=int(x), y=int(y), layer=layer, frame=frame, ramp=ramp,
    )
    result["facet_steps"] = steps
    # Two planes given different directions and handed the same tone will read as one
    # plane, and the caller cannot see that from the picture: the facet it authored is
    # simply not there. Surfaced rather than left to be noticed, because the fix is a
    # choice between three things and only the caller knows which. Absent when it did not
    # happen, like every other count here.
    by_step: dict[int, list[str]] = {}
    for symbol, step in steps.items():
        by_step.setdefault(step, []).append(symbol)
    merged = {step: sorted(syms) for step, syms in by_step.items() if len(syms) > 1}
    if merged:
        result["warnings"] = [
            f"facets {syms} all resolved to ramp step {step}, so they will read as one "
            "plane rather than as separate ones. Separate their angles, tilt one toward "
            "the viewer with [angle, z], or give the pass a longer ramp."
            for step, syms in sorted(merged.items())
        ]
    return result
