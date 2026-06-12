"""Pure-Python tests for the typed value models — no Aseprite (always run)."""

import pytest

from aseprite_mcp.tools.common import parse_color
from aseprite_mcp.tools.models import (
    ColorSpec,
    FrameRange,
    FrameRef,
    LayerRef,
    Pixel,
    Point,
    Rect,
    Size,
    SpritePath,
)


# ---------------------------------------------------------------- geometry
def test_point_and_size():
    assert Point.of("3", 4) == Point(3, 4)
    assert Size.of(16, 16) == Size(16, 16)
    with pytest.raises(ValueError):
        Size.of(0, 5)


def test_rect():
    r = Rect.of(2, 3, 10, 6)
    assert (r.x, r.y, r.width, r.height) == (2, 3, 10, 6)
    assert r.right == 12 and r.bottom == 9 and r.area == 60


# ---------------------------------------------------------------- colour
def test_colorspec_parse_forms():
    assert ColorSpec.parse("#ff0000").as_dict() == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert ColorSpec.parse("#ff000080").as_dict()["a"] == 128
    assert ColorSpec.parse("#f00").as_dict() == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert ColorSpec.parse("255,0,0").as_dict() == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert ColorSpec.parse("red").as_dict()["r"] == 255
    assert ColorSpec.parse("transparent").as_dict()["a"] == 0
    assert ColorSpec.parse("index:5").as_dict() == {"index": 5}


def test_colorspec_invalid():
    for bad in ("notacolor", "#zz", "1,2", None):
        with pytest.raises(ValueError):
            ColorSpec.parse(bad)


def test_parse_color_delegates_to_colorspec():
    # The long-standing common.parse_color must behave identically via ColorSpec.
    for spec in ("#ff0000", "#1d2b53ff", "10,20,30,40", "blue", "index:7", "#abc"):
        assert parse_color(spec) == ColorSpec.parse(spec).as_dict()


# ---------------------------------------------------------------- references
def test_layer_ref():
    assert LayerRef.of("body").value == "body"
    assert LayerRef.of(2).value == 2
    assert LayerRef.of(None).value is None


def test_frame_ref_and_range():
    assert FrameRef.of(3).number == 3
    with pytest.raises(ValueError):
        FrameRef.of(0)
    fr = FrameRange.of(4, 1)  # normalizes start <= end
    assert (fr.start, fr.end, fr.count) == (1, 4, 4)


def test_pixel():
    assert Pixel.of(1, 2).as_dict() == {"x": 1, "y": 2}  # colour optional
    p = Pixel.of(3, 4, "#ff0000")
    assert p.as_dict() == {"x": 3, "y": 4, "c": {"r": 255, "g": 0, "b": 0, "a": 255}}
    assert Pixel.of(0, 0, ColorSpec.parse("index:2")).as_dict()["c"] == {"index": 2}


def test_sprite_path_lua():
    assert SpritePath("C:\\a\\b.aseprite").lua() == "C:/a/b.aseprite"
    assert SpritePath("rel/x.png").lua() == "rel/x.png"
