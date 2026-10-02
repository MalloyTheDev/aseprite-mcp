"""Ramp arithmetic without Aseprite (always runs).

Two jobs: building a ramp from its ends, and recovering one from art. Both are colour
maths, and both have a failure mode that looks fine until someone shades with the result,
so they are checked against numbers here rather than against pictures elsewhere.
"""

from __future__ import annotations

import colorsys

import pytest

from aseprite_mcp.core import ramps


def rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def saturation(colour: str) -> float:
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb(colour)))[2]


# ------------------------------------------------------------------------ interpolate
def test_the_ends_come_back_exactly_as_given():
    built = ramps.interpolate((27, 42, 82), (255, 233, 196), 5)
    assert built[0] == "#1b2a52"
    assert built[-1] == "#ffe9c4"
    assert len(built) == 5


def test_a_ramp_runs_dark_to_light():
    built = ramps.interpolate((20, 20, 30), (240, 240, 250), 6)
    lums = [ramps.luminance(rgb(c)) for c in built]
    assert lums == sorted(lums)


def test_a_distant_pair_does_not_go_through_magenta():
    """Interpolating hue between a blue shadow and a cream highlight is the classic way
    to get a magenta middle: at that distance both ways round the wheel are equally
    short. Oklab walks between them instead, so the middle desaturates."""
    built = ramps.interpolate((27, 42, 82), (255, 233, 196), 5)
    middle = built[2]
    assert saturation(middle) < 0.2, f"{middle} is too saturated to be a blend"
    hue = colorsys.rgb_to_hls(*(c / 255 for c in rgb(middle)))[0] * 360
    assert not 260 < hue < 340, f"{middle} landed in the magentas"


def test_perceptual_and_linear_are_different_ramps():
    ends = ((27, 42, 82), (255, 233, 196))
    assert ramps.interpolate(*ends, 5, "perceptual") != ramps.interpolate(*ends, 5, "linear")


def test_two_steps_is_just_the_two_ends():
    assert ramps.interpolate((0, 0, 0), (255, 255, 255), 2) == ["#000000", "#ffffff"]


def test_oklab_round_trips():
    for colour in ((27, 42, 82), (255, 233, 196), (120, 200, 60), (0, 0, 0)):
        assert ramps.from_oklab(ramps.to_oklab(colour)) == colour


def test_one_step_is_refused():
    with pytest.raises(ValueError, match="at least 2"):
        ramps.interpolate((0, 0, 0), (255, 255, 255), 1)


def test_an_unknown_easing_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown easing 'smooth'"):
        ramps.interpolate((0, 0, 0), (255, 255, 255), 4, "smooth")


# ------------------------------------------------------------------- recovering a ramp
def test_a_recovered_ramp_is_ordered_and_comes_from_the_art():
    art = {"#602020": 100, "#e0d0b0": 40, "#a06040": 80, "#301010": 60}
    found = ramps.cluster_by_luminance(art, 4)

    assert set(found["colors"]) <= set(art)
    lums = [ramps.luminance(rgb(c)) for c in found["colors"]]
    assert lums == sorted(lums), "a ramp that is not ordered is not a ramp"
    assert abs(sum(found["coverage"]) - 1.0) < 0.01


def test_the_step_a_band_reports_is_the_one_most_of_it_uses():
    """A centroid colour would be one the caller cannot match anything against."""
    art = {"#404040": 500, "#414141": 3, "#f0f0f0": 400}
    found = ramps.cluster_by_luminance(art, 2)
    assert found["colors"][0] == "#404040"


def test_fewer_colours_than_steps_is_said_rather_than_padded():
    found = ramps.cluster_by_luminance({"#202020": 10, "#e0e0e0": 10}, 5)
    assert len(found["colors"]) == 2
    assert any("fewer than the 5 steps" in w for w in found["warnings"])


def test_a_hue_shifted_ramp_draws_no_complaint():
    """The false positive that matters: a cool shadow to a warm highlight crosses half
    the wheel and is exactly what a good ramp looks like."""
    art = {"#17145d": 40, "#283aa7": 90, "#5a7fd4": 200, "#a6c4e6": 120, "#f0f7fb": 50}
    found = ramps.cluster_by_luminance(art, 5)
    assert found["warnings"] == []
    assert found["colors"] == list(art)


