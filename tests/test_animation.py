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


# ============================================================= tween_cels (issue #124)
# An inbetween is more than a position, and the other three things it does (a scale, a
# turn, a fade) had no tool at all. The fixtures below are the cases the issue names: a
# bottom-anchored squash whose contact row must not move, a spin that must not invent a
# colour, and a fade that must not touch a pixel.

RAMP = ["#2c1b2e", "#6b2d4a", "#b04a5a", "#e07a5f", "#f2cc8f"]


def _hashes(name: str, layer: str = "Layer 1") -> list[str]:
    return [f["hash"] for f in animation.validate_loop(name, layer=layer)["animation"]["frames"]]


def test_a_bottom_anchored_squash_leaves_the_contact_row_where_it_was(request):
    """The point of the anchor. A scale about the centre grows a ball in every direction;
    a scale about the bottom edge squashes it onto the ground, and that is the one that
    reads as weight. `validate_loop`'s contact check is exactly the fault it catches."""
    name = _ball(f"a/{request.node.name}.aseprite", 5)

    result = animation.tween_cels(
        name, "Layer 1", [1, 2, 3, 4, 5],
        scale_from=1.0, scale_to=1.25, scale_y_from=1.0, scale_y_to=0.6,
        anchor="bottom",
    )

    measured = animation.validate_loop(name, layer="Layer 1")["animation"]
    assert measured["contact_drift_px"] == 0
    assert len(set(measured["contact_rows"])) == 1
    assert result["anchor"]["y"] == measured["contact_rows"][0]
    # A squash is wider as it is shorter; a uniform scale would move both the same way.
    heights = [s["bounds"]["height"] for s in result["steps"]]
    widths = [s["bounds"]["width"] for s in result["steps"]]
    assert heights[-1] < heights[0] and widths[-1] > widths[0]


def test_a_centre_anchored_scale_grows_in_every_direction(request):
    """The other half of the anchor's point, so the test above is about the anchor and
    not about scaling in general."""
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    # The drawn content, not the cel rectangle: a cel written by a drawing tool here is
    # canvas-sized, so its bounds say nothing about the shape inside it.
    before = animation.validate_loop(name, layer="Layer 1")["animation"]["frames"][0]["bounds"]

    animation.tween_cels(name, "Layer 1", [1, 2, 3], scale_to=1.6, anchor="center")

    measured = animation.validate_loop(name, layer="Layer 1")["animation"]
    assert measured["contact_drift_px"] > 0, "a centred scale moves the contact edge"
    grown = measured["frames"][-1]["bounds"]
    assert grown["height"] > before["height"]
    assert grown["y"] < before["y"], "it grew upward as well as downward"


def test_the_scale_series_is_monotone_and_measured_rather_than_claimed(request):
    """The property offset_cels is held to, checked against what landed in the file."""
    name = _ball(f"a/{request.node.name}.aseprite", 8)

    result = animation.tween_cels(
        name, "Layer 1", list(range(1, 9)), scale_to=2.0, ease="ease_in",
    )

    assert result["rendered_monotone"] == {"width": True, "height": True}
    rendered = [s["bounds"]["height"] for s in result["steps"]]
    assert rendered == sorted(rendered)
    assert result["steps"][0]["scale_x"] == 1.0
    assert result["steps"][-1]["scale_x"] == 2.0


def test_one_aseprite_launch_regardless_of_the_frame_count(request, monkeypatch):
    """The acceptance criterion, asserted at the runner seam: sixteen frames, each one
    resampled, one process."""
    from aseprite_mcp.core import runner

    name = _ball(f"a/{request.node.name}.aseprite", 16)
    launches = []
    real = runner._run_bounded

    def counted(*args, **kwargs):
        launches.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_bounded", counted)
    result = animation.tween_cels(name, "Layer 1", list(range(1, 17)), scale_to=1.5)

    assert len(launches) == 1
    assert len(result["steps"]) == 16


