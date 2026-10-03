"""A smear's own colours against the palette that has to hold them (issue #173).

`smear_frame` was the one ramp-taking tool the #145 palette reading never reached, and it
was exempted on purpose rather than overlooked: it resolves the ramp in Python into a
colour-to-colour lookup table and never passes a ramp to Lua, so the harness, which keys
on `ARG.ramp`, had nothing to measure.

The snap happened anyway. Every target colour in that table goes through `rgba_to_px`
like any other colour, so on an indexed sprite two shift levels can resolve to one
palette entry and two trail copies come out identical. Measured before the fix on the
fixture below: `#6b2d4a` (shift 3) and `#2c1b2e` (shift 4) both resolved to entry 1, the
smeared frame came back with 88 pixels of `#2c1b2e`, 44 of `#b04a5a`, none at all of
`#6b2d4a`, `pixels_written: 388`, and `warnings == []`.

The question is deliberately not the one #145 asks. There it is "which of the declared
ramp steps can this palette hold"; here the ramp is already spent and it is "which of this
table's target colours resolve to the same entry". The declared ramp has five steps and
this palette holds three, but only three of the five are ever targets, so measuring the
ramp would report a collision between two steps nothing shifts far enough to reach.

Every sprite here is built indexed from the start (`create_sprite(color_mode="indexed")`,
`set_palette`, then draw) rather than by converting an RGB one, because the palette is the
whole point of these cases and a quantization would decide it for us.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import inbetween, indexed
from aseprite_mcp.tools import animation, cels, drawing, frames, inspect, palette, sprite

# Darkest first, the order `generate_ramp` returns and every shading tool here expects.
RAMP = ["#2c1b2e", "#6b2d4a", "#b04a5a", "#e07a5f", "#f2cc8f"]


def _slide(request, colors: list[str], draw: str, mode: str = "indexed") -> str:
    """A disc that moves 36px a frame over four frames, on a palette we chose by hand.

    Named after the requesting test: the workspace fixture is session-scoped and
    `create_sprite` is no-clobber, so a shared filename would make every test after the
    first fail on that rather than on what it is checking.
    """
    name = f"ixs/{request.node.name}.aseprite"
    sprite.create_sprite(name, 64, 40, color_mode=mode)
    if mode == "indexed":
        palette.set_palette(name, ["#00000000", *colors])
    drawing.draw_ellipse(name, 10, 20, 5, 5, draw, filled=True)
    for _ in range(3):
        frames.add_frame(name)
    for f in (2, 3, 4):
        cels.copy_cel(name, "Layer 1", 1, f)
    animation.offset_cels(name, "Layer 1", [1, 2, 3, 4], dx=36)
    return name


# ------------------------------------------------------------------- the arithmetic
@pytest.mark.pure
def test_the_targets_measured_are_the_tables_own_and_not_the_declared_ramp():
    """The distinction the issue turns on. A subject on step 4 shifted by 1, 3 and 4 asks
    the palette for three colours; the ramp it came from has five. Measuring five would
    report a collision between two steps no plot ever reaches."""
    ramp_rgb = [(int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)) for c in RAMP]
    colors = [{"px": 3, "r": 0xF2, "g": 0xCC, "b": 0x8F}]

    table = inbetween.shift_table(colors, ramp_rgb, [1, 3, 4])
    targets = inbetween.shift_table_targets(table)

    assert len(targets) == 3, "three shifts in use, three colours asked for"
    assert [(t["r"], t["g"], t["b"]) for t in targets] == [
        ramp_rgb[3], ramp_rgb[1], ramp_rgb[0],
    ], "shift ascending, so shift 1's target first"


@pytest.mark.pure
def test_two_shifts_on_one_entry_are_grouped_by_the_subject_colour_they_came_from():
    """The pair the table contains, not a count. A subject with two materials in it can
    band in one of them and step cleanly in the other, so the group names the raw pixel
    value as well as the entry."""
    table = {
        1: {5: {"r": 10, "g": 10, "b": 10}, 9: {"r": 90, "g": 90, "b": 90}},
        2: {5: {"r": 20, "g": 20, "b": 20}, 9: {"r": 91, "g": 91, "b": 91}},
    }
    # Targets in order: (10,10,10), (90,90,90), (20,20,20), (91,91,91). Pixel 9's two
    # targets land on entry 7 together; pixel 5's land on 3 and 4.
    collisions = inbetween.shift_table_collisions(table, [3, 7, 4, 7])

    assert collisions == [
        {"px": 9, "index": 7, "shifts": [1, 2], "wants": ["#5a5a5a", "#5b5b5b"]},
    ]


@pytest.mark.pure
def test_a_palette_holding_every_target_is_not_worth_a_word():
    """The reading must not become noise on the arrangement this server recommends."""
    table = {1: {5: {"r": 10, "g": 10, "b": 10}}, 2: {5: {"r": 20, "g": 20, "b": 20}}}

    collisions = inbetween.shift_table_collisions(table, [3, 4])

    assert collisions == []
    assert indexed.shift_table_readings(
        {"declared": 2, "resolved": 2, "exact": 2, "steps": []}, collisions) == []


@pytest.mark.pure
def test_the_sentence_names_the_copies_rather_than_the_ramp_steps():
    """`ramp_readings`' wording is about declared ramp steps and would be wrong here: what
    merges is a trail copy. Pinned because sharing that function was the tempting shortcut
    and it answers a different question."""
    state = {"declared": 3, "resolved": 2, "exact": 1, "steps": []}
    collisions = [
        {"px": 3, "index": 1, "shifts": [3, 4], "wants": ["#6b2d4a", "#2c1b2e"]},
    ]

    notes = indexed.shift_table_readings(state, collisions)

    assert len(notes) == 1
    assert "The copies at shifts 3 and 4" in notes[0]
    assert "2 of the 3 colours this trail asks for" in notes[0]
    assert "declared ramp" not in notes[0], "that is the other question"
    assert "not the headroom warning" in notes[0], (
        "the two findings sit side by side and a reader has to be able to tell them apart"
    )


# ------------------------------------------------------- against a real indexed sprite
def test_two_shift_levels_landing_on_one_entry_are_reported(request):
    """The defect. The palette holds ramp steps 0, 2 and 4; the subject is drawn in step
    4; `mode="echo"` with `steps=3` plots shifts 1, 3 and 4. Shift 3 asks for `#6b2d4a`
    and shift 4 for `#2c1b2e`, and both resolve to entry 1, so two of the three copies
    come out the same colour.

    Nothing caught this before. `pixels_written` counts writes that happened, the ramp
    headroom warning is correctly silent (the subject has four steps below it and the
    deepest shift is four), and `palette_conformance` reads 1.0 because the colour landed
    on is still on the declared ramp. The only place the finding can come from is the
    palette.
    """
    name = _slide(request, [RAMP[0], RAMP[2], RAMP[4]], RAMP[4])

    result = animation.smear_frame(
        name, "Layer 1", 3, mode="echo", steps=3, ramp=RAMP, strength=1.0)

    assert sorted(p["shift"] for p in result["plots"]) == [1, 3, 4]
    measured = result["trail_on_palette"]
    assert (measured["declared"], measured["resolved"]) == (3, 2), (
        "three target colours asked for, two distinct entries got"
    )
    warning = " ".join(result["warnings"])
    assert "shifts 3 and 4" in warning
    assert "2 of the 3 colours this trail asks for" in warning
    assert "come out the same colour" in warning

    # And the picture agrees: shift 3's colour is nowhere in the frame, and the entry the
    # two of them merged onto carries both copies.
    seen: dict[str, int] = {}
    for row in inspect.get_pixels(name, 0, 0, 64, 40, frame=3)["pixels"]:
        for px in row:
            seen[px] = seen.get(px, 0) + 1
    assert f"{RAMP[1]}ff" not in seen, "the colour shift 3 asked for was never written"
    assert seen[f"{RAMP[0]}ff"] > seen[f"{RAMP[2]}ff"], (
        "two copies on the merged entry against one on the entry that held its own"
    )

    # The metric that is supposed to separate shading from filtering is blind to it,
    # which is why the reading comes from the palette and not from the pixels.
    assert inspect.assess_sprite(
        name, frame=3, layer="Layer 1", ramp=RAMP
    )["metrics"]["palette_conformance"] == 1.0


def test_a_palette_built_from_the_ramp_says_nothing(request):
    """The arrangement this server recommends. Every target is in the palette exactly, so
    the measurement is taken, comes back clean, and no warning is produced."""
    name = _slide(request, RAMP, RAMP[4])

    result = animation.smear_frame(
        name, "Layer 1", 3, mode="echo", steps=3, ramp=RAMP, strength=1.0)

    measured = result["trail_on_palette"]
    assert measured["declared"] == measured["resolved"] == measured["exact"] == 3
    assert result["warnings"] == [], "a palette that holds the trail is not worth a word"


def test_an_rgb_smear_is_never_told_about_a_palette(request):
    """An RGB pixel carries its own colour and there is no palette to snap to, so the
    measurement is skipped rather than computed and found uninteresting."""
    name = _slide(request, [], RAMP[4], mode="rgb")

    result = animation.smear_frame(
        name, "Layer 1", 3, mode="echo", steps=3, ramp=RAMP, strength=1.0)

    assert "trail_on_palette" not in result
    assert result["warnings"] == []


def test_the_reading_does_not_replace_the_headroom_warning(request):
    """Both findings are real and independent: one measures the art (how many ramp steps
    exist below the subject's lightest colour), the other the palette. A subject drawn in
    a middle step of a sparse palette raises both, and dropping either would trade a
    finding for a finding."""
    name = _slide(request, [RAMP[0], RAMP[2], RAMP[4]], RAMP[2])

    result = animation.smear_frame(
        name, "Layer 1", 3, mode="echo", steps=3, ramp=RAMP, strength=1.0)

    joined = " ".join(result["warnings"])
    assert "only 2 step(s) exist below it" in joined, "the headroom finding, about the art"
    assert "come out the same colour" in joined, "the palette finding, about the palette"
