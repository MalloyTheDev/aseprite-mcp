"""Pure-Python tests for the asset-spec schema: validate + plan (no Aseprite)."""

import json

from aseprite_mcp.core.asset_spec import SCHEMA, plan_spec, validate_spec

CHAR = {
    "schema": SCHEMA,
    "name": "hero",
    "kind": "character",
    "canvas": {"width": 32, "height": 32, "color_mode": "rgb"},
    "palette": ["#1d2b53", "#ff004d"],
    "layers": ["body", "details", "fx"],
    "animations": [
        {"name": "idle", "frame_count": 4, "duration_ms": 150, "loop": True},
        {"name": "walk", "frame_count": 6, "duration_ms": 100},
    ],
    "slices": [
        {"name": "hitbox", "type": "hitbox",
         "bounds": {"x": 8, "y": 12, "width": 16, "height": 14}, "color": "#ff0000ff"},
        {"name": "attach", "type": "attach", "id": "weapon",
         "bounds": {"x": 20, "y": 14, "width": 1, "height": 1}, "pivot": {"x": 20, "y": 14}},
    ],
    "exports": [{"format": "godot_spriteframes", "scale": 2}, {"format": "slice_metadata"}],
}


def _tools(steps):
    return [s["tool"] for s in steps]


def _one(steps, tool):
    return next(s for s in steps if s["tool"] == tool)


# ============================================================= validate_spec
def test_valid_character_passes():
    r = validate_spec(CHAR)
    assert r["passed"] and r["errors"] == []


def test_missing_name_fails():
    spec = {**CHAR}; del spec["name"]
    r = validate_spec(spec)
    assert not r["passed"] and any("name" in e for e in r["errors"])


def test_bad_kind_fails():
    r = validate_spec({**CHAR, "kind": "spaceship"})
    assert not r["passed"] and any("kind" in e for e in r["errors"])


def test_unknown_schema_fails():
    r = validate_spec({**CHAR, "schema": "something.else"})
    assert not r["passed"] and any("schema" in e for e in r["errors"])


def test_character_requires_canvas():
    spec = {**CHAR}; del spec["canvas"]
    r = validate_spec(spec)
    assert not r["passed"] and any("canvas" in e for e in r["errors"])


def test_icon_set_requires_icon_size_and_count():
    r = validate_spec({"name": "ic", "kind": "icon_set"})
    assert not r["passed"]
    assert any("icon_size" in e for e in r["errors"])
    assert any("count" in e for e in r["errors"])


def test_icon_set_does_not_require_canvas():
    r = validate_spec({"name": "ic", "kind": "icon_set", "icon_size": 16, "count": 4})
    assert r["passed"]


def test_tileset_requires_grid_fields():
    r = validate_spec({"name": "t", "kind": "tileset", "tile_size": 16})
    assert not r["passed"]
    assert any("columns" in e for e in r["errors"]) and any("rows" in e for e in r["errors"])


def test_bad_palette_colour_fails():
    r = validate_spec({**CHAR, "palette": ["#1d2b53", "notacolour"]})
    assert not r["passed"] and any("palette" in e for e in r["errors"])


def test_animation_needs_frame_count_not_frames():
    spec = {**CHAR, "animations": [{"name": "idle", "frames": 4}]}
    r = validate_spec(spec)
    assert not r["passed"]
    assert any("frame_count" in e for e in r["errors"])          # missing the real field
    assert any("frames" in w for w in r["warnings"])             # 'frames' ignored warning


def test_slice_needs_bounds():
    r = validate_spec({**CHAR, "slices": [{"name": "x"}]})
    assert not r["passed"] and any("bounds" in e for e in r["errors"])


def test_unknown_export_format_fails():
    r = validate_spec({**CHAR, "exports": [{"format": "unreal"}]})
    assert not r["passed"] and any("format" in e for e in r["errors"])


def test_animations_on_grid_kind_warns_not_fails():
    spec = {"name": "ic", "kind": "icon_set", "icon_size": 16, "count": 4,
            "animations": [{"name": "idle", "frame_count": 2}]}
    r = validate_spec(spec)
    assert r["passed"]                                            # ignored, not fatal
    assert any("ignored" in w for w in r["warnings"])


