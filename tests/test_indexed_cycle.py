"""Palette cycling, and finding the indices worth cycling (issue #128).

The issue opened with a question rather than a design: Aseprite's file format carries a
palette per frame and `Sprite.palettes` is a list, so can a second palette be added,
bound to a frame range, and saved? Measured against the installed editor
(`app.version == "1.3.18.6"`), it cannot:

* `#spr.palettes` is 1 on a fresh indexed sprite and stays 1.
* `Palette(4).frame` is nil, and assigning it raises
  "attempt to index a nil value (field '__setters')".
* `spr.palettes[2] = Palette(4)`, `table.insert(spr.palettes, ...)` and
  `spr.palettes.length = 2` all raise that same `__setters` error, so the collection is
  read-only.
* `Sprite:newPalette` and `Sprite:deletePalette` do not exist.
* `Palette{ frame = 2 }` returns a plain Lua table, not a Palette, and `setPalette` then
  rejects it: "PaletteObj expected, got table".
* `spr:setPalette(alt)` with `app.frame` on frame 2 replaces palette *1*, and reopening
  the saved file shows one palette. `app.command.LoadPalette` on frame 3 behaves the same.

So this ships the issue's fallback: the frames are generated, and what rotates is the
pixels' own indices rather than the palette. On an indexed sprite those are the same
picture, and the index move is exact, with no `nearest_index` in it anywhere.
`cycle_palette` reports `method: "pixel_remap"` so a caller never has to guess which of
the two the issue's options it got.

The editor-tier tests build every sprite indexed from the start rather than by converting
an RGB one, because the palette is the whole point.
"""

from __future__ import annotations

import hashlib

import pytest

from aseprite_mcp.core import indexed
from aseprite_mcp.core.errors import AsepriteError, ValidationFailed
from aseprite_mcp.tools import drawing, export, frames, inspect, layers, palette, sprite

# A four-step water ramp, dark to light, laid down as four repeating rows so every entry
# in the cycle has the same number of pixels and a rotation is visible in any of them.
WATER = ["#1b3a5c", "#2b5f8f", "#4a90c2", "#7fc4e8"]


def _pond(request, width: int = 24, height: int = 16, suffix: str = "") -> str:
    """Striped water on one frame of an indexed sprite, palette written by hand.

    Named after the requesting test: the workspace fixture is session-scoped and
    `create_sprite` is no-clobber, so a shared filename would make every test after the
    first fail on that rather than on what it is checking.
    """
    name = f"ixc/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, width, height, color_mode="indexed")
    palette.set_palette(name, ["#00000000", *WATER])
    for row in range(height):
        drawing.draw_rectangle(name, 0, row, width, 1, f"index:{1 + row % 4}", filled=True)
    return name


def _hashes(name: str, count: int, width: int = 24, height: int = 16) -> list[str]:
    """One hash per frame of the composited picture, so frames can be compared at all.

    Comparing hashes rather than looking at a GIF is the acceptance criterion: nobody in
    this conversation can watch an animation play, and "it animates" has to mean
    "consecutive frames differ" or it means nothing.
    """
    return [
        hashlib.sha256(
            repr(inspect.get_pixels(name, 0, 0, width, height, frame=f)["pixels"]).encode()
        ).hexdigest()
        for f in range(1, count + 1)
    ]


# ------------------------------------------------------------------- the arithmetic
@pytest.mark.pure
def test_a_rotation_moves_the_colours_forward_along_the_index_list():
    """The direction `step` means. Rotating the palette so slot j takes the colour from
    slot j - step is the same picture as leaving the palette alone and sending a pixel at
    indices[j] to indices[j - step], so a region painted with the first index takes the
    last one's colour and the band travels forward."""
    remaps = indexed.cycle_remaps([5, 6, 7, 8], 4, 1)

    assert remaps[0] == {}, "frame 1 is the drawn frame and comes back untouched"
    assert remaps[1] == {5: 8, 6: 5, 7: 6, 8: 7}
    assert remaps[3] == {5: 6, 6: 7, 7: 8, 8: 5}
    assert indexed.cycle_remaps([5, 6, 7, 8], 2, -1)[1] == {5: 6, 6: 7, 7: 8, 8: 5}, (
        "a negative step travels the other way"
    )


