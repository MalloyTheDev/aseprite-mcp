"""The indexed-mode judgement, without an editor: enums and the starting palette.

Pure Python. What a real Aseprite has to answer (does the art survive a conversion, does
a draw land visibly) is in `test_indexed_sprites.py`; this is the part that must hold on
CI, where there is no editor to launch, and it is also the part that decides whether a
bad argument costs a rejected call or an Aseprite process.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import indexed
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_COLOR_LIST_LENGTH
from aseprite_mcp.core.models import ColorSpec


def _spec(color: str) -> dict:
    return ColorSpec.parse(color).as_dict()


# ------------------------------------------------------------------ colour modes
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("rgb", "rgb"),
        ("RGB", "rgb"),
        ("  indexed  ", "indexed"),
        ("gray", "gray"),
        ("grey", "gray"),
        ("grayscale", "gray"),
        ("greyscale", "gray"),
        ("GreyScale", "gray"),
    ],
)
def test_the_spellings_people_type_all_resolve(given, expected):
    assert indexed.normalise_color_mode(given) == expected


def test_rgba_is_refused_rather_than_read_as_rgb():
    """"rgba" is not a fourth mode: an RGB sprite here always has an alpha channel, so
    accepting it would be guessing which of the three modes was meant."""
    with pytest.raises(ValidationFailed, match="color_mode"):
        indexed.normalise_color_mode("rgba")


@pytest.mark.parametrize("given", ["", "bogus", "index", "palette", None, 7])
def test_an_unknown_colour_mode_is_refused(given):
    with pytest.raises(ValidationFailed):
        indexed.normalise_color_mode(given)


def test_the_refusal_lists_the_modes_but_not_every_spelling():
    """A caller needs to be told what to say, not how many ways there are to say it."""
    with pytest.raises(ValidationFailed) as err:
        indexed.normalise_color_mode("rgba")
    message = str(err.value)
    assert "gray, indexed, rgb" in message
    assert "greyscale" not in message
    assert "'rgba'" in message, "the rejected value is quoted back"


# ------------------------------------------------------------------ dithering
@pytest.mark.parametrize("given", list(indexed.DITHERING_ALGORITHMS))
def test_every_advertised_dithering_algorithm_is_accepted(given):
    assert indexed.normalise_dithering(given) == given


def test_a_misspelled_dithering_algorithm_is_refused():
    """Aseprite accepts `dithering = "no-such-dither"` without a word and converts with
    its default, so an unvalidated typo reports success having done something else."""
    with pytest.raises(ValidationFailed, match="dithering"):
        indexed.normalise_dithering("ordered-bayer")


# ------------------------------------------------------------------ palette source
@pytest.mark.parametrize("given", list(indexed.PALETTE_SOURCES))
def test_every_palette_source_is_accepted(given):
    assert indexed.normalise_palette_source(given) == given


def test_an_unknown_palette_source_is_refused():
    with pytest.raises(ValidationFailed, match="palette_source"):
        indexed.normalise_palette_source("quantize")


# ------------------------------------------------------- the new-sprite palette
def test_index_zero_is_transparent():
    """The transparent index is 0, so entry 0 is the one offset that means "no pixel
    here". Aseprite's own default palette puts opaque black there, which makes a request
    for black resolve to the index that draws nothing."""
    assert indexed.DEFAULT_INDEXED_PALETTE[0] == "#00000000"


def test_black_is_still_available_further_up():
    """Spending entry 0 on transparency must not cost the palette its black: black is
    the commonest colour in pixel art and the one an outline is drawn with."""
    assert "#000000ff" in indexed.DEFAULT_INDEXED_PALETTE[1:]


def test_every_other_entry_is_a_distinct_opaque_colour():
    rest = indexed.DEFAULT_INDEXED_PALETTE[1:]
    assert len(rest) == 32
    assert all(entry.endswith("ff") for entry in rest), "all opaque"
    assert len(set(rest)) == len(rest), "no duplicates to waste a slot"
    assert all(len(entry) == 9 and entry.startswith("#") for entry in rest)


def test_the_default_palette_fits_the_palette_ceiling():
    """`palette_for_new_sprite` feeds a palette tool, so it is bounded by the same
    ceiling every other route to a palette is, background colour included."""
    longest = indexed.palette_for_new_sprite(_spec("#123456"))
    assert len(longest) <= MAX_COLOR_LIST_LENGTH


def test_no_background_gives_the_default_palette_unchanged():
    assert indexed.palette_for_new_sprite(None) == list(indexed.DEFAULT_INDEXED_PALETTE)


def test_a_background_colour_is_added_so_it_can_be_exact():
    """An indexed sprite holds only colours its palette names. Substituting the nearest
    default colour for the one the caller gave would be doing less than claimed."""
    colors = indexed.palette_for_new_sprite(_spec("#1d2b53"))

    assert colors[-1] == "#1d2b53ff"
    assert len(colors) == len(indexed.DEFAULT_INDEXED_PALETTE) + 1
    assert colors[:-1] == list(indexed.DEFAULT_INDEXED_PALETTE), "the default is intact"


def test_a_background_already_in_the_palette_is_not_duplicated():
    colors = indexed.palette_for_new_sprite(_spec("#ac3232"))

    assert colors == list(indexed.DEFAULT_INDEXED_PALETTE)
    assert colors.count("#ac3232ff") == 1


def test_a_semi_transparent_background_keeps_its_alpha():
    """Alpha is part of the entry, not rounded away: Aseprite palettes carry per-entry
    alpha and the conversion tools rely on it."""
    colors = indexed.palette_for_new_sprite(_spec("#1d2b5380"))

    assert colors[-1] == "#1d2b5380"


def test_a_transparent_background_is_not_added_twice_over():
    """"transparent" parses to #00000000, which entry 0 already is."""
    assert indexed.palette_for_new_sprite(_spec("transparent")) == list(
        indexed.DEFAULT_INDEXED_PALETTE
    )


