"""Indexed sprites against a real Aseprite (--run-aseprite): issues #137 and #138.

Both bugs were the same mistake approached from opposite ends. An indexed pixel is an
offset into a palette, one offset means "no pixel here", and both the tool that created a
palette and the tool that converted onto one were willing to answer a colour question
with that offset. Nothing failed: `draw_rectangle` reported sixteen pixels written onto a
new indexed sprite and left it blank, and `set_color_mode` reported ok having emptied the
sprite it was given.

`test_indexed.py` holds the part that is arithmetic. Everything here needs the editor,
because the question in every case is what Aseprite actually did to the pixels.

Each test that claims a refusal also checks the file on disk, since a refusal that has
already written half a conversion is not a refusal.
"""

from __future__ import annotations

import hashlib

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import drawing, frames, inspect, palette, sprite, tilemap
from aseprite_mcp.tools.common import resolve_path


def _name(request, suffix: str = "") -> str:
    """A workspace path unique to the running test, parametrised cases included."""
    stem = request.node.name.replace("[", "_").replace("]", "").replace("-", "_")
    return f"idx/{stem}{suffix}.aseprite"


def _digest(name: str) -> str:
    return hashlib.sha256(resolve_path(name).read_bytes()).hexdigest()


def _drawn(name: str, size: int, frame: int = 1) -> int:
    """Visible pixels, counted the slow obvious way through `get_pixels`."""
    rows = inspect.get_pixels(name, 0, 0, size, size, frame=frame)["pixels"]
    return sum(1 for row in rows for px in row if px[7:9] != "00")


# ============================================================== issue #138
# A freshly created indexed sprite could not be drawn on. Its palette was 256 entries of
# identical opaque black, so every entry was equidistant from every request and the first
# index won by being first; index 0 is the transparent index, so every draw landed and was
# invisible while reporting the pixels it had written.


def test_a_new_indexed_sprite_can_be_drawn_on_by_colour(request):
    """The reproduction from the issue, verbatim: sixteen pixels asked for, sixteen
    pixels there afterwards."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")

    result = drawing.draw_rectangle(name, 2, 2, 4, 4, "#ff0000", filled=True)

    assert result["pixels_written"] == 16
    assert _drawn(name, 8) == 16, "the pixels it reported writing are visible"
    assert inspect.get_pixels(name, 0, 0, 8, 8, format="map")["rows"][3] == "..aaaa.."


def test_a_new_indexed_sprite_has_a_palette_worth_drawing_with(request):
    """256 identical blacks is not a palette anybody asked for. Entry 0 is transparent
    because that is the index that means nothing is there, and black survives further up
    because an outline needs it."""
    name = _name(request)

    info = sprite.create_sprite(name, 8, 8, color_mode="indexed")

    assert info["paletteSize"] == 33
    colors = palette.get_palette(name)["colors"]
    assert colors[0] == "#00000000"
    assert "#000000ff" in colors[1:]
    assert len(set(colors[1:])) == 32, "32 distinct colours to draw with"


def test_two_different_colours_land_on_two_different_indices(request):
    """The symptom that made #138 look like a drawing bug rather than a palette one: with
    every entry the same colour, red and white resolved to the same index."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")

    drawing.draw_rectangle(name, 0, 0, 4, 8, "#ff0000", filled=True)
    drawing.draw_rectangle(name, 4, 0, 4, 8, "#ffffff", filled=True)

    left = inspect.get_pixels(name, 1, 1, 1, 1)["pixels"][0][0]
    right = inspect.get_pixels(name, 5, 1, 1, 1)["pixels"][0][0]
    assert left != right
    assert right == "#ffffffff", "white is in the palette exactly"


def test_a_background_colour_is_the_colour_that_was_asked_for(request):
    """An indexed sprite holds only the colours its palette names, so the requested
    background is added to the palette rather than approximated by the nearest default."""
    name = _name(request)

    sprite.create_sprite(name, 4, 4, color_mode="indexed", background="#1d2b53")

    assert inspect.get_pixels(name, 0, 0, 1, 1)["pixels"][0][0] == "#1d2b53ff"


