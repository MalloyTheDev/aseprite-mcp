"""Workflow-level tools: agent-friendly asset scaffolding.

These compose the low-level tools into one-call workflows that produce game-ready
asset scaffolds, and return a structured *manifest* (created files, paths, frames,
tags, dimensions, and suggested next actions) so an agent can keep going.

They are deterministic scaffolding: no AI/model generation. Build on top of them
with the low-level drawing/effects/tilemap tools.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import NamedTuple

from ..app import mcp
from ..core import indexed, validation
from ..core.errors import ExportError, ValidationFailed
from ..core.limits import (
    MAX_BATCH_OPERATIONS,
    MAX_COLOR_LIST_LENGTH,
    MAX_FRAMES_PER_DIRECTION,
    MAX_GRID_CELLS,
    MAX_WALK_DIRECTIONS,
    check_count,
    check_list_length,
)
from ..core.manifest import (
    export_entry,
    file_entry,
    pixel_counters,
    sprite_summary,
    workflow_manifest,
)
from ..core.models import Rect
from ..core.paths import ensure_output_path
from ..core.runner import AsepriteError
from . import (
    animation,
    batch,
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
)
from .common import resolve_path


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
    palette, and suggested next actions), plus `pixels_written` for the placeholder it
    drew. With `with_placeholder=False` nothing is drawn and the field is absent.
    """
    filename = _aseprite_name(name)
    sprite.create_sprite(filename, width, height, "rgb")
    layers.rename_layer(filename, "Layer 1", "body")
    layers.add_layer(filename, "details")

    ramp = palette.generate_ramp(base_color, steps=5, hue_shift=30, light_range=0.6)["colors"]
    palette.set_palette(filename, ramp)

    # Kept so the manifest can report what the placeholder cost. Measured on a 32x32
    # scaffold: the ellipse writes 221 pixels and the outline 72. Everything else this
    # tool calls (create_sprite, rename_layer, add_layer, set_palette) reports no pixel
    # counters at all, so the total is these two.
    drawn: list[dict] = []
    if with_placeholder:
        cx, cy = width // 2, height // 2
        rx, ry = max(2, width // 3), max(2, height // 3)
        drawn.append(
            drawing.draw_ellipse(filename, cx, cy, rx, ry, ramp[2], filled=True, layer="body")
        )
        drawn.append(
            effects.add_outline(filename, ramp[0], thickness=1, where="outside", layer="body")
        )

    final = inspect.get_sprite_info(filename)
    return workflow_manifest(
        "character_sprite",
        sprite=sprite_summary(final),
        created_files=[file_entry("source_sprite", final["path"], "aseprite")],
        palette={"colors": ramp, "count": len(ramp)},
        counters=pixel_counters(*drawn),
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
    # No `counters=`: measured, every call above (add_frame, set_cel_position,
    # set_all_frame_durations, add_tag) comes back with no pixel counters, because none of
    # them writes through `img_set`. Duplicating a frame copies a cel and moving one
    # changes its position; neither paints. So the harness's report is absent here because
    # there is nothing to report, not because this tool forgot to pass it (#201).
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
    overwrite: bool = False,
) -> dict:
    """Scaffold a tilemap project: a canvas sized columns×rows tiles, a tilemap layer,
    and a starter tileset (grass/dirt/water/stone by default, or your own
    [{"name","color"}] list). The grid is filled with the first tile to start.

    Returns a ``workflow_manifest.v1`` manifest with a tilemap block mapping tile
    names to their tileset indices.
    """
    # `tiles or _DEFAULT_TILES` made the guard below unreachable: an explicitly
    # empty list silently got the default tiles instead of being rejected.
    tile_defs = _DEFAULT_TILES if tiles is None else list(tiles)
    if not tile_defs:
        raise ValidationFailed("tiles must be non-empty when provided.")
    check_list_length(
        "tiles", tile_defs, MAX_GRID_CELLS,
        remedy="Each tile is its own Aseprite launch; add the rest with add_tile.",
    )
    filename = _aseprite_name(name)
    # Passed through, because without it this tool could be called exactly once per
    # filename and never again: every other creation tool here takes it, and a scaffold
    # that cannot be re-run is a scaffold you cannot iterate a tileset with.
    sprite.create_sprite(filename, columns * tile_size, rows * tile_size, "rgb",
                         overwrite=overwrite)
    tilemap.create_tilemap_layer(filename, "tiles", tile_size, tile_size, columns, rows)

    created = []
    for td in tile_defs:
        out = tilemap.add_tile(filename, "tiles", td["color"])
        created.append({"name": td.get("name", f"tile{out['index']}"),
                        "index": out["index"], "color": td["color"]})
    if created:
        tilemap.fill_tilemap(filename, "tiles", created[0]["index"])

    final = inspect.get_sprite_info(filename)
    # No `counters=`: measured, `add_tile` and `fill_tilemap` report no pixel counters.
    # A tilemap write sets tile indices on a tilemap cel rather than pixels through
    # `img_set`, so there is nothing for the harness to count (#201).
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
    overwrite: bool = False,
    ramp: list[str] | None = None,
    allow_defects: bool = False,
) -> dict:
    """Export a sprite into a game-ready bundle directory: a flattened PNG, an animated
    GIF, a packed sprite sheet (+ JSON data), a GIF per animation tag, and a
    `manifest.json` describing everything.

    **The art is judged before anything is written.** Every frame is assessed the way
    `assess_sprite` judges one (all of them in one launch, identical frames once), and
    the result is the manifest's `assessment` section. A *defect* refuses the bundle: an
    absent keyline on a figure of several masses, or, with `ramp`, a drawn pixel that is
    not on it. Those are the readings that scored as faults against sprites known to be
    good and bad. Every other reading is an *observation*, listed and never blocking,
    because observations do not separate good art from poor: on this project's own
    gallery its best sheet draws three and a featureless blob none. So a clean assessment
    means none of the measured faults, not that the art is good; looking at
    `render_preview` is still the only judge of that.

    Args:
        overwrite: Replace existing bundle files (default False = no-clobber). Every
            planned output is checked up front, so the bundle fails before writing any
            file if a target already exists.
        ramp: The colours the art is drawn from, as given to `assess_sprite`. When set,
            every drawn pixel must be one of them. Refused before anything is launched
            past the colour-list cap or in a notation that does not parse. On an indexed
            sprite whose palette cannot hold it exactly, `assessment.palette` says so,
            and a refusal for pixels off it carries that reading.
        allow_defects: Bundle even when the assessment finds a defect (default False).
            The defects are then the manifest's `warnings`, and `assessment.waived` is
            true.

    Returns a ``workflow_manifest.v1`` manifest (the same object is also written to
    disk as manifest.json inside the bundle).
    """
    if ramp:
        # Refused before anything is launched, as every tool that takes a ramp refuses one.
        check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
        ramp = inspect.ramp_as_hex(ramp)
    info = inspect.get_sprite_info(filename)
    base = Path(filename).stem
    bundle = bundle_name or f"{base}_bundle"

    def rel(p: str) -> str:
        return f"{bundle}/{p}"

    png_rel = rel(f"{base}.png")
    gif_rel = rel(f"{base}.gif")
    sheet_rel = rel(f"{base}_sheet.png")
    sheet_data_rel = rel(f"{base}_sheet.json")
    tag_rels = [(t["name"], rel(f"{base}_{t['name']}.gif")) for t in info["tags"]]
    manifest_rel = rel("manifest.json")

    # Validate every planned output up front so the bundle fails before writing any
    # file when a target already exists and overwrite is False.
    for planned in (png_rel, gif_rel, sheet_rel, sheet_data_rel,
                    *(p for _, p in tag_rels), manifest_rel):
        ensure_output_path(planned, overwrite=overwrite, error_type=ExportError)

    assessment = inspect.assess_frames(filename, frame_count=info["frameCount"],
                                       width=info["width"], height=info["height"],
                                       ramp=ramp)
    # On an indexed sprite whose palette cannot hold the ramp exactly, pixels off it are
    # the palette's doing rather than the shading's, so that reading travels with them.
    palette_notes = indexed.ramp_readings(assessment.pop("ramp_on_palette", None) or {})
    if palette_notes:
        assessment["palette"] = palette_notes
    defects = [_frames_reading(found) for found in assessment["defects"]]
    if defects and not allow_defects:
        count = f"{len(defects)} defect{'s' if len(defects) > 1 else ''}"
        raise ValidationFailed(
            f"The art has {count}, so nothing was bundled:\n"
            + "".join(f"- {line}\n" for line in defects)
            + "".join(f"The palette may be why: {note}\n" for note in palette_notes)
            + "Fix them (assess_sprite measures one frame in full), or pass "
            "allow_defects=True to bundle anyway; they are then the manifest's warnings."
        )
    warnings = list(defects)
    if defects:
        assessment["waived"] = True
    if assessment.get("skipped"):
        warnings.append(f"The art was not assessed: {assessment['skipped']}.")

    # Sub-exports use overwrite=True: the up-front pass already enforced the policy.
    exports = [
        export_entry("png", export.export_png(filename, png_rel, 1, scale, overwrite=True)["output"], "png"),
        export_entry("gif", export.export_gif(filename, gif_rel, scale, overwrite=True)["output"], "gif"),
    ]
    sheet = export.export_spritesheet(
        filename, sheet_rel, "packed", scale, sheet_data_rel, overwrite=True
    )
    exports.append(export_entry("spritesheet", sheet["output"], "png", metadata_path=sheet["data_output"]))
    for tag_name, tag_rel in tag_rels:
        out = export.export_tag_gif(filename, tag_name, tag_rel, scale, overwrite=True)
        exports.append(export_entry("tag_gif", out["output"], "gif"))

    manifest_path = resolve_path(manifest_rel)
    # No `counters=`: a bundle only reads the sprite and writes export files, so it never
    # offers a pixel to `img_set` and the harness's report is empty by construction (#201).
    actions = [
        "Import the sprite sheet + JSON into your engine (Godot/Unity/Phaser).",
        "Use the per-tag GIFs to preview each animation.",
    ]
    if assessment["observations"]:
        actions.append(
            f"{len(assessment['observations'])} reading(s) in assessment.observations are "
            "worth a look before this ships; none of them blocks it."
        )
    manifest = workflow_manifest(
        "game_asset_bundle",
        sprite=sprite_summary(info),
        created_files=[file_entry("manifest", manifest_path, "json")],
        exports=exports,
        assessment=assessment,
        suggested_next_actions=actions,
        warnings=warnings,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return manifest


def _frames_reading(found: dict) -> str:
    """One grouped reading as a line: the frames it was made on, then the reading."""
    frames = found["frames"]
    label = "frame" if len(frames) == 1 else "frames"
    return f"{label} {', '.join(str(n) for n in frames)}: {found['reading']}"


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

    Runs a series of checks: does the file open, do dimensions match (exactly or as
    a tile multiple), is the colour mode allowed, are frame counts / required animation
    tags present, is the background transparent, is the palette within budget, do
    expected export files exist, and is sprite-sheet metadata readable, plus soft
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
        ["The sprite passed all required checks, ready to export."]
        if report["passed"]
        else [f"Fix: {e}" for e in report["errors"]]
    )
    # No `counters=`, in any of this tool's three returns: it is in READ_ONLY_TOOLS and
    # writes nothing, so there is no pixel report to carry (#201).
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
                shape: str) -> tuple[dict, dict]:
    """Scaffold a grid sheet: a cell per name, each with a placeholder + a named slice.

    Returns the final get_sprite_info dict and the merged pixel counters for the
    placeholders it drew. (Shared by icon_set / rpg_item_sheet.)"""
    if len(set(names)) != len(names):
        raise ValidationFailed("Cell/slice names must be unique.")
    # Each cell costs a placeholder draw plus a slice, so the cell count is a
    # launch count until this scaffold is batched too (see the note on the walk
    # template): bound it here, where both grid-sheet scaffolds pass through.
    check_list_length(
        "cells", names, MAX_GRID_CELLS,
        remedy="Scaffold a smaller sheet, or split it across several sprites.",
    )
    n = len(names)
    cols = columns or min(n, 4)
    rows = math.ceil(n / cols)
    sprite.create_sprite(filename, cols * cell, rows * cell, "rgb")
    ramp = palette.generate_ramp(
        "#e0c060", steps=max(3, min(8, n)), hue_shift=200, light_range=0.5
    )["colors"]
    palette.set_palette(filename, ramp)
    inset = max(1, cell // 6)
    # One placeholder draw per cell, and each one reports what it wrote, so the sheet can
    # say what it covered in total rather than only that it returned (#201). `add_slice`
    # reports nothing: a slice is a named region, not pixels.
    drawn: list[dict] = []
    for i, nm in enumerate(names):
        row, col = divmod(i, cols)
        cell_rect = Rect.of(col * cell, row * cell, cell, cell)
        color = ramp[i % len(ramp)]
        if shape == "circle":
            drawn.append(drawing.draw_ellipse(
                filename, cell_rect.x + cell // 2, cell_rect.y + cell // 2,
                cell // 2 - inset, cell // 2 - inset, color, filled=True
            ))
        else:
            drawn.append(drawing.draw_rectangle(
                filename, cell_rect.x + inset, cell_rect.y + inset,
                cell - 2 * inset, cell - 2 * inset, color, filled=True
            ))
        slices.add_slice(filename, nm, cell_rect.x, cell_rect.y, cell_rect.width, cell_rect.height)
    return inspect.get_sprite_info(filename), pixel_counters(*drawn)


@mcp.tool()
def create_icon_set(
    name: str, icon_size: int = 16, count: int = 4, columns: int | None = None
) -> dict:
    """Scaffold an icon set: a grid sheet with `count` icon cells, each a placeholder
    inside a named slice (`icon_0`, `icon_1`, …) for easy atlas export.

    Returns a ``workflow_manifest.v1`` manifest (kind "icon_set"); the per-icon regions
    appear as slices under `sprite.slices`.
    """
    count = check_count(
        "count", count, MAX_GRID_CELLS, minimum=1,
        remedy="Scaffold a smaller sheet, or split it across several sprites.",
    )
    filename = _aseprite_name(name)
    info, counters = _grid_sheet(
        filename, icon_size, [f"icon_{i}" for i in range(count)], columns, "circle"
    )
    return workflow_manifest(
        "icon_set",
        sprite=sprite_summary(info),
        created_files=[file_entry("source_sprite", info["path"], "aseprite")],
        counters=counters,
        suggested_next_actions=[
            "Draw each icon inside its named slice region.",
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}', "
            f"tile_multiple={icon_size}).",
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
    # As in create_tileset_project: `items or _DEFAULT_ITEMS` made this guard
    # unreachable, so an explicitly empty list quietly became the default items.
    item_names = _DEFAULT_ITEMS if items is None else list(items)
    if not item_names:
        raise ValidationFailed("items must be non-empty when provided.")
    filename = _aseprite_name(name)
    info, counters = _grid_sheet(filename, item_size, list(item_names), columns, "rect")
    return workflow_manifest(
        "rpg_item_sheet",
        sprite=sprite_summary(info),
        created_files=[file_entry("source_sprite", info["path"], "aseprite")],
        counters=counters,
        suggested_next_actions=[
            "Draw each item inside its named slice region.",
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}', "
            f"tile_multiple={item_size}).",
            f"Export the atlas: export_game_asset_bundle('{filename}').",
        ],
    )


@mcp.tool()
def make_8_direction_walk_template(
    filename: str,
    frames_per_direction: int = 8,
    frame_duration_ms: int = 120,
    directions: list[str] | None = None,
) -> dict:
    """Scaffold an 8-direction walk-cycle template on an existing sprite: enough frames
    for `frames_per_direction` per direction, with one animation tag per direction
    (N, NE, E, SE, S, SW, W, NW by default).

    Args:
        frames_per_direction: 8 is the convention for a walk, and it is what this
            defaults to: contact, down, pass, up for each leg. 6 is the budget option and
            4 only reads as a walk mirrored on a side view, which an 8-direction sheet by
            definition is not. The default was 4 until this was fixed (#91), so a sprite
            scaffolded before then has half the frames a walk needs.
        frame_duration_ms: Set on every frame. Shape the timing afterwards with
            `apply_timing_curve`: a walk holds its contacts.
        directions: Override the eight compass tags.

    Frames are placeholders to draw over. Returns a ``workflow_manifest.v1`` manifest
    (kind "walk_template") with an animation block listing the directions/tags.
    """
    frames_per_direction = check_count(
        "frames_per_direction", frames_per_direction, MAX_FRAMES_PER_DIRECTION, minimum=1,
        remedy="Every frame is a full copy of frame 1; add more with add_frame if needed.",
    )
    dirs = list(directions or _DIRECTIONS_8)
    check_list_length(
        "directions", dirs, MAX_WALK_DIRECTIONS,
        remedy="Tag the extra directions separately with add_tag.",
    )
    total = frames_per_direction * len(dirs)

    # One launch to read the starting frame count, then one launch per batch. This used
    # to be a per-frame loop of add_frame + get_sprite_info -- two Aseprite launches for
    # every frame, and nothing bounded the call as a whole, since the per-operation
    # timeout applies to each launch individually. The per-frame get_sprite_info was
    # only re-reading a count we can keep ourselves.
    info = inspect.get_sprite_info(filename)
    ops: list[dict] = [
        {"op": "add_frame", "args": {"duration_ms": frame_duration_ms, "copy_from": 1}}
        for _ in range(max(0, total - info["frameCount"]))
    ]
    # Tags come after the frames in the same ordered list: ops run in order against one
    # open sprite, so by the time a tag is added the frames it spans exist.
    ops += [
        {"op": "add_tag", "args": {
            "name": direction,
            "from": i * frames_per_direction + 1,
            "to": (i + 1) * frames_per_direction,
            "direction": "forward",
        }}
        for i, direction in enumerate(dirs)
    ]
    # The batch manifests are kept rather than discarded so this scaffold reports whatever
    # the ops wrote (#201). Today the ops are add_frame and add_tag, neither of which
    # writes a pixel, so the counters come back empty and the fields stay absent; the
    # merge is here so a scaffold that grows a drawing op cannot silently stop saying so.
    batched = [
        batch.apply_operations(filename, ops[start:start + MAX_BATCH_OPERATIONS])
        for start in range(0, len(ops), MAX_BATCH_OPERATIONS)
    ]
    # Frames that already existed keep their own durations otherwise, so this still
    # runs. It stays a single Lua-side loop rather than one op per frame: one launch
    # either way, and it does not grow the batch with the sprite's existing frames.
    frames.set_all_frame_durations(filename, frame_duration_ms)

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
        counters=pixel_counters(*batched),
        suggested_next_actions=[
            "Draw each direction's walk frames under its tag.",
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}', required_tags={dirs}).",
            f"Export per direction: export_tags('{filename}', 'walk/{{tag}}_{{frame}}.png').",
        ],
    )


