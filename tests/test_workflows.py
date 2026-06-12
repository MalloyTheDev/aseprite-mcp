"""Integration tests for the high-level workflow tools.

Asserts the shared workflow_manifest.v1 contract. Requires Aseprite — runs only
under `pytest --run-aseprite`.
"""

import os

from aseprite_mcp.tools import inspect, workflow

_REQUIRED = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def _assert_manifest(m, kind):
    assert _REQUIRED <= set(m)
    assert m["ok"] is True
    assert m["schema_version"] == "workflow_manifest.v1"
    assert m["kind"] == kind
    assert isinstance(m["created_files"], list)
    assert isinstance(m["suggested_next_actions"], list) and m["suggested_next_actions"]
    assert m["warnings"] == []
    # every created-file entry has a consistent shape
    for entry in m["created_files"]:
        assert {"role", "path", "format"} <= set(entry)


def test_create_character_sprite():
    m = workflow.create_character_sprite("w/hero", 32, 32, base_color="#3878c8")
    _assert_manifest(m, "character_sprite")
    assert m["sprite"]["width"] == 32 and m["sprite"]["height"] == 32
    assert m["sprite"]["layers"] == ["body", "details"]
    assert m["palette"]["count"] == 5
    assert [f["role"] for f in m["created_files"]] == ["source_sprite"]
    assert inspect.get_sprite_info("w/hero.aseprite")["paletteSize"] == 5


def test_make_4_frame_idle_animation():
    workflow.create_character_sprite("w/idle", 16, 16)
    m = workflow.make_4_frame_idle_animation("w/idle.aseprite", layer="body", frame_duration_ms=120)
    _assert_manifest(m, "idle_animation")
    assert m["sprite"]["frames"] == 4
    assert m["animation"]["tag"] == "idle"
    assert m["animation"]["frames"] == [1, 2, 3, 4]
    assert m["animation"]["duration_ms"] == 120


def test_create_tileset_project():
    m = workflow.create_tileset_project("w/tiles", tile_size=16, columns=4, rows=3)
    _assert_manifest(m, "tileset_project")
    assert m["sprite"]["width"] == 64 and m["sprite"]["height"] == 48
    tm = m["tilemap"]
    assert tm["layer"] == "tiles" and tm["tile_width"] == 16
    assert [t["name"] for t in tm["tiles"]] == ["grass", "dirt", "water", "stone"]
    assert [t["index"] for t in tm["tiles"]] == [1, 2, 3, 4]


def test_export_game_asset_bundle():
    workflow.create_character_sprite("w/bundle", 16, 16)
    workflow.make_4_frame_idle_animation("w/bundle.aseprite")
    m = workflow.export_game_asset_bundle("w/bundle.aseprite", scale=2)
    _assert_manifest(m, "game_asset_bundle")
    assert m["sprite"]["frames"] == 4

    roles = {e["role"] for e in m["exports"]}
    assert {"png", "gif", "spritesheet", "tag_gif"} <= roles
    # the spritesheet export carries its metadata path
    sheet = next(e for e in m["exports"] if e["role"] == "spritesheet")
    assert "metadata_path" in sheet and os.path.getsize(sheet["metadata_path"]) > 0
    # every advertised file exists on disk
    for e in m["exports"]:
        assert os.path.getsize(e["path"]) > 0
    for f in m["created_files"]:
        assert os.path.getsize(f["path"]) > 0  # manifest.json


def test_validate_sprite_for_game_export():
    workflow.create_character_sprite("w/val", 32, 32)
    workflow.make_4_frame_idle_animation("w/val.aseprite")

    ok = workflow.validate_sprite_for_game_export(
        "w/val.aseprite",
        expected_width=32, expected_height=32,
        allowed_color_modes=["rgb"],
        min_frames=4, required_tags=["idle"],
    )
    _assert_manifest(ok, "validation")
    assert ok["validation"]["passed"] is True
    assert ok["validation"]["errors"] == []

    bad = workflow.validate_sprite_for_game_export(
        "w/val.aseprite", expected_width=64, required_tags=["walk"]
    )
    assert bad["validation"]["passed"] is False
    assert len(bad["validation"]["errors"]) >= 2  # wrong width + missing tag

    missing = workflow.validate_sprite_for_game_export("w/does_not_exist.aseprite")
    assert missing["validation"]["passed"] is False
    assert any("no such file" in e for e in missing["validation"]["errors"])


def _has_validate_suggestion(m):
    return any("validate_sprite_for_game_export" in a for a in m["suggested_next_actions"])


def test_create_icon_set():
    m = workflow.create_icon_set("w/icons", icon_size=16, count=6, columns=3)
    _assert_manifest(m, "icon_set")
    assert m["sprite"]["width"] == 48 and m["sprite"]["height"] == 32  # 3x2 grid of 16px
    assert [s["name"] for s in m["sprite"]["slices"]] == [f"icon_{i}" for i in range(6)]
    assert _has_validate_suggestion(m)


def test_create_rpg_item_sheet():
    m = workflow.create_rpg_item_sheet("w/items", item_size=16, items=["sword", "potion", "coin"])
    _assert_manifest(m, "rpg_item_sheet")
    assert [s["name"] for s in m["sprite"]["slices"]] == ["sword", "potion", "coin"]
    assert _has_validate_suggestion(m)


def test_make_8_direction_walk_template():
    workflow.create_character_sprite("w/walk", 16, 16)
    m = workflow.make_8_direction_walk_template("w/walk.aseprite", frames_per_direction=2)
    _assert_manifest(m, "walk_template")
    assert m["sprite"]["frames"] == 16  # 8 directions x 2 frames
    assert m["animation"]["directions"] == ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    assert len(m["animation"]["tags"]) == 8
    assert _has_validate_suggestion(m)
