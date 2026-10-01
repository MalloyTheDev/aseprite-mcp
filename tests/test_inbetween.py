"""The arithmetic and the judgement behind a tween and a smear. No Aseprite.

These are the properties the two tools rest on, in the form in which they can be checked
on CI where no editor exists: that the eased series hit their ends exactly and never
double back, that a quarter turn is lossless, that the inverse transform really is the
inverse, that a smear's vector comes from where the drawing sits rather than from a cel
rectangle, and that a trail's colours are entries of the declared ramp and nothing else.
"""

from __future__ import annotations

import math

import pytest

from aseprite_mcp.core import inbetween, motion

RAMP = [(44, 27, 46), (107, 45, 74), (176, 74, 90), (224, 122, 95), (242, 204, 143)]


# ------------------------------------------------------------------- eased scalars
def test_a_ramp_hits_both_ends_exactly():
    """The ends were chosen; only the frames between them may be approximate."""
    values = inbetween.scale_ramp(7, 1.0, 1.75, ease="ease_out")
    assert values[0] == 1.0
    assert values[-1] == 1.75
    assert len(values) == 7


def test_an_integer_ramp_is_whole_numbers_and_exact_at_the_ends():
    values = inbetween.int_ramp(5, 255, 0, ease="linear")
    assert values == [255, 191, 127, 64, 0]
    assert all(isinstance(v, int) for v in values)


@pytest.mark.parametrize("ease", motion.EASINGS)
def test_no_easing_ever_doubles_back(ease):
    """The property `offset_cels` is held to: monotone within a phase, never a reversal."""
    assert inbetween.is_monotone(inbetween.scale_ramp(12, 0.5, 2.0, ease=ease))
    assert inbetween.is_monotone(inbetween.int_ramp(12, 0, 255, ease=ease))


def test_gravity_accelerates_a_scalar_rather_than_going_linear():
    """`motion.plan` splits the axes for gravity: x stays linear while y accelerates, so
    a scalar riding the wrong axis would silently come out as `linear`."""
    accelerating = inbetween.int_ramp(5, 0, 100, ease="gravity")
    straight = inbetween.int_ramp(5, 0, 100, ease="linear")
    assert accelerating != straight
    assert accelerating[1] < straight[1]


def test_a_flat_spot_is_monotone_and_a_reversal_is_not():
    assert inbetween.is_monotone([5, 5, 6, 6, 7])
    assert not inbetween.is_monotone([5, 6, 5])


# -------------------------------------------------------------------- the transform
@pytest.mark.parametrize("angle", [0, 90, 180, 270, 360, -90, 450])
def test_the_quarter_turns_are_exact(angle):
    """cos(radians(90)) is 6.1e-17, and a sample taken through that lands a quarter turn
    a pixel out along one axis for no reason the caller could see."""
    cos, sin = inbetween._trig(angle)
    assert cos in (-1.0, 0.0, 1.0)
    assert sin in (-1.0, 0.0, 1.0)
    assert inbetween.rotation_offcut(angle) == 0


def test_a_rotation_is_measured_from_the_nearest_quarter_turn():
    assert inbetween.rotation_offcut(7) == 7
    assert inbetween.rotation_offcut(97) == 7, "a quarter turn plus 7 is as mushy as 7"
    assert inbetween.rotation_offcut(83) == 7
    assert inbetween.rotation_offcut(45) == 45


@pytest.mark.parametrize(
    ("scale_x", "scale_y", "angle"),
    [(1.0, 1.0, 30), (2.0, 0.5, 0), (1.3, 0.6, 15), (0.75, 1.25, 180)],
)
def test_the_inverse_transform_undoes_the_forward_one(scale_x, scale_y, angle):
    forward = inbetween.forward_transform(scale_x, scale_y, angle)
    inverse = inbetween.inverse_transform(scale_x, scale_y, angle)
    for x, y in ((1.0, 0.0), (0.0, 1.0), (3.0, -4.0)):
        fx = forward[0] * x + forward[1] * y
        fy = forward[2] * x + forward[3] * y
        assert inverse[0] * fx + inverse[1] * fy == pytest.approx(x, abs=1e-9)
        assert inverse[2] * fx + inverse[3] * fy == pytest.approx(y, abs=1e-9)


