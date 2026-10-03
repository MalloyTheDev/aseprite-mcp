"""Light from a source inside a silhouette, which `glow` cannot deliver by construction.

`glow` builds its halo on a layer below the artwork and its own docstring says so: "a body
blocks the halo of a gem inside it". The consequence was measured on this project's golem,
where `glow` contributed zero pixels to the export and the committed PNG held nine colours,
eight stone steps and one core colour, with nothing of the halo in it at all. The first test
below asserts that defect rather than describing it, because a new tool whose reason for
existing is not in the suite is a tool somebody will delete.

What this claims instead is that light from an interior source warms the surface it sits in,
so the measurements are: the changed pixels are inside the silhouette, the drawn pixel count
does not move (nothing is added, the surface is repainted), conformance to the declared ramp
stays at 1.0, the lift falls off with distance, and two tones at the same distance move
together so the surface keeps its own form.
"""
from __future__ import annotations

import pytest

from aseprite_mcp.core import lighting, quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_COLOR_LIST_LENGTH, MAX_GLOW_RADIUS
from aseprite_mcp.tools import drawing, effects, inspect, palette, shading, sprite

W = H = 32
CX = CY = 16
# A stone ramp with headroom above the surface tone, so a three-step lift has somewhere to
# go, and a hot source colour the ramp comes nowhere near.
STONE = palette.generate_ramp("#6b6477", steps=8, chroma=0.23)["colors"]
SURFACE = STONE[2]
SOURCE = "#ff8a2a"
TIGHT = 8.0
LOOSE = 40.0


def _grid(name):
    return inspect.get_pixels(name, 0, 0, W, H)["pixels"]


def _index(pixel):
    """Which stone step a pixel is on, or None if it is not on the stone ramp."""
    hexed = pixel.lower()[:7]
    return STONE.index(hexed) if hexed in STONE else None


# ------------------------------------------------------------------- the lift arithmetic
@pytest.mark.pure
def test_the_ring_touching_the_source_takes_the_full_depth():
    assert lighting.emission_lift(4, 3)[0] == 3
    assert lighting.emission_lift(1, 3) == [3]


@pytest.mark.pure
def test_no_ring_in_the_radius_is_allowed_to_move_nothing():
    """A ring that lifts by zero is a ring that should not have been in the radius, and it
    would show up as a result reporting a reach it did not have."""
    for radius in range(1, MAX_GLOW_RADIUS + 1):
        for depth in (1, 2, 5):
            lifts = lighting.emission_lift(radius, depth)
            assert len(lifts) == radius
            assert min(lifts) >= 1, (radius, depth, lifts)
            assert max(lifts) == depth, (radius, depth, lifts)


@pytest.mark.pure
def test_the_lift_never_grows_with_distance():
    for falloff in lighting.FALLOFFS:
        for radius in range(1, 9):
            lifts = lighting.emission_lift(radius, 6, falloff)
            assert lifts == sorted(lifts, reverse=True), (falloff, radius, lifts)


@pytest.mark.pure
def test_quadratic_keeps_the_light_closer_to_the_source_than_linear():
    """Which is the whole reason the argument exists: a linear falloff over a few pixels
    reads as a wash over the surface rather than as something glowing in it."""
    linear = lighting.emission_lift(5, 5, "linear")
    quadratic = lighting.emission_lift(5, 5, "quadratic")
    assert sum(quadratic) < sum(linear), (linear, quadratic)
    assert quadratic[0] == linear[0] == 5, (linear, quadratic)


@pytest.mark.pure
@pytest.mark.parametrize("args,pattern", [
    ((0, 3, "linear"), "radius of at least 1"),
    ((4, 0, "linear"), "depth of at least 1"),
    ((4, 3, "sudden"), "unknown falloff"),
])
def test_an_emission_that_could_not_light_anything_is_a_value_error(args, pattern):
    with pytest.raises(ValueError, match=pattern):
        lighting.emission_lift(*args)


