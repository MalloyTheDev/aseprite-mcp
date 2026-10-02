"""Palette quantization judgement: pure Python, always runs (CI tier).

`core.quantization` reads the result of a derived palette. The reason it exists is a
measured cliff in the one argument a caller controls: on 1.3.18.6, four distinct opaque
colours quantized with `max_colors=4` came back as two entries, one transparent and one
mid-grey that is the average of all four, while `max_colors=5` on the same art returned
all four exactly. Every call involved reported success, and nothing in the palette says
the art has been flattened to a single tone.

These tests pin what is said in each case, and, as much as that, what is *not* said when
the palette is fine.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import quantization
from aseprite_mcp.core.errors import ValidationFailed


def state(**over) -> dict:
    """A healthy measurement: 8 colours of art, all 8 in a 9-entry palette."""
    base = {
        "requested": 16,
        "size": 9,
        "drawable": 8,
        "art_scanned": True,
        "art_colors": 8,
        "art_colors_exact": 8,
        "art_colors_capped": False,
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ the argument
def test_the_palette_ceiling_is_the_cap():
    assert quantization.check_max_colors(256) == 256
    with pytest.raises(ValidationFailed, match="maximum is 256"):
        quantization.check_max_colors(257)


def test_fewer_than_two_colours_is_refused():
    """One entry is the transparent one the command reserves, so a one-colour palette
    can draw nothing. `max_colors=0` was accepted by the editor and produced a palette
    of three, which is not a reading of the argument anyone could predict."""
    with pytest.raises(ValidationFailed, match="minimum is 2"):
        quantization.check_max_colors(1)
    with pytest.raises(ValidationFailed, match="minimum is 2"):
        quantization.check_max_colors(0)


def test_a_count_written_as_text_is_accepted():
    assert quantization.check_max_colors("16") == 16


def test_a_count_that_is_not_a_number_is_refused():
    with pytest.raises(ValidationFailed, match="whole number"):
        quantization.check_max_colors("lots")


# ------------------------------------------------------------------ the readings
def test_a_palette_that_holds_the_art_says_nothing():
    """The point of the whole module: silence is the normal outcome, so a `warnings` key
    always means there is something to act on."""
    assert quantization.quantization_readings(state()) == []


def test_the_collapse_is_named_and_a_bigger_number_is_suggested():
    notes = quantization.quantization_readings(
        state(requested=4, size=2, drawable=1, art_colors=4, art_colors_exact=0)
    )
    joined = " ".join(notes)
    assert "single tone" in joined
    # The measured fix: one more than the number of colours in the art.
    assert "max_colors=5" in joined


def test_a_palette_with_nothing_drawable_says_so_first():
    notes = quantization.quantization_readings(
        state(requested=4, size=1, drawable=0, art_colors=4, art_colors_exact=0)
    )
    assert "cannot hold the art at all" in notes[0]


def test_one_drawable_entry_for_one_colour_of_art_is_not_a_complaint():
    """A sprite painted in a single colour quantizes to a single colour correctly. The
    reading has to be about the art, not about the number 1."""
    notes = quantization.quantization_readings(
        state(requested=8, size=2, drawable=1, art_colors=1, art_colors_exact=1)
    )
    assert notes == []


def test_stopping_short_of_the_ceiling_is_reported():
    notes = quantization.quantization_readings(
        state(requested=32, size=6, drawable=5, art_colors=20, art_colors_exact=5)
    )
    joined = " ".join(notes)
    assert "asked for up to 32" in joined
    assert "came back with 6" in joined


def test_a_small_palette_for_simple_art_is_not_reported_as_stopping_short():
    """Three colours of art and a four-entry palette is the right answer to
    max_colors=32, and a warning there would train a caller to ignore warnings."""
    notes = quantization.quantization_readings(
        state(requested=32, size=4, drawable=3, art_colors=3, art_colors_exact=3)
    )
    assert notes == []


def test_approximation_is_reported_with_the_shortfall():
    notes = quantization.quantization_readings(
        state(requested=16, size=9, drawable=8, art_colors=40, art_colors_exact=8)
    )
    joined = " ".join(notes)
    assert "32 of the 40 colours" in joined
    assert "nearest entry" in joined


def test_a_capped_scan_says_at_least_rather_than_a_number_it_does_not_have():
    notes = quantization.quantization_readings(
        state(requested=16, size=9, drawable=8, art_colors=1024,
              art_colors_exact=9, art_colors_capped=True)
    )
    assert "at least 1024" in " ".join(notes)


def test_a_blank_sprite_is_told_it_was_blank():
    notes = quantization.quantization_readings(
        state(size=1, drawable=0, art_colors=0, art_colors_exact=0)
    )
    assert len(notes) == 1
    assert "Nothing is drawn" in notes[0]


def test_an_unscanned_sprite_is_not_reported_as_a_blank_one():
    """The branch that keeps a missing measurement from reading as a finding: without
    it, art_colors=0 for an unscanned sprite produces "nothing is drawn in this
    sprite", which is a claim about the art made by a scan that never ran."""
    notes = quantization.quantization_readings(
        state(art_scanned=False, art_colors=0, art_colors_exact=0)
    )
    joined = " ".join(notes)
    assert "Nothing is drawn" not in joined
    assert "too large to scan" in joined


def test_an_unscanned_sprite_still_has_its_palette_checked():
    notes = quantization.quantization_readings(
        state(art_scanned=False, size=2, drawable=1, art_colors=0, art_colors_exact=0)
    )
    assert "raise max_colors" in " ".join(notes)
