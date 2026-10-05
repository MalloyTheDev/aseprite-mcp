"""Drawing onto an indexed Background: requires Aseprite (--run-aseprite).

A colour equal to the transparent palette index's resolved to the nearest *other* entry
even on a Background, where Aseprite draws that index as a colour: `fill_layer` with a
Background's own dark colour, index 0 here, painted it in another entry and reported ok.
On an ordinary layer the exclusion is right and stays (#138): there the index is
invisible.

Indices are read raw where the question is which entry was written, because two entries
can look alike; colours are read through `get_pixels` where the question is what shows.
"""

from __future__ import annotations

from aseprite_mcp.core.runner import run_lua
from aseprite_mcp.tools import batch, drawing, inspect, layers, palette, sprite
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


def _indexed_background(name: str) -> str:
    """4x4 indexed, palette dark (the transparent index), red, white, and one Background."""
    sprite.create_sprite(name, 4, 4, color_mode="indexed", overwrite=True)
    palette.set_palette(name, [DARK, RED, WHITE])
    sprite.convert_layer_to_background(name, "Layer 1")
    return name


def test_the_transparent_index_colour_is_drawable_on_a_background():
    name = _indexed_background("bw/fill.aseprite")
    drawing.fill_layer(name, RED, layer="Background")
    drawing.fill_layer(name, DARK, layer="Background")

    raw = _raw(name)
    assert raw["background"] is True
    assert raw["rows"] == [[0] * 4] * 4, "the dark fill landed on another entry"
    assert inspect.get_pixels(name, 0, 0, 1, 1)["pixels"][0][0] == DARK + "ff"


def test_an_ordinary_layer_still_cannot_be_drawn_in_the_transparent_index():
    """#138's rule, which must not move: there the index is invisible, so the nearest
    other entry is the only colour that shows."""
    name = _indexed_background("bw/ordinary.aseprite")
    layers.add_layer(name, "top")
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], DARK, layer="top")

    assert _raw(name, "top")["rows"][1][1] not in (0, -1)


def test_a_batch_names_its_target_per_operation():
    """The Background op may use the transparent index; the next op, on an ordinary layer,
    must not inherit that."""
    name = _indexed_background("bw/batch.aseprite")
    layers.add_layer(name, "top")
    batch.apply_operations(name, [
        {"op": "fill_rectangle", "args": {"layer": "Background", "x": 0, "y": 0,
                                          "width": 4, "height": 4, "color": RED}},
        {"op": "fill_rectangle", "args": {"layer": "Background", "x": 0, "y": 0,
                                          "width": 2, "height": 2, "color": DARK}},
        {"op": "set_pixel", "args": {"layer": "top", "x": 3, "y": 3, "color": DARK}},
    ])

    assert _raw(name)["rows"][0][:2] == [0, 0]
    assert _raw(name, "top")["rows"][3][3] not in (0, -1)
