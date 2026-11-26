"""The computable quality metrics, tested without Aseprite.

These are pure functions over a pixel grid, which is the whole point: the measurement
has to run on a CI machine with no editor installed, or it will not run at all and the
claims it exists to check go unverified.
"""

from __future__ import annotations

import pytest

import corpus
from aseprite_mcp.core import quality
from aseprite_mcp.core.errors import ValidationFailed

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
    assert out["luminance"] < 0.05
    assert out["contrast"] > quality.WCAG_GRAPHICAL_CONTRAST, (
        f"a near-black keyline against a mid grey should clear 3:1: {out}")

    # A mid tone separating a slightly lighter one does not come apart, and the measure
    # that says so is the contrast ratio rather than the separator's own value.
    pale = quality.separator_share(_from_map(["mmmm", "mkkm"], {"m": "#9a9a9aff",
                                                               "k": "#6a6a6aff"}))
    assert pale["contrast"] < quality.WCAG_GRAPHICAL_CONTRAST, (
        f"a mid tone must not pass as a separator: {pale}")


def test_the_darkest_colour_is_the_one_that_actually_looks_darkest():
    """The bug this replaced, kept as a test because it is invisible by inspection.

    HLS lightness is the mean of a colour's extreme channels, so it reports 0.500 for pure
    yellow and 0.500 for pure blue, whose relative luminances are 0.928 and 0.072. Asked
    for the darkest colour in a sprite made of those two, the previous implementation
    returned **yellow**: the brightest pixel in the picture, named as its keyline. Three
    readings rested on that answer.
    """
    checker = _from_map(["yb", "by"], {"y": "#ffff00ff", "b": "#0000ffff"})
    out = quality.separator_share(checker)
    assert out["separator"] == "#0000ff", (
        f"the darkest colour came back as {out['separator']}; blue is 13 times darker "
        "than yellow and HLS lightness cannot tell them apart")
    assert quality.luminance((255, 255, 0, 255)) > quality.luminance((0, 0, 255, 255))


def test_the_contrast_ratio_is_the_wcag_one():
    """Pinned against the two values the standard itself names, so a change to the
    linearisation or the coefficients cannot pass silently."""
    black, white = (0, 0, 0, 255), (255, 255, 255, 255)
    assert quality.contrast_ratio(black, white) == pytest.approx(21.0, abs=0.05)
    assert quality.contrast_ratio(white, white) == pytest.approx(1.0, abs=0.01)
    # Symmetric, because a ratio between two colours cannot depend on their order.
    mid = (119, 119, 119, 255)
    assert quality.contrast_ratio(black, mid) == pytest.approx(
        quality.contrast_ratio(mid, black), abs=1e-9)


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


def test_an_outline_carrying_half_the_sprite_is_reported_too():
    """The direction this reading shipped without.

    It checked the dark separator's share only from below, so a keyline that was too thin
    was reported and one doing the whole drawing was not. A figure in this project's own
    gallery spends 50.3 percent of its drawn pixels on a near-black outline and passed
    silently: its form is not described by its values at all, it is described by a ring,
    and the interior is three near-white tones with no mid tone between them.
    """
    legend = {".": T, "k": "#141018ff", "a": "#8a8f9aff", "b": "#c8ccd4ff"}
    # Articulated, shaded, and mostly outline: a thick ring with a thin interior.
    heavy = _from_map([
        "kkkkkkkk",
        "kkkkkkkk",
        "kkabbakk",
        "kkabbakk",
        "kkkkkkkk",
        "kkk..kkk",
        "kkk..kkk",
        "kkkkkkkk",
    ], legend)
    measured = quality.separator_share(heavy)
    assert measured["share"] > 0.5, measured
    lines = quality.readings(quality.score(heavy), width=8, height=8)
    hits = [line for line in lines if "doing the drawing" in line]
    assert hits, f"a 50%+ keyline produced no reading: {lines}"

    # And the balanced case stays quiet, so this is a reading and not a tax on outlines.
    balanced = _from_map([
        "..kkkk..",
        ".kaabbk.",
        "kaabbbbk",
        "kaabbbbk",
        "kaabbbbk",
        ".kaabbk.",
        "..k..k..",
        "..k..k..",
    ], legend)
    # Tied to the threshold rather than to a number of my own, so the fixture cannot
    # drift to the wrong side of it without this failing.
    assert (quality.separator_share(balanced)["share"]
            < quality.SEPARATOR_BAND[1] * 2)
    quiet = quality.readings(quality.score(balanced), width=8, height=8)
    assert not [line for line in quiet if "doing the drawing" in line], quiet


