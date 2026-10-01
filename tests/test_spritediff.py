"""What a diff means, without Aseprite (always runs).

The counting is Lua's job and the editor is the only thing that can check it. What a
count *means* is this module's job, and it is checked here against dicts, because the
interesting cases (four buckets at once, a change nobody asked about, an edit that landed
nowhere) are a nuisance to produce out of real sprites and trivial to write down.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import spritediff


def counts(**kwargs) -> dict:
    """A measurement with every bucket at zero, so a test states only its own case."""
    base = {
        "changed_pixels": 0, "silhouette_added": 0, "silhouette_removed": 0,
        "interior_changed": 0, "coverage_changed": 0, "drawn_union": 100,
        "change_box": None, "colors_before": [], "colors_after": [],
    }
    base.update(kwargs)
    base["changed_pixels"] = (
        base["silhouette_added"] + base["silhouette_removed"]
        + base["interior_changed"] + base["coverage_changed"]
    ) if "changed_pixels" not in kwargs else base["changed_pixels"]
    return base


def box(width: int, height: int) -> dict:
    return {"x": 0, "y": 0, "width": width, "height": height}


# ------------------------------------------------------------------- classification
def test_no_change_is_identical():
    assert spritediff.classify(counts()) == "identical"


def test_pixels_entering_the_shape_is_a_silhouette_change():
    assert spritediff.classify(counts(silhouette_added=4)) == "silhouette"


def test_pixels_leaving_the_shape_is_one_too():
    assert spritediff.classify(counts(silhouette_removed=4)) == "silhouette"


def test_a_repaint_inside_the_shape_is_interior():
    assert spritediff.classify(counts(interior_changed=9)) == "interior"


def test_alpha_alone_is_coverage():
    assert spritediff.classify(counts(coverage_changed=9)) == "coverage"


def test_a_repaint_and_an_alpha_change_together_are_mixed():
    assert spritediff.classify(counts(interior_changed=3, coverage_changed=3)) == "mixed"


def test_the_silhouette_wins_over_everything_else():
    """A shape that moved is what breaks collision boxes, outlines and the export box, so
    it is the finding worth naming even when a repaint happened in the same pass."""
    both = counts(silhouette_added=1, interior_changed=200, coverage_changed=50)
    assert spritediff.classify(both) == "silhouette"


# -------------------------------------------------------------------------- shares
def test_changed_share_is_against_the_drawn_art_not_the_canvas():
    """Four pixels of a four-pixel sprite is a total repaint; four pixels of a full 32x32
    is a touch-up. A denominator of width*height cannot tell them apart."""
    small = spritediff.shares(counts(interior_changed=4, drawn_union=4))
    large = spritediff.shares(counts(interior_changed=4, drawn_union=1024))
    assert small["changed_share"] == 1.0
    assert large["changed_share"] == 0.004


def test_an_empty_sprite_does_not_divide_by_zero():
    assert spritediff.shares(counts(drawn_union=0))["changed_share"] == 0.0


def test_density_is_against_the_change_box():
    filled = counts(interior_changed=64, change_box=box(8, 8))
    assert spritediff.shares(filled)["change_density"] == 1.0
    scattered = counts(interior_changed=8, change_box=box(16, 16))
    assert spritediff.shares(scattered)["change_density"] == 0.031


def test_no_change_box_means_no_density_rather_than_an_error():
    assert spritediff.shares(counts())["change_density"] == 0.0


# ----------------------------------------------------------------- colours introduced
def test_a_colour_the_edit_did_not_replace_counts_as_introduced():
    tallied = counts(
        interior_changed=2,
        colors_before=[{"color": "#6b4a2fff", "pixels": 2}],
        colors_after=[{"color": "#3a2418ff", "pixels": 2}],
    )
    assert spritediff.introduced(tallied) == [{"color": "#3a2418ff", "pixels": 2}]


def test_a_colour_that_was_already_among_the_replaced_ones_is_not_new():
    """Two pixels swapping colours with each other introduces nothing."""
    swap = counts(
        interior_changed=2,
        colors_before=[{"color": "#aaa", "pixels": 1}, {"color": "#bbb", "pixels": 1}],
        colors_after=[{"color": "#bbb", "pixels": 1}, {"color": "#aaa", "pixels": 1}],
    )
    assert spritediff.introduced(swap) == []


def test_missing_tallies_are_not_an_error():
    assert spritediff.introduced({"changed_pixels": 0}) == []


# ------------------------------------------------------------------------- readings
def says(notes: list[str], phrase: str) -> bool:
    return any(phrase in note for note in notes)


def test_nothing_changed_is_said_out_loud():
    """The whole reason this tool exists. An edit that went nowhere and an edit that was
    not needed look identical from the outside, so silence here would be a wrong answer
    dressed as a quiet one."""
    notes = spritediff.readings(counts(), names={"before": "a f1", "after": "a f2"})
    assert len(notes) == 1
    assert says(notes, "Nothing changed")
    assert says(notes, "layer")
    assert says(notes, "get_selection")


def test_nothing_changed_crowds_out_every_other_note():
    """There is nothing to say about the shape of a change that did not happen."""
    notes = spritediff.readings(counts(), names={})
    assert len(notes) == 1


def test_a_silhouette_change_is_named_as_one():
    notes = spritediff.readings(counts(silhouette_added=6), names={})
    assert says(notes, "The silhouette changed")
    assert says(notes, "collision")


def test_a_full_repaint_reads_as_a_filter_rather_than_an_edit():
    notes = spritediff.readings(
        counts(interior_changed=100, drawn_union=100, change_box=box(10, 10)), names={})
    assert says(notes, "filter over the whole frame")
    assert says(notes, "ramp=")


def test_a_partial_repaint_just_reports_itself():
    notes = spritediff.readings(
        counts(interior_changed=10, drawn_union=100, change_box=box(4, 4)), names={})
    assert says(notes, "10 pixels were repainted")
    assert not says(notes, "filter over the whole frame")


def test_scattered_pixels_read_as_noise_and_name_the_tool_for_it():
    notes = spritediff.readings(
        counts(interior_changed=6, drawn_union=400, change_box=box(32, 32)), names={})
    assert says(notes, "scattered")
    assert says(notes, "remove_stray_pixels")


def test_a_dense_region_is_not_called_scattered():
    notes = spritediff.readings(
        counts(interior_changed=100, drawn_union=400, change_box=box(10, 10)), names={})
    assert not says(notes, "scattered")


def test_a_small_box_is_not_called_scattered_however_sparse():
    """Four pixels in a 4x4 box is 25% density, which is 'scattered' by the ratio and
    nonsense as a finding: there is no room in a box that size for noise to be a
    pattern."""
    notes = spritediff.readings(
        counts(interior_changed=1, drawn_union=400, change_box=box(4, 4)), names={})
    assert not says(notes, "scattered")


def test_a_pile_of_new_colours_reads_as_a_change_of_material():
    many = counts(
        interior_changed=8, change_box=box(4, 4),
        colors_before=[{"color": "#111", "pixels": 8}],
        colors_after=[{"color": f"#{n:03x}", "pixels": 1} for n in range(8)],
    )
    notes = spritediff.readings(many, names={})
    assert says(notes, "introduced 8 colours")


def test_swapping_one_shade_for_another_does_not():
    shade = counts(
        interior_changed=8, change_box=box(4, 4),
        colors_before=[{"color": "#6b4a2fff", "pixels": 8}],
        colors_after=[{"color": "#3a2418ff", "pixels": 8}],
    )
    assert not says(spritediff.readings(shade, names={}), "introduced")


@pytest.mark.parametrize("field", ["silhouette_added", "interior_changed",
                                   "coverage_changed"])
def test_one_pixel_is_reported_as_one_pixel(field):
    """A report that says "1 pixels" reads as a broken report, and the numbers beside it
    are the whole product."""
    notes = spritediff.readings(counts(**{field: 1}, change_box=box(1, 1)), names={})
    assert notes, f"{field} produced no reading at all"
    assert says(notes, "1 pixel ")
    assert not says(notes, "1 pixels")


# -------------------------------------------------------------------------- verdict
def test_the_expected_change_passes():
    v = spritediff.verdict(counts(interior_changed=4), "interior")
    assert v["passed"] is True
    assert v["errors"] == []


def test_a_different_change_fails_and_says_what_it_measured():
    v = spritediff.verdict(counts(silhouette_removed=4), "interior")
    assert v["passed"] is False
    assert "expected a interior change and measured a silhouette one" in v["errors"][0]
    assert "4 left it" in v["errors"][0]


def test_expecting_nothing_to_change_is_a_check_like_any_other():
    """Useful in the other direction too: a mask or a lock is supposed to make an edit do
    nothing, and this is how that gets asserted."""
    assert spritediff.verdict(counts(), "identical")["passed"] is True
    assert spritediff.verdict(counts(interior_changed=1), "identical")["passed"] is False


def test_an_unknown_expectation_is_refused_rather_than_failed():
    """A typo must not read as a failed check: that would report the art as wrong."""
    with pytest.raises(ValueError, match="expect must be one of"):
        spritediff.verdict(counts(), "diffrent")


def test_every_classification_can_be_expected():
    """Whatever classify() can return, expect= has to accept, or a true measurement
    becomes unassertable."""
    for name in spritediff.CLASSIFICATIONS:
        spritediff.verdict(counts(), name)
