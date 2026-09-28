"""Ramp-aware shading, tested against a real Aseprite.

The point of these is the palette-conformance assertion: it is what separates a shading
operation from an image filter, and it is objective. Everything else about whether
shading looks good needs a person.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, effects, inspect, palette, shading, sprite

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
