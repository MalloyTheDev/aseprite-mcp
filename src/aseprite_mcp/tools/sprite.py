"""Sprite lifecycle: create, save, resize, crop, scale, flatten, colour mode."""

from __future__ import annotations

from ..app import mcp
from ..core import indexed
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_CANVAS_DIMENSION,
    MAX_CANVAS_PIXELS,
    MAX_SPRITE_TOTAL_PIXELS,
    MAX_VERIFY_PIXELS,
    check_canvas_size,
)
from ..core.paths import discard_selection_sidecar, ensure_output_path
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
    # A selection is state belonging to a sprite, and this replaces the sprite. Left in
    # place, the sidecar made the new sprite open with the old one's selection and quietly
    # dropped every edit outside it.
    inherited = discard_selection_sidecar(path)
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
    # Said rather than done silently: a caller who had a selection on the old sprite of
    # this name should know it is gone, and one who did not should see nothing.
    if inherited:
        info["discarded_selection"] = True
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
    # The copy is a different sprite at a different path, so whatever selection happened to
    # be sitting beside that path is not its. The source's own sidecar is untouched.
    discard_selection_sidecar(dst)
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

    That check counts every pixel of every frame, twice. Past `MAX_VERIFY_PIXELS` the
    conversion still runs and reports `verified: false` with the reason, rather than
    being refused: a capability that declines to work on a large sheet because the check
    is unaffordable is worse than one that works and says what it did not check.
    `diff_sprites` against a copy taken beforehand answers the same question by hand.

    Returns the sprite's structured info, plus `drawn_pixels` and `verified` (whether
    that count was actually compared across the conversion) and the `palette_source`
    used, for indexed targets.
    """
    mode = indexed.normalise_color_mode(color_mode)
    # Validated even for the modes that ignore it: an argument that is silently
    # discarded is indistinguishable from one that was honoured, and Aseprite accepts
    # `dithering = "no-such-dither"` without a word and converts with its default.
    dither = indexed.normalise_dithering(dithering)
    source = indexed.normalise_palette_source(palette_source)
    src = resolve_path(filename)
    args = {
        "src": lua_path(src), "mode": mode, "dither": dither, "source": source,
        "max_verify": MAX_VERIFY_PIXELS,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local to_indexed = (ARG.mode == "indexed")

    -- Only indexed targets are measured. RGB and gray both keep a per-pixel alpha
    -- channel and have no index that means "nothing", so there is no hole for a pixel
    -- to fall through and no reason to pay for the scan.
    --
    -- The work is the canvas times the frames, and it is paid twice. Measured rather
    -- than capped by the canvas alone: one frame at the maximum canvas is cheap, and
    -- twenty of them is not the same call at all.
    local scan_pixels = spr.width * spr.height * #spr.frames
    local verify = to_indexed and scan_pixels <= ARG.max_verify
    local before = verify and visible_count_all_frames(spr) or 0

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

    local after = verify and visible_count_all_frames(spr) or 0
    if verify and after < before then
      -- Raised before save_sprite, which is the whole point: the conversion exists only
      -- in this process, so refusing here leaves the file on disk exactly as it was.
      --
      -- The message states the measurement and the mechanism, not a diagnosis. Losing a
      -- drawn pixel in indexed mode has exactly one mechanism, landing on the transparent
      -- index or on a transparent entry, so that much is safe to say. It used to go on to
      -- name the palette at fault, in a branch per palette_source, and the from_art branch
      -- read "Unexpected with palette_source='from_art'" because no case reaching it was
      -- ever found: quantizing from the art is what stops pixels being lost. A message
      -- that has never run cannot be trusted to be right when it finally does, and
      -- guessing the route is not worth two texts, so both remedies are offered and
      -- neither is asserted.
      error(string.format(
        "converting to indexed would lose %d of %d drawn pixels: they would land on the " ..
        "transparent index or on a transparent palette entry and come out invisible. The " ..
        "sprite on disk is unchanged. Give the sprite a palette that covers its colours " ..
        "(set_palette, add_palette_color), or pass palette_source='from_art' to build one " ..
        "from the art; extract_palette reports the colours that need covering.",
        before - after, before), 0)
    end

    save_sprite(spr)
    RESULT = sprite_info(spr)
    if to_indexed then
      RESULT.palette_source = ARG.source
      RESULT.verified = verify
      if verify then
        RESULT.drawn_pixels = after
      else
        -- No count, rather than a 0 that would read as "nothing is drawn". A Lua table
        -- cannot hold an explicit null (a key set to nil simply is not there), so
        -- `verified` is the field to branch on and the reason says why in words.
        RESULT.unverified_reason = string.format(
          "%d pixels across %d frame(s) is past the verification cap of %d, so the " ..
          "conversion ran without checking that drawn pixels survived it. Nothing is " ..
          "known to be wrong. diff_sprites against a copy taken before the conversion " ..
          "answers the same question.", scan_pixels, #spr.frames, ARG.max_verify)
      end
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
    dimension/area caps as `create_sprite`. New area is transparent, except on a
    Background, where it is black, or the transparent palette index on an indexed sprite.
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
    background_fill(spr)
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
    (a "crop" to a larger rectangle grows the canvas). Where it grows a Background, the new
    area is black, or the transparent palette index on an indexed sprite.
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
    background_fill(spr)
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
    # The prelude's `visible_extent` rather than the per-pixel getPixel loop this used to
    # run, and rather than `Image:shrinkBounds`. The loop's answer was the careful one:
    # it treated a pixel held in a fully transparent palette entry as empty, which
    # shrinkBounds does not, and that answer is preserved exactly here (measured on an
    # 8x8 indexed sprite with such a pixel at 6,6: both say 2x2 at 2,2, shrinkBounds says
    # 5x5). What changes is that the definition now lives in one place shared with
    # `drawn_pixels`, so trimming and counting cannot drift apart (#172), and that the
    # scan reads the byte buffer instead of calling getPixel per pixel: 5.2x cheaper
    # measured over a 1024x1024 frame, which matters because this is the one scan in this
    # file with no cap but the canvas limit behind it.
    body = """
    local spr = open_sprite(ARG.src)
    local minx, miny, maxx, maxy
    for f = 1, #spr.frames do
      -- As Aseprite draws it, so an indexed Background is the opaque surface it is on
      -- screen, the same as an RGB one, rather than a margin to crop wherever it happens
      -- to be the transparent index's colour.
      local flat = readable_composite(spr, f)
      -- Per frame and unioned, not over a single composite: a sprite whose frames hold
      -- art in different places has to keep all of it, so the crop is the box that
      -- covers every frame.
      local _, box = visible_extent(spr, flat)
      if box ~= nil then
        if minx == nil or box.x < minx then minx = box.x end
        if miny == nil or box.y < miny then miny = box.y end
        local right, bottom = box.x + box.width - 1, box.y + box.height - 1
        if maxx == nil or right > maxx then maxx = right end
        if maxy == nil or bottom > maxy then maxy = bottom end
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
    """Convert a normal layer into the sprite's opaque Background layer.

    Its transparent pixels are filled: with black on an RGB or grayscale sprite, and with
    the transparent palette index on an indexed one, which a Background shows as that
    entry's colour, so no index changes and converting back restores the transparency.
    The fill used to come from the editor's colour bar, so the same call gave a different
    colour on every machine.
    """
    args = {"src": lua_path(resolve_path(filename)), "layer": layer}
    body = """
    local spr = open_sprite(ARG.src)
    background_fill(spr)
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
