"""Lighting arithmetic: light directions, specular geometry, shadow projection, glow rings.

Pure, so it runs on CI where there is no editor. These are the decisions the shading and
effects tools make before they touch a pixel, and the two worth testing hardest are the
ones whose errors are invisible in a preview: a shadow on the wrong side reads as a
shadow, and a specular on the diffuse peak reads as a highlight.
"""

from __future__ import annotations

import math

import pytest

from aseprite_mcp.core import lighting


def _length(v):
    return math.sqrt(sum(c * c for c in v))


# ----------------------------------------------------------------- light directions
def test_a_light_from_above_points_up_the_screen():
    """The sign error that makes every sprite look lit from below.

    Screen y grows downward, so a light at 90 degrees has to arrive with a NEGATIVE y.
    """
    x, y, _ = lighting.light_vector(90, 0.0)
    assert y < 0
    assert abs(x) < 1e-9


@pytest.mark.parametrize(
    ("angle", "sign_x", "sign_y"),
    [(0, 1, 0), (90, 0, -1), (180, -1, 0), (270, 0, 1), (135, -1, -1), (315, 1, 1)],
)
def test_light_quadrants(angle, sign_x, sign_y):
    x, y, _ = lighting.light_vector(angle, 0.0)
    for component, expected in ((x, sign_x), (y, sign_y)):
        if expected == 0:
            assert abs(component) < 1e-9
        else:
            assert component * expected > 0


def test_light_vectors_are_unit_length():
    for angle in range(0, 360, 15):
        for z in (0.0, 0.45, 1.0):
            assert _length(lighting.light_vector(angle, z)) == pytest.approx(1.0)


def test_a_degenerate_light_does_not_poison_the_lighting_with_nan():
    """A zero vector has no direction; returning the viewer keeps every later term finite.

    A NaN here would propagate into every pixel's ramp index and show up as a sprite that
    did not change, which is the hardest kind of failure to trace back to its cause.
    """
    assert lighting._normalise((0.0, 0.0, 0.0)) == lighting.VIEW


# ----------------------------------------------------------------- the half vector
def test_the_specular_sits_between_the_light_and_the_viewer():
    """The whole reason a specular is not just the diffuse peak.

    The half-vector has to lean toward the viewer (a larger z than the light's own) while
    keeping the light's side of the form, or the glint lands out on the lit shoulder where
    `shade_region_by_light` has already put the ramp's top step.
    """
    light = lighting.light_vector(135, 0.45)
    half = lighting.half_vector(light)

    assert half[2] > light[2], "the half-vector must lean toward the viewer"
    assert half[0] < 0 and half[1] < 0, "and must stay on the upper-left side"
    assert _length(half) == pytest.approx(1.0)


def test_a_light_straight_from_the_viewer_reflects_straight_back():
    """Stated against the vector rather than against an angle.

    `light_vector` cannot produce a light with no sideways component at all, because cos
    and sin are never both zero: even at light_z = 1 the angle still contributes. So the
    degenerate case is checked where it actually lives.
    """
    assert lighting.half_vector(lighting.VIEW) == pytest.approx(lighting.VIEW)


def test_raising_the_light_toward_the_viewer_pulls_the_specular_with_it():
    low = lighting.specular_direction(135, 0.1)
    high = lighting.specular_direction(135, 0.9)
    assert high[2] > low[2]


# ------------------------------------------------------------- cast shadow geometry
# The subject: 13 wide, 27 tall, its contact row at y = 30.
BOX = (8, 4, 20, 30)
CENTRE_X = (BOX[0] + BOX[2]) / 2


@pytest.mark.parametrize(
    ("angle", "description"),
    [(135, "upper left"), (180, "left")],
)
def test_a_light_from_the_left_throws_the_shadow_right(angle, description):
    cx, _, _, _ = lighting.shadow_ellipse(BOX, angle, 0.5, 30)
    assert cx > CENTRE_X, f"a light from the {description} must cast to the right"


@pytest.mark.parametrize(
    ("angle", "description"),
    [(45, "upper right"), (0, "right")],
)
def test_a_light_from_the_right_throws_the_shadow_left(angle, description):
    cx, _, _, _ = lighting.shadow_ellipse(BOX, angle, 0.5, 30)
    assert cx < CENTRE_X, f"a light from the {description} must cast to the left"


def test_an_overhead_light_casts_straight_down():
    cx, cy, _, _ = lighting.shadow_ellipse(BOX, 90, 1.0, 30)
    assert cx == pytest.approx(CENTRE_X, abs=0.5)
    assert cy == 30


def test_lowering_the_light_lengthens_the_shadow():
    """The direction of the change, not a size: the exact pixel count is not the claim."""
    lengths = [
        lighting.shadow_ellipse(BOX, 135, height, 30)[2]
        for height in (1.0, 0.8, 0.6, 0.4, 0.2)
    ]
    assert lengths == sorted(lengths), f"rx must grow as the light drops: {lengths}"
    assert lengths[-1] > lengths[0], lengths


