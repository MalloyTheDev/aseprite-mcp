"""render_preview's views: the frame in colour, in value, as a silhouette and at 1x.

An agent judging its own pixel art can only make the checks it is shown. Shown the
colour image alone, the death knight read as detailed armour; its silhouette is a black
bell with ears, its cape the same grey as its plate, which is what assess_sprite's
"fused masses" and "1.2:1 keyline" readings were saying in numbers. The views show
that at a glance, from the same single launch.

The sheet is assembled in Python from one 1x render, so everything but the end-to-end
check is `pure`: these tests build the render with Pillow and read the sheet back.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image as PILImage

from aseprite_mcp.core import quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_PREVIEW_EDGE
from aseprite_mcp.tools import drawing, inspect, sprite

YELLOW, BLUE, RED_HALF = (255, 255, 0, 255), (0, 0, 255, 255), (255, 0, 0, 128)
SCALE, SIZE = 4, 16
# Where the panels start, from the module's own layout constants: with a 16 px frame
# at 4x every scaled panel is 64 px, wider than its label, so the columns are uniform.
GAP, TOP = inspect._SHEET_GAP, inspect._SHEET_GAP + inspect._LABEL_H
ORIGIN = {"color": GAP, "value": GAP + 64 + GAP, "silhouette": GAP + 2 * (64 + GAP),
          "actual": GAP + 3 * (64 + GAP)}


def _png(size: tuple[int, int] = (SIZE, SIZE), pixels: dict | None = None) -> bytes:
    img = PILImage.new("RGBA", size, (0, 0, 0, 0))
    for (x, y), colour in (pixels or {}).items():
        img.putpixel((x, y), colour)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _sheet(views=("color", "value", "silhouette", "actual")) -> PILImage.Image:
    png = _png(pixels={(0, 0): YELLOW, (1, 0): BLUE, (3, 0): RED_HALF})
    return PILImage.open(io.BytesIO(inspect._views_sheet(png, list(views), SCALE))).convert("RGB")


def _at(sheet: PILImage.Image, view: str, x: int, y: int) -> tuple[int, int, int]:
    k = 1 if view == "actual" else SCALE
    return sheet.getpixel((ORIGIN[view] + x * k + k // 2, TOP + y * k + k // 2))


@pytest.fixture
def no_launch(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for views that are refused")
    monkeypatch.setattr(inspect, "run_cli", refuse)


@pytest.mark.pure
@pytest.mark.parametrize("views, match", [
    ([], "views is empty"),
    (["colour"], r"views has \['colour'\]"),
    (["value", "value"], "names a view twice"),
])
def test_bad_views_are_refused_before_launch(no_launch, views, match):
    with pytest.raises(ValidationFailed, match=match):
        inspect.render_preview("pv/x.aseprite", views=views)


@pytest.mark.pure
def test_each_panel_shows_what_it_says():
    sheet = _sheet()
    assert _at(sheet, "color", 0, 0) == YELLOW[:3]
    assert _at(sheet, "silhouette", 0, 0) == (0, 0, 0)
    assert _at(sheet, "silhouette", 3, 0) == (0, 0, 0), "a translucent pixel is drawn"
    assert _at(sheet, "silhouette", 2, 0) == (255, 255, 255)
    assert _at(sheet, "actual", 0, 0) == YELLOW[:3]
    assert _at(sheet, "actual", 1, 0) == BLUE[:3]


@pytest.mark.pure
def test_value_is_luminance_not_hls_lightness():
    """HLS lightness calls pure yellow and pure blue equally light (both 0.5); their
    relative luminances are 0.93 and 0.07. A value view built on HLS would show them as
    one grey, which is the error the view exists to catch."""
    sheet = _sheet()
    yellow, blue = _at(sheet, "value", 0, 0), _at(sheet, "value", 1, 0)
    assert len(set(yellow)) == 1 and len(set(blue)) == 1, "value panels are grey"
    assert yellow[0] == inspect._grey(quality.luminance(YELLOW))
    assert yellow[0] - blue[0] > 150


@pytest.mark.pure
def test_transparency_shows_as_a_checkerboard_not_as_grey():
    sheet = _sheet()
    assert _at(sheet, "color", 2, 0) in {c[:3] for c in inspect._CHECKER}
    assert _at(sheet, "value", 2, 0) in {c[:3] for c in inspect._CHECKER}


@pytest.mark.pure
def test_a_large_frame_is_shown_at_a_scale_that_fits():
    png = _png((600, 600), {(0, 0): YELLOW})
    sheet = PILImage.open(io.BytesIO(
        inspect._views_sheet(png, ["color", "value", "silhouette"], 8)))
    assert max(sheet.size) <= MAX_PREVIEW_EDGE


@pytest.mark.pure
def test_a_sheet_that_cannot_fit_at_1x_is_refused_not_shrunk():
    png = _png((900, 900), {(0, 0): YELLOW})
    with pytest.raises(ValidationFailed, match="Ask for fewer views"):
        inspect._views_sheet(png, ["color", "value", "silhouette"], 8)


def test_render_preview_returns_the_sheet_from_one_render():
    name = "pv/square.aseprite"
    sprite.create_sprite(name, SIZE, SIZE, overwrite=True)
    drawing.draw_rectangle(name, 4, 4, 8, 8, "#4060c0", filled=True)
    plain = PILImage.open(io.BytesIO(inspect.render_preview(name, scale=SCALE).data))
    sheet = PILImage.open(io.BytesIO(
        inspect.render_preview(name, scale=SCALE, views=["color", "silhouette"]).data))
    assert plain.size == (SIZE * SCALE, SIZE * SCALE), "no views is the colour image alone"
    assert sheet.size == (3 * GAP + 2 * SIZE * SCALE, TOP + GAP + SIZE * SCALE)
    second_panel = GAP + SIZE * SCALE + GAP
    assert sheet.convert("RGB").getpixel((second_panel + 30, TOP + 30)) == (0, 0, 0)
    assert sheet.convert("RGB").getpixel((second_panel + 2, TOP + 2)) == (255, 255, 255)
