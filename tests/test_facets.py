"""Shading a form made of flat planes, which the toolkit could not do.

`shade_region_by_light` infers a normal from how far a pixel sits from the silhouette's
edge, so it always rounds a form over. On a sphere that is correct. On a block it produces
a pillow, and every hard-surface subject in this project's gallery came out inflated for
that reason: a four-agent review called the results "grey plastic" and "a balloon" without
either reviewer knowing why. Measured side by side on one silhouette and one ramp, the
distance-field pass smears a diagonal gradient across faces that should be flat, and the
facet pass gives three flat planes meeting at hard edges.

The pure tests hold the lighting model, and the one that matters most is the fill light:
without it every plane facing away from the key clamps to the same ambient value and the
whole shadow side comes out one colour, which is the exact defect found on the helm in this
repository's item sheet. The editor-tier tests hold the defining property, that every pixel
of one facet is the same colour, because flatness is the whole point and a gradient cannot
imitate it.
"""
from __future__ import annotations

import pytest

from aseprite_mcp.core import facets
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import (
    drawing,
    inspect,
    palette,
    selection,
    shading,
    sprite,
)

KEY = 130.0
RAMP = palette.generate_ramp(
    base_color="#7a6a62", steps=8, chroma=0.28, shadow_hue="#2e2452",
    light_hue="#ffe2a8", sat_curve="peak", saturation_shift=35.0,
    easing="perceptual", light_range=0.74)["colors"]

# A plinth: a lit chamfer along the top edge, a top plane, a left plane and a front plane.
BLOCK = (["....tttttttttttt....",
          "..tttttttttttttttt..",
          "tttttttttttttttttttt",
          "bbbbbbbbbbbbbbbbbbbb"]
         + ["llllllllffffffffffff"] * 12)
FACES = {"t": 90, "b": [130, 0.2], "l": 180, "f": "front"}


# ------------------------------------------------------------------ the lighting model
@pytest.mark.pure
def test_the_three_ways_to_say_which_way_a_plane_faces():
    """An angle, the word "front", and an angle with a tilt toward the viewer."""
    assert facets.normal("front") == (0.0, 0.0, 1.0)
    up = facets.normal(90)
    assert up[1] < 0 and up[0] == pytest.approx(0.0, abs=1e-9), up
    right = facets.normal(0)
    assert right[0] > 0 and right[1] == pytest.approx(0.0, abs=1e-9), right
    # A tilt toward the viewer turns the normal out of the screen plane.
    shallow, steep = facets.normal([135, 1.6]), facets.normal([135, 0.1])
    assert shallow[2] > steep[2], (shallow, steep)


@pytest.mark.pure
def test_a_plane_facing_the_light_is_lighter_than_one_facing_away():
    toward = facets.step_for(facets.normal(KEY), steps=8, light_angle=KEY)
    away = facets.step_for(facets.normal(KEY + 180), steps=8, light_angle=KEY)
    assert toward > away, (toward, away)
    assert toward == 7, toward


@pytest.mark.pure
def test_the_fill_light_is_what_stops_the_shadow_side_being_one_colour():
    """The finding this argument exists for.

    Clamping Lambert at zero puts every plane facing away from the key on the same ambient
    value, so a form's whole shadow side comes out flat. That is the defect measured on the
    helm in this project's own item sheet, where one colour covered 202 pixels of a shaded
    surface with no second value anywhere in it.
    """
    behind = [0, -45, -90]  # right, down-right, down, with the key up and to the left
    flat = {facets.step_for(facets.normal(a), steps=8, light_angle=KEY, fill_strength=0.0)
            for a in behind}
    assert len(flat) == 1, f"the fixture is wrong: these should collapse without fill {flat}"

    lifted = {facets.step_for(facets.normal(a), steps=8, light_angle=KEY,
                              fill_strength=0.35) for a in behind}
    assert len(lifted) > 1, (
        f"the fill did not separate the planes facing away from the key: {lifted}")


@pytest.mark.pure
def test_too_much_fill_flattens_the_form_from_the_other_side():
    """Documented as a range rather than left to be discovered: past about 0.6 the bounce
    lifts shadow planes into the lit side's values."""
    key_lit = facets.normal(KEY)
    away = facets.normal(KEY + 180)
    def gap(fill_strength):
        lit = facets.step_for(key_lit, steps=8, light_angle=KEY,
                              fill_strength=fill_strength)
        dark = facets.step_for(away, steps=8, light_angle=KEY,
                               fill_strength=fill_strength)
        return lit - dark

    assert gap(0.35) > gap(0.9), (gap(0.35), gap(0.9))


@pytest.mark.pure
def test_a_pass_where_every_facet_lands_on_one_step_is_refused():
    """A shading tool that paints a flat fill has not shaded anything, and reporting that
    as a success is the failure this project treats as worse than an error."""
    with pytest.raises(ValidationFailed, match="would paint one flat colour"):
        facets.plan({"a": "front", "b": "front"}, steps=8)


@pytest.mark.pure
def test_a_ramp_too_short_to_hold_a_form_is_refused():
    with pytest.raises(ValidationFailed, match="at least 3 ramp entries"):
        facets.plan({"a": 90, "b": 0}, steps=2)


