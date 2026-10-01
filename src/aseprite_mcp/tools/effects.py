"""Effects & adjustments: gradients, outline, drop shadow, colour replace,
invert, brightness/contrast, hue/saturation, desaturate, checkerboard.

The cel-editing tools reuse the drawing harness (open -> edit full-canvas image
-> commit -> save). Adjustments are implemented as deterministic per-pixel passes
so they are scoped exactly to the chosen layer + frame and behave identically on
every Aseprite version.
"""

from __future__ import annotations

from ..app import mcp
from ..core import lighting
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_COLOR_LIST_LENGTH,
    MAX_GLOW_RADIUS,
    MAX_OUTLINE_THICKNESS,
    MAX_SHADOW_ELLIPSE_POINTS,
    MAX_SHADOW_SOFTNESS,
    check_count,
    check_list_length,
    check_region_size,
)
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path, run_ramp_lua
from .drawing import _draw
from .shading import _FIELD_LUA

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
            interpolation, great for limited palettes / retro looks.
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


# Shared by the two effects that write their own layer. Both put the effect *behind* the
# artwork, which is what makes them removable: the subject's own cel is never touched, so
# deleting one layer undoes the whole effect.
_EFFECT_LAYER_LUA = r"""
-- Refuse a name that is already taken rather than quietly adding a second layer with it.
-- `find_layer` resolves by name, so two layers called "glow" make every later call that
-- names one ambiguous, and the one you can see is not necessarily the one you changed.
-- Recursive, because find_layer searches inside groups and so a name hidden in a group
-- would collide there while looking free here.
local function require_free_layer_name(spr, name)
  local function scan(layers)
    for _, l in ipairs(layers) do
      if l.name == name then
        error("A layer named '" .. name .. "' already exists in this sprite. Pass " ..
              "new_layer with a different name, or remove_layer the old one first: two " ..
              "layers sharing a name make every later call that names it ambiguous.", 0)
      end
      if l.isGroup then scan(l.layers) end
    end
  end
  scan(spr.layers)
end

-- A fresh layer holding `img`, placed directly BELOW `below`.
local function add_effect_layer(spr, below, framenum, img, name, opacity)
  local lyr = spr:newLayer()
  lyr.name = name
  lyr.opacity = opacity
  -- newLayer lands on top of the stack; assigning the subject's own stackIndex slides
  -- this layer into that slot and pushes the subject up one, which leaves the effect
  -- underneath it.
  lyr.stackIndex = below.stackIndex
  spr:newCel(lyr, framenum, img, Point(0, 0))
  return lyr
end

-- The drawn box of a layer's cel, from the pixels rather than from cel.bounds. Every
-- drawing tool here commits a full-canvas image, so cel.bounds reports the whole canvas
-- and would put a shadow under the canvas's centre instead of under the subject's.
local function drawn_box(spr, img)
  local x0, y0, x1, y1, n = nil, nil, nil, nil, 0
  for y = 0, img.height - 1 do
    for x = 0, img.width - 1 do
      if img_solid(spr, img, x, y) then
        n = n + 1
        if x0 == nil or x < x0 then x0 = x end
        if x1 == nil or x > x1 then x1 = x end
        if y0 == nil or y < y0 then y0 = y end
        if y1 == nil or y > y1 then y1 = y end
      end
    end
  end
  return x0, y0, x1, y1, n
end
"""


