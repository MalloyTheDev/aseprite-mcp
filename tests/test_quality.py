"""The computable quality metrics, tested without Aseprite.

These are pure functions over a pixel grid, which is the whole point: the measurement
has to run on a CI machine with no editor installed, or it will not run at all and the
claims it exists to check go unverified.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import quality

T = "#00000000"


def grid(rows: list[str], legend: dict[str, str]) -> quality.Grid:
    """Build a grid from an ASCII picture, the same shape get_pixels returns."""
    return [[legend.get(c, T) for c in row] for row in rows]


RED = {"a": "#ff0000ff"}


def test_distinct_colors_counts_only_opaque_pixels():
    g = grid(["ab", ".."], {"a": "#ff0000ff", "b": "#00ff00ff"})
    assert quality.distinct_colors(g) == 2
    assert quality.distinct_colors(grid(["..", ".."], {})) == 0


def test_isolated_pixels_finds_a_lone_dot_and_ignores_a_block():
    block = grid(["....", ".aa.", ".aa.", "...."], RED)
    assert quality.isolated_pixels(block) == 0

    speck = grid(["...a", ".aa.", ".aa.", "...."], RED)
    assert quality.isolated_pixels(speck) == 1


def test_isolated_pixels_needs_a_same_coloured_neighbour():
    """A pixel touching only a different colour is still isolated in its own ramp."""
    g = grid(["ab"], {"a": "#ff0000ff", "b": "#00ff00ff"})
    assert quality.isolated_pixels(g) == 2


def test_jaggy_corners_counts_staircase_steps():
    square = grid(["aaa", "aaa", "aaa"], RED)
    assert quality.jaggy_corners(square) == 0

    step = grid(["aa.", "aaa", "aaa"], RED)
    assert quality.jaggy_corners(step) == 1


def test_bounding_box_and_usage():
    g = grid(["....", ".aa.", ".aa.", "...."], RED)
    box = quality.bounding_box(g)
    assert box == (1, 1, 2, 2)
    assert box.width == 2 and box.height == 2
    assert quality.canvas_usage(g) == pytest.approx(4 / 16)
    assert quality.bounding_box(grid(["..", ".."], {})) is None


def test_centred_allows_one_pixel_because_odd_shapes_cannot_sit_on_an_even_canvas():
    centred = grid(["....", ".aa.", ".aa.", "...."], RED)
    assert quality.is_centred(centred)

    # An odd-width shape on an even canvas is off by one whichever way it goes, which
    # is a property of the canvas rather than a mistake, so it still counts as centred.
    odd = grid(["....", ".aaa", ".aaa", "...."], RED)
    assert quality.is_centred(odd)

    shoved = grid(["....", "aa..", "aa..", "...."], RED)
    assert not quality.is_centred(shoved)


def test_silhouette_asymmetry():
    symmetric = grid([".aa.", ".aa."], RED)
    assert quality.silhouette_asymmetry(symmetric) == 0

    # Every column differs from its mirror here, both the opaque ones and the
    # transparent ones they map onto, so a 4x2 grid contributes 8 rather than 4.
    lopsided = grid(["aa..", "aa.."], RED)
    assert quality.silhouette_asymmetry(lopsided) == 8


def test_palette_conformance_is_the_measurement_that_separates_shading_from_filtering():
    """A ramp-aware operation scores 1.0; an image filter scores near 0 by construction."""
    ramp = ["#2a1a1aff", "#603030ff", "#a05050ff"]
    on_ramp = grid(["aa", "aa"], {"a": "#603030ff"})
    assert quality.palette_conformance(on_ramp, ramp) == 1.0

    # One step off in a single channel, which is what a brightness adjustment does.
    nudged = grid(["aa", "aa"], {"a": "#613131ff"})
    assert quality.palette_conformance(nudged, ramp) == 0.0

    half = grid(["ab", "ab"], {"a": "#603030ff", "b": "#613131ff"})
    assert quality.palette_conformance(half, ramp) == 0.5


def test_palette_conformance_of_an_empty_sprite_is_not_a_failure():
    assert quality.palette_conformance(grid(["..", ".."], {}), ["#000000ff"]) == 1.0


def test_tile_seam_ratio_identifies_which_axis_is_broken():
    """A tile commonly wraps on one axis and not the other, and which is most of the fix."""
    # Horizontally this alternates between two near-identical greys, so the wrap
    # transition looks exactly like an interior one. Vertically it ramps from dark to
    # light and then jumps straight back at the wrap, which is a visible seam.
    shades = {
        "a": "#202020ff", "b": "#282828ff",
        "c": "#404040ff", "d": "#484848ff",
        "e": "#606060ff", "f": "#686868ff",
        "g": "#808080ff", "h": "#888888ff",
    }
    seam = grid(["abab", "cdcd", "efef", "ghgh"], shades)
    horizontal, vertical = quality.tile_seam_ratio(seam)
    assert horizontal == pytest.approx(1.0, abs=0.2), horizontal
    assert vertical > 2.0, vertical
    assert horizontal < vertical


def test_loop_closure_flags_a_duplicated_seam_frame():
    a = grid(["aa", ".."], RED)
    b = grid(["..", "aa"], RED)
    # Last frame identical to the first: the classic double-hold at the loop seam.
    assert quality.loop_closure([a, b, a]) == 0.0
    assert quality.loop_closure([a, a, b]) > 0.0


def test_score_omits_palette_conformance_when_no_ramp_was_declared():
    """Reporting 1.0 with no ramp would be a meaningless pass."""
    g = grid([".aa.", ".aa."], RED)
    assert "palette_conformance" not in quality.score(g)
    assert "palette_conformance" in quality.score(g, ["#ff0000ff"])
