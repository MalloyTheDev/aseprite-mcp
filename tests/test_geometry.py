"""Bounding-box ellipses: require Aseprite (--run-aseprite).

`draw_ellipse` takes a centre and radii, so every ellipse it can draw is an odd
2*radius+1 across. On a 32x32 canvas that makes a centred disc impossible, and a circle
can never line up with an even-width rectangle. `draw_ellipse_in_box` takes the same box
as `draw_rectangle` instead, which is the shape most callers were trying to describe.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, inspect, sprite


def _grid(name: str, size: int = 32):
    return inspect.get_pixels(name, 0, 0, size, size)["pixels"]


def _opaque(px: str) -> bool:
    return px[7:9] != "00"


def _canvas(request, size: int = 32) -> str:
    name = f"g/{request.node.name}.aseprite"
    sprite.create_sprite(name, size, size)
    return name


# ------------------------------------------------------------------- the even diameter
@pytest.mark.parametrize("width", [2, 4, 6, 8, 16])
def test_an_even_width_ellipse_fills_the_box_it_was_given(request, width):
    name = f"g/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse_in_box(name, 4, 6, width, width, "#ffffff", filled=True)

    box = quality.bounding_box(_grid(name))
    assert (box.x0, box.y0) == (4, 6)
    assert box.x1 - box.x0 + 1 == width
    assert box.y1 - box.y0 + 1 == width


def test_a_disc_can_be_centred_on_an_even_canvas(request):
    """The case that was impossible: 32 is even, so no centre-and-radius call can cover
    it symmetrically."""
    name = _canvas(request)
    drawing.draw_ellipse_in_box(name, 0, 0, 32, 32, "#ffffff", filled=True)

    grid = _grid(name)
    box = quality.bounding_box(grid)
    assert (box.x0, box.y0, box.x1, box.y1) == (0, 0, 31, 31)
    assert quality.silhouette_asymmetry(grid) == 0
    # Vertically symmetric too, which the horizontal metric cannot see.
    assert [row[:] for row in grid] == [row[:] for row in reversed(grid)]


def test_an_even_side_repeats_the_middle_column_of_the_odd_one(request):
    """The documented construction, and how an even circle is drawn by hand."""
    name = _canvas(request)
    drawing.draw_ellipse_in_box(name, 0, 0, 12, 12, "#ffffff", filled=True)

    grid = _grid(name)
    left_middle = [_opaque(row[5]) for row in grid]
    right_middle = [_opaque(row[6]) for row in grid]
    assert left_middle == right_middle


# ------------------------------------------------- lining up with the other primitives
def test_a_circle_and_a_rectangle_share_a_box(request):
    """The acceptance criterion: same arguments, same extent, so they concentric."""
    ellipse = f"g/{request.node.name}_e.aseprite"
    rectangle = f"g/{request.node.name}_r.aseprite"
    for name in (ellipse, rectangle):
        sprite.create_sprite(name, 32, 32)
    drawing.draw_ellipse_in_box(ellipse, 6, 9, 20, 14, "#ffffff", filled=True)
    drawing.draw_rectangle(rectangle, 6, 9, 20, 14, "#ffffff", filled=True)

    assert quality.bounding_box(_grid(ellipse)) == quality.bounding_box(_grid(rectangle))


def test_an_odd_box_is_pixel_for_pixel_what_draw_ellipse_draws(request):
    """Both forms use the same geometry, so where they can express the same shape they
    have to agree. Two rasterisers that nearly agree would be worse than one form."""
    boxed = f"g/{request.node.name}_b.aseprite"
    centred = f"g/{request.node.name}_c.aseprite"
    for name in (boxed, centred):
        sprite.create_sprite(name, 32, 32)

    drawing.draw_ellipse_in_box(boxed, 5, 7, 15, 11, "#ffffff", filled=True)
    # Same box: centre (5+7, 7+5), radii 7 and 5.
    drawing.draw_ellipse(centred, 12, 12, 7, 5, "#ffffff", filled=True)

    assert _grid(boxed) == _grid(centred)


def test_the_outline_form_also_matches(request):
    boxed = f"g/{request.node.name}_b.aseprite"
    centred = f"g/{request.node.name}_c.aseprite"
    for name in (boxed, centred):
        sprite.create_sprite(name, 32, 32)

    drawing.draw_ellipse_in_box(boxed, 3, 3, 13, 13, "#ff8800")
    drawing.draw_ellipse(centred, 9, 9, 6, 6, "#ff8800")

    assert _grid(boxed) == _grid(centred)


# ----------------------------------------------------------------------- staying inside
def test_an_outline_never_leaves_its_box(request):
    name = _canvas(request)
    drawing.draw_ellipse_in_box(name, 10, 4, 9, 14, "#00ff00")

    box = quality.bounding_box(_grid(name))
    assert (box.x0, box.y0, box.x1, box.y1) == (10, 4, 18, 17)


def test_a_one_pixel_box_is_one_pixel(request):
    name = _canvas(request)
    drawing.draw_ellipse_in_box(name, 8, 8, 1, 1, "#ffffff", filled=True)
    box = quality.bounding_box(_grid(name))
    assert (box.x0, box.y0, box.x1, box.y1) == (8, 8, 8, 8)


def test_a_two_pixel_box_is_the_two_by_two_block(request):
    """The smallest even circle there is. It has no roundness to lose."""
    name = _canvas(request)
    drawing.draw_ellipse_in_box(name, 8, 8, 2, 2, "#ffffff", filled=True)
    grid = _grid(name)
    assert [(x, y) for y in range(32) for x in range(32) if _opaque(grid[y][x])] == [
        (8, 8), (9, 8), (8, 9), (9, 9),
    ]


# ------------------------------------------------------------------------- antialiasing
def test_antialiasing_softens_the_edge_and_stays_in_the_box(request):
    name = _canvas(request)
    drawing.draw_ellipse_in_box(name, 4, 4, 16, 16, "#ffffff", filled=True, antialias=True)

    grid = _grid(name)
    box = quality.bounding_box(grid)
    assert (box.x0, box.y0, box.x1, box.y1) == (4, 4, 19, 19)
    partial = [px for row in grid for px in row if px[7:9] not in ("00", "ff")]
    assert partial, "an antialiased edge should have partly covered pixels"


# ----------------------------------------------------------------------------- refusals
def test_a_zero_sized_box_is_refused():
    with pytest.raises(ValidationFailed, match="at least 1"):
        drawing.draw_ellipse_in_box("unused.aseprite", 0, 0, 0, 5, "#ffffff")


def test_a_negative_box_is_refused():
    with pytest.raises(ValidationFailed, match="at least 1"):
        drawing.draw_ellipse_in_box("unused.aseprite", 0, 0, 5, -3, "#ffffff")
