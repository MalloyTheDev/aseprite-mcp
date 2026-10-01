"""Integration tests for the batch op-runner. Require Aseprite (--run-aseprite)."""

import pytest

from aseprite_mcp.core.errors import AsepriteError, ValidationFailed
from aseprite_mcp.core.runner import LuaToolError
from aseprite_mcp.tools import batch, cels, drawing, frames, inspect, layers, sprite, tags
from aseprite_mcp.tools.common import resolve_path


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


# ------------------------------------------- out-of-range frames (issue #61)
def _pixels(name, size=8):
    return inspect.get_pixels(name, 0, 0, size, size)["pixels"]


def test_out_of_range_frame_is_rejected_not_clamped():
    """Issue #61 reproduction: `set_frame_duration` with frame=999 on a one-frame sprite
    used to return "set frame 999 duration" while editing frame 1."""
    sprite.create_sprite("b/f61a.aseprite", 8, 8, "rgb")
    with pytest.raises(LuaToolError, match=r"frame 999 does not exist.*numbered 1-1"):
        batch.apply_operations("b/f61a.aseprite", [
            {"op": "set_frame_duration", "args": {"frame": 999, "duration_ms": 250}},
        ])


def test_add_tag_out_of_range_range_is_rejected():
    """Issue #61 reproduction: `add_tag` with from=0, to=50000 used to answer
    "added tag 't'" having created it as (1, 1)."""
    sprite.create_sprite("b/f61b.aseprite", 8, 8, "rgb")
    # from=0 fails the 1-based check before Aseprite is launched at all.
    with pytest.raises(ValidationFailed, match="1-based frame number"):
        batch.apply_operations("b/f61b.aseprite", [
            {"op": "add_tag", "args": {"name": "t", "from": 0, "to": 50000}},
        ])
    # to=50000 needs the sprite, so it is rejected inside Aseprite, with the range.
    with pytest.raises(LuaToolError, match=r"to 50000 does not exist.*numbered 1-1"):
        batch.apply_operations("b/f61b.aseprite", [
            {"op": "add_tag", "args": {"name": "t", "from": 1, "to": 50000}},
        ])
    assert inspect.get_sprite_info("b/f61b.aseprite")["tags"] == []  # nothing created


def test_batch_summaries_report_the_frames_actually_used():
    sprite.create_sprite("b/f61c.aseprite", 8, 8, "rgb")
    m = batch.apply_operations("b/f61c.aseprite", [
        {"op": "add_frame", "args": {"duration_ms": 100}},
        {"op": "set_frame_duration", "args": {"frame": 2, "duration_ms": 250}},
        {"op": "add_tag", "args": {"name": "loop", "from": 1, "to": 2}},
    ])
    summaries = [o["summary"] for o in m["operations"]]
    assert summaries[1] == "set frame 2 duration to 250ms"
    assert summaries[2] == "added tag 'loop' on frames 1-2"
    # The manifest now agrees with the sprite.
    tag = m["sprite"]["tags"][0]
    assert (tag["from"], tag["to"]) == (1, 2)


def test_frame_rejection_still_rolls_the_whole_batch_back():
    """The frame guard raises inside the transaction, so atomicity must be unaffected:
    the file is byte-identical after a batch that fails on a frame."""
    sprite.create_sprite("b/f61d.aseprite", 8, 8, "rgb")
    drawing.fill_layer("b/f61d.aseprite", "#111111")
    path = resolve_path("b/f61d.aseprite")
    before = path.read_bytes()

    with pytest.raises(LuaToolError, match="does not exist"):
        batch.apply_operations("b/f61d.aseprite", [
            {"op": "fill_layer", "args": {"color": "#00ff00"}},        # would change pixels
            {"op": "set_frame_duration", "args": {"frame": 7, "duration_ms": 50}},  # op 1
        ])

    assert path.read_bytes() == before


def test_valid_frame_still_works():
    sprite.create_sprite("b/f61e.aseprite", 8, 8, "rgb")
    m = batch.apply_operations("b/f61e.aseprite", [
        {"op": "add_frame", "args": {"duration_ms": 100}},
        {"op": "duplicate_frame", "args": {"frame": 2}},
        {"op": "set_pixel", "args": {"frame": 3, "x": 1, "y": 1, "color": "#ff0000"}},
    ])
    assert [o["status"] for o in m["operations"]] == ["applied"] * 3
    assert m["sprite"]["frames"] == 3


# --------------------------------- op argument names / temp path (issue #62)
def test_op_accepts_the_standalone_tool_argument_spelling():
    sprite.create_sprite("b/f62a.aseprite", 8, 8, "rgb")
    m = batch.apply_operations("b/f62a.aseprite", [
        {"op": "add_frame", "args": {"duration_ms": 100}},
        {"op": "add_tag", "args": {"name": "walk", "from_frame": 1, "to_frame": 2}},
        {"op": "replace_color", "args": {"from_color": "transparent", "to_color": "#0000ff"}},
    ])
    assert [o["status"] for o in m["operations"]] == ["applied"] * 3
    assert m["sprite"]["tags"][0]["name"] == "walk"


