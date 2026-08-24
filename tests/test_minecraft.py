"""Pure-Python tests for the Minecraft domain: spec validation, planning, metadata,
and tiling-seam analysis (no Aseprite)."""

import math
import random

import pytest

from aseprite_mcp.core.asset_spec import SCHEMA, plan_spec, validate_spec
from aseprite_mcp.core.minecraft import (
    MS_PER_TICK,
    PACK_FORMATS,
    animation_mcmeta,
    evaluate_texture,
    evaluate_tiling,
    is_power_of_two,
    pack_mcmeta,
    resolve_pack_format,
    texture_rel_path,
)

BLOCK = {
    "schema": SCHEMA,
    "name": "copper_grate",
    "kind": "minecraft",
    "namespace": "mcsimcolony",
    "category": "block",
    "texture_size": 16,
    "tiling": True,
    "animation": {"frames": 4, "frametime": 3, "interpolate": False},
    "layers": ["base", "grime"],
    "palette": ["#2b1d17", "#7a4a2b", "#c98a4b"],
    "exports": [{"format": "minecraft_texture", "pack_root": "packs/mcsc"}],
}


def _tools(steps):
    return [s["tool"] for s in steps]


def _one(steps, tool):
    return next(s for s in steps if s["tool"] == tool)


def _grid(fn, w=16, h=16):
    return [[fn(x, y) for x in range(w)] for y in range(h)]


def _hex(r, g, b, a=255):
    return f"#{r:02x}{g:02x}{b:02x}{a:02x}"


# ============================================================= spec validation
def test_valid_block_spec_passes():
    r = validate_spec(BLOCK)
    assert r["passed"] and r["errors"] == []


def test_uppercase_name_is_rejected():
    # Uppercase resource locations load from a folder and 404 from a zip — the classic
    # Windows-authored-pack bug, which is exactly why it must fail at spec time.
    r = validate_spec({**BLOCK, "name": "CopperGrate"})
    assert not r["passed"]
    assert any("resource path" in e for e in r["errors"])


def test_subdirectory_name_is_allowed():
    assert validate_spec({**BLOCK, "name": "machines/press_top"})["passed"]


@pytest.mark.parametrize("bad", ["My_Pack", "pack space", "PACK"])
def test_invalid_namespace_rejected(bad):
    r = validate_spec({**BLOCK, "namespace": bad})
    assert not r["passed"] and any("namespace" in e for e in r["errors"])


def test_vanilla_namespace_warns_but_passes():
    r = validate_spec({**BLOCK, "namespace": "minecraft"})
    assert r["passed"]
    assert any("overrides vanilla" in w for w in r["warnings"])


def test_unknown_category_rejected():
    r = validate_spec({**BLOCK, "category": "blocks"})  # plural: the common typo
    assert not r["passed"] and any("category" in e for e in r["errors"])


@pytest.mark.parametrize("size", [12, 20, 24, 100])
def test_non_power_of_two_size_rejected(size):
    r = validate_spec({**BLOCK, "texture_size": size})
    assert not r["passed"] and any("power of two" in e for e in r["errors"])


@pytest.mark.parametrize("size", [8, 16, 32, 64, 128])
def test_power_of_two_sizes_accepted(size):
    assert validate_spec({**BLOCK, "texture_size": size})["passed"]


def test_high_resolution_warns():
    r = validate_spec({**BLOCK, "texture_size": 256})
    assert r["passed"] and any("atlas memory" in w for w in r["warnings"])


def test_single_frame_animation_rejected():
    r = validate_spec({**BLOCK, "animation": {"frames": 1}})
    assert not r["passed"] and any("just a static texture" in e for e in r["errors"])


def test_frame_order_index_out_of_range_rejected():
    spec = {**BLOCK, "animation": {"frames": 4, "frame_order": [0, 1, 9]}}
    r = validate_spec(spec)
    assert not r["passed"] and any("frame_order" in e for e in r["errors"])


def test_frame_order_objects_accepted():
    spec = {**BLOCK, "animation": {"frames": 4,
                                   "frame_order": [0, {"index": 1, "time": 6}, 2, 3]}}
    assert validate_spec(spec)["passed"]


