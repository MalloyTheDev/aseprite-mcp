"""Drawing on a grayscale sprite: requires Aseprite (--run-aseprite).

Both grayscale paths in the prelude averaged the channels. Aseprite converts with Rec.709
luma, so the two disagreed for every colour that is not already grey, and the same art
came out differently depending on the route: drawn onto a grayscale sprite, or drawn in
RGB and converted with `set_color_mode("gray")`.

An average also cannot tell apart colours whose channels sum alike, which is the part
that loses work rather than merely shifting it. Pure red, green and blue each sum to 255,
so all three landed on 85 and became one tone; yellow and cyan both landed on 170.

Grayscale had no tests at all before this file, which is how it went unnoticed. The
property every test here turns on is the one that was broken: **drawn equals converted.**
Raw grey values are read off the cel rather than through `get_pixels`, because the
question is which value was stored.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.runner import run_lua
from aseprite_mcp.tools import drawing, sprite
from aseprite_mcp.tools.common import lua_path, resolve_path

# Hues an average cannot tell apart (each row sums alike), then the ends and a grey.
COLORS = ["#ff0000", "#00ff00", "#0000ff",   # all sum to 255: one tone under an average
          "#ffff00", "#00ffff", "#ff00ff",   # all sum to 510: one tone under an average
          "#ffffff", "#000000", "#808080", "#1b2b4a", "#c89a62"]

_VALUES = """
local spr = app.open(ARG.src)
local cel = spr.layers[1]:cel(1)
local out = {}
for i = 0, ARG.n - 1 do
  local px = cel.image:getPixel(i - cel.position.x, -cel.position.y)
  out[#out + 1] = app.pixelColor.grayaV(px)
end
RESULT = { values = out, gray = (spr.colorMode == ColorMode.GRAY) }
"""


def _strip(name: str, colors: list[str], *, mode: str) -> str:
    sprite.create_sprite(name, len(colors), 1, color_mode=mode, overwrite=True)
    for i, colour in enumerate(colors):
        drawing.draw_pixels(name, [{"x": i, "y": 0}], colour)
    return name


def _greys(name: str, count: int) -> list[int]:
    read = run_lua(_VALUES, {"src": lua_path(resolve_path(name)), "n": count})
    assert read["gray"] is True, "the sprite under test is not grayscale"
    return read["values"]


def _drawn(name: str, colors: list[str] = COLORS) -> list[int]:
    return _greys(_strip(name, colors, mode="gray"), len(colors))


def _converted(name: str, colors: list[str] = COLORS) -> list[int]:
    sprite.set_color_mode(_strip(name, colors, mode="rgb"), "gray")
    return _greys(name, len(colors))


def test_a_colour_drawn_on_a_grayscale_sprite_is_the_one_aseprite_converts_it_to():
    """The property the fix exists for. Checked per colour so a failure names which."""
    drawn = _drawn("gy/drawn.aseprite")
    converted = _converted("gy/converted.aseprite")
    assert dict(zip(COLORS, drawn, strict=True)) == dict(zip(COLORS, converted, strict=True))


def test_colours_an_average_cannot_tell_apart_stay_apart():
    """Each triple sums alike, so an average gave all three one tone."""
    drawn = dict(zip(COLORS, _drawn("gy/distinct.aseprite"), strict=True))
    assert len({drawn["#ff0000"], drawn["#00ff00"], drawn["#0000ff"]}) == 3
    assert len({drawn["#ffff00"], drawn["#00ffff"], drawn["#ff00ff"]}) == 3
    # Green carries most of the light and blue almost none: the ordering, not just the
    # count, so a formula that separated them wrongly would still fail here.
    assert drawn["#00ff00"] > drawn["#ff0000"] > drawn["#0000ff"]


def test_the_ends_are_exact():
    """White is the case that says the weights are integers: in floating point the three
    coefficients fall a hair short of 1, and white came out 254."""
    drawn = dict(zip(COLORS, _drawn("gy/ends.aseprite"), strict=True))
    assert drawn["#ffffff"] == 255
    assert drawn["#000000"] == 0


@pytest.mark.parametrize("value", [0, 1, 64, 128, 199, 254, 255])
def test_a_grey_drawn_on_a_grayscale_sprite_keeps_its_value(value):
    """The guard that must not move: the weights sum to one, so a grey is itself."""
    hexed = f"#{value:02x}{value:02x}{value:02x}"
    assert _drawn(f"gy/grey_{value}.aseprite", [hexed]) == [value]


def test_a_ramp_keeps_all_of_its_steps():
    """A guard, not a pin: this ramp climbs enough in lightness to survive an average
    too, so it passes on the code before the fix. It is here because it is the shape of
    the practical failure (a shading ramp arriving with fewer steps than it was given)
    and nothing else would notice a future change that reintroduced it."""
    ramp = ["#591e16", "#962526", "#ce3a4c", "#dd778f", "#ecb5c8"]
    drawn = _drawn("gy/ramp.aseprite", ramp)
    assert len(set(drawn)) == len(ramp)
    assert drawn == sorted(drawn), "a ramp that climbs in lightness has to climb in grey"


def test_desaturating_all_the_way_lands_on_the_grey_the_conversion_gives():
    """Three formulas lived here: an average on both drawing paths, Rec.601 in
    `desaturate`, and Aseprite's Rec.709 in the conversion. A colour taken all the way to
    grey by either route now arrives at the same tone."""
    from aseprite_mcp.tools import effects, inspect

    name = _strip("gy/desaturated.aseprite", COLORS, mode="rgb")
    effects.desaturate(name, amount=100)
    desaturated = [px[1:3] for px in inspect.get_pixels(name, 0, 0, len(COLORS), 1)["pixels"][0]]
    converted = [f"{value:02x}" for value in _converted("gy/forconvert.aseprite")]
    assert desaturated == converted
