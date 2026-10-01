"""Palette management: read, replace, edit individual colours, load, transparency."""

from __future__ import annotations

from ..app import mcp
from ..core import indexed, ramps
from ..core.errors import ValidationFailed
from ..core.limits import MAX_COLOR_LIST_LENGTH, check_count, check_list_length
from ..core.models import FRAME_GUARD_LUA
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

    Returns the ramp as a list of "#RRGGBB" colours (darkest first).
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

    colors = []
    for i in range(steps):
        u = i / (steps - 1)  # 0 = darkest .. 1 = lightest
        t = u - 0.5  # -0.5 .. 0.5, the original parameterisation

        # Lightness. "perceptual" bunches the dark steps, because equal steps in HLS
        # lightness are not equal steps to the eye and a ramp built that way has a
        # muddy shadow end.
        lt = (u**1.5) - 0.5 if easing == "perceptual" else t
        L = min(1.0, max(0.0, lum + lt * light_range))

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
        colors.append(f"#{round(rr * 255):02x}{round(gg * 255):02x}{round(bb * 255):02x}")

    result = {"steps": steps, "colors": colors}
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
