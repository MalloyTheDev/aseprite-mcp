"""An outline whose weight follows the light, rather than a constant dark border.

`add_outline` painted one thickness all the way round. Nothing in nature has a border of
constant width, so a uniform outline is the single thing that most reliably makes a
sprite read as a die-cut sticker: the shape looks stamped out of card rather than lit.
Hand-drawn work in this style gathers the weight where the form turns away from the
light and lets it drop out entirely on the lit top faces, which is what a four-critic
review of this project's own gallery named as its first ranked change.

`outline_smart(mode="selective")` could already drop the outline on the lit side, but
only ever at one pixel, and only in colours taken from a ramp. The missing thing was
*weight*: two pixels where the form turns away, one or none where it faces the light.

The pure tests here hold the argument checking, which is where a caller finds out that
`lit_thickness` means nothing without a light direction. The editor-tier tests measure
the outline off the sprite, above and below the same disc, because the claim this
feature makes is geometric and the only honest way to check it is to count pixels.
"""
from __future__ import annotations

import itertools
import math

import pytest

from aseprite_mcp.core import lighting
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_OUTLINE_THICKNESS
from aseprite_mcp.tools import drawing, effects, inspect, sprite

# Upper left, which is the key light every showcase piece in this repo uses.
LIGHT = 135.0
FILL = "#b06a3a"
INK = "#120a18"

W = H = 32
CX = CY = 16
R = 8


def _column(name, x, y0, y1):
    """One column of the sprite as a list of lower-case "#rrggbbaa", top to bottom."""
    rows = inspect.get_pixels(name, x, y0, 1, y1 - y0 + 1)["pixels"]
    return [row[0].lower() for row in rows]


def _opaque(px):
    return px[7:9] != "00"


# ----------------------------------------------------------------- argument checking
@pytest.mark.pure
def test_a_lit_thickness_without_a_light_direction_is_refused():
    """Which edges are lit is not knowable without knowing where the light is, so the
    argument that only means something relative to a light says so rather than being
    quietly ignored."""
    with pytest.raises(ValidationFailed) as caught:
        effects.add_outline("x.aseprite", INK, thickness=2, lit_thickness=0)
    message = str(caught.value)
    assert "lit_thickness" in message and "light_angle" in message, message


@pytest.mark.pure
def test_a_light_angle_that_could_not_change_anything_is_refused():
    """At one pixel there is no weight to redistribute: both sides would come out the
    same, so the call would accept a light direction and draw exactly what it drew
    before. Silently doing nothing is the failure this project treats as worse than an
    error, so the refusal names both ways out."""
    with pytest.raises(ValidationFailed) as caught:
        effects.add_outline("x.aseprite", INK, thickness=1, light_angle=LIGHT)
    message = str(caught.value)
    assert "thickness" in message, message
    assert "lit_thickness=0" in message, message


@pytest.mark.pure
def test_a_lit_thickness_past_the_cap_is_refused():
    with pytest.raises(ValidationFailed, match=rf"maximum is {MAX_OUTLINE_THICKNESS}"):
        effects.add_outline("x.aseprite", INK, thickness=2, light_angle=LIGHT,
                            lit_thickness=MAX_OUTLINE_THICKNESS + 1)


@pytest.mark.pure
def test_a_negative_lit_thickness_is_refused():
    with pytest.raises(ValidationFailed):
        effects.add_outline("x.aseprite", INK, thickness=2, light_angle=LIGHT,
                            lit_thickness=-1)


# ------------------------------------------------------------------- the editor tier
@pytest.fixture
def disc(request):
    """A filled disc, which is the shape whose edge faces every direction at once."""
    name = f"outline_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_ellipse(name, CX, CY, R, R, FILL, filled=True)
    return name


