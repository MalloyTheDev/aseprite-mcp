"""Integration tests for validate_loop: require Aseprite (--run-aseprite).

The fixtures are deliberately broken animations. Each fault below was found in a real
8-frame bouncing ball built with this server's own tools, and none of it was reported by
anything: frames 1 and 8 byte-identical, frames 4 and 5 identical, uniform timing, and a
squash that lifted the contact row at the moment of impact.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import (
    animation,
    batch,
    cels,
    drawing,
    frames,
    inspect,
    layers,
    sprite,
    tags,
)


def _ball(name: str, count: int = 8) -> str:
    sprite.create_sprite(name, 64, 64)
    drawing.draw_ellipse(name, 32, 8, 6, 6, "#ff5050", filled=True)
    for _ in range(count - 1):
        frames.add_frame(name)
    for f in range(2, count + 1):
        cels.copy_cel(name, "Layer 1", 1, f)
    return name


def _move(name: str, ys: list[int]) -> None:
    batch.apply_operations(name, [
        {"op": "set_cel_position",
         "args": {"layer": "Layer 1", "frame": n + 1, "x": 0, "y": y}}
        for n, y in enumerate(ys)
    ])


def failed(result: dict) -> set[str]:
    return {c["name"] for c in result["validation"]["checks"] if not c["ok"]}


# ------------------------------------------------------------------ the broken bounce
def test_the_broken_bounce_reports_every_fault(request):
    name = _ball(f"a/{request.node.name}.aseprite")
    # Symmetric arc: the last pose returns to the first, and the peak is held by
    # repeating a frame instead of lengthening one.
    _move(name, [0, 10, 22, 34, 34, 22, 10, 0])

    result = animation.validate_loop(name)

    assert result["validation"]["passed"] is False
    assert {"no_seam_duplicate", "no_duplicate_adjacent_frames",
            "timing_varies", "contact_edge_stable"} <= failed(result)
    measured = result["animation"]
    assert measured["seam_duplicate"] is True
    assert measured["duplicate_pairs"] == [[4, 5]]
    assert measured["uniform_timing"] is True
    assert measured["contact_drift_px"] == 34
    assert measured["frame_count"] == 8


def test_each_fault_names_what_to_do_about_it(request):
    name = _ball(f"a/{request.node.name}.aseprite")
    _move(name, [0, 10, 22, 34, 34, 22, 10, 0])
    result = animation.validate_loop(name)
    actions = " ".join(result["suggested_next_actions"])
    assert "remove_frame(frame=8)" in actions      # the wrap frame
    assert "remove_frame(frame=5)" in actions      # the repeated peak
    assert "set_frame_duration" in actions         # hold it with time instead


def test_the_repaired_bounce_passes(request):
    """Applying what the report asked for has to clear it, or the advice is noise."""
    name = _ball(f"a/{request.node.name}.aseprite")
    _move(name, [0, 10, 22, 34, 34, 22, 10, 0])

    batch.apply_operations(name, [
        {"op": "remove_frame", "args": {"frame": 8}},   # the duplicated wrap
        {"op": "remove_frame", "args": {"frame": 5}},   # the repeated peak
        {"op": "set_frame_duration", "args": {"frame": 4, "duration_ms": 220}},
        {"op": "set_frame_duration", "args": {"frame": 1, "duration_ms": 180}},
    ])

    result = animation.validate_loop(name)
    assert result["validation"]["passed"] is True
    assert result["animation"]["seam_duplicate"] is False
    assert result["animation"]["duplicate_pairs"] == []
    assert result["animation"]["uniform_timing"] is False


# ---------------------------------------------------------------------- measurements
def test_the_hashes_are_stable_across_calls(request):
    """The fingerprint is only useful if the same pixels give the same string twice."""
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    _move(name, [0, 6, 14])
    first = [f["hash"] for f in animation.validate_loop(name)["animation"]["frames"]]
    second = [f["hash"] for f in animation.validate_loop(name)["animation"]["frames"]]
    assert first == second
    assert len(set(first)) == 3, "three different positions must hash differently"


def test_the_spacing_series_is_measured_from_the_drawn_content(request):
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    _move(name, [0, 5, 15, 30])
    measured = animation.validate_loop(name)["animation"]
    assert [s["dy"] for s in measured["spacing"]] == [5.0, 10.0, 15.0]
    assert [s["dx"] for s in measured["spacing"]] == [0.0, 0.0, 0.0]


def test_one_aseprite_launch_regardless_of_frame_count(request, monkeypatch):
    """The whole point of measuring in Lua. Sixteen frames, one process."""
    from aseprite_mcp.core import runner

    name = _ball(f"a/{request.node.name}.aseprite", 16)
    launches = []
    real = runner._run_bounded

    def counted(*args, **kwargs):
        launches.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_bounded", counted)
    result = animation.validate_loop(name)
    assert len(launches) == 1
    assert result["animation"]["frame_count"] == 16


# ------------------------------------------------------------------------- scoping
def test_a_tag_scopes_the_check_to_its_own_frames(request):
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    _move(name, [0, 8, 16, 0, 9, 18])
    tags.add_tag(name, "first", 1, 3)
    tags.add_tag(name, "second", 4, 6)

    result = animation.validate_loop(name, tag="second")
    measured = result["animation"]
    assert measured["tag"] == "second"
    assert measured["frame_count"] == 3
    assert [f["frame"] for f in measured["frames"]] == [4, 5, 6]
    assert measured["sprite_frame_count"] == 6


def test_a_layer_scopes_the_measurement_past_the_background(request):
    """A background fills the canvas, so the flattened content box never moves. Naming
    the layer measures the character instead, which is the number that matters."""
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    _move(name, [0, 8, 16, 24])
    layers.add_layer(name, "bg")
    layers.move_layer(name, "bg", 0)
    batch.apply_operations(name, [
        {"op": "fill_layer", "args": {"layer": "bg", "color": "#202030", "frame": f}}
        for f in range(1, 5)
    ])

    flattened = animation.validate_loop(name)["animation"]
    assert flattened["contact_drift_px"] == 0, "the background hides the motion"

    scoped = animation.validate_loop(name, layer="Layer 1")["animation"]
    assert scoped["contact_drift_px"] == 24
    assert [s["dy"] for s in scoped["spacing"]] == [8.0, 8.0, 8.0]


def test_an_unknown_tag_says_so(request):
    name = _ball(f"a/{request.node.name}.aseprite", 2)
    with pytest.raises(AsepriteError, match="No tag named 'nope'"):
        animation.validate_loop(name, tag="nope")


def test_an_empty_frame_is_reported_without_breaking_the_spacing(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    batch.apply_operations(name, [
        {"op": "delete_cel", "args": {"layer": "Layer 1", "frame": 2}},
    ])
    measured = animation.validate_loop(name)["animation"]
    assert measured["empty_frames"] == [2]
    assert measured["spacing"][0]["distance"] is None
    assert "no_empty_frames" in failed(animation.validate_loop(name))


def test_a_one_shot_does_not_fail_on_its_last_pose(request):
    """`loops=False` is how an attack or a death says it never wraps."""
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    _move(name, [0, 10, 20, 0])  # frame 4 is back where frame 1 was
    assert animation.validate_loop(name, loops=True)["validation"]["passed"] is False
    one_shot = animation.validate_loop(name, loops=False)
    assert one_shot["validation"]["passed"] is True
    assert "no_seam_duplicate" in failed(one_shot)


def test_validate_loop_saves_nothing(request):
    """It is listed read-only, so the file it opened must come back byte-identical."""
    import hashlib

    from aseprite_mcp.tools.common import resolve_path

    name = _ball(f"a/{request.node.name}.aseprite", 3)
    _move(name, [0, 7, 15])
    path = resolve_path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    mtime = path.stat().st_mtime_ns

    animation.validate_loop(name)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert path.stat().st_mtime_ns == mtime


# =============================================================== offset_cels (issue #88)
# Moving a drawn cel across eight frames used to be eight tool calls, eight Aseprite
# launches, and eight positions worked out by the caller.


def _positions(name: str, count: int) -> list[tuple[int, int]]:
    out = []
    for f in range(1, count + 1):
        cel = cels.get_cel(name, "Layer 1", f)
        out.append((cel["position"]["x"], cel["position"]["y"]))
    return out


def test_a_slide_places_every_cel_in_one_launch(request, monkeypatch):
    from aseprite_mcp.core import runner

    name = _ball(f"a/{request.node.name}.aseprite", 16)
    launches = []
    real = runner._run_bounded

    def counted(*args, **kwargs):
        launches.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_bounded", counted)
    result = animation.offset_cels(name, "Layer 1", list(range(1, 17)), dx=45)

    assert len(launches) == 1
    assert [(p["x"], p["y"]) for p in result["positions"]] == _positions(name, 16)
    assert result["positions"][-1]["x"] - result["positions"][0]["x"] == 45


def test_the_first_listed_frame_anchors_the_movement(request):
    """The movement is relative, so a cel that was already placed moves on from there."""
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    cels.set_cel_position(name, "Layer 1", 1, 12, 20)

    result = animation.offset_cels(name, "Layer 1", [1, 2, 3, 4], dx=30, dy=-9)

    assert result["anchor"] == {"x": 12, "y": 20}
    assert _positions(name, 4)[0] == (12, 20)
    assert _positions(name, 4)[-1] == (42, 11)


def test_the_planned_spacing_is_the_spacing_that_ends_up_in_the_file(request):
    """The returned deltas are a claim about the sprite; validate_loop measures it."""
    name = _ball(f"a/{request.node.name}.aseprite", 8)
    planned = animation.offset_cels(name, "Layer 1", list(range(1, 9)),
                                    dx=0, dy=40, ease="ease_in")

    measured = animation.validate_loop(name, layer="Layer 1")["animation"]
    assert [d["distance"] for d in planned["deltas"]] == \
           [s["distance"] for s in measured["spacing"]]
    assert measured["contact_drift_px"] == 40


def test_an_arc_lifts_the_cel_and_still_lands_it_on_target(request):
    name = _ball(f"a/{request.node.name}.aseprite", 9)
    result = animation.offset_cels(name, "Layer 1", list(range(1, 10)),
                                   dx=48, arc_height=16)

    ys = [p["y"] for p in result["positions"]]
    assert ys[0] == ys[-1] == 0, "a jump starts and ends on the ground"
    assert min(ys) == -16
    assert result["positions"][-1]["x"] == 48
    assert result["max_error_px"] < 1.0


def test_easing_moves_the_spacing_and_leaves_the_timing_alone(request):
    """Easing spacing and durations at once applies the curve twice, and the result
    reads as slow motion. This tool only ever touches positions."""
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    before = animation.validate_loop(name)["animation"]["durations_ms"]

    animation.offset_cels(name, "Layer 1", [1, 2, 3, 4, 5, 6], dx=40, ease="ease_out")

    after = animation.validate_loop(name)["animation"]["durations_ms"]
    assert after == before


def test_a_frame_without_a_cel_stops_the_whole_move(request):
    """Atomic, like every other multi-frame edit here: either all of it or none."""
    import hashlib

    from aseprite_mcp.tools.common import resolve_path

    name = _ball(f"a/{request.node.name}.aseprite", 5)
    batch.apply_operations(name, [
        {"op": "delete_cel", "args": {"layer": "Layer 1", "frame": 4}},
    ])
    path = resolve_path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(AsepriteError, match="no cel on frame 4"):
        animation.offset_cels(name, "Layer 1", [1, 2, 3, 4, 5], dx=20)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert _positions(name, 3) == [(0, 0), (0, 0), (0, 0)]


def test_a_frame_that_does_not_exist_is_named(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    with pytest.raises(AsepriteError, match="does not exist"):
        animation.offset_cels(name, "Layer 1", [1, 2, 99], dx=10)


# --------------------------------------------------- refused before Aseprite is launched
def test_one_frame_cannot_carry_a_movement():
    with pytest.raises(ValidationFailed, match="at least two frames"):
        animation.offset_cels("unused.aseprite", "Layer 1", [1], dx=10)


def test_a_repeated_frame_is_refused():
    with pytest.raises(ValidationFailed, match="more than once"):
        animation.offset_cels("unused.aseprite", "Layer 1", [1, 2, 2, 3], dx=10)


def test_frame_zero_is_refused_as_a_1_based_mistake():
    with pytest.raises(ValidationFailed, match="1-based"):
        animation.offset_cels("unused.aseprite", "Layer 1", [0, 1], dx=10)


def test_an_unknown_easing_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="ease_in_out"):
        animation.offset_cels("unused.aseprite", "Layer 1", [1, 2], ease="bouncy")


def test_too_many_frames_is_refused_with_the_cap():
    from aseprite_mcp.core.limits import MAX_MOTION_FRAMES

    with pytest.raises(ValidationFailed, match=f"maximum is {MAX_MOTION_FRAMES}"):
        animation.offset_cels("unused.aseprite", "Layer 1",
                              list(range(1, MAX_MOTION_FRAMES + 3)), dx=10)


def test_movement_off_the_canvas_measures_as_less_than_it_moved(request):
    """The two numbers answer different questions, and agree only while the cel is fully
    on the canvas. offset_cels reports how far the cel was moved; validate_loop measures
    the content still visible, and a cel leaving the canvas is clipped."""
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    planned = animation.offset_cels(name, "Layer 1", [1, 2, 3, 4], dx=0, dy=90)

    measured = animation.validate_loop(name, layer="Layer 1")["animation"]
    assert planned["positions"][-1]["y"] == 90
    assert measured["frames"][-1]["bounds"] is None, "the cel has left the canvas"
    assert sum(s["distance"] or 0 for s in measured["spacing"]) < 90


# ========================================================= apply_timing_curve (issue #89)
# Uniform timing is the placeholder every animation starts with. The other half of the
# job is refusing the cheap way to hold a pose: a hold is a duration, never a repeat.


def test_hold_extremes_gives_an_idle_a_shape_and_adds_no_frames(request):
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    before = inspect.get_sprite_info(name)["frameCount"]

    result = animation.apply_timing_curve(name, curve="hold_extremes", base_ms=100)

    assert result["durations_ms"] == [250, 100, 250, 100]
    assert result["roles"] == ["extreme", "passing", "extreme", "passing"]
    assert result["frames_added"] == 0
    assert inspect.get_sprite_info(name)["frameCount"] == before


def test_it_clears_the_warning_validate_loop_raises(request):
    """The two tools are the two halves of one loop: one says the timing is placeholder,
    the other fixes it, and the first has to agree afterwards."""
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    animation.offset_cels(name, "Layer 1", list(range(1, 7)), dx=18)

    before = animation.validate_loop(name)
    assert before["animation"]["uniform_timing"] is True
    assert "timing_varies" in failed(before)

    animation.apply_timing_curve(name, curve="hold_extremes")

    after = animation.validate_loop(name)
    assert after["animation"]["uniform_timing"] is False
    assert "timing_varies" not in failed(after)


def test_timing_never_touches_a_pixel(request):
    """Durations are metadata. If a frame's hash moved, something drew."""
    name = _ball(f"a/{request.node.name}.aseprite", 5)
    before = [f["hash"] for f in animation.validate_loop(name)["animation"]["frames"]]

    animation.apply_timing_curve(name, curve="attack", base_ms=90)

    after = [f["hash"] for f in animation.validate_loop(name)["animation"]["frames"]]
    assert after == before


