"""Pure-Python tests for the Godot 4 SpriteFrames .tres builder — no Aseprite."""

import pytest

from aseprite_mcp.core.engines import godot

# Two tags: "idle" (frames 0-1 @ 100ms) and "walk" (frames 2-3 @ 200ms).
SHEET = {
    "frames": [
        {"frame": {"x": 0, "y": 0, "w": 16, "h": 16}, "duration": 100},
        {"frame": {"x": 16, "y": 0, "w": 16, "h": 16}, "duration": 100},
        {"frame": {"x": 0, "y": 16, "w": 16, "h": 16}, "duration": 200},
        {"frame": {"x": 16, "y": 16, "w": 16, "h": 16}, "duration": 200},
    ],
    "meta": {"frameTags": [
        {"name": "idle", "from": 0, "to": 1, "direction": "forward"},
        {"name": "walk", "from": 2, "to": 3, "direction": "forward"},
    ]},
}


def _build(data=SHEET, **kw):
    kw.setdefault("texture_res_path", "res://hero.png")
    return godot.build_spriteframes(data, **kw)


def test_header_format_and_load_steps():
    tres = _build()
    # 1 ext_resource + 4 atlas sub_resources + [resource] == 6 load steps
    assert tres.startswith('[gd_resource type="SpriteFrames" load_steps=6 format=3]')


def test_ext_resource_points_at_texture():
    tres = _build(texture_res_path="res://art/hero.png")
    assert '[ext_resource type="Texture2D" path="res://art/hero.png" id="1_sheet"]' in tres


def test_atlas_subresources_and_regions():
    tres = _build()
    assert tres.count('[sub_resource type="AtlasTexture"') == 4
    assert 'atlas = ExtResource("1_sheet")' in tres
    assert "region = Rect2(16, 0, 16, 16)" in tres   # frame 1
    assert "region = Rect2(0, 16, 16, 16)" in tres    # frame 2


def test_one_animation_per_tag_with_names():
    tres = _build()
    assert '"name": &"idle"' in tres
    assert '"name": &"walk"' in tres


def test_timing_uniform_durations_map_to_speed():
    tres = _build()
    # idle: 100ms frames -> 10 fps, walk: 200ms -> 5 fps; uniform -> per-frame duration 1.0
    assert '"speed": 10.0' in tres
    assert '"speed": 5.0' in tres
    assert '"duration": 1.0' in tres


def test_timing_mixed_durations_use_relative_multiplier():
    data = {
        "frames": [
            {"frame": {"x": 0, "y": 0, "w": 8, "h": 8}, "duration": 100},
            {"frame": {"x": 8, "y": 0, "w": 8, "h": 8}, "duration": 200},
        ],
        "meta": {"frameTags": [{"name": "blink", "from": 0, "to": 1}]},
    }
    tres = _build(data)
    assert '"speed": 10.0' in tres   # base = most common (100ms) -> 10 fps
    assert '"duration": 1.0' in tres
    assert '"duration": 2.0' in tres  # the 200ms frame is twice as long


def test_untagged_sprite_gets_single_default_animation():
    data = {"frames": SHEET["frames"], "meta": {}}
    tres = _build(data)
    assert '"name": &"default"' in tres
    assert tres.count('"name":') == 1
    assert tres.startswith('[gd_resource type="SpriteFrames" load_steps=6 format=3]')


def test_default_loop_flag_respected():
    assert '"loop": true' in _build(default_loop=True)
    assert '"loop": false' in _build(default_loop=False)


def test_only_referenced_frames_get_atlas_textures():
    # A single tag covering frames 1-2 leaves 0 and 3 unreferenced.
    data = {"frames": SHEET["frames"],
            "meta": {"frameTags": [{"name": "mid", "from": 1, "to": 2}]}}
    tres = _build(data)
    assert tres.count('[sub_resource type="AtlasTexture"') == 2
    assert 'id="AtlasTexture_1"' in tres and 'id="AtlasTexture_2"' in tres
    assert 'id="AtlasTexture_0"' not in tres and 'id="AtlasTexture_3"' not in tres
    assert tres.startswith('[gd_resource type="SpriteFrames" load_steps=4 format=3]')


def test_tag_name_is_escaped():
    data = {"frames": SHEET["frames"][:1],
            "meta": {"frameTags": [{"name": 'a"b\\c', "from": 0, "to": 0}]}}
    tres = _build(data)
    assert '&"a\\"b\\\\c"' in tres


def test_requires_list_frames():
    with pytest.raises(ValueError, match="must be a list"):
        godot.build_spriteframes({"frames": {"0": {}}}, texture_res_path="res://x.png")


def test_empty_frames_rejected():
    with pytest.raises(ValueError, match="no frames"):
        godot.build_spriteframes({"frames": []}, texture_res_path="res://x.png")