# ============================================================ scaffold_cycle (#91 item 2)
class _Cycle(NamedTuple):
    """One animation kind's conventions, as animators actually author it.

    Every number is from the conventions recorded in #91 rather than from taste: `default`
    is the first count the issue names for the kind and `convention` is the range it names,
    which is the range the warning quotes.

    `loops` is the one field that is a correctness claim rather than a preference. An
    attack, a hurt and a death do not wrap, and the file's own answer to that is a tag's
    `repeats` (0 means forever, 1 is a one-shot). `validate_loop` reads exactly that
    field, so a one-shot scaffolded as a loop is not cosmetic: it makes the checker treat
    a held final pose as a duplicated seam frame and report an error about a wrap that
    does not exist.
    """

    default: int
    convention: tuple[int, int]
    loops: bool
    curve: str
    base_ms: int
    # A walk and a run are the same poses twice, once per leg, so their pose list below is
    # per step and gets an L/R suffix. Everything else runs straight through once.
    stepped: bool
    poses: tuple[str, ...]
    extra_poses: tuple[tuple[str, int], ...]
    # Shape the two curves that the curve itself cannot know about: a hurt is a flash and
    # then a held recovery, a death slows to a stop on a pose that stays on screen.
    snap_first: bool = False
    hold_last: bool = False


