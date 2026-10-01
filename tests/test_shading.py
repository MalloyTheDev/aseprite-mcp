"""Ramp-aware shading, tested against a real Aseprite.

The point of these is the palette-conformance assertion: it is what separates a shading
operation from an image filter, and it is objective. Everything else about whether
shading looks good needs a person.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import (
    drawing,
    effects,
    frames,
    inspect,
    palette,
    selection,
    shading,
    sprite,
)

RAMP = ["#362121", "#522b2b", "#824141", "#b16c6c", "#d2b7b7"]


def _grid(name: str) -> quality.Grid:
    return inspect.get_pixels(name, 0, 0, 32, 32)["pixels"]


@pytest.fixture()
def sphere(request):
    """A flat disc painted in a middle ramp step, the classic thing to shade.

    Named after the requesting test: the workspace fixture is session-scoped and
    create_sprite is no-clobber, so a shared filename would make every test after the
    first fail on that rather than on what it is checking.
    """
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse(name, 16, 16, 12, 12, RAMP[3], filled=True)
    return name


def test_shift_along_ramp_keeps_every_pixel_on_the_palette(sphere):
    """The measurement this tool exists for.

    On the same sprite, adjust_brightness_contrast leaves nothing on the ramp while
    shift_along_ramp leaves everything on it. That difference is invisible to every
    other metric: colour count, silhouette and bounding box are identical either way.
    """
    assert quality.palette_conformance(_grid(sphere), RAMP) == 1.0

    result = shading.shift_along_ramp(sphere, RAMP, steps=-1)

    assert quality.palette_conformance(_grid(sphere), RAMP) == 1.0
    # Every drawn pixel, counted from the sprite rather than written down here: the disc
    # is whatever draw_ellipse currently draws, and pinning its area made this test fail
    # when the filled ellipse was corrected to match its own outline.
    drawn = sum(1 for row in _grid(sphere) for px in row if px[7:9] != "00")
    assert result["pixels_matched"] == drawn
    assert result["pixels_written"] == drawn


def test_a_brightness_filter_destroys_the_palette_on_the_same_sprite(sphere):
    """The comparison case, pinned so the claim stays honest if the filter changes."""
    effects.adjust_brightness_contrast(sphere, brightness=-28)
    assert quality.palette_conformance(_grid(sphere), RAMP) == 0.0


def test_shifting_does_not_touch_the_silhouette(sphere):
    before = quality.bounding_box(_grid(sphere))
    shading.shift_along_ramp(sphere, RAMP, steps=-1)
    assert quality.bounding_box(_grid(sphere)) == before


def test_shifting_clamps_at_the_ends_rather_than_wrapping(sphere):
    """A shadow that wraps round to the highlight is never what was asked for."""
    shading.shift_along_ramp(sphere, RAMP, steps=-99)
    rows = _grid(sphere)
    opaque = {p.lower() for row in rows for p in row if not p.lower().endswith("00")}
    assert opaque == {RAMP[0].lower() + "ff"}, opaque

    shading.shift_along_ramp(sphere, RAMP, steps=99)
    rows = _grid(sphere)
    opaque = {p.lower() for row in rows for p in row if not p.lower().endswith("00")}
    assert opaque == {RAMP[-1].lower() + "ff"}, opaque


def test_pixels_far_from_the_ramp_are_left_alone(sphere):
    """Shading one material must not disturb the ones beside it."""
    drawing.draw_rectangle(sphere, 0, 0, 4, 4, "#1188ff", filled=True)
    result = shading.shift_along_ramp(sphere, RAMP, steps=-1, tolerance=20)

    assert result["pixels_skipped"] >= 16, result
    rows = _grid(sphere)
    assert any(p.lower().startswith("#1188ff") for row in rows for p in row), (
        "the blue square should have been left untouched"
    )


def test_a_region_scopes_the_change(sphere):
    """Whole-layer shading flattens separate materials into one ramp."""
    result = shading.shift_along_ramp(sphere, RAMP, steps=-1, x=0, y=0, width=16, height=32)
    assert 0 < result["pixels_matched"] < 477


def test_shift_along_ramp_rejects_arguments_that_cannot_mean_anything():
    name = "sh/reject.aseprite"
    sprite.create_sprite(name, 8, 8)
    with pytest.raises(ValidationFailed, match="at least 2"):
        shading.shift_along_ramp(name, ["#000000"], steps=-1)
    with pytest.raises(ValidationFailed, match="non-zero"):
        shading.shift_along_ramp(name, RAMP, steps=0)
    with pytest.raises(ValidationFailed, match="tolerance"):
        shading.shift_along_ramp(name, RAMP, steps=-1, tolerance=-1)


def test_generate_ramp_and_shift_compose(sphere):
    """The two halves of the workflow have to agree on what a ramp is."""
    ramp = palette.generate_ramp(
        "#a05050", steps=5, saturation_shift=30, sat_curve="peak", easing="perceptual"
    )["colors"]
    name = "sh/composed.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse(name, 16, 16, 10, 10, ramp[3], filled=True)

    shading.shift_along_ramp(name, ramp, steps=-1)
    assert quality.palette_conformance(_grid(name), ramp) == 1.0


# ------------------------------------------------------------- form shading


def _lit_centroid(name: str, size: int = 24) -> tuple[float, float] | None:
    """Where the brightest half of the ramp sits, as a centre of mass.

    A cheap way to ask "which way is the light coming from" without eyeballing.
    """
    rows = inspect.get_pixels(name, 0, 0, size, size)["pixels"]
    bright = {c.lower() + "ff" for c in RAMP[3:]}
    xs, ys = [], []
    for y, row in enumerate(rows):
        for x, px in enumerate(row):
            if px.lower() in bright:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys))


@pytest.fixture()
def disc(request):
    """A flat disc on a 24x24 canvas, big enough to have an interior to shade."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 10, 10, RAMP[3], filled=True)
    return name