def test_the_weight_gathers_on_the_side_facing_away_from_the_light(disc):
    """The headline claim, measured on the one column where the disc's edge faces
    straight up and straight down.

    Light from the upper left, two pixels of outline where the form turns away and none
    where it faces the light. Above the disc the silhouette has to stay bare, because
    that is the edge the eye reads as catching the light; below it the outline has to be
    exactly two deep and then stop.
    """
    effects.add_outline(disc, INK, thickness=2, light_angle=LIGHT, lit_thickness=0)
    column = _column(disc, CX, 4, 28)  # y = 4 .. 28, the disc occupies 8 .. 24

    above = [column[y - 4] for y in (5, 6, 7)]
    assert not any(_opaque(px) for px in above), (
        f"the lit top edge was outlined anyway: {above}. lit_thickness=0 means the "
        "outline drops out there, which is the whole point of the argument.")

    assert column[25 - 4][:7] == INK, f"no outline below the disc: {column[25 - 4]}"
    assert column[26 - 4][:7] == INK, f"the shadow side is only 1px: {column[26 - 4]}"
    assert not _opaque(column[27 - 4]), (
        f"the outline ran to {column[27 - 4]} at y=27, so thickness=2 laid down three "
        "pixels")


def test_the_counts_say_which_side_the_pixels_landed_on(disc):
    """Reported so a caller can prove the directional pass did something, rather than
    inferring it from a total that a uniform outline would also produce.

    `outline_lit` used to have to be exactly 0 here, and that assertion was a statement
    about the old hard switch rather than about the picture: with `lit_thickness=0` no
    pixel whose facing was lit by even a hair got an outline, which is what made the
    keyline come apart at the terminator. The taper keeps a thinning band across it, so a
    minority of the laid pixels now sit on the lit side of the terminator and the keyline
    is continuous. What the counts still have to do is distinguish the two sides, so that
    is what is asserted: most of the weight away from the light, and the two adding up to
    what was written.
    """
    result = effects.add_outline(disc, INK, thickness=2, light_angle=LIGHT,
                                 lit_thickness=0)
    assert result["outline_shadow"] > 4 * result["outline_lit"], (
        f"the weight is not gathering away from the light: {result}")
    assert result["outline_lit"] > 0, (
        "with lit_thickness=0 and a taper, the band through the terminator reaches a "
        f"little way onto the lit side; nothing did: {result}")
    assert result["outline_shadow"] + result["outline_lit"] == result["pixels_written"], (
        f"the two counts no longer account for every pixel written: {result}")


def test_without_a_light_the_outline_is_the_uniform_one_it_always_was(disc):
    """The regression that matters: every existing call, and five showcase generators,
    pass no light angle and must get the border they got before."""
    result = effects.add_outline(disc, INK, thickness=2)
    column = _column(disc, CX, 4, 28)
    for y in (6, 7, 25, 26):
        assert column[y - 4][:7] == INK, (
            f"y={y} is {column[y - 4]}, so the plain two-pixel outline changed shape")
    for y in (5, 27):
        assert not _opaque(column[y - 4]), f"y={y} is outlined, so it grew to 3px"
    assert "outline_lit" not in result, (
        f"the directional counts are reported for a call with no light: {result}")


def test_a_heavier_lit_side_gives_a_rim_light(disc):
    """`lit_thickness` above `thickness` inverts the convention on purpose: the weight
    goes to the lit edge instead, which is a rim light rather than a weighted outline.
    Allowed rather than refused, because it is a real thing pixel artists draw, and the
    pass count has to follow the larger of the two or the extra passes never run."""
    effects.add_outline(disc, "#ffe9b0", thickness=1, light_angle=LIGHT,
                        lit_thickness=3)
    column = _column(disc, CX, 4, 28)
    for y in (5, 6, 7):
        assert _opaque(column[y - 4]), f"the rim is thinner than 3px: y={y} is bare"
    assert not _opaque(column[4 - 4]), "the rim ran past 3px"
    assert _opaque(column[25 - 4]), "the shadow side lost its single pixel"
    assert not _opaque(column[26 - 4]), (
        "the shadow side is 2px, so thickness=1 was ignored once lit_thickness was "
        "larger")


