"""Sprite lifecycle: create, save, resize, crop, scale, flatten, colour mode."""

from __future__ import annotations

from ..app import mcp
from ..core import indexed
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_CANVAS_DIMENSION,
    MAX_CANVAS_PIXELS,
    MAX_SPRITE_TOTAL_PIXELS,
    check_canvas_size,
)
from ..core.paths import ensure_output_path
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path


@mcp.tool()
def create_sprite(
    filename: str,
    width: int,
    height: int,
    color_mode: str = "rgb",
    background: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Create a new sprite file and save it.

    Args:
        filename: Output path. Relative paths go in the workspace. Use a
            .aseprite/.ase extension to keep layers & frames editable.
        width, height: Canvas size in pixels. Each axis is capped at 16384px
            and the total area at 16,777,216 pixels (e.g. 4096x4096).
        color_mode: "rgb" (default), "indexed", or "gray".
        background: Optional fill colour for the first layer (e.g. "#1d2b53").
            Omit for a transparent canvas.
        overwrite: Replace `filename` if it already exists (default False = no-clobber).

    An **indexed** sprite is created with a usable 33-colour palette: a transparent
    entry at index 0 (the index that means "no pixel here"), then the 32 colours
    Aseprite ships as its default. Aseprite's own new indexed sprite has 256 entries of
    identical black instead, which made every colour equidistant from every entry, so
    every draw resolved to index 0 and was invisible while reporting success. A
    `background` colour that the default palette does not contain is appended to it, so
    the background is the exact colour asked for rather than the nearest one available.
    Replace the whole palette with `set_palette` when you have one in mind.

    Returns the new sprite's structured info.
    """
    width, height = check_canvas_size(width, height)
    # Rejected here rather than inside Lua's `colormode_from`, so a misspelled mode
    # costs an argument and not an Aseprite launch.
    mode = indexed.normalise_color_mode(color_mode)
    bg = parse_color(background) if background else None
    path = ensure_output_path(filename, overwrite=overwrite)
    args = {
        "path": lua_path(path),
        "width": width,
        "height": height,
        "color_mode": mode,
        "bg": bg,
        # Parsed on this side and handed over as {r,g,b,a} tables, which is the shape
        # `mkcolor` takes and the route `set_palette` already uses.
        "palette": (
            [parse_color(c) for c in indexed.palette_for_new_sprite(bg)]
            if mode == "indexed" else None
        ),
    }
    body = """
    local spr = Sprite(ARG.width, ARG.height, colormode_from(ARG.color_mode))
    spr.filename = ARG.path
    if ARG.palette ~= nil then
      local pal = Palette(#ARG.palette)
      for i, c in ipairs(ARG.palette) do pal:setColor(i - 1, mkcolor(c)) end
      spr:setPalette(pal)
      -- Stated rather than inherited. A new sprite's transparentColor is already 0, and
      -- entry 0 of the palette above is deliberately the transparent one; saying so
      -- here keeps the two facts together instead of leaving one to a default.
      spr.transparentColor = 0
    end
    if ARG.bg ~= nil then
      local layer = spr.layers[1]
      local img = get_draw_image(spr, layer, 1)
      draw_rect_img(img, 0, 0, spr.width, spr.height, to_pixel(spr, ARG.bg), true)
      commit_image(spr, layer, 1, img)
    end
    spr:saveAs(ARG.path)
    RESULT = sprite_info(spr)
    """
    info = run_lua(body, args)
    info["path"] = str(path)
    return info


@mcp.tool()
def save_sprite_as(
    filename: str, new_filename: str, flatten: bool = False, overwrite: bool = False
) -> dict:
    """Save a copy of a sprite under a new path (optionally flattened).

    The original file is left untouched. Useful for exporting an editable
    .aseprite to another .aseprite, or snapshotting a version.

    overwrite: Replace `new_filename` if it already exists (default False = no-clobber).
    """
    src = resolve_path(filename)
    dst = ensure_output_path(new_filename, overwrite=overwrite)
    args = {"src": lua_path(src), "dst": lua_path(dst), "flatten": bool(flatten)}
    body = """
    local spr = open_sprite(ARG.src)
    local copy = Sprite(spr)
    if ARG.flatten then copy:flatten() end
    copy.filename = ARG.dst
    copy:saveAs(ARG.dst)
    RESULT = sprite_info(copy)
    """
    info = run_lua(body, args)
    info["path"] = str(dst)
    return info


@mcp.tool()
def set_color_mode(
    filename: str,
    color_mode: str,
    dithering: str = "none",
    palette_source: str = "from_art",
) -> dict:
    """Convert a sprite between colour modes ("rgb", "indexed", "gray").

    Converting **to indexed** builds the palette from the sprite's own colours first,
    which is what the editor does and what makes the art survive. Mapping art against
    whatever palette the sprite happened to carry is how this tool used to empty a
    sprite: a saved RGB sprite carries a single transparent entry, so every pixel
    resolved to it and the whole image became transparent while the call reported ok.

    Args:
        color_mode: "rgb", "indexed", or "gray".
        dithering: "none" (default), "ordered", or "old". How a colour between two
            palette entries is resolved. Indexed conversions only.
        palette_source: "from_art" (default) quantizes the sprite's colours into a new
            palette and maps onto that, so flat colours convert exactly. "keep" maps
            against the palette the sprite already has, for when you loaded or built one
            deliberately; snapping the art to that palette is the point, so expect
            colours to shift, and expect two art colours to merge where the palette has
            only one entry near them. Indexed conversions only; the other modes have no
            palette to choose.

    **Refuses** a conversion to indexed that would make drawn pixels disappear, naming
    how many, and leaves the file untouched when it does. Losing colour accuracy is what
    indexed mode is for and is allowed; losing pixels is not recoverable and is the one
    thing a mode change must never do quietly. `set_palette` or `add_palette_color` fix a
    palette that has nothing to draw with.

    Returns the sprite's structured info, plus `drawn_pixels` (verified unchanged by the
    conversion) and the `palette_source` used, for indexed targets.
    """
    mode = indexed.normalise_color_mode(color_mode)
    # Validated even for the modes that ignore it: an argument that is silently
    # discarded is indistinguishable from one that was honoured, and Aseprite accepts
    # `dithering = "no-such-dither"` without a word and converts with its default.
    dither = indexed.normalise_dithering(dithering)
    source = indexed.normalise_palette_source(palette_source)
    src = resolve_path(filename)
    args = {"src": lua_path(src), "mode": mode, "dither": dither, "source": source}
    body = """
    local spr = open_sprite(ARG.src)
    local to_indexed = (ARG.mode == "indexed")

    -- Visible pixels, counted the same way `trim_sprite` counts them: flatten each
    -- frame and ask the prelude's decoder, which knows that the transparent index and a
    -- transparent palette entry both mean "not there".
    local function drawn(s)
      local n = 0
      for f = 1, #s.frames do
        local flat = Image(s.spec); flat:clear(); flat:drawSprite(s, f)
        for y = 0, flat.height - 1 do
          for x = 0, flat.width - 1 do
            local _, _, _, a = px_to_rgba(s, flat:getPixel(x, y))
            if a > 0 then n = n + 1 end
          end
        end
      end
      return n
    end

    -- Only indexed targets are measured. RGB and gray both keep a per-pixel alpha
    -- channel and have no index that means "nothing", so there is no hole for a pixel
    -- to fall through and no reason to pay for the scan.
    local before = to_indexed and drawn(spr) or 0

    if to_indexed and ARG.source == "from_art" and spr.colorMode ~= ColorMode.INDEXED then
      -- The step this tool was missing. ChangePixelFormat maps the art onto the palette
      -- the sprite already has; it does not build one. ColorQuantization is what builds
      -- it, reserving index 0 for transparency and giving every colour in every frame an
      -- entry, including the semi-transparent ones.
      --
      -- Skipped when the sprite is already indexed, because then the palette is the
      -- sprite's own and re-quantizing it would discard a palette nobody asked to lose.
      app.command.ColorQuantization{ ui = false }
    end
    app.command.ChangePixelFormat{ ui = false, format = ARG.mode, dithering = ARG.dither }

    local after = to_indexed and drawn(spr) or 0
    if to_indexed and after < before then
      -- Raised before save_sprite, which is the whole point: the conversion exists only
      -- in this process, so refusing here leaves the file on disk exactly as it was.
      --
      -- The message states the measurement and the mechanism, not a diagnosis. Losing a
      -- drawn pixel in indexed mode has exactly one mechanism, landing on the transparent
      -- index or on a transparent entry, so that much is safe to say; which palette is at
      -- fault depends on the route and is left to the remedy.
      local remedy = (ARG.source == "keep")
        and "Give the sprite a palette that covers its colours (set_palette, " ..
            "add_palette_color), or pass palette_source='from_art' to build one from the art."
        or "Unexpected with palette_source='from_art', which builds the palette from the " ..
           "art: read the colours back with extract_palette before converting."
      error(string.format(
        "converting to indexed would lose %d of %d drawn pixels: they would land on the " ..
        "transparent index or on a transparent palette entry and come out invisible. The " ..
        "sprite on disk is unchanged. %s", before - after, before, remedy), 0)
    end

    save_sprite(spr)
    RESULT = sprite_info(spr)
    if to_indexed then
      RESULT.drawn_pixels = after
      RESULT.palette_source = ARG.source
    end
    """
    return run_lua(body, args)


@mcp.tool()
def resize_canvas(
    filename: str, width: int, height: int, anchor: str = "top_left"
) -> dict:
    """Resize the canvas WITHOUT scaling the artwork (adds or trims space).

    anchor controls where existing content sits in the new canvas:
    "top_left" (default) or "center". The new canvas is subject to the same
    dimension/area caps as `create_sprite`.
    """
    width, height = check_canvas_size(width, height)
    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "width": width,
        "height": height,
        "anchor": anchor,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local x, y = 0, 0
    if ARG.anchor == "center" then
      x = -math.floor((ARG.width - spr.width) / 2)
      y = -math.floor((ARG.height - spr.height) / 2)
    end
    spr:crop(x, y, ARG.width, ARG.height)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def crop_sprite(filename: str, x: int, y: int, width: int, height: int) -> dict:
    """Crop the canvas to the rectangle (x, y, width, height).

    The resulting canvas is subject to the same dimension/area caps as `create_sprite`
    (a "crop" to a larger rectangle grows the canvas).
    """
    width, height = check_canvas_size(width, height)
    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "x": int(x),
        "y": int(y),
        "width": width,
        "height": height,
    }
    body = """
    local spr = open_sprite(ARG.src)
    spr:crop(ARG.x, ARG.y, ARG.width, ARG.height)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def scale_sprite(
    filename: str,
    factor: float | None = None,
    width: int | None = None,
    height: int | None = None,
    method: str = "nearest",
) -> dict:
    """Scale the whole sprite (artwork included).

    Provide either `factor` (e.g. 2.0 to double) OR explicit `width`/`height`.
    method: "nearest" (crisp pixels, default) or "bilinear" (smooth).

    The scaled canvas is subject to the same dimension/area caps as `create_sprite`.
    With `factor` the result depends on the sprite's current size, so that check runs
    inside Aseprite and reports the size it would have produced.
    """
    src = resolve_path(filename)
    if factor is None and width is None and height is None:
        raise ValidationFailed("Provide either factor or width/height.")
    if factor is not None:
        factor = float(factor)
        if factor != factor or factor <= 0 or factor == float("inf"):
            raise ValidationFailed(
                f"factor must be a positive finite number, got {factor!r}."
            )
    if width is not None and height is not None:
        width, height = check_canvas_size(width, height)
    elif width is not None:
        check_canvas_size(width, 1)
        width = int(width)
    elif height is not None:
        check_canvas_size(1, height)
        height = int(height)
    args = {
        "src": lua_path(src),
        "factor": factor,
        "width": width,
        "height": height,
        "method": method,
        "max_dim": MAX_CANVAS_DIMENSION,
        "max_pixels": MAX_CANVAS_PIXELS,
        "max_total_pixels": MAX_SPRITE_TOTAL_PIXELS,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local w = ARG.width
    local h = ARG.height
    if ARG.factor ~= nil then
      w = math.max(1, math.floor(spr.width * ARG.factor + 0.5))
      h = math.max(1, math.floor(spr.height * ARG.factor + 0.5))
    end
    w = w or spr.width
    h = h or spr.height
    if w > ARG.max_dim or h > ARG.max_dim or w * h > ARG.max_pixels then
      error(string.format(
        "scaled canvas %dx%d exceeds the limits (max %dpx per axis, %d pixels total). "
        .. "Use a smaller factor or explicit width/height.", w, h, ARG.max_dim, ARG.max_pixels))
    end
    -- SpriteSize rescales every cel, not just the canvas, so a legal target size
    -- still multiplies by the number of independent cel images. Bound the predicted
    -- aggregate before allocating any of it.
    local ratio = (w * h) / (spr.width * spr.height)
    local total = 0
    for _, cel in ipairs(spr.cels) do
      if cel.image ~= nil then
        total = total + cel.image.width * cel.image.height * ratio
      end
    end
    if total > ARG.max_total_pixels then
      error(string.format(
        "scaling to %dx%d would need about %d pixels across %d cels; maximum is %d. "
        .. "Use a smaller factor, or flatten/trim the sprite first.",
        w, h, math.floor(total), #spr.cels, ARG.max_total_pixels))
    end
    app.command.SpriteSize{ ui = false, width = w, height = h, method = ARG.method }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def flatten_sprite(filename: str) -> dict:
    """Flatten all layers into a single layer (in place)."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    spr:flatten()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})


@mcp.tool()
def trim_sprite(filename: str) -> dict:
    """Auto-crop the canvas to the bounding box of all non-transparent content
    (across every frame)."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    local minx, miny, maxx, maxy
    for f = 1, #spr.frames do
      local flat = Image(spr.spec); flat:clear(); flat:drawSprite(spr, f)
      for y = 0, flat.height - 1 do
        for x = 0, flat.width - 1 do
          local _, _, _, a = px_to_rgba(spr, flat:getPixel(x, y))
          if a > 0 then
            if minx == nil or x < minx then minx = x end
            if miny == nil or y < miny then miny = y end
            if maxx == nil or x > maxx then maxx = x end
            if maxy == nil or y > maxy then maxy = y end
          end
        end
      end
    end
    if minx == nil then error("Sprite is fully transparent; nothing to trim.") end
    spr:crop(minx, miny, maxx - minx + 1, maxy - miny + 1)
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})


@mcp.tool()
def convert_layer_to_background(filename: str, layer: str) -> dict:
    """Convert a normal layer into the sprite's opaque Background layer."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer}
    body = """
    local spr = open_sprite(ARG.src)
    app.layer = find_layer(spr, ARG.layer)
    app.command.BackgroundFromLayer()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)


@mcp.tool()
def convert_background_to_layer(filename: str) -> dict:
    """Convert the Background layer back into a normal (transparent-capable) layer."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    app.command.LayerFromBackground()
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})