def test_add_layer_op_can_nest_in_a_group():
    sprite.create_sprite("b/f62b.aseprite", 8, 8, "rgb")
    layers.add_group_layer("b/f62b.aseprite", "parts")
    m = batch.apply_operations("b/f62b.aseprite", [
        {"op": "add_layer", "args": {"name": "arm", "group": "parts"}},
    ])
    assert "in group 'parts'" in m["operations"][0]["summary"]


def test_batch_error_does_not_leak_the_temp_script_path():
    r"""Issue #62: the error carried `C:\...\asemcp_xxxx.lua:264:` in front of the
    message, which names a deleted temp file and a host path."""
    sprite.create_sprite("b/f62c.aseprite", 8, 8, "rgb")
    with pytest.raises(LuaToolError) as excinfo:
        batch.apply_operations("b/f62c.aseprite", [
            {"op": "rename_layer", "args": {"layer": "ghost", "new_name": "x"}},
        ])
    message = str(excinfo.value)
    assert "asemcp_" not in message and ".lua" not in message
    assert "No layer named 'ghost'" in message      # the useful part survives
    assert "Batch aborted at op 0 (rename_layer)" in message


# ------------------------------------------------------------------------------
# The standalone tools share the batch's frame guard (models.FRAME_GUARD_LUA), so the
# same contract is verified here rather than in a second Aseprite-gated file: an
# out-of-range frame is rejected with the sprite's range, never clamped.
# ------------------------------------------------------------------------------
def test_standalone_tools_reject_an_out_of_range_frame():
    sprite.create_sprite("b/f61f.aseprite", 8, 8, "rgb")
    for call in (
        lambda: frames.set_frame_duration("b/f61f.aseprite", 999, 250),
        lambda: frames.duplicate_frame("b/f61f.aseprite", 4),
        lambda: frames.add_frame("b/f61f.aseprite", copy_from=9),
        lambda: tags.add_tag("b/f61f.aseprite", "t", 1, 50000),
        lambda: cels.get_cel("b/f61f.aseprite", "Layer 1", 12),
        lambda: cels.copy_cel("b/f61f.aseprite", "Layer 1", 1, 5),
    ):
        with pytest.raises(LuaToolError, match="does not exist; the sprite has 1 frame"):
            call()
    # Nothing was applied: the sprite still has its single frame.
    assert len(inspect.get_sprite_info("b/f61f.aseprite")["frames"]) == 1


def test_standalone_tool_frame_rejection_names_the_range_and_not_the_script():
    sprite.create_sprite("b/f61g.aseprite", 8, 8, "rgb")
    frames.add_frame("b/f61g.aseprite", 100)
    with pytest.raises(LuaToolError) as excinfo:
        frames.set_frame_duration("b/f61g.aseprite", 5, 100)
    message = str(excinfo.value)
    assert "numbered 1-2" in message
    assert "asemcp_" not in message and ".lua" not in message


def test_standalone_tools_still_accept_a_valid_frame():
    sprite.create_sprite("b/f61h.aseprite", 8, 8, "rgb")
    frames.add_frame("b/f61h.aseprite", 100)
    assert frames.set_frame_duration("b/f61h.aseprite", 2, 250)["frame"] == 2
    assert tags.add_tag("b/f61h.aseprite", "loop", 2, 1)["tags"][0]["from"] == 1
    assert cels.get_cel("b/f61h.aseprite", "Layer 1", 2)["frame"] == 2


# ----------------------------------------------- cel and frame batch operations
# Animation is made of cel operations, and none of them was batchable: moving one drawn
# cel across eight frames cost eight Aseprite launches. These cover the ops that closed
# that gap, and above all that adding them did not cost atomicity.


def _animated(name: str, frames_wanted: int = 8):
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse(name, 8, 8, 3, 3, "#ff4040", filled=True)
    for _ in range(frames_wanted - 1):
        frames.add_frame(name)
    for f in range(2, frames_wanted + 1):
        cels.copy_cel(name, "Layer 1", 1, f)
    return name


def test_batched_cel_motion_matches_one_call_per_frame(request):
    """The batch has to be a faster route to the same sprite, not a different one."""
    per_call = _animated(f"b/{request.node.name}_a.aseprite")
    batched = _animated(f"b/{request.node.name}_b.aseprite")

    for f in range(1, 9):
        cels.set_cel_position(per_call, "Layer 1", f, (f - 1) * 3, (f - 1) * 2)

    batch.apply_operations(batched, [
        {"op": "set_cel_position",
         "args": {"layer": "Layer 1", "frame": f, "x": (f - 1) * 3, "y": (f - 1) * 2}}
        for f in range(1, 9)
    ])

    for f in range(1, 9):
        a = cels.get_cel(per_call, "Layer 1", f)["position"]
        b = cels.get_cel(batched, "Layer 1", f)["position"]
        assert (a["x"], a["y"]) == (b["x"], b["y"]), f"frame {f}: {a} vs {b}"