# --- the output tiers ------------------------------------------------------------------
# These exist because the first draft of the tiering was indistinguishable from deleting
# the module. Promoting two readings to the defect tier silenced the false complaint on
# every clean sprite in the repository, and also silenced every complaint on the two
# sprites known to be bad, which looked like a pass and was not one. The tests below pin
# both halves: a constructed defect must be reported, and correct art must not be.


def _joined_figure(keyline_rows: int) -> quality.Grid:
    """A head over a narrower neck over a body: one figure, with a waist and no gutter.

    Built joined on purpose. Two separate blocks with background between them would be
    simpler and would prove nothing, because the gutter gate correctly treats that as
    two pictures rather than one articulated figure.
    """
    size = 32
    g = [[T] * size for _ in range(size)]

    def band(y0: int, y1: int, x0: int, x1: int, color: str) -> None:
        for y in range(y0, y1):
            for x in range(x0, x1):
                g[y][x] = color

    band(4, 12, 12, 20, "#787878")      # head
    band(4, 8, 12, 20, "#c8c8c8")       # its lit top
    band(12, 15, 15, 17, "#787878")     # the neck, which is the waist
    band(15, 28, 9, 23, "#787878")      # body
    band(15, 21, 9, 23, "#c8c8c8")      # its lit top
    for y in range(4, 4 + keyline_rows):
        for x in range(12, 20):
            g[y][x] = "#0a0a0a"
    return g


def test_defect_tier_reports_a_constructed_defect() -> None:
    """A figure whose keyline is 3% of the drawing is a defect, not an observation."""
    metrics = quality.score(_joined_figure(1))
    assert metrics["row_structure"]["waists"] > 0, "fixture stopped being articulated"
    assert metrics["separator"]["share"] < quality.SEPARATOR_BAND[0]
    defects = quality.readings(metrics, width=32, height=32, tier=quality.DEFECT)
    assert [d for d in defects if "keyline" in d], defects


def test_defect_tier_is_silent_on_a_keyline_inside_the_band() -> None:
    """The same fixture with a keyline in the band draws nothing, so this is not a tax."""
    metrics = quality.score(_joined_figure(6))
    low, high = quality.SEPARATOR_BAND
    assert low <= metrics["separator"]["share"] <= high, metrics["separator"]
    assert quality.readings(metrics, width=32, height=32, tier=quality.DEFECT) == []


def test_off_ramp_pixels_are_counted_not_rounded() -> None:
    """One stray pixel in a large drawing must not be reported as "0% off the ramp"."""
    size = 32
    g = [[T] * size for _ in range(size)]
    for y in range(6, 26):
        for x in range(6, 26):
            g[y][x] = "#787878"
    g[10][10] = "#ff0080"
    metrics = quality.score(g, ramp=["#101010", "#787878", "#c8c8c8"])
    defects = quality.readings(metrics, width=size, height=size, tier=quality.DEFECT)
    hits = [d for d in defects if "off the declared ramp" in d]
    assert hits, defects
    assert "1 of 400 drawn pixels" in hits[0], hits[0]


def test_tier_argument_partitions_the_readings() -> None:
    """Defects and observations together are exactly the untiered output, in order."""
    metrics = quality.score(_joined_figure(1))
    size = {"width": 32, "height": 32}
    everything = quality.readings(metrics, **size)
    defects = quality.readings(metrics, **size, tier=quality.DEFECT)
    observations = quality.readings(metrics, **size, tier=quality.OBSERVATION)
    assert len(defects) + len(observations) == len(everything)
    assert set(defects) | set(observations) == set(everything)
    assert not set(defects) & set(observations)