def test_form_shading_uses_the_ramp_and_only_the_ramp(disc):
    result = shading.shade_region_by_light(disc, RAMP, light_angle=135)

    rows = inspect.get_pixels(disc, 0, 0, 24, 24)["pixels"]
    assert quality.palette_conformance(rows, RAMP) == 1.0
    assert result["shaded_pixels"] == result["region_pixels"]


def test_form_shading_spans_several_ramp_steps(disc):
    """A form quantised into one or two steps is a flat fill with extra work.

    This caught a real bug: the height field was normalised to 0..1 regardless of the
    region's size, so on anything bigger than a couple of pixels the gradient was
    vanishingly small, every normal pointed straight up, and the whole disc came out in
    two colours. Height has to be in the same units as x and y.
    """
    shading.shade_region_by_light(disc, RAMP, light_angle=135)
    rows = inspect.get_pixels(disc, 0, 0, 24, 24)["pixels"]
    assert quality.distinct_colors(rows) >= 3


def test_the_light_direction_actually_moves_the_light(disc, request):
    """The anti-pillow-shading test.

    Pillow shading is bands concentric with the silhouette, which looks identical from
    every light angle. If the lit region does not move when the light does, the tool is
    offsetting the outline rather than lighting a form.
    """
    other = f"sh/{request.node.name}_other.aseprite"
    sprite.create_sprite(other, 24, 24)
    drawing.draw_ellipse(other, 12, 12, 10, 10, RAMP[3], filled=True)

    shading.shade_region_by_light(disc, RAMP, light_angle=135)
    shading.shade_region_by_light(other, RAMP, light_angle=315)

    upper_left = _lit_centroid(disc)
    lower_right = _lit_centroid(other)
    assert upper_left is not None and lower_right is not None
    assert upper_left[0] < lower_right[0], (upper_left, lower_right)
    assert upper_left[1] < lower_right[1], (upper_left, lower_right)


def test_the_lit_region_is_not_centred_on_the_silhouette(disc):
    """Concentric bands would put the bright centroid at the middle of the disc."""
    shading.shade_region_by_light(disc, RAMP, light_angle=135)
    centroid = _lit_centroid(disc)
    assert centroid is not None
    assert abs(centroid[0] - 12) > 1.5 or abs(centroid[1] - 12) > 1.5, centroid


def test_a_region_with_no_interior_is_refused(request):
    """Below roughly 6px across there is no form to describe, so say so."""
    from aseprite_mcp.core.errors import AsepriteError

    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_rectangle(name, 2, 10, 20, 2, RAMP[3], filled=True)

    with pytest.raises(AsepriteError, match="too thin to shade"):
        shading.shade_region_by_light(name, RAMP)


def test_shading_respects_an_active_selection(request):
    """The reason this is region-scoped: one ramp per material, not per layer."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 10, 10, RAMP[3], filled=True)
    selection.select_region(name, "rect", x=0, y=0, width=12, height=24)

    result = shading.shade_region_by_light(name, RAMP, light_angle=135)

    assert result["selection_applied"] is True
    assert result["region_pixels"] < 333, "the field should be scoped to the selection"

    rows = inspect.get_pixels(name, 0, 0, 24, 24)["pixels"]
    right_half = {p.lower()[:7] for row in rows for p in row[13:] if not p.lower().endswith("00")}
    assert right_half == {RAMP[3]}, f"the unselected half must be untouched: {right_half}"


def test_base_color_scopes_without_a_selection(request):
    """Two materials, one call each, no selection needed."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_rectangle(name, 1, 1, 10, 22, RAMP[3], filled=True)
    drawing.draw_rectangle(name, 13, 1, 10, 22, "#50a050", filled=True)

    shading.shade_region_by_light(name, RAMP, base_color=RAMP[3], tolerance=10)

    rows = inspect.get_pixels(name, 0, 0, 24, 24)["pixels"]
    present = {p.lower()[:7] for row in rows for p in row if not p.lower().endswith("00")}
    assert "#50a050" in present, "the other material must be untouched"
    assert len(present & {c.lower() for c in RAMP}) >= 3, present


