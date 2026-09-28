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