def test_the_transparent_index_is_never_the_answer_to_a_colour(request):
    """The palette's nearest colour to the request *is* the transparent index, so a
    nearest-match that only measured distance would write an invisible pixel and report
    success. The second-nearest entry is the right answer: a visibly approximate pixel
    beats an invisible one that claims to be there."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    # Index 0 is the transparent index and is a dead ringer for the request; index 1 is
    # the only other entry and is nowhere near it.
    palette.set_palette(name, ["#fe0000ff", "#00ff00ff"])
    palette.set_transparent_color(name, 0)

    drawing.draw_rectangle(name, 2, 2, 4, 4, "#ff0000", filled=True)

    assert _drawn(name, 8) == 16
    assert inspect.get_pixels(name, 3, 3, 1, 1)["pixels"][0][0] == "#00ff00ff"


def test_a_transparent_palette_entry_is_never_the_answer_either(request):
    """Indexed transparency is two separate things: the transparent index, and an entry
    that is itself transparent. Both draw nothing, so neither answers a colour."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    # #fe000000 is the nearest entry to the request by RGB and is fully transparent.
    palette.set_palette(name, ["#00000000", "#fe000000", "#00ff00ff"])

    drawing.draw_rectangle(name, 2, 2, 4, 4, "#ff0000", filled=True)

    assert _drawn(name, 8) == 16
    assert inspect.get_pixels(name, 3, 3, 1, 1)["pixels"][0][0] == "#00ff00ff"


def test_a_palette_with_nothing_drawable_refuses_instead_of_writing_nothing(request):
    """When every entry is transparent there is no approximate answer, only the
    invisible one. Refusing names the tools that fix it; writing would not."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    palette.set_palette(name, ["#00000000", "#ffffff00"])
    before = _digest(name)

    with pytest.raises(AsepriteError) as err:
        drawing.draw_rectangle(name, 2, 2, 4, 4, "#ff0000", filled=True)

    message = str(err.value)
    assert "add_palette_color" in message and "set_palette" in message
    assert "#ff0000" in message, "the colour that could not be drawn is named"
    assert _digest(name) == before, "a refused draw leaves the file alone"


def test_erasing_on_an_indexed_sprite_still_uses_the_transparent_index(request):
    """The exclusion must not break the tools that mean to write nothing: a request for
    a transparent colour is answered with the transparent index, as before."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    drawing.draw_rectangle(name, 0, 0, 8, 8, "#ffffff", filled=True)

    drawing.draw_rectangle(name, 2, 2, 4, 4, "transparent", filled=True)

    rows = inspect.get_pixels(name, 0, 0, 8, 8, format="map")["rows"]
    assert rows[0] == "aaaaaaaa"
    assert rows[3] == "aa....aa", "the middle was erased, not painted"


def test_drawing_by_explicit_index_is_untouched(request):
    """`index:N` names the offset outright, so nothing resolves a colour and the
    transparent index stays reachable on purpose."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    palette.set_palette(name, ["#00000000", "#6b4a2fff"])

    drawing.draw_rectangle(name, 2, 2, 4, 4, "index:1", filled=True)

    assert _drawn(name, 8) == 16
    assert inspect.get_pixels(name, 3, 3, 1, 1)["pixels"][0][0] == "#6b4a2fff"


# ============================================================== issue #137
# Converting to indexed mapped the art against whatever palette the sprite was carrying.
# A saved RGB sprite carries a single transparent entry, so every pixel resolved to it and
# the art was gone, not remapped: there was no entry left for it to point at.


def test_converting_rgb_art_to_indexed_keeps_the_art(request):
    """The reproduction from the issue: sixteen drawn pixels before, sixteen after, and
    more than one palette entry."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 2, 2, 4, 4, "#6b4a2f", filled=True)
    assert _drawn(name, 8) == 16

    result = sprite.set_color_mode(name, "indexed")

    assert result["colorMode"] == "indexed"
    assert result["drawn_pixels"] == 16
    assert result["paletteSize"] > 1
    assert _drawn(name, 8) == 16