@pytest.mark.pure
@pytest.mark.parametrize("spec", ["sideways", [1, 2, 3], None, True, float("inf"), {}])
def test_a_legend_entry_that_is_not_a_direction_is_refused(spec):
    with pytest.raises(ValidationFailed):
        facets.plan({"a": spec, "b": 90}, steps=8)


@pytest.mark.pure
def test_a_legend_key_has_to_be_one_character():
    with pytest.raises(ValidationFailed, match="not a single character"):
        facets.plan({"top": 90, "f": "front"}, steps=8)


@pytest.mark.pure
@pytest.mark.parametrize("bad", [-0.1, 1.4])
def test_a_fill_strength_outside_zero_to_one_is_refused(bad):
    with pytest.raises(ValidationFailed, match="share of the key light"):
        facets.plan({"a": 90, "b": 0}, steps=8, fill_strength=bad)


# ------------------------------------------------------------------- the editor tier
@pytest.fixture
def canvas(request):
    name = f"facet_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, 24, 24, overwrite=True)
    return name


def test_every_pixel_of_a_facet_is_the_same_colour(canvas):
    """The defining property, and the thing a gradient cannot imitate.

    A plane's tone does not depend on where its pixels are, only on which way it faces.
    That flatness is what reads as cut rather than inflated, so it is asserted exactly
    rather than approximately: one colour per facet, no exceptions.
    """
    out = shading.shade_facets(canvas, BLOCK, FACES, RAMP, light_angle=KEY, x=2, y=3)
    assert "warnings" not in out, out
    assert len(set(out["facet_steps"].values())) == 4, out["facet_steps"]

    back = inspect.get_pixels(canvas, 0, 0, 24, 24)["pixels"]
    seen: dict[str, set[str]] = {}
    for cy, row in enumerate(BLOCK):
        for cx, symbol in enumerate(row):
            if symbol == ".":
                continue
            seen.setdefault(symbol, set()).add(back[3 + cy][2 + cx][:7].lower())
    for symbol, colours in sorted(seen.items()):
        assert len(colours) == 1, (
            f"facet {symbol!r} came out in {len(colours)} colours {sorted(colours)}; a "
            "plane is one value or it is not a plane")
    # And the four planes really are four different values.
    assert len({next(iter(c)) for c in seen.values()}) == 4, seen


def test_the_lit_plane_is_lighter_than_the_one_facing_away(canvas):
    """Which way round the light goes, measured off the sprite rather than asserted."""
    shading.shade_facets(canvas, BLOCK, FACES, RAMP, light_angle=KEY, x=2, y=3)
    back = inspect.get_pixels(canvas, 0, 0, 24, 24)["pixels"]
    top = back[3 + 2][2 + 10][:7].lower()      # the top plane
    front = back[3 + 8][2 + 14][:7].lower()    # the front plane
    lower = [c.lower() for c in RAMP]
    assert lower.index(top) > lower.index(front), (
        f"the top plane {top} is not lighter than the front plane {front} under a light "
        "from above")


def test_two_planes_handed_the_same_tone_are_reported(canvas):
    """A facet the caller authored and cannot see is worse than one it did not ask for:
    the picture gives no sign that a plane is missing."""
    out = shading.shade_facets(
        canvas, BLOCK, {"t": 90, "b": [115, 1.1], "l": 180, "f": "front"},
        RAMP, light_angle=KEY, x=2, y=3)
    assert "warnings" in out, out
    assert any("resolved to ramp step" in w for w in out["warnings"]), out["warnings"]


def test_a_facet_pass_honours_an_active_selection(canvas):
    """It delegates to the same write path as `draw_pixel_map`, so it inherits the mask
    and the clipping counters instead of growing a second set that would forget them."""
    selection.select_region(canvas, "rect", x=0, y=0, width=10, height=24)
    out = shading.shade_facets(canvas, BLOCK, FACES, RAMP, light_angle=KEY, x=2, y=3)
    assert out["selection_applied"] is True, out
    assert out["pixels_outside_selection"] > 0, out
    right = inspect.get_pixels(canvas, 14, 0, 10, 24)["pixels"]
    painted = [px for row in right for px in row if px[7:9] != "00"]
    assert not painted, f"the mask was ignored: {painted[:4]}"


def test_a_flat_plane_shaded_the_rounded_way_is_not_flat(canvas, request):
    """The comparison that justifies the tool existing.

    The same silhouette, the same ramp and the same light, shaded by distance to the
    silhouette's edge, does not produce flat planes: it produces a gradient across them.
    If this ever stops being true, `shade_facets` is redundant and should go.
    """
    rounded = f"rounded_{request.node.name}.aseprite"
    sprite.create_sprite(rounded, 24, 24, overwrite=True)
    drawing.draw_pixel_map(rounded, BLOCK, dict.fromkeys("tblf", RAMP[4]), x=2, y=3)
    shading.shade_region_by_light(rounded, RAMP, base_color=RAMP[4], light_angle=KEY)

    back = inspect.get_pixels(rounded, 0, 0, 24, 24)["pixels"]
    front_face = {back[3 + cy][2 + cx][:7].lower()
                  for cy, row in enumerate(BLOCK)
                  for cx, symbol in enumerate(row) if symbol == "f"}
    assert len(front_face) > 1, (
        "the distance-field pass produced a flat front plane, which would make "
        "shade_facets unnecessary")
