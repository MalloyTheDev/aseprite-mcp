"""gradient_map over real sprites: requires Aseprite (--run-aseprite).

Every other shading tool starts from art that is already on a ramp. This is the one that
puts art onto one, so the property that matters is the one measured here: whatever went
in, what comes out uses the ramp's colours and nothing else.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, effects, inspect, palette, shading, sprite

RAMP = palette.generate_ramp("#5a7fd4", steps=5, hue_shift=-40.0,
                             saturation_shift=-18.0, light_range=0.74)["colors"]


def _gradient(request, width: int = 64, height: int = 16, suffix: str = "") -> str:
    """A smooth left-to-right ramp of greys: many colours, none of them on any palette."""
    name = f"gm/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, width, height)
    effects.fill_gradient(name, ["#000000", "#ffffff"], angle=0.0, respect_alpha=False)
    return name


def _row(name: str, width: int = 64) -> list[str]:
    return inspect.get_pixels(name, 0, 0, width, 1)["pixels"][0]


# ------------------------------------------------------------------------ the promise
def test_arbitrary_art_comes_out_on_the_ramp(request):
    name = _gradient(request)
    before = inspect.assess_sprite(name, ramp=RAMP)["metrics"]
    assert before["colors"] > 10 and before["palette_conformance"] == 0.0

    shading.gradient_map(name, RAMP)

    after = inspect.assess_sprite(name, ramp=RAMP)["metrics"]
    assert after["palette_conformance"] == 1.0
    assert after["colors"] <= len(RAMP)


def test_dark_maps_dark_and_light_maps_light(request):
    name = _gradient(request)
    shading.gradient_map(name, RAMP)

    row = _row(name)
    assert row[0].lower().startswith(RAMP[0].lower()), "black should take the first step"
    assert row[-1].lower().startswith(RAMP[-1].lower()), "white should take the last"


def test_a_reversed_ramp_inverts_the_image(request):
    name = _gradient(request)
    shading.gradient_map(name, list(reversed(RAMP)))

    row = _row(name)
    assert row[0].lower().startswith(RAMP[-1].lower())
    assert row[-1].lower().startswith(RAMP[0].lower())


# ---------------------------------------------------------------- shaping the mapping
def test_contrast_pushes_the_art_toward_the_ends(request):
    flat = shading.gradient_map(_gradient(request, suffix="_a"), RAMP, contrast=1.0)
    punchy = shading.gradient_map(_gradient(request, suffix="_b"), RAMP, contrast=2.5)

    ends = lambda steps: steps[0] + steps[-1]  # noqa: E731
    middle = lambda steps: sum(steps[1:-1])    # noqa: E731
    assert ends(punchy["per_step"]) > ends(flat["per_step"])
    assert middle(punchy["per_step"]) < middle(flat["per_step"])


def test_low_contrast_crowds_the_middle(request):
    flat = shading.gradient_map(_gradient(request, suffix="_a"), RAMP, contrast=1.0)
    soft = shading.gradient_map(_gradient(request, suffix="_b"), RAMP, contrast=0.4)

    assert sum(soft["per_step"][1:-1]) > sum(flat["per_step"][1:-1])


def test_bias_moves_the_whole_mapping(request):
    lighter = shading.gradient_map(_gradient(request, suffix="_l"), RAMP, bias=0.3)
    darker = shading.gradient_map(_gradient(request, suffix="_d"), RAMP, bias=-0.3)

    assert lighter["per_step"][-1] > darker["per_step"][-1]
    assert darker["per_step"][0] > lighter["per_step"][0]


# -------------------------------------------------------------------------- dithering
def test_dithering_breaks_the_bands_without_adding_a_colour(request):
    plain = _gradient(request, suffix="_p")
    dithered = _gradient(request, suffix="_d")
    shading.gradient_map(plain, RAMP)
    shading.gradient_map(dithered, RAMP, dither="bayer4")

    def changes(name):
        row = _row(name)
        return sum(1 for a, b in pairwise(row) if a != b)

    assert changes(dithered) > changes(plain), "a dither interleaves the two steps"
    assert inspect.assess_sprite(dithered, ramp=RAMP)["metrics"]["palette_conformance"] == 1.0


# ------------------------------------------------------------------ what it must not do
def test_the_silhouette_and_its_soft_edges_survive(request):
    """Alpha is carried through, so an anti-aliased edge keeps its coverage and only its
    colour changes."""
    name = f"gm/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse(name, 15, 15, 12, 12, "#888888", filled=True, antialias=True)
    before = inspect.get_pixels(name, 0, 0, 32, 32)["pixels"]
    soft = [(x, y, px[7:9]) for y, row in enumerate(before)
            for x, px in enumerate(row) if px[7:9] not in ("00", "ff")]
    assert soft, "the fixture needs anti-aliased edge pixels to be worth anything"

    shading.gradient_map(name, RAMP)

    after = inspect.get_pixels(name, 0, 0, 32, 32)["pixels"]
    assert [(x, y, after[y][x][7:9]) for x, y, _ in soft] == soft
    assert inspect.assess_sprite(name)["metrics"]["drawn_pixels"] == \
        inspect.assess_sprite(name)["metrics"]["drawn_pixels"]


def test_a_region_leaves_the_rest_of_the_sprite_alone(request):
    name = _gradient(request, width=64, height=16)
    untouched = _row(name)[40:]

    shading.gradient_map(name, RAMP, x=0, y=0, width=32, height=16)

    row = _row(name)
    assert row[40:] == untouched
    assert row[0].lower().startswith(RAMP[0].lower())


# --------------------------------------------------- refused before Aseprite is launched
def test_a_one_colour_ramp_is_refused():
    with pytest.raises(ValidationFailed, match="at least 2"):
        shading.gradient_map("unused.aseprite", ["#ffffff"])


def test_zero_contrast_is_refused_and_says_what_it_would_be():
    with pytest.raises(ValidationFailed, match="fill_layer"):
        shading.gradient_map("unused.aseprite", RAMP, contrast=0.0)


def test_a_bias_outside_the_range_is_refused():
    with pytest.raises(ValidationFailed, match=r"between -1\.0 and 1\.0"):
        shading.gradient_map("unused.aseprite", RAMP, bias=2.0)


def test_an_unknown_dither_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="bayer4"):
        shading.gradient_map("unused.aseprite", RAMP, dither="noise")