# `poses` is the kind's pose list at its default count; `extra_poses` are inserted one at a
# time, in this order and at these indices into the list as it has grown so far, one per
# frame above the default; and the list is trimmed from the tail for each frame below it.
# So the default count gives exactly one frame per named pose, and every count in the
# convention's range still gets its poses named from one small table. The tail is the right
# end to trim, because the tail is what a shorter take loses: a 5-frame death drops
# `settle`/`still`, not the impact.
_CYCLES: dict[str, _Cycle] = {
    # 8 is the convention: contact, down, pass, up for each leg. 6 is the budget option
    # (it drops the `up` pose) and 4 only reads as a walk mirrored on a side view.
    "walk": _Cycle(8, (4, 8), True, "hold_extremes", 100, True,
                   ("contact", "down"), (("pass", 2), ("up", 3))),
    # A run is quicker and shorter than a walk, and the flight pose is what makes it a
    # run, so `air` is in the base list and `push` is what the 8-frame version adds.
    "run": _Cycle(6, (6, 8), True, "hold_extremes", 70, True,
                  ("contact", "air"), (("down", 1), ("push", 2))),
    "idle": _Cycle(4, (4, 6), True, "hold_extremes", 150, False,
                   ("rest", "rise", "peak", "fall"), (("hold", 3), ("settle", 5))),
    "attack": _Cycle(5, (5, 7), False, "attack", 80, False,
                     ("anticipation", "swing", "impact", "recoil", "recover"),
                     (("windup", 1), ("hold", 4))),
    "hurt": _Cycle(2, (2, 3), False, "ease_out", 80, False,
                   ("impact", "recover"), (("reel", 1),), snap_first=True),
    "death": _Cycle(6, (6, 10), False, "ease_out", 90, False,
                    ("impact", "stagger", "fall", "land", "settle", "still"),
                    (("reel", 2), ("bounce", 4), ("knees", 3), ("fade", 8)),
                    hold_last=True),
}


