"""Tools that read the layer they draw on, on a Background: requires Aseprite.

The writes were fixed first: on an indexed Background the transparent index is a colour
Aseprite draws, and drawing tools learned to paint it (test_background_writes.py). The
*reads* were not. `img_solid`, which effects use to ask "is anything drawn here?", still
decoded that index as empty, so on the same scene an indexed Background and an RGB one
were treated differently. Measured before the fix, on a 14x14 scene:

* `fill_gradient` with `respect_alpha` wrote 9 of 196 pixels on the indexed Background,
  skipping the whole sky as if it were transparent, and all 196 on the RGB one.
* `remove_stray_pixels` left 3 of 4 lone stars on the indexed Background and recoloured
  all 4 on the RGB one.
* `add_outline` laid 20 pixels of the background's own colour over itself and reported
  them written, and on an RGB Background returned ok having written nothing.

The property held here is the one that decides it: the same scene, as an RGB Background
and as an indexed one, comes out the same. The two guards matter as much: an ordinary
layer above an indexed Background keeps its transparency, which is what proves the fix
reads the Background image alone, and the way out the outline refusal names does work.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import drawing, effects, inspect, layers, shading, sprite

SKY, STAR, RED = "#101828", "#f0e070", "#c04040"
STARS = [(2, 2), (9, 3), (5, 8), (11, 10)]


def _scene(name: str, *, indexed: bool) -> str:
    """A 14x14 night sky with four lone stars and a red block, as a Background."""
    sprite.create_sprite(name, 14, 14, overwrite=True)
    drawing.fill_layer(name, SKY)
    drawing.draw_pixels(name, [{"x": x, "y": y} for x, y in STARS], STAR)
    drawing.draw_rectangle(name, 6, 4, 3, 3, RED, filled=True)
    sprite.convert_layer_to_background(name, "Layer 1")
    if indexed:
        sprite.set_color_mode(name, "indexed")
    return name


def _pixels(name: str) -> list[list[str]]:
    return inspect.get_pixels(name, 0, 0, 14, 14)["pixels"]


@pytest.mark.parametrize("indexed", [False, True], ids=["rgb", "indexed"])
def test_an_outline_on_a_background_is_refused_and_writes_nothing(indexed):
    name = _scene(f"br/outline_{indexed}.aseprite", indexed=indexed)
    before = _pixels(name)
    with pytest.raises(AsepriteError, match="is a Background, where every pixel is drawn"):
        effects.add_outline(name, "#000000", layer="Background")
    assert _pixels(name) == before


def test_the_way_out_the_refusal_names_works_on_an_indexed_sprite():
    """convert_background_to_layer turns the transparent index back into transparency,
    and the outline then goes round the art: the sky's index is the empty space."""
    name = _scene("br/converted.aseprite", indexed=True)
    sprite.convert_background_to_layer(name)
    result = effects.add_outline(name, "#000000", layer=1)
    assert result["pixels_written"] > 0


def test_a_gradient_that_respects_alpha_covers_an_indexed_background_entirely():
    written = {}
    for indexed in (False, True):
        name = _scene(f"br/gradient_{indexed}.aseprite", indexed=indexed)
        written[indexed] = effects.fill_gradient(
            name, ["#000000", "#ffffff"], layer="Background",
            respect_alpha=True)["pixels_written"]
    assert written == {False: 196, True: 196}


def test_stray_pixels_on_a_background_are_judged_alike_in_either_mode():
    after = {}
    for indexed in (False, True):
        name = _scene(f"br/stray_{indexed}.aseprite", indexed=indexed)
        effects.remove_stray_pixels(name, layer="Background")
        after[indexed] = _pixels(name)
    assert after[True] == after[False]
    assert all(after[True][y][x] != STAR + "ff" for x, y in STARS)


def test_a_layer_above_an_indexed_background_keeps_its_transparency():
    """The fix must read the Background image alone: on an ordinary layer the transparent
    index is still nothing, so an outline there goes round the art and nowhere else."""
    name = _scene("br/above.aseprite", indexed=True)
    layers.add_layer(name, "art")
    drawing.draw_rectangle(name, 1, 1, 2, 2, RED, filled=True, layer="art")
    result = effects.add_outline(name, "#000000", layer="art", connectivity=4)
    assert result["pixels_written"] == 8


# --- the same, for the tools that read a pixel's colour, not only whether it is drawn ---


def test_replace_color_finds_an_indexed_backgrounds_own_colour():
    """Recolouring a converted scene's sky did nothing: the sky is the transparent
    index, which read as (0, 0, 0, 0) and so never matched the colour asked for. The
    target colour is one the palette holds, so both modes can draw it exactly."""
    after = {}
    for indexed in (False, True):
        name = _scene(f"br/replace_{indexed}.aseprite", indexed=indexed)
        effects.replace_color(name, SKY, STAR, layer="Background")
        after[indexed] = _pixels(name)
    assert after[True] == after[False]
    assert after[True][0][0] == STAR + "ff"


def test_a_ramp_map_covers_an_indexed_background_alike():
    """Both ramp colours are already in the palette, so the two modes can only differ by
    which pixels the map reads, which is the question. The ramp starts at red rather than
    at the sky's own colour on purpose: mapped from a ramp that began with SKY, the dark
    sky lands on SKY whether it was read or skipped, and the test passed on the bug."""
    after = {}
    for indexed in (False, True):
        name = _scene(f"br/gmap_{indexed}.aseprite", indexed=indexed)
        shading.gradient_map(name, [RED, STAR], layer="Background")
        after[indexed] = _pixels(name)
    assert after[True] == after[False]
    assert after[True][0][0] == RED + "ff"


def test_a_filter_reaches_every_pixel_of_an_indexed_background():
    written = {}
    for indexed in (False, True):
        name = _scene(f"br/invert_{indexed}.aseprite", indexed=indexed)
        written[indexed] = effects.invert_colors(name, layer="Background")["pixels_written"]
    assert written == {False: 196, True: 196}