def test_an_empty_frame_answers_the_tier_it_was_asked() -> None:
    """The empty-frame early return handed back every reading whatever the tier, so a
    caller asking for defects alone was told an empty frame was one."""
    metrics = quality.score([[T] * 32 for _ in range(32)])
    assert quality.readings(metrics, width=32, height=32, tier=quality.DEFECT) == []
    assert quality.readings(metrics, width=32, height=32, tier=quality.OBSERVATION) == [
        "Nothing is drawn on this frame."]


def test_frame_findings_reports_a_shared_reading_once_with_its_frames() -> None:
    empty = quality.score([[T] * 32 for _ in range(32)])
    fused = quality.score(_joined_figure(1))
    found = quality.frame_findings([(1, empty), (2, fused), (3, empty), (4, fused)],
                                   width=32, height=32)

    keyline = [d for d in found["defects"] if "keyline" in d["reading"]]
    assert [d["frames"] for d in keyline] == [[2, 4]]
    blank = [o for o in found["observations"] if o["reading"].startswith("Nothing is drawn")]
    assert [o["frames"] for o in blank] == [[1, 3]]
    texts = [f["reading"] for f in found["defects"] + found["observations"]]
    assert len(texts) == len(set(texts)), "a reading was reported twice"


def test_frame_findings_splits_the_tiers_exactly_as_readings_does() -> None:
    fused = quality.score(_joined_figure(1))
    found = quality.frame_findings([(7, fused)], width=32, height=32)
    size = {"width": 32, "height": 32}
    assert [d["reading"] for d in found["defects"]] == quality.readings(
        fused, **size, tier=quality.DEFECT)
    assert [o["reading"] for o in found["observations"]] == quality.readings(
        fused, **size, tier=quality.OBSERVATION)


# --- defects and observations, and what the subject is ------------------------------
# `assess_sprite` returns `defects` and `observations` beside `readings`, so a caller can
# gate on one and show the other. They are only safe to gate on if they are the same
# lines: every reading in exactly one tier, each tier in reading order.


def _is_partition(lines: list[str], defects: list[str], observations: list[str]) -> bool:
    """True when `lines` is exactly `defects` and `observations` interleaved, in order."""
    d = o = 0
    for line in lines:
        if d < len(defects) and defects[d] == line:
            d += 1
        elif o < len(observations) and observations[o] == line:
            o += 1
        else:
            return False
    return d == len(defects) and o == len(observations)


_LIT, _MID, _FOOT = "#c8c8c8", "#787878", "#303030"


def _turned(widths: list[int], *, top: int = 8, size: int = 32) -> quality.Grid:
    """A lathe-turned object, one centred row per width: lit on top, a dark foot, and no
    keyline, which is how a pot or a lantern is often drawn and is not a fault in one."""
    g = [[T] * size for _ in range(size)]
    for i, width in enumerate(widths):
        colour = _FOOT if i == len(widths) - 1 else _LIT if i < 3 else _MID
        x0 = (size - width) // 2
        for x in range(x0, x0 + width):
            g[top + i][x] = colour
    return g


# Single objects whose outline goes in and out again. Each has a waist and no row with
# background in it, which is exactly what the limb and keyline readings take for a figure.
PROPS = {
    "vase": [6, 8, 8, 6, 4, 4, 6, 10, 14, 16, 16, 16, 14, 12, 10, 8],
    "lantern": [4, 10, 10, 6, 12, 14, 14, 14, 14, 12, 6, 10, 10, 8],
    "peanut": [6, 10, 12, 12, 10, 6, 4, 6, 10, 14, 16, 16, 14, 10, 6],
}
# Convex, or narrowing only once: never articulated, so the subject changes nothing.
CONTROLS = {
    "disc": [6, 10, 12, 14, 14, 16, 16, 16, 16, 14, 14, 12, 10, 6],
    "bottle": [4, 4, 4, 4, 6, 10, 12, 12, 12, 12, 12, 12, 12, 12, 10],
}