def _poses(spec: _Cycle, count: int) -> list[str]:
    """`count` pose names for one pass of `spec` (one step, for a stepped kind).

    Past the table's own length the extras run out and the remaining poses are numbered,
    which is the case the out-of-convention warning is about: a 12-frame walk is not a
    walk anybody has named poses for.
    """
    names = list(spec.poses)
    for name, at in spec.extra_poses:
        if len(names) >= count:
            break
        names.insert(at, name)
    while len(names) < count:
        names.append(f"pose{len(names) + 1}")
    return names[:count]


def _phases(spec: _Cycle, count: int) -> list[str]:
    """The phase name for each of `count` frames, in order."""
    if not spec.stepped:
        return _poses(spec, count)
    # The left step takes the extra frame on an odd count, so a 7-frame walk is a 4-pose
    # step followed by a 3-pose one rather than silently dropping a frame.
    left = (count + 1) // 2
    return ([f"{pose}L" for pose in _poses(spec, left)]
            + [f"{pose}R" for pose in _poses(spec, count - left)])


@mcp.tool()
def scaffold_cycle(
    filename: str,
    kind: str,
    frames: int | None = None,
    base_ms: int | None = None,
) -> dict:
    """Scaffold one animation cycle: its frames, a tag per phase, and a shaped timing curve.

    `kind` is `walk`, `run`, `idle`, `attack`, `hurt` or `death`, and it settles the four
    things a scaffolded animation otherwise gets wrong:

    * **The frame count.** walk 8 (6 is the budget option, and 4 only reads as a walk
      mirrored on a side view), run 6, idle 4, attack 5, hurt 2, death 6. A count outside
      the kind's conventional range is accepted with a warning rather than refused.
    * **A tag per phase, named for the pose rather than numbered.** An 8-frame walk gets
      `walk_contactL`, `walk_downL`, `walk_passL`, `walk_upL` and the same four for the
      right step, plus a `walk` tag over the whole cycle, so the frame you are drawing on
      says what it is meant to be.
    * **Non-uniform durations from the start**, via `apply_timing_curve`: a cycle holds
      its extremes, an attack snaps through the strike, a hurt flashes and then holds the
      recovery, a death slows to a stop on a held last pose. Uniform timing is the
      placeholder every animation starts with and almost none should keep.
    * **Loop versus one-shot.** An attack, a hurt and a death do not wrap, so every tag
      they get is written with `repeats=1` instead of being left at 0 ("play forever").
      That field is what `validate_loop` reads, so a one-shot tagged as a loop makes the
      checker report a duplicated seam frame on an animation that has no seam.

    Frames are copies of frame 1, there to draw over. Nothing already in the sprite is
    deleted, but Aseprite inserts a copied frame rather than appending it, so on a sprite
    that already has several frames the new ones land at the front and the existing ones
    end up at the end of the cycle; the manifest warns when that happens. Frames past the
    cycle are left untagged and untimed, with a warning saying which.

    Args:
        kind: walk | run | idle | attack | hurt | death.
        frames: Override the kind's default frame count.
        base_ms: The duration of a passing frame; every other duration is a multiple of
            it. Defaults per kind, because a run passes through its poses faster than an
            idle breathes.

    Returns a ``workflow_manifest.v1`` manifest (kind ``animation_cycle``) whose
    `animation` section lists every phase with the frame, tag, duration, timing role and
    repeat count it ended up with, read back off the saved sprite rather than restated
    from what was asked for.
    """
    spec = _CYCLES.get(kind)
    if spec is None:
        raise ValidationFailed(
            f"bad value for 'kind': {kind!r}; expected one of {', '.join(_CYCLES)}."
        )
    # MAX_FRAMES_PER_DIRECTION rather than a cap of its own: its comment is already about
    # exactly this number ("a hand-drawn walk cycle is 4-12 frames; 32 covers the most
    # detailed run cycle"), and a second constant carrying the same justification is a
    # second thing to keep in step. Renaming it belongs in core/limits.py.
    count = spec.default if frames is None else check_count(
        "frames", frames, MAX_FRAMES_PER_DIRECTION, minimum=1,
        remedy="Scaffold the cycle and extend it with add_frame if it really needs more.",
    )
    base = spec.base_ms if base_ms is None else int(base_ms)

    warnings: list[str] = []
    low, high = spec.convention
    if not low <= count <= high:
        warnings.append(
            f"a {kind} is conventionally {low} to {high} frames and this one is {count}. "
            f"The poses are named for {spec.default}; outside the range the extra phases "
            f"come out numbered rather than named."
        )

    phases = _phases(spec, count)
    phase_tags = [f"{kind}_{phase}" for phase in phases]
    # Measured while checking the tables: `hold_extremes` holds frames 1 and count//2+1,
    # and on a stepped kind the second contact is at (count+1)//2+1. Those agree only for
    # an even count. A 5-frame walk therefore comes out with the hold on `passL` (frame 3)
    # while the contacts are frames 1 and 4, which is the one case where the durations and
    # the phase names disagree, so it is said out loud rather than left to be noticed.
    if spec.stepped and count % 2:
        warnings.append(
            f"{count} frames is an odd count for a {kind}, so the two steps are uneven "
            f"({(count + 1) // 2} frames then {count // 2}) and the held extremes land on "
            f"frames 1 and {count // 2 + 1} while the contacts are frames 1 and "
            f"{(count + 1) // 2 + 1}. Re-time with apply_timing_curve(..., "
            f"hold_frames=[1, {(count + 1) // 2 + 1}]) if that matters."
        )

    info = inspect.get_sprite_info(filename)
    # Aseprite will happily hold two tags with one name, and then neither can be addressed
    # by it: `remove_tag`, `set_tag` and `export_tag_gif` each find a tag by name and
    # would pick whichever came first. Refused rather than scaffolded into that state.
    clash = sorted({t["name"] for t in info["tags"]}.intersection([kind, *phase_tags]))
    if clash:
        raise ValidationFailed(
            f"the sprite already has tag(s) {clash}, which this scaffold would duplicate; "
            "Aseprite allows two tags with one name and then neither can be addressed by "
            "it. Remove them with remove_tag first, or scaffold into a new sprite."
        )
    if info["frameCount"] > count:
        warnings.append(
            f"the sprite has {info['frameCount']} frames and a {kind} is {count}, so "
            f"frames {count + 1}-{info['frameCount']} are left untagged and untimed."
        )
    # Measured, and surprising enough to be worth saying out loud: `add_frame(copy_from=1)`
    # does not append. The copy goes in directly after frame 1 (#222), so on a sprite
    # holding a red frame 1 and a blue frame 2, one `add_frame(copy_from=1)` produced red,
    # red, blue: frame 1 stays first and everything drawn after it is pushed to the end.
    # `make_8_direction_walk_template` has always behaved this way for the same reason, and
    # whether a copy should append is `tools/frames.py`'s decision rather than something a
    # scaffold should work around, so this reports the consequence instead.
    if info["frameCount"] > 1 and info["frameCount"] < count:
        drawn = info["frameCount"]
        moved = (f"frame 2 is now frame {count}" if drawn == 2 else
                 f"frames 2-{drawn} are now frames {count - drawn + 2}-{count}")
        warnings.append(
            f"the sprite already had {drawn} frames and the new ones are copies of frame 1 "
            f"inserted right after it, so what was drawn after frame 1 moved to the end of "
            f"the cycle: {moved}. Reorder with move_frame, or scaffold onto a single-frame "
            f"sprite."
        )

    # Launch count: one read, one batch for the frames and every tag, two for the timing
    # curve (it reads the spacing before it writes), and one read back. Five, whatever the
    # frame count.
    #
    # It used to be fourteen for an 8-frame walk, measured end to end at 3.4s (0.234s a
    # launch), because the tags were a launch each: `core/oplib.py`'s `add_tag` op could
    # not take `repeats`, so a one-shot could not be written inside a batch (#223). Every
    # tag still goes through the same path, so a cycle's `repeats=0` remains a fact this
    # tool wrote rather than Aseprite's default inherited by accident; that path is now
    # the batch rather than the tool.
    missing = max(0, count - info["frameCount"])
    repeats = 0 if spec.loops else 1
    ops = [{"op": "add_frame", "args": {"duration_ms": base, "copy_from": 1}}
           for _ in range(missing)]
    ops.append({"op": "add_tag", "args": {"name": kind, "from": 1, "to": count,
                                          "direction": "forward", "repeats": repeats}})
    for number, phase_tag in enumerate(phase_tags, start=1):
        ops.append({"op": "add_tag", "args": {"name": phase_tag, "from": number,
                                              "to": number, "direction": "forward",
                                              "repeats": repeats}})
    batch.apply_operations(filename, ops)

    timed = animation.apply_timing_curve(
        filename,
        curve=spec.curve,
        frames=list(range(1, count + 1)),
        base_ms=base,
        hold_frames=[count] if spec.hold_last else None,
        snap_frames=[1] if spec.snap_first else None,
    )
    warnings += timed["warnings"]

    final = inspect.get_sprite_info(filename)
    # Read back rather than restated: the repeat counts below are what the file says after
    # the save, which is the only form of "this is a one-shot" an engine or `validate_loop`
    # will ever see.
    saved = {t["name"]: t for t in final["tags"]}
    cycle_repeats = saved.get(kind, {}).get("repeats", 0)

    # No `counters=`: a cycle scaffold adds frames, tags and durations. Copying a frame,
    # naming a tag and setting a duration all leave `img_set` alone, so the harness has no
    # pixels to report and the fields are absent by measurement (#201).
    return workflow_manifest(
        "animation_cycle",
        sprite=sprite_summary(final),
        created_files=[file_entry("source_sprite", final["path"], "aseprite")],
        animation={
            "kind": kind,
            "tag": kind,
            "frames": list(range(1, count + 1)),
            "loops": cycle_repeats == 0,
            "repeats": cycle_repeats,
            "curve": spec.curve,
            "base_ms": base,
            "durations_ms": timed["durations_ms"],
            "total_duration_ms": timed["total_duration_ms"],
            "phases": [
                {
                    "frame": number,
                    "phase": phase,
                    "tag": phase_tag,
                    "duration_ms": duration,
                    "role": role,
                    "repeats": saved.get(phase_tag, {}).get("repeats", 0),
                }
                for number, phase, phase_tag, duration, role in zip(
                    range(1, count + 1), phases, phase_tags,
                    timed["durations_ms"], timed["roles"], strict=True,
                )
            ],
        },
        warnings=warnings,
        suggested_next_actions=[
            f"Draw one pose per frame; the tags name them, {phase_tags[0]} to "
            f"{phase_tags[-1]}.",
            f"Move the character through it: offset_cels('{filename}', <layer>, "
            f"{list(range(1, count + 1))}, dx=..., dy=...).",
            f"Link a pose that genuinely repeats: link_cels('{filename}', <layer>, "
            "[<frames>]).",
            f"Re-time it once the poses exist: apply_timing_curve('{filename}', "
            f"curve='{spec.curve}', tag='{kind}').",
            # Not yet: every frame is a copy of frame 1, so a fresh scaffold fails this
            # check on identical adjacent frames by construction. It is the check for
            # after the poses are drawn, which is what makes it worth naming here.
            f"Once the poses are drawn, check it: validate_loop('{filename}', "
            f"tag='{kind}').",
        ],
    )
