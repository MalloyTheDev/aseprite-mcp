"""Occlusion where two masses of the same material meet, which colour cannot find.

`contact_shadow` finds its occluder with `occluder_color`, so it cannot darken the seam
between an arm and a torso cut from the same stone. That is the common case in a figure,
and the evidence it was missing is in this project's own golem: an armpit measured +131 in
luminance where an artist darkens the contact, and the generator grew a loop that read
seam pixels back in Python and slammed them two steps down. A workaround in a build script
is evidence of a missing capability, not a design.

The claim here is a luminance step across a seam, so that is what the editor-tier tests
measure: the same row of pixels before and after, in luminance, across a seam whose two
sides start out identical. The pure tests hold the geometry, which is where the asymmetry
lives: the mass in front darkens the one behind and never itself, because darkening both
sides of a seam is how you draw brickwork.
"""
from __future__ import annotations

import colorsys

import pytest

from aseprite_mcp.core import occlusion, quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_COLOR_LIST_LENGTH
from aseprite_mcp.tools import drawing, inspect, palette, shading, sprite

W = H = 24
# The arm's own columns, the torso's, and the row they overlap on.
ARM = (3, 7)
TORSO = (6, 17)
SEAM_ROW = 11

# An eight-step stone ramp of the kind the golem is painted on, built rather than written
# out so the chroma is the one `generate_ramp` actually produces.
RAMP = palette.generate_ramp("#6b6477", steps=8, chroma=0.23)["colors"]
MID = RAMP[5]


def _map_rows():
    """An arm laid over a torso, both the same material: the case colour cannot separate."""
    return [
        "".join(
            "a" if (ARM[0] <= x <= ARM[1] and 8 <= y <= 15)
            else ("b" if (TORSO[0] <= x <= TORSO[1] and 2 <= y <= 21) else ".")
            for x in range(W)
        )
        for y in range(H)
    ]


def _luminance(pixel: str) -> float | None:
    if pixel[7:9] == "00":
        return None
    r, g, b = (int(pixel[i:i + 2], 16) for i in (1, 3, 5))
    return round(colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[1] * 255, 1)


def _row(name, y, xs):
    grid = inspect.get_pixels(name, 0, 0, W, H)["pixels"]
    return [_luminance(grid[y][x].lower()) for x in xs]


# --------------------------------------------------------------------------- geometry
@pytest.mark.pure
def test_only_the_mass_behind_is_darkened():
    """The asymmetry, which is the whole difference between occlusion and a drawn line."""
    rows = _map_rows()
    plan = occlusion.plan(rows, {"a": 1, "b": 0}, radius=2, depth=2)
    for pixel in plan["darken"]:
        assert rows[pixel["y"]][pixel["x"]] == "b", (
            f"{pixel} is on mass {rows[pixel['y']][pixel['x']]!r}, which is not the one "
            "behind")


@pytest.mark.pure
def test_raising_the_other_mass_reverses_which_side_darkens():
    """The same map with the z swapped has to darken the other side, or the legend's z is
    decoration and the tool is really darkening whichever symbol it met first."""
    rows = _map_rows()
    forward = occlusion.plan(rows, {"a": 1, "b": 0}, radius=2, depth=2)
    backward = occlusion.plan(rows, {"a": 0, "b": 1}, radius=2, depth=2)
    assert {rows[p["y"]][p["x"]] for p in forward["darken"]} == {"b"}
    assert {rows[p["y"]][p["x"]] for p in backward["darken"]} == {"a"}