@pytest.mark.pure
def test_the_runs_the_art_uses_are_reported_longest_first():
    """A cycle wants a span of entries that reads as a ramp, and the only way to find one
    before this was to read every pixel through get_pixels and count by hand."""
    assert indexed.usage_runs([1, 2, 3, 7, 8, 20]) == [
        {"first": 1, "last": 3, "length": 3},
        {"first": 7, "last": 8, "length": 2},
        {"first": 20, "last": 20, "length": 1},
    ]


@pytest.mark.pure
def test_a_cycle_that_does_not_close_says_which_frame_count_would():
    """Not a refusal: a cycle that stops mid-rotation is a fine thing to hold under a tag
    that does not loop. But a caller who meant it to loop needs the number."""
    notes = indexed.cycle_readings([1, 2, 3, 4], 3, 1, {1: 9, 2: 9, 3: 9, 4: 9})

    assert len(notes) == 1
    assert "does not return the colours to where they started" in notes[0]
    assert "A multiple of 4 frame(s) closes it" in notes[0]
    assert indexed.cycle_readings([1, 2, 3, 4], 4, 1, {1: 9, 2: 9, 3: 9, 4: 9}) == [], (
        "four frames at step 1 over four indices closes, and silence is the right answer"
    )


@pytest.mark.pure
def test_an_index_that_cannot_draw_is_refused_from_the_same_place_as_one_out_of_range():
    """Two separate things in a palette mean "no pixel here" and both have to be kept out
    of a cycle: the sprite's transparent index, and an entry whose own alpha is 0. Testing
    only the first is the #138 failure arriving by a new route, because rotating either
    one in makes drawn pixels vanish on one frame."""
    colors = ["#00000000", "#1b3a5cff", "#00000000", "#4a90c2ff"]
    drawn = {1: 10, 3: 10}

    with pytest.raises(ValidationFailed, match="transparent index"):
        indexed.cycle_indices([0, 1, 3], colors, 0, drawn)
    with pytest.raises(ValidationFailed, match="fully transparent and so draws nothing"):
        indexed.cycle_indices([1, 2, 3], colors, 0, drawn)
    with pytest.raises(ValidationFailed, match="palette has 4 entries, numbered 0-3"):
        indexed.cycle_indices([1, 3, 9], colors, 0, drawn)
    with pytest.raises(ValidationFailed, match="already in the cycle"):
        indexed.cycle_indices([1, 3, 3], colors, 0, drawn)
    assert indexed.cycle_indices([1, 3], colors, 0, drawn) == [1, 3]


@pytest.mark.pure
def test_a_cycle_the_art_does_not_use_is_refused_with_the_indices_it_does():
    """Every frame would be a copy of the drawn one: the sprite grows, the GIF does not
    animate, and every tool reports success. The refusal hands over the answer the caller
    actually needed, which is what list_palette_usage is for."""
    with pytest.raises(ValidationFailed, match="indices the art is actually drawn with"):
        indexed.cycle_indices([2, 3], ["#00000000"] + ["#112233ff"] * 4, 0, {1: 40, 4: 40})


@pytest.mark.pure
def test_a_step_of_a_whole_lap_is_refused_rather_than_drawing_the_same_frame_twice():
    with pytest.raises(ValidationFailed, match="not a multiple of 4"):
        indexed.cycle_step(4, 4)
    with pytest.raises(ValidationFailed, match="not a multiple of 4"):
        indexed.cycle_step(0, 4)
    assert indexed.cycle_step(-1, 4) == -1


@pytest.mark.pure
def test_a_palette_with_no_three_entries_in_a_row_says_there_is_no_ramp_to_cycle():
    """Two entries swapping back and forth read as a flicker rather than as flow, so a
    sprite whose used indices are scattered gets told before it gets a cycle."""
    notes = indexed.palette_usage_readings(
        {"size": 16, "drawn": {1: 20, 5: 20, 11: 20}, "out_of_range": 0})

    assert any("never 3 in a row" in note for note in notes)
    assert indexed.palette_usage_readings(
        {"size": 16, "drawn": {1: 20, 2: 20, 3: 20}, "out_of_range": 0}) == []


