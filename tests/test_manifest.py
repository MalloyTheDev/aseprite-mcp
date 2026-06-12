"""Pure-Python tests for the workflow manifest schema — no Aseprite (always run)."""

import json

import pytest

from aseprite_mcp.core import manifest as M

_REQUIRED_KEYS = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def test_manifest_has_required_keys():
    m = M.workflow_manifest("character_sprite")
    assert _REQUIRED_KEYS <= set(m)
    assert m["ok"] is True
    assert m["schema_version"] == "workflow_manifest.v1"
    assert m["kind"] == "character_sprite"
    assert m["created_files"] == [] and m["warnings"] == []
    assert m["suggested_next_actions"] == []


def test_optional_sections_omitted_when_empty():
    m = M.workflow_manifest("idle_animation")
    for optional in ("sprite", "exports", "palette", "animation", "tilemap"):
        assert optional not in m  # omitted, not present-as-null


def test_optional_sections_included_when_present():
    m = M.workflow_manifest(
        "tileset_project",
        tilemap={"layer": "tiles", "tile_width": 16, "tile_height": 16, "tiles": []},
        palette={"colors": ["#000000"], "count": 1},
    )
    assert m["tilemap"]["layer"] == "tiles"
    assert m["palette"]["count"] == 1


def test_file_and_export_entries_normalize_paths():
    from pathlib import Path

    fe = M.file_entry("source_sprite", Path("a") / "b.aseprite", "aseprite")
    assert isinstance(fe["path"], str) and fe["role"] == "source_sprite"
    ee = M.export_entry("spritesheet", Path("x.png"), "png", metadata_path=Path("x.json"))
    assert isinstance(ee["path"], str) and isinstance(ee["metadata_path"], str)


def test_export_entry_omits_metadata_when_absent():
    ee = M.export_entry("gif", "a.gif", "gif")
    assert "metadata_path" not in ee


def test_invalid_kind_and_role_error_clearly():
    with pytest.raises(ValueError, match="Invalid manifest kind"):
        M.workflow_manifest("not_a_kind")
    with pytest.raises(ValueError, match="Invalid created-file role"):
        M.file_entry("bogus", "p", "png")
    with pytest.raises(ValueError, match="Invalid export role"):
        M.export_entry("bogus", "p", "png")


def test_normalize_actions():
    assert M.normalize_actions(None) == []
    assert M.normalize_actions(["a", "b"]) == ["a", "b"]
    assert M.normalize_actions([1, 2]) == ["1", "2"]


def test_manifest_is_json_serializable():
    m = M.workflow_manifest(
        "game_asset_bundle",
        created_files=[M.file_entry("manifest", "m.json", "json")],
        exports=[M.export_entry("png", "a.png", "png")],
        suggested_next_actions=["go"],
    )
    s = json.dumps(m)
    assert json.loads(s)["kind"] == "game_asset_bundle"


def test_sprite_summary_shape():
    info = {
        "path": "x.aseprite", "width": 32, "height": 16, "colorMode": "rgb",
        "frameCount": 4, "layers": [{"name": "body"}, {"name": "details"}],
        "tags": [{"name": "idle", "from": 1, "to": 4, "aniDir": "forward"}],
    }
    s = M.sprite_summary(info)
    assert s["width"] == 32 and s["height"] == 16 and s["color_mode"] == "rgb"
    assert s["frames"] == 4 and s["layers"] == ["body", "details"]
    assert s["tags"][0]["name"] == "idle"
    assert s["slices"] == []  # absent -> consistently empty


def test_sprite_summary_includes_slices():
    info = {
        "width": 16, "height": 16, "colorMode": "rgb", "frameCount": 1,
        "layers": [{"name": "Layer 1"}], "tags": [],
        "slices": [{"name": "icon_0", "bounds": {"x": 0, "y": 0, "width": 8, "height": 8}}],
    }
    s = M.sprite_summary(info)
    assert s["slices"][0]["name"] == "icon_0"


def test_new_workflow_kinds_are_valid():
    for kind in ("icon_set", "walk_template", "rpg_item_sheet", "validation"):
        assert M.workflow_manifest(kind)["kind"] == kind
