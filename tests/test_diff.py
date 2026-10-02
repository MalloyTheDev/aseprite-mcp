"""Comparing two frames: requires Aseprite (--run-aseprite).

`test_spritediff.py` checks what the counts mean. This checks that the counts are right,
which only a real editor can answer, and concentrates on the three places where the scan
takes a shortcut: `Image:isEqual` over the whole frame, a row of `Image.bytes` against the
other buffer, and the byte stride that counts visible pixels without touching getPixel. A
shortcut that is wrong about alpha or about byte order reports a confident wrong number,
so each one is checked against the slow answer it is standing in for.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import (
    cels,
    drawing,
    effects,
    frames,
    inspect,
    layers,
    palette,
    selection,
    sprite,
)


def _two_frames(request, size: int = 16, suffix: str = "") -> str:
    """One sprite, two identical frames holding a solid block."""
    name = f"diff/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, size, size)
    frames.add_frame(name)
    for f in (1, 2):
        drawing.draw_rectangle(name, 4, 4, 8, 8, "#6b4a2f", filled=True, frame=f)
    return name


def _drawn_by_hand(name: str, size: int, frame: int = 1, layer: str | None = None) -> int:
    """Visible pixels counted the slow, obvious way: one getPixel per pixel."""
    total = 0
    for y0 in range(0, size, 64):
        rows = inspect.get_pixels(name, 0, y0, size, min(64, size - y0),
                                  frame=frame, layer=layer)["pixels"]
        total += sum(1 for row in rows for px in row if px[7:9] != "00")
    return total


def _box_by_hand(name: str, size: int, frame: int = 1, layer: str | None = None):
    """The content box read the slow way, from the same pixels `_drawn_by_hand` counts.

    The point of having both is that the shortcut must agree with itself: `drawn_pixels`
    and `content` are two readings of one definition of "drawn", and this is that
    definition spelled out independently of the prelude that implements it. `get_pixels`
    reports RGBA whatever the colour mode, so a pixel held in a palette entry whose own
    alpha is 0 arrives here with alpha 00 and is not content, which is exactly the case
    the two fields used to answer differently.
    """
    xs: list[int] = []
    ys: list[int] = []
    for y0 in range(0, size, 64):
        rows = inspect.get_pixels(name, 0, y0, size, min(64, size - y0),
                                  frame=frame, layer=layer)["pixels"]
        for dy, row in enumerate(rows):
            for x, px in enumerate(row):
                if px[7:9] != "00":
                    xs.append(x)
                    ys.append(y0 + dy)
    if not xs:
        return None
    return {"x": min(xs), "y": min(ys),
            "width": max(xs) - min(xs) + 1, "height": max(ys) - min(ys) + 1}


# ------------------------------------------------------- the buckets, from real edits
def test_two_identical_frames_say_nothing_changed(request):
    name = _two_frames(request)
    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert result["identical"] is True
    assert result["change"] == "identical"
    assert result["metrics"]["changed_pixels"] == 0
    assert "Nothing changed" in result["readings"][0]


def test_a_pixel_added_outside_the_shape_is_a_silhouette_change(request):
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], "#ffffff", frame=2)

    metrics = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert metrics["silhouette_added"] == 1
    assert metrics["silhouette_removed"] == 0
    assert metrics["interior_changed"] == 0
    assert metrics["change_box"] == {"x": 1, "y": 1, "width": 1, "height": 1}


def test_a_pixel_erased_from_the_shape_is_the_other_direction(request):
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 5, "y": 5}], "transparent", frame=2)

    metrics = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert (metrics["silhouette_added"], metrics["silhouette_removed"]) == (0, 1)


def test_a_repaint_inside_the_shape_leaves_the_silhouette_alone(request):
    name = _two_frames(request)
    drawing.draw_rectangle(name, 4, 4, 8, 4, "#3a2418", filled=True, frame=2)

    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert result["change"] == "interior"
    assert result["metrics"]["interior_changed"] == 32
    assert result["metrics"]["silhouette_added"] == 0
    assert result["metrics"]["silhouette_removed"] == 0


def test_an_opacity_change_is_coverage_rather_than_a_repaint(request):
    """The distinction the issue for this tool got wrong: a pixel can change without its
    colour changing, and calling that a repaint sends you looking for the wrong bug."""
    name = _two_frames(request)
    cels.set_cel_opacity(name, "Layer 1", 2, 128)

    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert result["change"] == "coverage"
    assert result["metrics"]["coverage_changed"] == 64
    assert result["metrics"]["interior_changed"] == 0


def test_a_repaint_and_an_erase_together_name_the_silhouette(request):
    name = _two_frames(request)
    drawing.draw_rectangle(name, 4, 4, 8, 2, "#3a2418", filled=True, frame=2)
    drawing.draw_pixels(name, [{"x": 11, "y": 11}], "transparent", frame=2)

    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert result["change"] == "silhouette"
    assert result["metrics"]["interior_changed"] == 16
    assert result["metrics"]["silhouette_removed"] == 1


def test_the_buckets_add_up_to_the_total(request):
    """They are reported as a breakdown, so they have to be a partition: a pixel counted
    twice or not at all would make every share wrong."""
    name = _two_frames(request)
    drawing.draw_rectangle(name, 4, 4, 8, 3, "#3a2418", filled=True, frame=2)
    drawing.draw_pixels(name, [{"x": 2, "y": 2}, {"x": 3, "y": 2}], "#ffffff", frame=2)
    drawing.draw_pixels(name, [{"x": 10, "y": 10}], "transparent", frame=2)

    m = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert m["changed_pixels"] == (
        m["silhouette_added"] + m["silhouette_removed"]
        + m["interior_changed"] + m["coverage_changed"]
    )


# ---------------------------------------------------- the shortcuts, against the truth
def _indexed(request, suffix: str = "") -> str:
    """An 8x8 indexed sprite with a stated palette: 16 drawn pixels in frame 1, none in 2.

    Built index by index rather than by converting an RGB sprite, because the palette is
    the whole point of the cases below and a quantization would decide it for us.
    """
    name = f"diff/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    palette.set_palette(name, ["#00000000", "#6b4a2fff", "#ffffff00"])
    frames.add_frame(name)
    drawing.draw_rectangle(name, 2, 2, 4, 4, "index:1", filled=True, frame=1)
    return name


@pytest.mark.parametrize("mode", ["rgb", "gray"])
def test_the_byte_stride_count_agrees_with_counting_by_hand(request, mode):
    """`drawn_pixels` reads alpha at a fixed stride in Image.bytes instead of calling
    getPixel per pixel, which is only correct if the byte order is what it assumes. A
    wrong guess here is invisible: it just makes every share wrong by a constant."""
    name = _two_frames(request, suffix=mode)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}, {"x": 14, "y": 14}], "#c08040", frame=1)
    if mode != "rgb":
        sprite.set_color_mode(name, mode)

    reported = inspect.diff_sprites(name, 1, other_frame=2)["a"]["drawn_pixels"]

    assert reported == _drawn_by_hand(name, 16, frame=1)
    assert reported == 66


def test_the_indexed_count_agrees_with_counting_by_hand(request):
    name = _indexed(request)

    reported = inspect.diff_sprites(name, 1, other_frame=2)["a"]["drawn_pixels"]

    assert reported == _drawn_by_hand(name, 8, frame=1)
    assert reported == 16


def test_a_transparent_palette_entry_counts_as_undrawn(request):
    """Indexed transparency is two separate things: the sprite's transparent index, and a
    palette entry that is itself fully transparent. A count that tests only the first
    reports an empty canvas as drawn, which is the bug this server has already been
    bitten by once."""
    name = _indexed(request)
    drawing.draw_pixels(name, [{"x": 0, "y": 0}], "index:2", frame=1)

    reported = inspect.diff_sprites(name, 1, other_frame=2)["a"]["drawn_pixels"]

    assert reported == 16, "index 2 is #ffffff00, so that pixel is not drawn"


def test_the_content_box_and_the_count_agree_about_a_transparent_palette_entry(request):
    """One result, one definition of drawn. These two fields used to have two.

    `drawn_pixels` came from the prelude's byte scan, which treats both kinds of indexed
    transparency as empty, and `content` came from `Image:shrinkBounds`, which honours
    the transparent index only. So a pixel held in a palette entry whose own alpha is 0
    was nothing to the count and content to the box, and the result reported both numbers
    next to each other (#172). Measured before the fix on this sprite: `drawn_pixels: 16`
    beside a 5x5 box at 2,2, whose last row and column nothing in the sprite can draw.
    """
    name = _indexed(request)
    drawing.draw_pixels(name, [{"x": 6, "y": 6}], "index:2", frame=1)

    side = inspect.diff_sprites(name, 1, other_frame=2)["a"]

    assert side["drawn_pixels"] == _drawn_by_hand(name, 8, frame=1) == 16
    assert side["content"] == _box_by_hand(name, 8, frame=1)
    assert side["content"] == {"x": 2, "y": 2, "width": 4, "height": 4}, (
        "the box grew to cover a pixel the count correctly excluded"
    )


def test_the_sprite_from_the_report_measures_the_same_both_ways(request):
    """The 8x8 sprite the defect was measured on, built index by index as it was there.

    Transparent index 0, index 1 an opaque brown, index 2 a palette entry that is itself
    fully transparent; art at 2,2 to 3,3 in index 1 and one pixel at 6,6 in index 2.
    `shrinkBounds` answered 5x5 at 2,2 for that, beside a count of 4.
    """
    name = f"diff/{request.node.name}.aseprite"
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    palette.set_palette(name, ["#00000000", "#6b4a2fff", "#ffffff00"])
    frames.add_frame(name)
    drawing.draw_rectangle(name, 2, 2, 2, 2, "index:1", filled=True, frame=1)
    drawing.draw_pixels(name, [{"x": 6, "y": 6}], "index:2", frame=1)

    side = inspect.diff_sprites(name, 1, other_frame=2)["a"]

    assert side["drawn_pixels"] == 4
    assert side["content"] == {"x": 2, "y": 2, "width": 2, "height": 2}


def test_a_side_with_nothing_drawn_has_no_content_box(request):
    """No box at all rather than a zero-sized rectangle, so an empty frame cannot be
    read as one holding a pixel at the origin.

    The key is absent rather than null, which is what a nil in the Lua result table
    becomes and what this reported before the box moved into the prelude. Pinned as it
    is rather than changed, since the shape of the empty case is not what #172 was about.
    """
    name = _two_frames(request)
    layers.add_layer(name, name="blank")

    side = inspect.diff_sprites(name, 1, other_frame=2, layer="blank")["a"]

    assert side["drawn_pixels"] == 0
    assert "content" not in side
    assert _box_by_hand(name, 16, frame=1, layer="blank") is None


@pytest.mark.parametrize("mode", ["rgb", "gray"])
def test_the_content_box_is_unchanged_on_a_sprite_with_one_kind_of_transparency(
    request, mode
):
    """Only indexed sprites had two answers, so only they may change answer.

    On RGB and grayscale `shrinkBounds` and the byte scan agree by construction, and this
    pins that the box moving into the prelude did not shift it by a pixel: 4x3 at 5,7 on
    both, measured.
    """
    name = f"diff/{request.node.name}{mode}.aseprite"
    sprite.create_sprite(name, 32, 32, "rgb")
    drawing.draw_rectangle(name, 5, 7, 4, 3, "#c08040", filled=True, frame=1)
    if mode != "rgb":
        sprite.set_color_mode(name, mode)
    frames.add_frame(name)

    side = inspect.diff_sprites(name, 1, other_frame=2)["a"]

    assert side["content"] == _box_by_hand(name, 32, frame=1)
    assert side["content"] == {"x": 5, "y": 7, "width": 4, "height": 3}


def test_a_change_on_the_last_row_is_found(request):
    """The row scan compares one row of Image.bytes at a time, so an off-by-one in the
    stride loses the first or the last row and reports a real edit as identical."""
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 15, "y": 15}], "#ffffff", frame=2)

    assert inspect.diff_sprites(name, 1, other_frame=2)["metrics"]["changed_pixels"] == 1


def test_a_change_on_the_first_row_is_found(request):
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 0, "y": 0}], "#ffffff", frame=2)

    assert inspect.diff_sprites(name, 1, other_frame=2)["metrics"]["changed_pixels"] == 1


def test_changes_in_distant_rows_are_all_found(request):
    name = _two_frames(request, size=64)
    spots = [{"x": 1, "y": 0}, {"x": 2, "y": 31}, {"x": 3, "y": 63}]
    drawing.draw_pixels(name, spots, "#ffffff", frame=2)

    m = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert m["changed_pixels"] == 3
    assert m["change_box"] == {"x": 1, "y": 0, "width": 3, "height": 64}


def test_rgb_under_a_transparent_pixel_is_not_a_change(request):
    """`Image:isEqual` treats two fully transparent pixels as equal whatever bytes sit
    under them and a byte comparison does not. Whichever of the two the tool believed,
    the other would contradict it, so the per-pixel scan is the authority and this is
    the case that proves it: filling transparent-with-colour over transparent changes
    the buffer and changes nothing anybody can see."""
    name = _two_frames(request)
    drawing.draw_rectangle(name, 0, 0, 16, 2, "#ff000000", filled=True, frame=2)

    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert result["identical"] is True, result["metrics"]
    assert "Nothing changed" in result["readings"][0]


def test_an_indexed_sprite_against_its_rgb_self_compares_fine(request):
    """Different colour modes have different byte layouts, so the row shortcut cannot
    run; both sides are read as RGBA instead. An indexed sprite and its RGB export are
    the same art, and the diff has to agree."""
    name = _indexed(request)
    copied = name.replace(".aseprite", "-rgb.aseprite")
    sprite.save_sprite_as(name, copied)
    sprite.set_color_mode(copied, "rgb")

    result = inspect.diff_sprites(name, 1, other=copied, other_frame=1)

    assert result["a"]["color_mode"] == "indexed"
    assert result["b"]["color_mode"] == "rgb"
    assert result["identical"] is True, result["metrics"]
    assert result["metrics"]["drawn_union"] == 16


# --------------------------------------------------------------------- layer scoping
def test_an_edit_on_one_layer_is_invisible_in_another_layers_diff(request):
    """The reason layer= exists. A composite diff answers "did the picture change"; a
    layer diff answers "did my edit land", and those are different questions whenever
    more than one layer is in play."""
    name = f"diff/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    layers.add_layer(name, "shade")
    drawing.draw_rectangle(name, 2, 2, 12, 12, "#204020", filled=True, layer="Layer 1")
    before = name.replace(".aseprite", "-before.aseprite")
    sprite.save_sprite_as(name, before)
    drawing.draw_pixels(name, [{"x": 5, "y": 5}], "#ff0000", layer="shade")

    on_it = inspect.diff_sprites(before, other=name, layer="shade")
    not_on_it = inspect.diff_sprites(before, other=name, layer="Layer 1")

    assert on_it["metrics"]["silhouette_added"] == 1
    assert not_on_it["identical"] is True
    assert inspect.diff_sprites(before, other=name)["metrics"]["changed_pixels"] == 1


def test_two_layers_of_one_sprite_can_be_compared_against_each_other(request):
    name = f"diff/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    layers.add_layer(name, "copy")
    drawing.draw_rectangle(name, 2, 2, 6, 6, "#204020", filled=True, layer="Layer 1")
    drawing.draw_rectangle(name, 2, 2, 6, 6, "#204020", filled=True, layer="copy")

    assert inspect.diff_sprites(name, layer="Layer 1",
                                other_layer="copy")["identical"] is True


# ------------------------------------------------------------- what it does not touch
def test_a_diff_never_writes_to_either_sprite(request):
    """It opens two documents and renders frames into scratch images. If it ever saved,
    it would be an editing tool wearing an inspector's name, and the before-copy an
    agent diffs against would stop being a before-copy."""
    name = _two_frames(request)
    other = name.replace(".aseprite", "-b.aseprite")
    sprite.save_sprite_as(name, other)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], "#ffffff", frame=2)
    paths = [inspect.get_sprite_info(n)["path"] for n in (name, other)]
    import pathlib
    before = [pathlib.Path(p).read_bytes() for p in paths]

    inspect.diff_sprites(name, 1, other=other, other_frame=2)

    assert [pathlib.Path(p).read_bytes() for p in paths] == before


def test_a_selection_does_not_scope_the_comparison(request):
    """A selection lives in a sidecar and is reloaded on open, which is what lets it
    scope an edit across calls. A diff is a question about the whole frame, so it must
    not inherit one: a diff that silently reported only the selected pixels would be
    wrong in exactly the situation where you are least likely to check."""
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], "#ffffff", frame=2)
    selection.select_region(name, x=8, y=8, width=4, height=4)

    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert result["metrics"]["changed_pixels"] == 1, "the change is outside the selection"
    assert "selection_applied" not in result
    selection.deselect(name)


# ------------------------------------------------------------------- shares and boxes
def test_changed_share_is_measured_against_the_drawn_art(request):
    name = _two_frames(request)
    drawing.draw_rectangle(name, 4, 4, 8, 4, "#3a2418", filled=True, frame=2)

    m = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert m["drawn_union"] == 64, "8x8 of art on a 16x16 canvas"
    assert m["changed_share"] == 0.5


def test_pixels_that_appeared_count_towards_the_drawn_union(request):
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 0, "y": 0}, {"x": 1, "y": 0}], "#ffffff", frame=2)

    m = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert m["drawn_union"] == 66
    assert m["changed_share"] == round(2 / 66, 3)


def test_scattered_noise_is_reported_as_noise(request):
    """The case this is for: a pass that left dirt across the canvas rather than editing
    a region. The density of the change box is what separates the two."""
    name = _two_frames(request, size=32)
    drawing.draw_rectangle(name, 8, 8, 16, 16, "#6b4a2f", filled=True, frame=1)
    drawing.draw_rectangle(name, 8, 8, 16, 16, "#6b4a2f", filled=True, frame=2)
    strays = [{"x": x, "y": y} for x, y in ((2, 2), (29, 3), (4, 28), (27, 26))]
    drawing.draw_pixels(name, strays, "#ff00ff", frame=2)

    result = inspect.diff_sprites(name, 1, other_frame=2)

    assert any("scattered" in note for note in result["readings"])
    assert any("remove_stray_pixels" in note for note in result["readings"])


def test_removing_the_noise_again_brings_the_frames_back_together(request):
    """The round trip an agent actually runs: make a mess, clean it, confirm.

    The strays go *inside* the shape because that is the dirt remove_stray_pixels
    answers for: a lone pixel on empty canvas has no opaque neighbour to take a colour
    from, and erasing it would change the silhouette.
    """
    name = _two_frames(request, size=32)
    for f in (1, 2):
        drawing.draw_rectangle(name, 8, 8, 16, 16, "#6b4a2f", filled=True, frame=f)
    drawing.draw_pixels(name, [{"x": 12, "y": 12}, {"x": 19, "y": 18}], "#ff00ff",
                        frame=2)
    assert inspect.diff_sprites(name, 1, other_frame=2)["metrics"]["interior_changed"] == 2

    assert effects.remove_stray_pixels(name, frame=2)["replaced"] == 2

    assert inspect.diff_sprites(name, 1, other_frame=2,
                                expect="identical")["verdict"]["passed"] is True


def test_the_colours_involved_in_the_change_are_named(request):
    name = _two_frames(request)
    drawing.draw_rectangle(name, 4, 4, 8, 4, "#3a2418", filled=True, frame=2)

    m = inspect.diff_sprites(name, 1, other_frame=2)["metrics"]

    assert m["colors_before"] == [{"color": "#6b4a2fff", "pixels": 32}]
    assert m["colors_after"] == [{"color": "#3a2418ff", "pixels": 32}]
    assert m["colors_introduced"] == [{"color": "#3a2418ff", "pixels": 32}]


# ------------------------------------------------------------------------- verdicts
def test_an_expectation_that_holds_passes(request):
    name = _two_frames(request)
    drawing.draw_rectangle(name, 4, 4, 8, 4, "#3a2418", filled=True, frame=2)

    v = inspect.diff_sprites(name, 1, other_frame=2, expect="interior")["verdict"]

    assert v["passed"] is True


def test_an_expectation_that_does_not_hold_fails_with_the_measurement(request):
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], "#ffffff", frame=2)

    v = inspect.diff_sprites(name, 1, other_frame=2, expect="interior")["verdict"]

    assert v["passed"] is False
    assert "measured a silhouette one" in v["errors"][0]


def test_no_verdict_is_offered_when_none_was_asked_for(request):
    """Different is not wrong. A tool that graded every difference would be guessing at
    what the caller meant, and it would be wrong most of the time."""
    name = _two_frames(request)
    drawing.draw_pixels(name, [{"x": 1, "y": 1}], "#ffffff", frame=2)

    assert "verdict" not in inspect.diff_sprites(name, 1, other_frame=2)


# ------------------------------------------------------------------------- refusals
def test_different_canvas_sizes_are_refused_with_both_content_boxes(request):
    """A diff of differently sized frames is an offset question in disguise, and the
    content boxes are what answer it, so they are in the refusal."""
    small = _two_frames(request, suffix="-small")
    big = f"diff/{request.node.name}-big.aseprite"
    sprite.create_sprite(big, 32, 32)
    drawing.draw_rectangle(big, 10, 10, 8, 8, "#6b4a2f", filled=True)

    with pytest.raises(AsepriteError) as exc:
        inspect.diff_sprites(small, other=big)

    message = str(exc.value)
    assert "16x16" in message and "32x32" in message
    assert "8x8 at 4,4" in message and "8x8 at 10,10" in message
    assert "trim_sprite" in message


@pytest.mark.pure
def test_comparing_a_frame_with_itself_is_refused(request):
    with pytest.raises(ValidationFailed, match="compare a frame with itself"):
        inspect.diff_sprites("unused.aseprite")


@pytest.mark.pure
def test_an_unknown_expectation_is_refused_before_aseprite_is_launched():
    with pytest.raises(ValidationFailed, match="expect must be one of"):
        inspect.diff_sprites("unused.aseprite", 1, other_frame=2, expect="moved")


def test_a_frame_that_does_not_exist_says_so(request):
    name = _two_frames(request)
    with pytest.raises(AsepriteError, match="other_frame 9 does not exist"):
        inspect.diff_sprites(name, 1, other_frame=9)


def test_a_missing_second_sprite_says_which_one(request):
    name = _two_frames(request)
    with pytest.raises(AsepriteError, match="sprite to compare against"):
        inspect.diff_sprites(name, other="diff/not-here.aseprite")
