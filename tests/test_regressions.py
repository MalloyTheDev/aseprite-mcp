"""Regression tests for edge cases found during the pre-release audit."""

import pytest

from aseprite_mcp.runner import AsepriteError
from aseprite_mcp.tools import drawing, palette, sprite, tilemap


def test_drawing_on_tilemap_layer_errors_clearly():
    """Pixel drawing must refuse tilemap layers with a helpful message rather than
    failing cryptically deep in Lua."""
    sprite.create_sprite("r/tm.aseprite", 32, 32, "rgb")
    tilemap.create_tilemap_layer("r/tm.aseprite", "ground", 16, 16)
    with pytest.raises(AsepriteError, match="tilemap"):
        drawing.draw_rectangle("r/tm.aseprite", 0, 0, 8, 8, "#ff0000", filled=True, layer="ground")


def test_sort_palette_preserves_tilemap_indices():
    """sort_palette on an indexed sprite must not remap tilemap cels (whose pixels
    are tile indices, not palette indices)."""
    sprite.create_sprite("r/idx.aseprite", 32, 32, "indexed")
    palette.set_palette("r/idx.aseprite", ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff"])
    tilemap.create_tilemap_layer("r/idx.aseprite", "g", 16, 16)
    tilemap.add_tile("r/idx.aseprite", "g", "#ff0000")  # tile index 1
    tilemap.set_tile("r/idx.aseprite", "g", 0, 0, 1)
    palette.sort_palette("r/idx.aseprite", by="hue")
    tm = tilemap.get_tilemap("r/idx.aseprite", "g")
    assert tm["tiles"][0][0] == 1  # tile index unchanged by the palette sort
