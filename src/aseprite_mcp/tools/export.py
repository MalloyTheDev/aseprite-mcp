"""Export & import: PNG, animated GIF, sprite sheets, per-frame images, import.

These use the Aseprite CLI directly (rich export flags). Output paths follow the
same workspace rules as everything else.
"""

from __future__ import annotations

from ..app import mcp
from ..core import asefile, gifmeta
from ..core.errors import ExportError, ValidationFailed
from ..core.limits import (
    MAX_CANVAS_DIMENSION,
    MAX_CANVAS_PIXELS,
    MAX_MOTION_FRAMES,
    MAX_SPRITE_TOTAL_PIXELS,
    check_count,
    check_list_length,
)
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.paths import (
    discard_selection_sidecar,
    ensure_output_path,
    ensure_output_pattern,
)
from ..core.runner import run_cli, run_lua
from .common import lua_path, resolve_path
from .image import check_image_dimensions

_SHEET_TYPES = {"horizontal", "vertical", "rows", "columns", "packed"}

# The two data formats `ExportSpriteSheet` writes. Validated here because the command does
# not: `dataFormat = "no-such-format"` was accepted without a word and wrote a file in its
# default format, so a misspelling would have produced a sheet whose metadata was in the
# other shape than the one asked for.
_DATA_FORMATS = {"json-array", "json-hash"}


def _packed_sheet_notes(sheet_type: str, merge_duplicates: bool) -> list[str]:
    """What is worth saying about a sheet-type and flag combination.

    One combination misreports itself. A packed sheet merges identical frames whether or
    not `merge_duplicates` is set: measured on a three-frame sprite whose first two
    frames were identical, `sheet_type="packed"` with the flag off produced a two-cell
    sheet and a data file in which frames 0 and 1 share one rectangle, while the same
    sprite exported as rows put all three side by side. A caller comparing a packed sheet
    with and without the flag therefore sees no difference and concludes the flag does
    nothing.
    """
    if sheet_type == "packed" and not merge_duplicates:
        return [
            "A packed sheet merges identical frames whether or not merge_duplicates is "
            "set, because the packer reuses a rectangle it has already placed. This "
            "sheet is deduplicated; the flag only changes anything for the row and "
            "column layouts."
        ]
    return []