@pytest.mark.pure
def test_the_darkening_falls_off_with_distance_from_the_seam():
    """A hard line of uniform darkness reads as drawn brickwork. Asserted as a property of
    every pixel rather than on one row: nothing further from the seam may go deeper than
    something closer to it."""
    rows = _map_rows()
    plan = occlusion.plan(rows, {"a": 1, "b": 0}, radius=3, depth=3)
    arm = {(x, y) for y in range(H) for x in range(W) if rows[y][x] == "a"}
    for pixel in plan["darken"]:
        nearest = min(max(abs(pixel["x"] - ax), abs(pixel["y"] - ay)) for ax, ay in arm)
        assert pixel["steps"] >= 1
        assert pixel["steps"] <= 3 - (nearest - 1) + 1, pixel
    assert len(plan["by_steps"]) > 1, (
        f"every pixel moved the same distance, so this is a band and not a falloff: "
        f"{plan['by_steps']}")


@pytest.mark.pure
def test_the_falloff_curve_is_the_one_contact_shadow_uses():
    """Pinned as an equality rather than described, because two tools that disagree about
    what a contact falloff is produce two different seams on one figure."""
    rows = ["aab", "aab", "aab"]
    plan = occlusion.plan(rows, {"a": 1, "b": 0}, radius=2, depth=2)
    # x=2 is one away from mass "a" at full depth; nothing sits two away on this map.
    assert {p["steps"] for p in plan["darken"]} == {2}, plan["darken"]
    wide = occlusion.plan(["aabbb"] * 3, {"a": 1, "b": 0}, radius=2, depth=2)
    by_x = {p["x"]: p["steps"] for p in wide["darken"] if p["y"] == 1}
    assert by_x == {2: 2, 3: 1}, by_x


# --------------------------------------------------------------------------- refusals
@pytest.mark.pure
def test_one_mass_is_refused_and_points_at_the_other_tool():
    with pytest.raises(ValidationFailed) as caught:
        occlusion.plan(["bbb", "bbb"], {"b": 0}, radius=2, depth=1)
    assert "contact_shadow" in str(caught.value), str(caught.value)


@pytest.mark.pure
def test_masses_all_at_one_z_are_refused_because_none_is_in_front():
    with pytest.raises(ValidationFailed, match="none of them is in front of another"):
        occlusion.plan(_map_rows(), {"a": 0, "b": 0}, radius=2, depth=1)


@pytest.mark.pure
def test_masses_that_do_not_touch_are_refused_with_both_counts():
    with pytest.raises(ValidationFailed) as caught:
        occlusion.plan(["aa...", "aa...", ".....", "...bb"], {"a": 1, "b": 0},
                       radius=1, depth=1)
    message = str(caught.value)
    assert "raise radius" in message, message
    assert "z 1" in message and "z 0" in message, message


@pytest.mark.pure
@pytest.mark.parametrize("legend,pattern", [
    ({"a": "front", "b": 0}, "which is not a z"),
    ({"a": True, "b": 0}, "which is not a z"),
    ({"ab": 1, "b": 0}, "not a single character"),
    ({".": 1, "b": 0}, "already means"),
])
def test_a_legend_that_does_not_name_masses_and_depths_is_refused(legend, pattern):
    with pytest.raises(ValidationFailed, match=pattern):
        occlusion.plan(_map_rows(), legend, radius=2, depth=1)


@pytest.mark.pure
def test_a_character_the_legend_does_not_define_is_refused_not_skipped():
    """The same rule `draw_pixel_map` applies, for the same reason: a typo in a grid would
    otherwise leave a seam unshaded and report success."""
    with pytest.raises(ValidationFailed, match="which the legend does not define"):
        occlusion.plan(["aabc", "aabc"], {"a": 1, "b": 0}, radius=1, depth=1)


@pytest.mark.pure
def test_the_grid_refusals_are_the_ones_the_map_notation_already_had():
    """Both readers of this notation go through `pixelmap.read_rows`, so a ragged map earns
    the message a hand-written grid has always earned rather than a second one that drifts
    away from it."""
    with pytest.raises(ValidationFailed, match="Every row of a map has to be the same"):
        occlusion.plan(["aaa", "aa"], {"a": 1, "b": 0}, radius=1, depth=1)
    with pytest.raises(ValidationFailed, match="non-empty list of strings"):
        occlusion.plan([], {"a": 1, "b": 0}, radius=1, depth=1)