def test_a_positive_rotation_turns_clockwise_on_screen():
    """y grows downward in image space, and clockwise is what the caller means."""
    m00, m01, m10, m11 = inbetween.forward_transform(1.0, 1.0, 90)
    # (1, 0) points right; a clockwise quarter turn sends it down, to (0, 1).
    assert (m00 * 1 + m01 * 0, m10 * 1 + m11 * 0) == (0.0, 1.0)


def test_a_squash_scales_the_two_axes_independently():
    m00, _, _, m11 = inbetween.forward_transform(1.25, 0.7, 0)
    assert (m00, m11) == (1.25, 0.7)


# ------------------------------------------------------------------------ plan_tween
def test_a_tween_plan_carries_one_step_per_frame_with_both_matrices():
    plan = inbetween.plan_tween(4, scale_to=2.0, ease="linear")
    assert len(plan["steps"]) == 4
    assert plan["steps"][0]["scale_x"] == 1.0
    assert plan["steps"][-1]["scale_x"] == 2.0
    assert {"f00", "f01", "f10", "f11", "m00", "m01", "m10", "m11"} <= set(plan["steps"][0])


def test_the_vertical_scale_defaults_to_the_horizontal_one():
    plan = inbetween.plan_tween(3, scale_to=1.5)
    assert [s["scale_y"] for s in plan["steps"]] == [s["scale_x"] for s in plan["steps"]]


def test_a_squash_sends_the_two_axes_opposite_ways():
    plan = inbetween.plan_tween(
        3, scale_from=1.0, scale_to=1.3, scale_y_from=1.0, scale_y_to=0.6,
    )
    assert [s["scale_x"] for s in plan["steps"]] == [1.0, 1.15, 1.3]
    assert [s["scale_y"] for s in plan["steps"]] == [1.0, 0.8, 0.6]


def test_a_shallow_rotation_is_called_out_rather_than_quietly_mushed():
    plan = inbetween.plan_tween(4, rotate_to=9)
    assert plan["warnings"], "9 degrees over 4 frames is 3 degrees a frame"
    assert "quarter turn" in plan["warnings"][0]


def test_a_quarter_turn_draws_no_warning():
    assert inbetween.plan_tween(2, rotate_to=90)["warnings"] == []


def test_a_tween_needs_two_frames_and_a_known_easing():
    with pytest.raises(ValueError, match="at least 2 frames"):
        inbetween.plan_tween(1, scale_to=2.0)
    with pytest.raises(ValueError, match="unknown easing"):
        inbetween.plan_tween(3, scale_to=2.0, ease="bouncy")


def test_opacity_is_clamped_into_the_range_a_cel_can_hold():
    plan = inbetween.plan_tween(3, opacity_from=255, opacity_to=0)
    assert [s["opacity"] for s in plan["steps"]] == [255, 127, 0]
    assert all(0 <= s["opacity"] <= 255 for s in plan["steps"])


# ------------------------------------------------------------------------- the smear
def test_the_vector_comes_from_where_the_drawing_sits():
    """Not from `cel.position`: every tool here that writes a whole canvas back leaves
    the position at (0, 0) on every frame, so a position diff would read zero."""
    before = {"x": 10, "y": 20, "width": 8, "height": 8}
    after = {"x": 22, "y": 17, "width": 8, "height": 8}
    assert inbetween.smear_vector(before, after) == (12, -3)


def test_a_subject_that_changes_shape_still_measures_its_box_centre():
    before = {"x": 0, "y": 0, "width": 9, "height": 9}
    after = {"x": 10, "y": 0, "width": 5, "height": 13}
    assert inbetween.smear_vector(before, after) == (8, 2)


