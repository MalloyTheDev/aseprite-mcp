"""Integration tests for the batch op-runner. Require Aseprite (--run-aseprite)."""

import pytest

from aseprite_mcp.core.runner import LuaToolError
from aseprite_mcp.tools import batch, drawing, inspect, sprite


def test_dry_run_does_not_touch_file_and_returns_plan():
    sprite.create_sprite("b/dry.aseprite", 8, 8, "rgb")
    before = inspect.get_pixels("b/dry.aseprite", 0, 0, 8, 8)["pixels"]
    m = batch.apply_operations(
        "b/dry.aseprite",
        [{"op": "fill_layer", "args": {"color": "#ff0000"}}],
        dry_run=True,
    )
    assert m["kind"] == "batch" and m["dry_run"] is True
    assert m["operations"][0]["status"] == "planned"
    after = inspect.get_pixels("b/dry.aseprite", 0, 0, 8, 8)["pixels"]
    assert before == after  # nothing changed


def test_batch_applies_in_one_process_with_carried_state():
    # add a layer, then draw on that same new layer — proves ops see earlier ops.
    sprite.create_sprite("b/chain.aseprite", 16, 16, "rgb")
    m = batch.apply_operations("b/chain.aseprite", [
        {"op": "add_layer", "args": {"name": "fg"}},
        {"op": "fill_layer", "args": {"layer": "fg", "color": "#00ff00"}},
        {"op": "draw_rectangle",
         "args": {"layer": "fg", "x": 2, "y": 2, "width": 4, "height": 4, "color": "#ff0000"}},
        {"op": "add_frame", "args": {"duration_ms": 120, "copy_from": 1}},
        {"op": "add_tag", "args": {"name": "loop", "from": 1, "to": 2}},
    ])
    assert m["kind"] == "batch"
    assert [o["status"] for o in m["operations"]] == ["applied"] * 5
    assert "fg" in m["sprite"]["layers"]
    assert m["sprite"]["frames"] == 2
    assert m["sprite"]["tags"][0]["name"] == "loop"
    px = inspect.get_pixels("b/chain.aseprite", 0, 0, 16, 16)["pixels"]
    assert px[2][2] == "#ff0000ff"  # the red rectangle's outline (top-left corner)
    assert px[3][3] == "#00ff00ff"  # interior of the outline -> the green fill
    assert px[0][0] == "#00ff00ff"  # the green fill


def test_batch_matches_individual_calls():
    ops = [
        {"op": "fill_layer", "args": {"color": "#102030"}},
        {"op": "draw_rectangle",
         "args": {"x": 1, "y": 1, "width": 5, "height": 5, "color": "#ffaa00"}},
        {"op": "set_pixel", "args": {"x": 7, "y": 7, "color": "#00ffff"}},
    ]
    sprite.create_sprite("b/batched.aseprite", 8, 8, "rgb")
    batch.apply_operations("b/batched.aseprite", ops)

    sprite.create_sprite("b/manual.aseprite", 8, 8, "rgb")
    drawing.fill_layer("b/manual.aseprite", "#102030")
    drawing.draw_rectangle("b/manual.aseprite", 1, 1, 5, 5, "#ffaa00", filled=False)
    drawing.draw_pixels("b/manual.aseprite", [{"x": 7, "y": 7, "color": "#00ffff"}])

    a = inspect.get_pixels("b/batched.aseprite", 0, 0, 8, 8)["pixels"]
    b = inspect.get_pixels("b/manual.aseprite", 0, 0, 8, 8)["pixels"]
    assert a == b


def test_mid_batch_failure_rolls_back_and_saves_nothing():
    sprite.create_sprite("b/atomic.aseprite", 8, 8, "rgb")
    drawing.fill_layer("b/atomic.aseprite", "#111111")
    before = inspect.get_pixels("b/atomic.aseprite", 0, 0, 8, 8)["pixels"]

    with pytest.raises(LuaToolError, match="aborted at op 1"):
        batch.apply_operations("b/atomic.aseprite", [
            {"op": "fill_layer", "args": {"color": "#00ff00"}},      # would change pixels
            {"op": "rename_layer", "args": {"layer": "ghost", "new_name": "x"}},  # op 1: no such layer
        ])

    after = inspect.get_pixels("b/atomic.aseprite", 0, 0, 8, 8)["pixels"]
    assert after == before  # rolled back: the fill from op 0 was NOT saved


def test_layers_count_unchanged_marker():
    # sanity: a no-op-ish batch (visibility toggle) still returns a valid manifest
    sprite.create_sprite("b/v.aseprite", 8, 8, "rgb")
    m = batch.apply_operations("b/v.aseprite", [
        {"op": "set_layer_visible", "args": {"layer": "Layer 1", "visible": True}},
    ])
    assert m["operations"][0]["status"] == "applied"