def test_form_shading_rejects_arguments_that_cannot_mean_anything(request):
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 10, 10, RAMP[3], filled=True)

    with pytest.raises(ValidationFailed, match="at least 3"):
        shading.shade_region_by_light(name, RAMP[:2])
    with pytest.raises(ValidationFailed, match="ambient"):
        shading.shade_region_by_light(name, RAMP, ambient=2.0)
    with pytest.raises(ValidationFailed, match="rim"):
        shading.shade_region_by_light(name, RAMP, rim=-1)
    with pytest.raises(ValidationFailed, match="light_z"):
        shading.shade_region_by_light(name, RAMP, light_z=5)
    with pytest.raises(ValidationFailed, match="bulge"):
        shading.shade_region_by_light(name, RAMP, bulge=0)


def test_nothing_matching_base_color_is_an_error_not_a_silent_no_op(request):
    from aseprite_mcp.core.errors import AsepriteError

    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 10, 10, RAMP[3], filled=True)

    with pytest.raises(AsepriteError, match="Nothing to shade"):
        shading.shade_region_by_light(name, RAMP, base_color="#00ff00", tolerance=1)


# ------------------------------------------------------- contact / outline / dither


def _colors_in(name: str, size: int) -> set[str]:
    rows = inspect.get_pixels(name, 0, 0, size, size)["pixels"]
    return {p.lower()[:7] for row in rows for p in row if not p.lower().endswith("00")}


@pytest.fixture()
def ball_on_ground(request):
    """A disc resting on a band of a different colour: the contact-shadow case."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 20, 20)
    drawing.draw_rectangle(name, 0, 15, 20, 5, "#404040", filled=True)
    drawing.draw_ellipse(name, 10, 10, 5, 5, RAMP[3], filled=True)
    return name


def test_contact_shadow_darkens_toward_the_occluder(ball_on_ground):
    """The darkening has to fall off with distance, or it is a band not a contact."""
    result = shading.contact_shadow(
        ball_on_ground, RAMP, occluder_color="#404040", radius=2, depth=2
    )
    assert result["darkened_pixels"] > 0
    assert result["occluder_pixels"] > 0

    rows = inspect.get_pixels(ball_on_ground, 0, 0, 20, 20)["pixels"]
    index = {c.lower() + "ff": i for i, c in enumerate(RAMP)}

    def shade_at(x, y):
        return index.get(rows[y][x].lower())

    near = shade_at(10, 14)
    far = shade_at(10, 8)
    assert near is not None and far is not None
    assert near < far, "pixels nearer the ground should be darker"


def test_contact_shadow_keeps_everything_on_the_ramp(ball_on_ground):
    shading.contact_shadow(ball_on_ground, RAMP, occluder_color="#404040", radius=2)
    rows = inspect.get_pixels(ball_on_ground, 0, 0, 20, 20)["pixels"]
    ball = [p for row in rows for p in row if p.lower()[:7] != "#404040"
            and not p.lower().endswith("00")]
    allowed = {c.lower() + "ff" for c in RAMP}
    assert {p.lower() for p in ball} <= allowed


def test_contact_shadow_says_so_when_nothing_matches(ball_on_ground):
    from aseprite_mcp.core.errors import AsepriteError

    with pytest.raises(AsepriteError, match="No pixel matched occluder_color"):
        shading.contact_shadow(
            ball_on_ground, RAMP, occluder_color="#00ff00", tolerance=1
        )


def test_contact_shadow_rejects_a_radius_that_is_really_a_drop_shadow(ball_on_ground):
    with pytest.raises(ValidationFailed, match="radius"):
        shading.contact_shadow(ball_on_ground, RAMP, occluder_color="#404040", radius=0)
    with pytest.raises(ValidationFailed, match="depth"):
        shading.contact_shadow(ball_on_ground, RAMP, occluder_color="#404040", depth=0)


@pytest.fixture()
def shaded_disc(request):
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    drawing.draw_ellipse(name, 8, 8, 5, 5, RAMP[3], filled=True)
    shading.shade_region_by_light(name, RAMP, light_angle=135)
    return name


def test_colormatched_outline_varies_with_the_form(shaded_disc):
    """A flat outline reads as a sticker. This one follows the shading."""
    before = _colors_in(shaded_disc, 16)
    result = shading.outline_smart(shaded_disc, RAMP, mode="colormatched", darken_steps=2)

    assert result["outline_pixels"] > 0
    after = _colors_in(shaded_disc, 16)
    assert after >= before, "outlining must not remove interior colours"
    assert after <= {c.lower() for c in RAMP}, "outline colours must come from the ramp"
    assert len(after) > len(before) or len(before) >= 3


def test_selective_outline_drops_the_lit_side(shaded_disc, request):
    """Fewer outline pixels than colormatched, because the lit side is left open."""
    other = f"sh/{request.node.name}_cm.aseprite"
    sprite.create_sprite(other, 16, 16)
    drawing.draw_ellipse(other, 8, 8, 5, 5, RAMP[3], filled=True)
    shading.shade_region_by_light(other, RAMP, light_angle=135)

    selective = shading.outline_smart(
        shaded_disc, RAMP, mode="selective", light_angle=135
    )
    colormatched = shading.outline_smart(other, RAMP, mode="colormatched")

    assert selective["outline_pixels"] < colormatched["outline_pixels"]


def test_selective_outline_needs_to_know_where_the_light_is(shaded_disc):
    with pytest.raises(ValidationFailed, match="light_angle"):
        shading.outline_smart(shaded_disc, RAMP, mode="selective")


def test_outline_does_not_eat_into_the_artwork(shaded_disc):
    """It grows outward into transparency; the silhouette must only ever get bigger."""
    rows_before = inspect.get_pixels(shaded_disc, 0, 0, 16, 16)["pixels"]
    solid_before = {
        (x, y)
        for y, row in enumerate(rows_before)
        for x, p in enumerate(row)
        if not p.lower().endswith("00")
    }

    shading.outline_smart(shaded_disc, RAMP, mode="single")

    rows_after = inspect.get_pixels(shaded_disc, 0, 0, 16, 16)["pixels"]
    solid_after = {
        (x, y)
        for y, row in enumerate(rows_after)
        for x, p in enumerate(row)
        if not p.lower().endswith("00")
    }
    assert solid_before <= solid_after


def test_outline_smart_rejects_an_unknown_mode(shaded_disc):
    with pytest.raises(ValidationFailed, match="mode"):
        shading.outline_smart(shaded_disc, RAMP, mode="fancy")


@pytest.fixture()
def two_bands(request):
    """Two adjacent ramp steps meeting on a hard line."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    drawing.draw_rectangle(name, 0, 0, 16, 8, RAMP[2], filled=True)
    drawing.draw_rectangle(name, 0, 8, 16, 8, RAMP[3], filled=True)
    return name


