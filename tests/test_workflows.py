"""Integration tests for the high-level workflow tools.

Requires Aseprite — runs only under `pytest --run-aseprite`.
"""

import os

from aseprite_mcp.tools import inspect, workflow


def test_create_character_sprite():
    m = workflow.create_character_sprite("w/hero", 32, 32, base_color="#3878c8")
    assert m["ok"] and m["kind"] == "character_sprite"
    assert m["width"] == 32 and m["height"] == 32
    assert "body" in m["layers"] and "details" in m["layers"]
    assert len(m["palette"]) == 5
    assert m["suggested_next_actions"]
    info = inspect.get_sprite_info("w/hero.aseprite")
    assert info["paletteSize"] == 5


def test_make_4_frame_idle_animation():
    workflow.create_character_sprite("w/idle", 16, 16)
    m = workflow.make_4_frame_idle_animation("w/idle.aseprite", layer="body", frame_duration_ms=120)
    assert m["ok"] and m["frameCount"] == 4 and m["tag"] == "idle"
    info = inspect.get_sprite_info("w/idle.aseprite")
    assert info["frameCount"] == 4
    assert [t["name"] for t in info["tags"]] == ["idle"]
    assert all(abs(f["duration"] - 0.12) < 1e-6 for f in info["frames"])


def test_create_tileset_project():
    m = workflow.create_tileset_project("w/tiles", tile_size=16, columns=4, rows=3)
    assert m["ok"] and m["kind"] == "tileset_project"
    assert m["width"] == 64 and m["height"] == 48
    names = [t["name"] for t in m["tiles"]]
    assert names == ["grass", "dirt", "water", "stone"]
    # indices are 1..4 (0 is the empty tile)
    assert [t["index"] for t in m["tiles"]] == [1, 2, 3, 4]


def test_export_game_asset_bundle():
    workflow.create_character_sprite("w/bundle", 16, 16)
    workflow.make_4_frame_idle_animation("w/bundle.aseprite")
    m = workflow.export_game_asset_bundle("w/bundle.aseprite", scale=2)
    assert m["ok"] and m["kind"] == "game_asset_bundle"
    assert m["sprite"]["frames"] == 4
    # every advertised file exists on disk
    for key in ("png", "gif", "spritesheet", "spritesheet_data", "manifest"):
        assert os.path.getsize(m["files"][key]) > 0
    assert len(m["files"]["tag_gifs"]) == 1  # the "idle" tag
    assert os.path.getsize(m["files"]["tag_gifs"][0]["file"]) > 0
