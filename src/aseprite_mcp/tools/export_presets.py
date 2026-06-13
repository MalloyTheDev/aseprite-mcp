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
from ..core.runner import run_lua
from ..core.slice_metadata import build_slice_metadata
from . import export, inspect
from .common import lua_path, resolve_path


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


_SLICE_LUA = """
local spr = open_sprite(ARG.src)
local slices = {}
for i, sl in ipairs(spr.slices) do
  local s = {
    name = sl.name,
    bounds = { x = sl.bounds.x, y = sl.bounds.y, width = sl.bounds.width, height = sl.bounds.height },
    color = color_hex(sl.color),
    data = sl.data or "",
  }
  if sl.center ~= nil then
    s.center = { x = sl.center.x, y = sl.center.y, width = sl.center.width, height = sl.center.height }
  end
  if sl.pivot ~= nil then s.pivot = { x = sl.pivot.x, y = sl.pivot.y } end
  slices[i] = s
end
RESULT = { width = spr.width, height = spr.height, slices = slices }
"""


@mcp.tool()
def export_slice_metadata(
    filename: str,
    output: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Export every slice as engine-agnostic JSON (``aseprite_mcp.slice_metadata.v1``).

    Each slice becomes ``{name, type, id, bounds, pivot, nine_slice, color, data,
    raw_data}``. **Type detection:** a slice's user-data JSON ``type`` wins; otherwise the
    name convention ``<type>:<id>`` (recognized types: hitbox, hurtbox, collision, interact,
    pivot, origin, attach, spawn, nine_slice — anything else becomes ``"custom"``, never an
    error). ``id`` comes from the data ``id`` or the name's ``:<id>`` suffix. ``nine_slice``
    (Aseprite's 9-patch center) and ``pivot`` are emitted whenever the slice has them. Slice
    user-data that is valid JSON is parsed into ``data``; the raw string is kept in ``raw_data``.

    Args:
        output: Destination .json path. Defaults to ``<sprite>_slices.json`` beside the sprite.
        overwrite: Replace an existing file (default False = no-clobber).

    Returns a ``workflow_manifest.v1`` manifest (kind ``engine_metadata``).
    """
    src = resolve_path(filename)
    out_rel = output or str(Path(filename).with_name(f"{Path(filename).stem}_slices.json"))
    out_path = ensure_output_path(out_rel, overwrite=overwrite, error_type=ExportError)

    raw = run_lua(_SLICE_LUA, {"src": lua_path(src)})
    metadata = build_slice_metadata(
        sprite=Path(filename).name,
        width=raw["width"],
        height=raw["height"],
        slices=raw.get("slices") or [],
    )
    out_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")

    info = inspect.get_sprite_info(filename)
    n = len(metadata["slices"])
    warnings = ["No slices found in the sprite."] if n == 0 else []
    return workflow_manifest(
        "engine_metadata",
        sprite=sprite_summary(info),
        created_files=[file_entry("metadata", str(out_path), "json")],
        warnings=warnings,
        suggested_next_actions=[
            f"{n} slice(s) written to {out_path.name}; load it in your engine to place "
            "hitboxes/hurtboxes/collision/attach points and 9-slice regions.",
            'Tag slices by name (e.g. "hitbox", "attach:weapon") or a JSON data field '
            '({"type":"hitbox","id":"body"}) to set type/id.',
        ],
    )
