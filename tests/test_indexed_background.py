"""An indexed Background is opaque, and is now read as Aseprite draws it: requires Aseprite.

On an indexed sprite the transparent palette index means "no pixel" on an ordinary layer,
and every reader here decoded it that way on a Background too, where Aseprite draws it as
a colour. `get_pixels` returned a whole background as #00000000, `extract_palette` left the
background colour out, and the indexed conversion guard refused an opaque scene as losing
60 of its 64 pixels when it would have lost none.

The truth every test is held to is Aseprite's own RGB render of the same file, read in the
same process, rather than a colour this file computes: a Background is drawn over its
transparent index's colour, so a palette entry that is itself transparent shows that
colour there and a half-transparent one blends with it, and only the render gets every
case right.
"""

from __future__ import annotations

import pytest
from PIL import Image

from aseprite_mcp.core.runner import run_lua
from aseprite_mcp.tools import export, inspect, palette, sprite
from aseprite_mcp.tools.common import lua_path, resolve_path

# Index 0 is the transparent index and an opaque colour; 2 is an entry that is itself
# transparent; 3 is half transparent. Row 0 of the Background holds 0, 1, 2, 3 and row 1
# is all index 0. An ordinary layer above holds index 4 (white) at (0, 1) and nothing else.
_BUILD = """
local spr = Sprite(4, 2, ColorMode.INDEXED)
local pal = Palette(5)
pal:setColor(0, Color{ r = 10, g = 20, b = 30, a = 255 })
pal:setColor(1, Color{ r = 200, g = 0, b = 0, a = 255 })
pal:setColor(2, Color{ r = 0, g = 200, b = 0, a = 0 })
pal:setColor(3, Color{ r = 0, g = 0, b = 200, a = 128 })
pal:setColor(4, Color{ r = 255, g = 255, b = 255, a = 255 })
spr:setPalette(pal)
spr.transparentColor = 0
app.bgColor = Color{ index = 0 }
app.command.BackgroundFromLayer()
local bg = spr.layers[1]
local img = bg:cel(1).image:clone()
for x = 0, 3 do img:drawPixel(x, 0, x) end
for x = 0, 3 do img:drawPixel(x, 1, ARG.row1) end
bg:cel(1).image = img
local top = spr:newLayer()
top.name = "top"
local timg = Image(spr.spec)
timg:clear()
timg:drawPixel(0, 1, 4)
spr:newCel(top, 1, timg, Point(0, 0))
spr:saveAs(ARG.dst)
RESULT = { ok = true }
"""

_RENDER = """
local spr = app.open(ARG.src)
if ARG.only ~= nil then
  for _, lyr in ipairs(spr.layers) do lyr.isVisible = (lyr.name == ARG.only) end
end
local img = Image(spr.width, spr.height, ColorMode.RGB)
img:clear()
img:drawSprite(spr, 1)
local rows = {}
for y = 0, spr.height - 1 do
  local row = {}
  for x = 0, spr.width - 1 do
    local p = img:getPixel(x, y)
    row[#row + 1] = string.format("#%02x%02x%02x%02x", app.pixelColor.rgbaR(p),
      app.pixelColor.rgbaG(p), app.pixelColor.rgbaB(p), app.pixelColor.rgbaA(p))
  end
  rows[#rows + 1] = row
end
RESULT = { rows = rows }
"""

BASE = "#0a141eff"   # the transparent index's colour, which the Background is drawn over
COMPOSITE = [[BASE, "#c80000ff", BASE, "#050a73ff"],
             ["#ffffffff", BASE, BASE, BASE]]


def _built(name: str, row1: int = 0) -> str:
    run_lua(_BUILD, {"dst": lua_path(resolve_path(name)), "row1": row1})
    return name


def _render(name: str, only: str | None = None) -> list[list[str]]:
    return run_lua(_RENDER, {"src": lua_path(resolve_path(name)), "only": only})["rows"]


def test_the_composite_reads_as_aseprite_draws_it():
    name = _built("ib/composite.aseprite")

    assert _render(name) == COMPOSITE, "the fixture or Aseprite's render moved"
    assert inspect.get_pixels(name)["pixels"] == COMPOSITE


def test_a_background_read_alone_reads_as_drawn():
    name = _built("ib/alone.aseprite")
    alone = _render(name, only="Background")

    assert alone == [[BASE, "#c80000ff", BASE, "#050a73ff"], [BASE] * 4]
    assert inspect.get_pixels(name, layer="Background")["pixels"] == alone