@pytest.mark.pure
@pytest.mark.parametrize("radius,depth,pattern", [
    (0, 1, r"radius is 0"),
    (2, 0, r"depth is 0"),
])
def test_a_reach_or_a_depth_of_nothing_is_refused(radius, depth, pattern):
    with pytest.raises(ValidationFailed, match=pattern):
        occlusion.plan(_map_rows(), {"a": 1, "b": 0}, radius=radius, depth=depth)


@pytest.mark.pure
def test_a_flat_band_is_reported_as_one_rather_than_passed_off_as_a_falloff():
    """`depth=1` over `radius=2` rounds both distances to the same step, so it draws
    exactly the 2px line it was supposed to replace. Quiet arithmetic, surfaced."""
    plan = occlusion.plan(_map_rows(), {"a": 1, "b": 0}, radius=2, depth=1)
    note = occlusion.flat_band_note(plan["by_steps"], radius=2, depth=1)
    assert note and "flat band" in note and "raise depth" in note, note

    one = occlusion.plan(_map_rows(), {"a": 1, "b": 0}, radius=1, depth=1)
    assert occlusion.flat_band_note(one["by_steps"], radius=1, depth=1) is None, (
        "a one-pixel contact line is a legitimate thing to ask for and must not be "
        "warned about")


@pytest.mark.pure
def test_a_depth_the_ramp_cannot_express_is_refused_by_the_tool():
    """Stepping further than the ramp is long puts every seam pixel on the darkest entry
    whatever it was, which is a drawn black line rather than occlusion."""
    with pytest.raises(ValidationFailed, match=r"most this ramp can express is 3"):
        shading.seam_occlusion("x.aseprite", _map_rows(), {"a": 1, "b": 0},
                               RAMP[:4], radius=2, depth=4)


@pytest.mark.pure
def test_a_one_colour_ramp_is_refused():
    with pytest.raises(ValidationFailed, match="nowhere to step"):
        shading.seam_occlusion("x.aseprite", _map_rows(), {"a": 1, "b": 0}, [MID])


@pytest.mark.pure
def test_an_over_cap_ramp_is_refused_before_anything_else():
    with pytest.raises(ValidationFailed, match=rf"maximum is {MAX_COLOR_LIST_LENGTH}"):
        shading.seam_occlusion("x.aseprite", _map_rows(), {"a": 1, "b": 0},
                               [MID] * (MAX_COLOR_LIST_LENGTH + 1))


# -------------------------------------------------------------------- the editor tier
@pytest.fixture
def figure(request):
    """An arm over a torso, both painted the same mid-ramp stone."""
    name = f"seam_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_pixel_map(name, _map_rows(), {"a": MID, "b": MID})
    return name


def test_the_luminance_step_across_the_seam_goes_from_nothing_to_something(figure):
    """The headline measurement, on the row where the arm crosses the torso.

    Before the pass both sides of the seam are the same colour, so the step across it is
    exactly zero and there is no contact: that is the +131 armpit on the golem, which no
    tool here could see. After it, the torso side has dropped and the arm side has not.
    """
    columns = list(range(5, 14))
    before = _row(figure, SEAM_ROW, columns)
    assert len(set(before)) == 1, (
        f"the two sides of the seam were not identical to start with: {before}")

    result = shading.seam_occlusion(figure, _map_rows(), {"a": 1, "b": 0}, RAMP,
                                    radius=2, depth=2)
    after = _row(figure, SEAM_ROW, columns)

    flat, lit = before[0], after[0]
    assert lit == flat, f"the far side of the torso changed: {after}"
    step = flat - after[columns.index(ARM[1] + 1)]
    assert step > 20, (
        f"the seam is still nearly flat: {before} became {after}, a step of {step}")
    assert result["darkened_pixels"] == result["seam_pixels"], result


