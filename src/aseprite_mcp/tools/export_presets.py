"""Engine export presets — one-call exports into game-engine-native resource files.

These compose the sprite-sheet export with an engine adapter in `core/engines/`: run
Aseprite once to produce a packed sheet (+ JSON rects), then generate the engine resource
from that metadata. v1 ships Godot 4 `SpriteFrames`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..app import mcp
from ..core.engines import godot
from ..core.errors import ExportError
from ..core.manifest import export_entry, file_entry, sprite_summary, workflow_manifest
from ..core.paths import ensure_output_path
from . import export, inspect


@mcp.tool()
def export_godot_spriteframes(
    filename: str,
    output: str,
    sheet_output: str | None = None,
    scale: int = 1,
    texture_res_path: str | None = None,
    default_loop: bool = True,
    overwrite: bool = False,
) -> dict:
    """Export a sprite as a Godot 4 ``SpriteFrames`` resource (.tres) + a packed sheet.

    Produces three files: a packed PNG sprite sheet, its JSON frame/tag metadata, and a
    ``SpriteFrames`` .tres that references the sheet via ``AtlasTexture`` regions — one
    Godot animation per Aseprite tag (or a single ``default`` animation if untagged), with
    per-frame timing taken from Aseprite frame durations.

    v1 emits ``SpriteFrames`` only (no pivot/origin/hitbox/9-slice). Aseprite tag direction
    isn't represented (Godot animations only loop or not); ``default_loop`` is applied to all.

    Args:
        output: Destination .tres path (workspace-relative).
        sheet_output: Sheet PNG path. Defaults to ``<output stem>.png`` beside the .tres.
        scale: Integer upscaling factor for the sheet.
        texture_res_path: The ``res://`` path of the sheet inside your Godot project (the
            AtlasTexture atlas). Defaults to ``res://<sheet filename>`` (same-folder import).
        default_loop: ``loop`` flag for every generated animation (default True).
        overwrite: Replace existing outputs (default False = no-clobber). All three targets
            are validated up front, so nothing is written if any already exists.

    Returns a ``workflow_manifest.v1`` manifest (kind ``engine_preset``).
    """
    tres_path = Path(output)
    sheet_rel = sheet_output or str(tres_path.with_suffix(".png"))
    json_rel = str(Path(sheet_rel).with_suffix(".json"))
    res_path = texture_res_path or f"res://{Path(sheet_rel).name}"

    # Validate every planned output up front (no-clobber): fail before writing any file.
    out_tres = ensure_output_path(output, overwrite=overwrite, error_type=ExportError)
    ensure_output_path(sheet_rel, overwrite=overwrite, error_type=ExportError)
    ensure_output_path(json_rel, overwrite=overwrite, error_type=ExportError)

    # Produce the packed sheet + JSON rects (overwrite=True: policy already enforced above).
    sheet = export.export_spritesheet(
        filename, sheet_rel, "packed", scale, data_output=json_rel, overwrite=True
    )
    sheet_data = json.loads(Path(sheet["data_output"]).read_text(encoding="utf-8"))

    tres_text = godot.build_spriteframes(
        sheet_data, texture_res_path=res_path, default_loop=default_loop
    )
    out_tres.write_text(tres_text, encoding="utf-8", newline="\n")

    info = inspect.get_sprite_info(filename)
    anim_count = len((sheet_data.get("meta") or {}).get("frameTags") or []) or 1
    return workflow_manifest(
        "engine_preset",
        sprite=sprite_summary(info),
        created_files=[file_entry("engine_resource", str(out_tres), "tres")],
        exports=[export_entry("spritesheet", sheet["output"], "png",
                              metadata_path=sheet["data_output"])],
        suggested_next_actions=[
            f"Copy the .tres and sheet into your Godot project; ensure the sheet imports "
            f"at '{res_path}' (override with texture_res_path if it lives elsewhere).",
            f"Assign the SpriteFrames to an AnimatedSprite2D — {anim_count} animation(s) ready.",
            "Re-run with overwrite=True to regenerate after editing the sprite.",
        ],
    )