def test_attack_holds_the_anticipation_and_snaps_the_strike(request):
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    result = animation.apply_timing_curve(name, curve="attack", base_ms=100)

    assert result["roles"] == [
        "anticipation", "snap", "snap", "impact", "recovery", "recovery",
    ]
    durations = animation.validate_loop(name)["animation"]["durations_ms"]
    assert durations == result["durations_ms"]
    assert durations[0] > durations[-1] and durations[3] > durations[-1]
    assert 20 <= durations[1] <= 40


def test_a_tag_scopes_the_timing_to_its_own_frames(request):
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    tags.add_tag(name, "first", 1, 3)
    tags.add_tag(name, "second", 4, 6)

    result = animation.apply_timing_curve(name, tag="second", curve="flat", base_ms=250)

    assert result["tag"] == "second"
    assert result["frames"] == [4, 5, 6]
    assert animation.validate_loop(name)["animation"]["durations_ms"] == \
        [100, 100, 100, 250, 250, 250]


def test_an_explicit_frame_list_times_only_those_frames(request):
    name = _ball(f"a/{request.node.name}.aseprite", 5)
    animation.apply_timing_curve(name, frames=[2, 4], curve="flat", base_ms=300)
    assert animation.validate_loop(name)["animation"]["durations_ms"] == \
        [100, 300, 100, 300, 100]