def test_dither_band_touches_only_the_boundary(two_bands):
    """Dithering a whole sprite is what makes dithering look dated."""
    result = shading.dither_band(two_bands, RAMP, from_step=3, to_step=4)
    assert result["dithered_pixels"] > 0

    rows = inspect.get_pixels(two_bands, 0, 0, 16, 16)["pixels"]
    # Rows well away from the seam must be untouched.
    assert {p.lower()[:7] for p in rows[0]} == {RAMP[2]}
    assert {p.lower()[:7] for p in rows[15]} == {RAMP[3]}
    # The seam rows must now contain both.
    assert {p.lower()[:7] for p in rows[7]} == {RAMP[2], RAMP[3]}


def test_dither_band_introduces_no_new_colours(two_bands):
    before = _colors_in(two_bands, 16)
    shading.dither_band(two_bands, RAMP, from_step=3, to_step=4)
    assert _colors_in(two_bands, 16) == before


def test_dither_band_ramps_across_the_zone_rather_than_checkerboarding_it(two_bands):
    """Dithering is a gradient, not a texture.

    Comparing the ordered-dither threshold against a fixed 0.5 gives a uniform 50/50
    checkerboard over the whole zone, which is not what dithering is for. The mix has to
    follow how far through the transition each pixel sits: near the seam about half the
    pixels flip, and deep in a band almost none do.
    """
    shading.dither_band(two_bands, RAMP, 3, 4, pattern="bayer4", width=3)
    rows = inspect.get_pixels(two_bands, 0, 0, 16, 16)["pixels"]

    def share_of_lower(y: int) -> float:
        return sum(1 for p in rows[y] if p.lower()[:7] == RAMP[3]) / len(rows[y])

    zone = [share_of_lower(y) for y in range(6, 11)]

    # Compared across the zone rather than between neighbours: a 4x4 Bayer cell can
    # only express a few distinct fractions per row, so two adjacent rows legitimately
    # tie even where the underlying mix differs.
    assert zone[0] < zone[-1], f"the zone should ramp toward the lower band: {zone}"
    assert len(set(zone)) > 1, f"a uniform zone is a texture, not a gradient: {zone}"
    # And it stays a transition: neither end of the zone is pure.
    assert 0.0 < zone[len(zone) // 2] < 1.0, zone


def test_dither_patterns_differ(two_bands, request):
    """A one-pixel-deep seam alternates whatever the pattern, so this needs width."""
    other = f"sh/{request.node.name}_b.aseprite"
    sprite.create_sprite(other, 16, 16)
    drawing.draw_rectangle(other, 0, 0, 16, 8, RAMP[2], filled=True)
    drawing.draw_rectangle(other, 0, 8, 16, 8, RAMP[3], filled=True)

    fine = shading.dither_band(two_bands, RAMP, 3, 4, pattern="bayer4", width=3)
    hard = shading.dither_band(other, RAMP, 3, 4, pattern="checker", width=3)
    assert fine["pattern"] != hard["pattern"]

    a = inspect.get_pixels(two_bands, 0, 0, 16, 16)["pixels"]
    b = inspect.get_pixels(other, 0, 0, 16, 16)["pixels"]
    assert a != b, "different patterns should produce different pixels"


def test_dither_band_rejects_a_width_that_is_a_texture(two_bands):
    with pytest.raises(ValidationFailed, match="width"):
        shading.dither_band(two_bands, RAMP, 3, 4, width=0)
    with pytest.raises(ValidationFailed, match="width"):
        shading.dither_band(two_bands, RAMP, 3, 4, width=99)


def test_dither_band_refuses_non_adjacent_steps(two_bands):
    """Dithering between distant steps is noise, not an intermediate shade."""
    with pytest.raises(ValidationFailed, match="adjacent"):
        shading.dither_band(two_bands, RAMP, from_step=1, to_step=4)
    with pytest.raises(ValidationFailed, match="between 1 and"):
        shading.dither_band(two_bands, RAMP, from_step=0, to_step=1)
    with pytest.raises(ValidationFailed, match="pattern"):
        shading.dither_band(two_bands, RAMP, 3, 4, pattern="noise")


# ------------------------------------------------- specular highlight and a fill light


def _opaque_cells(name: str, size: int) -> dict[tuple[int, int], str]:
    rows = inspect.get_pixels(name, 0, 0, size, size)["pixels"]
    return {
        (x, y): p.lower()
        for y, row in enumerate(rows)
        for x, p in enumerate(row)
        if not p.lower().endswith("00")
    }


@pytest.fixture()
def shaded_ball(request):
    """A disc shaded with the ramp MINUS its top step, which is reserved for the glint.

    This is the documented workflow, and it is the only one in which a specular is
    visible: shading with the whole ramp spreads the top step over the lit side and
    leaves nothing above it, which the tool refuses rather than painting invisibly.
    """
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[2], filled=True)
    shading.shade_region_by_light(name, RAMP[:-1], light_angle=135, light_z=0.45)
    return name


