"""Workflow-level tools — agent-friendly asset scaffolding.

These compose the low-level tools into one-call workflows that produce game-ready
asset scaffolds, and return a structured *manifest* (created files, paths, frames,
tags, dimensions, and suggested next actions) so an agent can keep going.

They are deterministic scaffolding — no AI/model generation. Build on top of them
with the low-level drawing/effects/tilemap tools.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..app import mcp
from ..runner import AsepriteError
from . import (
    cels,
    drawing,
    effects,
    export,
    frames,
    inspect,
    layers,
    palette,
    slices,
    sprite,
    tags,
    tilemap,
    validation,
)
from .common import resolve_path
from .manifest import export_entry, file_entry, sprite_summary, workflow_manifest


def _aseprite_name(name: str) -> str:
    return name if name.lower().endswith((".aseprite", ".ase")) else f"{name}.aseprite"


@mcp.tool()
def create_character_sprite(
    name: str,
    width: int = 32,
    height: int = 32,
    base_color: str = "#3878c8",
    with_placeholder: bool = True,
) -> dict:
    """Scaffold a character sprite project: a transparent canvas with a tidy layer
    stack (body + details), an auto-generated shading palette ramp from `base_color`,
    and (optionally) an outlined placeholder body to draw over.

    Returns a ``workflow_manifest.v1`` manifest (sprite summary, created files,
    palette, and suggested next actions).
    """
    filename = _aseprite_name(name)
    sprite.create_sprite(filename, width, height, "rgb")
    layers.rename_layer(filename, "Layer 1", "body")
    layers.add_layer(filename, "details")

    ramp = palette.generate_ramp(base_color, steps=5, hue_shift=30, light_range=0.6)["colors"]
    palette.set_palette(filename, ramp)

    if with_placeholder:
        cx, cy = width // 2, height // 2
        rx, ry = max(2, width // 3), max(2, height // 3)
        drawing.draw_ellipse(filename, cx, cy, rx, ry, ramp[2], filled=True, layer="body")
        effects.add_outline(filename, ramp[0], thickness=1, where="outside", layer="body")

    final = inspect.get_sprite_info(filename)
    return workflow_manifest(
        "character_sprite",
        sprite=sprite_summary(final),
        created_files=[file_entry("source_sprite", final["path"], "aseprite")],
        palette={"colors": ramp, "count": len(ramp)},
        suggested_next_actions=[
            f"Draw the character on the 'body' layer with the palette shades {ramp}.",
            "Add a face/features on the 'details' layer.",
            f"Animate it: make_4_frame_idle_animation('{filename}').",
            f"Preview with render_preview('{filename}').",
        ],
    )


@mcp.tool()
def make_4_frame_idle_animation(
    filename: str,
    layer: str = "body",
    frame_duration_ms: int = 150,
    bob_pixels: int = 1,
    tag_name: str = "idle",
) -> dict:
    """Turn a single-frame sprite into a 4-frame idle "bob" loop.

    Duplicates frame 1 to 4 frames, nudges `layer` down by `bob_pixels` on frames 2
    and 4 for a subtle bob, sets uniform durations, and adds a looping tag.

    Returns a ``workflow_manifest.v1`` manifest (sprite summary + animation block).
    """
    info = inspect.get_sprite_info(filename)
    while info["frameCount"] < 4:
        frames.add_frame(filename, frame_duration_ms, copy_from=1)
        info = inspect.get_sprite_info(filename)

    # Bob the layer down on the off-beats; cels default to (0,0).
    for fr in (2, 4):
        cels.set_cel_position(filename, layer, fr, 0, bob_pixels)

    frames.set_all_frame_durations(filename, frame_duration_ms)
    tags.add_tag(filename, tag_name, 1, 4, "forward")

    final = inspect.get_sprite_info(filename)
    return workflow_manifest(
        "idle_animation",
        sprite=sprite_summary(final),
        created_files=[file_entry("source_sprite", final["path"], "aseprite")],
        animation={
            "tag": tag_name,
            "frames": list(range(1, final["frameCount"] + 1)),
            "duration_ms": frame_duration_ms,
            "bob_pixels": bob_pixels,
            "animated_layer": layer,
        },
        suggested_next_actions=[
            f"Preview the loop: render_preview('{filename}', frame=2).",
            f"Export it: export_gif('{filename}', '{Path(filename).stem}.gif', scale=8).",
            "Add more poses with draw_* tools per frame, or another tag for 'walk'.",
        ],
    )


_DEFAULT_TILES = [
    {"name": "grass", "color": "#5ac54f"},
    {"name": "dirt", "color": "#a05b53"},
    {"name": "water", "color": "#3978a8"},
    {"name": "stone", "color": "#94b0c2"},
]


@mcp.tool()
def create_tileset_project(
    name: str,
    tile_size: int = 16,
    columns: int = 4,
    rows: int = 4,
    tiles: list[dict] | None = None,
) -> dict:
    """Scaffold a tilemap project: a canvas sized columns×rows tiles, a tilemap layer,
    and a starter tileset (grass/dirt/water/stone by default, or your own
    [{"name","color"}] list). The grid is filled with the first tile to start.

    Returns a ``workflow_manifest.v1`` manifest with a tilemap block mapping tile
    names to their tileset indices.
    """
    tile_defs = tiles or _DEFAULT_TILES
    if not tile_defs:
        raise ValueError("tiles must be non-empty when provided.")
    filename = _aseprite_name(name)
    sprite.create_sprite(filename, columns * tile_size, rows * tile_size, "rgb")
    tilemap.create_tilemap_layer(filename, "tiles", tile_size, tile_size, columns, rows)

    created = []
    for td in tile_defs:
        out = tilemap.add_tile(filename, "tiles", td["color"])
        created.append({"name": td.get("name", f"tile{out['index']}"),
                        "index": out["index"], "color": td["color"]})
    if created:
        tilemap.fill_tilemap(filename, "tiles", created[0]["index"])

    final = inspect.get_sprite_info(filename)
    return workflow_manifest(
        "tileset_project",
        sprite=sprite_summary(final),
        created_files=[file_entry("source_sprite", final["path"], "aseprite")],
        tilemap={
            "layer": "tiles",
            "tile_width": tile_size,
            "tile_height": tile_size,
            "grid": {"columns": columns, "rows": rows},
            "tiles": created,
        },
        suggested_next_actions=[
            "Paint detail into tiles with paint_tile_pixels(filename, 'tiles', <index>, [...]).",
            "Lay out the map with set_tiles(filename, 'tiles', [{'column','row','index'}, ...]).",
            "Read it back with get_tilemap(filename, 'tiles').",
        ],
    )


@mcp.tool()
def export_game_asset_bundle(
    filename: str,
    bundle_name: str | None = None,
    scale: int = 1,
) -> dict:
    """Export a sprite into a game-ready bundle directory: a flattened PNG, an animated
    GIF, a packed sprite sheet (+ JSON data), a GIF per animation tag, and a
    `manifest.json` describing everything.

    Returns a ``workflow_manifest.v1`` manifest (the same object is also written to
    disk as manifest.json inside the bundle).
    """
    info = inspect.get_sprite_info(filename)
    base = Path(filename).stem
    bundle = bundle_name or f"{base}_bundle"

    def rel(p: str) -> str:
        return f"{bundle}/{p}"

    exports = [
        export_entry("png", export.export_png(filename, rel(f"{base}.png"), 1, scale)["output"], "png"),
        export_entry("gif", export.export_gif(filename, rel(f"{base}.gif"), scale)["output"], "gif"),
    ]
    sheet = export.export_spritesheet(
        filename, rel(f"{base}_sheet.png"), "packed", scale, rel(f"{base}_sheet.json")
    )
    exports.append(export_entry("spritesheet", sheet["output"], "png", metadata_path=sheet["data_output"]))
    for tag in info["tags"]:
        out = export.export_tag_gif(filename, tag["name"], rel(f"{base}_{tag['name']}.gif"), scale)
        exports.append(export_entry("tag_gif", out["output"], "gif"))

    manifest_path = resolve_path(rel("manifest.json"))
    manifest = workflow_manifest(
        "game_asset_bundle",
        sprite=sprite_summary(info),
        created_files=[file_entry("manifest", manifest_path, "json")],
        exports=exports,
        suggested_next_actions=[
            "Import the sprite sheet + JSON into your engine (Godot/Unity/Phaser).",
            "Use the per-tag GIFs to preview each animation.",
        ],
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return manifest


@mcp.tool()
def validate_sprite_for_game_export(
    filename: str,
    expected_width: int | None = None,
    expected_height: int | None = None,
    tile_multiple: int | None = None,
    allowed_color_modes: list[str] | None = None,
    min_frames: int | None = None,
    max_frames: int | None = None,
    required_tags: list[str] | None = None,
    require_transparent_background: bool = False,
    max_palette_size: int | None = None,
    expected_exports: list[str] | None = None,
    spritesheet_data: str | None = None,
) -> dict:
    """Check whether a sprite is game-ready against the criteria you specify.

    Runs a series of checks — does the file open, do dimensions match (exactly or as
    a tile multiple), is the colour mode allowed, are frame counts / required animation
    tags present, is the background transparent, is the palette within budget, do
    expected export files exist, and is sprite-sheet metadata readable — plus soft
    warnings for oversized canvases, missing tags, and default/blank layer names.

    All criteria are optional; only the ones you pass are enforced. Returns a
    ``workflow_manifest.v1`` manifest (kind "validation") with a `validation` section
    `{passed, checks[], errors[], warnings[]}`. `validation.passed` is the verdict;
    `ok` just means the check ran.
    """
    path = resolve_path(filename)
    if not path.exists():
        report = {
            "passed": False,
            "checks": [{"name": "file_exists", "ok": False, "level": "error",
                        "detail": f"no such file: {path}"}],
            "errors": [f"no such file: {path}"],
            "warnings": [],
        }
        return workflow_manifest(
            "validation", validation=report, warnings=report["warnings"],
            suggested_next_actions=["Create or export the sprite before validating it."],
        )

    try:
        info = inspect.get_sprite_info(filename)
    except AsepriteError as exc:
        report = {
            "passed": False,
            "checks": [{"name": "opens", "ok": False, "level": "error", "detail": str(exc)}],
            "errors": [str(exc)],
            "warnings": [],
        }
        return workflow_manifest("validation", validation=report, warnings=report["warnings"])

    transparent_corners = None
    if require_transparent_background:
        w, h = info["width"], info["height"]
        transparent_corners = []
        for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            px = inspect.get_pixels(filename, x, y, 1, 1)["pixels"][0][0]
            transparent_corners.append(px[7:9] == "00")  # alpha byte == 00

    missing_exports = None
    if expected_exports is not None:
        missing_exports = [p for p in expected_exports if not resolve_path(p).exists()]

    unreadable_metadata = None
    if spritesheet_data is not None:
        meta = resolve_path(spritesheet_data)
        if not meta.exists():
            unreadable_metadata = str(meta)
        else:
            try:
                json.loads(meta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                unreadable_metadata = str(meta)

    report = validation.evaluate(
        info,
        expected_width=expected_width,
        expected_height=expected_height,
        tile_multiple=tile_multiple,
        allowed_color_modes=allowed_color_modes,
        min_frames=min_frames,
        max_frames=max_frames,
        required_tags=required_tags,
        max_palette_size=max_palette_size,
        require_transparent_background=require_transparent_background,
        transparent_corners=transparent_corners,
        missing_exports=missing_exports,
        unreadable_metadata=unreadable_metadata,
    )

    actions = (
        ["The sprite passed all required checks — ready to export."]
        if report["passed"]
        else [f"Fix: {e}" for e in report["errors"]]
    )
    return workflow_manifest(
        "validation",
        sprite=sprite_summary(info),
        validation=report,
        warnings=report["warnings"],
        suggested_next_actions=actions,
    )


_DEFAULT_ITEMS = ["sword", "shield", "potion", "coin", "key", "gem"]
_DIRECTIONS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _grid_sheet(filename: str, cell: int, names: list[str], columns: int | None,
                shape: str) -> dict:
    """Scaffold a grid sheet: a cell per name, each with a placeholder + a named slice.
    Returns the final get_sprite_info dict. (Shared by icon_set / rpg_item_sheet.)"""
    if len(set(names)) != len(names):
        raise ValueError("Cell/slice names must be unique.")
    n = len(names)
    cols = columns or min(n, 4)
    rows = math.ceil(n / cols)
    sprite.create_sprite(filename, cols * cell, rows * cell, "rgb")
    ramp = palette.generate_ramp(
        "#e0c060", steps=max(3, min(8, n)), hue_shift=200, light_range=0.5
    )["colors"]
    palette.set_palette(filename, ramp)
    inset = max(1, cell // 6)
    for i, nm in enumerate(names):
        r, c = divmod(i, cols)
        x0, y0 = c * cell, r * cell
        color = ramp[i % len(ramp)]
        if shape == "circle":
            drawing.draw_ellipse(
                filename, x0 + cell // 2, y0 + cell // 2,
                cell // 2 - inset, cell // 2 - inset, color, filled=True
            )
        else:
            drawing.draw_rectangle(
                filename, x0 + inset, y0 + inset, cell - 2 * inset, cell - 2 * inset,
                color, filled=True
            )
        slices.add_slice(filename, nm, x0, y0, cell, cell)
    return inspect.get_sprite_info(filename)


@mcp.tool()
def create_icon_set(
    name: str, icon_size: int = 16, count: int = 4, columns: int | None = None
) -> dict:
    """Scaffold an icon set: a grid sheet with `count` icon cells, each a placeholder
    inside a named slice (`icon_0`, `icon_1`, …) for easy atlas export.

    Returns a ``workflow_manifest.v1`` manifest (kind "icon_set"); the per-icon regions
    appear as slices under `sprite.slices`.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    filename = _aseprite_name(name)
    info = _grid_sheet(filename, icon_size, [f"icon_{i}" for i in range(count)], columns, "circle")
    return workflow_manifest(
        "icon_set",
        sprite=sprite_summary(info),
        created_files=[file_entry("source_sprite", info["path"], "aseprite")],
        suggested_next_actions=[
            "Draw each icon inside its named slice region.",
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}', tile_multiple={icon_size}).",
            f"Export the atlas: export_game_asset_bundle('{filename}').",
        ],
    )


