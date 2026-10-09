"""What a Background is filled with where it gains a pixel: requires Aseprite (--run-aseprite).

Every such fill (converting a layer to a Background, growing a Background's canvas) came
from the editor's colour bar, which is user state a headless run inherits: on the machine
this was found on, a purple at alpha 186, and on an indexed sprite a palette entry that did
not exist. The same call gave a different file on every machine. Every script now starts
from Aseprite's factory colours, and an indexed fill is the transparent index, which a
Background shows as that entry's colour.

Note for whoever runs these: an editor whose background colour is already black passes
the RGB cases without the fix, so they prove it only where the colour bar says otherwise.
"""

from __future__ import annotations

import pytest
from PIL import Image

from aseprite_mcp.core.runner import run_lua
from aseprite_mcp.tools import drawing, export, inspect, palette, sprite
from aseprite_mcp.tools.common import lua_path, resolve_path

DARK, RED, WHITE = "#0a141e", "#c80000", "#ffffff"

_RAW = """
local spr = app.open(ARG.src)
local layer = nil
for _, lyr in ipairs(spr.layers) do if lyr.name == ARG.layer then layer = lyr end end
local cel = layer:cel(1)
local out = {}
for y = 0, spr.height - 1 do
  local row = {}
  for x = 0, spr.width - 1 do
    local cx, cy = x - cel.position.x, y - cel.position.y
    if cx >= 0 and cy >= 0 and cx < cel.image.width and cy < cel.image.height then
      row[#row + 1] = cel.image:getPixel(cx, cy)
    else
      row[#row + 1] = -1
    end
  end
  out[#out + 1] = row
end
RESULT = { rows = out, background = layer.isBackground, transparent = spr.transparentColor }
"""


def _raw(name: str, layer: str = "Background") -> dict:
    return run_lua(_RAW, {"src": lua_path(resolve_path(name)), "layer": layer})


def test_every_script_starts_from_the_factory_colours():
    """Whatever the editor last left in its colour bar."""
    seen = run_lua("""
    RESULT = { bg = { app.bgColor.red, app.bgColor.green, app.bgColor.blue, app.bgColor.alpha },
               fg = { app.fgColor.red, app.fgColor.green, app.fgColor.blue, app.fgColor.alpha } }
    """, {})

    assert seen == {"bg": [0, 0, 0, 255], "fg": [255, 255, 255, 255]}


def test_converting_an_rgb_layer_fills_with_black():
    name = "bf/convert_rgb.aseprite"
    sprite.create_sprite(name, 4, 4, overwrite=True)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], RED)
    sprite.convert_layer_to_background(name, "Layer 1")

    rows = inspect.get_pixels(name)["pixels"]
    assert rows[0][0] == "#000000ff"
    assert rows[1][1] == RED + "ff"


def test_converting_an_indexed_layer_keeps_every_index():
    """The transparent pixels keep the transparent index, which the Background now shows
    as that entry's colour; no entry is invented and none changes."""
    name = "bf/convert_indexed.aseprite"
    sprite.create_sprite(name, 4, 4, color_mode="indexed", overwrite=True)
    palette.set_palette(name, [DARK, RED, WHITE])
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], RED, layer="Layer 1")
    sprite.convert_layer_to_background(name, "Layer 1")

    raw = _raw(name)
    assert raw["background"] is True
    assert raw["rows"][0][0] == raw["transparent"] == 0
    assert raw["rows"][1][1] == 1
    assert inspect.get_pixels(name, 0, 0, 1, 1)["pixels"][0][0] == DARK + "ff"


def _green_background(name: str) -> str:
    png = name.replace(".aseprite", ".png")
    Image.new("RGB", (4, 4), (10, 200, 30)).save(resolve_path(png))
    export.import_image(png, name, overwrite=True)
    return name


@pytest.mark.parametrize("grow", ["resize_canvas", "crop_sprite"])
def test_growing_a_background_fills_the_new_area_with_black(grow):
    name = _green_background(f"bf/grow_{grow}.aseprite")
    if grow == "resize_canvas":
        sprite.resize_canvas(name, 6, 6)
    else:
        sprite.crop_sprite(name, 0, 0, 6, 6)

    rows = inspect.get_pixels(name)["pixels"]
    assert rows[0][0] == "#0ac81eff", "the old area moved"
    assert rows[5][5] == "#000000ff"


def test_growing_an_indexed_background_fills_with_the_transparent_index():
    name = "bf/grow_indexed.aseprite"
    sprite.create_sprite(name, 4, 4, color_mode="indexed", overwrite=True)
    palette.set_palette(name, [DARK, RED, WHITE])
    sprite.convert_layer_to_background(name, "Layer 1")
    drawing.fill_layer(name, RED, layer="Background")
    sprite.resize_canvas(name, 6, 6)

    raw = _raw(name)
    assert raw["rows"][0][0] == 1
    assert raw["rows"][5][5] == raw["transparent"] == 0