def test_a_specular_is_a_ramp_step_and_not_a_new_colour(shaded_ball):
    """The acceptance criterion: a highlight is a ramp step, never an invented colour."""
    result = shading.specular_highlight(shaded_ball, RAMP, light_angle=135, size=3)

    assert result["specular_pixels"] == 3
    assert result["pixels_changed"] == 3
    assert result["highlight_on_ramp"] is True
    rows = inspect.get_pixels(shaded_ball, 0, 0, 24, 24)["pixels"]
    assert quality.palette_conformance(rows, RAMP) == 1.0


def test_a_glint_that_would_be_invisible_is_refused_rather_than_reported_as_done(request):
    """Shading with the whole ramp leaves nothing above its top step for a glint to be.

    A tool that writes three pixels the colour they already are and reports success is
    the failure this codebase keeps finding, so this is an error that names the fix.
    """
    from aseprite_mcp.core.errors import AsepriteError

    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[3], filled=True)
    shading.shade_region_by_light(name, RAMP, light_angle=135)

    with pytest.raises(AsepriteError, match="glint would be invisible") as exc:
        shading.specular_highlight(name, RAMP, light_angle=135, size=3)
    assert "minus its last entry" in str(exc.value)


def test_a_specular_never_lands_on_an_edge_pixel(shaded_ball):
    """Asserted from the rendered grid, not from the parameters.

    A glint on the silhouette's border reads as a hole punched in the form. The check is
    that every pixel the tool wrote has all eight neighbours opaque, which is the property
    the tool claims rather than the mechanism it used to get there.
    """
    result = shading.specular_highlight(shaded_ball, RAMP, light_angle=135, size=4)
    after = _opaque_cells(shaded_ball, 24)

    assert result["pixels"], "the specular has to have written something"
    assert len(result["pixels"]) == result["specular_pixels"]
    for x, y in result["pixels"]:
        missing = [
            (x + dx, y + dy)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if not (dx == 0 and dy == 0) and (x + dx, y + dy) not in after
        ]
        assert not missing, f"specular pixel {(x, y)} touches the edge at {missing}"


def test_a_specular_lands_on_the_lit_side(shaded_ball, request):
    """And moves when the light does, which is what makes it a specular and not a dot."""
    other = f"sh/{request.node.name}_other.aseprite"
    sprite.create_sprite(other, 24, 24)
    drawing.draw_ellipse(other, 12, 12, 9, 9, RAMP[2], filled=True)
    shading.shade_region_by_light(other, RAMP[:-1], light_angle=315, light_z=0.45)

    upper_left = shading.specular_highlight(shaded_ball, RAMP, light_angle=135)
    lower_right = shading.specular_highlight(other, RAMP, light_angle=315)

    assert upper_left["seat"][0] < 12 and upper_left["seat"][1] < 12, upper_left["seat"]
    assert lower_right["seat"][0] > 12 and lower_right["seat"][1] > 12, lower_right["seat"]


def test_a_specular_is_one_connected_blob_rather_than_scattered_dots(shaded_ball):
    """Taking the globally best pixels would spread the glint over the whole lit side."""
    shading.specular_highlight(shaded_ball, RAMP, light_angle=135, size=5)
    rows = inspect.get_pixels(shaded_ball, 0, 0, 24, 24)["pixels"]
    top = RAMP[-1].lower() + "ff"
    glint = {
        (x, y)
        for y, row in enumerate(rows)
        for x, p in enumerate(row)
        if p.lower() == top
    }
    assert glint

    # Flood fill over 8-connectivity: one component means one glint.
    seen, stack = set(), [next(iter(glint))]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if (x + dx, y + dy) in glint:
                    stack.append((x + dx, y + dy))
    assert seen == glint, f"the glint is in several pieces: {sorted(glint - seen)}"