def _constructed() -> list[tuple[str, quality.Grid, list[str] | None]]:
    off_ramp = _turned(PROPS["vase"])
    off_ramp[16][16] = "#ff0080"
    return [
        *((name, _turned(w), None) for name, w in {**PROPS, **CONTROLS}.items()),
        ("joined_thin_keyline", _joined_figure(1), None),
        ("joined_banded_keyline", _joined_figure(6), None),
        ("vase_off_ramp", off_ramp, [_LIT, _MID, _FOOT]),
        ("vase_on_border", _turned(PROPS["vase"], top=0), [_LIT, _MID, _FOOT]),
        ("empty", [[T] * 32 for _ in range(32)], None),
    ]


@pytest.mark.parametrize("subject", ["character", "prop"])
def test_defects_and_observations_partition_the_readings(subject) -> None:
    """Over the whole corpus and the constructed cases, under both subjects."""
    c = corpus.build()
    cases = [(s.name, s.metrics, s.width, s.height)
             for s in list(c.good) + list(c.known_bad) + list(c.mutants)]
    cases += [(name, quality.score(g, ramp), len(g[0]), len(g))
              for name, g, ramp in _constructed()]
    both_tiers = False
    for name, metrics, width, height in cases:
        size = {"width": width, "height": height, "subject": subject}
        split = quality.by_tier(quality.tiered_readings(metrics, **size))
        assert split["readings"] == quality.readings(metrics, **size), name
        assert split["defects"] == quality.readings(metrics, **size, tier=quality.DEFECT)
        assert split["observations"] == quality.readings(metrics, **size,
                                                         tier=quality.OBSERVATION)
        assert _is_partition(split["readings"], split["defects"], split["observations"]), (
            name, split)
        both_tiers |= bool(split["defects"]) and bool(split["observations"])
    assert both_tiers, "no case had a reading in each tier, so the interleaving is untested"


def test_the_partition_check_rejects_a_reordered_or_duplicated_split() -> None:
    lines = ["a", "b", "c"]
    assert _is_partition(lines, ["b"], ["a", "c"])
    assert not _is_partition(lines, ["b"], ["c", "a"])
    assert not _is_partition(lines, ["b", "b"], ["a", "c"])
    assert not _is_partition(lines, [], ["a", "c"])


@pytest.mark.parametrize("name", sorted(PROPS))
def test_a_prop_is_not_told_to_separate_limbs_or_given_a_keyline_defect(name) -> None:
    metrics = quality.score(_turned(PROPS[name]))
    rows = metrics["row_structure"]
    assert rows["waists"] >= 1 and rows["rows_with_air"] == 0, rows
    size = {"width": 32, "height": 32}

    as_character = quality.readings(metrics, **size)
    assert [r for r in as_character if "masses have fused" in r], as_character
    assert [r for r in quality.readings(metrics, **size, tier=quality.DEFECT)
            if "keyline" in r], "the fixture no longer draws the keyline defect"

    as_prop = quality.readings(metrics, **size, subject="prop")
    assert not [r for r in as_prop if "fused" in r or "darkest colour" in r], as_prop
    assert quality.readings(metrics, **size, tier=quality.DEFECT, subject="prop") == []
    # Nothing else moved: the prop's readings are the character's minus those two.
    assert as_prop == [r for r in as_character
                       if "masses have fused" not in r and "darkest colour" not in r]


@pytest.mark.parametrize("name", sorted(CONTROLS))
def test_a_convex_object_reads_the_same_under_either_subject(name) -> None:
    metrics = quality.score(_turned(CONTROLS[name]))
    assert metrics["row_structure"]["waists"] == 0, metrics["row_structure"]
    size = {"width": 32, "height": 32}
    assert (quality.tiered_readings(metrics, **size, subject="prop")
            == quality.tiered_readings(metrics, **size, subject="character"))


