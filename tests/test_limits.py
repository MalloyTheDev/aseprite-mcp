"""Pure-Python tests for the collection size limits (DoS guard) — no Aseprite.

The caps are enforced before any path resolution or Aseprite launch, so the
tool-level cases raise without a real Aseprite (the check fires first).
"""

import pytest

from aseprite_mcp.core import limits, oplib
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, palette, tilemap


# --------------------------------------------------------- check_list_length
def test_at_limit_is_allowed():
    limits.check_list_length("x", [0] * 10, 10)  # exactly the max: no raise


def test_over_limit_message_has_all_parts():
    with pytest.raises(ValidationFailed) as excinfo:
        limits.check_list_length(
            "operations", [0] * 731, 500, remedy="Split the edit into multiple batches."
        )
    msg = str(excinfo.value)
    assert "operations" in msg  # field
    assert "731" in msg         # received count
    assert "500" in msg         # maximum
    assert "Split the edit into multiple batches." in msg  # remedy


def test_default_remedy_present():
    with pytest.raises(ValidationFailed, match="smaller calls"):
        limits.check_list_length("colors", [0] * 2, 1)


# ------------------------------------------------------- wired call sites
def test_set_palette_color_cap():
    colors = ["#000000"] * (limits.MAX_COLOR_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"colors has \d+ items; maximum is 256"):
        palette.set_palette("w/x.aseprite", colors)


def test_draw_pixels_cap():
    pixels = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"pixels has \d+ items; maximum is 65536"):
        drawing.draw_pixels("w/x.aseprite", pixels, color="#ffffff")


def test_draw_polyline_cap():
    points = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"points has \d+ items; maximum is 65536"):
        drawing.draw_polyline("w/x.aseprite", points, color="#ffffff")


def test_set_tiles_cap():
    tiles = [{"column": 0, "row": 0, "index": 0}] * (limits.MAX_TILE_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"tiles has \d+ items; maximum is 65536"):
        tilemap.set_tiles("w/x.aseprite", "tiles", tiles)


def test_paint_tile_pixels_cap():
    pixels = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"pixels has \d+ items; maximum is 65536"):
        tilemap.paint_tile_pixels("w/x.aseprite", "tiles", 1, pixels, color="#ffffff")


def test_oplib_batch_cap_reexposed():
    ops = [{"op": "add_layer", "args": {"name": "x"}}] * (limits.MAX_BATCH_OPERATIONS + 1)
    with pytest.raises(ValidationFailed, match="Split the edit into multiple batches"):
        oplib.validate_operations(ops)
