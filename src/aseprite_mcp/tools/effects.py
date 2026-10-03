"""Effects & adjustments: gradients, outline, drop shadow, colour replace,
invert, brightness/contrast, hue/saturation, desaturate, checkerboard.

The cel-editing tools reuse the drawing harness (open -> edit full-canvas image
-> commit -> save). Adjustments are implemented as deterministic per-pixel passes
so they are scoped exactly to the chosen layer + frame and behave identically on
every Aseprite version.
"""

from __future__ import annotations

from ..app import mcp
from ..core import edges, lighting
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_ASSESS_PIXELS,
    MAX_COLOR_LIST_LENGTH,
    MAX_GLOW_RADIUS,
    MAX_OUTLINE_THICKNESS,
    MAX_SHADOW_ELLIPSE_POINTS,
    MAX_SHADOW_SOFTNESS,
    MAX_STRAY_CLUSTER,
    check_count,
    check_list_length,
    check_region_size,
)
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import run_lua
from .common import LANDED_LUA, lua_path, parse_color, resolve_path, run_ramp_lua
from .drawing import _CLOSE, _OPEN, _draw
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
    check_region_size(width, height, x=x, y=y, field="gradient region")
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
    light_angle: float | None = None,
    lit_thickness: int | None = None,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Add a pixel outline around the artwork on a layer, optionally weighted by light.

    Args:
        color: Outline colour.
        thickness: Outline width in pixels (default 1). With `light_angle`, this is the
            width on the edges that face away from the light.
        connectivity: 4 (orthogonal only) or 8 (includes diagonals, default).
        where: "outside" (grow into transparency, default) or "inside"
            (recolour the shape's border pixels).
        light_angle: Degrees, 0 from the right and 90 from above, as the shading tools
            state it. Given, the outline's width varies by which way each edge faces:
            `thickness` where the form turns away from the light, `lit_thickness` where
            it faces into it, and **everything between the two across the band of edge in
            between**.
        lit_thickness: Width on the edges facing the light. 0 drops the outline there
            entirely. Defaults to one pixel less than `thickness`. A value above
            `thickness` is allowed and puts the weight on the lit side instead, which is
            a rim light rather than a weighted outline.

    A constant-width border is the single thing that most reliably makes a sprite read as
    a die-cut sticker: nothing lit has an edge of uniform darkness, so the eye sees card
    stamped out with a punch rather than a form in light. Hand-drawn work in this style
    gathers the weight where the surface turns away and lets it vanish on the lit top
    faces. `thickness=2, light_angle=135, lit_thickness=0` is that look.

    The weight **tapers** rather than switching. The lit and shadow widths are the two ends
    of a run of integers, and each edge pixel takes the one its facing selects, so a 2-to-0
    keyline passes through 2, then 1, then 0 across a band of edge instead of flipping
    between two values at the terminator. Facing is measured over a neighbourhood rather
    than over the touching pixels, which is what makes the band continuous on a lumpy
    silhouette: at a radius of one, a single-pixel bump swings the facing by ninety degrees
    and the keyline comes apart into scraps. Measured by walking the boundary ring of a disc
    with twelve bumps on it, the old per-pixel test crossed between outlined and bare 30
    times, which is fifteen separate pieces of keyline; the taper crosses twice, which is
    one arc. That fragmenting is why `lit_thickness=0` had to be reverted to 1 on this
    project's own golem, where it measured better and looked damaged.

    With the two widths one apart there are only two integers to choose from and the
    changeover sits at the same facing the old comparison used, so
    `thickness=2, lit_thickness=1` draws exactly what it drew before. The taper appears once
    they differ by two or more, which is the case that was broken.

    Reports `outline_weights` alongside the lit and shadow counts: how many of the
    silhouette's own boundary pixels took each thickness, from 0 upward. That is the number
    that says whether a pass tapered or switched, since a switch leaves the entries between
    its two widths empty.

    For an outline in colours taken from the artwork's own ramp rather than one flat
    colour, see `outline_smart`, which varies hue instead of width.
    """
    if connectivity not in (4, 8):
        raise ValidationFailed("connectivity must be 4 or 8")
    if where not in ("outside", "inside"):
        raise ValidationFailed('where must be "outside" or "inside"')
    if lit_thickness is not None and light_angle is None:
        raise ValidationFailed(
            "lit_thickness needs light_angle: which edges are lit is not knowable "
            "without a light direction. Pass light_angle=135 for the usual key light."
        )
    shadow_side = check_count(
        "thickness", max(1, int(thickness)), MAX_OUTLINE_THICKNESS, minimum=1,
        remedy="Each pixel of thickness is another full-canvas pass; outline in "
               "several calls if you really need more.",
    )
    if light_angle is None:
        lit_side = shadow_side
    elif lit_thickness is None:
        if shadow_side == 1:
            # Accepting this would take a light direction and draw exactly the border it
            # drew before, which is the kind of silent no-op this project treats as worse
            # than an error.
            raise ValidationFailed(
                "light_angle with thickness=1 has nothing to redistribute: one pixel on "
                "the shadow side and one on the lit side is the uniform outline it would "
                "have drawn anyway. Raise thickness to 2 so the shadow side is heavier, "
                "or pass lit_thickness=0 to drop the outline on the lit side instead."
            )
        lit_side = shadow_side - 1
    else:
        lit_side = check_count(
            "lit_thickness", int(lit_thickness), MAX_OUTLINE_THICKNESS, minimum=0,
            remedy="Each pixel of thickness is another full-canvas pass; outline in "
                   "several calls if you really need more.",
        )
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "thickness": shadow_side,
        "lit_thickness": lit_side,
        # The loop has to follow the larger of the two, or a rim light's extra passes
        # never run and `lit_thickness` above `thickness` would silently clamp.
        "passes": max(shadow_side, lit_side),
        # Built here rather than in Lua so the angle convention has one definition, in
        # core, shared with every other tool that takes a light angle. z=0 because this
        # is a question about the screen plane: an edge faces left, not toward the viewer.
        "light": (None if light_angle is None
                  else list(lighting.light_vector(light_angle, 0.0)[:2])),
        # The thickness at each facing, innermost-shadow first. Built in core so the taper
        # is a list of integers rather than arithmetic transcribed into Lua, and absent
        # when no light was given, which is what switches the whole facing pass off and
        # leaves a call with no light drawing exactly the uniform border it always drew.
        "taper": (None if light_angle is None
                  else lighting.taper_weights(shadow_side, lit_side)),
        "facing_radius": lighting.TAPER_RADIUS,
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
    local W, H = img.width, img.height
    local done = {}
    local function key(x, y) return y * W + x end

    -- An outside outline grows: what a pass lays down is solid, so the next pass finds
    -- the next ring out by itself. An inside one does not, because recolouring a border
    -- pixel leaves it just as opaque as it was. Every pass therefore used to re-mark the
    -- same border, and `thickness` had no effect at all beyond the first pixel: an inside
    -- outline came out one pixel wide whatever was asked for. Carrying `done` forward and
    -- treating it as already-outlined is what makes the second pass step inward.
    local function is_seed(x, y)
      if ARG.where == "inside" then
        return (not img_solid(spr, img, x, y)) or done[key(x, y)] == true
      end
      return img_solid(spr, img, x, y)
    end
    local function is_candidate(x, y)
      if ARG.where == "inside" then
        return img_solid(spr, img, x, y) and done[key(x, y)] ~= true
      end
      return not img_solid(spr, img, x, y)
    end

    -- Whether this pixel is on the boundary at all: does anything across the edge touch
    -- it. A membership test only, and deliberately at a radius of one, because the ring a
    -- pass lays down is the pixels adjacent to what came before.
    local function touches_seed(xx, yy)
      for _, nb in ipairs(neighbors(xx, yy)) do
        if is_seed(nb[1], nb[2]) then return true end
      end
      return false
    end
    -- An outside outline's seeds are the shape, so its outward normal is the negation of
    -- the direction to them; an inside outline's seeds are already outside the shape, so
    -- there it is that direction itself.
    local nsign = 1
    if ARG.where == "outside" then nsign = -1 end

    -- Which way the edge faces here, as the sum of the directions to everything across it
    -- within `facing_radius`, each weighted by one over its distance squared. Summed
    -- rather than taken from one neighbour because a pixel in a concave corner is seeded
    -- from two sides at once and the average is the direction the edge actually faces;
    -- summed over a neighbourhood rather than over the touching pixels because at a radius
    -- of one a single-pixel bump swings the answer by ninety degrees, and the outline then
    -- changes weight pixel by pixel instead of across a band. The weighting is what keeps
    -- the mass behind an edge in charge of the bump in front of it.
    local R = ARG.facing_radius
    local function facing(xx, yy)
      local fx, fy = 0.0, 0.0
      for dy = -R, R do
        for dx = -R, R do
          local d2 = dx * dx + dy * dy
          if d2 > 0 and d2 <= R * R and is_seed(xx + dx, yy + dy) then
            fx = fx + dx / d2
            fy = fy + dy / d2
          end
        end
      end
      local length = math.sqrt(fx * fx + fy * fy)
      if length < 1e-9 then return nil end
      return (nsign * fx) / length, (nsign * fy) / length
    end

    local lit_laid, shadow_laid = 0, 0
    -- How many of the shape's own edge pixels took each thickness, from 0 upward. The
    -- measurement that says whether this tapered or switched: a switch puts everything in
    -- two entries, and a taper fills the ones between them. Tallied on the first pass,
    -- where the candidates are exactly the silhouette's boundary ring.
    local weights = {}
    for i = 1, ARG.passes + 1 do weights[i] = 0 end
    for _pass = 1, ARG.passes do
      local mark = {}
      for yy = 0, H - 1 do
        for xx = 0, W - 1 do
          if is_candidate(xx, yy) and touches_seed(xx, yy) then
            local allowed, lit = ARG.thickness, false
            if ARG.taper ~= nil then
              local nx, ny = facing(xx, yy)
              -- A facing that cancels exactly is not determinate: a one-pixel sliver has
              -- background on both sides at once. Such a pixel is still an edge and still
              -- gets outlined, at the shadow side's weight, because the alternative is
              -- dropping it and breaking the silhouette.
              if nx ~= nil then
                local toward = nx * ARG.light[1] + ny * ARG.light[2]
                if toward < -1 then toward = -1 elseif toward > 1 then toward = 1 end
                -- The table is built in core.lighting, so the shape of the taper is a
                -- list of integers that can be asserted on rather than a band of pixels
                -- that can only be looked at.
                local bucket = math.floor((toward + 1) * 0.5 * (#ARG.taper - 1) + 0.5) + 1
                allowed = ARG.taper[bucket]
                lit = toward > 0
              end
            end
            if _pass == 1 then weights[allowed + 1] = weights[allowed + 1] + 1 end
            if _pass <= allowed then
              mark[#mark+1] = {xx, yy}
              if lit then lit_laid = lit_laid + 1 else shadow_laid = shadow_laid + 1 end
            end
          end
        end
      end
      for _, p in ipairs(mark) do
        img_set(img, p[1], p[2], oc)
        done[key(p[1], p[2])] = true
      end
    end
    if ARG.taper ~= nil then
      _extra = { outline_lit = lit_laid, outline_shadow = shadow_laid,
                 outline_weights = weights }
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
    body = FRAME_GUARD_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local target = find_layer(spr, ARG.layer)
    if target.isGroup then error("Cannot shadow a group layer: " .. target.name) end
    local framenum = require_frame(spr, ARG.frame, "frame")
    local src = get_draw_image(spr, target, framenum)
    local shadow = Image(spr.spec); shadow:clear()
    local sc = to_pixel(spr, ARG.color)
    local mark = landed()
    for yy = 0, src.height - 1 do
      for xx = 0, src.width - 1 do
        if img_solid(spr, src, xx, yy) then img_set(shadow, xx + ARG.dx, yy + ARG.dy, sc) end
      end
    end
    -- A layer with nothing on it is not a shadow. The counters were honest here (0 written
    -- beside 64 refused), but the layer still went in, and `cast_shadow` and `glow` refuse
    -- the same situation, so this answering with a success was the odd one out.
    if landed() == mark then
      if _sel ~= nil then
        error("The shadow landed entirely outside the active selection, so nothing was " ..
              "written and no layer was added. deselect, or select a region the " ..
              "offset silhouette falls in.", 0)
      end
      error(string.format(
        "The shadow landed entirely off the canvas: layer '%s' offset by %d,%d on a " ..
        "%dx%d canvas leaves nothing on it, so no layer was added. Lower the offset, " ..
        "or resize_canvas to leave room.",
        target.name, ARG.dx, ARG.dy, spr.width, spr.height), 0)
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
-- The layer an effect will write into: a new one, or the one it made last time.
--
-- The guarantee worth keeping is about a *cel*: two effects composited into one cel are a
-- picture neither call describes, so a second call to the same layer and frame is refused.
-- That used to be enforced on the *layer*, and a layer spans every frame, so a four-frame
-- torch flicker needed `glow 1` through `glow 4`, each holding a single cel and empty on
-- the other three. A ten-frame effect needed ten. The layer stack then said nothing about
-- the animation it belonged to.
--
-- Reuse is only allowed for a layer this tool made itself. Writing a glow into a layer
-- somebody drew art on is a different surprise, and the position matters too: `new_layer`
-- is documented as sitting directly below `layer`, so a layer that has since been moved
-- elsewhere is not the one this call would choose.
--
-- The mark goes in namespaced plugin data rather than in `layer.data`. `data` is the User
-- Data field the editor shows and a caller may be using for their own notes, and
-- `set_properties` already treats the unnamed group as theirs; a namespace is the slot
-- Aseprite provides for exactly this. It travels in the .aseprite file, which is what
-- makes it readable on the next call: every call here is its own process.
local EFFECT_NS = "aseprite-mcp"
local EFFECT_MARK = "effect_layer"

local function effect_layer_for(spr, below, name, framenum)
  local found = nil
  local function scan(layers)
    for _, l in ipairs(layers) do
      if l.name == name then found = l end
      if l.isGroup then scan(l.layers) end
    end
  end
  scan(spr.layers)
  if found == nil then return nil end

  if found.properties(EFFECT_NS)[EFFECT_MARK] ~= true then
    error("A layer named '" .. name .. "' already exists in this sprite and was not " ..
          "created by this tool, so writing an effect into it would overwrite whatever " ..
          "is there. Pass new_layer with a different name, or remove_layer the old one " ..
          "first.", 0)
  end
  if found.stackIndex ~= below.stackIndex - 1 then
    error("The layer named '" .. name .. "' is no longer directly below '" ..
          below.name .. "', so an effect written into it would not sit where this tool " ..
          "places one. Move it back, or pass new_layer with a different name.", 0)
  end
  if found:cel(framenum) ~= nil then
    error("The layer named '" .. name .. "' already has a cel on frame " ..
          tostring(framenum) .. ". Two effects composited into one cel are a picture " ..
          "neither call describes, so pass new_layer with a different name, or " ..
          "delete_cel that frame first. Writing the same effect layer on a *different* " ..
          "frame is fine and is how a per-frame effect is built.", 0)
  end
  return found
end

-- A fresh layer holding `img`, placed directly BELOW `below`.
local function add_effect_layer(spr, below, framenum, img, name, opacity)
  -- Reused when this tool made it and the target frame is free, which is what lets one
  -- layer carry a per-frame effect across a whole animation.
  local lyr = effect_layer_for(spr, below, name, framenum)
  if lyr == nil then
    lyr = spr:newLayer()
    lyr.name = name
    -- Marked as ours, so a later call can tell its own layer from one holding artwork.
    lyr.properties(EFFECT_NS)[EFFECT_MARK] = true
    -- newLayer lands on top of the stack; assigning the subject's own stackIndex slides
    -- this layer into that slot and pushes the subject up one, which leaves the effect
    -- underneath it.
    lyr.stackIndex = below.stackIndex
  end
  lyr.opacity = opacity
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


def _ground_layer_notes(result: dict) -> list[str]:
    """What to say about a ground layer that the finished picture does not show.

    `ground_layer` is consulted for its drawn pixels and nothing else, which is the right
    "onto what" question: a shadow is a property of the surface under it, and a surface is
    where its pixels are. A hidden layer has those pixels too, though, and so does one at
    a tenth opacity, so the shadow landed crisply on a floor that is not in the picture and
    nothing in the result mentioned it (#146).

    Reported rather than refused, which is the choice worth stating. The clip is still
    answerable and the geometry is still right; hiding the floor while working on the
    subject, or keeping it faint as an underpainting, are ordinary things to do; and the
    shadow goes on a new layer of its own, so nothing is spent by proceeding. A refusal
    would break those calls to say something a sentence says better, and it would need a
    `force` to climb back out of. What was actually missing was the sentence.

    The measurements come from the editor, which is the only thing that knows them; the
    judgement is here so CI can test it with no editor installed.
    """
    name = result.get("ground_layer")
    if name is None:
        return []

    notes: list[str] = []
    hidden = result.get("ground_layer_hidden") or []
    if hidden:
        # Aseprite's visibility is per layer, so a floor inside a hidden group reports
        # itself visible while none of it reaches the render. The note has to name what is
        # actually switched off, because that is what the caller has to go and change.
        groups = [entry for entry in hidden if entry != name]
        listed = " and ".join(f"'{entry}'" for entry in groups)
        plural = "groups" if len(groups) > 1 else "group"
        if groups and name in hidden:
            what = f"'{name}' is hidden, and so is the {plural} {listed} it sits in"
        elif groups:
            what = (f"'{name}' sits in the hidden {plural} {listed}, and its own flag "
                    "is on")
        else:
            what = f"'{name}' is hidden"
        notes.append(
            f"ground_layer {what}, so this shadow was clipped to a surface the render "
            "does not show. Its pixels are there, which is all the clip asks about, and "
            "none of them reach the picture. Make it visible with set_layer_properties, "
            "or name the layer that already is."
        )

    opacity = result.get("ground_layer_opacity")
    if opacity == 0:
        notes.append(
            f"ground_layer '{name}' is at opacity 0, which is a hidden layer by another "
            "route: the shadow is fully solid over a surface that shows nothing of itself."
        )
    elif isinstance(opacity, int | float) and opacity < 255:
        notes.append(
            f"ground_layer '{name}' is at opacity {opacity} of 255, so the shadow reads as "
            "more solid than the floor it lies on. Match a faint floor with a lighter ramp "
            "step rather than by lowering the shadow layer's opacity, which blends its "
            "pixels with what is under them and takes the composite off the ramp."
        )
    return notes


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
        layer: The layer casting the shadow. Its cel is never modified. A background
            layer is refused: it is opaque and covers the canvas, so it has no silhouette
            to cast. `convert_background_to_layer` first if the subject is one.
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
            catch it. Consulted for its pixels, not for whether the picture shows them: a
            hidden layer, or one at a low opacity, still holds the pixels the clip asks
            about, so the shadow is drawn and the result reports what the floor actually
            is (see below) rather than the call being refused over it.
        softness: Pixels of penumbra around the core, each one ramp step lighter. 0 is a
            hard-edged shadow, 1 or 2 is the usual soft contact.
        opacity: The shadow *layer's* opacity, 0 to 255. Left at 255 the shadow's pixels
            are exactly ramp entries, which is what keeps conformance at 1.0; lowering it
            blends them with whatever is underneath and takes the composite off the ramp,
            so prefer a lighter ramp step over a lower opacity.
        new_layer: Name for the shadow's own layer, created directly below `layer`, or
            reused when a previous call of this tool made it and `frame` has no cel on it
            yet. That is how one shadow layer carries a whole walk cycle. A second call for
            the same layer *and* frame is refused, because two effects composited into one
            cel are a picture neither call describes, and so is a layer of that name this
            tool did not create.
        frame: Frame to build the shadow for, 1-based.

    Returns the ellipse it used as `shadow_ellipse` (`[cx, cy, rx, ry]`), the
    `contact_row` it measured, and `shadow_pixels`. A shadow that landed entirely off the
    canvas is refused rather than reported as a success that drew nothing.

    With a `ground_layer` the result also says what that floor is: `ground_layer_visible`,
    `ground_layer_opacity`, and `ground_layer_hidden` naming the layer and any group whose
    flag is off, which is present only when something is. A floor the picture does not
    show, or shows faintly, is reported in `warnings` as well, because a crisp shadow on
    an invisible surface is usually a layer named by mistake rather than an intent.

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
    body = FRAME_GUARD_LUA + _EFFECT_LAYER_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local subject = find_layer(spr, ARG.layer)
    if subject.isGroup then
      error("Cannot cast a shadow from a group layer: " .. subject.name ..
            ". Name one of the layers inside it.", 0)
    end
    -- Said here rather than letting the projection fail further down, because what comes
    -- out of there is a sentence about light_height, and light_height was never the
    -- problem. A background is opaque and covers the canvas, so the drawn box below is
    -- the whole canvas: on a square sprite that produced a confident success, an ellipse
    -- cast from the canvas's own outline, and on a taller one it overflowed the canvas
    -- check and sent the caller off to tune a light that was fine (#146).
    if subject.isBackground then
      error("Layer '" .. subject.name .. "' is this sprite's background, so it cannot " ..
            "cast a shadow: a background is opaque and fills the canvas, which leaves " ..
            "it no silhouette to cast. convert_background_to_layer turns it back into " ..
            "an ordinary layer, after which only the pixels drawn on it count and the " ..
            "shadow has a shape to come from.", 0)
    end
    local framenum = require_frame(spr, ARG.frame, "frame")

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
    local ground_name, ground_opacity, ground_hidden = nil, nil, nil
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
      -- What the render shows of this floor, measured rather than judged: the sentences
      -- are built in Python, where CI can read them. `isVisible` is one layer's own flag,
      -- so a floor inside a hidden group reports itself visible while nothing of it
      -- reaches the picture; walking up collects every flag that is off, nearest first.
      -- `parent` leads to the sprite, which is not a layer and has none of these fields,
      -- so that is where the walk stops.
      ground_name = gl.name
      ground_opacity = gl.opacity
      ground_hidden = {}
      if not gl.isVisible then ground_hidden[#ground_hidden + 1] = gl.name end
      local node = gl.parent
      while node ~= nil and node ~= spr do
        if not node.isVisible then ground_hidden[#ground_hidden + 1] = node.name end
        node = node.parent
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
    local mark = landed()
    local clipped = 0
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
          end
        end
      end
    end
    -- What landed, not what was offered. Counting beside the loop meant an active
    -- selection that the ellipse never reaches took every write and still let this
    -- report `shadow_pixels: 95`, add a shadow layer with nothing on it, and sail past
    -- the refusal below, which is the one thing here that could have caught it.
    local painted = landed() - mark

    if painted == 0 then
      if _sel ~= nil then
        error(string.format(
          "The shadow landed entirely outside the active selection: an ellipse %dx%d " ..
          "centred on %d,%d, with every one of its pixels masked out. Nothing was " ..
          "written and no layer was added. deselect, or select a region the shadow " ..
          "falls in.", rx * 2, ry * 2, cx, cy), 0)
      end
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
    if ground_name ~= nil then
      RESULT.ground_layer = ground_name
      RESULT.ground_layer_visible = (#ground_hidden == 0)
      RESULT.ground_layer_opacity = ground_opacity
      -- Absent rather than empty, so the key appearing at all means there is something
      -- switched off to go and look at.
      if #ground_hidden > 0 then RESULT.ground_layer_hidden = ground_hidden end
    end
    """
    result = run_ramp_lua(body, args)
    if isinstance(result, dict):
        notes = _ground_layer_notes(result)
        if notes:
            # Appended rather than assigned, for the same reason run_ramp_lua appends its
            # own: an indexed sprite may already have put a ramp reading here, and
            # dropping that to report this would trade one finding for another.
            existing = result.get("warnings")
            result["warnings"] = [*existing, *notes] if isinstance(existing, list) else notes
    return result


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
        new_layer: Name for the glow's own layer, created directly below `layer`, or
            reused when a previous call of this tool made it and `frame` has no cel on it
            yet. That is how one glow layer carries a flickering torch across four frames
            rather than needing four layers with one cel each. A second call for the same
            layer *and* frame is refused, because two halos composited into one cel are a
            picture neither call describes, and so is a layer of that name this tool did
            not create.
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
    body = FRAME_GUARD_LUA + _FIELD_LUA + _EFFECT_LAYER_LUA + LANDED_LUA + """
    local spr = open_sprite(ARG.src)
    local subject = find_layer(spr, ARG.layer)
    if subject.isGroup then
      error("Cannot glow a group layer: " .. subject.name ..
            ". Name one of the layers inside it.", 0)
    end
    local framenum = require_frame(spr, ARG.frame, "frame")

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
    local mark = landed()
    local per_ring = {}
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
              -- Tallied from what landed. `img_set` refuses a write outside the active
              -- selection, and counting the offer instead let a selection in a corner
              -- the glow never reaches produce `glow_pixels: 56`, `per_ring: [36, 20]`,
              -- `pixels_written: 0` and a glow layer with nothing at all on it.
              local before = landed()
              img_set(out, x, y, rgba_to_px(spr, c.r, c.g, c.b, 255))
              if landed() > before then
                per_ring[ring] = per_ring[ring] + 1
              end
            end
          end
        end
      end
    end

    local painted = landed() - mark
    if painted == 0 then
      if _sel ~= nil then
        error(string.format(
          "The glow landed entirely outside the active selection: every pixel of the " ..
          "%d-pixel ring around the %d matching pixels was masked out. Nothing was " ..
          "written and no layer was added. deselect, or select a region the glow " ..
          "reaches.", ARG.radius, seeds), 0)
      end
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
          img_set(img, xx, yy, tp)
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
          img_set(img, xx, yy, rgba_to_px(spr, nr, ng, nb, na))
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
    check_region_size(width, height, x=x, y=y, field="checkerboard region")
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


# `replaced` reaches the result through the drawing harness, which carries exactly one
# counter for every tool that uses it. Erasing is a second count and a different promise,
# so it is attached here, after that harness has built RESULT, rather than by widening a
# block every drawing tool shares for the sake of one of them.
@mcp.tool()
def remove_stray_pixels(
    filename: str,
    layer: str | None = None,
    frame: int = 1,
    protect: list[str] | None = None,
    erase_isolated: bool = False,
    min_cluster: int = 1,
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

    A stray with no opaque neighbour at all has no colour to take, so by default it is
    skipped: inventing one would be drawing rather than cleaning. That is the right answer
    inside the art and the wrong one for the commonest dirt an effects pass leaves, which
    is a lone pixel *outside* the art on empty canvas. `erase_isolated` is for that.

    Args:
        protect: Colours never to replace. A one-pixel eye highlight or a specular dot is
            a stray by this definition and is meant to be there, so name its colour. Also
            keeps a cluster `erase_isolated` would otherwise erase, if the colour is in it.
        erase_isolated: Erase a cluster that stands clear of everything else instead of
            skipping it. **Opt-in, because this changes the silhouette**, which is the one
            thing the tool otherwise never does: a one-pixel spark, a floating highlight,
            the dot of an "i" drawn as its own element and a dither sparser than a
            checkerboard are all clusters by this rule and are all meant to be there. What
            it erases is reported as `erased`, apart from `replaced`, for the same reason.
        min_cluster: How many pixels a detached cluster may have and still count as dirt.
            1, the default, is a lone pixel, which is all "isolated" means by itself; 2
            catches the two-pixel speck these passes usually leave, where neither pixel is
            isolated because each has the other for company. Capped low, and the refusal
            names the cap: past a handful of pixels a thing standing clear of the artwork
            is a mark somebody drew. Only means anything with `erase_isolated`, and is
            refused without it rather than ignored.

    Erasure is decided over clusters of **opaque** pixels, connected in all eight
    directions, that have nothing but transparency around them. That is what makes it safe
    at any `min_cluster`: the artwork is connected to itself, so it is never a cluster, and
    only something standing clear of it can go. It is also why the two halves of this tool
    barely meet: a cluster touches no other opaque pixel, so nothing else's replacement can
    be reading a colour off one. Where they do meet, erasing wins, since recolouring dirt
    on its way out is work with no result.

    A pixel whose only same-colour neighbour is **diagonal** is part of a dither pattern,
    not dirt, and is left alone. `assess_sprite` counts isolation orthogonally, which is
    the stricter reading, so a dithered sprite still reports some `isolated_pixels` after
    this has run and that count is the dithering rather than anything to fix.

    This is not Aseprite's own Despeckle, which is a median filter: that one averages
    neighbourhoods, introduces colours that were not in the palette, and on a measured
    test left *more* stray pixels than it found. This changes only the pixels that are
    strays, and only to colours already next to them.

    Returns how many were replaced, so a second call can be skipped when it says 0. With
    `erase_isolated` it also returns `erased` and `erased_clusters`, which are absent
    otherwise: a count of work nobody asked for reads as a finding.
    """
    min_cluster = check_count(
        "min_cluster", min_cluster, MAX_STRAY_CLUSTER, minimum=1,
        remedy="A detached cluster that big is a mark rather than a speck, and erasing it "
               "is a silhouette change this tool should not be making on your behalf: "
               "draw_pixels with 'transparent' is the honest way to remove a shape.",
    )
    if min_cluster > 1 and not erase_isolated:
        # Refused rather than ignored. It has nothing to act on: the replacement rule
        # works a pixel at a time, and the cluster is only ever the unit of erasing.
        raise ValidationFailed(
            f"min_cluster {min_cluster} only means something together with "
            "erase_isolated=True, which is what works in clusters; replacing a stray reads "
            "the colours next to one pixel and has no cluster to size. Pass "
            "erase_isolated=True as well, or leave min_cluster at 1."
        )
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
        "protect": [parse_color(c) for c in (protect or [])],
        "erase_isolated": bool(erase_isolated),
        "min_cluster": min_cluster,
    }
    snippet = """
    local protected = {}
    for _, colour in ipairs(ARG.protect) do
      protected[to_pixel(spr, colour)] = true
    end
    local w, h = img.width, img.height

    -- What to erase is decided first, over the untouched pixels, because the replacement
    -- pass below has to know which pixels are on their way out.
    --
    -- A cluster is a run of OPAQUE pixels joined to each other in any of the eight
    -- directions and to nothing else: every neighbour of the whole run is transparent.
    -- That is what dirt outside the art is, and it is what keeps this off the artwork at
    -- any min_cluster, since the artwork is joined to itself and so is never a cluster.
    -- `erase` is the membership test the stray pass needs; `erase_groups` keeps the same
    -- pixels grouped, because a cluster counts as erased only when all of it went and
    -- that cannot be asked of a flattened map.
    local erase, erase_groups = {}, {}
    if ARG.erase_isolated then
      -- The pixels joined to (x0,y0), or nil once there are more of them than dirt has.
      -- It pops at most min_cluster + 1 pixels before giving up, so a wrong guess costs a
      -- handful of reads and its own tables never hold more than a handful of entries,
      -- whatever the canvas is: the only thing in this pass that grows with the sprite is
      -- the list of pixels actually being erased.
      local function cluster_at(x0, y0)
        local seen, stack, members = { [y0 * w + x0] = true }, { { x0, y0 } }, {}
        while #stack > 0 do
          local p = table.remove(stack)
          members[#members + 1] = p
          if #members > ARG.min_cluster then return nil end
          for dy = -1, 1 do
            for dx = -1, 1 do
              local nx, ny = p[1] + dx, p[2] + dy
              if not (dx == 0 and dy == 0) and img_solid(spr, img, nx, ny) then
                local key = ny * w + nx
                if not seen[key] then
                  seen[key] = true
                  stack[#stack + 1] = { nx, ny }
                end
              end
            end
          end
        end
        return members
      end

      for y = 0, h - 1 do
        for x = 0, w - 1 do
          local key = y * w + x
          if img_solid(spr, img, x, y) and erase[key] == nil then
            -- Counted before any walking. Every opaque neighbour of a pixel in a cluster is
            -- in that same cluster, so a pixel in a cluster of n has at most n - 1 of them,
            -- and a pixel with more cannot be in one at all. That keeps the walk off the
            -- inside of the artwork, where it would otherwise start again at every pixel,
            -- and it costs no record of where it has already been: a full-canvas table of
            -- that is the memory this avoids, on a sprite of up to sixteen million pixels.
            local around = 0
            for dy = -1, 1 do
              for dx = -1, 1 do
                if not (dx == 0 and dy == 0) and img_solid(spr, img, x + dx, y + dy) then
                  around = around + 1
                end
              end
            end
            local members = nil
            if around < ARG.min_cluster then members = cluster_at(x, y) end
            if members ~= nil then
              -- A protected colour anywhere in the cluster keeps all of it: a spark drawn
              -- clear of the art is a cluster by this rule and is meant to be there, and
              -- erasing the pixel beside it would leave half of whatever it was.
              local keep = false
              for _, p in ipairs(members) do
                if protected[img:getPixel(p[1], p[2])] then keep = true end
              end
              if not keep then
                erase_groups[#erase_groups + 1] = members
                for _, p in ipairs(members) do
                  erase[p[2] * w + p[1]] = p
                end
              end
            end
          end
        end
      end
    end

    -- Which pixels are strays, settled before deciding what any of them becomes.
    --
    -- A stray may only take a colour from a pixel that is staying, and that needs knowing
    -- which pixels those are. Without it, a two-pixel speck of two colours had each pixel
    -- take the other's: the pass reported two replacements, cleaned nothing, and a second
    -- pass traded them back, so the tool was not idempotent on its own output (#177).
    -- Three mutually adjacent strays shuffled the same way.
    --
    -- A pixel being erased is not a stray to repaint either. It can only ever be one of
    -- its own cluster's members, because a cluster has no opaque neighbour outside itself,
    -- so leaving these out cannot change what any surviving pixel is replaced with.
    local stray = {}
    for y = 0, h - 1 do
      for x = 0, w - 1 do
        local here = img:getPixel(x, y)
        if img_solid(spr, img, x, y) and not protected[here] and erase[y * w + x] == nil then
          local alone = true
          for dy = -1, 1 do
            for dx = -1, 1 do
              if not (dx == 0 and dy == 0) then
                local nx, ny = x + dx, y + dy
                if nx >= 0 and ny >= 0 and nx < w and ny < h
                   and img:getPixel(nx, ny) == here then
                  alone = false
                end
              end
            end
          end
          if alone then stray[y * w + x] = true end
        end
      end
    end

    -- Read first, write after: a stray replaced mid-pass would become a neighbour that
    -- rescues the next one, and the result would depend on scan order.
    local replacements = {}
    for y = 0, h - 1 do
      for x = 0, w - 1 do
        if stray[y * w + x] then
          local here = img:getPixel(x, y)
          local tally, best, best_n = {}, nil, 0
          for dy = -1, 1 do
            for dx = -1, 1 do
              if not (dx == 0 and dy == 0) then
                local nx, ny = x + dx, y + dy
                if nx >= 0 and ny >= 0 and nx < w and ny < h then
                  local other = img:getPixel(nx, ny)
                  -- `other ~= here` is already guaranteed for a stray, and is kept as the
                  -- statement of that: a pixel with a neighbour of its own colour is not
                  -- one.
                  if other ~= here and img_solid(spr, img, nx, ny)
                     and not stray[ny * w + nx] then
                    local n = (tally[other] or 0) + 1
                    tally[other] = n
                    if n > best_n then best, best_n = other, n end
                  end
                end
              end
            end
          end
          -- No staying neighbour means nothing to take, which is the same situation as a
          -- stray on empty canvas: left alone here, and erased by `erase_isolated`.
          if best ~= nil then
            replacements[#replacements + 1] = { x = x, y = y, px = best }
          end
        end
      end
    end

    -- Both counts are taken from what landed rather than from what was offered: an
    -- active selection refuses a write silently, so a tally kept beside the loop claims
    -- speckle was cleaned in pixels this call was never allowed to touch.
    local mark_r = landed()
    for _, item in ipairs(replacements) do
      img_set(img, item.x, item.y, item.px)
    end
    local replaced = landed() - mark_r

    -- rgba_to_px with no alpha is the transparent pixel in every colour mode, including
    -- the sprite's transparent index on indexed art, so this erases rather than writing
    -- a black that happens to look like a hole in RGB.
    local blank = rgba_to_px(spr, 0, 0, 0, 0)
    local erased, clusters = 0, 0
    for _, members in ipairs(erase_groups) do
      local before = landed()
      for _, p in ipairs(members) do
        img_set(img, p[1], p[2], blank)
      end
      local gone = landed() - before
      erased = erased + gone
      -- Only a cluster that went entirely. Half a speck left behind is not a speck
      -- removed, and a selection edge can cut one in two.
      if gone == #members then clusters = clusters + 1 end
    end

    _extra = { replaced = replaced }
    if ARG.erase_isolated then
      _extra.erased = erased
      _extra.erased_clusters = clusters
    end
    """
    return run_lua(_OPEN + LANDED_LUA + snippet + _CLOSE, args)


# Reads the silhouette and nothing else. One run-length row per pixel row, alternating
# "not drawn" then "drawn", always starting with "not drawn", so a row that begins with
# art opens with a zero. A 64x64 silhouette comes back as a few hundred integers rather
# than 4,096 colour strings, which is what makes reading the whole frame affordable.
_SILHOUETTE_LUA = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
if layer.isGroup then
  error("Cannot read a silhouette off a group layer: " .. layer.name ..
        ". Name one of the layers inside it.", 0)
end
local framenum = require_frame(spr, ARG.frame, "frame")
if spr.width * spr.height > ARG.max_pixels then
  error("This frame is " .. spr.width .. "x" .. spr.height .. " (" ..
        (spr.width * spr.height) .. " px); normalize_edge_runs reads at most " ..
        ARG.max_pixels .. ". Normalise a smaller sprite, or crop a copy of this one.", 0)
end
local img = get_draw_image(spr, layer, framenum)

local rows, drawn = {}, 0
for yy = 0, spr.height - 1 do
  local row, n, state, length = {}, 0, false, 0
  for xx = 0, spr.width - 1 do
    local _, _, _, a = px_to_rgba(spr, img:getPixel(xx, yy))
    local solid = a > 0
    if solid then drawn = drawn + 1 end
    if solid == state then
      length = length + 1
    else
      n = n + 1; row[n] = length
      state, length = solid, 1
    end
  end
  n = n + 1; row[n] = length
  rows[yy + 1] = row
end

RESULT = { ok = true, filename = spr.filename, layer = layer.name, frame = framenum,
           width = spr.width, height = spr.height, rows = rows, drawn_pixels = drawn }
"""


def _silhouette(measured: dict) -> list[list[bool]]:
    """The run-length rows back as rows of booleans, which is what `core.edges` reads."""
    width = measured["width"]
    mask = []
    for row in measured["rows"]:
        cells: list[bool] = []
        state = False
        for length in row:
            cells.extend([state] * int(length))
            state = not state
        # The encoder emits the final run even when it is empty, and a row of pure
        # transparency is a single run, so the lengths always sum to the width. Checked
        # rather than trusted, because a short row here would silently shift every pixel
        # after it and the plan would be made against a different shape than the sprite.
        if len(cells) != width:
            raise ValidationFailed(
                f"the silhouette read back as {len(cells)} cells on a row of a "
                f"{width}-wide sprite, so the encoding and the canvas disagree. Nothing "
                "was written."
            )
        mask.append(cells)
    return mask


@mcp.tool()
def normalize_edge_runs(
    filename: str,
    min_span: int = edges.MIN_SPAN,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Even out the run lengths along a silhouette's diagonals, conservatively.

    A hand-drawn diagonal is built from runs of consistent length: a 1:2 slope is two
    pixels, two pixels, two pixels, held steady, and broken only on purpose. A generated
    one wanders, runs of 3, 1, 2, 1, 4 where a person would have drawn 2, 2, 2, 2, and
    that wander is the most recognisable tell in generated pixel art, ahead of both colour
    and shading. `assess_sprite` already counts it as `jaggy_corners`, which on a boundary
    stepping one way is exactly the number of steps; this is what to do about the count.

    What it changes is narrow on purpose: a run of **exactly one**, with a run of at least
    two on either side, stepping the same way on both sides, by exactly one pixel each
    time. That run is merged into whichever neighbour lies further out, which paints one
    pixel in the colour of the pixel beside it. Everything else is left alone and counted
    under `kept`, so a pass that declines to touch something says which rule stopped it:

    * `diagonal`: the run sits next to another one-pixel run, so this is a 1:1 diagonal,
      already the most even edge there is;
    * `feature`: the run is further out, or further in, than both its neighbours. That is a
      spike or a notch, a local extremum, and somebody drew it: a horn, a finger, a chip
      in the stone;
    * `step`: the step either side is more than one pixel, so this is a change of slope;
    * `thin`: the edge belongs to something thinner than `min_span`, where adding a pixel
      reshapes the feature instead of smoothing its edge;
    * `no_gain`: the merge would not lower the jagged-corner count, measured over the four
      2x2 windows the one new pixel can change.

    Because it only ever adds a pixel, and only ever a value the boundary already held
    somewhere else, **the silhouette's extent cannot move and nothing can be eaten**. Both
    are checked rather than promised: a plan whose bounding box differs from the
    original's is refused and nothing is written.

    Args:
        min_span: How thick the mass behind an edge has to be before its edge is treated
            as an edge, measured as the unbroken run of drawn pixels inward from the
            boundary. The default of 3 is the smallest value at which the added pixel is a
            minority of what it joins. Raise it to protect thin limbs; 2 is the floor.
        layer: The layer whose silhouette is read and written (default: top layer).
        frame: Target frame, 1-based.

    Returns `jaggy_corners_before` and `jaggy_corners_after` every call, so the claim is in
    the result rather than in this docstring, along with `runs_merged` and `by_side`. A
    pass with nothing to merge is **refused**, and the refusal carries the tally above: a
    silhouette this cannot improve is the normal case for art that was drawn by hand.

    Two Aseprite launches, one to read the silhouette and one to paint: the decision about
    which runs are stumbles is arithmetic over the whole shape, and the shape is only
    knowable with the file open. The read ignores any active selection, because the
    geometry is a fact about the whole silhouette, while the write honours it like every
    other drawing tool. When the mask refuses some of the planned pixels, the after figure
    is withheld rather than reported against a shape that was not painted.
    """
    src = resolve_path(filename)
    measured = run_lua(_SILHOUETTE_LUA, {
        "src": lua_path(src), "layer": layer, "frame": int(frame),
        "max_pixels": MAX_ASSESS_PIXELS,
    })
    if not measured.get("drawn_pixels"):
        raise ValidationFailed(
            f"layer {measured['layer']!r} has nothing drawn on frame {measured['frame']}, "
            "so there is no silhouette to even out."
        )
    planned = edges.plan(_silhouette(measured), min_span=int(min_span))

    result = _draw(
        {
            "src": lua_path(src), "layer": layer, "frame": int(frame), "color": None,
            "pixels": planned["add"],
        },
        """
        for _, p in ipairs(ARG.pixels) do
          -- The colour of the neighbour this run is being merged into, read off the image
          -- rather than passed in. Nothing new can appear in the sprite, so a drawing on
          -- a ramp stays on it without this tool having to know what a ramp is.
          img_set(img, p.x, p.y, img:getPixel(p.from_x, p.from_y))
        end
        """,
    )
    result["runs_examined"] = planned["runs_examined"]
    result["runs_merged"] = planned["runs_merged"]
    result["by_side"] = planned["by_side"]
    result["jaggy_corners_before"] = planned["jaggy_before"]
    result["bbox"] = planned["bbox"]
    if planned["kept"]:
        result["kept"] = planned["kept"]
    written = result.get("pixels_written")
    if written == len(planned["add"]):
        result["jaggy_corners_after"] = planned["jaggy_after"]
    else:
        # The plan was scored against a silhouette with every merge in it. With some of
        # them masked out the shape on disk is a different one, and reporting the planned
        # figure against it would be a measurement of something that was not painted.
        note = (
            f"{written} of the {len(planned['add'])} planned pixels were written, so the "
            f"silhouette on disk is not the one the plan was scored against: "
            f"jaggy_corners_after is withheld rather than reported as "
            f"{planned['jaggy_after']}. deselect and run this again, or call "
            "assess_sprite to measure what is actually there."
        )
        existing = result.get("warnings")
        result["warnings"] = [*existing, note] if isinstance(existing, list) else [note]
    return result