@mcp.tool()
def create_rpg_item_sheet(
    name: str, item_size: int = 16, items: list[str] | None = None, columns: int | None = None
) -> dict:
    """Scaffold an RPG item sheet: a grid sheet with one named slice per item
    (default sword/shield/potion/coin/key/gem), each with a placeholder.

    Returns a ``workflow_manifest.v1`` manifest (kind "rpg_item_sheet"); item regions
    appear as slices (named after each item) under `sprite.slices`.
    """
    item_names = items or _DEFAULT_ITEMS
    if not item_names:
        raise ValueError("items must be non-empty when provided.")
    filename = _aseprite_name(name)
    info = _grid_sheet(filename, item_size, list(item_names), columns, "rect")
    return workflow_manifest(
        "rpg_item_sheet",
        sprite=sprite_summary(info),
        created_files=[file_entry("source_sprite", info["path"], "aseprite")],
        suggested_next_actions=[
            "Draw each item inside its named slice region.",
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}', tile_multiple={item_size}).",
            f"Export the atlas: export_game_asset_bundle('{filename}').",
        ],
    )


@mcp.tool()
def make_8_direction_walk_template(
    filename: str,
    frames_per_direction: int = 4,
    frame_duration_ms: int = 120,
    directions: list[str] | None = None,
) -> dict:
    """Scaffold an 8-direction walk-cycle template on an existing sprite: enough frames
    for `frames_per_direction` per direction, with one animation tag per direction
    (N, NE, E, SE, S, SW, W, NW by default).

    Frames are placeholders to draw over. Returns a ``workflow_manifest.v1`` manifest
    (kind "walk_template") with an animation block listing the directions/tags.
    """
    if frames_per_direction < 1:
        raise ValueError("frames_per_direction must be >= 1")
    dirs = directions or _DIRECTIONS_8
    total = frames_per_direction * len(dirs)
    info = inspect.get_sprite_info(filename)
    while info["frameCount"] < total:
        frames.add_frame(filename, frame_duration_ms, copy_from=1)
        info = inspect.get_sprite_info(filename)
    frames.set_all_frame_durations(filename, frame_duration_ms)
    for i, direction in enumerate(dirs):
        start = i * frames_per_direction + 1
        tags.add_tag(filename, direction, start, start + frames_per_direction - 1, "forward")

    final = inspect.get_sprite_info(filename)
    return workflow_manifest(
        "walk_template",
        sprite=sprite_summary(final),
        created_files=[file_entry("source_sprite", final["path"], "aseprite")],
        animation={
            "directions": list(dirs),
            "frames_per_direction": frames_per_direction,
            "duration_ms": frame_duration_ms,
            "tags": [t["name"] for t in final["tags"]],
        },
        suggested_next_actions=[
            "Draw each direction's walk frames under its tag.",
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}', required_tags={dirs}).",
            f"Export per direction: export_tags('{filename}', 'walk/{{tag}}_{{frame}}.png').",
        ],
    )