def _sprite_facts(src) -> dict:
    """Frame count, tag names and layer names, so an export can be checked before it runs."""
    body = """
    local spr = open_sprite(ARG.src)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})


def _frame_count(src) -> int:
    """From the file's header when it is an .aseprite, which costs a read rather than the
    launch `_sprite_facts` is; from that launch for anything else."""
    head = asefile.read_header(src)
    if head is not None:
        return head.frames
    return len(_sprite_facts(src).get("frames") or [])


def _require_frame(src, frame: int) -> int:
    """Aseprite silently exports a DIFFERENT frame when asked for one out of range.

    The old code clamped with max(0, frame-1) and then reported the requested number back,
    so export_png(frame=99) on a one-frame sprite wrote frame 1 and answered {"frame": 99}.
    """
    count = _frame_count(src)
    if not 1 <= int(frame) <= count:
        raise ExportError(
            f"frame {frame} does not exist; the sprite has {count} frame(s), numbered 1-{count}."
        )
    return int(frame)


def _canvas_of(src) -> tuple[int, int, int] | None:
    """(width, height, frames), from the header of an .aseprite and from Pillow for an
    image (which also runs the decompression-bomb guard), or None when neither can say."""
    head = asefile.read_header(src)
    if head is not None:
        return head.width, head.height, head.frames
    size = check_image_dimensions(str(src))
    return (size[0], size[1], 1) if size is not None else None


def _require_scale(scale: int, src=None, *, every_frame: bool = False) -> int:
    """A scale of at least 1, whose scaled image the canvas caps would allow.

    Nothing bounded the top: every export passed `scale` straight to Aseprite, so a 16x16
    sprite at scale 50000 asked for an 800,000-pixel-square image. Checked from the file's
    header before anything is launched, with the largest scale that fits named. A sheet
    holds `every_frame` at once, so its total is bounded as one sprite's storage is.
    """
    value = int(scale)
    if value < 1:
        raise ExportError(f"scale must be at least 1 (got {scale}).")
    canvas = _canvas_of(src) if src is not None else None
    if canvas is None:
        return value
    w, h, frames = canvas
    ow, oh = w * value, h * value
    count = max(1, frames) if every_frame else 1
    if (ow > MAX_CANVAS_DIMENSION or oh > MAX_CANVAS_DIMENSION
            or ow * oh > MAX_CANVAS_PIXELS or count * ow * oh > MAX_SPRITE_TOTAL_PIXELS):
        fit = 0
        for s in range(value - 1, 0, -1):
            sw, sh = w * s, h * s
            if (sw <= MAX_CANVAS_DIMENSION and sh <= MAX_CANVAS_DIMENSION
                    and sw * sh <= MAX_CANVAS_PIXELS and count * sw * sh <= MAX_SPRITE_TOTAL_PIXELS):
                fit = s
                break
        what = f"{count} frames of {ow}x{oh}" if count > 1 else f"a {ow}x{oh} image"
        remedy = (f"The largest scale that fits is {fit}." if fit
                  else "No scale fits; export a smaller sprite or fewer frames.")
        raise ExportError(
            f"a {w}x{h} sprite at scale {value} is {what}, past the caps "
            f"({MAX_CANVAS_DIMENSION} px per axis, {MAX_CANVAS_PIXELS} px per image, "
            f"{MAX_SPRITE_TOTAL_PIXELS} px in all). {remedy}"
        )
    return value


def _require_tag(src, tag: str) -> str:
    """An unknown --tag makes Aseprite export EVERY frame, and still exit 0."""
    names = [t.get("name") for t in (_sprite_facts(src).get("tags") or [])]
    if tag not in names:
        known = ", ".join(repr(n) for n in names) if names else "none"
        raise ExportError(f"no tag named {tag!r}; the sprite has: {known}.")
    return tag


def _unhonoured_tag_directions(src, only: str | None = None) -> list[str]:
    """Tag directions the exported file cannot represent.

    Aseprite stores a tag's direction in the .aseprite file, but GIF and sprite-sheet
    output are flat frame sequences with no notion of playback order, so a ping-pong
    tag exports as a plain forward run. A 4-frame ping-pong is 6 frames of playback and
    exports as 4. Saying nothing made the tool claim a loop it had not produced, so the
    exporters report this instead of leaving the caller to discover it in-engine.
    """
    notes = []
    for t in _sprite_facts(src).get("tags") or []:
        direction = (t.get("aniDir") or "forward").lower()
        if direction in ("forward", ""):
            continue
        name = t.get("name")
        if only is not None and name != only:
            continue
        notes.append(
            f"tag {name!r} is {direction}, which this format cannot express; "
            "the frames were written in forward order"
        )
    return notes


def _flat_layer_names(layers, out=None):
    out = [] if out is None else out
    for layer in layers or []:
        name = layer.get("name")
        if name:
            out.append(name)
        _flat_layer_names(layer.get("layers"), out)
    return out


def _require_layer(src, layer: str) -> str:
    """An unknown --layer exports the whole sprite instead, and still exits 0."""
    names = _flat_layer_names(_sprite_facts(src).get("layers"))
    if layer not in names:
        known = ", ".join(repr(n) for n in names) if names else "none"
        raise ExportError(f"no layer named {layer!r}; the sprite has: {known}.")
    return layer


def _verify_written(out, what: str = "export") -> int:
    """run_cli only raises on a non-zero exit, and Aseprite exits 0 for work it skipped."""
    if not out.exists():
        raise ExportError(f"{what} reported success but wrote nothing to {out}.")
    size = out.stat().st_size
    if size == 0:
        raise ExportError(f"{what} wrote an empty file to {out}.")
    return size


@mcp.tool()
def export_png(
    filename: str, output: str, frame: int = 1, scale: int = 1, overwrite: bool = False
) -> dict:
    """Export one frame as a flattened PNG.

    Args:
        output: Destination .png path.
        frame: Frame to export, 1-based (default 1).
        scale: Integer upscaling factor (default 1).
        overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    src = resolve_path(filename)
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    scale = _require_scale(scale, src)
    frame = _require_frame(src, frame)
    f0 = frame - 1
    run_cli([
        str(src),
        "--frame-range", f"{f0},{f0}",
        "--scale", str(scale),
        "--save-as", str(out),
    ])
    return {"ok": True, "output": str(out), "frame": frame, "scale": scale,
            "bytes": _verify_written(out, "export_png")}


