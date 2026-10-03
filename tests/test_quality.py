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


# ============ the five measurements a welded, clipped, flat figure used to pass =========
# Added after a four-critic review of this project's own showcase art found that every
# metric above passed on a figure that read as one grey slab: it had a sensible colour
# count, no stray pixels, a reasonable bounding box, and no form whatsoever. Each
# threshold here is a number measured off reference art, recorded in `core/quality.py`.

T = "#00000000"          # transparent


def _from_map(rows, legend):
    """A grid from a character map, which is how these cases stay readable."""
    return [[legend[ch] for ch in row] for row in rows]


def test_row_structure_counts_the_air_between_limbs():
    """The measurement no other one here makes: a silhouette can have a perfect bounding
    box and be one welded mass."""
    legend = {".": T, "#": "#ffffffff"}
    two_legs = _from_map(["##..##", "##..##", "##..##"], legend)
    one_slab = _from_map(["######", "######", "######"], legend)

    open_shape = quality.row_structure(two_legs)
    assert open_shape["rows_with_air"] == 3
    assert open_shape["welded_rows"] == 0
    assert open_shape["widest_run"] == 2

    welded = quality.row_structure(one_slab)
    assert welded["rows_with_air"] == 0
    assert welded["welded_rows"] == 3
    assert welded["widest_run"] == 6


def test_waists_tell_a_figure_apart_from_a_single_convex_mass():
    """The gate that stops the welding reading firing on every circle.

    A disc is one unbroken run on every row, which is true of all discs and is not a
    defect. What makes the welding reading meaningful is evidence that the shape has
    parts: either background between two of them on some row, or a narrowing with more
    shape below it. The second is the one that matters on its own, because a figure
    welded so completely that no row has any gap is the worst case and counting gaps
    alone would pass it.
    """
    legend = {".": T, "#": "#ffffffff"}
    # A convex blob: widens once, narrows once.
    blob = _from_map([
        "..##..",
        ".####.",
        "######",
        ".####.",
        "..##..",
    ], legend)
    assert quality.row_structure(blob)["waists"] == 0

    # A figure with a neck and a waist, and not one pixel of background between parts on
    # any row, so this is exactly the case `rows_with_air` cannot see.
    figure = _from_map([
        "..##..",
        "..##..",
        "######",
        "######",
        ".####.",
        "..##..",
        "######",
        "######",
    ], legend)
    structure = quality.row_structure(figure)
    assert structure["rows_with_air"] == 0, "the fixture is meant to have no gaps at all"
    assert structure["waists"] >= 1, structure

    # A single pixel of jitter is a curve stair-stepping, not a waist.
    curve = _from_map([
        "..##..",
        ".###..",
        "..##..",
        ".###..",
    ], legend)
    assert quality.row_structure(curve)["waists"] == 0, (
        "a one-pixel dip counted as a waist, so every antialiased edge is a figure")


def test_edge_contact_finds_a_silhouette_cut_off_by_its_canvas():
    """A figure touching the border cannot take an outline there, so it dissolves on
    exactly the side that touches. Cheap to measure and easy to miss: the figure this was
    written for had a part placed at a negative coordinate and quietly clipped."""
    legend = {".": T, "#": "#ffffffff"}
    inside = _from_map(["....", ".##.", ".##.", "...."], legend)
    touching = _from_map(["#...", ".##.", ".##.", "...#"], legend)
    assert quality.edge_contact(inside) == 0
    assert quality.edge_contact(touching) == 2


def test_tone_shares_names_the_colour_that_is_doing_the_filling():
    """Reported, but deliberately not turned into a reading.

    A threshold on this number was tried and withdrawn: at 40 percent it fired on the
    clean reference orb, which spends 51 percent of itself on one midtone because a
    five-step ramp on a sphere has to, and stayed silent on the welded figure it was
    written for, which spends 19. The measurement is still worth having in the metrics;
    the line of advice is not, which is why no threshold constant accompanies it.
    """
    legend = {".": T, "a": "#101010ff", "b": "#808080ff", "c": "#f0f0f0ff"}
    formed = _from_map(["abc", "abc", "abc"], legend)
    flat = _from_map(["bbb", "bbb", "abc"], legend)
    assert quality.tone_shares(formed)["top_share"] == pytest.approx(1 / 3, abs=0.01)
    filled = quality.tone_shares(flat)
    assert filled["top_color"] == "#808080"
    assert filled["top_share"] == pytest.approx(7 / 9, abs=0.01)
    assert filled["tones"] == 3
    assert not hasattr(quality, "FLAT_TONE_SHARE"), (
        "the flat-tone threshold is back; it could not tell the clean orb from the "
        "welded figure, and in the wrong direction")


