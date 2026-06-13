"""Integration tests for engine export presets — require Aseprite (--run-aseprite)."""

from pathlib import Path

import pytest

from aseprite_mcp.core.errors import ExportError
from aseprite_mcp.tools import export_presets, workflow

_REQUIRED = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def _make_tagged_sprite(name):
    workflow.create_character_sprite(name, 16, 16)
    workflow.make_4_frame_idle_animation(f"{name}.aseprite")  # adds the "idle" tag


def test_export_godot_spriteframes_writes_resource_and_sheet():
    _make_tagged_sprite("w/gd")
    m = export_presets.export_godot_spriteframes("w/gd.aseprite", "w/gd.tres")

    assert _REQUIRED <= set(m)
    assert m["kind"] == "engine_preset"
    tres_entry = next(f for f in m["created_files"] if f["role"] == "engine_resource")
    sheet_entry = next(e for e in m["exports"] if e["role"] == "spritesheet")

    # All three files exist and are non-empty.
    assert Path(tres_entry["path"]).stat().st_size > 0
    assert Path(sheet_entry["path"]).stat().st_size > 0
    assert Path(sheet_entry["metadata_path"]).stat().st_size > 0

    tres = Path(tres_entry["path"]).read_text(encoding="utf-8")
    assert 'type="SpriteFrames"' in tres and "format=3" in tres
    assert '[ext_resource type="Texture2D"' in tres
    assert '[sub_resource type="AtlasTexture"' in tres
    assert '"name": &"idle"' in tres
    assert 'path="res://gd.png"' in tres  # default texture res path = res://<sheet name>


def test_texture_res_path_override():
    _make_tagged_sprite("w/gd2")
    m = export_presets.export_godot_spriteframes(
        "w/gd2.aseprite", "w/gd2.tres", texture_res_path="res://art/gd2.png"
    )
    tres = Path(m["created_files"][0]["path"]).read_text(encoding="utf-8")
    assert 'path="res://art/gd2.png"' in tres


def test_preset_is_no_clobber():
    _make_tagged_sprite("w/gd3")
    export_presets.export_godot_spriteframes("w/gd3.aseprite", "w/gd3.tres")
    with pytest.raises(ExportError, match="already exists"):
        export_presets.export_godot_spriteframes("w/gd3.aseprite", "w/gd3.tres")
    # explicit overwrite regenerates all three outputs
    export_presets.export_godot_spriteframes("w/gd3.aseprite", "w/gd3.tres", overwrite=True)