@mcp.tool()
def export_gif(filename: str, output: str, scale: int = 1, overwrite: bool = False,
               loop: bool = True) -> dict:
    """Export the full animation as an animated GIF (honours frame durations).

    Tag *ranges* are honoured, but a tag's playback direction is not: a GIF is a flat
    frame sequence. A ping-pong tag exports forward, and the result says so in
    `warnings` rather than letting the caller find out in-engine.

    Args:
        overwrite: Replace `output` if it already exists (default False = no-clobber).
        loop: True (the default) repeats forever, which is what Aseprite writes and what
            a cycle wants. False plays the animation once and stops.

    `loop=False` is the one a one-shot needs, and there was no way to ask for it. An attack
    or a death is not a cycle: built from tags at `repeats=1`, with `validate_loop`
    confirming it does not close, it still exported as an endless loop that snapped from
    the recovery pose back to the wind-up. Set this and the result reports `loops`.
    """
    src = resolve_path(filename)
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    scale = _require_scale(scale, src)
    run_cli([str(src), "--scale", str(scale), "--save-as", str(out)])
    if not loop:
        # After the CLI has written it, because Aseprite has no flag for this and always
        # writes "repeat forever". Metadata only: every frame and delay is untouched.
        out.write_bytes(gifmeta.strip_loop(out.read_bytes()))
    result = {"ok": True, "output": str(out), "scale": scale, "loops": bool(loop),
              "bytes": _verify_written(out, "export_gif")}
    warnings = _unhonoured_tag_directions(src)
    if warnings:
        result["warnings"] = warnings
    return result