def test_an_index_background_adds_nothing():
    """`index:N` names an offset rather than a colour, so there is nothing to add; the
    default palette has to be deep enough for the index to resolve against."""
    colors = indexed.palette_for_new_sprite(_spec("index:5"))

    assert colors == list(indexed.DEFAULT_INDEXED_PALETTE)
    assert len(colors) > 5


# ------------------------------------ entries a palette holds and cannot draw (#143)
def _state(size, transparent_index, at_transparent_index, drawable):
    return {"size": size, "transparent_index": transparent_index,
            "at_transparent_index": at_transparent_index, "drawable": drawable}


def test_an_opaque_colour_at_the_transparent_index_is_reported():
    """It is in the palette, get_palette returns it, and it can never be drawn: a
    request for it resolves to the nearest entry that can be."""
    notes = indexed.palette_readings(
        _state(2, 0, "#000000ff", 1), "indexed")

    assert notes, "an unreachable entry said nothing"
    assert "entry 0 is #000000ff" in notes[0]
    assert "set_transparent_color" in notes[0], "the remedy is not named"


def test_a_transparent_entry_at_the_transparent_index_is_the_normal_case():
    """The usual arrangement, and it must not produce a warning anyone has to read."""
    assert indexed.palette_readings(_state(3, 0, "#00000000", 2), "indexed") == []


@pytest.mark.parametrize("mode", ["rgb", "gray"])
def test_nothing_is_said_about_a_mode_that_has_no_transparent_index(mode):
    """An RGB or grayscale pixel carries its own alpha, so `transparentColor` means
    nothing there and an opaque entry at index 0 is unremarkable. Warning about it
    would be noise a caller cannot act on."""
    assert indexed.palette_readings(_state(2, 0, "#000000ff", 1), mode) == []


def test_a_palette_with_nothing_drawable_says_so_separately():
    """The #138 condition. Worth its own sentence because the remedy is different: the
    palette needs a colour added, not reordered."""
    notes = indexed.palette_readings(_state(4, 0, "#00000000", 0), "indexed")

    assert any("None of this palette" in n for n in notes)
    assert any("add_palette_color" in n for n in notes)


def test_a_transparent_index_past_the_end_of_the_palette_shadows_nothing():
    """`at_transparent_index` is None when the index is out of range, and nothing is
    hidden, so there is nothing to report about it."""
    assert indexed.palette_readings(_state(2, 9, None, 2), "indexed") == []


def test_several_undrawable_entries_are_counted_rather_than_listed():
    notes = indexed.palette_readings(_state(8, 0, "#00000000", 3), "indexed")

    assert any("5 of 8" in n for n in notes)


def test_a_state_the_lua_never_measured_does_not_raise():
    """`palette_readings` is handed whatever the measurement produced, so a missing
    field has to be survivable rather than an exception in a reporting path."""
    assert indexed.palette_readings({}, "indexed") == []
    assert indexed.palette_readings({}, "") == []

# ----------------------------------------------- a ramp against the palette (#145)
# Every one of these is the arithmetic of "what did the ramp become", with no editor
# involved. What Aseprite actually does to the pixels is in test_indexed_sprites.py.
def _step(step: int, want: str, index: int, got: str) -> dict:
    return {"step": step, "want": want, "index": index, "got": got,
            "exact": want == got}


def _ramp_state(*steps: dict) -> dict:
    return {
        "steps": list(steps),
        "declared": len(steps),
        "resolved": len({s["index"] for s in steps}),
        "exact": sum(1 for s in steps if s["exact"]),
    }


def test_a_ramp_the_palette_holds_exactly_says_nothing():
    """The normal case, and it has to be silent. A palette built from the ramp
    (`generate_ramp` then `set_palette`) is the arrangement this server recommends, so a
    warning here would fire on every correct use and teach the caller to ignore it."""
    state = _ramp_state(
        _step(1, "#1a1a2eff", 1, "#1a1a2eff"),
        _step(2, "#3d3d5cff", 2, "#3d3d5cff"),
        _step(3, "#6b6b8fff", 3, "#6b6b8fff"),
    )

    assert indexed.ramp_readings(state) == []


