"""Export & import: PNG, animated GIF, sprite sheets, per-frame images, import.

These use the Aseprite CLI directly (rich export flags). Output paths follow the
same workspace rules as everything else.
"""

from __future__ import annotations

from ..app import mcp
from ..runner import run_cli, run_lua
from .common import lua_path, resolve_path

_SHEET_TYPES = {"horizontal", "vertical", "rows", "columns", "packed"}


@mcp.tool()
def export_png(filename: str, output: str, frame: int = 1, scale: int = 1) -> dict:
    """Export one frame as a flattened PNG.

    Args:
        output: Destination .png path.
        frame: Frame to export, 1-based (default 1).
        scale: Integer upscaling factor (default 1).
    """
    src = resolve_path(filename)
    out = resolve_path(output)
    f0 = max(0, int(frame) - 1)
    run_cli([
        str(src),
        "--frame-range", f"{f0},{f0}",
        "--scale", str(max(1, int(scale))),
        "--save-as", str(out),
    ])
    return {"ok": True, "output": str(out), "frame": int(frame), "scale": int(scale)}


@mcp.tool()
def export_gif(filename: str, output: str, scale: int = 1) -> dict:
    """Export the full animation as an animated GIF (honours frame durations & tags)."""
    src = resolve_path(filename)
    out = resolve_path(output)
    run_cli([str(src), "--scale", str(max(1, int(scale))), "--save-as", str(out)])
    return {"ok": True, "output": str(out), "scale": int(scale)}


@mcp.tool()
def export_tag_gif(filename: str, tag: str, output: str, scale: int = 1) -> dict:
    """Export only the frames of a named animation tag as an animated GIF."""
    src = resolve_path(filename)
    out = resolve_path(output)
    run_cli([
        str(src),
        "--tag", tag,
        "--scale", str(max(1, int(scale))),
        "--save-as", str(out),
    ])
    return {"ok": True, "output": str(out), "tag": tag, "scale": int(scale)}


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
    """
    if sheet_type not in _SHEET_TYPES:
        raise ValueError(f"sheet_type must be one of {sorted(_SHEET_TYPES)}")
    src = resolve_path(filename)
    out = resolve_path(output)
    cli = [
        str(src),
        "--sheet", str(out),
        "--sheet-type", sheet_type,
        "--scale", str(max(1, int(scale))),
    ]
    if padding:
        cli += ["--shape-padding", str(int(padding)), "--border-padding", str(int(padding))]
    if layer:
        cli += ["--layer", layer]
    if ignore_layer:
        cli += ["--ignore-layer", ignore_layer]
    if split_layers:
        cli.append("--split-layers")
    if split_tags:
        cli.append("--split-tags")
    result = {"ok": True, "output": str(out), "sheet_type": sheet_type}
    if data_output:
        data_path = resolve_path(data_output)
        cli += ["--data", str(data_path), "--format", "json-array", "--list-tags", "--list-slices"]
        result["data_output"] = str(data_path)
    run_cli(cli)
    return result


@mcp.tool()
def export_layer(filename: str, layer: str, output: str, frame: int = 1, scale: int = 1) -> dict:
    """Export a single layer of one frame as a PNG (others excluded)."""
    src = resolve_path(filename)
    out = resolve_path(output)
    f0 = max(0, int(frame) - 1)
    run_cli([
        str(src), "--layer", layer,
        "--frame-range", f"{f0},{f0}",
        "--scale", str(max(1, int(scale))),
        "--save-as", str(out),
    ])
    return {"ok": True, "output": str(out), "layer": layer, "frame": int(frame)}


@mcp.tool()
def export_layers(
    filename: str, output_pattern: str, scale: int = 1, include_hidden: bool = False
) -> dict:
    """Export each layer to its own image file.

    output_pattern must contain "{layer}" (e.g. "layers/{layer}.png"); add
    "{frame}" too for animations. include_hidden also exports hidden layers.
    """
    if "{layer}" not in output_pattern:
        raise ValueError('output_pattern must contain "{layer}".')
    src = resolve_path(filename)
    out = resolve_path(output_pattern)
    cli = [str(src), "--split-layers", "--scale", str(max(1, int(scale)))]
    if include_hidden:
        cli.append("--all-layers")
    cli += ["--save-as", str(out)]
    run_cli(cli)
    return {"ok": True, "output_pattern": str(out)}


@mcp.tool()
def export_tags(filename: str, output_pattern: str, scale: int = 1) -> dict:
    """Export each animation tag's frames to their own files.

    output_pattern must contain "{tag}" (and usually "{frame}"),
    e.g. "anim/{tag}_{frame}.png".
    """
    if "{tag}" not in output_pattern:
        raise ValueError('output_pattern must contain "{tag}".')
    src = resolve_path(filename)
    out = resolve_path(output_pattern)
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
) -> dict:
    """Export a frame with neighbouring frames ghosted behind it (onion skin).

    Args:
        frame: The in-focus frame (drawn fully opaque), 1-based.
        previous, next: How many earlier/later frames to ghost.
        ghost_opacity: Max opacity (0-255) of the nearest ghost; further frames fade.
        scale: Integer upscaling factor for the output PNG.
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "output": lua_path(resolve_path(output)),
        "frame": int(frame),
        "previous": max(0, int(previous)),
        "next": max(0, int(next)),
        "ghost_opacity": max(0, min(255, int(ghost_opacity))),
        "scale": max(1, int(scale)),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local cur = clamp_frame(spr, ARG.frame)
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
def export_frames(filename: str, output_pattern: str, scale: int = 1) -> dict:
    """Export each frame to its own image file.

    output_pattern must contain "{frame}" (and optionally "{tag}", "{layer}"),
    e.g. "frames/walk_{frame}.png". Aseprite substitutes the values.
    """
    if "{frame}" not in output_pattern:
        raise ValueError('output_pattern must contain "{frame}", e.g. "out_{frame}.png".')
    src = resolve_path(filename)
    out = resolve_path(output_pattern)
    run_cli([str(src), "--scale", str(max(1, int(scale))), "--save-as", str(out)])
    return {"ok": True, "output_pattern": str(out), "scale": int(scale)}


@mcp.tool()
def import_image(input_image: str, output: str) -> dict:
    """Create an editable .aseprite sprite from a flat image (.png/.bmp/.jpg/...).

    Args:
        input_image: Source raster image.
        output: Destination .aseprite path.
    """
    args = {
        "src": lua_path(resolve_path(input_image)),
        "dst": lua_path(resolve_path(output)),
    }
    body = """
    local spr = open_sprite(ARG.src)
    spr:saveAs(ARG.dst)
    RESULT = sprite_info(spr)
    """
    info = run_lua(body, args)
    info["path"] = str(resolve_path(output))
    return info
