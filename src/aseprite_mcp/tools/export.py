"""Export & import: PNG, animated GIF, sprite sheets, per-frame images, import.

These use the Aseprite CLI directly (rich export flags). Output paths follow the
same workspace rules as everything else.
"""

from __future__ import annotations

from ..app import mcp
from ..core.errors import ExportError, ValidationFailed
from ..core.models import FRAME_GUARD_LUA
from ..core.paths import ensure_output_path, ensure_output_pattern
from ..core.runner import run_cli, run_lua
from .common import lua_path, resolve_path

_SHEET_TYPES = {"horizontal", "vertical", "rows", "columns", "packed"}



def _sprite_facts(src) -> dict:
    """Frame count, tag names and layer names, so an export can be checked before it runs."""
    body = """
    local spr = open_sprite(ARG.src)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, {"src": lua_path(src)})


def _require_frame(src, frame: int) -> int:
    """Aseprite silently exports a DIFFERENT frame when asked for one out of range.

    The old code clamped with max(0, frame-1) and then reported the requested number back,
    so export_png(frame=99) on a one-frame sprite wrote frame 1 and answered {"frame": 99}.
    """
    count = len(_sprite_facts(src).get("frames") or [])
    if not 1 <= int(frame) <= count:
        raise ExportError(
            f"frame {frame} does not exist; the sprite has {count} frame(s), numbered 1-{count}."
        )
    return int(frame)


def _require_scale(scale: int) -> int:
    value = int(scale)
    if value < 1:
        raise ExportError(f"scale must be at least 1 (got {scale}).")
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
    frame = _require_frame(src, frame)
    scale = _require_scale(scale)
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
def export_gif(filename: str, output: str, scale: int = 1, overwrite: bool = False) -> dict:
    """Export the full animation as an animated GIF (honours frame durations).

    Tag *ranges* are honoured, but a tag's playback direction is not: a GIF is a flat
    frame sequence. A ping-pong tag exports forward, and the result says so in
    `warnings` rather than letting the caller find out in-engine.

    overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    src = resolve_path(filename)
    out = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    scale = _require_scale(scale)
    run_cli([str(src), "--scale", str(scale), "--save-as", str(out)])
    result = {"ok": True, "output": str(out), "scale": scale,
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
    scale = _require_scale(scale)
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
        "--scale", str(_require_scale(scale)),
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
    frame = _require_frame(src, frame)
    scale = _require_scale(scale)
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
    cli = [str(src), "--split-layers", "--scale", str(max(1, int(scale)))]
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
        "--scale", str(max(1, int(scale))),
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
    out_path = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    args = {
        "src": lua_path(resolve_path(filename)),
        "output": lua_path(out_path),
        "frame": int(frame),
        "previous": max(0, int(previous)),
        "next": max(0, int(next)),
        "ghost_opacity": max(0, min(255, int(ghost_opacity))),
        "scale": max(1, int(scale)),
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
    run_cli([str(src), "--scale", str(max(1, int(scale))), "--save-as", str(out)])
    return {"ok": True, "output_pattern": str(out), "scale": int(scale)}


@mcp.tool()
def import_image(input_image: str, output: str, overwrite: bool = False) -> dict:
    """Create an editable .aseprite sprite from a flat image (.png/.bmp/.jpg/...).

    Args:
        input_image: Source raster image.
        output: Destination .aseprite path.
        overwrite: Replace `output` if it already exists (default False = no-clobber).
    """
    dst = ensure_output_path(output, overwrite=overwrite)
    args = {
        "src": lua_path(resolve_path(input_image)),
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