def test_a_rotation_invents_no_colour_so_the_palette_check_still_holds(request):
    """Nearest-neighbour, not interpolation: the sampler copies a source pixel whole, so
    palette_conformance is the same after the spin as before it."""
    name = f"a/{request.node.name}.aseprite"
    sprite.create_sprite(name, 48, 48)
    drawing.draw_ellipse(name, 24, 24, 9, 9, "#b04a5a", filled=True)
    drawing.draw_rectangle(name, 22, 8, 4, 12, "#f2cc8f", filled=True)
    for _ in range(3):
        frames.add_frame(name)
    for f in range(2, 5):
        cels.copy_cel(name, "Layer 1", 1, f)
    before = inspect.assess_sprite(name, frame=1, ramp=RAMP)["metrics"]

    animation.tween_cels(name, "Layer 1", [1, 2, 3, 4], rotate_to=90)

    after = inspect.assess_sprite(name, frame=4, ramp=RAMP)["metrics"]
    assert before["palette_conformance"] == 1.0
    assert after["palette_conformance"] == 1.0
    assert after["colors"] <= before["colors"], "a resample may lose a colour, never add"


def test_a_quarter_turn_keeps_every_pixel(request):
    """cos(radians(90)) is 6.1e-17, and sampling through that loses a row for no reason
    the caller could see. The quarter turns are the ones pixel art is drawn at."""
    name = f"a/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_rectangle(name, 10, 12, 13, 7, "#b04a5a", filled=True)
    frames.add_frame(name)
    cels.copy_cel(name, "Layer 1", 1, 2)

    result = animation.tween_cels(name, "Layer 1", [1, 2], rotate_to=90)

    assert result["steps"][0]["drawn_pixels"] == 13 * 7
    assert result["steps"][1]["drawn_pixels"] == 13 * 7, "a quarter turn is lossless"
    assert result["steps"][1]["bounds"]["width"] == 7
    assert result["steps"][1]["bounds"]["height"] == 13
    assert result["warnings"] == []


def test_a_shallow_rotation_says_so_and_still_does_it(request):
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    result = animation.tween_cels(name, "Layer 1", [1, 2, 3, 4], rotate_to=12)
    assert result["warnings"], "4 degrees a frame is mush, and the caller should hear it"
    assert "quarter turn" in result["warnings"][0]
    assert result["steps"][-1]["rotate_deg"] == 12


def test_a_fade_sets_cel_opacity_and_does_not_touch_a_pixel(request):
    """Baking a fade into the pixels invents colours that are not on the palette. A cel's
    own opacity is the honest mechanism, and it is what set_cel_opacity sets one frame at
    a time."""
    name = _ball(f"a/{request.node.name}.aseprite", 5)
    before = _hashes(name)

    result = animation.tween_cels(name, "Layer 1", [1, 2, 3, 4, 5], opacity_to=0)

    assert [s["opacity"] for s in result["steps"]] == [255, 191, 127, 64, 0]
    assert [cels.get_cel(name, "Layer 1", f)["opacity"] for f in range(1, 6)] == \
        [255, 191, 127, 64, 0]
    assert _hashes(name) == before, "an opacity tween must not redraw anything"