@mcp.tool()
def cast_shadow(
    filename: str,
    layer: str,
    ramp: list[str],
    light_angle: float = 135.0,
    light_height: float = 0.6,
    ground_y: int | None = None,
    ground_layer: str | None = None,
    softness: int = 1,
    opacity: int = 255,
    new_layer: str = "shadow",
    frame: int = 1,
) -> dict:
    """Lay a subject's shadow on the ground, away from the light and made of ramp steps.

    `add_drop_shadow` offsets a copy of the artwork and tints it, which is a sticker of
    the subject floating beside it. A cast shadow is a different thing: it falls on a
    *surface*, away from the light, and flattens as it goes, so on the ground it is a
    foreshortened ellipse under the subject rather than a second copy of its silhouette.

    Built entirely of ramp steps, which is the point. A shadow made by multiplying alpha
    lands every pixel of it between palette entries, and then `palette_conformance` drops
    and nothing downstream holds together: indexed export, tileset reuse, a consistent
    look between two sprites. The core is `ramp[0]` and each pixel of `softness` around it
    is one step lighter, so the whole effect is ramp entries arranged in space.

    Where it falls: the direction is away from `light_angle`, and the length comes from
    `light_height` as the actual cotangent of the light's elevation. An overhead light
    casts an ellipse straight underneath; a low light throws it far to one side.

    Onto what: `ground_layer`. Name the layer holding the floor and the shadow is clipped
    to it, so it cannot run off the edge of a platform and hang in the air, and if that
    layer has nothing where the shadow would land the call is refused rather than drawing
    a shadow onto nothing.

    Args:
        layer: The layer casting the shadow. Its cel is never modified.
        ramp: Colours darkest first, normally the *ground's* ramp rather than the
            subject's, since the shadow is a darkening of the surface it lies on.
            Required, and deliberately so: a shadow built out of alpha instead is
            `add_drop_shadow`, which already exists.
        light_angle: Degrees. 0 is from the right, 90 from above, 135 from the upper left.
            The shadow falls the opposite way.
        light_height: The light's elevation, above 0 and up to 1. 1.0 is directly
            overhead and casts no length at all; small values are a low sun and throw a
            long shadow. This is the control that changes the shadow's length.
        ground_y: The row the shadow lies on. Defaults to the subject's own contact row,
            the lowest row it has a pixel on, which is the same measurement
            `validate_loop` reports as `contact_rows`. Refused if it sits above that row,
            because a floor running through the subject is not a floor.
        ground_layer: The layer holding the surface. When given, the shadow is clipped to
            that layer's pixels and the call is refused if there is nothing there to
            catch it.
        softness: Pixels of penumbra around the core, each one ramp step lighter. 0 is a
            hard-edged shadow, 1 or 2 is the usual soft contact.
        opacity: The shadow *layer's* opacity, 0 to 255. Left at 255 the shadow's pixels
            are exactly ramp entries, which is what keeps conformance at 1.0; lowering it
            blends them with whatever is underneath and takes the composite off the ramp,
            so prefer a lighter ramp step over a lower opacity.
        new_layer: Name for the shadow's own layer, created directly below `layer`.
            Refused if a layer of that name already exists.
        frame: Frame to build the shadow for, 1-based.

    Returns the ellipse it used as `shadow_ellipse` (`[cx, cy, rx, ry]`), the
    `contact_row` it measured, and `shadow_pixels`. A shadow that landed entirely off the
    canvas is refused rather than reported as a success that drew nothing.

    `clipped_pixels` is routinely large next to `shadow_pixels` when `ground_layer` is a
    thin floor, and that is arithmetic rather than a fault: the ellipse is centred on the
    contact row and so half of it lies above the floor's top edge, where there is no
    surface. Pass `ground_y` at the floor's own top row to push it down, or leave
    `ground_layer` out and let the subject hide the upper half.

    A shadow is refused when rasterising it would allocate more points than the limit,
    which is reachable from legal arguments on a large canvas: the ellipse's radii grow
    with the subject's size and with how low the light sits, and the point list is built
    in full before any pixel is drawn, so that cost is memory rather than patience. The
    message names both radii and the remedy. `ellipse_points` in the result says how close
    an accepted shadow came.
    """
    if len(ramp) < 2:
        raise ValidationFailed(
            "ramp needs at least 2 colours: a cast shadow is a core step plus the steps "
            "around it, so with one colour there is no shadow to build out of it."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if not 0.0 < light_height <= 1.0:
        raise ValidationFailed(
            f"light_height must be above 0 and at most 1; got {light_height}. At 0 the "
            "light is on the horizon and the shadow is infinitely long, which is not a "
            "picture. Use a small value such as 0.1 for a long low shadow."
        )
    softness = check_count(
        "softness", softness, MAX_SHADOW_SOFTNESS,
        remedy="A penumbra wider than that reads as a gradient rather than as a shadow.",
    )
    if softness + 1 > len(ramp):
        # Refused rather than clamped. Each pixel of penumbra is one step lighter than the
        # one inside it, so the request needs a core step plus one per pixel; with a
        # shorter ramp the outer rings would all land on its last entry and the "soft"
        # edge would be a flat band of one colour, which is not what was asked for and is
        # invisible in the result.
        raise ValidationFailed(
            f"softness {softness} needs {softness + 1} ramp steps, a core plus one for "
            f"each pixel of penumbra, but ramp has {len(ramp)}. Lower softness to "
            f"{len(ramp) - 1}, or pass a longer ramp: stacking the outer rings onto the "
            "last step would draw a flat band and call it a soft edge."
        )
    opacity = check_count("opacity", opacity, 255, remedy="Opacity is 0 to 255.")
    if not new_layer.strip():
        raise ValidationFailed("new_layer must be a name, not blank.")
    if ground_layer is not None and ground_layer == layer:
        raise ValidationFailed(
            "ground_layer is the same layer as the subject, so the subject would be its "
            "own floor and the shadow would be clipped to the shape casting it. Name the "
            "layer holding the ground, or omit ground_layer to place the shadow freely."
        )
    if ground_layer is not None and ground_layer == new_layer:
        raise ValidationFailed(
            "ground_layer and new_layer name the same layer, so the shadow would be "
            "clipped to itself before it existed."
        )

    projection = lighting.shadow_projection(light_angle, light_height)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "ground_y": None if ground_y is None else int(ground_y),
        "ground_layer": ground_layer,
        "dir_x": projection["dir_x"],
        "cot_elev": projection["cot_elev"],
        "flatten": lighting.GROUND_FLATTEN,
        "light_height": float(light_height),
        "softness": softness,
        "opacity": opacity,
        "new_layer": new_layer,
        "max_points": MAX_SHADOW_ELLIPSE_POINTS,
    }
    body = FRAME_GUARD_LUA + _EFFECT_LAYER_LUA + """
    local spr = open_sprite(ARG.src)
    local subject = find_layer(spr, ARG.layer)
    if subject.isGroup then
      error("Cannot cast a shadow from a group layer: " .. subject.name ..
            ". Name one of the layers inside it.", 0)
    end
    local framenum = require_frame(spr, ARG.frame, "frame")
    require_free_layer_name(spr, ARG.new_layer)

    local src = get_draw_image(spr, subject, framenum)
    local W, H = src.width, src.height
    local x0, y0, x1, y1, drawn = drawn_box(spr, src)
    if drawn == 0 then
      error("Layer '" .. subject.name .. "' has nothing drawn on frame " .. framenum ..
            ", so there is no subject to cast a shadow. Draw it first, or name the " ..
            "layer that holds the artwork.", 0)
    end

    -- The contact row: the lowest row the subject has a pixel on, which is where it
    -- meets the ground whether or not a floor is drawn there.
    local contact = y1
    local ground = ARG.ground_y or contact
    if ground < 0 or ground >= H then
      error(string.format(
        "ground_y %d is off the canvas, which is %d pixels tall (rows 0 to %d). The " ..
        "subject's own contact row is %d, which is what this uses when ground_y is " ..
        "omitted.", ground, H, H - 1, contact), 0)
    end
    if ground < contact then
      error(string.format(
        "ground_y %d is above the subject's contact row %d, so the floor would run " ..
        "through the subject and the shadow would land on its legs. Pass a row at or " ..
        "below %d, or omit ground_y to use the contact row.", ground, contact, contact), 0)
    end

    -- Transcribed from core.lighting.shadow_ellipse, which is where this geometry is
    -- explained and tested; only the editor knows the drawn box, so the four lines live
    -- in both places and an integration test asserts they agree.
    local function round(v) return math.floor(v + 0.5) end
    local bw, bh = x1 - x0 + 1, y1 - y0 + 1
    local reach = bh * ARG.cot_elev
    local cx = round((x0 + x1) / 2.0 + ARG.dir_x * reach / 2.0)
    local cy = ground
    local rx = math.max(1, round(bw / 2.0 + reach / 2.0))
    local ry = math.max(1, round((bw / 2.0) * ARG.flatten))

    -- The hard bound, checked first and before anything is rasterised. Transcribed from
    -- core.lighting.filled_ellipse_points: ellipse_offsets emits one table per pixel of a
    -- filled ellipse's AREA and builds the whole list before it returns, so this count is
    -- the allocation rather than the running time. The radii are quadratic in the inputs
    -- and the canvas cap allows 16,384 pixels per axis, so a wide subject under a low
    -- light reaches a point count that is an out-of-memory with nothing drawn, from
    -- arguments that are each individually legal. The softness rings are larger than the
    -- core, so the outermost is the one that has to fit.
    local orx, ory = rx + ARG.softness, ry + ARG.softness
    local points = math.ceil(math.pi * (orx + 1) * (ory + 1))
    if points > ARG.max_points then
      error(string.format(
        "This shadow would rasterise %d points, an ellipse with radii %d and %d, past " ..
        "the limit of %d. The whole point list is built before anything is drawn, so " ..
        "this is memory rather than patience. Raise light_height toward 1 to shorten " ..
        "the shadow, or cast it from a smaller subject.",
        points, orx, ory, ARG.max_points), 0)
    end

    -- The picture bound, which is the one that fires for an ordinary sprite and names the
    -- argument a caller would actually want to change.
    if rx > W or ry > H then
      error(string.format(
        "light_height %.3f throws a shadow %d pixels across on a %dx%d canvas, so it " ..
        "is past anything the sprite can show. Raise light_height toward 1 to shorten " ..
        "it.", ARG.light_height, rx * 2, W, H), 0)
    end

    -- The ground, when one was named. Read before anything is drawn so the refusal below
    -- happens before a layer is created.
    local ground_mask = nil
    if ARG.ground_layer ~= nil then
      local gl = find_layer(spr, ARG.ground_layer)
      if gl.isGroup then
        error("ground_layer '" .. gl.name .. "' is a group layer; name the layer that " ..
              "actually holds the floor's pixels.", 0)
      end
      -- Compared by name, not by identity: the two arguments can name the same layer by
      -- different routes (a name on one side and a stack index on the other), and the
      -- Python-side check only catches the case where the two strings match.
      if gl.name == subject.name then
        error("ground_layer resolves to the subject layer itself ('" .. gl.name ..
              "'), so the shadow would be clipped to the shape casting it. Name the " ..
              "layer holding the ground instead.", 0)
      end
      local gimg = get_draw_image(spr, gl, framenum)
      ground_mask = {}
      for y = 0, H - 1 do
        ground_mask[y] = {}
        for x = 0, W - 1 do ground_mask[y][x] = img_solid(spr, gimg, x, y) end
      end
    end

    -- Painted as a table of ramp indices first, so the softness rings can be laid down
    -- outermost-first and overwritten by the core without any of those intermediate
    -- writes being counted as pixels the tool drew.
    local idx_at = {}
    for y = 0, H - 1 do idx_at[y] = {} end
    local ramp = ARG.ramp
    local function stamp(erx, ery, step)
      if step > #ramp then step = #ramp end
      for _, pt in ipairs(ellipse_offsets(erx, ery, true)) do
        local x, y = cx + pt[1], cy + pt[2]
        if x >= 0 and y >= 0 and x < W and y < H then idx_at[y][x] = step end
      end
    end
    -- Outermost ring first, lightest step, down to the core. Each ring is one ramp step
    -- lighter than the one inside it, which is the penumbra: a shadow is darkest where
    -- the surface and the subject are closest.
    for s = ARG.softness, 1, -1 do stamp(rx + s, ry + s, 1 + s) end
    stamp(rx, ry, 1)

    local out = Image(spr.spec)
    out:clear()
    local painted, clipped = 0, 0
    for y = 0, H - 1 do
      for x = 0, W - 1 do
        local step = idx_at[y][x]
        if step ~= nil then
          if ground_mask ~= nil and not ground_mask[y][x] then
            -- Off the edge of the floor. A shadow is a property of a surface, so with no
            -- surface under it there is nothing to darken.
            clipped = clipped + 1
          else
            local c = ramp[step]
            img_set(out, x, y, rgba_to_px(spr, c.r, c.g, c.b, 255))
            painted = painted + 1
          end
        end
      end
    end

    if painted == 0 then
      if ground_mask ~= nil then
        error(string.format(
          "There is no surface for this shadow to land on: layer '" ..
          ARG.ground_layer .. "' has no pixels anywhere the shadow falls (an ellipse " ..
          "%dx%d centred on %d,%d, with %d pixels clipped away). Draw the ground " ..
          "first, extend it under the subject, or omit ground_layer to place the " ..
          "shadow without clipping it to a floor.",
          rx * 2, ry * 2, cx, cy, clipped), 0)
      end
      error(string.format(
        "The shadow landed entirely off the canvas: an ellipse %dx%d centred on %d,%d " ..
        "on a %dx%d canvas. Raise light_height to shorten it, or move the subject.",
        rx * 2, ry * 2, cx, cy, W, H), 0)
    end

    local lyr = add_effect_layer(spr, subject, framenum, out, ARG.new_layer, ARG.opacity)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = lyr.name,
               subject_layer = subject.name, frame = framenum,
               shadow_ellipse = { cx, cy, rx, ry }, contact_row = contact,
               ground_y = ground, subject_box = { x0, y0, x1, y1 },
               shadow_pixels = painted, clipped_pixels = clipped,
               ellipse_points = points,
               softness = ARG.softness, opacity = ARG.opacity }
    """
    return run_ramp_lua(body, args)