def test_the_darkening_grades_away_from_the_seam_on_the_sprite(figure):
    """Not just darker, but darker in the right order. A hard line at full depth is the
    masonry the workaround produced; the pixel one further out has to sit between the seam
    and the untouched surface."""
    shading.seam_occlusion(figure, _map_rows(), {"a": 1, "b": 0}, RAMP, radius=2, depth=2)
    contact, next_out, untouched = _row(figure, SEAM_ROW, [8, 9, 12])
    assert contact < next_out < untouched, (
        f"the falloff is not graded: contact {contact}, next {next_out}, surface "
        f"{untouched}")


def test_the_mass_in_front_is_not_touched(figure):
    """Occlusion is asymmetric on the sprite as well as in the plan: the arm keeps its
    tone, which is what makes it read as being in front."""
    before = _row(figure, SEAM_ROW, list(range(ARM[0], ARM[1] + 1)))
    shading.seam_occlusion(figure, _map_rows(), {"a": 1, "b": 0}, RAMP, radius=2, depth=2)
    assert _row(figure, SEAM_ROW, list(range(ARM[0], ARM[1] + 1))) == before


def test_every_darkened_pixel_is_still_on_the_declared_ramp(figure):
    """What separates this from a brightness filter. Measured with the project's own
    conformance metric rather than asserted."""
    shading.seam_occlusion(figure, _map_rows(), {"a": 1, "b": 0}, RAMP, radius=2, depth=2)
    grid = inspect.get_pixels(figure, 0, 0, W, H)["pixels"]
    assert quality.palette_conformance(grid, RAMP) == 1.0, (
        "the pass put pixels off the ramp it was given")


def test_a_map_that_is_not_where_the_art_is_refuses_and_says_so(figure):
    """The plan is geometry and the sprite is paint. Offset far enough and every seam pixel
    lands on empty canvas, which is a mistake in `x`/`y` and has to be named as one rather
    than reported as a pass that darkened nothing."""
    with pytest.raises(Exception) as caught:
        shading.seam_occlusion(figure, _map_rows(), {"a": 1, "b": 0}, RAMP,
                               radius=2, depth=2, x=60, y=60)
    message = str(caught.value)
    assert "darkened nothing" in message, message
    assert "off the canvas" in message, message


def test_a_seam_on_a_different_material_is_left_alone(figure):
    """`tolerance` is what stops a seam dragging another material onto this ramp. With a
    ramp the art is nowhere near, every pixel is off-ramp and the pass refuses instead of
    recolouring the figure to match the ramp it was handed."""
    with pytest.raises(Exception) as caught:
        shading.seam_occlusion(figure, _map_rows(), {"a": 1, "b": 0},
                               ["#004400", "#008800", "#00cc00"], radius=2, depth=2,
                               tolerance=4.0)
    message = str(caught.value)
    assert "from any ramp entry" in message, message
    assert _row(figure, SEAM_ROW, [8, 9])[0] is not None, "the figure was damaged anyway"


def test_an_indexed_palette_that_cannot_hold_the_ramp_is_reported(request):
    """A `ramp` argument on an indexed sprite is a request the palette may not be able to
    meet: two steps that resolve to one entry make a darkening that changes nothing and
    still reports the pixels it wrote, and conformance cannot see it because the colour
    landed on is still on the ramp. Going through `run_ramp_lua` is what reports it, and
    `test_imports.py` pins that structurally; this is the behaviour behind the pin."""
    name = f"seam_indexed_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, color_mode="indexed", overwrite=True)
    # A palette one entry short of the ramp, so two steps have to collapse together.
    palette.set_palette(name, [*RAMP[1:], "#ff8a2a"])
    drawing.draw_pixel_map(name, _map_rows(), {"a": MID, "b": MID})

    result = shading.seam_occlusion(name, _map_rows(), {"a": 1, "b": 0}, RAMP,
                                    radius=2, depth=2)
    assert result["darkened_pixels"] > 0, result
    assert any("indexed" in note for note in result.get("warnings", [])), (
        f"the palette cannot hold the declared ramp and nothing said so: {result}")