def test_an_inside_outline_weights_the_same_way_round(disc):
    """The outward normal is the direction away from the shape, so for an inside
    outline it is the sum of the directions to the *transparent* neighbours rather than
    its negation. Easy to get backwards, and the symptom would be an outline that
    thickens on the lit side, so it is measured."""
    effects.add_outline(disc, INK, thickness=2, where="inside", light_angle=LIGHT,
                        lit_thickness=0)
    column = _column(disc, CX, 4, 28)
    assert column[24 - 4][:7] == INK, f"the bottom border was not recoloured: {column[24 - 4]}"
    assert column[23 - 4][:7] == INK, f"the inside outline is only 1px: {column[23 - 4]}"
    assert column[8 - 4][:7] == FILL, (
        f"the lit top border was recoloured to {column[8 - 4]}; with lit_thickness=0 it "
        "keeps the fill")


def test_an_inside_outline_is_as_thick_as_it_was_asked_for(disc, request):
    """A defect this work uncovered rather than introduced, and the reason the pass loop
    carries a record of what it has already laid down.

    An outside outline grows the shape, so each pass finds the next ring out by itself.
    An inside one does not: recolouring a border pixel leaves it exactly as opaque as it
    was, so every pass found the same border and recoloured it again. `thickness` had no
    effect beyond the first pixel, and a two-pixel inside outline came out one pixel
    wide.

    Asserted as a ratio rather than at fixed coordinates, because the exact rows an
    ellipse occupies are Aseprite's business and the claim here is only that the second
    pass went somewhere new.
    """
    thin = f"outline_thin_{request.node.name}.aseprite"
    sprite.create_sprite(thin, W, H, overwrite=True)
    drawing.draw_ellipse(thin, CX, CY, R, R, FILL, filled=True)
    one = effects.add_outline(thin, INK, thickness=1, where="inside")["pixels_written"]
    two = effects.add_outline(disc, INK, thickness=2, where="inside")["pixels_written"]
    assert two > one * 1.5, (
        f"a two-pixel inside outline wrote {two} pixels against {one} for one pixel, so "
        "the second pass re-marked the border instead of stepping inward")


def test_the_light_direction_actually_steers_which_side_is_heavy(disc):
    """The same call with the light underneath puts the weight on top, which is the
    check that the vector is being used rather than a hard-coded down-and-left bias."""
    effects.add_outline(disc, INK, thickness=2, light_angle=-45.0, lit_thickness=0)
    column = _column(disc, CX, 4, 28)
    assert _opaque(column[7 - 4]) and _opaque(column[6 - 4]), (
        "the light is from below, so the top edge is the shadow side and takes the "
        f"weight: {column[:6]}")
    assert not _opaque(column[25 - 4]), (
        f"the lit bottom edge was outlined anyway: {column[25 - 4]}")


# --------------------------------------------------------------------- the taper itself
# The weight table is arithmetic and gets pure tests; the band it produces is geometry and
# gets measured off a sprite. Both are needed: a correct table drawn through a facing
# measured at the wrong radius still comes apart, which is what the ring walk below counts.


@pytest.mark.pure
def test_a_two_to_zero_keyline_passes_through_one():
    """The headline. Three weights rather than two, and the middle one covering the widest
    band of facing, because that band is the terminator the keyline has to thin across."""
    weights = lighting.taper_weights(2, 0)
    assert sorted(set(weights)) == [0, 1, 2], weights
    assert weights[0] == 2 and weights[-1] == 0, weights
    counted = {value: weights.count(value) for value in set(weights)}
    assert counted[1] > counted[0] and counted[1] > counted[2], counted


@pytest.mark.pure
def test_the_table_only_ever_runs_one_way():
    """A weight that rose again toward the light would be a second keyline on the lit side.
    Asserted across every pairing a caller can ask for rather than on one example."""
    for shadow in range(0, 5):
        for lit in range(0, 5):
            weights = lighting.taper_weights(shadow, lit)
            assert weights[0] == shadow and weights[-1] == lit, (shadow, lit, weights)
            step = 1 if lit >= shadow else -1
            for before, after in itertools.pairwise(weights):
                assert (after - before) * step >= 0, (
                    f"{shadow} to {lit} doubles back: {weights}")