def test_every_new_operation_applies_in_one_batch(request):
    name = _animated(f"b/{request.node.name}.aseprite")

    result = batch.apply_operations(name, [
        {"op": "set_all_frame_durations", "args": {"duration_ms": 80}},
        {"op": "set_cel_opacity", "args": {"layer": "Layer 1", "frame": 3, "opacity": 128}},
        {"op": "draw_pixels",
         "args": {"pixels": [{"x": 1, "y": 1}, {"x": 2, "y": 2}], "color": "#00ff00",
                  "frame": 1}},
        {"op": "copy_cel", "args": {"layer": "Layer 1", "from_frame": 1, "to_frame": 8}},
        {"op": "delete_cel", "args": {"layer": "Layer 1", "frame": 7}},
        {"op": "remove_frame", "args": {"frame": 6}},
    ])

    assert [o["status"] for o in result["operations"]] == ["applied"] * 6
    info = inspect.get_sprite_info(name)
    assert info["frameCount"] == 7
    assert info["frames"][0]["duration"] == pytest.approx(0.08)


def test_copy_cel_accepts_the_standalone_tool_spelling(request):
    """from_frame/to_frame are aliases, because renaming would break working calls."""
    name = _animated(f"b/{request.node.name}.aseprite", 3)
    canonical = batch.apply_operations(name, [
        {"op": "copy_cel", "args": {"layer": "Layer 1", "from": 1, "to": 2}},
    ])
    aliased = batch.apply_operations(name, [
        {"op": "copy_cel", "args": {"layer": "Layer 1", "from_frame": 1, "to_frame": 3}},
    ])
    assert canonical["operations"][0]["status"] == "applied"
    assert aliased["operations"][0]["status"] == "applied"


def test_a_failing_cel_op_rolls_the_whole_batch_back(request):
    """The property that makes batching safe to reach for. Re-checked because these
    operations mutate frame structure, not just pixels."""
    import hashlib

    from aseprite_mcp.tools.common import resolve_path

    name = _animated(f"b/{request.node.name}.aseprite", 4)
    path = resolve_path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    mtime = path.stat().st_mtime_ns

    with pytest.raises(AsepriteError, match="does not exist"):
        batch.apply_operations(name, [
            {"op": "set_cel_position", "args": {"layer": "Layer 1", "frame": 1, "x": 9, "y": 9}},
            {"op": "set_cel_opacity", "args": {"layer": "Layer 1", "frame": 2, "opacity": 10}},
            {"op": "delete_cel", "args": {"layer": "Layer 1", "frame": 99}},
        ])

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert path.stat().st_mtime_ns == mtime
    position = cels.get_cel(name, "Layer 1", 1)["position"]
    assert (position["x"], position["y"]) == (0, 0), "the first op must have rolled back"


def test_draw_pixels_in_a_batch_is_capped_per_operation(request):
    """The batch cap counts operations, so one op carrying a huge list would slip past."""
    from aseprite_mcp.core.limits import MAX_PIXEL_LIST_LENGTH

    name = _animated(f"b/{request.node.name}.aseprite", 2)
    too_many = [{"x": 0, "y": 0}] * (MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match="maximum"):
        batch.apply_operations(name, [
            {"op": "draw_pixels", "args": {"pixels": too_many, "color": "#ff0000"}},
        ])


def test_draw_pixels_in_a_batch_rejects_a_malformed_entry(request):
    """Refused before Aseprite is launched, so the message names the problem."""
    name = _animated(f"b/{request.node.name}.aseprite", 2)
    with pytest.raises(ValidationFailed, match="pixels"):
        batch.apply_operations(name, [
            {"op": "draw_pixels", "args": {"pixels": [{"x": 1}], "color": "#ff0000"}},
        ])
    with pytest.raises(ValidationFailed, match="non-empty"):
        batch.apply_operations(name, [
            {"op": "draw_pixels", "args": {"pixels": [], "color": "#ff0000"}},
        ])


def test_a_cel_operation_on_a_missing_cel_says_which(request):
    name = _animated(f"b/{request.node.name}.aseprite", 3)
    batch.apply_operations(name, [
        {"op": "delete_cel", "args": {"layer": "Layer 1", "frame": 2}},
    ])
    with pytest.raises(AsepriteError, match="no cel on frame 2"):
        batch.apply_operations(name, [
            {"op": "set_cel_position", "args": {"layer": "Layer 1", "frame": 2, "x": 1, "y": 1}},
        ])


@pytest.mark.pure
def test_the_generated_reference_lists_the_new_operations():
    """The docstring is generated from OP_SPECS, so it cannot drift from the registry."""
    from aseprite_mcp.core import oplib

    reference = oplib.operations_reference()
    for op in ("set_cel_position", "set_cel_opacity", "copy_cel", "delete_cel",
               "draw_pixels", "remove_frame", "set_all_frame_durations"):
        assert op in reference, f"{op} is registered but undocumented"