def test_tiling_on_non_tiling_category_warns():
    r = validate_spec({**BLOCK, "category": "item", "tiling": True})
    assert r["passed"] and any("does not repeat" in w for w in r["warnings"])


def test_minecraft_export_rejected_on_other_kinds():
    spec = {
        "schema": SCHEMA, "name": "hero", "kind": "character",
        "canvas": {"width": 32, "height": 32},
        "exports": [{"format": "minecraft_texture", "pack_root": "p"}],
    }
    r = validate_spec(spec)
    assert not r["passed"] and any("only valid for kind" in e for e in r["errors"])


def test_export_without_pack_root_rejected():
    r = validate_spec({**BLOCK, "exports": [{"format": "minecraft_texture"}]})
    assert not r["passed"] and any("pack_root" in e for e in r["errors"])


def test_canvas_is_ignored_and_says_why():
    r = validate_spec({**BLOCK, "canvas": {"width": 99, "height": 99}})
    assert r["passed"] and any("texture_size" in w for w in r["warnings"])


# ============================================================= planning
def test_plan_scaffolds_square_canvas_not_a_strip():
    # The strip is produced at export time. A hand-built 16x64 canvas cannot be previewed
    # as an animation and breaks the moment the frame count changes.
    step = _one(plan_spec(BLOCK), "create_sprite")
    assert step["args"]["width"] == step["args"]["height"] == 16


def test_plan_adds_one_aseprite_frame_per_animation_frame():
    ops = _one(plan_spec(BLOCK), "apply_operations")["args"]["operations"]
    assert sum(1 for o in ops if o["op"] == "add_frame") == 3  # frame 1 already exists


def test_plan_converts_frametime_ticks_to_milliseconds():
    ops = _one(plan_spec(BLOCK), "apply_operations")["args"]["operations"]
    durations = {o["args"]["duration_ms"] for o in ops
                 if o["op"] in ("add_frame", "set_frame_duration")}
    # Hard-coded, not `3 * MS_PER_TICK`: expressing the expectation in terms of the
    # constant under test makes the assertion move with the bug and never fail.
    assert durations == {150}  # 3 ticks x 50 ms


def test_ms_per_tick_matches_the_game():
    assert MS_PER_TICK == 50  # 20 ticks per second


def test_plan_tags_every_frame():
    ops = _one(plan_spec(BLOCK), "apply_operations")["args"]["operations"]
    tag = next(o for o in ops if o["op"] == "add_tag")["args"]
    assert (tag["from"], tag["to"]) == (1, 4)


def test_static_texture_plans_no_frames():
    spec = {k: v for k, v in BLOCK.items() if k != "animation"}
    steps = plan_spec(spec)
    ops = _one(steps, "apply_operations")["args"]["operations"]
    assert not any(o["op"] in ("add_frame", "add_tag") for o in ops)


def test_plan_export_carries_pack_location_and_animation():
    args = _one(plan_spec(BLOCK), "export_minecraft_texture")["args"]
    assert args["pack_root"] == "packs/mcsc"
    assert args["namespace"] == "mcsimcolony"
    assert args["category"] == "block"
    assert args["frametime"] == 3


def test_plan_order_is_create_then_structure_then_export():
    tools = _tools(plan_spec(BLOCK))
    assert tools.index("create_sprite") < tools.index("apply_operations")
    assert tools.index("apply_operations") < tools.index("export_minecraft_texture")


# ============================================================= paths & metadata
def test_texture_rel_path():
    assert (texture_rel_path("mcsc", "block", "copper_grate")
            == "assets/mcsc/textures/block/copper_grate.png")


def test_pack_format_from_known_version():
    assert resolve_pack_format("1.21.1") == 34
    assert resolve_pack_format("1.21.1") == PACK_FORMATS["1.21.1"]


def test_unknown_version_refuses_to_guess():
    # Guessing produces a pack the game rejects as incompatible, with no useful message.
    with pytest.raises(ValueError, match="Unknown Minecraft version"):
        resolve_pack_format("1.99.0")