@pytest.mark.pure
def test_two_widths_one_apart_still_switch_where_they_always_switched():
    """The compatibility property, and the reason this could become the default rather than
    an argument. With only two integers available the changeover sits at the midpoint of
    the facing range, which is where `dot > 0` put it, so every existing call with
    `thickness=2, lit_thickness=1` draws exactly what it drew before."""
    weights = lighting.taper_weights(2, 1)
    assert sorted(set(weights)) == [1, 2], weights
    middle = len(weights) // 2
    assert weights[middle] == 2, (
        "an edge exactly square to the light has to count as the shadow side, which is "
        f"what the comparison it replaced did: {weights[middle - 1:middle + 2]}")
    assert weights[middle + 1] == 1, weights[middle:middle + 2]


@pytest.mark.pure
def test_a_taper_needs_a_middle_and_cannot_be_negative():
    with pytest.raises(ValueError, match="at least 3 buckets"):
        lighting.taper_weights(2, 0, buckets=2)
    with pytest.raises(ValueError, match="cannot be negative"):
        lighting.taper_weights(2, -1)


def test_the_thickness_changes_gradually_around_a_disc(disc):
    """Measured off the sprite rather than off the table: every weight between the two
    asked for has to actually land on the silhouette's own boundary ring.

    On a circle each of the three weights of a 2-to-0 taper covers 120 degrees of arc, so
    they should come out in roughly equal thirds. A per-pixel switch would leave the middle
    entry empty, and the facing measured at too small a radius leaves it nearly empty: at a
    radius of one the same disc split 28 / 12 / 56 instead.
    """
    result = effects.add_outline(disc, INK, thickness=2, light_angle=LIGHT,
                                 lit_thickness=0)
    weights = result["outline_weights"]
    assert len(weights) == 3, weights
    assert all(count > 0 for count in weights), (
        f"a weight between the two asked for never appeared, so this switched rather than "
        f"tapered: {weights}")
    ring = sum(weights)
    assert weights[1] > 0.2 * ring, (
        f"the band of single-pixel keyline is only {weights[1]} of {ring} edge pixels, "
        "which is a seam rather than a taper")


def test_a_longer_drop_uses_every_weight_on_the_way_down(disc):
    """Three to nothing has four weights, and all four have to appear. This is the case the
    old switch could not express at all: it had two values whatever the arguments."""
    result = effects.add_outline(disc, INK, thickness=3, light_angle=LIGHT,
                                 lit_thickness=0)
    weights = result["outline_weights"]
    assert len(weights) == 4, weights
    assert all(count > 0 for count in weights), (
        f"a 3-to-0 keyline skipped a weight on the way down: {weights}")


def test_the_keyline_stays_in_one_piece_on_a_lumpy_silhouette(request):
    """The defect this item exists for, counted.

    A taper that works lays one continuous arc of outline and leaves one continuous arc
    bare, so walking the shape's boundary ring in angular order crosses between the two
    exactly twice. The per-pixel test crossed 30 times on this shape, which is fifteen
    separate scraps of keyline: the figure looked damaged, which is why `lit_thickness=0`
    had to be reverted to 1 on this project's golem even though the measurement preferred
    it.

    A handful of crossings is allowed rather than exactly two, because the ring of a bumpy
    silhouette is not a circle and the angular sort around its centroid is an
    approximation of walking it. Fifteen pieces and one piece are not close enough for
    that to matter.
    """
    name = f"outline_lumpy_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_ellipse(name, CX, CY, 9, 9, FILL, filled=True)
    bumps = [(16, 6), (11, 8), (21, 8), (6, 15), (26, 17), (12, 24), (21, 24), (16, 26),
             (9, 11), (24, 22), (8, 20), (24, 11)]
    drawing.draw_pixels(name, [{"x": x, "y": y} for x, y in bumps], FILL)

    rows = inspect.get_pixels(name, 0, 0, W, H)["pixels"]
    solid = {(x, y) for y in range(H) for x in range(W) if _opaque(rows[y][x].lower())}
    cx = sum(x for x, _ in solid) / len(solid)
    cy = sum(y for _, y in solid) / len(solid)
    ring = {
        (x + dx, y + dy)
        for x, y in solid
        for dx in (-1, 0, 1) for dy in (-1, 0, 1)
        if (x + dx, y + dy) not in solid and 0 <= x + dx < W and 0 <= y + dy < H
    }
    walk = sorted(ring, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

    effects.add_outline(name, INK, thickness=2, light_angle=LIGHT, lit_thickness=0)
    after = inspect.get_pixels(name, 0, 0, W, H)["pixels"]
    inked = [after[y][x].lower()[:7] == INK for x, y in walk]
    crossings = sum(1 for i, state in enumerate(inked) if state != inked[i - 1])
    assert 0 < crossings <= 6, (
        f"the keyline crosses between outlined and bare {crossings} times around the "
        f"ring, so it is in about {max(1, crossings // 2)} pieces rather than one")

    # And no scrap left on its own, which is what a reader sees as dirt rather than as a
    # thinning keyline.
    ink = {(x, y) for y in range(H) for x in range(W) if after[y][x].lower()[:7] == INK}
    lone = [
        (x, y) for x, y in ink
        if not any((x + dx, y + dy) in ink
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0))
    ]
    assert lone == [], f"{len(lone)} outline pixels are stranded alone: {lone[:6]}"