@mcp.tool()
def export_tag_gif(
    filename: str, tag: str, output: str, scale: int = 1, overwrite: bool = False
) -> dict:
    """Export only the frames of a named animation tag as an animated GIF.

    overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    src = resolve_path(filename)
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    tag = _require_tag(src, tag)
    scale = _require_scale(scale, src)
    run_cli([
        str(src),
        "--tag", tag,
        "--scale", str(scale),
        "--save-as", str(out),
    ])
    result = {"ok": True, "output": str(out), "tag": tag, "scale": scale,
              "bytes": _verify_written(out, "export_tag_gif")}
    warnings = _unhonoured_tag_directions(src, only=tag)
    if warnings:
        result["warnings"] = warnings
    return result


@mcp.tool()
def export_spritesheet(
    filename: str,
    output: str,
    sheet_type: str = "packed",
    scale: int = 1,
    data_output: str | None = None,
    padding: int = 0,
    layer: str | None = None,
    ignore_layer: str | None = None,
    split_layers: bool = False,
    split_tags: bool = False,
    overwrite: bool = False,
) -> dict:
    """Export frames into a single sprite-sheet image.

    Args:
        output: Destination sheet image (.png).
        sheet_type: one of horizontal, vertical, rows, columns, packed.
        scale: Integer upscaling factor.
        data_output: Optional .json path to also write frame/tag/slice metadata
            (JSON-array format) describing each frame's rectangle in the sheet.
        padding: Pixels of padding around/between frames.
        layer: Only include this layer.
        ignore_layer: Exclude this layer (e.g. a "reference" layer).
        split_layers: Lay out each layer as separate cels in the sheet.
        split_tags: Treat each tag as a separate set in the sheet.
        overwrite: Replace existing output(s) (default False = no-clobber). When
            data_output is given, both files are checked before anything is written.
    """
    if sheet_type not in _SHEET_TYPES:
        raise ValidationFailed(f"sheet_type must be one of {sorted(_SHEET_TYPES)}")
    src = resolve_path(filename)
    # Validate every target up front so a multi-file export fails before writing any file.
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    data_path = (
        ensure_output_path(data_output, overwrite=overwrite, error_type=ExportError)
        if data_output
        else None
    )
    cli = [
        str(src),
        "--sheet", str(out),
        "--sheet-type", sheet_type,
        "--scale", str(_require_scale(scale, src, every_frame=True)),
    ]
    if padding:
        cli += ["--shape-padding", str(int(padding)), "--border-padding", str(int(padding))]
    if layer:
        cli += ["--layer", _require_layer(src, layer)]
    if ignore_layer:
        cli += ["--ignore-layer", _require_layer(src, ignore_layer)]
    if split_layers:
        cli.append("--split-layers")
    if split_tags:
        cli.append("--split-tags")
    result = {"ok": True, "output": str(out), "sheet_type": sheet_type}
    if data_path is not None:
        cli += ["--data", str(data_path), "--format", "json-array", "--list-tags", "--list-slices"]
        result["data_output"] = str(data_path)
    run_cli(cli)
    result["bytes"] = _verify_written(out, "export_spritesheet")
    return result


@mcp.tool()
def export_spritesheet_packed(
    filename: str,
    output: str,
    sheet_type: str = "packed",
    trim: bool = False,
    extrude: bool = False,
    merge_duplicates: bool = False,
    padding: int = 0,
    data_output: str | None = None,
    data_format: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Export a sprite sheet with the controls a game engine needs: extrude, dedupe, trim.

    The sibling of `export_spritesheet`, which goes through the Aseprite CLI. This one
    drives the editor's own export command, which the CLI flags do not fully reach, and
    adds three things that matter when the sheet is going into an engine rather than into
    a preview:

    Args:
        output: Destination sheet image (.png).
        sheet_type: one of horizontal, vertical, rows, columns, packed (the default).
        trim: Trim each frame to its drawn pixels before packing, so empty margins cost
            no sheet space. The frame rectangles in the data file say where each frame
            went and how much was trimmed, so an engine can still place it correctly.
        extrude: Duplicate each frame's edge pixels one pixel outwards around its cell.
            This is the fix for the thin seam or transparent line that appears between
            tiles in Unity, Godot or a shader at non-integer zoom: the sampler reads
            half a texel past the frame's edge, and without extrude that is whatever the
            neighbouring frame or empty space holds. The frame rectangle in the data file
            still names the frame itself, not the border.
        merge_duplicates: Give identical frames one rectangle in the sheet instead of a
            copy each, which is what shrinks a sheet full of held poses. Identical by
            pixels, so it catches both a duplicated frame and a linked cel. A packed
            sheet does this anyway and the result says so.
        padding: Pixels of padding around and between frames, as `export_spritesheet`.
            Padding separates frames; extrude fills the gap at the frame's own edge.
            They solve different halves of the same bleeding problem and compose.
        data_output: Optional .json path for the sheet metadata, which also carries the
            layer, tag and slice lists.
        data_format: "json-array" (the default when `data_output` is given) or
            "json-hash". The array form lists frames in order, which an engine indexing
            by frame number wants; the hash form keys them by name, which a loader
            looking frames up by name wants. The tag section is called `frameTags` in
            both.
        overwrite: Replace existing output(s) (default False = no-clobber). When
            `data_output` is given, both files are checked before anything is written.

    The source sprite is not modified: verified, the file's bytes and frame count are the
    same afterwards, including with trim and extrude set.
    """
    if sheet_type not in _SHEET_TYPES:
        raise ValidationFailed(f"sheet_type must be one of {sorted(_SHEET_TYPES)}")
    if data_format is not None and data_format not in _DATA_FORMATS:
        raise ValidationFailed(f"data_format must be one of {sorted(_DATA_FORMATS)}")
    if data_format is not None and not data_output:
        raise ValidationFailed(
            "data_format only applies to data_output, and no data_output was given, so "
            "nothing would be written in that format."
        )
    if padding < 0:
        raise ValidationFailed(f"padding cannot be negative (got {padding}).")

    src = resolve_path(filename)
    # Every target is validated before anything runs, so a two-file export cannot fail
    # halfway and leave one of them behind.
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    data_path = (
        ensure_output_path(data_output, overwrite=overwrite, error_type=ExportError)
        if data_output
        else None
    )
    args = {
        "src": lua_path(src),
        "output": lua_path(out),
        "sheet_type": sheet_type,
        "trim": bool(trim),
        "extrude": bool(extrude),
        "merge_duplicates": bool(merge_duplicates),
        "padding": int(padding),
        "data_output": lua_path(data_path) if data_path is not None else None,
        "data_format": (data_format or "json-array") if data_path is not None else None,
    }
    body = """
    -- Mapped to the editor's own enums rather than passed through as strings. The command
    -- accepts `type = "no-such-type"` without a word and exports in its default layout,
    -- so a typo anywhere on this path would otherwise produce a sheet in a layout nobody
    -- asked for and report success. Python has already checked the name; this is the half
    -- of the check that cannot drift from the enum.
    local SHEET_TYPES = {
      horizontal = SpriteSheetType.HORIZONTAL,
      vertical = SpriteSheetType.VERTICAL,
      rows = SpriteSheetType.ROWS,
      columns = SpriteSheetType.COLUMNS,
      packed = SpriteSheetType.PACKED,
    }
    local DATA_FORMATS = {
      ["json-array"] = SpriteSheetDataFormat.JSON_ARRAY,
      ["json-hash"] = SpriteSheetDataFormat.JSON_HASH,
    }
    local kind = SHEET_TYPES[ARG.sheet_type]
    if kind == nil then error("unknown sheet_type '" .. tostring(ARG.sheet_type) .. "'", 0) end

    local spr = open_sprite(ARG.src)
    local params = {
      ui = false,
      type = kind,
      textureFilename = ARG.output,
      trim = ARG.trim,
      extrude = ARG.extrude,
      mergeDuplicates = ARG.merge_duplicates,
    }
    if ARG.padding > 0 then
      params.shapePadding = ARG.padding
      params.borderPadding = ARG.padding
    end
    if ARG.data_output ~= nil then
      local fmt = DATA_FORMATS[ARG.data_format]
      if fmt == nil then
        error("unknown data_format '" .. tostring(ARG.data_format) .. "'", 0)
      end
      params.dataFilename = ARG.data_output
      params.dataFormat = fmt
      -- The three sections that make the data file worth writing: without them it
      -- describes rectangles and nothing about what is in them.
      params.listLayers = true
      params.listTags = true
      params.listSlices = true
    end
    app.command.ExportSpriteSheet(params)

    -- Measured off the written file rather than computed from the layout: the sheet's
    -- size is the one fact a caller cannot work out for themselves, and it is how the
    -- effect of trim, padding and extrude becomes visible at all. Deliberately no
    -- save_sprite: the export does not modify the sprite and saving it would rewrite a
    -- file the caller did not ask to have touched.
    RESULT = { ok = true, frames = #spr.frames }
    if app.fs.isFile(ARG.output) then
      local sheet = app.open(ARG.output)
      RESULT.sheet_size = { width = sheet.width, height = sheet.height }
    end
    """
    result = run_lua(body, args)
    result.update({
        "output": str(out),
        "sheet_type": sheet_type,
        "trim": bool(trim),
        "extrude": bool(extrude),
        "merge_duplicates": bool(merge_duplicates),
        # run_cli is not involved here, so the "exited 0 having done nothing" check that
        # `run_cli` makes has to be made again: the command returns before the file is
        # verified and would report success for a sheet it never wrote.
        "bytes": _verify_written(out, "export_spritesheet_packed"),
    })
    if data_path is not None:
        result["data_output"] = str(data_path)
        result["data_format"] = data_format or "json-array"
        result["data_bytes"] = _verify_written(data_path, "export_spritesheet_packed data")
    notes = _packed_sheet_notes(sheet_type, bool(merge_duplicates))
    if notes:
        result["warnings"] = notes
    return result


