"""Integration tests for round 3: brushes/symmetry, slices, palette tools,
pixel-perfect/AA, filtered & onion-skin exports, reference layers."""

import os

from aseprite_mcp.tools import (
    brushes,
    drawing,
    export,
    inspect,
    palette,
    reference,
    slices,
    sprite,
)


def test_draw_brush():
    sprite.create_sprite("a/brush.aseprite", 16, 16, "rgb")
    brushes.draw_brush("a/brush.aseprite", ["111", "111", "111"], [{"x": 5, "y": 5}], "#ff0000",
                       anchor="topleft")
    px = inspect.get_pixels("a/brush.aseprite", 5, 5, 3, 3)
    assert all(c == "#ff0000ff" for row in px["pixels"] for c in row)


def test_mirror_layer():
    sprite.create_sprite("a/mirror.aseprite", 8, 8, "rgb")
    drawing.draw_pixels("a/mirror.aseprite", [{"x": 1, "y": 1, "color": "#00ff00"}])
    brushes.mirror_layer("a/mirror.aseprite", "Layer 1", "horizontal", "first")  # axis=4
    px = inspect.get_pixels("a/mirror.aseprite", 0, 0, 8, 8)
    assert px["pixels"][1][6] == "#00ff00ff"  # x=1 reflects to x=6


def test_symmetric_pixels():
    sprite.create_sprite("a/sym.aseprite", 8, 8, "rgb")
    brushes.draw_symmetric_pixels("a/sym.aseprite", [{"x": 1, "y": 1}], "#ff0000", mode="both")
    px = inspect.get_pixels("a/sym.aseprite", 0, 0, 8, 8)
    for x, y in [(1, 1), (6, 1), (1, 6), (6, 6)]:
        assert px["pixels"][y][x] == "#ff0000ff"


def test_slices_9patch():
    sprite.create_sprite("a/slice.aseprite", 32, 32, "rgb")
    slices.add_slice("a/slice.aseprite", "btn", 2, 2, 20, 12,
                     center_x=4, center_y=4, center_width=12, center_height=4)
    info = slices.list_slices("a/slice.aseprite")
    assert info["count"] == 1
    sl = info["slices"][0]
    assert sl["name"] == "btn"
    assert sl["center"] == {"x": 4, "y": 4, "width": 12, "height": 4}
    slices.remove_slice("a/slice.aseprite", "btn")
    assert slices.list_slices("a/slice.aseprite")["count"] == 0


def test_extract_palette():
    sprite.create_sprite("a/ext.aseprite", 8, 8, "rgb")
    drawing.draw_rectangle("a/ext.aseprite", 0, 0, 4, 8, "#ff0000", filled=True)
    drawing.draw_rectangle("a/ext.aseprite", 4, 0, 4, 8, "#0000ff", filled=True)
    out = palette.extract_palette("a/ext.aseprite", set_as_palette=True)
    assert out["count"] == 2
    assert set(out["colors"]) == {"#ff0000ff", "#0000ffff"}


def test_generate_ramp():
    out = palette.generate_ramp("#3878c8", steps=5, hue_shift=40, light_range=0.7)
    assert len(out["colors"]) == 5
    assert all(c.startswith("#") and len(c) == 7 for c in out["colors"])


def test_sort_palette_indexed_preserves_image():
    sprite.create_sprite("a/idx.aseprite", 4, 4, "indexed", "#ff0000")
    palette.set_palette("a/idx.aseprite", ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff"])
    drawing.fill_layer("a/idx.aseprite", "#00ff00")  # nearest index = green
    before = inspect.get_pixels("a/idx.aseprite", 0, 0, 1, 1)["pixels"][0][0]
    palette.sort_palette("a/idx.aseprite", by="hue")
    after = inspect.get_pixels("a/idx.aseprite", 0, 0, 1, 1)["pixels"][0][0]
    assert before == after  # appearance preserved despite reindexing


def test_pixel_perfect_line():
    sprite.create_sprite("a/pp.aseprite", 16, 16, "rgb", "#000000")
    out = drawing.draw_line("a/pp.aseprite", 0, 0, 10, 4, "#ffffff", pixel_perfect=True)
    assert out["ok"] is True


def test_antialiased_line_has_partial_alpha():
    sprite.create_sprite("a/aa.aseprite", 16, 16, "rgb")  # transparent bg
    drawing.draw_line("a/aa.aseprite", 0, 1, 15, 6, "#ffffff", antialias=True)
    px = inspect.get_pixels("a/aa.aseprite", 0, 0, 16, 16)
    alphas = {c[7:9] for row in px["pixels"] for c in row}
    partial = [a for a in alphas if a not in ("00", "ff")]
    assert partial  # anti-aliasing produced semi-transparent edge pixels


def test_export_layers(tmp_path):
    sprite.create_sprite("a/exp.aseprite", 8, 8, "rgb")
    from aseprite_mcp.tools import layers as L
    L.add_layer("a/exp.aseprite", "top")
    pat = str(tmp_path / "ly_{layer}.png")
    export.export_layers("a/exp.aseprite", pat, 1)
    files = list(tmp_path.glob("ly_*.png"))
    assert len(files) >= 2  # one file per layer


def test_onion_skin(tmp_path):
    sprite.create_sprite("a/onion.aseprite", 8, 8, "rgb", "#111111")
    from aseprite_mcp.tools import frames as F
    F.add_frame("a/onion.aseprite", 100, copy_from=1)
    F.add_frame("a/onion.aseprite", 100, copy_from=1)
    out = str(tmp_path / "onion.png")
    export.export_onion_skin("a/onion.aseprite", 3, out, previous=2, next=0, scale=2)
    assert os.path.getsize(out) > 0


def test_reference_layer_locked():
    sprite.create_sprite("a/ref.aseprite", 8, 8, "rgb")
    export.export_png("a/ref.aseprite", "a/refsrc.png", 1, 1)
    info = reference.add_reference_layer("a/ref.aseprite", "a/refsrc.png", "reference", opacity=100)
    ref = next(l for l in info["layers"] if l["name"] == "reference")
    assert ref["isEditable"] is False
    assert ref["opacity"] == 100