def test_separator_share_measures_the_keyline_and_how_dark_it_is():
    """A separator has to be near black to read as one, and has to cover enough of the
    sprite to separate anything. Both halves are reported because a mid tone covering a
    fifth of the figure is not a keyline either."""
    legend = {"k": "#05050aff", "m": "#9a9a9aff"}
    keyed = _from_map(["kkkk", "kmmk", "kmmk", "kkkk"], legend)
    out = quality.separator_share(keyed)
    assert out["separator"] == "#05050a"
    assert out["share"] == pytest.approx(12 / 16, abs=0.01)
    assert out["lightness"] < 0.1

    pale = quality.separator_share(_from_map(["mmmm", "mkkm"], {"m": "#9a9a9aff",
                                                            "k": "#6a6a6aff"}))
    assert pale["lightness"] > 0.25, "a mid tone must not pass as a separator"


def test_ramp_chroma_catches_a_hue_rotation_that_goes_through_grey():
    """The finding this exists for. A ramp interpolated between two endpoints on opposite
    sides of the colour wheel routes through the neutral axis, and the middle of that path
    is grey: the ramp that failed rotated 227 degrees and rendered as eight greys. So the
    number that matters is the saturation floor, not the hue span."""
    through_grey = ["#241f2a", "#3a353e", "#524c53", "#6b6568",
                    "#857f7f", "#a09a96", "#bbb6ae", "#d8d2c6"]
    measured = quality.ramp_chroma(through_grey)
    assert measured["hue_span"] > 100, measured
    assert measured["sat_floor"] < 0.05, measured
    assert measured["grey_steps"] >= 5, measured

    held = ["#2a1020", "#5e2338", "#9c4436", "#ce7219", "#e8a63c", "#f7d98e"]
    kept = quality.ramp_chroma(held)
    assert kept["sat_floor"] > quality.HUE_INVISIBLE_SAT, kept
    assert kept["grey_steps"] == 0, kept


def test_the_silhouette_readings_stay_silent_on_a_full_bleed_scene():
    """A scene fills its canvas on purpose, so "the masses have fused" is true and
    meaningless. The first version of these readings fired on a lava cavern, correctly
    measuring that every one of its rows was one run, which is what a cavern is."""
    scene = _from_map(["aaaa", "aaaa", "aaaa", "aaaa"], {"a": "#404040ff"})
    metrics = quality.score(scene)
    lines = quality.readings(metrics, width=4, height=4)
    assert not [line for line in lines if "fused" in line or "border" in line], lines

    # Three tones, because these readings are about form and are deliberately not given
    # to art that is not attempting any: a flat one-colour shape is a silhouette, not a
    # surface with no form. This fixture needed a third colour for exactly that reason.
    #
    # And one row of background between two parts, because that is the other thing these
    # readings require. The fixture was a solid shaded block until the articulation gate
    # went in, at which point it correctly went quiet: a convex slab has no limbs to
    # separate, and the reading that told it to separate them was the false positive
    # being fixed. What has to keep firing is a figure that *does* have parts and has
    # fused them anyway, so that is what this now is.
    sprite_shape = _from_map(
        ["aabaa", "abbba", "abcba", "aa.aa", "aabaa"],
        {".": T, "a": "#202020ff", "b": "#808080ff", "c": "#e0e0e0ff"})
    sprite_lines = quality.readings(quality.score(sprite_shape), width=5, height=5)
    assert [line for line in sprite_lines if "fused" in line], (
        "a shaded shape with transparency is a silhouette and must still be judged")