@mcp.tool()
def export_layer(
    filename: str,
    layer: str,
    output: str,
    frame: int = 1,
    scale: int = 1,
    overwrite: bool = False,
) -> dict:
    """Export a single layer of one frame as a PNG (others excluded).

    overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    src = resolve_path(filename)
    # Both halves are needed: no-clobber on the destination, and validation of the
    # arguments. Clamping was the old behaviour on this path (max(0, frame - 1) and
    # max(1, scale)), which let export_layer(frame=99) on a one-frame sprite report
    # {"ok": true, "frame": 99} while writing frame 1. The _require_* helpers raise
    # instead, so the returned values are the ones actually used.
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    layer = _require_layer(src, layer)
    scale = _require_scale(scale, src)
    frame = _require_frame(src, frame)
    run_cli([
        str(src), "--layer", layer,
        "--frame-range", f"{frame - 1},{frame - 1}",
        "--scale", str(scale),
        "--save-as", str(out),
    ])
    return {"ok": True, "output": str(out), "layer": layer, "frame": frame, "scale": scale,
            "bytes": _verify_written(out, "export_layer")}


@mcp.tool()
def export_layers(
    filename: str,
    output_pattern: str,
    scale: int = 1,
    include_hidden: bool = False,
    overwrite: bool = False,
) -> dict:
    """Export each layer to its own image file.

    output_pattern must contain "{layer}" (e.g. "layers/{layer}.png"); add
    "{frame}" too for animations. include_hidden also exports hidden layers.

    overwrite: Replace files the pattern would expand onto (default False =
    no-clobber). Aseprite expands the placeholders, so the check refuses when any
    file matching the pattern already exists.
    """
    if "{layer}" not in output_pattern:
        raise ValidationFailed('output_pattern must contain "{layer}".')
    src = resolve_path(filename)
    out = ensure_output_pattern(output_pattern, overwrite=overwrite, error_type=ExportError)
    cli = [str(src), "--split-layers", "--scale", str(_require_scale(scale, src))]
    if include_hidden:
        cli.append("--all-layers")
    cli += ["--save-as", str(out)]
    run_cli(cli)
    return {"ok": True, "output_pattern": str(out)}


@mcp.tool()
def export_tags(
    filename: str, output_pattern: str, scale: int = 1, overwrite: bool = False
) -> dict:
    """Export each animation tag's frames to their own files.

    output_pattern must contain "{tag}" (and usually "{frame}"),
    e.g. "anim/{tag}_{frame}.png".

    overwrite: Replace files the pattern would expand onto (default False = no-clobber).
    """
    if "{tag}" not in output_pattern:
        raise ValidationFailed('output_pattern must contain "{tag}".')
    src = resolve_path(filename)
    out = ensure_output_pattern(output_pattern, overwrite=overwrite, error_type=ExportError)
    run_cli([
        str(src), "--split-tags",
        "--scale", str(_require_scale(scale, src)),
        "--save-as", str(out),
    ])
    return {"ok": True, "output_pattern": str(out)}


@mcp.tool()
def export_onion_skin(
    filename: str,
    frame: int,
    output: str,
    previous: int = 2,
    next: int = 0,
    ghost_opacity: int = 80,
    scale: int = 4,
    overwrite: bool = False,
) -> dict:
    """Export a frame with neighbouring frames ghosted behind it (onion skin).

    Args:
        frame: The in-focus frame (drawn fully opaque), 1-based.
        previous, next: How many earlier/later frames to ghost.
        ghost_opacity: Max opacity (0-255) of the nearest ghost; further frames fade.
        scale: Integer upscaling factor for the output PNG.
        overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    src = resolve_path(filename)
    scale = _require_scale(scale, src)
    out_path = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    args = {
        "src": lua_path(src),
        "output": lua_path(out_path),
        "frame": int(frame),
        "previous": max(0, int(previous)),
        "next": max(0, int(next)),
        "ghost_opacity": max(0, min(255, int(ghost_opacity))),
        "scale": scale,
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local cur = require_frame(spr, ARG.frame, "frame")
    local W, H = spr.width, spr.height
    local out = Image(ImageSpec{ width = W, height = H, colorMode = ColorMode.RGB })
    out:clear()
    local function ghost(f, op)
      if f < 1 or f > #spr.frames or op <= 0 then return end
      local g = Image(ImageSpec{ width = W, height = H, colorMode = ColorMode.RGB })
      g:clear(); g:drawSprite(spr, f)
      out:drawImage(g, Point(0, 0), op, BlendMode.NORMAL)
    end
    for k = ARG.previous, 1, -1 do
      ghost(cur - k, math.floor(ARG.ghost_opacity * (ARG.previous - k + 1) / (ARG.previous + 1)))
    end
    for k = 1, ARG.next do
      ghost(cur + k, math.floor(ARG.ghost_opacity * (ARG.next - k + 1) / (ARG.next + 1)))
    end
    local c = Image(ImageSpec{ width = W, height = H, colorMode = ColorMode.RGB })
    c:clear(); c:drawSprite(spr, cur)
    out:drawImage(c, Point(0, 0), 255, BlendMode.NORMAL)

    local osp = Sprite(W, H, ColorMode.RGB)
    osp.cels[1].image = out
    app.sprite = osp
    if ARG.scale > 1 then
      app.command.SpriteSize{ ui = false, width = W * ARG.scale, height = H * ARG.scale, method = "nearest" }
    end
    osp:saveAs(ARG.output)
    RESULT = { ok = true, output = ARG.output, frame = cur }
    """
    return run_lua(body, args)


@mcp.tool()
def export_motion_trail(
    filename: str,
    output: str,
    tag: str | None = None,
    frames: list[int] | None = None,
    scale: int = 6,
    overwrite: bool = False,
) -> dict:
    """Export every frame of a motion composited into one image, the oldest faintest.

    The way to judge whether a whole motion reads: arc shape, spacing and squash are all
    visible at once in a still image that can be studied, where a GIF moves on before a
    defect can be seen, and `export_onion_skin` shows only a few frames either side of one.

    Args:
        filename: The sprite.
        output: The image to write. Use .png: the fades are alpha, which a GIF cannot keep.
        tag: Composite this tag's frames.
        frames: Or these frames (1-based), in the order given. Pass neither for every
            frame of the sprite, and not both.
        scale: Integer upscaling of the output (default 6). The scaled image is held to
            the same caps as any canvas.
        overwrite: Replace `output` if it already exists (default False = no-clobber).

    Frame i of n is drawn at opacity 255 * i / n, so the last is fully opaque and on top.
    An opaque Background layer would bury every frame under the next, so when there is one
    it is drawn once, as of the last frame, and the frames contribute their other layers.

    Returns the frames used, the opacity each was drawn at, and whether a Background was
    laid underneath.
    """
    if tag is not None and frames is not None:
        raise ValidationFailed("pass tag or frames, not both: they name the same thing twice.")
    frame_list = None
    if frames is not None:
        if not frames:
            raise ValidationFailed("frames is empty; pass at least one frame, or omit it "
                                   "for every frame of the sprite.")
        check_list_length("frames", frames, MAX_MOTION_FRAMES,
                          remedy="Composite a shorter stretch, or a tag.")
        frame_list = [FrameRef.arg(f"frames[{i}]", f) for i, f in enumerate(frames, 1)]
    scale = check_count("scale", scale, MAX_CANVAS_DIMENSION, minimum=1)
    src = resolve_path(filename)
    # From the header, before the launch; the Lua check below is the backstop for a
    # source whose header cannot be read.
    scale = _require_scale(scale, src)
    out_path = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    args = {
        "src": lua_path(src),
        "output": lua_path(out_path),
        "tag": tag,
        "frames": frame_list,
        "scale": scale,
        "max_dimension": MAX_CANVAS_DIMENSION,
        "max_pixels": MAX_CANVAS_PIXELS,
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local list = {}
    if ARG.tag ~= nil then
      local found, names = nil, {}
      for _, t in ipairs(spr.tags) do
        names[#names + 1] = t.name
        if t.name == ARG.tag then found = t end
      end
      if found == nil then
        error("the sprite has no tag named '" .. ARG.tag .. "'; its tags are: " ..
              (#names > 0 and table.concat(names, ", ") or "none") .. ".", 0)
      end
      for f = found.fromFrame.frameNumber, found.toFrame.frameNumber do list[#list + 1] = f end
    elseif ARG.frames ~= nil then
      for i, f in ipairs(ARG.frames) do list[i] = require_frame(spr, f, "frames[" .. i .. "]") end
    else
      for f = 1, #spr.frames do list[f] = f end
    end

    local W, H = spr.width, spr.height
    local OW, OH = W * ARG.scale, H * ARG.scale
    if OW > ARG.max_dimension or OH > ARG.max_dimension or OW * OH > ARG.max_pixels then
      error(string.format("a %dx%d sprite at scale %d is a %dx%d image, past the canvas " ..
            "caps (%d px per axis, %d px in all). Use a smaller scale.",
            W, H, ARG.scale, OW, OH, ARG.max_dimension, ARG.max_pixels), 0)
    end

    -- The Background, if a visible one exists, is laid once underneath and kept out of the
    -- frames: every frame of an opaque sprite is opaque, so the last one, drawn at full
    -- opacity, would otherwise cover the whole trail. Its visibility is changed in memory
    -- only; this sprite is never saved.
    local bg = nil
    for _, lyr in ipairs(spr.layers) do
      if lyr.isBackground and lyr.isVisible then bg = lyr end
    end
    local out = Image(W, H, ColorMode.RGB)
    out:clear()
    if bg ~= nil then
      local shown = {}
      for _, lyr in ipairs(spr.layers) do
        if not lyr.isBackground and lyr.isVisible then
          lyr.isVisible = false
          shown[#shown + 1] = lyr
        end
      end
      local base = Image(W, H, ColorMode.RGB)
      base:clear()
      base:drawSprite(spr, list[#list])
      out:drawImage(base, Point(0, 0), 255, BlendMode.NORMAL)
      for _, lyr in ipairs(shown) do lyr.isVisible = true end
      bg.isVisible = false
    end

    local opacities = {}
    for i, f in ipairs(list) do
      local op = math.floor(255 * i / #list + 0.5)
      local img = Image(W, H, ColorMode.RGB)
      img:clear()
      img:drawSprite(spr, f)
      out:drawImage(img, Point(0, 0), op, BlendMode.NORMAL)
      opacities[i] = op
    end
    if bg ~= nil then bg.isVisible = true end

    local osp = Sprite(W, H, ColorMode.RGB)
    osp.cels[1].image = out
    app.sprite = osp
    if ARG.scale > 1 then
      app.command.SpriteSize{ ui = false, width = OW, height = OH, method = "nearest" }
    end
    osp:saveAs(ARG.output)
    RESULT = { ok = true, output = ARG.output, frames = list, opacities = opacities,
               background = (bg ~= nil), width = OW, height = OH }
    """
    return run_lua(body, args)


@mcp.tool()
def export_frames(
    filename: str, output_pattern: str, scale: int = 1, overwrite: bool = False
) -> dict:
    """Export each frame to its own image file.

    output_pattern must contain "{frame}" (and optionally "{tag}", "{layer}"),
    e.g. "frames/walk_{frame}.png". Aseprite substitutes the values.

    overwrite: Replace files the pattern would expand onto (default False = no-clobber).
    """
    if "{frame}" not in output_pattern:
        raise ValidationFailed('output_pattern must contain "{frame}", e.g. "out_{frame}.png".')
    src = resolve_path(filename)
    out = ensure_output_pattern(output_pattern, overwrite=overwrite, error_type=ExportError)
    run_cli([str(src), "--scale", str(_require_scale(scale, src)), "--save-as", str(out)])
    return {"ok": True, "output_pattern": str(out), "scale": int(scale)}


@mcp.tool()
def import_image(input_image: str, output: str, overwrite: bool = False) -> dict:
    """Create an editable .aseprite sprite from a flat image (.png/.bmp/.jpg/...).

    Args:
        input_image: Source raster image.
        output: Destination .aseprite path.
        overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    src = resolve_path(input_image)
    # The decompression-bomb guard the stamping tools run, before anything is launched or
    # created: a solid-colour PNG a few kilobytes on disk can declare 16384x16384, which
    # Aseprite allocates the moment it opens the file.
    check_image_dimensions(str(src))
    dst = ensure_output_path(output, overwrite=overwrite)
    # This writes a sprite, so unlike every other tool in this module it has to forget any
    # selection sitting beside that path. None of the exports may: `with_suffix` maps
    # `hero.png` and `hero.aseprite` onto the same `hero.msk`, so an export doing this
    # would throw away the selection of the sprite it was exporting.
    discard_selection_sidecar(dst)
    args = {
        "src": lua_path(src),
        "dst": lua_path(dst),
    }
    body = """
    local spr = open_sprite(ARG.src)
    spr:saveAs(ARG.dst)
    RESULT = sprite_info(spr)
    """
    info = run_lua(body, args)
    info["path"] = str(dst)
    return info
