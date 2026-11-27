"""Godot export adapter tests with sheet metadata supplied in place of Aseprite."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from aseprite_mcp.core.errors import ExportError
from aseprite_mcp.tools import export_presets

pytestmark = pytest.mark.pure


@pytest.fixture
def sheet_export(monkeypatch):
    data = {
        "frames": [
            {"frame": {"x": i * 8, "y": 0, "w": 8, "h": 8}, "duration": 100}
            for i in range(2)
        ],
        "meta": {"frameTags": [
            {"name": "fade", "from": 0, "to": 1, "direction": "reverse", "repeat": "3"},
            {"name": "blink", "from": 0, "to": 1, "direction": "pingpong", "repeat": 2},
            {"name": "idle", "from": 0, "to": 1, "direction": "forward"},
        ]},
    }

    def export_sheet(filename, output, sheet_type, scale, *, data_output, overwrite):
        Path(output).write_bytes(b"sheet placeholder")
        Path(data_output).write_text(json.dumps(data), encoding="utf-8")
        return {"output": str(output), "data_output": str(data_output)}

    exporter = Mock(side_effect=export_sheet)
    monkeypatch.setattr(export_presets.export, "export_spritesheet", exporter)
    monkeypatch.setattr(export_presets.inspect, "get_sprite_info", Mock(return_value={
        "width": 8, "height": 8, "colorMode": "rgb", "frameCount": 2, "layers": [], "tags": [],
    }))
    return data, exporter


@pytest.mark.parametrize("default_loop", [True, False])
def test_export_delivers_tag_warnings_and_resource(tmp_path, sheet_export, default_loop):
    _, exporter = sheet_export
    out = tmp_path / "hero.tres"
    sheet = tmp_path / "atlas.png"
    metadata = sheet.with_suffix(".json")
    manifest = export_presets.export_godot_spriteframes(
        "hero.aseprite", str(out), sheet_output=str(sheet), scale=2,
        texture_res_path="res://art/atlas.png", default_loop=default_loop,
    )
    exporter.assert_called_once_with(
        "hero.aseprite", str(sheet), "packed", 2, data_output=str(metadata), overwrite=True,
    )
    assert manifest["ok"] is True
    assert manifest["schema_version"] == "workflow_manifest.v1"
    assert manifest["kind"] == "engine_preset"
    assert len(manifest["warnings"]) == 2
    for warning, name, repeat in zip(manifest["warnings"], ["fade", "blink"], [3, 2], strict=True):
        assert name in warning and str(repeat) in warning and "once" in warning
    assert manifest["created_files"][0]["path"] == str(out)
    assert manifest["exports"][0]["path"] == str(sheet)
    assert manifest["exports"][0]["metadata_path"] == str(metadata)
    tres = out.read_text(encoding="utf-8")
    assert 'path="res://art/atlas.png"' in tres
    assert tres.count('"loop": false') == (2 if default_loop else 3)
    assert tres.count('"loop": true') == (1 if default_loop else 0)
    assert tres.index('SubResource("AtlasTexture_1")') < tres.index('SubResource("AtlasTexture_0")')


@pytest.mark.parametrize("suffix", [".tres", ".png", ".json"])
def test_existing_output_refused_before_export(tmp_path, sheet_export, suffix):
    _, exporter = sheet_export
    out = tmp_path / "hero.tres"
    existing = out.with_suffix(suffix)
    existing.write_bytes(b"keep me")
    with pytest.raises(ExportError, match="already exists"):
        export_presets.export_godot_spriteframes("hero.aseprite", str(out))
    exporter.assert_not_called()
    assert existing.read_bytes() == b"keep me"
    assert set(tmp_path.iterdir()) == {existing}


def test_overwrite_refreshes_resource_and_warnings(tmp_path, sheet_export):
    data, exporter = sheet_export
    out = tmp_path / "hero.tres"
    export_presets.export_godot_spriteframes("hero.aseprite", str(out))
    data["meta"]["frameTags"] = []
    manifest = export_presets.export_godot_spriteframes("hero.aseprite", str(out), overwrite=True)
    assert exporter.call_count == 2
    assert manifest["warnings"] == []
    tres = out.read_text(encoding="utf-8")
    assert '"name": &"default"' in tres
    assert '"loop": true' in tres
    assert 'path="res://hero.png"' in tres
