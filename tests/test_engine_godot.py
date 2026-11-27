"""Pure-Python tests for the Godot 4 SpriteFrames .tres builder: no Aseprite."""

import json
import re
from copy import deepcopy

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



def _animations(tres):
    text = tres.split("animations = ", 1)[1]
    text = re.sub(r'SubResource\("AtlasTexture_(\d+)"\)', r'\1', text)
    return json.loads(text.replace('&"', '"'))


@pytest.mark.parametrize(("direction", "expected"), [
    ("forward", [1, 2, 3, 4]),
    ("reverse", [4, 3, 2, 1]),
    ("pingpong", [1, 2, 3, 4, 3, 2]),
    ("pingpong_reverse", [4, 3, 2, 1, 2, 3]),
])
def test_tag_direction_preserves_frame_identity_and_timing(direction, expected):
    data = {
        "frames": [
            {"frame": {"x": i * 8, "y": 0, "w": 8, "h": 8}, "duration": ms}
            for i, ms in enumerate([100, 80, 120, 160, 200, 100])
        ],
        "meta": {"frameTags": [{"name": "pulse", "from": 1, "to": 4, "direction": direction}]},
    }
    original = deepcopy(data)
    tres = _build(data)
    anim, = _animations(tres)
    assert [f["texture"] for f in anim["frames"]] == expected
    assert [f["duration"] / anim["speed"] for f in anim["frames"]] == pytest.approx(
        [data["frames"][i]["duration"] / 1000 for i in expected], abs=1e-6
    )
    assert anim["loop"] is True
    assert data == original
    assert re.findall(r'\[sub_resource type="AtlasTexture" id="AtlasTexture_(\d+)"\]', tres) == [
        "1", "2", "3", "4"
    ]


@pytest.mark.parametrize("direction", ["forward", "reverse", "pingpong", "pingpong_reverse"])
@pytest.mark.parametrize(("lo", "hi", "forward"), [
    (1, 1, [1]),
    (1, 2, [1, 2]),
    (-2, 1, [0, 1]),
    (2, 9, [2, 3]),
    (3, 1, []),
    (9, 10, []),
])
def test_short_and_clamped_tag_ranges(direction, lo, hi, forward):
    data = {"frames": SHEET["frames"], "meta": {"frameTags": [
        {"name": "short", "from": lo, "to": hi, "direction": direction},
    ]}}
    anim, = _animations(_build(data))
    expected = forward[::-1] if direction in {"reverse", "pingpong_reverse"} else forward
    assert [f["texture"] for f in anim["frames"]] == expected


@pytest.mark.parametrize("default_loop", [True, False])
@pytest.mark.parametrize("repeat", [None, 0, "0", 1, "1", 3, "3"])
def test_tag_repeat_controls_loop(default_loop, repeat):
    tag = {"name": "ignite", "from": 0, "to": 3}
    if repeat is not None:
        tag["repeat"] = repeat
    data = {"frames": SHEET["frames"], "meta": {"frameTags": [tag]}}
    anim, = _animations(_build(data, default_loop=default_loop))
    assert anim["loop"] is (False if repeat in (1, "1", 3, "3") else default_loop)
    assert [f["texture"] for f in anim["frames"]] == [0, 1, 2, 3]


@pytest.mark.parametrize("repeat", [1, "1", 2, "2"])
def test_finite_repeat_warnings_name_tag_and_explain_single_playback(repeat):
    data = {"frames": SHEET["frames"], "meta": {"frameTags": [
        {"name": "extinguish", "from": 0, "to": 3, "repeat": repeat},
    ]}}
    warnings = ["earlier warning"]
    _build(data, warnings=warnings)
    assert warnings[0] == "earlier warning"
    if int(repeat) == 1:
        assert warnings == ["earlier warning"]
    else:
        assert len(warnings) == 2
        assert "extinguish" in warnings[1] and str(repeat) in warnings[1]
        assert "once" in warnings[1] and "repeat count" in warnings[1]


def test_overlapping_tags_share_atlas_textures_and_keep_independent_loop_flags():
    data = {"frames": SHEET["frames"], "meta": {"frameTags": [
        {"name": "once", "from": 0, "to": 3, "direction": "reverse", "repeat": "1"},
        {"name": "cycle", "from": 1, "to": 3, "direction": "pingpong"},
    ]}}
    tres = _build(data)
    once, cycle = _animations(tres)
    assert [f["texture"] for f in once["frames"]] == [3, 2, 1, 0]
    assert [f["texture"] for f in cycle["frames"]] == [1, 2, 3, 2]
    assert once["loop"] is False and cycle["loop"] is True
    assert tres.count('[sub_resource type="AtlasTexture"') == 4
