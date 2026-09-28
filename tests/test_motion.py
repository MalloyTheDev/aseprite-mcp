"""Pure tests for the movement distributor (no Aseprite, always run).

The distributor exists because cel positions are integers. Rounding each step on its own
keeps the total right and loses the motion: a 43px slide over nine steps came out as
5, 4, 5, 5, 4, 5, 5, 4, 5, which reads as a limp. Rounding the running position carries
the leftover forward instead, and that is the property these tests hold it to, per axis
and for every easing, rather than only checking that the cel ends up in the right place.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aseprite_mcp.core import motion

FAST = settings(max_examples=100, deadline=None)


def steps(offsets, axis: int) -> list[int]:
    return [b[axis] - a[axis] for a, b in pairwise(offsets)]


# ------------------------------------------------------------------ the straight slide
def test_a_slide_spreads_the_leftover_instead_of_repeating_it():
    """43px over nine steps. Every step is 4 or 5, and the short ones are spread out
    rather than alternating with the long ones."""
    offsets = motion.plan(10, 0, 43)["offsets"]
    series = steps(offsets, 1)
    assert sum(series) == 43
    assert set(series) == {4, 5}
    assert series == [5, 5, 4, 5, 5, 5, 4, 5, 5]


def test_the_ends_are_exact():
    plan = motion.plan(7, 17, -23, ease="ease_in_out")
    assert plan["offsets"][0] == (0, 0)
    assert plan["offsets"][-1] == (17, -23)


def test_two_frames_is_just_the_two_ends():
    assert motion.plan(2, 9, 4)["offsets"] == [(0, 0), (9, 4)]


# ------------------------------------------------------------------------- the curves
def test_ease_in_never_slows_down():
    series = steps(motion.plan(12, 0, 100, ease="ease_in")["offsets"], 1)
    assert series == sorted(series), series


def test_ease_out_never_speeds_up():
    series = steps(motion.plan(12, 0, 100, ease="ease_out")["offsets"], 1)
    assert series == sorted(series, reverse=True), series


def test_ease_in_out_speeds_up_then_slows_down():
    series = steps(motion.plan(13, 0, 120, ease="ease_in_out")["offsets"], 1)
    peak = series.index(max(series))
    assert series[:peak + 1] == sorted(series[:peak + 1])
    assert series[peak:] == sorted(series[peak:], reverse=True)


def test_gravity_keeps_the_horizontal_speed_and_gains_the_vertical():
    """A thrown object does not slow down sideways as it falls, so the two axes are
    distributed differently. Easing both would make it arrive in slow motion."""
    offsets = motion.plan(9, 64, 64, ease="gravity")["offsets"]
    across, down = steps(offsets, 0), steps(offsets, 1)
    assert max(across) - min(across) <= 1, across
    assert down == sorted(down), down
    assert down[-1] > down[0] * 3, "the fall should visibly accelerate"


# ---------------------------------------------------------------------------- the arc
def test_an_arc_peaks_in_the_middle_and_lands_flat():
    offsets = motion.plan(9, 40, 0, arc_height=16)["offsets"]
    heights = [y for _, y in offsets]
    assert heights[0] == 0 and heights[-1] == 0
    assert min(heights) == -16, heights  # up is negative y, and the peak is the height
    assert heights.index(min(heights)) == 4


def test_an_arc_bends_across_the_line_between_the_ends():
    """Diagonal movement: the bulge is perpendicular to the path, not simply upward."""
    straight = motion.plan(5, 40, 40)["offsets"]
    arced = motion.plan(5, 40, 40, arc_height=14)["offsets"]
    mid_straight, mid_arced = straight[2], arced[2]
    assert mid_arced != mid_straight
    # Perpendicular to a 45-degree path lifts and pushes forward in equal measure.
    assert mid_arced[0] > mid_straight[0]
    assert mid_arced[1] < mid_straight[1]


def test_a_movement_that_goes_nowhere_still_arcs_upward():
    """A hop in place has no direction to be perpendicular to, so it lifts."""
    offsets = motion.plan(5, 0, 0, arc_height=10)["offsets"]
    assert offsets[0] == (0, 0) and offsets[-1] == (0, 0)
    assert min(y for _, y in offsets) == -10


# --------------------------------------------------------------------------- refusals
def test_one_frame_is_refused():
    with pytest.raises(ValueError, match="at least 2 frames"):
        motion.plan(1, 10, 0)


def test_an_unknown_easing_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown easing 'bouncy'"):
        motion.plan(4, 10, 0, ease="bouncy")


# ------------------------------------------------------------------------- properties
@FAST
@given(
    count=st.integers(min_value=2, max_value=64),
    dx=st.integers(min_value=-500, max_value=500),
    dy=st.integers(min_value=-500, max_value=500),
    ease=st.sampled_from(motion.EASINGS),
)
def test_the_movement_always_ends_where_it_was_asked_to(count, dx, dy, ease):
    offsets = motion.plan(count, dx, dy, ease=ease)["offsets"]
    assert len(offsets) == count
    assert offsets[0] == (0, 0)
    assert offsets[-1] == (dx, dy)


@FAST
@given(
    count=st.integers(min_value=2, max_value=64),
    dx=st.integers(min_value=-500, max_value=500),
    dy=st.integers(min_value=-500, max_value=500),
    ease=st.sampled_from(motion.EASINGS),
    arc=st.integers(min_value=-60, max_value=60),
)
def test_no_frame_lands_further_than_a_pixel_from_the_ideal(count, dx, dy, ease, arc):
    plan = motion.plan(count, dx, dy, ease=ease, arc_height=arc)
    assert plan["max_error_px"] < 1.0
    for (px, py), (ix, iy) in zip(plan["offsets"], plan["ideal"], strict=True):
        assert math.hypot(px - ix, py - iy) < 1.0


@FAST
@given(
    count=st.integers(min_value=3, max_value=48),
    distance=st.integers(min_value=1, max_value=500),
    ease=st.sampled_from(motion.EASINGS),
)
def test_a_single_axis_never_doubles_back(count, distance, ease):
    """Whatever the curve, a movement in one direction never steps backwards: that is
    the jitter the per-step rounding used to produce."""
    series = steps(motion.plan(count, 0, distance, ease=ease)["offsets"], 1)
    assert all(step >= 0 for step in series), series
    assert sum(series) == distance