@pytest.mark.pure
def test_pixels_pointing_past_the_end_of_the_palette_are_named():
    """A palette resized smaller than its art leaves pixels carrying offsets there is no
    entry to read: every colour question about them has no answer at all, not a near one."""
    notes = indexed.palette_usage_readings(
        {"size": 4, "drawn": {1: 20, 2: 20, 3: 20}, "out_of_range": 17})

    assert "17 pixel(s) carry an index at or past the end of this 4-entry palette" in (
        " ".join(notes)
    )


# ----------------------------------------------------- against a real indexed sprite
def test_a_cycled_sprite_animates_and_its_palette_is_untouched(request):
    """The whole point of the fallback, checked both ways round. The frames differ, which
    is what makes it an animation, and the palette comes back exactly as it was written,
    which is what makes it cycling rather than recolouring."""
    name = _pond(request)
    before = palette.get_palette(name)

    result = palette.cycle_palette(name, [1, 2, 3, 4])

    assert result["method"] == "pixel_remap", "the fallback, and it says so"
    assert result["frame_count"] == 4
    assert result["closes"] is True
    assert "warnings" not in result, (
        "absent rather than empty, like the rest of this module: a warnings key here "
        "always means there is something in it"
    )
    assert palette.get_palette(name) == before, (
        "what rotates is the pixels; the palette is not touched"
    )
    assert len(set(_hashes(name, 4))) == 4, "four frames, four different pictures"


def test_the_exported_gif_animates_too(request):
    """The issue's acceptance criterion: a GIF, checked by comparing exported frame hashes
    rather than by eye. The pixel-remap fallback is the option that survives an export at
    all, which is why it is the one that shipped."""
    name = _pond(request)
    palette.cycle_palette(name, [1, 2, 3, 4])
    out = f"ixc/{request.node.name}.gif"

    export.export_gif(name, out, overwrite=True)

    hashes = _hashes(out, 4)
    assert len(set(hashes)) == 4, "the exported GIF's four frames are four pictures"
    assert hashes == _hashes(name, 4), (
        "and they are the sprite's own frames, so the export did not resample anything"
    )


def test_the_rotation_is_the_one_the_step_promised(request):
    """Not just "the frames differ": frame 2's picture is frame 1's with every index moved
    one place back along the cycle, which is the same picture a palette rotated one place
    forward would have shown."""
    name = _pond(request, width=8, height=4)
    first = inspect.get_pixels(name, 0, 0, 8, 4)["pixels"]

    palette.cycle_palette(name, [1, 2, 3, 4], frame_count=2)

    second = inspect.get_pixels(name, 0, 0, 8, 4, frame=2)["pixels"]
    wheel = [f"{c}ff" for c in WATER]
    expected = [
        [wheel[(wheel.index(px) - 1) % 4] for px in row] for row in first
    ]
    assert second == expected


def test_a_cycle_can_be_scoped_to_one_layer(request):
    """A waterfall cycles; the rock behind it does not."""
    name = _pond(request, width=8, height=4)
    layers.add_layer(name, "rock")
    drawing.draw_rectangle(name, 0, 0, 4, 2, "index:1", filled=True, layer="rock")
    rock_before = inspect.get_pixels(name, 0, 0, 8, 4, layer="rock")["pixels"]

    result = palette.cycle_palette(name, [1, 2, 3, 4], layer="Layer 1")

    assert {entry["layer"] for entry in result["remapped"]} == {"Layer 1"}
    for frame in (2, 3, 4):
        assert inspect.get_pixels(
            name, 0, 0, 8, 4, frame=frame, layer="rock")["pixels"] == rock_before