def test_a_trail_steps_back_one_pixel_at_a_time_without_repeats():
    offsets = inbetween.trail_offsets((10, 0), 0.6)
    assert offsets == [(-1, 0), (-2, 0), (-3, 0), (-4, 0), (-5, 0), (-6, 0)]
    assert len(set(offsets)) == len(offsets)


def test_a_diagonal_trail_is_a_staircase_with_no_gaps():
    offsets = inbetween.trail_offsets((8, 8), 1.0)
    assert offsets == [(-i, -i) for i in range(1, 9)]


def test_a_trail_shorter_than_a_pixel_is_empty_rather_than_a_dot():
    """The tool turns this into a refusal that names the movement and the strength."""
    assert inbetween.trail_offsets((1, 0), 0.4) == []


def test_echo_copies_are_spread_evenly_and_reach_the_far_end_exactly():
    offsets = inbetween.echo_offsets((12, 0), 1.0, 4)
    assert offsets == [(-3, 0), (-6, 0), (-9, 0), (-12, 0)]


def test_an_echo_whose_reach_rounds_to_nothing_is_empty_rather_than_a_pile():
    """Otherwise `steps` copies are all stamped on the subject at (0, 0): a call that
    draws nothing and reports success for it. The tool turns the empty list into the same
    refusal a too-short stretch gets."""
    assert inbetween.echo_offsets((1, 0), 0.3, 4) == []
    assert inbetween.plan_smear((1, 0), mode="echo", strength=0.3, steps=4,
                                ramp_length=5)["plots"] == []


def test_copies_landing_on_top_of_each_other_are_counted_and_called_out():
    """They are all still drawn, nearest last, so the picture is right; what would be
    wrong is reporting four copies when two are visible."""
    plan = inbetween.plan_smear((3, 0), mode="echo", strength=1.0, steps=4,
                                ramp_length=5)
    assert plan["copies"] == 4
    assert plan["distinct_positions"] == 3
    assert plan["warnings"] and "on top of each other" in plan["warnings"][0]


def test_copies_that_all_fit_draw_no_warning():
    plan = inbetween.plan_smear((16, 0), mode="echo", strength=1.0, steps=4,
                                ramp_length=5)
    assert plan["distinct_positions"] == 4
    assert plan["warnings"] == []


def test_the_perpendicular_is_the_axis_a_smear_thins_across():
    assert inbetween.perpendicular((5, 0)) == (0.0, 1.0)
    assert inbetween.perpendicular((0, -5)) == (1.0, 0.0)


def test_the_half_extent_is_the_box_projected_onto_that_axis():
    box = {"x": 0, "y": 0, "width": 11, "height": 21}
    assert inbetween.box_half_extent(box, (0.0, 1.0)) == 10.0
    assert inbetween.box_half_extent(box, (1.0, 0.0)) == 5.0


def test_the_plots_come_back_furthest_first_so_the_nearer_copy_wins():
    plan = inbetween.plan_smear((10, 0), mode="stretch", strength=1.0, steps=3,
                                ramp_length=5)
    distances = [math.hypot(p["dx"], p["dy"]) for p in plan["plots"]]
    assert distances == sorted(distances, reverse=True)
    assert plan["plots"][0]["shift"] >= plan["plots"][-1]["shift"]


def test_every_trail_copy_is_at_least_one_step_down_the_ramp():
    """A copy on the subject's own colour is a copy nobody can see."""
    plan = inbetween.plan_smear((20, 0), mode="stretch", strength=1.0, steps=3,
                                ramp_length=5)
    assert all(p["shift"] >= 1 for p in plan["plots"])
    assert max(p["shift"] for p in plan["plots"]) == 4


