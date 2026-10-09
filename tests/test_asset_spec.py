"""Pure-Python tests for the asset-spec schema: validate + plan (no Aseprite)."""

import json

import pytest

from aseprite_mcp.core import config as core_config
from aseprite_mcp.core.asset_spec import (
    MAX_SPEC_ANIMATION_FRAMES,
    MAX_SPEC_EXPORTS,
    MAX_SPEC_LAYERS,
    MAX_SPEC_SLICES,
    MAX_SPEC_TOTAL_FRAMES,
    SCHEMA,
    _layer_and_animation_ops,
    _planned_operation_count,
    compare_to_built,
    plan_spec,
    sprite_filename,
    validate_spec,
)
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import (
    MAX_BATCH_OPERATIONS,
    MAX_FRAMES_PER_DIRECTION,
    MAX_GRID_CELLS,
    check_canvas_size,
)
from aseprite_mcp.tools import asset_spec as asset_spec_tools
from aseprite_mcp.tools.workflow import _aseprite_name

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
    spec = {**CHAR}
    del spec["name"]
    r = validate_spec(spec)
    assert not r["passed"] and any("name" in e for e in r["errors"])


def test_bad_kind_fails():
    r = validate_spec({**CHAR, "kind": "spaceship"})
    assert not r["passed"] and any("kind" in e for e in r["errors"])


def test_unknown_schema_fails():
    r = validate_spec({**CHAR, "schema": "something.else"})
    assert not r["passed"] and any("schema" in e for e in r["errors"])


def test_character_requires_canvas():
    spec = {**CHAR}
    del spec["canvas"]
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


# ==================================== canvas limits (validate vs build agree)
def test_canvas_over_the_real_limit_fails():
    r = validate_spec({**CHAR, "canvas": {"width": 65535, "height": 65535}})
    assert not r["passed"]
    assert any("16384" in e for e in r["errors"])      # the real cap, not the old 65535


def test_canvas_at_max_area_passes():
    r = validate_spec({**CHAR, "canvas": {"width": 16384, "height": 1024}})
    assert r["passed"], r["errors"]                    # exactly MAX_CANVAS_PIXELS


@pytest.mark.parametrize("w,h", [(16385, 1), (1, 16385)])
def test_canvas_one_past_either_axis_fails(w, h):
    r = validate_spec({**CHAR, "canvas": {"width": w, "height": h}})
    assert not r["passed"] and any("canvas" in e for e in r["errors"])


@pytest.mark.parametrize("w,h", [
    (1, 1), (32, 32), (4096, 4096), (16384, 1024), (16384, 1025), (16385, 1),
    (1, 16385), (65535, 65535), (0, 32), (32, 0),
])
def test_validate_and_build_agree_on_canvas_limits(w, h):
    """The validator must accept exactly what the build path accepts, or it is useless."""
    try:
        check_canvas_size(w, h)
    except ValidationFailed:
        build_accepts = False
    else:
        build_accepts = True
    assert validate_spec({**CHAR, "canvas": {"width": w, "height": h}})["passed"] is build_accepts


# =========================================================== name -> filename
@pytest.mark.parametrize("name,expected", [
    ("hero", "hero.aseprite"),
    ("hero.aseprite", "hero.aseprite"),
    ("hero.ase", "hero.ase"),
])
def test_plan_targets_one_file_whatever_the_name_carries(name, expected):
    steps = plan_spec({**CHAR, "name": name})
    # The scaffold step is handed `name` and appends the extension itself, so the file the
    # build creates is _aseprite_name(name); every later step must target that same file.
    created = _aseprite_name(steps[0]["args"]["name"])
    targeted = {s["args"]["filename"] for s in steps if "filename" in s["args"]}
    assert created == expected
    assert targeted == {expected}


