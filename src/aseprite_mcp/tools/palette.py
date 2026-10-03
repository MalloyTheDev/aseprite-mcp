"""Palette management: read, replace, edit individual colours, load, transparency."""

from __future__ import annotations

from ..app import mcp
from ..core import indexed, quantization, ramps
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_ASSESS_PIXELS,
    MAX_COLOR_LIST_LENGTH,
    check_count,
    check_list_length,
)
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path

# What the pure diagnosis in `core.indexed.palette_readings` needs, measured where the
# palette actually is. Appended to the body of every tool that writes a palette, because
# an entry that cannot be drawn is created by *writing* one, and the caller who wrote it
# is the one who can still do something about it.
#
# Only the four numbers, not the colours: `get_palette` already returns those, and a
# tool that edits one entry should not answer with 256.
_PALETTE_STATE_LUA = """
do
  local pal = spr.palettes[1]
  local ti = spr.transparentColor
  local shadowed = nil
  if ti >= 0 and ti < #pal then shadowed = color_hex(pal:getColor(ti)) end
  local drawable = 0
  for i = 0, #pal - 1 do
    if i ~= ti and pal:getColor(i).alpha > 0 then drawable = drawable + 1 end
  end
  RESULT.color_mode = colormode_name(spr.colorMode)
  RESULT.palette = {
    size = #pal,
    transparent_index = ti,
    at_transparent_index = shadowed,
    drawable = drawable,
  }
end
"""


def _with_palette_readings(result: dict) -> dict:
    """Attach `warnings` when the palette now holds something it cannot draw.

    The judgement is pure and lives in `core.indexed`; this only hands it the
    measurement and drops the result in. Absent rather than empty when there is nothing
    to say, so a `warnings` key always means there is.
    """
    notes = indexed.palette_readings(result.get("palette") or {},
                                     result.get("color_mode") or "")
    if notes:
        result["warnings"] = notes
    return result


@mcp.tool()
def get_palette(filename: str) -> dict:
    """Return the sprite's palette as a list of "#RRGGBBAA" colours."""
    body = """
    local spr = open_sprite(ARG.src)
    local pal = spr.palettes[1]
    local cols = {}
    for i = 0, #pal - 1 do cols[i + 1] = color_hex(pal:getColor(i)) end
    RESULT = { size = #pal, colors = cols }
    """
    return run_lua(body, {"src": lua_path(resolve_path(filename))})


@mcp.tool()
def set_palette(filename: str, colors: list[str]) -> dict:
    """Replace the entire palette with the given list of colours.

    colors: list of colour strings, e.g. ["#000000", "#ffffff", "255,0,0"].
    """
    if not colors:
        raise ValidationFailed("colors must be a non-empty list.")
    check_list_length("colors", colors, MAX_COLOR_LIST_LENGTH)
    parsed = [parse_color(c) for c in colors]
    args = {"src": lua_path(resolve_path(filename)), "colors": parsed}
    body = """
    local spr = open_sprite(ARG.src)
    local pal = Palette(#ARG.colors)
    for i, c in ipairs(ARG.colors) do pal:setColor(i - 1, mkcolor(c)) end
    spr:setPalette(pal)
    save_sprite(spr)
    RESULT = { ok = true, size = #pal }
    """ + _PALETTE_STATE_LUA
    return _with_palette_readings(run_lua(body, args))