def test_without_a_ramp_the_plots_carry_an_alpha_that_never_reaches_zero():
    plan = inbetween.plan_smear((10, 0), mode="echo", strength=1.0, steps=4,
                                ramp_length=0)
    assert all(p["shift"] == 0 for p in plan["plots"])
    assert min(p["alpha"] for p in plan["plots"]) == inbetween.MIN_TRAIL_ALPHA


def test_an_unknown_smear_mode_lists_the_ones_that_exist():
    with pytest.raises(ValueError, match="stretch, echo"):
        inbetween.plan_smear((5, 0), mode="blur", strength=1.0, steps=3, ramp_length=5)


# ------------------------------------------------------------------- ramp matching
def test_a_colour_matches_the_ramp_entry_it_belongs_to():
    assert inbetween.nearest_ramp_index((176, 74, 90), RAMP) == 2
    assert inbetween.nearest_ramp_index((0, 0, 0), RAMP) == 0
    assert inbetween.nearest_ramp_index((255, 255, 255), RAMP) == 4


def test_matching_is_weighted_the_way_the_eye_is():
    """Unweighted RGB distance picks visibly wrong neighbours on a hue-shifted ramp, and
    a hue-shifted ramp is the kind pixel art uses. The eye weighs green about five times
    as heavily as blue, so the two metrics disagree here and the weighted one is right."""
    ramp = [(0, 50, 0), (0, 0, 60)]
    plain = min(
        range(2), key=lambda i: sum(c**2 for c in ramp[i])
    )
    assert plain == 0, "plain RGB distance prefers the 50-away green"
    assert inbetween.nearest_ramp_index((0, 0, 0), ramp) == 1


def test_a_shift_table_only_ever_produces_ramp_colours():
    colors = [{"px": 7, "r": 176, "g": 74, "b": 90},
              {"px": 9, "r": 242, "g": 204, "b": 143}]
    table = inbetween.shift_table(colors, RAMP, [1, 2, 3])
    produced = {
        (c["r"], c["g"], c["b"]) for per_shift in table.values() for c in per_shift.values()
    }
    assert produced <= set(RAMP)


def test_a_shift_table_is_keyed_by_shift_then_by_the_raw_pixel_value():
    """The Lua side picks one table per copy and then looks a colour up in it. Getting
    this nesting the wrong way round made a ramped smear fall back to alpha in silence."""
    table = inbetween.shift_table([{"px": 7, "r": 176, "g": 74, "b": 90}], RAMP, [1, 2])
    assert sorted(table) == [1, 2]
    assert table[1][7] == {"r": 107, "g": 45, "b": 74}
    assert table[2][7] == {"r": 44, "g": 27, "b": 46}


def test_a_shift_is_clamped_at_the_dark_end_and_never_wrapped():
    """A trail that wraps round to the highlight produces the opposite of the request."""
    table = inbetween.shift_table([{"px": 7, "r": 107, "g": 45, "b": 74}], RAMP, [1, 4, 9])
    assert table[4][7] == {"r": 44, "g": 27, "b": 46}
    assert table[9][7] == table[4][7]


def test_headroom_is_the_art_s_own_position_on_the_ramp_not_the_ramp_s_length():
    """A subject on the third step of a nine-colour ramp has two steps below it, not
    eight, and that is what decides whether the copies read apart."""
    mid = [{"px": 1, "r": 176, "g": 74, "b": 90}]
    assert inbetween.ramp_headroom(mid, RAMP) == 2
    lightest = [{"px": 1, "r": 242, "g": 204, "b": 143}]
    assert inbetween.ramp_headroom(lightest, RAMP) == 4
    darkest = [{"px": 1, "r": 44, "g": 27, "b": 46}]
    assert inbetween.ramp_headroom(darkest, RAMP) == 0


def test_headroom_is_taken_from_the_lightest_colour_in_the_art():
    both = [{"px": 1, "r": 44, "g": 27, "b": 46},
            {"px": 2, "r": 224, "g": 122, "b": 95}]
    assert inbetween.ramp_headroom(both, RAMP) == 3
