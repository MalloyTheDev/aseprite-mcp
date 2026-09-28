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
    assert result["pixels_matched"] == 477
    assert result["pixels_written"] == 477


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