# ------------------------------------------------------------------------ argument checks
@pytest.mark.pure
def test_a_one_colour_ramp_is_refused():
    with pytest.raises(ValidationFailed, match="nowhere to step"):
        shading.surface_emission("x.aseprite", [SURFACE], SOURCE)


@pytest.mark.pure
def test_an_over_cap_ramp_is_refused():
    with pytest.raises(ValidationFailed, match=rf"maximum is {MAX_COLOR_LIST_LENGTH}"):
        shading.surface_emission("x.aseprite", [SURFACE] * (MAX_COLOR_LIST_LENGTH + 1),
                                 SOURCE)


@pytest.mark.pure
def test_a_depth_the_ramp_cannot_express_is_refused():
    """Lifting further than the ramp is long puts every lit pixel on the brightest entry
    whatever it was, which erases the form the light was supposed to describe."""
    with pytest.raises(ValidationFailed, match=r"most this ramp can express is 3"):
        shading.surface_emission("x.aseprite", STONE[:4], SOURCE, depth=4)


@pytest.mark.pure
@pytest.mark.parametrize("kwargs,pattern", [
    ({"falloff": "sudden"}, 'falloff must be "linear" or "quadratic"'),
    ({"radius": MAX_GLOW_RADIUS + 1}, rf"maximum is {MAX_GLOW_RADIUS}"),
    ({"radius": 0}, "minimum is 1"),
    ({"depth": 0}, "minimum is 1 ramp step"),
    ({"tolerance": -1.0}, "tolerance must not be negative"),
    ({"source_tolerance": -1.0}, "source_tolerance must not be negative"),
])
def test_the_pre_flight_refusals_name_the_field_and_the_value(kwargs, pattern):
    with pytest.raises(ValidationFailed, match=pattern):
        shading.surface_emission("x.aseprite", STONE, SOURCE, **kwargs)


# -------------------------------------------------------------------- the editor tier
@pytest.fixture
def cored(request):
    """A stone body with a glowing core *inside* its silhouette."""
    name = f"emit_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_ellipse(name, CX, CY, 13, 13, SURFACE, filled=True)
    drawing.draw_pixel_map(name, ["s"], {"s": SOURCE}, x=CX, y=CY)
    return name


def test_a_halo_has_nowhere_to_go_for_a_source_inside_a_body(cored):
    """The defect, asserted. `glow` grows rings outward from the matching pixels and never
    paints over the subject, so a core inside a silhouette gets a halo of nothing: here it
    refuses outright, and on the golem, where the canvas had room elsewhere, it reported
    success and contributed zero pixels to the export."""
    with pytest.raises(Exception) as caught:
        effects.glow(cored, STONE, radius=3, base_color=SOURCE, tolerance=TIGHT,
                     new_layer="halo")
    assert "nowhere to go" in str(caught.value), str(caught.value)


def test_the_light_lands_on_pixels_inside_the_silhouette(cored):
    """The headline. Every pixel this changes was already painted, and the silhouette is
    exactly the size it was: this repaints a surface rather than adding a halo to it."""
    before = _grid(cored)
    result = shading.surface_emission(cored, STONE, SOURCE, radius=4, depth=4,
                                      source_tolerance=TIGHT, tolerance=LOOSE)
    after = _grid(cored)

    changed = [(x, y) for y in range(H) for x in range(W) if before[y][x] != after[y][x]]
    assert changed, "the pass reported success and changed no pixel"
    assert len(changed) == result["lifted_pixels"], (len(changed), result)
    on_transparency = [p for p in changed if before[p[1]][p[0]][7:9] == "00"]
    assert on_transparency == [], (
        f"{len(on_transparency)} of the changed pixels were transparent, so this painted "
        "a halo rather than lighting a surface")
    assert (len(quality._opaque_cells(after))
            == len(quality._opaque_cells(before))), "the silhouette changed size"