def test_the_converted_colour_is_the_colour_it_was(request):
    """A palette built from the art holds the art's own colours, so a conversion of a
    handful of flat colours is exact rather than approximate."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 2, 2, 4, 4, "#6b4a2f", filled=True)

    sprite.set_color_mode(name, "indexed")

    assert inspect.get_pixels(name, 3, 3, 1, 1)["pixels"][0][0] == "#6b4a2fff"
    assert palette.get_palette(name)["colors"] == ["#00000000", "#6b4a2fff"]


def test_every_frame_contributes_to_the_palette(request):
    """A palette is per sprite, not per frame, so quantizing only frame 1 would empty
    every other frame. This is the case a single-frame check cannot see."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    frames.add_frame(name)
    drawing.fill_layer(name, "#0ac81e", frame=1)
    drawing.fill_layer(name, "#c80adc", frame=2)

    sprite.set_color_mode(name, "indexed")

    assert inspect.get_pixels(name, 0, 0, 1, 1, frame=1)["pixels"][0][0] == "#0ac81eff"
    assert inspect.get_pixels(name, 0, 0, 1, 1, frame=2)["pixels"][0][0] == "#c80adcff"


def test_semi_transparent_art_survives_the_conversion(request):
    """Aseprite palettes carry per-entry alpha and the quantizer uses it, so
    anti-aliased edges convert instead of vanishing. Worth pinning: if they did vanish,
    the pixel-loss guard below would refuse every conversion of anti-aliased art."""
    name = _name(request)
    sprite.create_sprite(name, 16, 16)
    drawing.draw_line(name, 0, 1, 15, 6, "#ffffff", antialias=True)
    before = _drawn(name, 16)
    alphas_before = {
        px[7:9] for row in inspect.get_pixels(name, 0, 0, 16, 16)["pixels"] for px in row
    }
    assert any(a not in ("00", "ff") for a in alphas_before), "there are partial pixels"

    result = sprite.set_color_mode(name, "indexed")

    assert result["drawn_pixels"] == before
    assert _drawn(name, 16) == before


def test_a_conversion_that_would_empty_the_sprite_is_refused(request):
    """`palette_source="keep"` against the palette a saved RGB sprite carries is exactly
    what #137 did. It now refuses, names how many pixels were at stake, and leaves the
    file as it found it."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 2, 2, 4, 4, "#6b4a2f", filled=True)
    before = _digest(name)

    with pytest.raises(AsepriteError) as err:
        sprite.set_color_mode(name, "indexed", palette_source="keep")

    message = str(err.value)
    assert "16 of 16" in message, "the refusal names the actual numbers"
    assert "set_palette" in message and "from_art" in message
    assert _digest(name) == before, "the sprite on disk is untouched"
    assert inspect.get_sprite_info(name)["colorMode"] == "rgb", "still RGB"


def test_keeping_a_deliberate_palette_converts_against_it(request):
    """"keep" exists for the caller who built or loaded a palette on purpose. It has to
    work, or the refusal above would be the only thing it ever did."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 2, 2, 4, 4, "#6b4a2f", filled=True)
    palette.set_palette(name, ["#00000000", "#6b4a2fff", "#ffffffff"])

    result = sprite.set_color_mode(name, "indexed", palette_source="keep")

    assert result["drawn_pixels"] == 16
    assert result["paletteSize"] == 3, "the palette given was the palette used"
    assert inspect.get_pixels(name, 3, 3, 1, 1)["pixels"][0][0] == "#6b4a2fff"


