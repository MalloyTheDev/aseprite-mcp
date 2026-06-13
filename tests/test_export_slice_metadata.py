"""Integration tests for export_slice_metadata — require Aseprite (--run-aseprite)."""

import json
from pathlib import Path

import pytest

from aseprite_mcp.core.errors import ExportError
from aseprite_mcp.tools import export_presets, slices, sprite

_REQUIRED = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def _setup(name):
    sprite.create_sprite(f"{name}.aseprite", 32, 32)
    slices.add_slice(f"{name}.aseprite", "hitbox", 8, 12, 16, 14, color="#ff0000ff")
    slices.add_slice(f"{name}.aseprite", "attach:weapon", 20, 14, 1, 1,
                     pivot_x=20, pivot_y=14, color="#00ffffff")
    slices.add_slice(f"{name}.aseprite", "ui:panel", 0, 0, 32, 32,
                     center_x=4, center_y=4, center_width=24, center_height=24)
    slices.add_slice(f"{name}.aseprite", "body", 0, 0, 10, 10,
                     data='{"type":"hurtbox","id":"core"}')


def test_export_slice_metadata_round_trip():
    _setup("w/sl")
    m = export_presets.export_slice_metadata("w/sl.aseprite")
    assert _REQUIRED <= set(m)
    assert m["kind"] == "engine_metadata"

    path = m["created_files"][0]["path"]
    assert path.endswith("sl_slices.json")  # default <sprite>_slices.json
    doc = json.loads(Path(path).read_text(encoding="utf-8"))

    assert doc["schema"] == "aseprite_mcp.slice_metadata.v1"
    assert doc["source"] == {"sprite": "sl.aseprite", "width": 32, "height": 32}

    by_name = {s["name"]: s for s in doc["slices"]}
    assert by_name["hitbox"]["type"] == "hitbox" and by_name["hitbox"]["id"] is None
    assert by_name["hitbox"]["color"] == "#ff0000ff"
    assert by_name["hitbox"]["bounds"] == {"x": 8, "y": 12, "width": 16, "height": 14}

    weapon = by_name["attach:weapon"]
    assert weapon["type"] == "attach" and weapon["id"] == "weapon"
    assert weapon["pivot"] == {"x": 20, "y": 14}

    panel = by_name["ui:panel"]
    assert panel["type"] == "custom" and panel["id"] == "panel"  # "ui" not a known type
    assert panel["nine_slice"] == {"center": {"x": 4, "y": 4, "width": 24, "height": 24}}

    body = by_name["body"]  # data JSON type wins over the name
    assert body["type"] == "hurtbox" and body["id"] == "core"
    assert body["data"] == {"type": "hurtbox", "id": "core"}


def test_export_slice_metadata_no_clobber():
    _setup("w/sl2")
    export_presets.export_slice_metadata("w/sl2.aseprite", "w/sl2_meta.json")
    with pytest.raises(ExportError, match="already exists"):
        export_presets.export_slice_metadata("w/sl2.aseprite", "w/sl2_meta.json")
    export_presets.export_slice_metadata("w/sl2.aseprite", "w/sl2_meta.json", overwrite=True)


def test_export_slice_metadata_no_slices_warns():
    sprite.create_sprite("w/sl3.aseprite", 16, 16)
    m = export_presets.export_slice_metadata("w/sl3.aseprite")
    assert m["warnings"] == ["No slices found in the sprite."]
    doc = json.loads(Path(m["created_files"][0]["path"]).read_text(encoding="utf-8"))
    assert doc["slices"] == []