def test_a_specular_does_not_move_the_silhouette(request):
    """The classic bug in this area, measured with diff_sprites rather than by eye."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    frames.add_frame(name)
    for f in (1, 2):
        drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[2], filled=True, frame=f)
        shading.shade_region_by_light(name, RAMP[:-1], light_angle=135, frame=f)

    shading.specular_highlight(name, RAMP, light_angle=135, size=3, frame=2)

    verdict = inspect.diff_sprites(name, 1, other_frame=2, expect="interior")["verdict"]
    assert verdict["passed"] is True, verdict


def test_a_metal_glint_may_leave_the_ramp_and_says_so(shaded_ball):
    """Metal is the one material whose specular is brighter than its own ramp.

    The tool does not pretend this is still on the palette: it reports that it is not,
    which is the honest trade rather than a silent conformance drop.
    """
    result = shading.specular_highlight(
        shaded_ball, RAMP, light_angle=135, size=2, highlight_color="#fff6f6"
    )

    assert result["highlight_on_ramp"] is False
    rows = inspect.get_pixels(shaded_ball, 0, 0, 24, 24)["pixels"]
    assert quality.palette_conformance(rows, RAMP) < 1.0
    assert quality.palette_conformance(rows, [*RAMP, "#fff6f6"]) == 1.0


def test_a_specular_takes_the_ramp_top_by_default(shaded_ball):
    result = shading.specular_highlight(shaded_ball, RAMP, light_angle=135, size=1)
    x, y = result["seat"]
    rows = inspect.get_pixels(shaded_ball, 0, 0, 24, 24)["pixels"]
    assert rows[y][x].lower()[:7] == RAMP[-1].lower()


def test_a_region_too_thin_for_a_specular_gives_the_shading_refusal(request):
    """The same message shade_region_by_light gives, not a silently different result."""
    from aseprite_mcp.core.errors import AsepriteError

    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_rectangle(name, 2, 10, 20, 2, RAMP[3], filled=True)

    with pytest.raises(AsepriteError, match="too thin to shade"):
        shading.specular_highlight(name, RAMP)


def test_a_light_that_reflects_nowhere_is_refused_with_the_number_to_use(shaded_ball):
    """A parameter the caller cannot guess has to come back in the error."""
    from aseprite_mcp.core.errors import AsepriteError

    with pytest.raises(AsepriteError, match="faces the reflection closely enough") as exc:
        shading.specular_highlight(shaded_ball, RAMP, light_angle=135, tightness=1.0)
    assert "best alignment anywhere in the region is" in str(exc.value)


def test_specular_rejects_arguments_that_cannot_mean_anything(shaded_ball):
    with pytest.raises(ValidationFailed, match="at least 2"):
        shading.specular_highlight(shaded_ball, ["#000000"])
    with pytest.raises(ValidationFailed, match="tightness"):
        shading.specular_highlight(shaded_ball, RAMP, tightness=1.5)
    with pytest.raises(ValidationFailed, match="light_z"):
        shading.specular_highlight(shaded_ball, RAMP, light_z=-1)
    with pytest.raises(ValidationFailed, match="size"):
        shading.specular_highlight(shaded_ball, RAMP, size=0)
    with pytest.raises(ValidationFailed, match="size"):
        shading.specular_highlight(shaded_ball, RAMP, size=10_000)
    with pytest.raises(ValidationFailed, match="bulge"):
        shading.specular_highlight(shaded_ball, RAMP, bulge=0)


def test_nothing_matching_base_color_is_refused_for_a_specular_too(shaded_ball):
    from aseprite_mcp.core.errors import AsepriteError

    with pytest.raises(AsepriteError, match="Nothing to highlight"):
        shading.specular_highlight(shaded_ball, RAMP, base_color="#00ff00", tolerance=1)


def test_a_fill_light_lightens_the_shadow_side(request):
    """The acceptance criterion, as a count of pixels per ramp step rather than by eye."""
    plain = f"sh/{request.node.name}_plain.aseprite"
    filled = f"sh/{request.node.name}_fill.aseprite"
    for name in (plain, filled):
        sprite.create_sprite(name, 24, 24)
        drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[3], filled=True)

    one = shading.shade_region_by_light(plain, RAMP, light_angle=135, ambient=0.2)
    two = shading.shade_region_by_light(
        filled, RAMP, light_angle=135, ambient=0.2, fill_angle=315, fill_strength=0.5
    )

    assert one["fill_light"] is False and two["fill_light"] is True
    assert one["region_pixels"] == two["region_pixels"]

    # The shadow side is the dark end of the ramp, so a fill light has to move pixels up
    # out of it. Measured over the dark half rather than over step 0 alone: with ambient
    # at 0.2 nothing reaches the very bottom step even unfilled, so step 0 is 0 either way
    # and would make this assertion pass for the wrong reason.
    dark = len(RAMP) // 2
    assert sum(two["per_step"][:dark]) < sum(one["per_step"][:dark]), (
        one["per_step"], two["per_step"]
    )

    # And the form as a whole is lighter: the mean ramp step rises.
    def mean_step(per_step):
        total = sum(per_step)
        return sum(i * n for i, n in enumerate(per_step)) / total

    assert mean_step(two["per_step"]) > mean_step(one["per_step"])

    rows = inspect.get_pixels(filled, 0, 0, 24, 24)["pixels"]
    assert quality.palette_conformance(rows, RAMP) == 1.0


def test_a_fill_light_does_not_move_the_silhouette(request):
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    frames.add_frame(name)
    for f in (1, 2):
        drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[3], filled=True, frame=f)
    shading.shade_region_by_light(name, RAMP, light_angle=135, frame=1)
    shading.shade_region_by_light(
        name, RAMP, light_angle=135, fill_angle=315, fill_strength=0.5, frame=2
    )

    verdict = inspect.diff_sprites(name, 1, other_frame=2, expect="interior")["verdict"]
    assert verdict["passed"] is True, verdict


def test_a_fill_light_does_not_darken_the_lit_side(request):
    """Summed and clamped, not averaged: averaging would cost the ramp's top step.

    This is the regression guard for the trade-off the tool chose. If the two lights are
    ever combined by normalising instead, the brightest step loses pixels and this fails.
    """
    plain = f"sh/{request.node.name}_plain.aseprite"
    filled = f"sh/{request.node.name}_fill.aseprite"
    for name in (plain, filled):
        sprite.create_sprite(name, 24, 24)
        drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[3], filled=True)

    one = shading.shade_region_by_light(plain, RAMP, light_angle=135)
    two = shading.shade_region_by_light(
        filled, RAMP, light_angle=135, fill_angle=315, fill_strength=0.5
    )

    assert two["per_step"][-1] == one["per_step"][-1], (one["per_step"], two["per_step"])


def test_a_fill_light_as_strong_as_the_key_is_refused(request):
    """It cancels the form, which is the thing the tool exists to produce."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[3], filled=True)

    with pytest.raises(ValidationFailed, match="fill_strength"):
        shading.shade_region_by_light(
            name, RAMP, light_angle=135, fill_angle=315, fill_strength=1.0
        )
    with pytest.raises(ValidationFailed, match="fill_strength"):
        shading.shade_region_by_light(
            name, RAMP, light_angle=135, fill_angle=315, fill_strength=-0.1
        )


