"""Every write path, held to the selection it says it applied.

These exist because nine of them did not. `img_set` in the prelude was the only write that
consulted the mask, and the anti-aliased coverage write, the flood fill, every per-pixel
effect pass, `mirror_layer` and the batch runner's replace op all called `Image:drawPixel`
directly: they edited the whole layer while the harness stamped `selection_applied: true`,
which it sets from `_sel ~= nil` and cannot tell whether the body honoured.

That is the inverse of the gap in #181, and the worse half of it. A missing count can be
noticed. A result that asserts a selection was applied when it was not cannot.

So each test here asserts **the pixels outside the selection**, not a count. A count can be
satisfied by a tool that wrote the right number of pixels in the wrong places, and these
tools were reporting numbers that looked fine while painting the whole canvas.

Every case is built so that it would fail without the fix: the tool is aimed at something
that is *outside* the mask, so honouring the mask and doing nothing are distinguishable.
"""

from __future__ import annotations

import re

import pytest

from aseprite_mcp.tools import (
    batch,
    brushes,
    drawing,
    effects,
    inspect,
    selection,
    sprite,
)

W, H = 16, 8
BASE = "#ff0000"
PAINT = "#0000ff"


def sprite_name(request) -> str:
    """A filename from the test's own name, with the parametrisation made safe.

    `request.node.name` for a parametrised case carries `[`, `]`, `<` and `>`, none of
    which are legal in a Windows filename, so the first version of this file built paths
    the filesystem refused. The error surfaced from `discard_selection_sidecar`, which
    raises rather than swallowing an unlink it cannot do (#182), and said exactly what was
    wrong.
    """
    return f"scope/{re.sub(r'[^A-Za-z0-9_]+', '_', request.node.name)}.aseprite"