def test_naming_the_poses_by_hand_overrides_the_curve(request):
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    result = animation.apply_timing_curve(
        name, curve="flat", base_ms=100, hold_frames=[2], snap_frames=[4],
    )
    assert result["roles"] == ["even", "hold", "even", "snap"]
    assert result["durations_ms"][1] == 300
    assert 20 <= result["durations_ms"][3] <= 40


def test_eased_spacing_and_an_eased_curve_are_called_out(request):
    """Both are the same curve, and applying it twice reads as slow motion. The cels are
    measured on the way through, so the warning is about this sprite, not a guess."""
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    animation.offset_cels(name, "Layer 1", list(range(1, 7)), dy=40, ease="ease_in")

    result = animation.apply_timing_curve(name, curve="ease_out")

    assert result["warnings"], "eased spacing plus an eased curve should warn"
    assert "twice" in result["warnings"][0]
    # It warns and still does what was asked: the caller decides, having been told.
    assert animation.validate_loop(name)["animation"]["durations_ms"] == \
        result["durations_ms"]


def test_even_spacing_draws_no_warning(request):
    name = _ball(f"a/{request.node.name}.aseprite", 6)
    animation.offset_cels(name, "Layer 1", list(range(1, 7)), dx=25, ease="linear")
    assert animation.apply_timing_curve(name, curve="ease_out")["warnings"] == []


# --------------------------------------------------- refused before Aseprite is launched
def test_an_unknown_curve_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="hold_extremes"):
        animation.apply_timing_curve("unused.aseprite", curve="bouncy")


def test_frames_and_tag_together_are_refused():
    with pytest.raises(ValidationFailed, match="not both"):
        animation.apply_timing_curve("unused.aseprite", frames=[1, 2], tag="walk")


def test_frame_zero_in_a_timing_call_is_refused():
    with pytest.raises(ValidationFailed, match="1-based"):
        animation.apply_timing_curve("unused.aseprite", frames=[0, 1])


def test_holding_a_frame_that_is_not_being_timed_is_refused(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    with pytest.raises(ValidationFailed, match="not being timed"):
        animation.apply_timing_curve(name, frames=[1, 2], hold_frames=[3])
