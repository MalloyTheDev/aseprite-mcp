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


# ------------------------------------------------------------------------ readings
# A number is not a verdict, and the caller cannot see the sprite. These check the
# reading is produced when it should be and, more importantly, kept quiet when it
# should not: a report that comments on every sprite is one nobody reads.


def _grid(width: int, height: int, points) -> quality.Grid:
    """A blank canvas with the given (x, y, colour) pixels painted on it."""
    canvas = [[T for _ in range(width)] for _ in range(height)]
    for x, y, colour in points:
        canvas[y][x] = colour
    return canvas


def _metrics(picture, ramp=None):
    return quality.score(picture, ramp)


def test_an_empty_frame_says_so_and_stops():
    notes = quality.readings(_metrics(_grid(4, 4, [])), width=4, height=4)
    assert notes == ["Nothing is drawn on this frame."]


def test_art_lost_in_its_canvas_is_reported_with_both_sizes():
    grid = _grid(32, 32, [(x, y, "#ffffffff") for x in range(4) for y in range(4)])
    notes = quality.readings(_metrics(grid), width=32, height=32)
    assert any("4x4 of 32x32" in line for line in notes)
    assert any("trim_sprite" in line for line in notes)


def test_a_sprite_that_fills_its_canvas_draws_no_comment_about_size():
    grid = _grid(8, 8, [(x, y, "#ffffffff") for x in range(8) for y in range(8)])
    notes = quality.readings(_metrics(grid), width=8, height=8)
    assert not any("canvas" in line for line in notes)


def test_off_ramp_pixels_name_the_tools_that_put_them_back():
    ramp = ["#202040ff", "#4060a0ff", "#80c0ffff"]
    grid = _grid(8, 8, [(x, 0, "#ff00ffff") for x in range(8)])
    notes = quality.readings(_metrics(grid, ramp), width=8, height=8)
    assert any("off the declared ramp" in line for line in notes)
    assert any("shift_along_ramp" in line for line in notes)


def test_a_round_shape_is_not_told_off_for_being_round():
    """A raster circle is made of steps. The threshold is a share of the shape's size,
    so stepping that is inherent to the resolution stays quiet."""
    points = [(x, y, "#ffffffff") for x in range(24) for y in range(24)
              if ((x - 11.5) / 12) ** 2 + ((y - 11.5) / 12) ** 2 <= 1.0]
    notes = quality.readings(_metrics(_grid(24, 24, points)), width=24, height=24)
    assert not any("jagged" in line for line in notes)


def test_near_symmetry_is_worth_a_word_and_gross_asymmetry_is_not():
    symmetric = [(x, y, "#ffffffff") for x in range(4, 12) for y in range(4, 12)]
    nearly = _grid(16, 16, [*symmetric, (2, 5, "#ffffffff")])
    assert any("Nearly symmetric" in line
               for line in quality.readings(_metrics(nearly), width=16, height=16))

    lopsided = _grid(16, 16, [(x, y, "#ffffffff") for x in range(0, 6) for y in range(16)])
    assert not any("symmetric" in line
                   for line in quality.readings(_metrics(lopsided), width=16, height=16))


def test_clean_art_produces_no_readings_at_all():
    """The report has to be able to say nothing, or it says nothing worth reading."""
    points = [(x, y, "#4060a0ff") for x in range(3, 13) for y in range(3, 13)]
    notes = quality.readings(_metrics(_grid(16, 16, points), ["#4060a0ff"]),
                             width=16, height=16)
    assert notes == []


def test_drawn_pixels_counts_the_painted_ones_not_the_box():
    grid = _grid(16, 16, [(0, 0, "#ffffffff"), (15, 15, "#ffffffff")])
    assert quality.score(grid)["drawn_pixels"] == 2
    assert quality.score(grid)["canvas_usage"] == 1.0