@mcp.tool()
def glow(
    filename: str,
    ramp: list[str],
    radius: int = 3,
    falloff: str = "linear",
    dither_edge: bool = True,
    base_color: str | None = None,
    tolerance: float = 24.0,
    new_layer: str = "glow",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Halo a shape in rings of ramp steps, so it glows without leaving the palette.

    `add_outline` gives one flat ring, which reads as a sticker. A glow is several rings,
    each a step further down a ramp: hottest against the artwork, fading outward, with the
    outer ring optionally dithered so it ends in something softer than a hard edge.

    The ramp is what makes this different from a glow in an image editor. A halo made of
    alpha, or of colours interpolated between two others, takes the art off its palette,
    and then `palette_conformance` drops and the sprite no longer exports to an indexed
    format, reuses a tileset, or matches the sprite beside it. Every pixel this writes is
    exactly one of the colours you passed in.

    The glow goes on its own layer below the artwork, so the subject's cel is untouched
    and deleting one layer removes the effect.

    Args:
        ramp: Colours darkest first. Ring 1, touching the artwork, takes the top step and
            the outermost ring takes `ramp[0]`, so a longer ramp fades more finely. For a
            glow that reads as light rather than as a coloured border this usually wants
            its own bright ramp (a gem's or a flame's), not the subject's body ramp.
        radius: How many rings, in pixels. 2 or 3 reads as a glow; much more reads as fog.
        falloff: "linear" spaces the steps evenly. "quadratic" drops away faster, keeping
            a hotter core and a dimmer skirt, which is the one that reads as a light
            source rather than as an outline.
        dither_edge: Dither the outermost ring, so the glow ends in a half-density
            scatter instead of a hard line. This is binary coverage, a pixel either drawn
            or not, rather than a partial alpha, so every drawn pixel is still exactly a
            ramp step and conformance stays at 1.0.
        base_color: Glow only around pixels near this colour, which is how a gem glows
            while the hand holding it does not. Distance is measured out from those
            pixels, but the glow is never painted over any part of the subject layer, so
            a body blocks the halo of a gem inside it.
        tolerance: How close a pixel must be to `base_color` to be treated as a source,
            as a weighted RGB distance. Ignored when `base_color` is omitted.
        new_layer: Name for the glow's own layer, created directly below `layer`. Refused
            if a layer of that name already exists.
        layer: The layer to glow around (default: top layer). Its cel is never modified.
        frame: Target frame, 1-based.

    Refuses rather than drawing nothing: no pixel matching `base_color` is an error, and
    so is a subject that leaves the glow nowhere to go.
    """
    if len(ramp) < 2:
        raise ValidationFailed(
            "ramp needs at least 2 colours: a glow is a fade through ramp steps, and "
            "with one colour it is add_outline."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    if falloff not in lighting.FALLOFFS:
        raise ValidationFailed(
            f'falloff must be "linear" or "quadratic"; got {falloff!r}.'
        )
    radius = check_count(
        "radius", radius, MAX_GLOW_RADIUS, minimum=1,
        remedy="A glow wider than a sprite is tall is a background fill, which "
               "fill_gradient does better.",
    )
    if tolerance < 0:
        raise ValidationFailed("tolerance must not be negative.")
    if not new_layer.strip():
        raise ValidationFailed("new_layer must be a name, not blank.")

    # Which ramp step each ring takes, decided in Python so the Lua does a table lookup
    # and the curve can be checked against a list of integers rather than a picture.
    rings = lighting.glow_rings(radius, len(ramp), falloff)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "ramp": [parse_color(c) for c in ramp],
        "base": parse_color(base_color) if base_color else None,
        "rings": rings,
        "radius": radius,
        "dither_edge": bool(dither_edge),
        "tolerance": float(tolerance),
        "new_layer": new_layer,
    }
    body = FRAME_GUARD_LUA + _FIELD_LUA + _EFFECT_LAYER_LUA + """
    local spr = open_sprite(ARG.src)
    local subject = find_layer(spr, ARG.layer)
    if subject.isGroup then
      error("Cannot glow a group layer: " .. subject.name ..
            ". Name one of the layers inside it.", 0)
    end
    local framenum = require_frame(spr, ARG.frame, "frame")
    require_free_layer_name(spr, ARG.new_layer)

    local src = get_draw_image(spr, subject, framenum)
    local W, H = src.width, src.height
    local base = ARG.base

    -- Two masks doing two different jobs. The glow is emitted by the pixels matching
    -- base_color and may not cover any pixel of the subject, which are the same set when
    -- no base_color was given and, when one was, the difference between a gem lighting up
    -- the air around it and a gem lighting up the hand holding it.
    --
    -- The emitting set is stored already inverted, as `outside`, because that is the only
    -- form anything later needs: the chamfer field measures distance *out* from the art,
    -- so it wants a mask that is true where the art is not. Building it inverted here
    -- rather than negating a second table afterwards keeps one full-canvas table alive
    -- instead of two, which on a large sprite is the difference that matters.
    local outside, occupied = {}, {}
    local seeds, solid = 0, 0
    for y = 0, H - 1 do
      outside[y], occupied[y] = {}, {}
      for x = 0, W - 1 do
        local r, g, b, a = px_to_rgba(spr, src:getPixel(x, y))
        local is_solid = a > 0
        local is_seed = false
        if is_solid then
          solid = solid + 1
          if base == nil then
            is_seed = true
          else
            local dr, dg, db = r - base.r, g - base.g, b - base.b
            is_seed = math.sqrt(0.299*dr*dr + 0.587*dg*dg + 0.114*db*db) <= ARG.tolerance
          end
        end
        outside[y][x] = not is_seed
        occupied[y][x] = is_solid
        if is_seed then seeds = seeds + 1 end
      end
    end

    if seeds == 0 then
      if base ~= nil then
        error("No pixel matched base_color, so there is nothing to glow around. Check " ..
              "the colour, or raise tolerance.", 0)
      end
      error("Layer '" .. subject.name .. "' has nothing drawn on frame " .. framenum ..
            ", so there is nothing to glow around.", 0)
    end

    -- The chamfer field run on the inverted mask, which turns "distance into the shape"
    -- into "distance out from it". One O(canvas) pass whatever the radius, where scanning
    -- a neighbourhood per pixel would have been O(canvas * radius^2).
    local dist = distance_field(outside, W, H)
    -- Dropped as soon as the field exists, so the mask and the field are not both held
    -- while the much larger paint loop runs.
    outside = nil

    local BAYER = { {0,8,2,10}, {12,4,14,6}, {3,11,1,9}, {15,7,13,5} }
    local out = Image(spr.spec)
    out:clear()
    local ramp, rings = ARG.ramp, ARG.rings
    local painted, per_ring = 0, {}
    for i = 1, ARG.radius do per_ring[i] = 0 end

    for y = 0, H - 1 do
      for x = 0, W - 1 do
        if not occupied[y][x] then
          -- The field counts 3 per orthogonal step and 4 per diagonal one, so a pixel
          -- touching the artwork reads 3 and lands in ring 1.
          local ring = math.floor(dist[y][x] / 3.0 + 0.5)
          if ring >= 1 and ring <= ARG.radius then
            local draw = true
            if ARG.dither_edge and ring == ARG.radius and ARG.radius > 0 then
              -- Half the pixels of the outermost ring, chosen by an ordered pattern. The
              -- fade is in the coverage, not in an alpha value, so the pixels that are
              -- drawn are still exactly ramp entries.
              draw = BAYER[(y % 4) + 1][(x % 4) + 1] < 8
            end
            if draw then
              local c = ramp[rings[ring]]
              img_set(out, x, y, rgba_to_px(spr, c.r, c.g, c.b, 255))
              painted = painted + 1
              per_ring[ring] = per_ring[ring] + 1
            end
          end
        end
      end
    end

    if painted == 0 then
      error(string.format(
        "The glow had nowhere to go: every pixel within %d of the %d matching pixels " ..
        "is either part of the subject or off the canvas. Trim or resize the canvas to " ..
        "leave room around the artwork.", ARG.radius, seeds), 0)
    end

    local lyr = add_effect_layer(spr, subject, framenum, out, ARG.new_layer, 255)
    save_sprite(spr)
    RESULT = { ok = true, filename = spr.filename, layer = lyr.name,
               subject_layer = subject.name, frame = framenum,
               seed_pixels = seeds, subject_pixels = solid,
               glow_pixels = painted, per_ring = per_ring,
               rings = rings, radius = ARG.radius, falloff_dithered = ARG.dither_edge }
    """
    return run_ramp_lua(body, args)


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
