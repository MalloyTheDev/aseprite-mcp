"""Palette management: read, replace, edit individual colours, load, transparency."""

from __future__ import annotations

from ..app import mcp
from ..core.limits import MAX_COLOR_LIST_LENGTH, check_list_length
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path


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
        raise ValueError("colors must be a non-empty list.")
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
    """
    return run_lua(body, args)


@mcp.tool()
def set_palette_color(filename: str, index: int, color: str) -> dict:
    """Set a single palette entry by index (0-based). Grows the palette if needed."""
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
    """
    return run_lua(body, args)


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
    """
    return run_lua(body, args)


@mcp.tool()
def resize_palette(filename: str, size: int) -> dict:
    """Resize the palette to `size` entries (new entries are black)."""
    args = {"src": lua_path(resolve_path(filename)), "size": max(1, int(size))}
    body = """
    local spr = open_sprite(ARG.src)
    spr.palettes[1]:resize(ARG.size)
    save_sprite(spr)
    RESULT = { ok = true, size = #spr.palettes[1] }
    """
    return run_lua(body, args)


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
    """
    return run_lua(body, args)


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
        raise ValueError('by must be one of: hue, luminance, saturation, value')
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
      for _, cel in ipairs(spr.cels) do
        -- Skip tilemap cels: their pixels are tile indices, not palette indices.
        if not cel.layer.isTilemap then
          local im = Image(cel.image)
          for y = 0, im.height - 1 do
            for x = 0, im.width - 1 do
              local v = im:getPixel(x, y)
              if remap[v] ~= nil then im:drawPixel(x, y, remap[v]) end
            end
          end
          cel.image = im
        end
      end
      if remap[spr.transparentColor] ~= nil then spr.transparentColor = remap[spr.transparentColor] end
    end
    save_sprite(spr)
    RESULT = { ok = true, size = n, by = ARG.by }
    """
    return run_lua(body, args)


@mcp.tool()
def generate_ramp(
    base_color: str,
    steps: int = 5,
    hue_shift: float = 0.0,
    saturation_shift: float = 0.0,
    light_range: float = 0.6,
    filename: str | None = None,
    apply: str = "none",
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
    base = parse_color(base_color)
    r, g, b = base["r"] / 255, base["g"] / 255, base["b"] / 255
    h, lum, sat = colorsys.rgb_to_hls(r, g, b)
    colors = []
    for i in range(steps):
        t = (i / (steps - 1)) - 0.5  # -0.5 .. 0.5
        L = min(1.0, max(0.0, lum + t * light_range))
        H = (h + (t * hue_shift / 360.0)) % 1.0
        S = min(1.0, max(0.0, sat * (1 + t * saturation_shift / 100.0)))
        rr, gg, bb = colorsys.hls_to_rgb(H, L, S)
        colors.append("#%02x%02x%02x" % (round(rr * 255), round(gg * 255), round(bb * 255)))

    result = {"steps": steps, "colors": colors}
    if apply != "none":
        if apply not in ("append", "replace"):
            raise ValueError('apply must be "none", "append", or "replace"')
        if not filename:
            raise ValueError("filename is required when apply is not 'none'.")
        parsed = [parse_color(c) for c in colors]
        args = {
            "src": lua_path(resolve_path(filename)),
            "colors": parsed, "mode": apply,
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
        result["applied"] = run_lua(body, args)
    return result


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