def test_a_uniform_outline_reports_no_weights(disc):
    """The counts are a statement about a directional pass. A call with no light has no
    facing to report, and a zero-filled table would read as a taper that came out flat."""
    result = effects.add_outline(disc, INK, thickness=2)
    assert "outline_weights" not in result, result


# ------------------------------------------- the negative space an outline destroys
@pytest.fixture
def two_masses(request):
    """Two blocks with a gap between them, which is what a silhouette's air is made of."""
    def build(gap: int) -> str:
        name = f"gap_{gap}_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
        sprite.create_sprite(name, 32, 16, overwrite=True)
        cells = [{"x": x, "y": y} for y in range(4, 12) for x in range(4, 9)]
        cells += [{"x": x, "y": y} for y in range(4, 12) for x in range(9 + gap, 14 + gap)]
        drawing.draw_pixels(name, cells, FILL)
        return name
    return build


@pytest.mark.parametrize("gap,thickness,survives", [
    (3, 1, True),    # 3 - 2*1 = 1px of background left
    (3, 2, False),   # 3 - 2*2 is negative: the masses weld
    (4, 2, False),   # exactly eaten
    (6, 2, True),    # 2px left
    (8, 2, True),
])
def test_an_outline_reports_the_gaps_it_closes(two_masses, gap, thickness, survives):
    """An outline grows inward from both sides of every gap, so a gap of twice the
    thickness or less closes completely and two masses become one.

    Nothing else in the result can see that happen. The drawing had the air, the finished
    sprite does not, and every counter still reports success: `pixels_written` is correct,
    the silhouette is intact, and the figure has quietly lost the thing that made it
    readable. Measured on this project's own golem, a two-pixel outline closed 31 of the
    86 gaps in the drawing and cost 8 rows their negative space, welding the legs and the
    feet into a single plinth.

    The expectation here is arithmetic rather than a fitted threshold, which is why it is
    parameterised across the boundary: a gap survives exactly when it is wider than twice
    the outline.
    """
    name = two_masses(gap)
    result = effects.add_outline(name, INK, thickness=thickness)
    closed = result.get("gaps_closed", 0)
    if survives:
        assert closed == 0, (
            f"a {gap}px gap under a {thickness}px outline should keep "
            f"{gap - 2 * thickness}px of background, but {closed} rows welded")
    else:
        assert closed == 8, (
            f"a {gap}px gap under a {thickness}px outline cannot survive, but only "
            f"{closed} of the 8 rows were reported as welded")
    back = inspect.get_pixels(name, 0, 0, 32, 16)["pixels"]
    middle = [px for px in back[8] if px[7:9] == "00"][:1]
    assert bool(middle) == survives or closed > 0, (
        "the reported count disagrees with the picture on row 8")


def test_a_gap_that_survives_is_not_reported(two_masses):
    """Absent rather than zero, like every other count here, so a `gaps_closed` key in a
    result always means something was actually lost."""
    result = effects.add_outline(two_masses(8), INK, thickness=1)
    assert "gaps_closed" not in result, result