def test_the_source_frame_is_rewritten_when_its_own_values_are_not_the_identity(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    result = animation.tween_cels(
        name, "Layer 1", [1, 2, 3], scale_from=0.5, scale_to=1.0, anchor="center",
    )
    assert result["steps"][0]["scale_x"] == 0.5
    assert result["steps"][0]["bounds"]["height"] < result["steps"][-1]["bounds"]["height"]


def test_every_frame_is_sampled_from_the_original_so_the_error_cannot_compound(request):
    """A tween that fed each frame into the next would resample eight times over to reach
    the last pose, and nearest-neighbour resampling is lossy: pixels dropped on the way
    are gone. Reaching the same angle in eight steps and in one must therefore give the
    same cel, and it only does if every frame reads the pristine source."""
    long_way = f"a/{request.node.name}-8.aseprite"
    short_way = f"a/{request.node.name}-2.aseprite"
    for name, count in ((long_way, 8), (short_way, 2)):
        sprite.create_sprite(name, 48, 48)
        drawing.draw_rectangle(name, 14, 20, 19, 7, "#b04a5a", filled=True)
        for _ in range(count - 1):
            frames.add_frame(name)
        for f in range(2, count + 1):
            cels.copy_cel(name, "Layer 1", 1, f)
        animation.tween_cels(name, "Layer 1", list(range(1, count + 1)), rotate_to=40)

    assert _hashes(long_way)[-1] == _hashes(short_way)[-1]


def test_a_tween_leaves_the_frame_durations_alone(request):
    """Easing the spacing and the timing at once applies the curve twice, and the result
    reads as slow motion rather than as weight."""
    name = _ball(f"a/{request.node.name}.aseprite", 5)
    before = animation.validate_loop(name)["animation"]["durations_ms"]
    animation.tween_cels(name, "Layer 1", [1, 2, 3, 4, 5], scale_to=1.4, ease="ease_out")
    assert animation.validate_loop(name)["animation"]["durations_ms"] == before


def test_the_generated_cel_is_trimmed_to_its_own_content(request):
    """A canvas-sized cel reports the whole canvas as its bounds, which is a claim about
    the drawing that is not true, and smear_frame reads that number."""
    name = _ball(f"a/{request.node.name}.aseprite", 2)
    animation.tween_cels(name, "Layer 1", [1, 2], scale_to=0.5, anchor="center")
    cel = cels.get_cel(name, "Layer 1", 2)
    assert cel["bounds"]["width"] < 48
    assert cel["bounds"]["height"] < 48


def test_a_diff_shows_the_tweened_frame_differing_from_its_source(request):
    name = _ball(f"a/{request.node.name}.aseprite", 4)
    animation.tween_cels(name, "Layer 1", [1, 2, 3, 4], scale_to=1.8, anchor="center")
    diff = inspect.diff_sprites(name, frame=1, other_frame=4, layer="Layer 1",
                                expect="silhouette")
    assert diff["verdict"]["passed"] is True
    assert diff["identical"] is False
    # Every pixel the scale added is the ball's own colour: nothing was blended, and the
    # inside of the old silhouette was not repainted.
    assert [e["color"] for e in diff["metrics"]["colors_after"]] == ["#ff5050ff"]
    assert diff["metrics"]["interior_changed"] == 0


# -------------------------------------------------------------------- tween refusals
def test_a_linked_target_frame_is_refused_and_nothing_is_written(request):
    """Linked cels share one image, one position and one opacity, so writing a tween into
    a link group would change every frame in it. Measured, not assumed: assigning to one
    of four linked cels changed all four."""
    import hashlib

    from aseprite_mcp.tools.common import resolve_path

    name = _ball(f"a/{request.node.name}.aseprite", 4)
    cels.link_cels(name, "Layer 1", [2, 3, 4])
    path = resolve_path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(AsepriteError, match="linked cel") as raised:
        animation.tween_cels(name, "Layer 1", [1, 2, 3, 4], scale_to=1.5)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "unlink_cels" in str(raised.value)
    assert "2, 3, 4" in str(raised.value), "the refusal names the frames"


def test_a_source_frame_without_a_cel_is_refused(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    cels.delete_cel(name, "Layer 1", 1)
    with pytest.raises(AsepriteError, match="no cel on frame 1"):
        animation.tween_cels(name, "Layer 1", [1, 2, 3], scale_to=1.5)


def test_a_source_cel_with_nothing_drawn_on_it_is_refused(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    layers.add_layer(name, "empty")
    # A cel that exists and holds nothing, which is a different fault from no cel at all.
    drawing.fill_layer(name, "transparent", layer="empty", frame=1)
    assert cels.get_cel(name, "empty", 1)["exists"] is True
    with pytest.raises(AsepriteError, match="nothing drawn"):
        animation.tween_cels(name, "empty", [1, 2, 3], scale_to=1.5)


def test_a_group_layer_is_refused_by_name(request):
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    layers.add_group_layer(name, "folder")
    with pytest.raises(AsepriteError, match="group layer"):
        animation.tween_cels(name, "folder", [1, 2, 3], scale_to=1.5)


def test_a_transform_that_lands_off_the_canvas_is_refused_atomically(request):
    """Nothing partial: either every frame or none, like every other multi-frame edit
    here. A frame that came out empty is a null result, not a small one."""
    import hashlib

    from aseprite_mcp.tools.common import resolve_path

    # A ring, so the anchor pixel at its centre is transparent. Anything with an opaque
    # pixel at the anchor keeps that one pixel whatever the scale, because the anchor is
    # the point the transform holds still; a hole there is what lets a frame empty out.
    name = f"a/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse(name, 16, 16, 10, 10, "#b04a5a", filled=False)
    frames.add_frame(name)
    cels.copy_cel(name, "Layer 1", 1, 2)
    path = resolve_path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(AsepriteError, match="came out empty"):
        animation.tween_cels(name, "Layer 1", [1, 2], scale_to=4.0, anchor="center")

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_a_tween_too_big_to_run_is_refused_with_the_sample_count(request):
    name = f"a/{request.node.name}.aseprite"
    sprite.create_sprite(name, 2048, 2048)
    drawing.draw_rectangle(name, 0, 0, 2048, 2048, "#b04a5a", filled=True)
    for _ in range(3):
        frames.add_frame(name)
    for f in (2, 3, 4):
        cels.copy_cel(name, "Layer 1", 1, f)
    with pytest.raises(AsepriteError, match="maximum is"):
        animation.tween_cels(name, "Layer 1", [1, 2, 3, 4], scale_to=1.6)


# --------------------------------------------------- refused before Aseprite is launched
def test_one_frame_cannot_carry_a_tween():
    with pytest.raises(ValidationFailed, match="at least two frames"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1], scale_to=2.0)


def test_a_repeated_frame_in_a_tween_is_refused():
    with pytest.raises(ValidationFailed, match="more than once"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2, 2], scale_to=2.0)


def test_frame_zero_in_a_tween_is_refused_as_a_1_based_mistake():
    with pytest.raises(ValidationFailed, match="1-based"):
        animation.tween_cels("unused.aseprite", "Layer 1", [0, 1], scale_to=2.0)


def test_too_many_frames_in_a_tween_is_refused_with_the_cap():
    from aseprite_mcp.core.limits import MAX_MOTION_FRAMES

    with pytest.raises(ValidationFailed, match=f"maximum is {MAX_MOTION_FRAMES}"):
        animation.tween_cels("unused.aseprite", "Layer 1",
                             list(range(1, MAX_MOTION_FRAMES + 3)), scale_to=2.0)


def test_an_unknown_anchor_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="bottom"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2],
                             scale_to=2.0, anchor="feet")


