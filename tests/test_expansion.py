"""Integration tests for the expansion: effects, text, tilemap, image, curves, trim."""

from aseprite_mcp.tools import (
    drawing,
    effects,
    export,
    image,
    inspect,
    sprite,
    text,
    tilemap,
)


def test_gradient_linear():
    sprite.create_sprite("e/grad.aseprite", 16, 1, "rgb")
    effects.fill_gradient("e/grad.aseprite", ["#000000", "#ffffff"], "linear", angle=0)
    px = inspect.get_pixels("e/grad.aseprite", 0, 0, 16, 1)
    row = px["pixels"][0]
    # left end darker than right end
    assert int(row[0][1:3], 16) < int(row[-1][1:3], 16)


def test_invert_colors():
    sprite.create_sprite("e/inv.aseprite", 4, 4, "rgb")
    drawing.fill_layer("e/inv.aseprite", "#102030")
    effects.invert_colors("e/inv.aseprite")
    px = inspect.get_pixels("e/inv.aseprite", 0, 0, 1, 1)
    assert px["pixels"][0][0] == "#efdfcfff"  # 255-16,255-32,255-48


def test_replace_color():
    sprite.create_sprite("e/rep.aseprite", 4, 4, "rgb")
    drawing.fill_layer("e/rep.aseprite", "#ff0000")
    effects.replace_color("e/rep.aseprite", "#ff0000", "#00ff00", tolerance=0)
    px = inspect.get_pixels("e/rep.aseprite", 0, 0, 1, 1)
    assert px["pixels"][0][0] == "#00ff00ff"


def test_outline_outside():
    sprite.create_sprite("e/out.aseprite", 8, 8, "rgb")
    drawing.draw_rectangle("e/out.aseprite", 2, 2, 4, 4, "#ff0000", filled=True)
    effects.add_outline("e/out.aseprite", "#000000", thickness=1, connectivity=4, where="outside")
    px = inspect.get_pixels("e/out.aseprite", 0, 0, 8, 8)
    # the cell directly left of the rect (x=1,y=3) should now be black outline
    assert px["pixels"][3][1] == "#000000ff"


def test_drop_shadow_adds_layer():
    sprite.create_sprite("e/shadow.aseprite", 8, 8, "rgb")
    drawing.draw_rectangle("e/shadow.aseprite", 1, 1, 3, 3, "#ffffff", filled=True)
    info = effects.add_drop_shadow("e/shadow.aseprite", "Layer 1", 1, 1, "#000000", opacity=128)
    names = [l["name"] for l in info["layers"]]
    assert "Layer 1 shadow" in names


def test_checkerboard():
    sprite.create_sprite("e/check.aseprite", 4, 4, "rgb")
    effects.fill_checkerboard("e/check.aseprite", "#ffffff", "#000000", size=1)
    px = inspect.get_pixels("e/check.aseprite", 0, 0, 2, 1)
    assert px["pixels"][0][0] != px["pixels"][0][1]  # adjacent cells differ


def test_text_renders_pixels():
    sprite.create_sprite("e/txt.aseprite", 64, 16, "rgb", "#000000")
    out = text.draw_text("e/txt.aseprite", "AB", 1, 1, "#ffffff", scale=1)
    assert out["text_width"] > 0 and out["text_height"] > 0
    px = inspect.get_pixels("e/txt.aseprite", 0, 0, 32, 16)
    white = sum(1 for row in px["pixels"] for c in row if c == "#ffffffff")
    assert white > 0  # text drew some white pixels


def test_draw_curve():
    sprite.create_sprite("e/curve.aseprite", 16, 16, "rgb")
    out = drawing.draw_curve("e/curve.aseprite", 0, 15, 8, 0, 15, 15, "#ff0000", steps=24)
    assert out["ok"] is True


def test_tilemap_roundtrip():
    sprite.create_sprite("e/tm.aseprite", 64, 64, "rgb")
    tilemap.create_tilemap_layer("e/tm.aseprite", "ground", 16, 16)
    r1 = tilemap.add_tile("e/tm.aseprite", "ground", "#ff0000")
    r2 = tilemap.add_tile("e/tm.aseprite", "ground", "#00ff00")
    assert r1["index"] == 1 and r2["index"] == 2
    tilemap.set_tile("e/tm.aseprite", "ground", 0, 0, 1)
    tilemap.set_tiles("e/tm.aseprite", "ground", [{"column": 1, "row": 1, "index": 2}])
    tm = tilemap.get_tilemap("e/tm.aseprite", "ground")
    assert tm["tileCount"] == 3
    assert tm["tiles"][0][0] == 1
    assert tm["tiles"][1][1] == 2


def test_stamp_file():
    sprite.create_sprite("e/src.aseprite", 4, 4, "rgb", "#ff8800")
    export.export_png("e/src.aseprite", "e/src.png", 1, 1)
    sprite.create_sprite("e/dst.aseprite", 16, 16, "rgb", "#000000")
    image.stamp_file("e/dst.aseprite", "e/src.png", 5, 5)
    px = inspect.get_pixels("e/dst.aseprite", 5, 5, 1, 1)
    assert px["pixels"][0][0] == "#ff8800ff"


def test_trim_sprite():
    sprite.create_sprite("e/trim.aseprite", 32, 32, "rgb")
    drawing.draw_rectangle("e/trim.aseprite", 10, 10, 5, 5, "#ffffff", filled=True)
    info = sprite.trim_sprite("e/trim.aseprite")
    assert info["width"] == 5 and info["height"] == 5