def test_two_steps_resolving_to_one_entry_are_named():
    """The measured reproduction: a five-step ramp against a palette holding three of
    its colours. Steps 1 and 2 both land on entry 1, so a one-step shade between them
    rewrote 144 pixels to the colour they already were and reported success."""
    state = _ramp_state(
        _step(1, "#1a1a2eff", 1, "#1a1a2eff"),
        _step(2, "#3d3d5cff", 1, "#1a1a2eff"),
        _step(3, "#6b6b8fff", 2, "#6b6b8fff"),
        _step(4, "#9a9ac2ff", 2, "#6b6b8fff"),
        _step(5, "#ccccf0ff", 3, "#ccccf0ff"),
    )

    notes = indexed.ramp_readings(state)

    assert notes, "a ramp that collapses has to say so"
    first = notes[0]
    assert "3 of the 5" in first
    assert "steps 1 and 2" in first and "steps 3 and 4" in first
    assert "#3d3d5cff" in first, "the colour that was lost is named"
    assert "palette_conformance" in first, (
        "the reading has to say why the usual metric will not show this"
    )


def test_the_no_op_is_stated_rather_than_implied():
    """The finding a caller cannot reach any other way. Two steps on one entry means a
    shade between them changes nothing, and neither the pixel counts nor
    palette_conformance will say so: the colour landed on is still on the ramp."""
    state = _ramp_state(
        _step(1, "#111111ff", 1, "#111111ff"),
        _step(2, "#222222ff", 1, "#111111ff"),
    )

    joined = " ".join(indexed.ramp_readings(state))

    assert "changes nothing" in joined
    assert "reports the pixels it wrote" in joined


def test_a_ramp_that_collapses_to_a_single_colour_says_there_is_no_ramp():
    """The catastrophic end of the same scale. Distinct from the banding case: nothing
    the tool writes can vary at all, so "it will band" understates it."""
    state = _ramp_state(
        _step(1, "#1a1a2eff", 1, "#808080ff"),
        _step(2, "#3d3d5cff", 1, "#808080ff"),
        _step(3, "#6b6b8fff", 1, "#808080ff"),
    )

    joined = " ".join(indexed.ramp_readings(state))

    assert "no ramp on this sprite to shade along" in joined
    assert "#808080ff" in joined


def test_steps_that_shift_but_stay_distinct_are_reported_more_softly():
    """Every step on a different entry means the shading keeps its shape; the colours
    are simply not the declared ones. That is worth a line and not an alarm, because it
    is what snapping to a fixed palette means and refusing it would make these tools
    useless on the sprites that most want one."""
    state = _ramp_state(
        _step(1, "#1a1a2eff", 1, "#191930ff"),
        _step(2, "#3d3d5cff", 2, "#3c3c5aff"),
        _step(3, "#6b6b8fff", 3, "#6b6b8fff"),
        _step(4, "#ccccf0ff", 4, "#cdcdf1ff"),
    )

    notes = indexed.ramp_readings(state)

    joined = " ".join(notes)
    assert "nearest entry" in joined
    assert "shading holds its shape" in joined
    assert "changes nothing" not in joined, "nothing collapsed, so say nothing about it"


def test_a_long_ramp_names_a_few_shifted_steps_and_stops():
    """A reading is a sentence, not a table. Twelve shifted steps listed in full is the
    measurement again rather than a finding."""
    state = _ramp_state(*[
        _step(i, f"#{i:02x}{i:02x}{i:02x}ff", i, f"#{i + 1:02x}{i + 1:02x}{i + 1:02x}ff")
        for i in range(1, 13)
    ])

    joined = " ".join(indexed.ramp_readings(state))

    assert "12 of the 12" in joined
    assert joined.count(" as #") == 4, "four examples named"
    assert "and 8 more" in joined, "and the rest counted rather than listed"


def test_a_ramp_state_the_lua_never_measured_does_not_raise():
    """Same contract as `palette_readings`: this is a reporting path handed whatever the
    measurement produced, so an absent or empty measurement is silence, not an
    exception. The harness omits `ramp_on_palette` entirely on RGB and gray sprites."""
    assert indexed.ramp_readings({}) == []
    assert indexed.ramp_readings({"steps": [], "declared": 0}) == []
    assert indexed.ramp_readings({"declared": 3}) == []


def test_a_palette_that_can_draw_nothing_says_so_rather_than_nothing():
    """The measurement cannot resolve a single step here, because `nearest_index` has no
    candidate to offer. That is reported rather than left as silence: a shading tool on
    such a sprite writes nothing and *succeeds*, since there was nothing to write, and
    the reason it had no effect is a fact about the palette that nothing else in the
    result mentions.
    """
    notes = indexed.ramp_readings(
        {"steps": [], "declared": 4, "resolved": 0, "exact": 0,
         "undrawable_palette": True})

    assert len(notes) == 1
    assert "no entry that can draw a visible pixel" in notes[0]
    assert "4 declared ramp steps" in notes[0]
    assert "set_palette" in notes[0], "and what to do about it"