def test_fill_strength_is_ignored_without_a_fill_angle(request):
    """No second light means nothing to validate, so an unused value must not refuse."""
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_ellipse(name, 12, 12, 9, 9, RAMP[3], filled=True)

    result = shading.shade_region_by_light(name, RAMP, fill_strength=5.0)
    assert result["fill_light"] is False

# =============================================== the shading layer on indexed art (#145)
# Every test above this line builds an RGB sprite, so the indexed path through the whole
# shading layer was untested. It is not a corner: an indexed pixel is an offset into a
# palette, so a ramp colour the palette does not hold cannot be written at all. It
# resolves to the nearest entry that can draw, and the result says the pixels were
# written because they were.
#
# Built index by index (`create_sprite(color_mode="indexed")`, `set_palette`, then draw)
# rather than by converting an RGB sprite, because the palette is the whole point of
# these cases and a quantization would decide it for us.
def _indexed_sprite(request, colors: list[str], draw: str, suffix: str = "") -> str:
    name = f"sh/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, 32, 32, color_mode="indexed")
    palette.set_palette(name, ["#00000000", *colors])
    drawing.draw_ellipse(name, 16, 16, 12, 12, draw, filled=True)
    return name


def test_a_ramp_the_indexed_palette_holds_shades_and_conforms(request):
    """The arrangement this server recommends: a palette built from the ramp. Shading
    then behaves exactly as it does on RGB, conformance is 1.0, and nothing is warned
    about, because there is nothing wrong."""
    name = _indexed_sprite(request, RAMP, RAMP[3])

    result = shading.shade_region_by_light(
        name, ramp=RAMP, light_angle=135.0, tolerance=64.0)

    assert "warnings" not in result, "a palette that holds the ramp is not worth a word"
    assessed = inspect.assess_sprite(name, ramp=RAMP)
    assert assessed["metrics"]["palette_conformance"] == 1.0
    assert assessed["readings"] == [] or all(
        "ramp" not in note for note in assessed["readings"]
    )
    assert assessed["metrics"]["colors"] > 2, "it actually shaded"


