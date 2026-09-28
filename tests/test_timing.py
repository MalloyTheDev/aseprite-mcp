"""Pure tests for the duration curves (no Aseprite, always run).

Timing is where an animation stops looking like a slideshow, and the two ways it is
usually got wrong are both structural rather than aesthetic: every frame left at the
placeholder duration, and a pose "held" by duplicating a frame instead of lengthening
one. The first is what the curves are for. The second this module cannot do at all, which
is the point: it returns durations and never a frame count.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import timing


def durations(count: int, curve: str, **kwargs) -> list[int]:
    return timing.plan(list(range(1, count + 1)), curve=curve, **kwargs)["durations_ms"]


def roles(count: int, curve: str, **kwargs) -> list[str]:
    return timing.plan(list(range(1, count + 1)), curve=curve, **kwargs)["roles"]


# ------------------------------------------------------------------------ the curves
def test_hold_extremes_on_a_four_frame_idle_is_not_uniform():
    """The acceptance case: a 4-frame idle holds its two extremes and passes through the
    other two, which is what separates an idle from a slideshow."""
    series = durations(4, "hold_extremes", base_ms=100)
    assert series == [250, 100, 250, 100]
    assert len(set(series)) > 1


def test_hold_extremes_holds_the_ends_of_the_cycle():
    assert roles(8, "hold_extremes") == [
        "extreme", "passing", "passing", "passing",
        "extreme", "passing", "passing", "passing",
    ]


def test_flat_is_the_way_back_to_even_timing():
    assert durations(5, "flat", base_ms=80) == [80] * 5


def test_attack_is_anticipation_then_snap_then_impact_then_recovery():
    assert roles(6, "attack") == [
        "anticipation", "snap", "snap", "impact", "recovery", "recovery",
    ]
    series = durations(6, "attack", base_ms=100)
    assert series[0] > series[-1], "the anticipation is held"
    assert series[3] > series[-1], "so is the impact"
    assert timing.MIN_SNAP_MS <= series[1] <= timing.MAX_SNAP_MS, "the strike snaps"


def test_a_snap_stays_inside_the_window_whatever_the_base():
    """Below 20ms a frame is invisible and above 40ms it stops snapping, so the strike is
    clamped into that window rather than scaled without limit."""
    for base in (40, 100, 400, 2000):
        series = durations(6, "attack", base_ms=base)
        assert timing.MIN_SNAP_MS <= series[1] <= timing.MAX_SNAP_MS, base


def test_ease_in_starts_slow_and_ease_out_ends_slow():
    """The same words mean the same thing here as in spacing: a longer frame reads as
    slower, so ease_in puts the long frames at the start."""
    starting = durations(6, "ease_in")
    ending = durations(6, "ease_out")
    assert starting == sorted(starting, reverse=True)
    assert ending == sorted(ending)
    assert starting == list(reversed(ending))


# --------------------------------------------------------------- explicit holds and snaps
def test_named_frames_override_the_curve():
    plan = timing.plan([1, 2, 3, 4], curve="flat", base_ms=100,
                       hold_frames=[1], snap_frames=[3])
    assert plan["durations_ms"] == [300, 100, plan["snap_ms"], 100]
    assert plan["roles"] == ["hold", "even", "snap", "even"]


def test_a_frame_cannot_be_both_held_and_snapped():
    with pytest.raises(ValueError, match="both a hold and a snap"):
        timing.plan([1, 2, 3], curve="flat", hold_frames=[2], snap_frames=[2])


def test_naming_a_frame_that_is_not_being_timed_is_refused():
    """Silently ignoring it would leave the caller believing a pose was held."""
    with pytest.raises(ValueError, match=r"not being timed: \[9\]"):
        timing.plan([1, 2, 3], curve="flat", hold_frames=[9])


# --------------------------------------------------------------------------- refusals
def test_an_unknown_curve_lists_the_ones_that_exist():
    with pytest.raises(ValueError, match="hold_extremes"):
        timing.plan([1, 2], curve="bouncy")


def test_no_frames_is_refused():
    with pytest.raises(ValueError, match="no frames"):
        timing.plan([], curve="flat")


def test_a_base_outside_what_aseprite_stores_is_refused():
    with pytest.raises(ValueError, match="between 1 and 65535"):
        timing.plan([1, 2], curve="flat", base_ms=0)
    with pytest.raises(ValueError, match="between 1 and 65535"):
        timing.plan([1, 2], curve="flat", base_ms=100_000)


def test_a_long_base_cannot_push_a_held_frame_past_the_limit():
    series = durations(4, "hold_extremes", base_ms=60_000)
    assert max(series) == timing.MAX_DURATION_MS


# ------------------------------------------------------------- the double-ease warning
def test_easing_durations_over_eased_spacing_is_called_out():
    plan = timing.plan([1, 2, 3, 4, 5], curve="ease_out", spacing=[2.0, 4.0, 8.0, 16.0])
    assert plan["warnings"]
    assert "twice" in plan["warnings"][0]


def test_even_spacing_is_left_alone():
    plan = timing.plan([1, 2, 3, 4, 5], curve="ease_out", spacing=[5.0, 5.0, 5.0, 5.0])
    assert plan["warnings"] == []


def test_a_curve_that_is_not_an_ease_never_warns_about_spacing():
    """hold_extremes is not the same curve as eased spacing, so stacking them is fine."""
    plan = timing.plan([1, 2, 3, 4, 5], curve="hold_extremes",
                       spacing=[2.0, 4.0, 8.0, 16.0])
    assert plan["warnings"] == []


def test_a_wobble_is_not_mistaken_for_easing():
    assert timing.looks_eased([4.0, 9.0, 5.0, 10.0]) is False


def test_a_one_pixel_difference_is_not_a_curve():
    assert timing.looks_eased([5.0, 5.0, 6.0, 6.0]) is False


def test_too_few_steps_to_tell():
    assert timing.looks_eased([2.0, 8.0]) is False
    assert timing.looks_eased([None, None, None]) is False


# --------------------------------------------------------------------------- the point
def test_timing_returns_durations_and_never_a_frame_count():
    """A hold is a duration. Nothing in here can produce a frame, which is why the tool
    can promise that it added none."""
    plan = timing.plan([1, 2, 3, 4], curve="hold_extremes")
    assert set(plan) == {"durations_ms", "roles", "warnings", "snap_ms"}
    assert len(plan["durations_ms"]) == 4


def test_uniform_output_suggests_the_curve_that_would_not_be():
    plan = timing.plan([1, 2, 3, 4], curve="flat")
    assert plan["warnings"]
    assert "hold_extremes" in plan["warnings"][0]