@pytest.fixture()
def half_masked(request):
    """A red canvas with only the right half selected.

    Anything a tool does to the left half is a write that escaped the mask.
    """
    name = sprite_name(request)
    sprite.create_sprite(name, W, H, overwrite=True)
    # A crashed earlier run can leave a `.msk` beside a sprite of this name, and
    # `create_sprite` discards it (#182); this is belt and braces for a fixture that would
    # otherwise fail in a way that looks like the bug under test.
    selection.deselect(name)
    drawing.fill_layer(name, BASE)
    selection.select_region(name, "rect", x=W // 2, y=0, width=W // 2, height=H)
    return name


def halves(name: str) -> tuple[set[str], set[str]]:
    rows = inspect.get_pixels(name, 0, 0, W, H)["pixels"]
    left = {px[:7].lower() for row in rows for px in row[: W // 2]}
    right = {px[:7].lower() for row in rows for px in row[W // 2 :]}
    return left, right


def assert_scoped(name: str, result: dict) -> None:
    """The mask held, the tool still did its job, and the result says what the mask ate."""
    left, right = halves(name)
    assert left == {BASE}, f"wrote outside the selection: {sorted(left)}"
    assert right != {BASE}, (
        "nothing changed inside the selection either, so this test cannot tell a scoped "
        "write from a no-op"
    )
    assert result.get("selection_applied") is True
    assert result.get("pixels_outside_selection", 0) > 0, (
        "the mask refused pixels, so the count has to say so"
    )


# ===== the shared prelude, which is most of the blast radius ==========================


def test_a_flood_fill_does_not_leak_out_of_the_selection(half_masked):
    """A masked pixel is a wall, not a hole.

    Not painting it is only half the answer. The fill must not spread *through* it either,
    or it leaks around the selection and paints the far side of the region the mask was
    there to protect. This fill starts inside the selection on a canvas that is one
    connected colour, so a fill that traverses masked pixels covers everything.
    """
    result = drawing.fill_area(half_masked, W - 2, H // 2, PAINT)
    assert_scoped(half_masked, result)


def test_an_antialiased_line_does_not_write_outside_the_selection(half_masked):
    """The coverage write blends and then stores, and used to store unconditionally."""
    result = drawing.draw_line(half_masked, 0, H // 2, W - 1, H // 2, PAINT, antialias=True)
    assert_scoped(half_masked, result)


def test_an_antialiased_ellipse_does_not_write_outside_the_selection(half_masked):
    result = drawing.draw_ellipse(
        half_masked, W // 2 + 2, H // 2, 5, 3, PAINT, filled=True, antialias=True)
    assert_scoped(half_masked, result)


def test_a_hard_edged_line_still_behaves_exactly_as_before(half_masked):
    """The path that was always right, pinned so the refactor cannot have moved it."""
    result = drawing.draw_line(half_masked, 0, H // 2, W - 1, H // 2, PAINT)
    assert_scoped(half_masked, result)
    assert result["pixels_written"] == W // 2
    assert result["pixels_outside_selection"] == W // 2


# ===== the per-pixel effect passes ====================================================


@pytest.mark.parametrize(
    "label,call",
    [
        ("invert_colors", lambda n: effects.invert_colors(n)),
        ("desaturate", lambda n: effects.desaturate(n)),
        ("brightness", lambda n: effects.adjust_brightness_contrast(n, brightness=60)),
        ("hue", lambda n: effects.adjust_hue_saturation(n, hue=120)),
        ("replace_color", lambda n: effects.replace_color(n, BASE, "#00ff00")),
    ],
)
def test_an_effect_pass_only_touches_the_selection(half_masked, label, call):
    """All five share `_pixel_pass`, which walked the whole image and wrote every pixel."""
    result = call(half_masked)
    assert_scoped(half_masked, result)
    # The whole canvas was offered and exactly half of it refused, which is the shape of
    # a pass that walks everything and is clipped at the write.
    assert result["pixels_outside_selection"] == W * H // 2


def test_an_outline_is_clipped_to_the_selection(half_masked):
    result = effects.add_outline(half_masked, "#000000", where="inside")
    assert_scoped(half_masked, result)


# ===== mirror_layer, where the write side is the point ================================


def test_mirror_layer_will_not_write_into_the_masked_half(request):
    """Aimed entirely at masked pixels, so honouring the mask means writing nothing.

    The source side is inside the selection and the destination side is outside it, which
    is the only arrangement that tells a scoped mirror from an unscoped one: with the
    selection on the destination side every write lands inside it either way.
    """
    name = sprite_name(request)
    sprite.create_sprite(name, W, H, overwrite=True)
    selection.deselect(name)
    drawing.fill_layer(name, BASE)
    drawing.draw_rectangle(name, 0, 0, 4, H, PAINT, filled=True)
    selection.select_region(name, "rect", x=0, y=0, width=W // 2, height=H)

    result = brushes.mirror_layer(name, "Layer 1", direction="horizontal",
                                  source_side="first")

    _left, right = halves(name)
    assert right == {BASE}, f"mirrored into the masked half: {sorted(right)}"
    assert result["pixels_written"] == 0
    assert result["pixels_outside_selection"] == W * H // 2


# ===== the batch runner ===============================================================


def test_a_batched_replace_colour_is_clipped_too(half_masked):
    """`apply_operations` runs the ops through the same prelude, so it inherits the fix.

    Its manifest now carries the harness's report at the top level, which is what #201
    settled, so `assert_scoped` reads it exactly as it reads the eighteen bare-dict
    results above: that one shared helper working on a manifest is the whole argument for
    the counters being top-level keys rather than a `pixels` section of their own.

    Before that, the manifest reported `status: applied` for an op whose every offered
    pixel the mask had refused, and the only thing this test could check was the canvas.
    """
    manifest = batch.apply_operations(
        half_masked,
        [{"op": "replace_color", "args": {"from_color": BASE, "to_color": "#00ff00"}}],
    )

    left, right = halves(half_masked)
    assert left == {BASE}, f"the batch wrote outside the selection: {sorted(left)}"
    assert right == {"#00ff00"}

    assert_scoped(half_masked, manifest)
    # The whole canvas was offered to a colour replace and exactly half of it refused,
    # which is the count the manifest used to drop. Asserted as the literal here because
    # the fixture's geometry is what fixes it: 16x8 with the right half selected.
    assert manifest["pixels_written"] == W * H // 2
    assert manifest["pixels_outside_selection"] == W * H // 2
    # And the manifest is still a manifest, not a bare result wearing one's name.
    assert manifest["schema_version"] == "workflow_manifest.v1"
    assert manifest["operations"][0]["status"] == "applied"


# ===== and the other direction: no selection, nothing changes =========================


@pytest.mark.parametrize(
    "label,call",
    [
        ("fill_area", lambda n: drawing.fill_area(n, 6, H // 2, PAINT)),
        ("antialiased line", lambda n: drawing.draw_line(
            n, 0, H // 2, W - 1, H // 2, PAINT, antialias=True)),
        ("invert_colors", lambda n: effects.invert_colors(n)),
        ("mirror_layer", lambda n: brushes.mirror_layer(
            n, "Layer 1", direction="horizontal", source_side="first")),
        # A manifest answers this question the same way a bare result does, which is the
        # other half of #201: the counters are absent, not zero, when nothing was masked.
        ("batched replace_color", lambda n: batch.apply_operations(
            n, [{"op": "replace_color",
                 "args": {"from_color": PAINT, "to_color": "#00ff00"}}])),
    ],
)
def test_with_no_selection_nothing_is_scoped_and_nothing_is_reported(request, label, call):
    """The half of the behaviour that had to stay exactly as it was.

    The fix threads a mask check through paths that never had one, so the case with no
    mask is the regression risk: a tool that started clipping, or counting, or reporting
    `selection_applied` when no selection exists would be a new bug of the same family.

    The canvas is deliberately not uniform. On a flat red one, mirroring copies red onto
    red and inverting is the only case that visibly does anything, so three of these four
    could not have told a working tool from one that wrote nothing.
    """
    name = sprite_name(request)
    sprite.create_sprite(name, W, H, overwrite=True)
    selection.deselect(name)
    drawing.fill_layer(name, BASE)
    drawing.draw_rectangle(name, 0, 0, 4, H, PAINT, filled=True)
    before = inspect.get_pixels(name, 0, 0, W, H)["pixels"]

    result = call(name)

    assert "selection_applied" not in result
    assert "pixels_outside_selection" not in result
    after = inspect.get_pixels(name, 0, 0, W, H)["pixels"]
    assert after != before, "with no selection the whole canvas is fair game"


# ===== and the counts the tools keep themselves ======================================
#
# `pixels_written` comes from the prelude and was always right. The number each of these
# tools reports *beside* it did not: it was tallied where the write was offered rather
# than where it landed, and `img_set` refuses a write outside the mask silently. So a
# half-masked canvas produced two counts in one result that disagreed by exactly the
# pixels the mask ate, and the tool's own was the headline one.
#
# Asserted as an equality against `pixels_written` rather than against a literal, because
# the literal is what a reader would have to trust and the equality is the claim.


def _tally_cases():
    from aseprite_mcp.tools import shading

    ramp = ["#2a2a3a", "#3f3f58", "#5a5a7a", "#7a7a9c", "#9c9cc0"]
    return [
        ("shift_along_ramp", "pixels_matched",
         lambda n: shading.shift_along_ramp(n, ramp, steps=-1)),
        ("dither_band", "dithered_pixels",
         lambda n: shading.dither_band(n, ramp, from_step=3, to_step=4)),
        ("gradient_map", None, lambda n: shading.gradient_map(n, ramp)),
    ]


@pytest.mark.parametrize("label,field,call", _tally_cases(),
                         ids=[c[0] for c in _tally_cases()])
def test_a_tools_own_pixel_count_agrees_with_what_landed(request, label, field, call):
    """Two numbers in one result that have to add up, and did not.

    The canvas is painted in two ramp steps so `dither_band` has a boundary to work on,
    and only the right half is selected, so every tool here is offered twice the pixels it
    is allowed to write.
    """
    ramp = ["#2a2a3a", "#3f3f58", "#5a5a7a", "#7a7a9c", "#9c9cc0"]
    name = sprite_name(request)
    sprite.create_sprite(name, W, H, overwrite=True)
    selection.deselect(name)
    drawing.fill_layer(name, ramp[2])
    drawing.draw_rectangle(name, 0, 0, W, H // 2, ramp[3], filled=True)
    selection.select_region(name, "rect", x=W // 2, y=0, width=W // 2, height=H)

    result = call(name)

    written = result["pixels_written"]
    assert result["pixels_outside_selection"] > 0, (
        "the mask has to have refused something or this proves nothing"
    )
    if field is not None:
        assert result[field] == written, (
            f"{label} reported {field}={result[field]} with pixels_written={written}"
        )
    else:
        # gradient_map's number is a histogram, so the claim is about its total.
        assert sum(result["per_step"]) == written, (
            f"per_step sums to {sum(result['per_step'])} with pixels_written={written}"
        )


def test_outline_smart_counts_the_outline_it_drew_not_the_one_it_planned(request):
    """Collected first and written after, so the plan and the result can differ.

    A shape in the middle of the canvas with only the right half selected: half the
    outline it plans is refused, and `outline_pixels` used to report the whole plan.
    """
    from aseprite_mcp.tools import shading

    ramp = ["#2a2a3a", "#3f3f58", "#5a5a7a", "#7a7a9c", "#9c9cc0"]
    name = sprite_name(request)
    sprite.create_sprite(name, 16, 16, overwrite=True)
    selection.deselect(name)
    drawing.draw_rectangle(name, 4, 4, 8, 8, ramp[2], filled=True)
    selection.select_region(name, "rect", x=8, y=0, width=8, height=16)

    result = shading.outline_smart(name, ramp)

    assert result["pixels_outside_selection"] > 0
    assert result["outline_pixels"] == result["pixels_written"]


def test_remove_stray_pixels_counts_only_the_specks_it_reached(request):
    """Two specks, one inside the selection and one outside it.

    `erased` and `erased_clusters` used to count both, so the result claimed the canvas
    had been cleaned in a place the call was never allowed to touch.
    """
    name = sprite_name(request)
    sprite.create_sprite(name, 16, 16, overwrite=True)
    selection.deselect(name)
    drawing.draw_pixels(name, [{"x": 2, "y": 2}, {"x": 13, "y": 13}], PAINT)
    selection.select_region(name, "rect", x=8, y=0, width=8, height=16)

    result = effects.remove_stray_pixels(name, erase_isolated=True)

    rows = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]
    assert not rows[2][2].endswith("00"), "the speck outside the mask must survive"
    assert rows[13][13].endswith("00"), "the speck inside the mask must be gone"
    assert result["erased"] == 1, result
    assert result["erased_clusters"] == 1, result


# ===== a new layer with nothing on it is not an effect ================================


@pytest.mark.parametrize(
    "label,call",
    [
        ("glow", lambda n: effects.glow(
            n, ["#2a2a3a", "#5a5a7a", "#9c9cc0"], radius=2)),
        ("cast_shadow", lambda n: effects.cast_shadow(
            n, "Layer 1", ["#2a2a3a", "#5a5a7a", "#9c9cc0"])),
        ("add_drop_shadow", lambda n: effects.add_drop_shadow(n, "Layer 1")),
    ],
)
def test_an_effect_the_mask_ate_entirely_is_refused_not_layered(request, label, call):
    """These two paint into a brand-new image and then add it as a layer.

    With the selection in a corner the effect never reaches, every write was refused and
    the tools' own tallies did not notice: `glow` returned `glow_pixels: 56` beside
    `pixels_written: 0`, added a layer with nothing at all on it, and walked straight past
    its own `painted == 0` refusal, which is the only thing that could have caught it.
    """
    from aseprite_mcp.core.errors import AsepriteError

    name = sprite_name(request)
    sprite.create_sprite(name, 32, 32, overwrite=True)
    selection.deselect(name)
    drawing.draw_rectangle(name, 12, 10, 8, 12, "#9c9cc0", filled=True)
    before = [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]
    selection.select_region(name, "rect", x=0, y=0, width=2, height=2)

    with pytest.raises(AsepriteError, match="outside the active selection"):
        call(name)

    after = [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]
    assert after == before, f"{label} added a layer for an effect it did not paint"