def test_a_ramp_the_indexed_palette_cannot_hold_reports_the_collapse(request):
    """The defect. The palette holds three of the ramp's five colours, so steps 1 and 2
    both resolve to entry 1 and steps 3 and 4 both resolve to entry 2.

    A one-step shade of art drawn in step 1 therefore rewrites every pixel to the colour
    it already was: measured at 144 pixels written and a sprite identical afterwards. No
    existing signal catches that. `pixels_written` counts the writes, which happened, and
    `palette_conformance` reads 1.0 because the colour landed on is still on the declared
    ramp. The only place the finding can come from is the palette.
    """
    sparse = [RAMP[0], RAMP[2], RAMP[4]]
    name = _indexed_sprite(request, sparse, RAMP[0])
    before = inspect.get_pixels(name, 0, 0, 32, 32)["pixels"]

    result = shading.shift_along_ramp(name, ramp=RAMP, steps=1, tolerance=64.0)

    assert result["pixels_written"] > 0, "it reported writing pixels"
    assert inspect.get_pixels(name, 0, 0, 32, 32)["pixels"] == before, (
        "and the picture is unchanged, which is the whole problem"
    )
    measured = result["ramp_on_palette"]
    assert (measured["declared"], measured["resolved"]) == (5, 3)
    assert measured["exact"] == 3
    warning = " ".join(result["warnings"])
    assert "3 of the 5" in warning
    assert "steps 1 and 2" in warning
    assert "changes nothing" in warning

    # And the metric that is supposed to separate shading from filtering is blind to it,
    # which is why this is reported from the palette and not from the pixels. Pinned so
    # the reading is never dropped on the theory that conformance would have caught it.
    assert inspect.assess_sprite(name, ramp=RAMP)["metrics"]["palette_conformance"] == 1.0


def test_assess_sprite_says_when_conformance_is_measuring_the_palette(request):
    """`assess_sprite(ramp=...)` is the tool a caller uses to check their shading. On an
    indexed sprite whose palette does not hold the declared ramp, the conformance number
    is about the palette rather than the shading, and the report has to say so where the
    number is, not leave the caller to infer it."""
    name = _indexed_sprite(request, [RAMP[0], RAMP[2], RAMP[4]], RAMP[0])

    assessed = inspect.assess_sprite(name, ramp=RAMP)

    notes = " ".join(assessed["readings"])
    assert "3 of the 5 declared ramp steps" in notes
    assert "palette_conformance" in notes, "named explicitly, beside the number it qualifies"
    assert assessed["metrics"]["palette_conformance"] == 1.0, (
        "the number itself is unchanged; it is the reading that was missing"
    )


def test_a_ramp_with_no_colours_in_the_palette_says_there_is_no_ramp(request):
    """The catastrophic end: a palette of one drawable colour. Distinct from banding,
    because nothing the tool writes can vary at all."""
    name = _indexed_sprite(request, ["#808080"], "index:1")

    result = shading.gradient_map(name, ramp=RAMP)

    joined = " ".join(result["warnings"])
    assert "no ramp on this sprite to shade along" in joined
    assert result["ramp_on_palette"]["resolved"] == 1


def test_an_rgb_sprite_is_never_told_about_a_palette(request, sphere):
    """The reading must not become noise on the common case. An RGB pixel carries its own
    colour, there is no palette to snap to, and the measurement is skipped rather than
    computed and found uninteresting."""
    result = shading.shift_along_ramp(sphere, ramp=RAMP, steps=-1, tolerance=64.0)

    assert "ramp_on_palette" not in result
    assert "warnings" not in result


def test_effects_that_take_a_ramp_report_it_too(request):
    """The finding is not specific to shading.py: `cast_shadow` and `glow` resolve a ramp
    against the same palette through the same `rgba_to_px`, so they get the same reading
    from the same place rather than each growing their own."""
    name = _indexed_sprite(request, [RAMP[0], RAMP[2], RAMP[4]], RAMP[2])

    result = effects.glow(name, ramp=RAMP, radius=2, tolerance=64.0)

    assert result["ramp_on_palette"]["declared"] == 5
    assert any("declared ramp steps" in note for note in result["warnings"])


def test_a_palette_that_can_draw_nothing_does_not_fail_the_call(request):
    """A regression test for the reporting path itself.

    The ramp measurement runs in the harness, after the body has succeeded and outside
    the pcall that guards it, and `nearest_index` raises when no palette entry can draw.
    So the first version of this feature turned a completed no-op into a hard failure: a
    shade that matched nothing on a sprite whose palette held one transparent entry had
    written nothing, had nothing to fail about, and failed. The script aborted before
    RESULT was printed, so the call came back with no result at all.

    The measurement now answers that case instead of asking it, and the harness pcalls it
    besides, so a future error inside a measurement cannot fail the operation it is
    describing either. This test pins the known cause; the pcall is the backstop for the
    ones nobody has found.
    """
    name = f"sh/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16, color_mode="indexed")
    palette.set_palette(name, ["#00000000"])

    result = shading.shift_along_ramp(name, ramp=RAMP, steps=1, tolerance=1.0)

    assert result["ok"] is True, "nothing was written, so nothing failed"
    assert result["pixels_matched"] == 0
    assert result["ramp_on_palette"]["undrawable_palette"] is True
    assert "no entry that can draw a visible pixel" in " ".join(result["warnings"])