def test_an_unknown_easing_in_a_tween_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="ease_in_out"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2],
                             scale_to=2.0, ease="bouncy")


def test_a_scale_of_zero_is_refused_and_names_the_fade_instead():
    with pytest.raises(ValidationFailed, match="opacity_to=0"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2], scale_to=0.0)


def test_a_scale_past_the_cap_is_refused_with_the_number():
    from aseprite_mcp.core.limits import MAX_TWEEN_SCALE

    with pytest.raises(ValidationFailed, match=f"maximum is {MAX_TWEEN_SCALE}"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2],
                             scale_to=MAX_TWEEN_SCALE + 1)


def test_a_rotation_past_the_cap_is_refused():
    from aseprite_mcp.core.limits import MAX_TWEEN_ROTATION_DEG

    with pytest.raises(ValidationFailed, match="periodic"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2],
                             rotate_to=MAX_TWEEN_ROTATION_DEG + 1)


def test_an_opacity_outside_the_range_a_cel_holds_is_refused():
    with pytest.raises(ValidationFailed, match="maximum is 255"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2], opacity_to=300)
    with pytest.raises(ValidationFailed, match="minimum is 0"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2], opacity_to=-1)


def test_a_tween_with_nothing_to_tween_is_refused():
    """Otherwise every listed frame is rewritten with the drawing the source already
    holds, and the call reports success for having done nothing."""
    with pytest.raises(ValidationFailed, match="nothing to tween"):
        animation.tween_cels("unused.aseprite", "Layer 1", [1, 2, 3])


