"""Integration tests covering the core tool surface. Require a real Aseprite
install (skipped automatically otherwise — see conftest.py)."""

from aseprite_mcp.tools import (
    cels,
    drawing,
    export,
    frames,
    inspect,
    layers,
    palette,
    sprite,
    tags,
    transform,
)


def test_create_and_info():
    info = sprite.create_sprite("t/a.aseprite", 16, 16, "rgb", "#1d2b53")
    assert info["width"] == 16 and info["height"] == 16
    assert info["colorMode"] == "rgb"
    again = inspect.get_sprite_info("t/a.aseprite")
    assert again["frameCount"] == 1
    assert again["layers"][0]["name"] == "Layer 1"


def test_drawing_and_pixels():
    sprite.create_sprite("t/draw.aseprite", 8, 8, "rgb")
    drawing.fill_layer("t/draw.aseprite", "#000000")
    drawing.draw_rectangle("t/draw.aseprite", 1, 1, 4, 4, "#ff0000", filled=True)
    drawing.draw_pixels("t/draw.aseprite", [{"x": 0, "y": 0, "color": "#00ff00"}])
    px = inspect.get_pixels("t/draw.aseprite", 0, 0, 8, 8)
    assert px["pixels"][0][0] == "#00ff00ff"   # the green pixel
    assert px["pixels"][2][2] == "#ff0000ff"   # inside the red rect


def test_layers():
    sprite.create_sprite("t/layers.aseprite", 8, 8, "rgb")
    layers.add_layer("t/layers.aseprite", "fg")
    info = layers.add_group_layer("t/layers.aseprite", "grp")
    names = [l["name"] for l in info["layers"]]
    assert "fg" in names and "grp" in names
    info = layers.set_layer_properties("t/layers.aseprite", "fg", opacity=100, blend_mode="multiply")
    fg = next(l for l in info["layers"] if l["name"] == "fg")
    assert fg["opacity"] == 100 and fg["blendMode"] == "multiply"


def test_frames_and_durations():
    sprite.create_sprite("t/anim.aseprite", 8, 8, "rgb")
    frames.add_frame("t/anim.aseprite", 100, copy_from=1)
    out = frames.add_frame("t/anim.aseprite", 100)
    assert out["frameCount"] == 3
    frames.set_all_frame_durations("t/anim.aseprite", 80)
    info = inspect.get_sprite_info("t/anim.aseprite")
    assert all(abs(f["duration"] - 0.08) < 1e-6 for f in info["frames"])


def test_tags():
    sprite.create_sprite("t/tags.aseprite", 8, 8, "rgb")
    frames.add_frame("t/tags.aseprite", 100)
    frames.add_frame("t/tags.aseprite", 100)
    info = tags.add_tag("t/tags.aseprite", "walk", 1, 3, "pingpong", "#00ff00")
    assert info["tags"][0]["name"] == "walk"
    assert info["tags"][0]["aniDir"] == "pingpong"
    info = tags.remove_tag("t/tags.aseprite", "walk")
    assert info["tags"] == []


def test_cels():
    sprite.create_sprite("t/cels.aseprite", 8, 8, "rgb")
    drawing.fill_layer("t/cels.aseprite", "#ffffff")
    frames.add_frame("t/cels.aseprite", 100)
    cels.copy_cel("t/cels.aseprite", "Layer 1", 1, 2)
    cels.set_cel_position("t/cels.aseprite", "Layer 1", 2, 2, 2)
    info = cels.get_cel("t/cels.aseprite", "Layer 1", 2)
    assert info["exists"] is True
    assert info["position"] == {"x": 2, "y": 2}


def test_palette():
    sprite.create_sprite("t/pal.aseprite", 8, 8, "indexed")
    palette.set_palette("t/pal.aseprite", ["#000000", "#ffffff", "#ff0000"])
    pal = palette.get_palette("t/pal.aseprite")
    assert pal["size"] == 3
    assert pal["colors"][2] == "#ff0000ff"


def test_transforms():
    sprite.create_sprite("t/tx.aseprite", 10, 6, "rgb")
    info = transform.rotate_sprite("t/tx.aseprite", 90)
    assert info["width"] == 6 and info["height"] == 10  # dims swap on 90deg
    transform.flip_sprite("t/tx.aseprite", "horizontal")


def test_export(tmp_path):
    sprite.create_sprite("t/exp.aseprite", 8, 8, "rgb", "#123456")
    frames.add_frame("t/exp.aseprite", 100)
    out_png = str(tmp_path / "exp.png")
    out_gif = str(tmp_path / "exp.gif")
    out_sheet = str(tmp_path / "sheet.png")
    export.export_png("t/exp.aseprite", out_png, 1, 2)
    export.export_gif("t/exp.aseprite", out_gif, 1)
    export.export_spritesheet("t/exp.aseprite", out_sheet, "horizontal", 1)
    import os
    assert os.path.getsize(out_png) > 0
    assert os.path.getsize(out_gif) > 0
    assert os.path.getsize(out_sheet) > 0


def test_render_preview_returns_png():
    sprite.create_sprite("t/prev.aseprite", 8, 8, "rgb", "#abcdef")
    img = inspect.render_preview("t/prev.aseprite", 1, 4)
    assert img.data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number