def test_explicit_pack_format_overrides_version():
    assert resolve_pack_format("1.21.1", pack_format=64) == 64


def test_pack_mcmeta_shape():
    doc = pack_mcmeta(34, "MC_Sim_Colony textures")
    assert doc["pack"]["pack_format"] == 34
    assert doc["pack"]["description"] == "MC_Sim_Colony textures"
    assert "supported_formats" not in doc["pack"]


def test_pack_mcmeta_supported_range():
    doc = pack_mcmeta(34, supported_formats={"min_inclusive": 32, "max_inclusive": 42})
    assert doc["pack"]["supported_formats"] == {"min_inclusive": 32, "max_inclusive": 42}


def test_animation_mcmeta_omits_defaults():
    # The game reads {"animation": {}} as "1 tick, no interpolation"; restating defaults
    # is noise in a file people hand-edit.
    assert animation_mcmeta() == {"animation": {}}


def test_animation_mcmeta_emits_set_values():
    doc = animation_mcmeta(frametime=3, interpolate=True)["animation"]
    assert doc == {"frametime": 3, "interpolate": True}


def test_animation_mcmeta_frame_order_mixed_forms():
    doc = animation_mcmeta(frametime=2, frame_order=[0, {"index": 1, "time": 6}])["animation"]
    assert doc["frames"] == [0, {"index": 1, "time": 6}]


def test_animation_mcmeta_frame_order_defaults_time_to_frametime():
    doc = animation_mcmeta(frametime=5, frame_order=[{"index": 2}])["animation"]
    assert doc["frames"] == [{"index": 2, "time": 5}]


@pytest.mark.parametrize("n,expected", [(1, True), (16, True), (64, True),
                                        (0, False), (12, False), (100, False)])
def test_is_power_of_two(n, expected):
    assert is_power_of_two(n) is expected


# ============================================================= tiling seams
def test_flat_texture_is_seamless():
    r = evaluate_tiling(_grid(lambda x, y: _hex(90, 60, 40)))
    assert r["horizontal"]["verdict"] == r["vertical"]["verdict"] == "seamless"


def test_horizontal_ramp_is_a_seam_on_one_axis_only():
    r = evaluate_tiling(_grid(lambda x, y: _hex(x * 16, x * 16, x * 16)))
    assert r["horizontal"]["verdict"] == "seam"
    assert r["vertical"]["verdict"] == "seamless"


def test_vertical_ramp_is_a_seam_on_the_other_axis():
    r = evaluate_tiling(_grid(lambda x, y: _hex(y * 16, y * 16, y * 16)))
    assert r["vertical"]["verdict"] == "seam"
    assert r["horizontal"]["verdict"] == "seamless"


def test_sine_tile_that_wraps_is_not_flagged():
    # A full sine period wraps perfectly, but its steepest transition IS at the wrap.
    # Judged against the mean alone this reads as an outlier; it is correct art.
    rows = _grid(lambda x, y: _hex(*(int(128 + 100 * math.sin(2 * math.pi * x / 16)),) * 3))
    assert evaluate_tiling(rows)["horizontal"]["verdict"] == "seamless"


def test_noise_is_not_flagged():
    rng = random.Random(7)
    rows = _grid(lambda x, y: _hex(*(rng.randrange(256),) * 3))
    r = evaluate_tiling(rows)
    assert r["horizontal"]["verdict"] == r["vertical"]["verdict"] == "seamless"


def test_transparent_pixels_with_junk_rgb_are_not_a_seam():
    # Aseprite keeps RGB under erased pixels; comparing it raw reports a seam between two
    # invisible edges. The junk must be *structured* (a ramp that slams back at the wrap)
    # for this to bite — random junk averages out and would pass without premultiplying,
    # which is a test that cannot fail rather than a test that passes.
    rows = _grid(lambda x, y: _hex(x * 16, x * 16, x * 16, 0))
    r = evaluate_tiling(rows)["horizontal"]
    assert r["wrap_distance"] == 0.0  # fully transparent: nothing is visible to seam
    assert r["verdict"] == "seamless"