def test_two_materials_at_the_same_brightness_are_called_out():
    art = {"#c03030": 300, "#3060c0": 300}
    found = ramps.cluster_by_luminance(art, 2)
    assert any("several materials" in w for w in found["warnings"])


def test_a_stray_off_hue_pixel_is_not_called_a_material():
    """Anti-aliasing and a few dirty pixels are not a second material, and warning about
    them would make the warning worthless."""
    art = {"#c03030": 2000, "#a02828": 900, "#3060c0": 3}
    found = ramps.cluster_by_luminance(art, 2)
    assert not any("several materials" in w for w in found["warnings"])


def test_nothing_drawn_says_so():
    found = ramps.cluster_by_luminance({}, 4)
    assert found["colors"] == []
    assert found["warnings"] == ["Nothing is drawn here."]


def test_one_step_is_refused_here_too():
    with pytest.raises(ValueError, match="at least 2"):
        ramps.cluster_by_luminance({"#000000": 1}, 1)


# ===== clipping =======================================================================
# `generate_ramp` clamps lightness at both ends, so a base near white or near black spends
# its outermost steps on one colour. The ramp is still returned; what was missing was any
# way to find out, and the failure then surfaced two tools later in `specular_highlight`
# with a message about the shading pass.


def test_clipped_ends_counts_the_extra_entries_at_each_end():
    assert ramps.clipped_ends(["#000000", "#111111", "#222222"]) == (0, 0)
    assert ramps.clipped_ends(["#aaaaaa", "#ffffff", "#ffffff"]) == (0, 1)
    assert ramps.clipped_ends(["#000000", "#000000", "#000000", "#333333"]) == (2, 0)
    assert ramps.clipped_ends(["#808080", "#808080"]) == (1, 1), (
        "a two-entry ramp of one colour has collapsed from both directions"
    )
    assert ramps.clipped_ends(["#808080"]) == (0, 0)
    assert ramps.clipped_ends([]) == (0, 0)


def test_clipped_ends_does_not_claim_an_end_for_a_duplicate_in_the_middle():
    """A pair rounding together mid-ramp is a different problem from a clamped end."""
    assert ramps.clipped_ends(["#101010", "#404040", "#404040", "#f0f0f0"]) == (0, 0)


def test_nearest_unclipped_looks_both_ways():
    """Distinctness is not monotonic in light_range, so a bisection would be wrong.

    Too wide clamps the ends onto each other; too narrow rounds neighbours onto the same
    hex. The answer can therefore lie either side of what was asked for.
    """
    # Workable in a window around 0.5, so asking from below and from above should both
    # walk toward it rather than away.
    def rebuild(span):
        return ["a", "b", "c"] if 0.40 <= span <= 0.60 else ["a", "a", "c"]

    assert ramps.nearest_unclipped(rebuild, 3, 0.20) == 0.40
    assert ramps.nearest_unclipped(rebuild, 3, 0.90) == 0.60
    assert ramps.nearest_unclipped(rebuild, 3, 0.50) == 0.50


def test_nearest_unclipped_returns_nothing_rather_than_a_value_that_does_not_work():
    assert ramps.nearest_unclipped(lambda span: ["a", "a"], 2, 0.5) is None


def test_clip_warning_names_the_end_the_steps_went_to():
    light = ramps.clip_warning(["#cccccc", "#ffffff", "#ffffff"], 3, 0.47)
    assert "the top 2 entries are all #ffffff" in light
    assert "light_range=0.47" in light
    assert "specular_highlight" in light, (
        "a collapsed top step is specifically what breaks a glint, so say so"
    )

    dark = ramps.clip_warning(["#000000", "#000000", "#cccccc"], 3, 0.13)
    assert "the bottom 2 entries are all #000000" in dark
    assert "specular_highlight" not in dark, (
        "the dark end has a different problem and does not need a note about glints"
    )

    middle = ramps.clip_warning(["#101010", "#404040", "#404040", "#f0f0f0"], 4, 0.3)
    assert "too narrow for this many steps" in middle


def test_clip_warning_says_so_when_no_range_would_work():
    assert "ask for fewer steps" in ramps.clip_warning(["#888888", "#888888"], 2, None)
