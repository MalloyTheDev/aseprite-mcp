"""ramp_between and ramp_from_art against real sprites: requires Aseprite (--run-aseprite).

The arithmetic is tested in test_ramps.py. What needs an editor is the round trip: a ramp
built from two ends, painted into a sprite, recovered from that sprite, and then handed
back to a shading tool, which is the whole reason either tool exists.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, inspect, layers, palette, shading, sprite

SHADOW, LIGHT = "#1b2a52", "#ffe9c4"


def _sphere(request, ramp: list[str], suffix: str = "") -> str:
    name = f"rt/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse_in_box(name, 3, 3, 26, 26, ramp[len(ramp) // 2], filled=True)
    shading.shade_region_by_light(name, ramp, light_angle=125, rim=0.2, ambient=0.25)
    return name


# ------------------------------------------------------------------------ the round trip
def test_a_ramp_survives_being_painted_and_read_back(request):
    built = palette.ramp_between(SHADOW, LIGHT, steps=5)["colors"]
    name = _sphere(request, built)

    found = palette.ramp_from_art(name)

    assert set(found["colors"]) <= set(built), "every step must be a colour in the art"
    assert len(found["colors"]) >= 3
    assert sum(found["coverage"]) == pytest.approx(1.0, abs=0.01)


def test_a_recovered_ramp_can_be_shaded_with(request):
    """The point of recovering one: an agent handed somebody else's sprite can carry on
    working in its colours."""
    built = palette.ramp_between(SHADOW, LIGHT, steps=5)["colors"]
    name = _sphere(request, built)
    found = palette.ramp_from_art(name)["colors"]

    shading.shift_along_ramp(name, found, steps=-1)

    metrics = inspect.assess_sprite(name, ramp=found)["metrics"]
    assert metrics["palette_conformance"] == 1.0


def test_the_ends_are_the_colours_that_were_asked_for():
    built = palette.ramp_between(SHADOW, LIGHT, steps=6)
    assert built["colors"][0] == SHADOW
    assert built["colors"][-1] == LIGHT
    assert len(built["colors"]) == 6


def test_a_built_ramp_can_be_written_into_the_palette(request):
    name = f"rt/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)

    built = palette.ramp_between(SHADOW, LIGHT, steps=4, filename=name, apply="replace")

    assert built["applied"]["size"] == 4
    assert [c[:7] for c in palette.get_palette(name)["colors"]] == built["colors"]


# --------------------------------------------------------------------------- scoping
def test_a_layer_scopes_the_read_past_another_material(request):
    """Two materials on one sprite is the case the warning is for, and naming a layer is
    the answer it suggests."""
    built = palette.ramp_between(SHADOW, LIGHT, steps=5)["colors"]
    name = _sphere(request, built)
    layers.add_layer(name, "banner")
    drawing.draw_rectangle(name, 0, 0, 32, 6, "#c03030", filled=True, layer="banner")
    drawing.draw_rectangle(name, 0, 6, 32, 6, "#8a1f1f", filled=True, layer="banner")

    scoped = palette.ramp_from_art(name, layer="Layer 1")

    assert set(scoped["colors"]) <= set(built)
    assert not any("several materials" in w for w in scoped["warnings"])


def test_art_with_two_materials_says_so(request):
    name = f"rt/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_rectangle(name, 0, 0, 16, 32, "#c03030", filled=True)
    drawing.draw_rectangle(name, 16, 0, 16, 32, "#3060c0", filled=True)

    found = palette.ramp_from_art(name, steps=2)

    assert any("several materials" in w for w in found["warnings"])


def test_an_empty_frame_says_nothing_is_drawn(request):
    name = f"rt/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)

    found = palette.ramp_from_art(name)

    assert found["colors"] == []
    assert found["warnings"] == ["Nothing is drawn here."]


# --------------------------------------------------- refused before Aseprite is launched
def test_a_single_step_ramp_is_refused():
    with pytest.raises(ValidationFailed, match="minimum is 2"):
        palette.ramp_between(SHADOW, LIGHT, steps=1)


def test_an_unknown_easing_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="perceptual"):
        palette.ramp_between(SHADOW, LIGHT, easing="smooth")


def test_applying_without_a_file_is_refused():
    with pytest.raises(ValidationFailed, match="filename is required"):
        palette.ramp_between(SHADOW, LIGHT, apply="replace")