def test_the_lift_falls_off_with_distance_from_the_source(cored):
    """Not a flat band and not a halo: a ray walked outward from the source has to climb
    the ramp at the source and come back down to the untouched surface."""
    shading.surface_emission(cored, STONE, SOURCE, radius=4, depth=4,
                             source_tolerance=TIGHT, tolerance=LOOSE)
    grid = _grid(cored)
    ray = [_index(grid[CY][x]) for x in range(CX + 1, CX + 9)]
    assert None not in ray, f"the ray left the ramp: {ray}"
    assert ray == sorted(ray, reverse=True), f"the lift does not fall off: {ray}"
    assert ray[0] > ray[-1], f"nothing was lifted along the ray: {ray}"
    assert ray[-1] == STONE.index(SURFACE), (
        f"the far end of the ray is at step {ray[-1]} rather than the surface's own "
        f"{STONE.index(SURFACE)}, so the light reached past its radius")


def test_the_rings_are_reported_so_the_falloff_is_in_the_result(cored):
    result = shading.surface_emission(cored, STONE, SOURCE, radius=4, depth=4,
                                      source_tolerance=TIGHT, tolerance=LOOSE)
    assert result["lifts"] == lighting.emission_lift(4, 4, "quadratic"), result["lifts"]
    assert len(result["per_ring"]) == 4
    assert all(count > 0 for count in result["per_ring"]), (
        f"a ring inside the radius lit nothing: {result['per_ring']}")
    assert sum(result["per_ring"]) == result["lifted_pixels"], result


def test_conformance_to_the_declared_ramp_is_preserved(cored):
    """What separates this from a brightness filter, measured with the project's own metric.
    The source colour is counted as allowed because it is part of the art, not of the pass."""
    shading.surface_emission(cored, STONE, SOURCE, radius=4, depth=4,
                             source_tolerance=TIGHT, tolerance=LOOSE)
    assert quality.palette_conformance(_grid(cored), [*STONE, SOURCE]) == 1.0


def test_two_tones_at_the_same_distance_move_together(request):
    """Why the lift is a distance along the ramp rather than a colour per ring. A crack near
    a glowing core has to stay darker than the stone beside it: both brighten, and their
    relation survives. Picking a colour per ring would flatten the two into one."""
    name = f"emit_form_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_ellipse(name, CX, CY, 10, 10, SURFACE, filled=True)
    # A darker patch and the surface tone, both one pixel from the source.
    drawing.draw_pixel_map(name, ["dd"], {"d": STONE[1]}, x=CX - 1, y=CY - 1)
    drawing.draw_pixel_map(name, ["s"], {"s": SOURCE}, x=CX, y=CY)

    before = _grid(name)
    patch, plain = (CX - 1, CY - 1), (CX + 1, CY + 1)
    was = (_index(before[patch[1]][patch[0]]), _index(before[plain[1]][plain[0]]))
    assert was == (1, 2), f"the fixture is not two tones at one distance: {was}"

    shading.surface_emission(name, STONE, SOURCE, radius=3, depth=3,
                             source_tolerance=TIGHT, tolerance=LOOSE)
    after = _grid(name)
    now = (_index(after[patch[1]][patch[0]]), _index(after[plain[1]][plain[0]]))
    assert now[0] - was[0] == now[1] - was[1], (
        f"the darker patch moved {now[0] - was[0]} steps and the surface beside it "
        f"{now[1] - was[1]}, so the form was flattened rather than lit")
    assert now[0] < now[1], f"the patch stopped being the darker of the two: {now}"


def test_the_source_itself_is_never_repainted(cored):
    before = _grid(cored)
    shading.surface_emission(cored, STONE, SOURCE, radius=4, depth=4,
                             source_tolerance=TIGHT, tolerance=LOOSE)
    after = _grid(cored)
    assert after[CY][CX] == before[CY][CX], (
        f"the source was lit by its own light: {before[CY][CX]} became {after[CY][CX]}")


def test_a_source_with_no_surface_around_it_is_refused(request):
    """This lights a surface. A lone source on empty canvas is what `glow` is for, and the
    refusal says so rather than reporting a pass that lit nothing."""
    name = f"emit_lone_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_pixel_map(name, ["s"], {"s": SOURCE}, x=CX, y=CY)
    with pytest.raises(Exception) as caught:
        shading.surface_emission(name, STONE, SOURCE, source_tolerance=TIGHT)
    message = str(caught.value)
    assert "lit nothing" in message, message
    assert "glow is the tool for a halo" in message, message