# ============================================================ smear_frame (issue #126)
# Between two frames of a fast movement the eye expects a smear, and a smear made with
# alpha is a smear made of colours that are not in the palette. These check both halves:
# that the trail lies along the movement the sprite itself knows about, and that with a
# ramp every pixel of it is a colour the sprite already had.


def _slide(name: str, count: int = 4, dx: int = 36, color: str = "#b04a5a") -> str:
    sprite.create_sprite(name, 64, 40)
    drawing.draw_ellipse(name, 10, 20, 5, 5, color, filled=True)
    for _ in range(count - 1):
        frames.add_frame(name)
    for f in range(2, count + 1):
        cels.copy_cel(name, "Layer 1", 1, f)
    animation.offset_cels(name, "Layer 1", list(range(1, count + 1)), dx=dx)
    return name


def test_a_smear_lies_along_the_movement_the_cels_themselves_know_about(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)

    result = animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    assert result["from_frame"] == 2
    assert result["vector"] == {"dx": 12, "dy": 0}
    before, after = result["subject_bounds"], result["bounds"]
    assert after["x"] == before["x"] - 12, "the trail reaches back along the movement"
    assert after["width"] == before["width"] + 12
    assert after["y"] == before["y"] and after["height"] == before["height"]


def test_a_vertical_movement_smears_vertically(request):
    """The vector is taken from the cels, so the axis is not something the caller says."""
    name = f"a/{request.node.name}.aseprite"
    sprite.create_sprite(name, 40, 64)
    drawing.draw_ellipse(name, 20, 10, 5, 5, "#b04a5a", filled=True)
    for _ in range(3):
        frames.add_frame(name)
    for f in (2, 3, 4):
        cels.copy_cel(name, "Layer 1", 1, f)
    animation.offset_cels(name, "Layer 1", [1, 2, 3, 4], dy=33)

    result = animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    assert result["vector"] == {"dx": 0, "dy": 11}
    assert all(p["dx"] == 0 and p["dy"] < 0 for p in result["plots"])


def test_the_vector_is_read_from_the_content_and_not_from_the_cel_rectangle(request):
    """Every tool here that writes a whole canvas back leaves the cel at (0, 0) on every
    frame. A vector taken from cel.position would read zero while the drawing moved."""
    name = f"a/{request.node.name}.aseprite"
    sprite.create_sprite(name, 64, 40)
    for _ in range(2):
        frames.add_frame(name)
    for n, cx in enumerate((10, 22, 34), start=1):
        drawing.draw_ellipse(name, cx, 20, 5, 5, "#b04a5a", filled=True, frame=n)
    positions = {
        (cels.get_cel(name, "Layer 1", f)["position"]["x"],
         cels.get_cel(name, "Layer 1", f)["position"]["y"]) for f in (1, 2, 3)
    }
    assert positions == {(0, 0)}, "the fixture is only interesting if they all sit at 0,0"

    result = animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    assert result["vector"] == {"dx": 12, "dy": 0}


def test_with_a_ramp_every_pixel_of_the_smear_is_on_the_palette(request):
    """The acceptance criterion, and the property every shading tool here holds to."""
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)

    result = animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    measured = inspect.assess_sprite(name, frame=3, layer="Layer 1", ramp=RAMP)
    assert measured["metrics"]["palette_conformance"] == 1.0
    assert result["on_palette"] is True


