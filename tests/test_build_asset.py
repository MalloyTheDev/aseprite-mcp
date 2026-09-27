"""Integration tests for build_asset_from_spec — require Aseprite (--run-aseprite)."""

import json
from pathlib import Path

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import asset_spec, inspect

_REQUIRED = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def test_build_character_is_structure_only():
    spec = {
        "schema": "aseprite_mcp.asset_spec.v1",
        "name": "w/hero_spec", "kind": "character",
        "canvas": {"width": 32, "height": 32, "color_mode": "rgb"},
        "palette": ["#1d2b53", "#ff004d", "#ffffff"],
        "layers": ["body", "details", "fx"],
        "animations": [
            {"name": "idle", "frame_count": 2, "duration_ms": 150},
            {"name": "walk", "frame_count": 2, "duration_ms": 100},
        ],
        "slices": [{"name": "hitbox", "type": "hitbox",
                    "bounds": {"x": 8, "y": 12, "width": 16, "height": 14}}],
        "exports": [{"format": "godot_spriteframes"}, {"format": "slice_metadata"}],
    }
    m = asset_spec.build_asset_from_spec(spec)
    assert set(m) >= _REQUIRED and m["kind"] == "asset_spec"

    info = inspect.get_sprite_info("w/hero_spec.aseprite")
    assert [layer["name"] for layer in info["layers"]] == ["body", "details", "fx"]
    assert info["frameCount"] == 4                                  # 2 + 2
    assert {t["name"] for t in info["tags"]} == {"idle", "walk"}
    assert {s["name"] for s in info["slices"]} == {"hitbox"}

    # Structure only: the canvas was never drawn on (top-left pixel is transparent).
    px = inspect.get_pixels("w/hero_spec.aseprite", 0, 0, 1, 1)["pixels"][0][0]
    assert px[7:9] == "00"

    roles = {f["role"]: f["path"] for f in m["created_files"]}
    assert Path(roles["engine_resource"]).stat().st_size > 0       # .tres
    assert Path(roles["metadata"]).stat().st_size > 0              # _slices.json

    # The slice type survives the build -> export round-trip.
    doc = json.loads(Path(roles["metadata"]).read_text(encoding="utf-8"))
    hitbox = next(s for s in doc["slices"] if s["name"] == "hitbox")
    assert hitbox["type"] == "hitbox"


def test_build_icon_set_makes_named_slices():
    spec = {"name": "w/icons_spec", "kind": "icon_set", "icon_size": 16, "count": 4, "columns": 2,
            "exports": [{"format": "slice_metadata"}]}
    asset_spec.build_asset_from_spec(spec)
    info = inspect.get_sprite_info("w/icons_spec.aseprite")
    assert {s["name"] for s in info["slices"]} == {f"icon_{i}" for i in range(4)}


def test_build_rejects_invalid_spec_without_launching():
    with pytest.raises(ValidationFailed, match="Invalid asset spec"):
        asset_spec.build_asset_from_spec({"name": "w/bad", "kind": "character"})  # no canvas
