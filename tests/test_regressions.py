"""Regression tests for edge cases found during the pre-release audit."""

import pytest

from aseprite_mcp.runner import AsepriteError
from aseprite_mcp.tools import brushes, drawing, effects, export, palette, sprite, tilemap


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


def test_stamp_pattern_negative_spacing_does_not_hang():
    """Negative spacing must be clamped so the tiling loop always advances."""
    sprite.create_sprite("r/tile.aseprite", 4, 4, "rgb", "#00ff00")
    export.export_png("r/tile.aseprite", "r/tile.png", 1, 1)
    sprite.create_sprite("r/dst.aseprite", 16, 16, "rgb")
    out = brushes.stamp_pattern("r/dst.aseprite", "r/tile.png", 0, 0, 16, 16, spacing_x=-100, spacing_y=-100)
    assert out["ok"] is True and out["tiles"] > 0


def test_set_color_mode_validates_input():
    sprite.create_sprite("r/cm.aseprite", 8, 8, "rgb")
    with pytest.raises(ValueError, match="color_mode"):
        sprite.set_color_mode("r/cm.aseprite", "rgba")  # not a real mode


def test_replace_color_accepts_index_spec():
    """replace_color with an `index:N` source must not crash on indexed sprites."""
    sprite.create_sprite("r/ri.aseprite", 8, 8, "indexed")
    palette.set_palette("r/ri.aseprite", ["#000000", "#ffffff", "#ff0000"])
    drawing.fill_layer("r/ri.aseprite", "#ff0000")  # index 2
    out = effects.replace_color("r/ri.aseprite", "index:2", "#ffffff", tolerance=0)
    assert out["ok"] is True
