"""Workflow-level tools — agent-friendly asset scaffolding.

These compose the low-level tools into one-call workflows that produce game-ready
asset scaffolds, and return a structured *manifest* (created files, paths, frames,
tags, dimensions, and suggested next actions) so an agent can keep going.

They are deterministic scaffolding — no AI/model generation. Build on top of them
with the low-level drawing/effects/tilemap tools.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..app import mcp
from . import (
    cels,
    drawing,
    effects,
    export,
    frames,
    inspect,
    layers,
    palette,
    sprite,
    tags,
    tilemap,
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