def test_edge_stripe_tiles_into_a_pattern_not_a_seam():
    # One bright edge column is already adjacent to a dark column inside the texture, so
    # tiling introduces no transition that was not already there.
    rows = _grid(lambda x, y: _hex(240, 240, 240) if x == 15 else _hex(40, 40, 40))
    r = evaluate_tiling(rows)["horizontal"]
    assert r["ratio"] > 4.0 and r["verdict"] == "seamless"  # outlier by ratio, still fine


def test_real_seam_still_fires_alongside_strong_internal_detail():
    # The guard against false positives must not suppress true ones.
    def planks(x, y):
        if x == 8:
            return _hex(100, 85, 60)
        return _hex(60, 50, 40) if x < 8 else _hex(220, 190, 140)

    r = evaluate_tiling(_grid(planks))["horizontal"]
    assert r["verdict"] == "seam" and r["exceeds_peak_interior"]


def test_tiling_thresholds_are_adjustable():
    rows = _grid(lambda x, y: _hex(x * 16, x * 16, x * 16))
    assert evaluate_tiling(rows, error_ratio=100.0)["horizontal"]["verdict"] == "suspect"


def test_tiny_texture_cannot_be_judged():
    with pytest.raises(ValueError, match="at least 3x3"):
        evaluate_tiling(_grid(lambda x, y: _hex(0, 0, 0), w=2, h=2))


def test_ragged_rows_rejected():
    with pytest.raises(ValueError, match="ragged"):
        evaluate_tiling([["#000000ff", "#000000ff"], ["#000000ff"]])


# ============================================================= texture validation
def _info(width=16, height=16, frames=1, palette=None):
    info = {"width": width, "height": height, "frameCount": frames,
            "colorMode": "rgb", "layers": [], "tags": []}
    if palette is not None:
        info["paletteSize"] = palette
    return info


def test_valid_texture_passes():
    assert evaluate_texture(_info(), category="block", texture_size=16)["passed"]


def test_non_square_frame_fails():
    r = evaluate_texture(_info(width=16, height=8))
    assert not r["passed"] and any("square" in e for e in r["errors"])


def test_non_power_of_two_fails():
    r = evaluate_texture(_info(width=12, height=12))
    assert not r["passed"] and any("power of two" in e for e in r["errors"])


def test_declared_size_mismatch_fails():
    r = evaluate_texture(_info(width=32, height=32), texture_size=16)
    assert not r["passed"] and any("texture_size" in e for e in r["errors"])


def test_frame_count_mismatch_fails():
    r = evaluate_texture(_info(frames=3), expected_frames=4)
    assert not r["passed"] and any("frame" in e for e in r["errors"])


def test_animated_texture_without_sidecar_fails():
    r = evaluate_texture(_info(frames=4), has_mcmeta=False)
    assert not r["passed"] and any("mcmeta" in e for e in r["errors"])


def test_static_texture_needs_no_sidecar():
    assert evaluate_texture(_info(frames=1), has_mcmeta=False)["passed"]


def test_palette_budget_warns_but_passes():
    r = evaluate_texture(_info(palette=64), max_palette_size=32)
    assert r["passed"] and any("palette" in w for w in r["warnings"])


def test_seam_in_any_frame_fails_the_texture():
    ramp = evaluate_tiling(_grid(lambda x, y: _hex(x * 16, x * 16, x * 16)))
    clean = evaluate_tiling(_grid(lambda x, y: _hex(90, 60, 40)))
    r = evaluate_texture(_info(frames=2), tiling=True, frame_tilings=[clean, ramp])
    assert not r["passed"]
    assert any("tiling.frame2.horizontal" in c["name"] for c in r["checks"] if not c["ok"])


def test_seam_check_skipped_when_not_tiling():
    ramp = evaluate_tiling(_grid(lambda x, y: _hex(x * 16, x * 16, x * 16)))
    assert evaluate_texture(_info(), tiling=False, frame_tilings=[ramp])["passed"]
