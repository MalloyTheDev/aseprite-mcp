"""Golden-output tests: deterministic sprites with exact assertions on dimensions,
pixel colours, frame/layer counts, tag metadata, and exported image geometry.

Requires Aseprite — runs only under `pytest --run-aseprite`.
"""

from PIL import Image as PILImage

from aseprite_mcp.tools import drawing, export, frames, inspect, layers, sprite, tags


def test_golden_pixels_and_info():
    f = "g/hero.aseprite"
    info = sprite.create_sprite(f, 16, 16, "rgb", "#1d2b53")
    assert info["width"] == 16 and info["height"] == 16
    assert info["colorMode"] == "rgb"
    assert info["frameCount"] == 1 and info["layerCount"] == 1

    drawing.draw_rectangle(f, 4, 4, 6, 6, "#ff004d", filled=True)
    drawing.draw_pixels(f, [{"x": 0, "y": 0, "color": "#00e436"}])

    px = inspect.get_pixels(f, 0, 0, 16, 16)["pixels"]
    assert px[0][0] == "#00e436ff"   # the lone green pixel
    assert px[5][5] == "#ff004dff"   # inside the red rectangle
    assert px[0][1] == "#1d2b53ff"   # background


def test_golden_animation_metadata():
    f = "g/anim.aseprite"
    sprite.create_sprite(f, 16, 16, "rgb")
    layers.add_layer(f, "fg")
    frames.add_frame(f, 100, copy_from=1)
    frames.add_frame(f, 100, copy_from=1)
    tags.add_tag(f, "walk", 1, 3, "pingpong", "#00ff00")

    info = inspect.get_sprite_info(f)
    assert info["frameCount"] == 3
    assert [l["name"] for l in info["layers"]] == ["Layer 1", "fg"]
    assert len(info["tags"]) == 1
    t = info["tags"][0]
    assert (t["name"], t["from"], t["to"], t["aniDir"]) == ("walk", 1, 3, "pingpong")


def test_golden_png_export_geometry_and_pixels(tmp_path):
    f = "g/exp.aseprite"
    sprite.create_sprite(f, 8, 8, "rgb", "#112233")
    drawing.draw_rectangle(f, 0, 0, 4, 4, "#ffaa00", filled=True)
    out = str(tmp_path / "exp.png")
    export.export_png(f, out, 1, 4)  # scale 4 -> 32x32, nearest-neighbour

    im = PILImage.open(out).convert("RGBA")
    assert im.size == (32, 32)
    assert im.getpixel((2, 2)) == (255, 170, 0, 255)    # inside the scaled orange rect
    assert im.getpixel((30, 30)) == (17, 34, 51, 255)   # background corner


def test_golden_spritesheet_geometry(tmp_path):
    f = "g/sheet.aseprite"
    sprite.create_sprite(f, 8, 8, "rgb", "#000000")
    frames.add_frame(f, 100, copy_from=1)
    frames.add_frame(f, 100, copy_from=1)  # 3 frames total
    out = str(tmp_path / "sheet.png")
    export.export_spritesheet(f, out, "horizontal", 1)

    im = PILImage.open(out)
    assert im.size == (24, 8)  # 3 frames laid out horizontally