def test_an_ordinary_layer_still_reads_the_transparent_index_as_nothing():
    """The other half of the rule, which must not move: #138's reading stands everywhere
    but on a Background."""
    name = _built("ib/ordinary.aseprite")
    rows = inspect.get_pixels(name, layer="top")["pixels"]

    assert rows[1][0] == "#ffffffff"
    assert rows[1][1] == "#00000000"


def test_reading_a_background_alone_puts_every_layer_back():
    """`readable_layer` hides the other layers to render the Background, in memory. A tool
    that read a Background and then saved must not save them hidden."""
    name = _built("ib/restore.aseprite")
    seen = run_lua("""
    local spr = app.open(ARG.src)
    local function flags()
      local out = {}
      for i, lyr in ipairs(spr.layers) do out[i] = lyr.isVisible end
      return out
    end
    local before = flags()
    readable_layer(spr, spr.layers[1], 1)
    RESULT = { before = before, after = flags() }
    """, {"src": lua_path(resolve_path(name))})

    assert seen["after"] == seen["before"] == [True, True]


def test_assess_counts_every_pixel_of_an_opaque_sprite():
    name = _built("ib/assess.aseprite")
    metrics = inspect.assess_sprite(name)["metrics"]

    assert metrics["drawn_pixels"] == 8
    assert metrics["bbox"] == [0, 0, 3, 1]


def test_a_changed_background_pixel_is_a_change_not_an_addition():
    """Index 0 to index 1 on the Background. Read as "nothing" before, the pixel looked
    added, and both sprites looked mostly empty."""
    a = _built("ib/diff_a.aseprite")
    b = _built("ib/diff_b.aseprite", row1=1)
    result = inspect.diff_sprites(a, other=b)

    metrics = result["metrics"]
    assert result["a"]["drawn_pixels"] == result["b"]["drawn_pixels"] == 8
    assert metrics["changed_pixels"] == 3   # (1,1), (2,1), (3,1); (0,1) is under the white
    assert metrics["silhouette_added"] == metrics["silhouette_removed"] == 0


def test_extract_palette_includes_the_background_colour():
    name = _built("ib/extract.aseprite")
    colours = palette.extract_palette(name, set_as_palette=False)["colors"]

    assert BASE in colours


def test_palette_usage_counts_the_background_transparent_index_as_drawn():
    """Per pixel, not per index: index 0 draws five times on the Background and nothing on
    the layer above, where it is the transparent index doing its usual job."""
    name = _built("ib/usage.aseprite")
    used = {entry["index"]: entry["pixels"] for entry in palette.list_palette_usage(name)["used"]}

    assert used == {0: 5, 1: 1, 2: 1, 3: 1, 4: 1}


def _opaque_scene(name: str) -> str:
    img = Image.new("RGB", (8, 8), (20, 12, 28))
    img.paste((200, 40, 40), (3, 3, 5, 5))
    img.save(resolve_path(name))
    return name


def test_an_opaque_scene_converts_to_indexed_and_keeps_its_pixels():
    """The pipeline this blocked: an opaque PNG imported (it arrives as a Background) and
    palette-limited. The guard counted the dark background, which lands on index 0, as 60
    lost pixels and refused; nothing was lost."""
    _opaque_scene("ib/scene.png")
    export.import_image("ib/scene.png", "ib/scene.aseprite", overwrite=True)
    before = inspect.get_pixels("ib/scene.aseprite")["pixels"]

    result = sprite.set_color_mode("ib/scene.aseprite", "indexed")

    assert result["colorMode"] == "indexed"
    assert result["drawn_pixels"] == 64
    assert inspect.get_pixels("ib/scene.aseprite")["pixels"] == before


@pytest.mark.parametrize("mode", ["rgb", "indexed"])
def test_trim_treats_an_opaque_background_alike_in_both_modes(mode):
    """A Background is the opaque surface it is on screen in either mode. Indexed, the
    margins in the transparent index's colour used to count as empty and were cropped."""
    name = f"ib/trim_{mode}.aseprite"
    _opaque_scene(f"ib/trim_{mode}.png")
    export.import_image(f"ib/trim_{mode}.png", name, overwrite=True)
    if mode == "indexed":
        sprite.set_color_mode(name, "indexed")

    result = sprite.trim_sprite(name)

    assert (result["width"], result["height"]) == (8, 8)