def test_no_pixel_matching_the_source_is_refused(cored):
    with pytest.raises(Exception, match="No pixel matched source_color"):
        shading.surface_emission(cored, STONE, "#00ff00", source_tolerance=TIGHT)


def test_a_surface_on_another_ramp_is_left_alone_and_said_so(cored):
    """`tolerance` is what stops this dragging another material onto the ramp it was handed.
    With a ramp the stone is nowhere near, every pixel is off-ramp and the pass refuses."""
    with pytest.raises(Exception) as caught:
        # depth 2, not the default: a three-colour ramp cannot express a three-step lift
        # and that refusal fires first, which would pass this test for the wrong reason.
        shading.surface_emission(cored, ["#004400", "#008800", "#00cc00"], SOURCE,
                                 depth=2, source_tolerance=TIGHT, tolerance=4.0)
    assert "from any ramp entry" in str(caught.value), str(caught.value)


def test_a_source_the_ramp_cannot_be_told_apart_from_is_a_warning(request):
    """The quiet failure `contact_shadow` documents at `occluder_tolerance`: a surface that
    matches its own light source spreads the light from the wrong pixels, and nothing in
    the picture says so.

    The source here is the ramp's own brightest step, which is a thing a caller really does
    (a white-hot core on the same ramp as the metal around it). Only the core matches it,
    because the surface is painted several steps down, so the pass still works and the
    overlap is exactly the kind that would otherwise go unnoticed.
    """
    name = f"emit_overlap_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_ellipse(name, CX, CY, 10, 10, SURFACE, filled=True)
    drawing.draw_pixel_map(name, ["s"], {"s": STONE[7]}, x=CX, y=CY)

    result = shading.surface_emission(name, STONE, STONE[7], radius=3, depth=3,
                                      source_tolerance=20.0, tolerance=LOOSE)
    assert result["source_pixels"] == 1, result
    assert any("treated as the light source" in note
               for note in result.get("warnings", [])), result


def test_a_depth_that_cannot_fall_off_is_reported_as_a_flat_band(cored):
    """At depth 1 every ring lifts by the same single step, so the result is a band of
    uniform warmth rather than light falling off, and the arithmetic that produces it is
    quiet. Warned rather than refused: a one-ring lift is a legitimate thing to ask for."""
    result = shading.surface_emission(cored, STONE, SOURCE, radius=3, depth=1,
                                      source_tolerance=TIGHT, tolerance=LOOSE)
    assert result["lifts"] == [1, 1, 1], result["lifts"]
    assert any("flat band" in note for note in result.get("warnings", [])), result

    single = shading.surface_emission(cored, STONE, SOURCE, radius=1, depth=1,
                                      source_tolerance=TIGHT, tolerance=LOOSE)
    assert not any("flat band" in note for note in single.get("warnings", [])), (
        "a one-ring lift cannot fall off and must not be warned about")


def test_an_indexed_palette_that_cannot_hold_the_ramp_is_reported(request):
    """The same protection `contact_shadow` and its siblings have: on an indexed sprite two
    ramp steps can resolve to one palette entry, which makes a lift that changes nothing
    and still reports the pixels it wrote. `palette_conformance` cannot see it, because the
    colour landed on is still on the ramp."""
    name = f"emit_indexed_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, color_mode="indexed", overwrite=True)
    palette.set_palette(name, [*STONE[1:], SOURCE])
    drawing.draw_ellipse(name, CX, CY, 10, 10, SURFACE, filled=True)
    drawing.draw_pixel_map(name, ["s"], {"s": SOURCE}, x=CX, y=CY)

    result = shading.surface_emission(name, STONE, SOURCE, radius=3, depth=3,
                                      source_tolerance=TIGHT, tolerance=LOOSE)
    assert result["lifted_pixels"] > 0, result
    assert any("indexed" in note for note in result.get("warnings", [])), (
        f"the palette cannot hold the declared ramp and nothing said so: {result}")
