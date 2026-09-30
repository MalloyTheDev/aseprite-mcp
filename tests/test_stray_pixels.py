"""remove_stray_pixels over real sprites: requires Aseprite (--run-aseprite).

A stray is a pixel with no neighbour of its own colour in any of the eight directions.
They are what a shading pass leaves at a band boundary, and they read as dirt. The two
properties that make the tool safe to reach for are that it cannot introduce a colour and
cannot change the silhouette, so both are tested rather than described.
"""

from __future__ import annotations

from aseprite_mcp.tools import drawing, effects, inspect, palette, shading, sprite

RAMP = palette.generate_ramp("#5a7fd4", steps=5, hue_shift=-40.0)["colors"]


def _metrics(name: str, **kwargs) -> dict:
    return inspect.assess_sprite(name, **kwargs)["metrics"]


def _block(request, size: int = 16) -> str:
    name = f"sp/{request.node.name}.aseprite"
    sprite.create_sprite(name, size, size)
    drawing.draw_rectangle(name, 2, 2, size - 4, size - 4, RAMP[2], filled=True)
    return name


def test_a_planted_stray_is_taken_back_to_the_colour_around_it(request):
    name = _block(request)
    drawing.draw_pixels(name, [{"x": 7, "y": 7}], RAMP[4])
    assert _metrics(name)["colors"] == 2

    result = effects.remove_stray_pixels(name)

    assert result["replaced"] == 1
    assert _metrics(name)["colors"] == 1, "the stray took the colour around it"


def test_no_colour_that_was_not_already_there_can_appear(request):
    """The property that makes this safe on ramped art: a stray is replaced by a colour
    from its own neighbourhood, never by an average of one."""
    name = _block(request)
    shading.shade_region_by_light(name, RAMP, base_color=RAMP[2], light_angle=125)
    before = _metrics(name, ramp=RAMP)

    effects.remove_stray_pixels(name)

    after = _metrics(name, ramp=RAMP)
    assert after["colors"] <= before["colors"]
    assert after["palette_conformance"] == 1.0
    assert after["drawn_pixels"] == before["drawn_pixels"], "the silhouette must not move"


def test_it_leaves_a_dither_alone(request):
    """A checkerboard is diagonally connected and nothing else. Removing 'strays' by an
    orthogonal rule would eat it, which is why the rule here counts diagonals."""
    name = f"sp/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    drawing.draw_rectangle(name, 0, 0, 16, 16, RAMP[1], filled=True)
    drawing.draw_pixels(name, [{"x": x, "y": y} for y in range(16) for x in range(16)
                               if (x + y) % 2 == 0], RAMP[3])
    before = _metrics(name)

    result = effects.remove_stray_pixels(name)

    assert result["replaced"] == 0
    assert _metrics(name)["colors"] == before["colors"]


def test_a_protected_colour_survives(request):
    """A one-pixel specular is a stray by the definition and is meant to be there."""
    name = _block(request)
    drawing.draw_pixels(name, [{"x": 6, "y": 6}], RAMP[4])
    drawing.draw_pixels(name, [{"x": 10, "y": 10}], RAMP[0])

    result = effects.remove_stray_pixels(name, protect=[RAMP[4]])

    assert result["replaced"] == 1
    pixels = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]
    assert pixels[6][6].lower().startswith(RAMP[4].lower()), "the protected pixel stayed"
    assert not pixels[10][10].lower().startswith(RAMP[0].lower()), "the other went"


def test_running_it_twice_changes_nothing_the_second_time(request):
    name = _block(request)
    drawing.draw_pixels(name, [{"x": 5, "y": 5}, {"x": 9, "y": 4}], RAMP[4])

    first = effects.remove_stray_pixels(name)
    second = effects.remove_stray_pixels(name)

    assert first["replaced"] == 2
    assert second["replaced"] == 0


def test_transparent_pixels_are_never_filled_in(request):
    """It cleans the art, it does not grow it."""
    name = f"sp/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    drawing.draw_ellipse_in_box(name, 3, 3, 10, 10, RAMP[2], filled=True)
    drawing.draw_pixels(name, [{"x": 8, "y": 8}], RAMP[4])
    before = _metrics(name)

    effects.remove_stray_pixels(name)

    after = _metrics(name)
    assert after["drawn_pixels"] == before["drawn_pixels"]
    assert after["bbox"] == before["bbox"]


def test_a_lone_pixel_with_nothing_around_it_is_left_where_it_is(request):
    """With no opaque neighbour there is no colour to take, and inventing one would be
    drawing rather than cleaning."""
    name = f"sp/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    drawing.draw_pixels(name, [{"x": 8, "y": 8}], RAMP[3])

    result = effects.remove_stray_pixels(name)

    assert result["replaced"] == 0
    assert _metrics(name)["drawn_pixels"] == 1