def test_omitting_the_subject_is_the_character_subject() -> None:
    c = corpus.build()
    grids = [(s.metrics, s.width, s.height) for s in list(c.good) + list(c.known_bad)]
    grids += [(quality.score(g, ramp), 32, 32) for _name, g, ramp in _constructed()]
    for metrics, width, height in grids:
        size = {"width": width, "height": height}
        assert (quality.tiered_readings(metrics, **size)
                == quality.tiered_readings(metrics, **size, subject="character"))
        for tier in (None, quality.DEFECT, quality.OBSERVATION):
            assert (quality.readings(metrics, **size, tier=tier)
                    == quality.readings(metrics, **size, tier=tier, subject="character"))
    per_frame = [(1, quality.score(_joined_figure(1))), (2, quality.score(_turned(PROPS["vase"])))]
    assert (quality.frame_findings(per_frame, width=32, height=32)
            == quality.frame_findings(per_frame, width=32, height=32, subject="character"))


def test_a_prop_still_reports_border_contact_and_off_ramp_pixels() -> None:
    ramp = [_LIT, _MID, _FOOT]
    clipped = quality.score(_turned(PROPS["vase"], top=0), ramp)
    assert clipped["edge_contact"] > 0
    lines = quality.readings(clipped, width=32, height=32, subject="prop")
    assert [r for r in lines if "canvas border" in r], lines

    stray = _turned(PROPS["vase"])
    stray[16][16] = "#ff0080"
    metrics = quality.score(stray, ramp)
    defects = quality.readings(metrics, width=32, height=32, tier=quality.DEFECT,
                               subject="prop")
    assert defects == [r for r in defects if "off the declared ramp" in r] and defects, defects


def test_the_frame_findings_gate_uses_the_subject() -> None:
    per_frame = [(1, quality.score(_turned(PROPS["lantern"])))]
    character = quality.frame_findings(per_frame, width=32, height=32)
    prop = quality.frame_findings(per_frame, width=32, height=32, subject="prop")
    assert [d for d in character["defects"] if "keyline" in d["reading"]]
    assert prop["defects"] == []


@pytest.mark.parametrize("subject", ["tile", "Character", "", "props"])
def test_an_unknown_subject_is_refused_by_name(subject) -> None:
    metrics = quality.score(_turned(PROPS["vase"]))
    for call in (
        lambda: quality.readings(metrics, width=32, height=32, subject=subject),
        lambda: quality.frame_findings([(1, metrics)], width=32, height=32, subject=subject),
        lambda: quality.check_subject(subject),
    ):
        with pytest.raises(ValidationFailed) as excinfo:
            call()
        assert '"character"' in str(excinfo.value) and '"prop"' in str(excinfo.value)


def test_the_isolated_pixel_reading_says_what_it_counts() -> None:
    """A diagonal dither is isolated by this count and is not dirt, and the reading has to
    say so: it named the count as noise, and the tool it pointed at leaves a dither alone."""
    g = [[T] * 32 for _ in range(32)]
    for y in range(8, 24):
        for x in range(8, 24):
            g[y][x] = "#787878" if (x + y) % 2 else "#c8c8c8"
    metrics = quality.score(g)
    assert metrics["isolated_pixels"] > quality.NOISY_ISOLATED
    hits = [r for r in quality.readings(metrics, width=32, height=32)
            if "neighbour of their own colour" in r]
    assert len(hits) == 1, hits
    assert "above, below or to either side" in hits[0]
    assert "diagonal dither counts here" in hits[0]
    assert "remove_stray_pixels leaves it alone" in hits[0]
    assert "eight directions" in hits[0]


def test_the_jagged_reading_does_not_promise_normalize_edge_runs_will_act() -> None:
    g = [[T] * 24 for _ in range(24)]
    for y in range(2, 22):
        out = y % 2
        for x in range(6 - out, 18 + out):
            g[y][x] = "#787878" if y > 4 else "#c8c8c8"
    metrics = quality.score(g)
    hits = [r for r in quality.readings(metrics, width=24, height=24)
            if "jagged corners" in r]
    assert len(hits) == 1, (metrics["jaggy_corners"], hits)
    assert "normalize_edge_runs" in hits[0] and "sawtooth" in hits[0]
    assert "declines consecutive one-pixel runs" in hits[0]
