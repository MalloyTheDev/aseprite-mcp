"""export_motion_trail (#77): every frame of a motion in one image, the oldest faintest.

Most of this needs a real Aseprite (--run-aseprite); the argument refusals are `pure`,
because they are made in Python before anything is launched. Pixel values are read back
off the written PNG with Pillow, not taken from the tool's own report.
"""

from __future__ import annotations

import pytest
from PIL import Image

from aseprite_mcp.core.errors import ExportError, ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import drawing, export, frames, layers, sprite, tags
from aseprite_mcp.tools.common import resolve_path

RED = "#ff0000"


def _moving_dot(name: str, xs: list[int]) -> str:
    """One frame per x: a red pixel at (x, 2) on a transparent 8x5 sprite."""
    sprite.create_sprite(name, 8, 5, overwrite=True)
    for i, x in enumerate(xs):
        if i:
            frames.add_frame(name)
        drawing.draw_pixels(name, [{"x": x, "y": 2}], RED, frame=i + 1)
    return name


def _pixel(path: str, x: int, y: int) -> tuple[int, int, int, int]:
    with Image.open(resolve_path(path)) as img:
        return img.convert("RGBA").getpixel((x, y))


@pytest.fixture
def no_launch(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for a call that is refused before it")
    monkeypatch.setattr(export, "run_lua", refuse)


# --- refused before launch ---------------------------------------------------------


@pytest.mark.pure
def test_a_tag_and_a_frame_list_together_are_refused(no_launch):
    with pytest.raises(ValidationFailed, match="not both"):
        export.export_motion_trail("mt/x.aseprite", "mt/x.png", tag="walk", frames=[1, 2])


@pytest.mark.pure
def test_an_empty_frame_list_is_refused(no_launch):
    with pytest.raises(ValidationFailed, match="frames is empty"):
        export.export_motion_trail("mt/x.aseprite", "mt/x.png", frames=[])


@pytest.mark.pure
def test_a_scale_below_one_is_refused(no_launch):
    with pytest.raises(ValidationFailed, match="scale is 0; minimum is 1"):
        export.export_motion_trail("mt/x.aseprite", "mt/x.png", scale=0)


@pytest.mark.pure
def test_an_existing_output_is_not_replaced_without_overwrite(no_launch):
    resolve_path("mt/taken.png").parent.mkdir(parents=True, exist_ok=True)
    resolve_path("mt/taken.png").write_bytes(b"not replaced")
    with pytest.raises(ExportError, match="already exists"):
        export.export_motion_trail("mt/x.aseprite", "mt/taken.png")
    assert resolve_path("mt/taken.png").read_bytes() == b"not replaced"


# --- against Aseprite --------------------------------------------------------------


def test_the_oldest_frame_is_faintest_and_the_last_opaque():
    name = _moving_dot("mt/dot.aseprite", [1, 3, 5])
    result = export.export_motion_trail(name, "mt/dot.png", scale=1, overwrite=True)

    assert result["frames"] == [1, 2, 3]
    assert result["opacities"] == [85, 170, 255]
    assert [_pixel("mt/dot.png", x, 2) for x in (1, 3, 5)] == [
        (255, 0, 0, 85), (255, 0, 0, 170), (255, 0, 0, 255)]
    assert _pixel("mt/dot.png", 0, 0) == (0, 0, 0, 0)


def test_a_tag_composites_only_its_frames():
    name = _moving_dot("mt/tagged.aseprite", [0, 2, 4, 6])
    tags.add_tag(name, "middle", 2, 3)
    result = export.export_motion_trail(name, "mt/tagged.png", tag="middle", scale=1,
                                        overwrite=True)

    assert result["frames"] == [2, 3]
    assert [_pixel("mt/tagged.png", x, 2)[3] for x in (0, 2, 4, 6)] == [0, 128, 255, 0]


def test_frames_are_drawn_in_the_order_given():
    """The last listed is the one on top, whatever its number."""
    name = _moving_dot("mt/ordered.aseprite", [1, 3, 5])
    result = export.export_motion_trail(name, "mt/ordered.png", frames=[3, 1], scale=1,
                                        overwrite=True)

    assert result["frames"] == [3, 1]
    assert _pixel("mt/ordered.png", 5, 2)[3] == 128
    assert _pixel("mt/ordered.png", 1, 2)[3] == 255


def test_an_opaque_background_lies_under_the_trail_instead_of_burying_it():
    """Every frame of an opaque sprite is opaque, so without this the last frame, drawn at
    full opacity, covered the whole trail and the image showed one frame."""
    name = "mt/scene.aseprite"
    sprite.create_sprite(name, 8, 5, overwrite=True)
    drawing.fill_layer(name, "#0ac81e")
    sprite.convert_layer_to_background(name, "Layer 1")
    frames.add_frame(name, copy_from=1)
    frames.add_frame(name, copy_from=2)
    layers.add_layer(name, "dot")
    for i, x in enumerate([1, 3, 5]):
        drawing.draw_pixels(name, [{"x": x, "y": 2}], RED, layer="dot", frame=i + 1)

    result = export.export_motion_trail(name, "mt/scene.png", scale=2, overwrite=True)

    assert result["background"] is True
    assert (result["width"], result["height"]) == (16, 10)
    assert _pixel("mt/scene.png", 0, 4) == (10, 200, 30, 255)    # the base, untouched
    assert _pixel("mt/scene.png", 2, 4) == (91, 134, 20, 255)    # red at 85 over green
    assert _pixel("mt/scene.png", 6, 4) == (173, 67, 10, 255)    # red at 170 over green
    assert _pixel("mt/scene.png", 10, 4) == (255, 0, 0, 255)     # the last frame, on top


def test_an_unknown_tag_names_the_ones_that_exist():
    name = _moving_dot("mt/notag.aseprite", [1, 3])
    tags.add_tag(name, "walk", 1, 2)
    with pytest.raises(AsepriteError, match="no tag named 'run'; its tags are: walk"):
        export.export_motion_trail(name, "mt/notag.png", tag="run", overwrite=True)


def test_a_scale_past_the_canvas_caps_is_refused_from_the_header():
    """Before the launch, from the file's header; the Lua check is the backstop for a
    source whose header cannot be read."""
    name = _moving_dot("mt/huge.aseprite", [1, 3])
    with pytest.raises(ExportError, match="past the caps"):
        export.export_motion_trail(name, "mt/huge.png", scale=4000, overwrite=True)


def test_a_whole_sprite_is_held_to_the_same_frame_cap_as_a_list(monkeypatch):
    """The cap was on the explicit list only; a tag or the whole sprite composited every
    frame however many there were. Lowered here rather than building 513 frames."""
    monkeypatch.setattr(export, "MAX_MOTION_FRAMES", 2)
    name = _moving_dot("mt/capped.aseprite", [1, 3, 5])
    with pytest.raises(AsepriteError, match="that is 3 frames; a motion trail composites at most 2"):
        export.export_motion_trail(name, "mt/capped.png", overwrite=True)