def test_without_a_ramp_it_fades_and_says_that_it_left_the_palette(request):
    """The fallback is honest about itself rather than quietly producing motion blur."""
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)

    result = animation.smear_frame(name, "Layer 1", 3, strength=1.0)

    assert result["on_palette"] is False
    assert any("not on the palette" in w for w in result["warnings"])
    measured = inspect.assess_sprite(name, frame=3, layer="Layer 1", ramp=RAMP)
    assert measured["metrics"]["palette_conformance"] < 1.0


def test_the_unsmeared_frames_are_untouched(request):
    """A smear is one frame of a movement. Every other frame has to come back unchanged,
    which is also why a linked cel is refused."""
    name = _slide(f"a/{request.node.name}.aseprite", 5, dx=48)
    before = _hashes(name)

    animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    after = _hashes(name)
    assert after[2] != before[2], "the smeared frame has to have changed"
    assert [after[i] for i in (0, 1, 3, 4)] == [before[i] for i in (0, 1, 3, 4)]


def test_the_subject_survives_on_top_of_its_own_trail(request):
    """A smear describes the movement behind a drawing; it does not replace it. So the
    change is pixels entering the silhouette and nothing inside it being repainted."""
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    sprite.save_sprite_as(name, f"a/{request.node.name}-before.aseprite")

    animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    diff = inspect.diff_sprites(
        f"a/{request.node.name}-before.aseprite", frame=3, layer="Layer 1",
        other=name, other_frame=3, expect="silhouette",
    )
    assert diff["verdict"]["passed"] is True
    assert diff["metrics"]["interior_changed"] == 0
    assert diff["metrics"]["silhouette_removed"] == 0
    assert diff["metrics"]["silhouette_added"] > 0


def test_a_stretch_thins_to_a_point_at_the_trailing_end(request):
    """The shape of a smear rather than the shape of a rectangle: full width where it
    leaves the subject, a single row at the tip."""
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    result = animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=1.0)

    box, subject = result["bounds"], result["subject_bounds"]
    grid = inspect.get_pixels(name, x=box["x"], y=box["y"], width=box["width"],
                              height=box["height"], frame=3, layer="Layer 1")["pixels"]
    # Only the columns the trail has to itself: the subject is a circle, so its own
    # columns narrow again at its far edge and say nothing about the thinning.
    trail = [
        sum(1 for row in grid if not row[x].endswith("00"))
        for x in range(subject["x"] - box["x"])
    ]
    assert trail, "the fixture has to leave the trail some columns of its own"
    assert trail[0] == 1, "the tip is one pixel tall"
    assert trail == sorted(trail), "and it widens all the way back to the subject"
    assert trail[-1] > trail[0]


def test_echo_draws_the_asked_for_number_of_copies_along_the_vector(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)

    result = animation.smear_frame(name, "Layer 1", 3, mode="echo", steps=3,
                                   strength=1.0, ramp=RAMP)

    assert result["copies"] == 3
    assert [p["dx"] for p in result["plots"]] == [-12, -8, -4]
    assert inspect.assess_sprite(
        name, frame=3, layer="Layer 1", ramp=RAMP
    )["metrics"]["palette_conformance"] == 1.0