def test_keeping_a_palette_can_merge_two_art_colours_into_one(request):
    """A recorded sharp edge rather than a fix. The palette here has two opaque entries,
    but one of them sits at the transparent index, so only one can show a pixel and both
    halves of the art snap onto it. Nothing is lost, in the sense the refusal guards:
    all 64 pixels are still visible, and half of them changed colour.

    Not refused, because snapping art onto a stated palette is exactly what "keep" is
    for; a conversion that refused whenever a colour moved would make the option useless.
    Pinned so that the behaviour is known rather than discovered, and because it is the
    case that shows what Aseprite's own mapper does: it avoids the transparent index too,
    which is the rule the prelude's `nearest_index` now follows."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 0, 0, 4, 8, "#000000", filled=True)
    drawing.draw_rectangle(name, 4, 0, 4, 8, "#ff0000", filled=True)
    # Index 0 is the transparent index on any indexed sprite, opaque entry or not.
    palette.set_palette(name, ["#000000ff", "#ff0000ff"])

    result = sprite.set_color_mode(name, "indexed", palette_source="keep")

    assert result["drawn_pixels"] == 64, "no pixel fell through the transparent index"
    left = inspect.get_pixels(name, 1, 1, 1, 1)["pixels"][0][0]
    right = inspect.get_pixels(name, 5, 1, 1, 1)["pixels"][0][0]
    assert left == right == "#ff0000ff", "black snapped onto the one usable entry"


def test_converting_an_indexed_sprite_to_indexed_keeps_its_palette(request):
    """Already indexed means the palette is the sprite's own. Re-quantizing would
    rebuild it from the art and discard entries nobody asked to lose."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    chosen = ["#00000000", "#112233ff", "#445566ff", "#778899ff"]
    palette.set_palette(name, chosen)
    drawing.draw_rectangle(name, 1, 1, 3, 3, "index:2", filled=True)

    result = sprite.set_color_mode(name, "indexed")

    assert result["drawn_pixels"] == 9
    assert palette.get_palette(name)["colors"] == chosen


def test_a_blank_sprite_converts_without_a_refusal(request):
    """No drawn pixels means none can be lost. The resulting palette has nothing to draw
    with, which is honest about an empty sprite and is what the draw-time refusal is
    for."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)

    result = sprite.set_color_mode(name, "indexed")

    assert result["colorMode"] == "indexed"
    assert result["drawn_pixels"] == 0


def test_a_sprite_with_a_tilemap_layer_converts(request):
    """A tilemap cel's pixels are tile indices rather than palette indices, so the
    conversion and the pixel count both have to leave them alone."""
    name = _name(request)
    sprite.create_sprite(name, 32, 32)
    drawing.draw_rectangle(name, 0, 0, 8, 8, "#6b4a2f", filled=True)
    tilemap.create_tilemap_layer(name, "ground", 16, 16)
    tilemap.add_tile(name, "ground", "#ff0000")
    tilemap.set_tile(name, "ground", 0, 0, 1)

    result = sprite.set_color_mode(name, "indexed")

    assert result["colorMode"] == "indexed"
    assert tilemap.get_tilemap(name, "ground")["tiles"][0][0] == 1


# --------------------------------------------------- the modes without a palette
def test_the_other_modes_report_no_palette_decision(request):
    """RGB and gray both keep a per-pixel alpha channel and have no index that means
    "nothing", so there is no hole for a pixel to fall through, nothing to quantize, and
    no reason to pay for the verification scan."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 1, 1, 4, 4, "#6b4a2f", filled=True)

    result = sprite.set_color_mode(name, "gray")

    assert result["colorMode"] == "gray"
    assert "drawn_pixels" not in result and "palette_source" not in result
    assert _drawn(name, 8) == 16


def test_indexed_converts_back_to_rgb(request):
    name = _name(request)
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    drawing.draw_rectangle(name, 2, 2, 4, 4, "#ffffff", filled=True)

    result = sprite.set_color_mode(name, "rgb")

    assert result["colorMode"] == "rgb"
    assert inspect.get_pixels(name, 3, 3, 1, 1)["pixels"][0][0] == "#ffffffff"


# --------------------------------------------------- arguments, refused up front
@pytest.mark.parametrize(
    "kwargs",
    [
        {"color_mode": "rgba"},
        {"color_mode": "indexed", "dithering": "ordered-bayer"},
        {"color_mode": "indexed", "palette_source": "quantize"},
    ],
)
def test_a_bad_argument_is_refused_without_opening_the_sprite(request, kwargs):
    """These never reach Aseprite. `dithering` is the one that mattered: Aseprite accepts
    any string for it and silently converts with its default, so a typo used to report
    success having dithered some other way."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    before = _digest(name)

    with pytest.raises(ValidationFailed):
        sprite.set_color_mode(name, **kwargs)

    assert _digest(name) == before