@pytest.mark.parametrize("name", ["hero", "hero.aseprite", "hero.ase", "hero.ASEPRITE", "a.b/hero"])
def test_sprite_filename_agrees_with_the_workflow_helper(name):
    """Two copies of the rule exist until _aseprite_name is folded into core; pin them."""
    assert sprite_filename(name) == _aseprite_name(name)


# ============================================ planned work is bounded up front
def test_plan_over_the_batch_cap_fails_validation_and_names_the_field():
    spec = {**CHAR, "animations": [{"name": "idle", "frame_count": 400}]}
    r = validate_spec(spec)
    assert not r["passed"]
    over = [e for e in r["errors"] if "structural operations" in e]
    assert over and "animations[].frame_count" in over[0]
    assert str(MAX_BATCH_OPERATIONS) in over[0]


def test_many_tiny_animations_still_hit_the_batch_cap():
    """Every field legal, the aggregate not: 240 one-frame animations plan 719 operations."""
    spec = {**CHAR, "animations": [{"name": f"a{i}", "frame_count": 1}
                                   for i in range(MAX_SPEC_TOTAL_FRAMES)]}
    r = validate_spec(spec)
    assert not r["passed"] and any("structural operations" in e for e in r["errors"])


def test_build_refuses_an_over_cap_spec_without_writing_anything():
    ws = core_config.workspace()
    before = sorted(p.name for p in ws.glob("*")) if ws.exists() else []
    spec = {**CHAR, "name": "over_cap", "animations": [{"name": "idle", "frame_count": 400}]}
    with pytest.raises(ValidationFailed, match="Invalid asset spec"):
        asset_spec_tools.build_asset_from_spec(spec)
    after = sorted(p.name for p in ws.glob("*")) if ws.exists() else []
    assert after == before


@pytest.mark.parametrize("count,passes", [
    (MAX_SPEC_ANIMATION_FRAMES, True), (MAX_SPEC_ANIMATION_FRAMES + 1, False),
])
def test_frame_count_cap(count, passes):
    r = validate_spec({**CHAR, "animations": [{"name": "idle", "frame_count": count}]})
    assert r["passed"] is passes, r["errors"]
    if not passes:
        assert any("frame_count" in e and str(MAX_SPEC_ANIMATION_FRAMES) in e for e in r["errors"])


@pytest.mark.parametrize("total,passes", [(MAX_SPEC_TOTAL_FRAMES, True), (MAX_SPEC_TOTAL_FRAMES + 1, False)])
def test_total_frames_cap(total, passes):
    half = total // 2
    anims = [{"name": "a", "frame_count": half}, {"name": "b", "frame_count": total - half}]
    r = validate_spec({**CHAR, "animations": anims})
    assert r["passed"] is passes, r["errors"]
    if not passes:
        assert any("totals" in e and str(MAX_SPEC_TOTAL_FRAMES) in e for e in r["errors"])


@pytest.mark.parametrize("n,passes", [(MAX_SPEC_LAYERS, True), (MAX_SPEC_LAYERS + 1, False)])
def test_layers_cap(n, passes):
    spec = {**CHAR, "animations": [], "layers": [f"l{i}" for i in range(n)]}
    r = validate_spec(spec)
    assert r["passed"] is passes, r["errors"]
    if not passes:
        assert any("layers" in e and str(MAX_SPEC_LAYERS) in e for e in r["errors"])


@pytest.mark.parametrize("n,passes", [(MAX_SPEC_SLICES, True), (MAX_SPEC_SLICES + 1, False)])
def test_slices_cap(n, passes):
    slices = [{"name": f"s{i}", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1}}
              for i in range(n)]
    r = validate_spec({**CHAR, "slices": slices})
    assert r["passed"] is passes, r["errors"]
    if not passes:
        assert any("slices" in e and str(MAX_SPEC_SLICES) in e for e in r["errors"])