# ================================================================== plan_spec
def test_plan_character_step_order():
    steps = plan_spec(CHAR)
    assert _tools(steps) == [
        "create_character_sprite", "set_palette", "apply_operations",
        "add_slice", "add_slice", "export_godot_spriteframes", "export_slice_metadata",
    ]


def test_plan_create_is_structure_only():
    create = _one(plan_spec(CHAR), "create_character_sprite")
    assert create["args"]["with_placeholder"] is False
    assert create["args"]["width"] == 32 and create["args"]["height"] == 32


def test_plan_never_emits_drawing_tools():
    tools = _tools(plan_spec(CHAR))
    assert not any(t.startswith("draw_") or t in ("set_pixel", "fill_layer") for t in tools)


def test_plan_layers_skip_scaffold_defaults():
    ops = _one(plan_spec(CHAR), "apply_operations")["args"]["operations"]
    added = [o["args"]["name"] for o in ops if o["op"] == "add_layer"]
    assert added == ["fx"]            # body/details already made by the scaffold


def test_plan_animations_to_frames_and_tags():
    ops = _one(plan_spec(CHAR), "apply_operations")["args"]["operations"]
    add_frames = [o for o in ops if o["op"] == "add_frame"]
    assert len(add_frames) == 9       # total 10 frames, frame 1 already exists
    tags = {o["args"]["name"]: (o["args"]["from"], o["args"]["to"])
            for o in ops if o["op"] == "add_tag"}
    assert tags == {"idle": (1, 4), "walk": (5, 10)}
    durs = {o["args"]["frame"]: o["args"]["duration_ms"]
            for o in ops if o["op"] == "set_frame_duration"}
    assert durs[1] == 150 and durs[4] == 150 and durs[5] == 100 and durs[10] == 100


def test_plan_slice_encodes_type_and_geometry():
    steps = plan_spec(CHAR)
    hitbox = next(s for s in steps if s["tool"] == "add_slice" and s["args"]["name"] == "hitbox")
    assert json.loads(hitbox["args"]["data"]) == {"type": "hitbox"}
    assert hitbox["args"]["color"] == "#ff0000ff"
    attach = next(s for s in steps if s["tool"] == "add_slice" and s["args"]["name"] == "attach")
    assert json.loads(attach["args"]["data"]) == {"type": "attach", "id": "weapon"}
    assert attach["args"]["pivot_x"] == 20 and attach["args"]["pivot_y"] == 14


def test_plan_export_defaults_and_scale():
    steps = plan_spec(CHAR)
    godot = _one(steps, "export_godot_spriteframes")
    assert godot["args"]["output"] == "hero.tres" and godot["args"]["scale"] == 2
    slicemeta = _one(steps, "export_slice_metadata")
    assert slicemeta["args"]["output"] == "hero_slices.json"


def test_plan_walk8dir_uses_template_and_ignores_animations():
    spec = {"name": "w", "kind": "walk_8dir",
            "canvas": {"width": 16, "height": 16},
            "frames_per_direction": 3,
            "animations": [{"name": "ignored", "frame_count": 2}]}
    steps = plan_spec(spec)
    assert _tools(steps) == ["create_character_sprite", "make_8_direction_walk_template"]
    tmpl = _one(steps, "make_8_direction_walk_template")
    assert tmpl["args"]["frames_per_direction"] == 3


def test_plan_enemy_default_base_color_differs():
    steps = plan_spec({**CHAR, "kind": "enemy", "name": "slime"})
    assert _one(steps, "create_character_sprite")["args"]["base_color"] == "#c83737"


def test_plan_icon_set_scaffold():
    steps = plan_spec({"name": "ic", "kind": "icon_set", "icon_size": 16, "count": 6, "columns": 3})
    assert _tools(steps)[0] == "create_icon_set"
    assert _one(steps, "create_icon_set")["args"] == {
        "name": "ic", "icon_size": 16, "count": 6, "columns": 3
    }
