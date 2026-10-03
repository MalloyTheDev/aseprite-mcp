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

import pytest

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
    inferring it from a total that a uniform outline would also produce."""
    result = effects.add_outline(disc, INK, thickness=2, light_angle=LIGHT,
                                 lit_thickness=0)
    assert result["outline_lit"] == 0, result
    assert result["outline_shadow"] > 0, result
    assert result["outline_shadow"] == result["pixels_written"], result


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