def test_a_smear_can_be_asked_to_measure_from_any_earlier_frame(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    result = animation.smear_frame(name, "Layer 1", 4, from_frame=1, ramp=RAMP,
                                   strength=0.5)
    assert result["from_frame"] == 1
    assert result["vector"] == {"dx": 36, "dy": 0}
    assert result["copies"] == 18


def test_a_subject_sitting_too_high_on_the_ramp_is_warned_about(request):
    """A subject on the third step of a five-colour ramp has two steps below it, not
    four, and the copies past that all land on the darkest entry."""
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    result = animation.smear_frame(name, "Layer 1", 3, mode="echo", steps=4,
                                   strength=1.0, ramp=RAMP)
    assert any("step 3 of 5" in w for w in result["warnings"])


# -------------------------------------------------------------------- smear refusals
def test_a_frame_with_no_movement_to_smear_is_refused(request):
    """The acceptance criterion: rather than producing a blur of nothing, it says where
    the subject sat on both frames."""
    name = _ball(f"a/{request.node.name}.aseprite", 3)
    with pytest.raises(ValidationFailed, match="does not move"):
        animation.smear_frame(name, "Layer 1", 2, ramp=RAMP)


def test_a_movement_too_short_to_smear_names_the_pixels_and_the_strength(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=6)
    with pytest.raises(ValidationFailed, match="would be 0px long"):
        animation.smear_frame(name, "Layer 1", 3, ramp=RAMP, strength=0.2)


def test_a_linked_frame_cannot_be_smeared(request):
    """The smear would appear on every frame sharing the image, so the unsmeared frames
    would not be untouched."""
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    cels.link_cels(name, "Layer 1", [3, 4])
    with pytest.raises(ValidationFailed, match="unlink_cels"):
        animation.smear_frame(name, "Layer 1", 3, ramp=RAMP)


def test_an_undrawn_frame_cannot_be_smeared(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    cels.delete_cel(name, "Layer 1", 3)
    with pytest.raises(AsepriteError, match="nothing drawn on frame 3"):
        animation.smear_frame(name, "Layer 1", 3, ramp=RAMP)


def test_an_undrawn_source_frame_says_what_it_was_needed_for(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    cels.delete_cel(name, "Layer 1", 2)
    with pytest.raises(AsepriteError, match="measure the movement from"):
        animation.smear_frame(name, "Layer 1", 3, ramp=RAMP)


def test_a_group_layer_cannot_be_smeared(request):
    name = _slide(f"a/{request.node.name}.aseprite", 4, dx=36)
    layers.add_group_layer(name, "folder")
    with pytest.raises(AsepriteError, match="group layer"):
        animation.smear_frame(name, "folder", 3, ramp=RAMP)


# --------------------------------------------------- refused before Aseprite is launched
def test_frame_one_has_nothing_to_have_moved_from():
    with pytest.raises(ValidationFailed, match="no earlier frame"):
        animation.smear_frame("unused.aseprite", "Layer 1", 1)


def test_smearing_a_frame_from_itself_is_refused():
    with pytest.raises(ValidationFailed, match="zero by construction"):
        animation.smear_frame("unused.aseprite", "Layer 1", 3, from_frame=3)


def test_an_unknown_smear_mode_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="stretch, echo"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2, mode="blur")


def test_steps_with_a_stretch_is_refused_rather_than_ignored():
    """An argument that is silently dropped is the bug class this server keeps finding."""
    with pytest.raises(ValidationFailed, match="only applies to mode='echo'"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2, mode="stretch", steps=4)


def test_a_strength_of_zero_or_past_the_cap_is_refused():
    from aseprite_mcp.core.limits import MAX_SMEAR_STRENGTH

    with pytest.raises(ValidationFailed, match="greater than 0"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2, strength=0)
    with pytest.raises(ValidationFailed, match=f"maximum is {MAX_SMEAR_STRENGTH}"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2,
                              strength=MAX_SMEAR_STRENGTH + 1)


def test_too_many_echo_steps_is_refused_with_the_cap():
    from aseprite_mcp.core.limits import MAX_SMEAR_STEPS

    with pytest.raises(ValidationFailed, match=f"maximum is {MAX_SMEAR_STEPS}"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2, mode="echo",
                              steps=MAX_SMEAR_STEPS + 1)


def test_a_one_colour_ramp_cannot_be_stepped_down():
    with pytest.raises(ValidationFailed, match="at least 2"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2, ramp=["#b04a5a"])


def test_a_ramp_of_palette_indices_is_refused_with_the_reason():
    with pytest.raises(ValidationFailed, match="palette index"):
        animation.smear_frame("unused.aseprite", "Layer 1", 2,
                              ramp=["index:1", "index:2"])