def test_list_palette_usage_finds_the_run_worth_cycling(request):
    """The companion tool, and the thing `get_palette` cannot answer: a palette says what
    colours exist, this says which of them the picture is painted with."""
    name = _pond(request)
    palette.add_palette_color(name, "#ff00ff")

    usage = palette.list_palette_usage(name)

    assert [entry["index"] for entry in usage["used"]] == [1, 2, 3, 4]
    assert all(entry["pixels"] == 96 for entry in usage["used"])
    assert usage["used"][0]["color"] == f"{WATER[0]}ff"
    assert usage["runs"][0] == {"first": 1, "last": 4, "length": 4}
    assert usage["unused"] == [5], "the colour nothing is drawn with"
    assert usage["transparent_index"] == 0
    assert "readings" not in usage, "a palette with a ramp in it is not worth a word"


def test_an_index_whose_entry_is_transparent_is_not_counted_as_used(request):
    """Two separate things mean "nothing here" on an indexed sprite, and a tool that tests
    only the sprite's transparent index is the #138 failure waiting to happen again: an
    entry whose own alpha is 0 draws nothing either, whatever index it sits at.

    The pixels are really there, written with `index:2` and reported by `get_pixels`, so
    the only thing separating them from art is the palette. They are counted, under
    `transparent_pixels`, and kept out of `used` so that a cycle planned from this answer
    cannot rotate an invisible entry into itself.
    """
    name = f"ixc/{request.node.name}.aseprite"
    sprite.create_sprite(name, 8, 4, color_mode="indexed")
    palette.set_palette(name, ["#00000000", WATER[0], "#00000000", WATER[2]])
    drawing.draw_rectangle(name, 0, 0, 8, 2, "index:1", filled=True)
    drawing.draw_rectangle(name, 0, 2, 8, 2, "index:2", filled=True)

    usage = palette.list_palette_usage(name)

    assert [entry["index"] for entry in usage["used"]] == [1], (
        "entry 2 holds 16 pixels and cannot draw one of them"
    )
    assert usage["used"][0]["pixels"] == 16
    assert usage["transparent_pixels"] == 16
    assert usage["scanned_pixels"] == 32, "every pixel was counted, drawable or not"


def test_list_palette_usage_can_be_scoped_to_a_frame_and_a_layer(request):
    """Scoping matters for the question `cycle_palette` asks of it: whether the art *in
    scope* uses the indices about to be cycled."""
    name = _pond(request, width=8, height=4)
    frames.add_frame(name)
    drawing.draw_rectangle(name, 0, 0, 8, 4, "index:2", filled=True, frame=2)

    whole = palette.list_palette_usage(name)
    second = palette.list_palette_usage(name, frame=2)

    assert [entry["index"] for entry in second["used"]] == [2]
    assert second["frames_scanned"] == {"first": 2, "last": 2}
    assert whole["scanned_pixels"] > second["scanned_pixels"]
    assert palette.list_palette_usage(name, layer="Layer 1")["layers_scanned"] == [
        "Layer 1"
    ]


def test_an_rgb_sprite_has_no_indices_to_count_or_cycle(request):
    """An RGB pixel carries its own colour, so there is no offset to rotate. Refused with
    the tools that do answer the colour-census question for such a sprite."""
    name = f"ixc/{request.node.name}.aseprite"
    sprite.create_sprite(name, 8, 8)

    with pytest.raises(AsepriteError, match="extract_palette"):
        palette.list_palette_usage(name)
    with pytest.raises(AsepriteError, match="set_color_mode"):
        palette.cycle_palette(name, [1, 2, 3])


def test_a_sprite_that_already_animates_is_refused_rather_than_redefined(request):
    """A cycle generates the whole timeline from one drawn frame, so there is no honest
    way to write it over an animation that is already there."""
    name = _pond(request, width=8, height=4)
    frames.add_frame(name)

    with pytest.raises(ValidationFailed, match="redefine the animation"):
        palette.cycle_palette(name, [1, 2, 3, 4])


def test_an_index_outside_this_sprites_palette_is_refused_before_anything_is_written(
    request,
):
    """The acceptance criterion: validated against the palette's size, which is only
    knowable with the file open, and the sprite still has its one frame afterwards."""
    name = _pond(request, width=8, height=4)

    with pytest.raises(ValidationFailed, match="palette has 5 entries, numbered 0-4"):
        palette.cycle_palette(name, [1, 2, 99])

    assert inspect.get_sprite_info(name)["frameCount"] == 1, "nothing was written"