@pytest.mark.parametrize("n,passes", [(MAX_SPEC_EXPORTS, True), (MAX_SPEC_EXPORTS + 1, False)])
def test_exports_cap(n, passes):
    r = validate_spec({**CHAR, "exports": [{"format": "png"}] * n})
    assert r["passed"] is passes, r["errors"]
    if not passes:
        assert any("exports" in e and str(MAX_SPEC_EXPORTS) in e for e in r["errors"])


@pytest.mark.parametrize("spec", [
    CHAR,
    {**CHAR, "layers": ["body", "details", "fx", "shadow"]},
    {"name": "ic", "kind": "icon_set", "icon_size": 16, "count": 4, "layers": ["a", "b"]},
    {"name": "w", "kind": "walk_8dir", "canvas": {"width": 16, "height": 16}, "layers": ["x"]},
    {"name": "block/fire", "kind": "minecraft", "namespace": "mod", "category": "block",
     "layers": ["base", "glow"], "animation": {"frames": 8, "frametime": 2}},
    {"name": "block/stone", "kind": "minecraft", "namespace": "mod", "category": "block"},
])
def test_planned_operation_count_matches_the_real_plan(spec):
    """The cap is enforced on arithmetic, so it must equal what the planner really emits."""
    assert _planned_operation_count(spec, spec["kind"]) == len(
        _layer_and_animation_ops(spec, spec["kind"])
    )