def test_the_light_height_moves_the_length_and_not_the_depth():
    """Depth is the floor's foreshortening, which the light has nothing to do with."""
    depths = {lighting.shadow_ellipse(BOX, 135, h, 30)[3] for h in (0.2, 0.5, 0.9)}
    assert len(depths) == 1, f"ry must not depend on light_height: {depths}"


def test_an_overhead_light_puts_the_shadow_under_the_subject_not_beyond_it():
    """An overhead light adds no reach, so the ellipse is the subject's own width.

    Within a pixel either way: an odd width cannot be halved exactly, and the half-axis
    rounds up rather than losing the edge column.
    """
    width = BOX[2] - BOX[0] + 1
    _, _, rx, _ = lighting.shadow_ellipse(BOX, 135, 1.0, 30)
    assert abs(2 * rx - width) <= 2, (rx, width)


def test_the_shadow_lies_on_the_row_it_was_given():
    for row in (0, 17, 30, 99):
        assert lighting.shadow_ellipse(BOX, 135, 0.5, row)[1] == row


def test_a_one_pixel_subject_still_gets_a_visible_shadow():
    """Rounding a sub-pixel ellipse to nothing would report success having drawn nothing."""
    _, _, rx, ry = lighting.shadow_ellipse((5, 5, 5, 5), 135, 1.0, 5)
    assert rx >= 1 and ry >= 1


def test_a_light_on_the_horizon_is_bounded_rather_than_infinite():
    """light_height is validated above 0 by the tool; the cotangent is capped anyway.

    An unbounded reach becomes an ellipse with a radius of millions, which is an
    allocation rather than a picture.
    """
    assert lighting.shadow_projection(135, 1e-9)["cot_elev"] == lighting._MAX_COT
    assert lighting.shadow_projection(135, 0.0)["cot_elev"] == 0.0


def test_an_overhead_light_reaches_nowhere_sideways():
    assert lighting.shadow_projection(135, 1.0)["cot_elev"] == pytest.approx(0.0)


# ------------------------------------------------------------------ glow ring steps
def test_a_glow_starts_at_the_top_of_the_ramp_and_ends_at_the_bottom():
    rings = lighting.glow_rings(4, 5, "linear")
    assert rings[0] == 5, "the ring touching the artwork takes the ramp's top step"
    assert rings[-1] == 1, "the outermost ring takes the bottom step"


def test_a_glow_never_brightens_as_it_goes_out():
    for radius in range(1, 9):
        for length in range(2, 9):
            for falloff in lighting.FALLOFFS:
                rings = lighting.glow_rings(radius, length, falloff)
                assert rings == sorted(rings, reverse=True), (radius, length, falloff)
                assert all(1 <= step <= length for step in rings)


def test_a_single_ring_glow_takes_the_top_step():
    """radius 1 is t = 0, not a division by zero."""
    assert lighting.glow_rings(1, 5, "linear") == [5]
    assert lighting.glow_rings(1, 5, "quadratic") == [5]


def test_quadratic_falls_away_faster_than_linear():
    """Which is what keeps a hot core and makes it read as a light source."""
    linear = lighting.glow_rings(5, 9, "linear")
    quadratic = lighting.glow_rings(5, 9, "quadratic")
    assert linear[0] == quadratic[0], "both are hottest against the artwork"
    assert all(q <= ln for q, ln in zip(quadratic, linear, strict=True))
    assert quadratic[1] < linear[1], (linear, quadratic)


def test_a_glow_ring_count_matches_the_radius():
    for radius in (1, 3, 7):
        assert len(lighting.glow_rings(radius, 4, "linear")) == radius


def test_glow_rings_refuses_arguments_that_cannot_mean_anything():
    with pytest.raises(ValueError, match="at least 1 ring"):
        lighting.glow_rings(0, 5, "linear")
    with pytest.raises(ValueError, match="at least 2 ramp steps"):
        lighting.glow_rings(3, 1, "linear")
    with pytest.raises(ValueError, match="unknown falloff"):
        lighting.glow_rings(3, 5, "gaussian")


# -------------------------------------------------------------------------- rounding
def test_rounding_matches_the_lua_transcription_at_a_half():
    """Python's round is banker's rounding and Lua's floor(v + 0.5) is not.

    The cast-shadow geometry is computed here and again in Lua, so a disagreement at .5
    would be a test that passes on odd-width subjects and fails on even ones.
    """
    assert lighting._round_half_up(20.5) == 21
    assert lighting._round_half_up(21.5) == 22
    assert round(20.5) == 20, "the stdlib behaviour this exists to avoid"
