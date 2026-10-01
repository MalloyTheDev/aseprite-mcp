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