# ======================================================== report shape
@pytest.mark.parametrize("spec", [
    CHAR,
    {**CHAR, "animations": [{"name": "idle", "frame_count": 2}], "slices": [
        {"name": "hitbox", "bounds": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
    {**CHAR, "animations": [{"name": "", "frame_count": 0}], "slices": [{"name": " "}]},
    {"name": "block/fire", "kind": "minecraft", "namespace": "mod", "category": "block",
     "animation": {"frames": 4}},
    {"name": "x", "kind": "nonsense"},
])
def test_every_check_entry_has_a_boolean_ok(spec):
    """Consumers read `ok` as a boolean; `isinstance(...) and s.strip()` leaks the string."""
    bad = [c for c in validate_spec(spec)["checks"] if not isinstance(c["ok"], bool)]
    assert bad == []


# ------------------------------------------------- spec caps match tool caps
# These close the gap the tool-level caps opened: a spec field that feeds a capped tool
# argument has to be checked against the same constant, or the spec validates and the
# build then fails inside the scaffold with the sprite already created.


@pytest.mark.parametrize(
    ("spec", "field"),
    [
        (
            {"schema": SCHEMA, "kind": "icon_set", "name": "i", "icon_size": 16,
             "count": MAX_GRID_CELLS + 1},
            "icon_set.count.max",
        ),
        (
            {"schema": SCHEMA, "kind": "tileset", "name": "t", "tile_size": 16,
             "columns": 64, "rows": 64},
            "tileset.cells",
        ),
        (
            {"schema": SCHEMA, "kind": "walk_8dir", "name": "w",
             "canvas": {"width": 32, "height": 32},
             "frames_per_direction": MAX_FRAMES_PER_DIRECTION + 1},
            "walk_8dir.frames_per_direction.max",
        ),
    ],
)
def test_a_spec_field_over_its_tool_cap_fails_validation(spec, field):
    result = validate_spec(spec)
    assert not result["passed"]
    assert any(c["name"] == field and not c["ok"] for c in result["checks"]), (
        f"expected a failing {field} check, got {[c['name'] for c in result['checks'] if not c['ok']]}"
    )


@pytest.mark.parametrize(
    "spec",
    [
        {"schema": SCHEMA, "kind": "icon_set", "name": "i", "icon_size": 16,
         "count": MAX_GRID_CELLS},
        {"schema": SCHEMA, "kind": "tileset", "name": "t", "tile_size": 16,
         "columns": 32, "rows": 32},
        {"schema": SCHEMA, "kind": "walk_8dir", "name": "w",
         "canvas": {"width": 32, "height": 32},
         "frames_per_direction": MAX_FRAMES_PER_DIRECTION},
    ],
)
def test_a_spec_field_exactly_at_its_tool_cap_still_validates(spec):
    """The caps must be reachable, not merely present."""
    assert validate_spec(spec)["passed"], validate_spec(spec)["errors"]


def test_tileset_cells_catches_two_individually_legal_axes():
    """64x64 cells is 4096: each axis looks fine alone, the product does not."""
    spec = {"schema": SCHEMA, "kind": "tileset", "name": "t", "tile_size": 16,
            "columns": 64, "rows": 64}
    assert not validate_spec(spec)["passed"]


# --- the loop closer: did what got built match what was asked for ----------------------


def _knight_spec() -> dict:
    return {
        "schema": "aseprite_mcp.asset_spec.v1", "name": "knight", "kind": "character",
        "canvas": {"width": 128, "height": 128},
        "layers": ["cape", "plate", "keyline"],
        "animations": [{"name": "idle", "frame_count": 4}],
        "slices": [{"name": "hitbox"}],
    }


def test_compare_to_built_passes_a_sprite_that_matches():
    observed = {
        "width": 128, "height": 128,
        "layers": [{"name": "cape"}, {"name": "plate"}, {"name": "keyline"}],
        "frames": [{"number": i} for i in range(1, 5)],
        "tags": [{"name": "idle"}], "slices": [{"name": "hitbox"}],
    }
    result = compare_to_built(_knight_spec(), observed)
    assert result["ok"]
    assert result["verifiable"]
    assert set(result["checked"]) == {"canvas", "layers", "animations", "slices"}


def test_compare_to_built_names_every_way_a_build_drifted():
    """Each of these is a real failure mode, not a hypothetical.

    The missing layer is the one that matters most: a figure shipped from this repository
    with no keyline because `add_outline` was pointed at a layer that was never created,
    and every count in the build's own result reported success. A declared layer that is
    absent from the sprite is exactly that bug, and nothing was watching for it.
    """
    drifted = {
        "width": 128, "height": 160,
        "layers": [{"name": "cape"}, {"name": "plate"}],
        "frames": [{"number": 1}, {"number": 2}],
        "tags": [], "slices": [],
    }
    result = compare_to_built(_knight_spec(), drifted)
    assert not result["ok"]
    fields = {m["field"] for m in result["mismatches"]}
    assert fields == {"canvas", "layers", "animations", "tags", "slices"}
    layer_miss = next(m for m in result["mismatches"] if m["field"] == "layers")
    assert "keyline" in layer_miss["detail"]
    # Every mismatch says what was asked for and what arrived, not just that they differ.
    for mismatch in result["mismatches"]:
        assert mismatch["declared"] is not None
        assert mismatch["detail"]


def test_a_spec_with_nothing_checkable_is_not_reported_as_passing():
    """"Nothing was wrong" and "nothing was checked" must not look the same.

    This is the shape of the session's recurring failure: a measurement that fires on
    nothing reads identically to art with no faults, and a skipped test reads identically
    to a passing one in a summary line.
    """
    result = compare_to_built(
        {"schema": "aseprite_mcp.asset_spec.v1", "name": "n", "kind": "character"},
        {"width": 64, "height": 64, "layers": [{"name": "Layer 1"}]})
    assert result["ok"]
    assert not result["verifiable"]
    assert result["checked"] == []


def test_layer_names_are_found_inside_groups():
    """A layer declared in the spec may be built inside a group, and still exists."""
    observed = {
        "width": 128, "height": 128,
        "layers": [{"name": "body", "layers": [{"name": "cape"}, {"name": "plate"}]},
                   {"name": "keyline"}],
        "frames": [{"number": i} for i in range(1, 5)],
        "tags": [{"name": "idle"}], "slices": [{"name": "hitbox"}],
    }
    assert compare_to_built(_knight_spec(), observed)["ok"]