@mcp.tool()
def set_palette_color(filename: str, index: int, color: str) -> dict:
    """Set a single palette entry by index (0-based). Grows the palette if needed.

    The index is bounded by the palette ceiling: the Lua below resizes the palette to
    `index + 1`, so the index *is* a palette size.
    """
    check_count(
        "index", index, MAX_COLOR_LIST_LENGTH - 1, minimum=0,
        remedy=f"A palette holds at most {MAX_COLOR_LIST_LENGTH} colours.",
    )
    args = {
        "src": lua_path(resolve_path(filename)),
        "index": int(index),
        "color": parse_color(color),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local pal = spr.palettes[1]
    if ARG.index >= #pal then pal:resize(ARG.index + 1) end
    pal:setColor(ARG.index, mkcolor(ARG.color))
    save_sprite(spr)
    RESULT = { ok = true, index = ARG.index, size = #pal }
    """ + _PALETTE_STATE_LUA
    return _with_palette_readings(run_lua(body, args))


@mcp.tool()
def add_palette_color(filename: str, color: str) -> dict:
    """Append a colour to the end of the palette."""
    args = {"src": lua_path(resolve_path(filename)), "color": parse_color(color)}
    body = """
    local spr = open_sprite(ARG.src)
    local pal = spr.palettes[1]
    local n = #pal
    pal:resize(n + 1)
    pal:setColor(n, mkcolor(ARG.color))
    save_sprite(spr)
    RESULT = { ok = true, index = n, size = #pal }
    """ + _PALETTE_STATE_LUA
    return _with_palette_readings(run_lua(body, args))


@mcp.tool()
def resize_palette(filename: str, size: int) -> dict:
    """Resize the palette to `size` entries (new entries are black)."""
    size = max(1, int(size))
    check_count(
        "size", size, MAX_COLOR_LIST_LENGTH, minimum=1,
        remedy=f"A palette holds at most {MAX_COLOR_LIST_LENGTH} colours.",
    )
    args = {"src": lua_path(resolve_path(filename)), "size": size}
    body = """
    local spr = open_sprite(ARG.src)
    spr.palettes[1]:resize(ARG.size)
    save_sprite(spr)
    RESULT = { ok = true, size = #spr.palettes[1] }
    """ + _PALETTE_STATE_LUA
    return _with_palette_readings(run_lua(body, args))


@mcp.tool()
def load_palette(filename: str, palette_file: str) -> dict:
    """Load a palette from a file (.gpl, .pal, .aseprite, .png, ...) and apply it."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "palfile": lua_path(resolve_path(palette_file)),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local pal = Palette{ fromFile = ARG.palfile }
    if pal == nil then error("Could not load palette from " .. ARG.palfile) end
    spr:setPalette(pal)
    save_sprite(spr)
    RESULT = { ok = true, size = #pal }
    """ + _PALETTE_STATE_LUA
    return _with_palette_readings(run_lua(body, args))


@mcp.tool()
def extract_palette(
    filename: str,
    from_image: str | None = None,
    set_as_palette: bool = True,
    include_alpha: bool = False,
    max_colors: int = 256,
) -> dict:
    """Extract the unique colours used in a sprite (or another image).

    Args:
        from_image: Optional image/sprite to scan instead of `filename`.
        set_as_palette: Apply the extracted colours as `filename`'s palette.
        include_alpha: Treat differing alpha as distinct colours (default off).
        max_colors: Error out if more unique colours than this are found.

    Returns the list of "#RRGGBBAA" colours found.
    """
    args = {
        "target": lua_path(resolve_path(filename)),
        "from_image": lua_path(resolve_path(from_image)) if from_image else None,
        "set_as_palette": bool(set_as_palette),
        "include_alpha": bool(include_alpha),
        "max_colors": max(1, int(max_colors)),
    }
    # Scanning may report more colours than a palette can hold (that is a useful
    # answer), but the moment the result is written back as a palette it is a palette
    # size and takes the palette ceiling like every other route to one.
    if args["set_as_palette"]:
        check_count(
            "max_colors", args["max_colors"], MAX_COLOR_LIST_LENGTH, minimum=1,
            remedy=f"A palette holds at most {MAX_COLOR_LIST_LENGTH} colours; pass "
                   "set_as_palette=false to just count the colours in an image.",
        )
    body = """
    local scanpath = ARG.from_image or ARG.target
    local spr = open_sprite(scanpath)
    local seen, colors = {}, {}
    for f = 1, #spr.frames do
      local flat = Image(spr.spec); flat:clear(); flat:drawSprite(spr, f)
      for y = 0, flat.height - 1 do
        for x = 0, flat.width - 1 do
          local r, g, b, a = px_to_rgba(spr, flat:getPixel(x, y))
          if a > 0 or ARG.include_alpha then
            local key = ARG.include_alpha and string.format("%d_%d_%d_%d", r, g, b, a)
                                           or string.format("%d_%d_%d", r, g, b)
            if seen[key] == nil then
              seen[key] = true
              colors[#colors + 1] = { r = r, g = g, b = b, a = ARG.include_alpha and a or 255 }
              if #colors > ARG.max_colors then
                error("Found more than " .. ARG.max_colors .. " unique colours; raise max_colors.")
              end
            end
          end
        end
      end
    end
    local hexes = {}
    for i, c in ipairs(colors) do hexes[i] = color_hex(mkcolor(c)) end
    if ARG.set_as_palette and #colors > 0 then
      local target = spr
      if ARG.from_image ~= nil then target = open_sprite(ARG.target) end
      local pal = Palette(#colors)
      for i, c in ipairs(colors) do pal:setColor(i - 1, mkcolor(c)) end
      target:setPalette(pal)
      save_sprite(target)
    end
    RESULT = { count = #colors, colors = hexes }
    """
    return run_lua(body, args)


@mcp.tool()
def quantize_palette(filename: str, max_colors: int = 256) -> dict:
    """Derive a palette from the art, reduced to at most `max_colors` entries.

    The step between a picture and pixel art. `extract_palette` lists the colours a
    sprite already uses but cannot reduce them to a budget, and `set_color_mode` maps art
    onto a palette but cannot decide what the palette should be. This asks the editor's
    own quantizer for the best `max_colors` colours for this art and installs them, which
    is what to do before `set_color_mode("indexed", palette_source="keep")`.

    One entry is spent on transparency, at index 0, which is what an indexed sprite needs
    there: an opaque colour at the transparent index is in the palette and can never be
    drawn.

    **`max_colors` is a ceiling and nothing more, and it has a cliff in it.** The
    reduction merges whole levels of colour space at a time, so it can stop well short of
    what was asked for: measured, four distinct colours with `max_colors=4` came back as
    one mid-grey that was the average of all four, while `max_colors=5` on the same art
    returned all four exactly. The result therefore reports how many colours the art has,
    how many of them the new palette holds exactly, and how many entries can draw at all,
    and says in `warnings` when the palette cannot hold the art. Raising `max_colors` by
    a little is usually what fixes it.

    Refuses an indexed sprite. There a pixel is an offset into the palette rather than a
    colour, so replacing the palette changes what every pixel means without touching a
    pixel; the error says how to do it in that case.

    Past a million pixels the art is not scanned, the palette is still derived, and the
    result says the comparison was skipped rather than implying the art is blank.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "max_colors": quantization.check_max_colors(max_colors),
        "scan_cap": quantization.MAX_SCANNED_COLORS,
        # Paid per pixel through getPixel and px_to_rgba, which is the slow decode rather
        # than the byte-stride count `MAX_VERIFY_PIXELS` is sized for, so the smaller cap
        # is the right one: a million pixels is about six tenths of a second.
        "max_scan_pixels": MAX_ASSESS_PIXELS,
    }
    body = """
    local spr = open_sprite(ARG.src)
    if spr.colorMode == ColorMode.INDEXED then
      error("this sprite is indexed, so its pixels are offsets into the palette rather " ..
            "than colours: replacing the palette would change what every pixel means " ..
            "without touching a pixel, and the art on disk is left alone instead. " ..
            "Measured on an indexed sprite, quantizing reordered the palette and the " ..
            "art came back showing different colours, and a reduction left pixels " ..
            "pointing past the end of the palette. To reduce an indexed sprite's " ..
            "palette: set_color_mode(rgb), quantize_palette, then " ..
            "set_color_mode(indexed, palette_source='keep'), which remaps the art.", 0)
    end

    -- The art's own colours, counted before the palette is replaced. Only the count and
    -- the exact matches are reported: the palette is the tool's output and the art's
    -- colours are the question asked of it, not a second palette to hand back.
    local scan_pixels = spr.width * spr.height * #spr.frames
    local scanned = scan_pixels <= ARG.max_scan_pixels
    local seen, art, capped = {}, 0, false
    if scanned then
      for f = 1, #spr.frames do
        local flat = Image(spr.spec); flat:clear(); flat:drawSprite(spr, f)
        for y = 0, flat.height - 1 do
          for x = 0, flat.width - 1 do
            local r, g, b, a = px_to_rgba(spr, flat:getPixel(x, y))
            if a > 0 then
              local key = string.format("%d_%d_%d_%d", r, g, b, a)
              if seen[key] == nil then
                if art < ARG.scan_cap then
                  seen[key] = true
                  art = art + 1
                else
                  capped = true
                end
              end
            end
          end
        end
      end
    end

    app.command.ColorQuantization{ ui = false, maxColors = ARG.max_colors }

    local pal = spr.palettes[1]
    local have = {}
    for i = 0, #pal - 1 do
      local c = pal:getColor(i)
      have[string.format("%d_%d_%d_%d", c.red, c.green, c.blue, c.alpha)] = true
    end
    local exact = 0
    for key in pairs(seen) do if have[key] then exact = exact + 1 end end
    local colors = {}
    for i = 0, #pal - 1 do colors[i + 1] = color_hex(pal:getColor(i)) end

    save_sprite(spr)
    RESULT = { ok = true, requested = ARG.max_colors, size = #pal, colors = colors,
               art_scanned = scanned, art_colors = art, art_colors_exact = exact,
               art_colors_capped = capped }
    if not scanned then
      RESULT.unscanned_reason = string.format(
        "%d pixels across %d frame(s) is past the scan cap of %d", scan_pixels,
        #spr.frames, ARG.max_scan_pixels)
    end
    """ + _PALETTE_STATE_LUA
    result = run_lua(body, args)
    # The judgement is pure and lives in `core.quantization`; this only hands it the
    # measurement. `indexed.palette_readings` is deliberately not also applied: it can
    # only speak about indexed sprites, and this tool refuses those.
    notes = quantization.quantization_readings({
        "requested": result.get("requested"),
        "size": result.get("size"),
        "drawable": (result.get("palette") or {}).get("drawable"),
        "art_scanned": result.get("art_scanned", True),
        "art_colors": result.get("art_colors"),
        "art_colors_exact": result.get("art_colors_exact"),
        "art_colors_capped": result.get("art_colors_capped"),
    })
    if notes:
        result["warnings"] = notes
    return result


@mcp.tool()
def sort_palette(filename: str, by: str = "luminance", reverse: bool = False) -> dict:
    """Sort the palette by "hue", "luminance" (default), "saturation", or "value".

    For indexed sprites the pixel indices are remapped so the image looks identical.
    """
    if by not in ("hue", "luminance", "saturation", "value"):
        raise ValidationFailed('by must be one of: hue, luminance, saturation, value')
    args = {"src": lua_path(resolve_path(filename)), "by": by, "reverse": bool(reverse)}
    body = """
    local spr = open_sprite(ARG.src)
    local pal = spr.palettes[1]
    local n = #pal
    local entries = {}
    for i = 0, n - 1 do entries[#entries + 1] = { idx = i, c = pal:getColor(i) } end
    local function keyof(c)
      local r, g, b = c.red / 255, c.green / 255, c.blue / 255
      local mx, mn = math.max(r, g, b), math.min(r, g, b)
      local L = (mx + mn) / 2
      local d = mx - mn
      local H, S = 0, 0
      if d > 0 then
        S = (L > 0.5) and (d / (2 - mx - mn)) or (d / (mx + mn))
        if mx == r then H = (g - b) / d + (g < b and 6 or 0)
        elseif mx == g then H = (b - r) / d + 2 else H = (r - g) / d + 4 end
        H = H / 6
      end
      if ARG.by == "hue" then return H * 1000 + L
      elseif ARG.by == "saturation" then return S
      elseif ARG.by == "value" then return mx
      else return 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue end
    end
    table.sort(entries, function(a, b)
      local ka, kb = keyof(a.c), keyof(b.c)
      if ARG.reverse then return ka > kb else return ka < kb end
    end)
    local newpal = Palette(n)
    local remap = {}
    for newi, e in ipairs(entries) do
      newpal:setColor(newi - 1, e.c)
      remap[e.idx] = newi - 1
    end
    spr:setPalette(newpal)
    if spr.colorMode == ColorMode.INDEXED then
      -- One representative cel per *distinct image*, collected before anything is
      -- written. Linked cels share a single CelData, so assigning `cel.image` writes
      -- through to every frame in the group; iterating cels therefore remapped a shared
      -- image once per linked frame, and the result was silent corruption that scaled
      -- with the group size. A four frame hold came back remapped four times: index 1
      -- became 2, then 0, then 3, then 1 again, so art drawn in the darkest colour of a
      -- four colour palette came back mid grey while the tool reported success and
      -- promised the image would look identical.
      local targets, seen = {}, {}
      for _, cel in ipairs(spr.cels) do
        -- Skip tilemap cels: their pixels are tile indices, not palette indices.
        if not cel.layer.isTilemap and not seen[cel.image.id] then
          seen[cel.image.id] = true
          targets[#targets + 1] = cel
        end
      end
      -- `im:drawPixel` below, not `img_set`. This is a reindex, not a paint: it rewrites
      -- every pixel's palette index after the palette was reordered, so the art looks
      -- unchanged. Clipped to a selection, the unselected pixels would keep pointing at
      -- the old indices and the sprite would visibly corrupt.
      for _, cel in ipairs(targets) do
        local im = Image(cel.image)
        for y = 0, im.height - 1 do
          for x = 0, im.width - 1 do
            local v = im:getPixel(x, y)
            if remap[v] ~= nil then im:drawPixel(x, y, remap[v]) end
          end
        end
        -- Deliberately assigned through the shared record rather than broken out with
        -- newCel: every frame in the group shows the same drawing and all of them need
        -- the same remap, so this is the one case where writing through a link is the
        -- correct thing to do. The links are preserved.
        cel.image = im
      end
      if remap[spr.transparentColor] ~= nil then spr.transparentColor = remap[spr.transparentColor] end
    end
    save_sprite(spr)
    RESULT = { ok = true, size = n, by = ARG.by }
    """ + _PALETTE_STATE_LUA
    return _with_palette_readings(run_lua(body, args))


def _unit_rgb(color: str) -> tuple[float, float, float]:
    """A colour spec as 0..1 RGB, for handing to colorsys."""
    c = parse_color(color)
    return c["r"] / 255, c["g"] / 255, c["b"] / 255


def _lerp_hue(start: float, end: float, k: float) -> float:
    """Interpolate hue the short way round the wheel.

    Naive interpolation from 350 degrees to 10 would travel backwards through the
    whole spectrum instead of the 20 degrees that were meant.
    """
    delta = (end - start + 0.5) % 1.0 - 0.5
    return (start + delta * k) % 1.0


@mcp.tool()
def generate_ramp(
    base_color: str,
    steps: int = 5,
    hue_shift: float = 0.0,
    saturation_shift: float = 0.0,
    light_range: float = 0.6,
    filename: str | None = None,
    apply: str = "none",
    shadow_hue: str | None = None,
    light_hue: str | None = None,
    sat_curve: str = "linear",
    easing: str = "linear",
) -> dict:
    """Generate a shading ramp from a base colour (dark -> light).

    Produces `steps` colours by varying lightness across `light_range`, optionally
    rotating hue by `hue_shift` total degrees across the ramp (classic pixel-art
    hue shifting: cool shadows / warm highlights) and scaling saturation by
    `saturation_shift` percent across the ramp.

    Args:
        filename: If set with apply, write the ramp into that sprite's palette.
        apply: "none" (just return), "append" (add to palette), or "replace".

    Returns the ramp as a list of "#RRGGBB" colours (darkest first), with `distinct`, how
    many of them are different from each other.

    **`distinct` is not always `steps`.** Lightness is clamped at both ends, so a base
    already near white or near black spends its outermost steps on the same colour: nine
    steps in, eight colours out. The ramp is still returned, because clamping is the honest
    result of the inputs and a caller may not care, but `warnings` then names which end
    collapsed and the nearest `light_range` that would not.

    It is worth caring about at least once. `specular_highlight` needs the ramp's top step
    to be brighter than what `shade_region_by_light` spread across the lit side, so a ramp
    whose top two entries are both `#ffffff` makes that call refuse, with a message about
    the shading pass. The cause is two calls earlier, in this one, which used to report
    success either way.
    """
    import colorsys

    steps = max(2, int(steps))
    # A ramp longer than a palette is not a ramp, and every step is materialized in
    # Python before anything is launched, so this one is spent locally either way.
    check_count(
        "steps", steps, MAX_COLOR_LIST_LENGTH, minimum=2,
        remedy=f"A ramp of more than {MAX_COLOR_LIST_LENGTH} shades exceeds a palette.",
    )
    base = parse_color(base_color)
    r, g, b = base["r"] / 255, base["g"] / 255, base["b"] / 255
    h, lum, sat = colorsys.rgb_to_hls(r, g, b)
    if sat_curve not in ("linear", "peak"):
        raise ValidationFailed('sat_curve must be "linear" or "peak".')
    if easing not in ("linear", "perceptual"):
        raise ValidationFailed('easing must be "linear" or "perceptual".')

    shadow_h = colorsys.rgb_to_hls(*_unit_rgb(shadow_hue))[0] if shadow_hue else None
    light_h = colorsys.rgb_to_hls(*_unit_rgb(light_hue))[0] if light_hue else None

    # Wrapped in a function of `span` rather than reading `light_range` directly, so the
    # clipping check below can ask what this same arithmetic would have produced at another
    # range. Nothing inside it changed when it was wrapped, which matters: the committed
    # showcase art is reproduced byte for byte from these numbers.
    def build(span: float) -> list[str]:
        colors = []
        for i in range(steps):
            u = i / (steps - 1)  # 0 = darkest .. 1 = lightest
            t = u - 0.5  # -0.5 .. 0.5, the original parameterisation

            # Lightness. "perceptual" bunches the dark steps, because equal steps in HLS
            # lightness are not equal steps to the eye and a ramp built that way has a
            # muddy shadow end.
            lt = (u**1.5) - 0.5 if easing == "perceptual" else t
            L = min(1.0, max(0.0, lum + lt * span))

            # Hue. Explicit targets express the rule as artists state it, "shadows go
            # toward blue, highlights toward yellow", which a single symmetric rotation
            # about the base cannot: it forces the two ends to be equal and opposite.
            if shadow_h is not None or light_h is not None:
                if u <= 0.5:
                    target, k = (shadow_h if shadow_h is not None else h), 1 - (u * 2)
                else:
                    target, k = (light_h if light_h is not None else h), (u - 0.5) * 2
                H = _lerp_hue(h, target, k)
            else:
                H = (h + (t * hue_shift / 360.0)) % 1.0

            # Saturation. A ramp's chroma peaks in the midtone and falls at both ends:
            # highlights desaturate toward the light, deep shadows toward ambient. The
            # monotonic form cannot express that, so the brightest step came out the most
            # saturated, which is the opposite of how a hand-built ramp reads.
            if sat_curve == "peak":
                falloff = (2 * u - 1) ** 2  # 0 at the midtone, 1 at either end
                S = sat * (1 - (saturation_shift / 100.0) * falloff)
            else:
                S = sat * (1 + t * saturation_shift / 100.0)
            S = min(1.0, max(0.0, S))

            rr, gg, bb = colorsys.hls_to_rgb(H, L, S)
            colors.append(
                f"#{round(rr * 255):02x}{round(gg * 255):02x}{round(bb * 255):02x}")
        return colors

    colors = build(light_range)
    distinct = len(set(colors))
    result = {"steps": steps, "colors": colors, "distinct": distinct}
    # Only when it happened. A ramp that came back whole should not grow a warning saying
    # so, for the same reason the pixel counters do not grow a "0".
    if distinct < steps:
        result["warnings"] = [
            ramps.clip_warning(
                colors, steps, ramps.nearest_unclipped(build, steps, light_range)
            )
        ]
    applied = _apply_palette(filename, colors, apply)
    if applied is not None:
        result["applied"] = applied
    return result


def _apply_palette(filename: str | None, colors: list[str], apply: str) -> dict | None:
    """Write a generated ramp into a sprite's palette, or do nothing.

    Shared by the ramp builders: they differ in how they arrive at the colours and not at
    all in what "apply" means.
    """
    if apply == "none":
        return None
    if apply not in ("append", "replace"):
        raise ValidationFailed('apply must be "none", "append", or "replace"')
    if not filename:
        raise ValidationFailed("filename is required when apply is not 'none'.")
    args = {
        "src": lua_path(resolve_path(filename)),
        "colors": [parse_color(c) for c in colors],
        "mode": apply,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local pal = spr.palettes[1]
    if ARG.mode == "replace" then
      local np = Palette(#ARG.colors)
      for i, c in ipairs(ARG.colors) do np:setColor(i - 1, mkcolor(c)) end
      spr:setPalette(np)
    else
      local n = #pal
      pal:resize(n + #ARG.colors)
      for i, c in ipairs(ARG.colors) do pal:setColor(n + i - 1, mkcolor(c)) end
    end
    save_sprite(spr)
    RESULT = { ok = true, size = #spr.palettes[1] }
    """
    return run_lua(body, args)


@mcp.tool()
def set_transparent_color(filename: str, index: int) -> dict:
    """Set which palette index is treated as transparent (indexed sprites only)."""
    args = {"src": lua_path(resolve_path(filename)), "index": int(index)}
    body = """
    local spr = open_sprite(ARG.src)
    if spr.colorMode ~= ColorMode.INDEXED then
      error("transparentColor only applies to indexed sprites.")
    end
    spr.transparentColor = ARG.index
    save_sprite(spr)
    RESULT = { ok = true, transparentColor = spr.transparentColor }
    """
    return run_lua(body, args)


@mcp.tool()
def ramp_between(
    shadow_color: str,
    light_color: str,
    steps: int = 5,
    easing: str = "perceptual",
    filename: str | None = None,
    apply: str = "none",
) -> dict:
    """Build a ramp from its two ends, which is how a ramp is usually decided.

    `generate_ramp` grows a ramp outward from one base colour, so reaching a particular
    shadow and a particular highlight means guessing at `hue_shift` until the ends land
    near what was wanted. This takes the ends directly: pick the cool shadow and the warm
    highlight, and the middle is interpolated between them.

    Both ends come back **exactly** as given. They were chosen, and a ramp whose endpoints
    are approximations of the caller's own colours is not the ramp that was asked for.

    Args:
        easing: "perceptual" (the default) walks the straight line between the ends in
            Oklab, so the middle steps are evenly spaced to the eye and the ramp keeps its
            hue. "linear" is the naive sRGB blend, which darkens and greys the middle.
        filename, apply: As `generate_ramp`. "append" or "replace" writes the ramp into
            that sprite's palette.

    Neither mode rotates hue. Interpolating hue between distant colours is what turns a
    blue-to-cream ramp magenta in the middle: at that distance both ways round the wheel
    are equally short, and neither is the blend anybody wanted.
    """
    parsed_shadow = parse_color(shadow_color)
    parsed_light = parse_color(light_color)
    steps = int(steps)
    check_count(
        "steps", steps, MAX_COLOR_LIST_LENGTH, minimum=2,
        remedy=f"A ramp of more than {MAX_COLOR_LIST_LENGTH} shades exceeds a palette.",
    )
    if easing not in ("linear", "perceptual"):
        raise ValidationFailed('easing must be "linear" or "perceptual".')

    colors = ramps.interpolate(
        (parsed_shadow["r"], parsed_shadow["g"], parsed_shadow["b"]),
        (parsed_light["r"], parsed_light["g"], parsed_light["b"]),
        steps,
        easing,
    )
    result = {"steps": steps, "colors": colors}
    applied = _apply_palette(filename, colors, apply)
    if applied is not None:
        result["applied"] = applied
    return result


@mcp.tool()
def ramp_from_art(
    filename: str,
    steps: int = 5,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Recover the ramp an existing sprite is painted with.

    `extract_palette` reports the colours a sprite uses as a set. A set is not a ramp: the
    shading tools need them ordered dark to light, and an agent asked to add to somebody
    else's sprite has no way to get that order today.

    The colours are grouped by luminance into `steps` bands, and each band is represented
    by the colour most of its pixels use, so every entry is a colour that is actually in
    the art and can be matched against it. `coverage` says what share of the drawn pixels
    each step covers, which is how to tell a real ramp from one step plus four stragglers.

    Says so when the colours are not a ramp: art spanning many hues is several materials
    sharing a sprite, and comes back with a warning rather than with a plausible-looking
    five colours. Scope the read with `layer` when that happens.
    """
    steps = int(steps)
    check_count(
        "steps", steps, MAX_COLOR_LIST_LENGTH, minimum=2,
        remedy="A ramp longer than a palette is not a ramp.",
    )
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame": int(frame),
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local framenum = require_frame(spr, ARG.frame, "frame")
    local img
    if ARG.layer ~= nil then
      img = get_draw_image(spr, find_layer(spr, ARG.layer), framenum)
    else
      img = Image(spr.spec); img:clear(); img:drawSprite(spr, framenum)
    end

    -- A histogram rather than the pixels: the ordering work is arithmetic over colours,
    -- and there are never many of those even when there are a great many pixels.
    local counts, order, n = {}, {}, 0
    for yy = 0, img.height - 1 do
      for xx = 0, img.width - 1 do
        local r, g, b, a = px_to_rgba(spr, img:getPixel(xx, yy))
        if a > 0 then
          local hex = string.format("#%02x%02x%02x", r, g, b)
          if counts[hex] == nil then
            counts[hex] = 0
            n = n + 1
            order[n] = hex
          end
          counts[hex] = counts[hex] + 1
        end
      end
    end

    local entries = {}
    for i, hex in ipairs(order) do entries[i] = { color = hex, count = counts[hex] } end
    RESULT = { frame = framenum, entries = entries }
    """
    measured = run_lua(body, args)
    histogram = {entry["color"]: entry["count"] for entry in measured["entries"]}
    found = ramps.cluster_by_luminance(histogram, steps)
    return {
        "ok": True,
        "frame": measured["frame"],
        "layer": layer,
        "colors": found["colors"],
        "coverage": found["coverage"],
        "distinct_colors": len(histogram),
        "warnings": found["warnings"],
    }


# --------------------------------------------------------------------------- #
# Palette cycling (issue #128)                                                #
# --------------------------------------------------------------------------- #
# Which palette index every pixel in scope carries, measured where the pixels are.
#
# Shared by `list_palette_usage`, which reports it, and by `cycle_palette`, which decides
# against it: the indices a cycle rotates have to be checked against the palette the
# sprite actually has, and that size is only knowable with the file open. Running the
# measurement as its own launch is what lets the refusals be written in Python with real
# numbers in them, and means nothing has been written when one of them fires.
#
# The empty/drawn split comes from the prelude's `clear_bytes` rather than from a test
# written here, so this cannot disagree with `visible_count` and `visible_extent` about
# what an empty pixel is. That disagreement is #172, and it cost one report a "4 drawn
# pixels" beside a 5x5 box.
_PALETTE_USAGE_LUA = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
if spr.colorMode ~= ColorMode.INDEXED then
  error("this sprite is " .. colormode_name(spr.colorMode) .. ", so its pixels carry " ..
        "their own colour rather than an offset into a palette and there are no palette " ..
        "indices to count or to cycle. extract_palette lists the colours an RGB sprite " ..
        "uses and assess_sprite counts them; set_color_mode(..., \\"indexed\\") first if " ..
        "you mean to cycle this one.", 0)
end

-- Every pixel layer, groups walked through rather than refused: a group holds no cels of
-- its own, so there is nothing to count on it and nothing to skip either. Tilemap layers
-- are left out because their cels are tile references and the indices in them are tile
-- numbers, not palette offsets.
local function collect(layers, out)
  for _, lyr in ipairs(layers) do
    if lyr.isGroup then
      collect(lyr.layers, out)
    elseif not lyr.isTilemap then
      out[#out + 1] = lyr
    end
  end
  return out
end

local scope, names = {}, {}
if ARG.layer ~= nil then
  local lyr = find_layer(spr, ARG.layer)
  if lyr.isGroup then
    error("'" .. lyr.name .. "' is a group layer and holds no cels of its own, so there " ..
          "are no pixels on it to count; name one of the layers inside it, or leave " ..
          "layer unset to count every pixel layer.", 0)
  end
  if lyr.isTilemap then
    error("'" .. lyr.name .. "' is a tilemap layer: the numbers in its cels are tile " ..
          "references rather than palette offsets. Read it with get_tilemap.", 0)
  end
  scope[1] = lyr
else
  collect(spr.layers, scope)
end
for i, lyr in ipairs(scope) do names[i] = lyr.name end

local first, last = 1, #spr.frames
if ARG.frame ~= nil then
  local n = require_frame(spr, ARG.frame, "frame")
  first, last = n, n
end

-- The cost is known before any of it is paid: a cel's image is only as big as its own
-- bounds, so this is the real figure rather than canvas times frames.
local area = 0
for f = first, last do
  for _, lyr in ipairs(scope) do
    local cel = lyr:cel(f)
    if cel ~= nil and cel.image ~= nil then
      area = area + cel.image.width * cel.image.height
    end
  end
end
if area > ARG.max_scan_pixels then
  error("counting palette indices here would read " .. area .. " pixels (" ..
        #scope .. " layer(s) across " .. (last - first + 1) .. " frame(s)); maximum is " ..
        ARG.max_scan_pixels .. ". Pass frame= or layer= to scope it down.", 0)
end

local pal = spr.palettes[1]
local size = #pal
local colors = {}
for i = 0, size - 1 do colors[i + 1] = color_hex(pal:getColor(i)) end

local stride, firstbyte, clear = clear_bytes(spr)
local counts, scanned, out_of_range = {}, 0, 0
local function tally(ix)
  counts[ix] = (counts[ix] or 0) + 1
  scanned = scanned + 1
  if ix >= size then out_of_range = out_of_range + 1 end
end

for f = first, last do
  for _, lyr in ipairs(scope) do
    local cel = lyr:cel(f)
    if cel ~= nil and cel.image ~= nil then
      local img = cel.image
      local s = img.bytes
      if #s == img.width * img.height * stride then
        -- One byte per pixel in indexed mode, and that byte *is* the index, so the whole
        -- histogram is a pass over the buffer with no getPixel and no palette lookup.
        -- Read in blocks because calling string.byte per byte dominates the cost, which
        -- is the same trick `visible_count` uses.
        local len, i = #s, 1
        while i <= len do
          local j = math.min(i + 511, len)
          local t = table.pack(string.byte(s, i, j))
          for k = firstbyte, t.n, stride do tally(t[k]) end
          i = j + 1
        end
      else
        -- Not the layout assumed above. Count the slow, certain way rather than a wrong
        -- way, exactly as `visible_count` does.
        for y = 0, img.height - 1 do
          for x = 0, img.width - 1 do tally(img:getPixel(x, y)) end
        end
      end
    end
  end
end

-- A list of records rather than a table keyed by index. json_encode decides between an
-- array and an object by looking at the keys, so a histogram that happened to be dense
-- from 1 would arrive as an array and one with a gap as an object: the same measurement
-- in two shapes, decided by the art. `draws` is the prelude's answer, not a second one.
local entries, n = {}, 0
for ix, count in pairs(counts) do
  n = n + 1
  entries[n] = { index = ix, pixels = count, draws = not clear[ix] }
end
table.sort(entries, function(a, b) return a.index < b.index end)

RESULT = {
  color_mode = colormode_name(spr.colorMode),
  size = size,
  transparent_index = spr.transparentColor,
  colors = colors,
  entries = entries,
  scanned = scanned,
  out_of_range = out_of_range,
  canvas = { width = spr.width, height = spr.height },
  frame_count = #spr.frames,
  frames_scanned = { first = first, last = last },
  layers = names,
}
"""


def _usage_scope(filename: str, frame: int | None, layer: str | None) -> dict:
    """Run the shared index measurement, with the arguments both callers share."""
    if frame is not None:
        frame = FrameRef.arg("frame", frame)
    return run_lua(_PALETTE_USAGE_LUA, {
        "src": lua_path(resolve_path(filename)),
        "frame": frame,
        "layer": layer,
        # Paid per pixel, and in the fast path it is a byte read rather than the getPixel
        # decode, so this ceiling is generous for what it buys: a million pixels is about
        # a tenth of a second. The same cap `quantize_palette` scans under.
        "max_scan_pixels": MAX_ASSESS_PIXELS,
    })


def _drawn_counts(measured: dict) -> dict[int, int]:
    """Index to pixel count, for the indices that can actually draw a visible pixel.

    Two separate things mean "nothing here" on an indexed sprite and both have to be
    excluded: the sprite's transparent index, and an entry whose own alpha is 0. Testing
    only the first is #138. The Lua side already answered it through `clear_bytes`; this
    only reads `draws` back.
    """
    return {
        int(entry["index"]): int(entry["pixels"])
        for entry in measured.get("entries") or []
        if entry.get("draws")
    }


@mcp.tool()
def list_palette_usage(
    filename: str, frame: int | None = None, layer: str | None = None
) -> dict:
    """Which palette indices the art is drawn with, how many pixels each covers, and
    which runs of them are worth cycling.

    Indexed sprites only: an RGB or grayscale pixel carries its own colour rather than an
    offset into a palette, so there is no index to count. `extract_palette` lists the
    colours such a sprite uses and `assess_sprite` counts them.

    The answer `cycle_palette` needs and the answer `get_palette` cannot give. A palette
    says what colours exist; this says which of them the picture actually uses, so a
    256-entry palette on a sprite painted in nine colours stops being a wall of hex. The
    only way to work this out before was to read every pixel through `get_pixels` and
    count them by hand.

    Args:
        frame: Count only this frame. Default: every frame.
        layer: Count only this layer. Default: every pixel layer, groups walked through.
            Tilemap layers are skipped, because the numbers in their cels are tile
            references rather than palette offsets.

    Returns `used` (index, colour and pixel count, most pixels first), `unused`, `runs`
    (the contiguous spans of used indices, longest first, which is what a cycle rotates),
    the transparent index and how many pixels sit on it, and `out_of_range`: pixels
    carrying an index past the end of the palette, which is what a palette resized
    smaller than its art leaves behind and which no colour can be read for at all.
    """
    measured = _usage_scope(filename, frame, layer)
    colors = measured["colors"]
    drawn = _drawn_counts(measured)
    transparent = measured["transparent_index"]

    # Only the entries the art uses carry a colour here. A tool asked which indices are in
    # use should not answer with the whole palette; `get_palette` is the tool for that.
    used = [
        {"index": index, "color": colors[index], "pixels": pixels}
        for index, pixels in sorted(drawn.items(), key=lambda pair: (-pair[1], pair[0]))
        if index < len(colors)
    ]
    result = {
        "size": measured["size"],
        "transparent_index": transparent,
        "transparent_pixels": sum(
            int(entry["pixels"]) for entry in measured["entries"]
            if not entry.get("draws")
        ),
        "scanned_pixels": measured["scanned"],
        "frames_scanned": measured["frames_scanned"],
        "layers_scanned": measured["layers"],
        "used": used,
        "unused": [
            index for index in range(measured["size"])
            if index != transparent and index not in drawn
        ],
        "runs": indexed.usage_runs(sorted(drawn)),
    }
    if measured["out_of_range"]:
        result["out_of_range"] = measured["out_of_range"]
    notes = indexed.palette_usage_readings({
        "size": measured["size"],
        "drawn": drawn,
        "out_of_range": measured["out_of_range"],
    })
    if notes:
        result["readings"] = notes
    return result


# The pixel remap each generated frame is written with, applied where the pixels are.
#
# `img_set` rather than `drawPixel`, so an active selection scopes the cycle like every
# other write here and the harness's `pixels_written` counts it. Read from a snapshot and
# written to the live image, because the remap is a permutation over the cycled indices:
# writing in place would let a pixel already moved to index 8 be read again as a source.
_CYCLE_WRITE_LUA = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
if spr.colorMode ~= ColorMode.INDEXED then
  error("this sprite is no longer indexed, so its pixels are not palette offsets any " ..
        "more and the cycle it was planned for does not describe them. Nothing was " ..
        "written.", 0)
end
if #spr.frames ~= 1 then
  error("the sprite has " .. #spr.frames .. " frames now and had 1 when this cycle was " ..
        "planned, so another call added frames between the two passes of this one. " ..
        "Nothing was written; try again.", 0)
end

local function collect(layers, out)
  for _, lyr in ipairs(layers) do
    if lyr.isGroup then collect(lyr.layers, out)
    elseif not lyr.isTilemap then out[#out + 1] = lyr end
  end
  return out
end

local scope = {}
if ARG.layer ~= nil then
  scope[1] = find_layer(spr, ARG.layer)
else
  collect(spr.layers, scope)
end

-- The frames first, all duplicated from the one drawn frame, so every one of them starts
-- as the art the caller drew and only the indices change afterwards. newFrame inserts
-- after the frame it copies, so these arrive in reverse order; that costs nothing,
-- because they are all identical until they are remapped by frame number below.
for _ = 2, ARG.frame_count do
  spr:newFrame(1)
end

local changed = {}
for f = 2, ARG.frame_count do
  local remap = ARG.remaps[f]
  if remap == nil then
    error("no remap was planned for frame " .. f .. "; nothing further was written. " ..
          "This is a bug in cycle_palette rather than anything about the sprite.", 0)
  end
  for _, lyr in ipairs(scope) do
    local cel = lyr:cel(f)
    if cel ~= nil and cel.image ~= nil then
      local img = get_draw_image(spr, lyr, f)
      local snapshot = img:clone()
      local moved = 0
      for y = 0, img.height - 1 do
        for x = 0, img.width - 1 do
          local to = remap[snapshot:getPixel(x, y)]
          if to ~= nil then
            img_set(img, x, y, to)
            moved = moved + 1
          end
        end
      end
      if moved > 0 then
        commit_image(spr, lyr, f, img)
        changed[#changed + 1] = { frame = f, layer = lyr.name, pixels = moved }
      end
    end
  end
end

save_sprite(spr)
RESULT = {
  frame_count = #spr.frames,
  remapped = changed,
  -- Reported because it is the promise this tool makes and the easiest thing to get
  -- wrong: what rotates is the pixels, and the palette comes back exactly as it went in.
  palette_size = #spr.palettes[1],
}
"""


@mcp.tool()
def cycle_palette(
    filename: str,
    indices: list[int],
    frame_count: int | None = None,
    step: int = 1,
    layer: str | None = None,
) -> dict:
    """Animate a sprite by cycling a run of palette colours, the oldest trick in the
    medium: the pixels do not move, the colours do, and water flows.

    **What this ships, and why.** Aseprite's file format carries a palette per frame, but
    its Lua API does not expose one, so the real thing cannot be authored from here.
    Measured on 1.3.18.6: `#spr.palettes` is 1 and stays 1, the collection is read-only
    (`spr.palettes[2] = ...` and `table.insert` both raise "attempt to index a nil value
    (field '__setters')"), `Palette` has no `frame` property, `Sprite:newPalette` does not
    exist, and `Sprite:setPalette` replaces the single sprite-wide palette no matter which
    frame `app.frame` is on, as does `app.command.LoadPalette`. So this is the fallback:
    the frames are generated, it costs one frame of storage each, and it works everywhere
    a frame does, including in a GIF or a PNG sequence.

    What rotates is the pixels' own indices, not the palette. On an indexed sprite those
    are the same picture, and the index move is exact: no colour matching, nothing routed
    through `nearest_index`, and the palette comes back byte for byte as it went in, so
    `get_palette` still shows the ramp that was authored.

    Args:
        indices: The palette indices to rotate, **in the order the colours travel**. At
            least two, distinct, each one in the palette, and none of them an entry that
            cannot draw (the sprite's transparent index, or an entry whose alpha is 0):
            rotating one of those through the cycle would make drawn pixels vanish.
            `list_palette_usage` reports the contiguous runs worth passing here.
        frame_count: How many frames the cycle occupies. Defaults to `len(indices)`, which
            is one frame per colour, and is capped there: past that the rotation repeats a
            frame already written, so the extra frames cost storage and show nothing new.
        step: How far the colours travel per frame. Positive moves them forward along
            `indices`; negative moves them back. A multiple of `len(indices)` is refused
            rather than silently producing identical frames.
        layer: Cycle only this layer's pixels. Default: every pixel layer.

    The sprite must have exactly one frame. A cycle generates the whole timeline from the
    one drawn frame, so a sprite that already animates would have its timeline redefined,
    and that is refused rather than guessed at: `duplicate_frame` the pose into a sprite
    of its own first.

    Refuses, before anything is written, an index outside the palette (it names the size),
    an index that cannot draw, a repeated index, a step that is a whole number of laps, and
    a cycle none of whose indices appear in the art, which would write identical frames and
    animate nothing. That last refusal names the indices the art *is* drawn with.

    Returns the frames it wrote and how many pixels moved on each, `closes` (whether the
    rotation returns to where it started at the wrap), and `warnings` when the cycle does
    not close, or when an index in it has no pixels to travel through. `warnings` is
    absent rather than empty when there is nothing to say.
    """
    if not isinstance(indices, list):
        raise ValidationFailed(
            f"indices must be a list of palette indices; got {type(indices).__name__}."
        )
    check_list_length("indices", indices, MAX_COLOR_LIST_LENGTH,
                      remedy=f"A palette holds at most {MAX_COLOR_LIST_LENGTH} colours.")

    measured = _usage_scope(filename, None, layer)
    if measured["frame_count"] != 1:
        raise ValidationFailed(
            f"this sprite has {measured['frame_count']} frames. A cycle generates the "
            "whole timeline from one drawn frame, so writing it here would redefine the "
            "animation that is already there. Draw the pose into a single-frame sprite of "
            "its own and cycle that, or remove_frame down to one first."
        )

    drawn = _drawn_counts(measured)
    wheel = indexed.cycle_indices(
        indices, measured["colors"], measured["transparent_index"], drawn)
    travel = indexed.cycle_step(step, len(wheel))
    count = len(wheel) if frame_count is None else check_count(
        "frame_count", frame_count, len(wheel), minimum=2,
        remedy=f"The cycle has {len(wheel)} indices, so past {len(wheel)} frames the "
               "rotation repeats a frame already written and the extra frames cost "
               "storage without showing anything new.",
    )

    # Canvas times the frames about to be written, because every one of them is walked
    # pixel by pixel. The measurement pass bounded its own scan against the cels; this is
    # the larger figure and it is bounded before the first frame is added.
    layers = max(1, len(measured["layers"]))
    budget = (
        measured["canvas"]["width"] * measured["canvas"]["height"] * (count - 1) * layers
    )
    if budget > MAX_ASSESS_PIXELS:
        raise ValidationFailed(
            f"this cycle would walk {budget} pixels ("
            f"{measured['canvas']['width']}x{measured['canvas']['height']} times "
            f"{count - 1} generated frame(s) times {layers} layer(s)); maximum is "
            f"{MAX_ASSESS_PIXELS}. Nothing was written. Pass layer= to cycle one layer, "
            "ask for fewer frames, or cycle a smaller canvas."
        )

    remaps = indexed.cycle_remaps(wheel, count, travel)
    applied = run_lua(_CYCLE_WRITE_LUA, {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "frame_count": count,
        # 1-based, keyed by the frame number the remap belongs to, so the Lua side looks
        # a frame up rather than counting along a list and hoping the orders agree.
        "remaps": {index + 1: remap for index, remap in enumerate(remaps)},
    })

    result = {
        "ok": True,
        "method": "pixel_remap",
        "indices": wheel,
        "step": travel,
        "frame_count": applied["frame_count"],
        "palette_size": applied["palette_size"],
        "remapped": applied["remapped"],
        "pixels_written": applied.get("pixels_written", 0),
        "closes": (count * travel) % len(wheel) == 0,
    }
    # Absent rather than empty when there is nothing to say, which is what the rest of
    # this module does: a `warnings` key here always means there is something in it.
    notes = indexed.cycle_readings(wheel, count, travel, drawn)
    if notes:
        result["warnings"] = notes
    return result
