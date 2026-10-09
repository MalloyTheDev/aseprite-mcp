"""The release gate for a measurement, and the gate's own tests.

Three layers, in the order they run:

1. **The machinery**, against hand-computed values. An AUC that is wrong about a tie, or a
   Wilson bound that is wrong at zero successes, would make every verdict below a confident
   lie, so these are checked against numbers worked out by hand rather than against the
   implementation's own output.
2. **The corpus**, against the defects it claims to seed. A negative labelled "20 stray
   pixels" that contains 18, or that also clipped the figure, poisons every sensitivity
   figure computed from it.
3. **The measures that already exist in `core/quality.py`**, against that corpus. This is
   the part that was missing, and it is the reason the module shipped a threshold fitted to
   one sprite, a measure named for craft that counts geometry, and fourteen readings whose
   compounding false-positive rate nobody had multiplied out.

The third layer deliberately does not assert that `core/quality.py` is good. It asserts
that each verdict follows from its evidence, and it pins the findings that are structural
rather than numeric, so that retuning a constant moves numbers in the printed table without
turning the suite red, while a measure quietly acquiring a discordant pair does turn it red.

Run the table on its own with:

    uv run --no-sync python -m pytest tests/test_metric_validation.py -s -k report
"""

from __future__ import annotations

import math

import pytest

import corpus
from aseprite_mcp.core import edges, quality
from aseprite_mcp.core import validation as V
from aseprite_mcp.core.errors import ValidationFailed
from corpus import measures as M
from corpus import mutations as MU

# Every test here is pure Python: no Aseprite, no filesystem beyond the baked corpus PNGs.
# The marker is not decoration. `tests/conftest.py` keeps an allowlist of module names that
# always run, a new file defaults to skipped, and a skip is indistinguishable from a pass in
# a summary line, which is exactly the failure mode this whole module exists to argue
# against.
pytestmark = pytest.mark.pure


# ============================================================ 1. the machinery


@pytest.mark.pure
def test_auc_perfect_separation():
    assert V.auc([3.0, 4.0, 5.0], [0.0, 1.0, 2.0]) == 1.0


@pytest.mark.pure
def test_auc_perfect_inversion_reports_a_sign_error():
    # 0.0 and not 0.5: the measure is not blind, it is backwards, and that distinction is
    # the difference between negating it and withdrawing it.
    assert V.auc([0.0, 1.0, 2.0], [3.0, 4.0, 5.0]) == 0.0


@pytest.mark.pure
def test_auc_all_ties_is_a_coin():
    assert V.auc([1.0, 1.0, 1.0], [1.0, 1.0]) == 0.5


@pytest.mark.pure
def test_auc_hand_computed_with_one_tie():
    # positives [1, 2] against negatives [2, 3], so four pairs:
    #   1 vs 2 lose, 1 vs 3 lose, 2 vs 2 tie (0.5), 2 vs 3 lose  ->  0.5 / 4
    assert V.auc([1.0, 2.0], [2.0, 3.0]) == pytest.approx(0.125)


@pytest.mark.pure
def test_auc_hand_computed_three_quarters():
    #   2 vs 1 win, 2 vs 3 lose, 4 vs 1 win, 4 vs 3 win  ->  3 / 4
    assert V.auc([2.0, 4.0], [1.0, 3.0]) == pytest.approx(0.75)


@pytest.mark.pure
def test_auc_requires_both_sides():
    with pytest.raises(ValueError):
        V.auc([1.0], [])
    with pytest.raises(ValueError):
        V.auc([], [1.0])


@pytest.mark.pure
def test_normal_quantile_matches_the_published_z():
    assert V._normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert V._normal_quantile(0.995) == pytest.approx(2.575829, abs=1e-5)
    assert V._normal_quantile(0.5) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.pure
def test_wilson_zero_of_twenty_is_the_published_bound():
    """The figure the brief for this harness quotes, and the sentence it licenses.

    0 fires in 20 clean examples does not support "no false positives". It supports
    "probably under 16 percent", and the difference between those two sentences is the
    entire reason this function is here instead of a division.
    """
    low, high = V.wilson_interval(0, 20)
    assert low == 0.0
    assert high == pytest.approx(0.161, abs=0.001)


@pytest.mark.pure
def test_wilson_is_symmetric_under_complement():
    """An independent check on the algebra: swapping successes for failures mirrors it.

    Worth having because the alternative check is to re-derive the same formula, which
    would agree with a typo as happily as with the truth.
    """
    for successes, trials in ((0, 20), (1, 10), (3, 7), (9, 20), (12, 12)):
        low, high = V.wilson_interval(successes, trials)
        other_low, other_high = V.wilson_interval(trials - successes, trials)
        assert low == pytest.approx(1.0 - other_high, abs=1e-12)
        assert high == pytest.approx(1.0 - other_low, abs=1e-12)


@pytest.mark.pure
def test_wilson_narrows_as_the_corpus_grows():
    widths = [V.wilson_interval(0, n)[1] for n in (5, 10, 20, 50, 200)]
    assert widths == sorted(widths, reverse=True)
    assert widths[0] > 0.4 and widths[-1] < 0.03


@pytest.mark.pure
def test_wilson_brackets_the_observed_rate():
    low, high = V.wilson_interval(5, 20)
    assert low < 0.25 < high


@pytest.mark.pure
def test_wilson_rejects_impossible_counts():
    with pytest.raises(ValueError):
        V.wilson_interval(0, 0)
    with pytest.raises(ValueError):
        V.wilson_interval(21, 20)
    with pytest.raises(ValueError):
        V.wilson_interval(-1, 20)


@pytest.mark.pure
def test_family_wise_error_at_five_percent_and_fourteen_readings():
    """1 - 0.95**14, which is the arithmetic nobody did before shipping fourteen readings."""
    assert V.family_wise_error(0.05, 14) == pytest.approx(0.5123, abs=1e-4)
    assert V.family_wise_error(0.05, 1) == pytest.approx(0.05)


@pytest.mark.pure
def test_family_wise_error_edges():
    assert V.family_wise_error(0.0, 100) == 0.0
    assert V.family_wise_error(0.37, 0) == 0.0
    assert V.family_wise_error(1.0, 1) == 1.0


@pytest.mark.pure
def test_family_wise_error_rejects_bad_input():
    with pytest.raises(ValueError):
        V.family_wise_error(1.5, 3)
    with pytest.raises(ValueError):
        V.family_wise_error(0.05, -1)


@pytest.mark.pure
def test_discordant_pairs_catches_a_deliberately_inverted_measure():
    """A measure with the sign the wrong way round, which is failure mode three.

    Four candidate alignment measures each ranked a known-good sprite worse than the
    known-bad one. Every (good, bad) pair here is wrong, so the count is the full product.
    """
    good = [9.0, 8.0, 7.0]
    bad = [1.0, 2.0]
    assert len(V.discordant_pairs(good, bad)) == 6


@pytest.mark.pure
def test_discordant_pairs_does_not_count_ties():
    """A tie is blindness, not inversion, and `auc` is what reports blindness."""
    assert V.discordant_pairs([1.0, 1.0], [1.0, 1.0]) == []
    assert V.auc([1.0, 1.0], [1.0, 1.0]) == 0.5


@pytest.mark.pure
def test_discordant_pairs_names_the_offenders():
    pairs = V.discordant_pairs([0.1, 0.9], [0.5])
    assert len(pairs) == 1
    (only,) = pairs
    assert only.good_index == 1
    assert only.bad_index == 0
    assert (only.good_score, only.bad_score) == (0.9, 0.5)


@pytest.mark.pure
def test_one_discordant_pair_discards_however_good_the_auc():
    """The hard gate. 99 of 100 pairs right is still a measure that ranked good art worse."""
    good = [0.0] * 10 + [50.0]
    bad = [10.0] * 20
    report = V.evaluate_measure(
        "nearly_right", "a defect", V.ScoredCorpus(good, bad), thresholds={"cut": V.SOURCED}
    )
    assert report.auc > 0.9
    assert report.verdict == V.DISCARD
    assert len(report.discordant) == 20


@pytest.mark.pure
def test_insufficient_corpus_is_unvalidated_not_a_pass():
    report = V.evaluate_measure(
        "untested", "a defect",
        V.ScoredCorpus([0.0, 0.0], [1.0, 1.0]),
        thresholds={"cut": V.SOURCED},
    )
    assert report.verdict == V.UNVALIDATED
    assert report.auc == 1.0, "perfect separation on two examples is still perfect, and still proves nothing"
    assert any("below floor" in n for n in report.notes)


@pytest.mark.pure
def test_unsourced_threshold_is_unvalidated_even_with_perfect_separation():
    """Failure mode one. The ordering can be perfect while the cut is somebody's guess."""
    report = V.evaluate_measure(
        "fitted_to_one_sprite", "a defect",
        V.ScoredCorpus([0.0] * 12, [1.0] * 12, [False] * 12, [True] * 12),
        thresholds={"FIRED_ABOVE_40_PERCENT": V.UNVALIDATED},
    )
    assert report.auc == 1.0
    assert not report.discordant
    assert report.verdict == V.UNVALIDATED
    assert report.unvalidated_thresholds == ("FIRED_ABOVE_40_PERCENT",)


@pytest.mark.pure
def test_blind_measure_is_discarded():
    report = V.evaluate_measure(
        "constant", "a defect",
        V.ScoredCorpus([1.0] * 12, [1.0] * 12),
        thresholds={"cut": V.SOURCED},
    )
    assert report.auc == 0.5
    assert not report.discordant
    assert report.verdict == V.DISCARD


@pytest.mark.pure
def test_sourced_threshold_and_separation_ships():
    report = V.evaluate_measure(
        "good_one", "a defect",
        V.ScoredCorpus([0.0] * 12, [1.0] * 12, [False] * 12, [True] * 12),
        thresholds={"a published standard": V.SOURCED},
    )
    assert report.verdict == V.SHIP
    assert report.sensitivity == 1.0
    assert report.specificity == 1.0
    # Even a perfect result on twelve clean sprites only licenses a bounded claim.
    assert report.false_positive_upper == pytest.approx(0.242, abs=0.002)


@pytest.mark.pure
def test_no_threshold_declared_is_a_ranking_result_only():
    report = V.evaluate_measure(
        "scalar_only", "a defect", V.ScoredCorpus([0.0] * 12, [1.0] * 12)
    )
    assert report.sensitivity is None
    assert report.specificity is None
    assert any("ranking result only" in n for n in report.notes)


@pytest.mark.pure
def test_empty_side_yields_unvalidated_and_not_a_crash():
    report = V.evaluate_measure("nothing", "a defect", V.ScoredCorpus([], [1.0]))
    assert report.verdict == V.UNVALIDATED
    assert math.isnan(report.auc)


@pytest.mark.pure
def test_fires_must_match_scores_in_length():
    with pytest.raises(ValueError):
        V.evaluate_measure(
            "mismatched", "a defect",
            V.ScoredCorpus([0.0, 1.0], [2.0], [False], [True]),
        )


@pytest.mark.pure
def test_mutation_score_names_the_survivors():
    score, survivors = V.mutation_score(
        {"a:offset_1": ["off_centre"], "a:weld_2": [], "a:lightflip": []}
    )
    assert score == pytest.approx(1 / 3)
    assert survivors == ("a:lightflip", "a:weld_2")
    assert V.mutation_score({}) == (0.0, ())


@pytest.mark.pure
def test_measure_report_summary_carries_the_evidence_not_just_the_verdict():
    report = V.evaluate_measure(
        "m", "a defect",
        V.ScoredCorpus([0.0] * 12, [1.0] * 12, [False] * 12, [True] * 12),
        thresholds={"guess": V.UNVALIDATED},
    )
    line = report.summary()
    for fragment in ("UNVALIDATED", "auc=", "discordant=", "sens=", "spec=", "fp<=", "unsourced="):
        assert fragment in line


# ============================================================ 2. the corpus


@pytest.mark.pure
def test_corpus_is_baked_and_labelled():
    c = corpus.build()
    assert len(c.good) == 12
    assert len(c.known_bad) == 2
    assert len(c.mutants) >= 100
    assert {s.label for s in c.good} == {"good"}
    assert {s.label for s in c.mutants} | {s.label for s in c.known_bad} == {"bad"}


@pytest.mark.pure
def test_every_seeded_defect_reaches_the_corpus():
    """No defect may be silently absent: an unseeded defect looks like an undetected one."""
    c = corpus.build()
    seeded = {s.defect for s in c.mutants}
    assert seeded == {defect for defect, _severity, _suffix in MU.PLAN}


@pytest.mark.pure
def test_no_mutant_is_a_copy_of_its_parent():
    """The rule that keeps the labels honest: a no-op mutation is not a negative."""
    c = corpus.build()
    grids = corpus.grids()
    for mutant in c.mutants:
        assert mutant.grid != grids[mutant.parent], f"{mutant.name} is identical to its parent"


@pytest.mark.pure
def test_offset_preserves_the_pixel_count():
    """One defect per mutant: an offset that lost pixels would also be a clipping defect."""
    c = corpus.build()
    for mutant in c.mutants_for((MU.OFFSET,)):
        parent = c.parents[mutant.parent]
        assert mutant.metrics["drawn_pixels"] == parent.metrics["drawn_pixels"]


@pytest.mark.pure
def test_weld_adds_pixels_without_adding_colours():
    c = corpus.build()
    welded = c.mutants_for((MU.WELD,))
    assert welded, "the weld defect must be seeded somewhere"
    for mutant in welded:
        parent = c.parents[mutant.parent]
        assert mutant.metrics["drawn_pixels"] > parent.metrics["drawn_pixels"]
        assert mutant.metrics["colors"] <= parent.metrics["colors"]


@pytest.mark.pure
def test_collapse_removes_exactly_one_colour():
    c = corpus.build()
    for mutant in c.mutants_for((MU.COLLAPSE,)):
        parent = c.parents[mutant.parent]
        assert mutant.metrics["colors"] == parent.metrics["colors"] - 1
        assert mutant.metrics["drawn_pixels"] == parent.metrics["drawn_pixels"]


@pytest.mark.pure
def test_keyline_mutation_removes_the_darkest_tone():
    c = corpus.build()
    grids = corpus.grids()
    for mutant in c.mutants_for((MU.KEYLINE,)):
        darkest = MU.ramp_of(grids[mutant.parent])[0]
        assert darkest not in {color for row in mutant.grid for color in row}


@pytest.mark.pure
def test_strays_add_exactly_the_requested_isolated_pixels():
    """The count in the label is the count in the art, which is what makes it ground truth.

    Exact rather than approximate, and it can be: each stray is placed on a transparent cell
    with no orthogonal neighbour of the colour being painted, so it is isolated by this
    metric's own definition, and no stray is adjacent to another, so none of them rescues
    any other from isolation.
    """
    c = corpus.build()
    seen = 0
    for mutant in c.mutants_for((MU.STRAYS,)):
        parent = c.parents[mutant.parent]
        delta = mutant.metrics["isolated_pixels"] - parent.metrics["isolated_pixels"]
        assert delta == int(mutant.name.rsplit("_", 1)[1]), mutant.name
        seen += 1
    assert seen >= 9


@pytest.mark.pure
def test_strays_stay_off_the_canvas_border():
    """The one-defect rule again: a stray on the border would also seed `edge_contact`."""
    c = corpus.build()
    for mutant in c.mutants_for((MU.STRAYS,)):
        parent = c.parents[mutant.parent]
        assert mutant.metrics["edge_contact"] == parent.metrics["edge_contact"]


@pytest.mark.pure
def test_clip_loses_pixels_and_lands_on_the_border():
    c = corpus.build()
    for mutant in c.mutants_for((MU.CLIP,)):
        parent = c.parents[mutant.parent]
        assert mutant.metrics["drawn_pixels"] < parent.metrics["drawn_pixels"]
        assert mutant.metrics["edge_contact"] > 0


@pytest.mark.pure
def test_desaturate_takes_pixels_off_the_declared_ramp():
    c = corpus.build()
    for mutant in c.mutants_for((MU.DESATURATE,)):
        assert mutant.metrics["palette_conformance"] < 1.0
        assert c.parents[mutant.parent].metrics["palette_conformance"] == 1.0


@pytest.mark.pure
def test_light_flip_leaves_the_silhouette_identical():
    """Values move, shape does not, so a measure that notices has noticed the light."""
    c = corpus.build()
    grids = corpus.grids()
    flipped = c.mutants_for((MU.LIGHTFLIP,))
    assert flipped
    for mutant in flipped:
        assert quality.opacity_mask(mutant.grid) == quality.opacity_mask(grids[mutant.parent])
        assert mutant.grid != grids[mutant.parent]


@pytest.mark.pure
def test_seeded_severity_is_monotone_in_the_damage_done():
    """The corpus's own ground truth: a 4px offset really does move more than a 1px one.

    Checked on the generator and not on any measure, because this is the premise the
    monotonicity relation below rests on. If the ladder were not a ladder, a measure failing
    to rank it would be the corpus's fault.
    """
    grids = corpus.grids()
    chains = 0
    for name in corpus.GOOD_NAMES:
        grid = grids[name]
        moved = []
        for severity in (1, 2, 3, 4):
            mutated = MU.offset_lower_half(grid, severity)
            if mutated is None:
                break
            moved.append(
                sum(
                    1
                    for y, row in enumerate(grid)
                    for x, color in enumerate(row)
                    if color != mutated[y][x]
                )
            )
        if len(moved) == 4:
            chains += 1
            assert moved == sorted(moved) and len(set(moved)) == 4, f"{name}: {moved}"
    assert chains >= 4


# ============================================================ 3. metamorphic relations


@pytest.mark.pure
def test_monotonicity_a_three_pixel_offset_scores_worse_than_one_which_beats_zero():
    """The relation as specified, on the only measure in the module that satisfies it.

    `silhouette_asymmetry` is strictly ordered across 0, 1 and 3 pixels of offset on every
    chain the corpus can build. It is **not** strictly ordered across the full ladder: on
    one item sprite it saturates at 298 for 2, 3 and 4 pixels, because past two pixels the
    shifted mass no longer overlaps its own mirror image and there is nothing left to count.
    That is a ceiling rather than an inversion, and the distinction is why this asserts the
    specified relation strictly and the full ladder only as non-decreasing.
    """
    grids = corpus.grids()
    chains = 0
    for name in corpus.GOOD_NAMES:
        grid = grids[name]
        ladder = [MU.offset_lower_half(grid, severity) for severity in (1, 2, 3, 4)]
        if any(step is None for step in ladder):
            continue
        scores = [quality.silhouette_asymmetry(grid)] + [
            quality.silhouette_asymmetry(step) for step in ladder
        ]
        chains += 1
        assert scores[0] < scores[1] < scores[3], f"{name}: 0 < 1px < 3px failed, {scores}"
        assert scores == sorted(scores), f"{name}: the ladder inverted, {scores}"
    assert chains >= 4, "no sprite could carry the full offset ladder"


@pytest.mark.pure
def test_the_monotonicity_check_rejects_a_flat_chain():
    """A relation nothing can fail is not a test. This is the same check, failing."""
    flat = [3.0, 3.0, 3.0, 3.0, 3.0]
    inverted = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert not flat[0] < flat[1] < flat[3]
    assert not inverted[0] < inverted[1] < inverted[3]
    assert inverted != sorted(inverted)


# The metrics that must not notice a horizontal flip, and must not notice the drawing moving
# within its canvas. `bbox` is excluded from both for the obvious reason, and `centred` and
# `silhouette_asymmetry` are excluded from translation only: both are measured against the
# canvas's own axis, so moving the art relative to the canvas is exactly the thing they are
# built to report. Excluding them from mirroring would be wrong, and they are not excluded.
UNSIGNED_SCALARS = (
    "colors", "drawn_pixels", "ramps", "isolated_pixels", "jaggy_corners",
    "canvas_usage", "centred", "silhouette_asymmetry", "edge_contact",
)
SHAPE_SCALARS = (
    "colors", "drawn_pixels", "ramps", "isolated_pixels", "jaggy_corners",
    "canvas_usage",
)
NESTED = (
    ("row_structure", ("rows_drawn", "rows_with_air", "welded_rows", "widest_run", "waists",
                       "gutters")),
    ("separator", ("separator", "share", "contrast")),
    ("tone_shares", ("top_color", "top_share", "tones")),
)


@pytest.mark.pure
def test_mirror_invariance_of_every_unsigned_measure():
    """Flipping a sprite horizontally must not move a single unsigned reading."""
    for name, grid in corpus.grids().items():
        before = quality.score(grid)
        after = quality.score(MU.mirror(grid))
        for key in UNSIGNED_SCALARS:
            assert before[key] == after[key], f"{name}: {key} changed under a mirror"
        for group, keys in NESTED:
            for key in keys:
                assert before[group][key] == after[group][key], f"{name}: {group}.{key}"


@pytest.mark.pure
def test_translation_invariance_of_the_shape_measures():
    """Moving the drawing within its canvas must not move a shape reading.

    Only six of the twelve good sprites can be translated at all: the rest fill their canvas
    in one axis or both, and a translation that clipped them would be testing clipping.
    """
    moved = 0
    for name, grid in corpus.grids().items():
        shifted = MU.translate(grid, 1, 0)
        if shifted is None:
            continue
        moved += 1
        before, after = quality.score(grid), quality.score(shifted)
        for key in SHAPE_SCALARS:
            assert before[key] == after[key], f"{name}: {key} changed under a translation"
        for key in ("rows_drawn", "rows_with_air", "welded_rows", "widest_run", "waists",
                    "gutters"):
            assert before["row_structure"][key] == after["row_structure"][key], f"{name}: {key}"
    assert moved >= 6


@pytest.mark.pure
def test_idempotence_of_the_stray_repair():
    """A repair run twice must not change the score the second time.

    Not assumed: erasing a lone pixel can orphan the pixel that was keeping another one
    company, so a single pass is not obviously a fixed point. On this corpus it is, and the
    second pass is asserted to be a no-op rather than merely expected to be one.
    """
    grids = corpus.grids()
    checked = 0
    for name in corpus.GOOD_NAMES:
        noisy = MU.add_strays(grids[name], 20) or MU.add_strays(grids[name], 5)
        if noisy is None:
            continue
        checked += 1
        once = MU.repair_strays(noisy)
        twice = MU.repair_strays(once)
        assert twice == once, f"{name}: the repair is not idempotent"
        assert quality.isolated_pixels(once) == 0, f"{name}: strays survived one pass"
        assert quality.score(twice) == quality.score(once)
    assert checked >= 6


@pytest.mark.pure
def test_non_regression_a_declined_plan_claims_nothing():
    """A tool that declines to act must not change a score at all.

    This relation has already been violated in this repository: an edge-normalising pass
    that correctly declined to touch a shape nonetheless reported its score as one better.
    `edges.plan` now refuses by raising, so declining cannot carry a number at all, and the
    test holds the shape of that guarantee: the decline is repeatable and the silhouette it
    declined is unchanged by having been asked.
    """
    declined = 0
    for sample in corpus.build().good:
        mask = quality.opacity_mask(sample.grid)
        before = quality.jaggy_corners_in_mask(mask)
        try:
            edges.plan(mask)
        except ValidationFailed:
            declined += 1
            assert quality.opacity_mask(sample.grid) == mask
            assert quality.jaggy_corners_in_mask(mask) == before
            with pytest.raises(ValidationFailed):
                edges.plan(mask)
    assert declined >= 1, "no sprite in the corpus exercises the decline path"


@pytest.mark.pure
def test_non_regression_a_claimed_improvement_is_a_real_improvement():
    """When the pass does act, the score it reports must be the score it achieved.

    The other half of the same failure. `plan` returns `jaggy_after` without applying
    anything, so that number is a claim; this applies the plan and measures it. A pass that
    reported an improvement it did not make is the bug that motivated this relation.
    """
    acted = 0
    c = corpus.build()
    for sample in list(c.good) + list(c.known_bad) + list(c.mutants)[:40]:
        mask = quality.opacity_mask(sample.grid)
        try:
            plan = edges.plan(mask)
        except ValidationFailed:
            continue
        acted += 1
        applied = [list(row) for row in mask]
        for pixel in plan["add"]:
            applied[pixel["y"]][pixel["x"]] = True
        assert quality.jaggy_corners_in_mask(applied) == plan["jaggy_after"], sample.name
        assert plan["jaggy_after"] < plan["jaggy_before"], sample.name
        assert quality.bounding_box(sample.grid) is not None
        assert list(quality.bounding_box(sample.grid)) == plan["bbox"], sample.name
    assert acted >= 5, "no sprite in the corpus exercises the acting path"


# ============================================================ 4. the readings as they stand


@pytest.mark.pure
def test_the_measure_table_fires_as_often_as_quality_readings_does():
    """A guard on this harness, not on `core/quality.py`.

    The gating logic in `corpus/measures.py` is an independent reimplementation of
    `quality.readings`, because scraping its prose would break on a reworded sentence and
    copying its thresholds would silently stop tracking them. An independent
    reimplementation can drift instead, so it is checked against the real function across
    every sprite and mutant in the corpus: a few hundred comparisons, which is enough that
    a divergence in any one gate shows up.
    """
    c = corpus.build()
    for sample in list(c.good) + list(c.known_bad) + list(c.mutants):
        expected = quality.readings(sample.metrics, width=sample.width, height=sample.height)
        mine = M.fired(sample)
        assert len(mine) == len(expected), (
            f"{sample.name}: this table fired {sorted(mine)} while quality.readings "
            f"produced {len(expected)} line(s):\n  " + "\n  ".join(expected)
        )


@pytest.mark.pure
def test_at_most_one_separator_reading_fires_on_any_sprite():
    """Structural, and easy to forget: the three keyline readings are an elif chain.

    It matters for the gate, because it means a sprite whose keyline is both too thin and
    too low in contrast reports only the thinness, and the contrast reading can never be
    scored on it.
    """
    c = corpus.build()
    arms = ("separator_share_low", "separator_share_high", "separator_contrast")
    for sample in list(c.good) + list(c.known_bad) + list(c.mutants):
        assert len(M.fired(sample) & set(arms)) <= 1, sample.name


@pytest.mark.pure
def test_the_compounding_false_positive_rate_is_realised_on_clean_art():
    """Failure mode four, measured instead of predicted.

    `family_wise_error(0.05, 13)` predicts 0.49 of clean sprites collecting at least one
    spurious complaint. The measured rate on this repository's own published art is higher
    than that, which means the per-reading rate is not 5 percent.
    """
    profile = corpus.false_positives()
    complained_about = [name for name, readings in profile.items() if readings]
    rate = len(complained_about) / len(profile)
    low, high = V.wilson_interval(len(complained_about), len(profile))
    predicted = V.family_wise_error(0.05, len(M.ALL_MEASURES))

    assert rate > predicted, (
        f"{len(complained_about)} of {len(profile)} clean sprites draw a complaint "
        f"(95% CI {low:.2f} to {high:.2f}); {len(M.ALL_MEASURES)} readings at a 5% "
        f"per-reading rate would predict {predicted:.2f}"
    )
    assert low > 0.5, "the lower confidence bound should already exceed a coin"
    # The reference orb is the one sprite nothing complains about, and it is the cleanest
    # art in the repository. If that changes, a reading has gone wrong, not the orb.
    assert profile["good_orb"] == set()


@pytest.mark.pure
def test_two_separator_arms_cannot_be_reached_by_any_seeded_defect():
    """A coverage hole, pinned because it is invisible otherwise.

    `separator_share_high` and `separator_contrast` receive no mutant at all. The only
    seeded defect aimed at the keyline replaces the darkest tone, which drops the separator
    share below the band's floor, and the elif chain then hands the sprite to
    `separator_share_low` and silences the other two. They are not failing; they are
    unasked, and a report that showed them blank without saying so would read as a pass.
    """
    for name in ("separator_share_high", "separator_contrast"):
        measure = next(m for m in M.SPRITE_MEASURES if m.name == name)
        assert corpus.absolute_report(measure) is None, f"{name} now has a corpus; gate it"


@pytest.mark.pure
def test_every_verdict_follows_from_its_evidence():
    """The gate must be auditable: each verdict is re-derived from the report's own fields."""
    for measure in M.SPRITE_MEASURES:
        report = corpus.absolute_report(measure)
        if report is None:
            continue
        if report.verdict == V.SHIP:
            assert not report.discordant
            assert report.auc > 0.5
            assert not report.unvalidated_thresholds
        elif report.verdict == V.DISCARD:
            assert report.discordant or report.auc <= 0.5
        else:
            assert report.verdict == V.UNVALIDATED
            below_floor = report.good_count < V.MIN_GOOD or report.bad_count < V.MIN_BAD
            assert below_floor or report.unvalidated_thresholds


@pytest.mark.pure
def test_no_measure_ships_while_a_discordant_pair_exists():
    """The hard gate, applied to the real module rather than to a synthetic example."""
    for measure in M.ALL_MEASURES:
        report = corpus.absolute_report(measure) if measure in M.SPRITE_MEASURES else None
        if report is not None and report.discordant:
            assert report.verdict == V.DISCARD, measure.name


@pytest.mark.pure
def test_palette_conformance_is_the_one_reading_that_passes_the_absolute_gate():
    """Pinned because it is the finding, and because it should become false.

    One of thirteen readings separates known-good art from seeded defects with no discordant
    pair and a threshold that can be cited. It is also the least interesting of them: it is
    definitional rather than perceptual, and its specificity cannot be observed on this
    corpus, because the ramp a clean sprite is scored against is derived from that sprite.

    When a second reading earns a SHIP this test fails, which is the intended way to find out.
    """
    shipped = {
        m.name
        for m in M.SPRITE_MEASURES
        if (r := corpus.absolute_report(m)) is not None and r.verdict == V.SHIP
    }
    assert shipped == {"palette_conformance"}, f"the shipping set changed: {sorted(shipped)}"


@pytest.mark.pure
def test_the_paired_gate_passes_measures_the_absolute_gate_rejects():
    """Most of these readings are sound regression guards and unsound absolute verdicts.

    The distinction is the practical finding of this harness. `isolated_pixels` ranks every
    one of its eighteen matched pairs correctly, and it still cannot support a fixed
    threshold, because the clean dungeon scene reads 701 and a stray-seeded orb reads 11.
    """
    perfect_paired, rejected_absolute = set(), set()
    for measure in M.SPRITE_MEASURES:
        paired = corpus.paired_report(measure)
        absolute = corpus.absolute_report(measure)
        if paired is not None and paired.better == 0 and paired.auc > 0.9:
            perfect_paired.add(measure.name)
        if absolute is not None and absolute.verdict != V.SHIP:
            rejected_absolute.add(measure.name)
    both = perfect_paired & rejected_absolute
    assert both, "no measure is a sound paired guard and an unsound absolute reading"
    assert "isolated_pixels" in both


@pytest.mark.pure
def test_edge_contact_inverts_on_matched_pairs():
    """Pinned because it is a real inversion and not a threshold problem.

    Clipping a figure can *lower* the border-pixel count: slide a drawing that already
    touched the right border to the left and the pixels that were on that border leave the
    canvas. Ten of its twenty-two matched pairs move the wrong way, so the scalar does not
    measure "is the silhouette cut off" in the direction its name claims.
    """
    measure = next(m for m in M.SPRITE_MEASURES if m.name == "edge_contact")
    paired = corpus.paired_report(measure)
    assert paired is not None
    assert paired.better > 0, "edge_contact no longer inverts; re-read the gate"
    assert paired.auc < 0.75


@pytest.mark.pure
def test_the_mutation_score_names_the_defects_nothing_detects():
    """Two seeded defects survive every one of the thirteen readings, and they are named.

    Welding and a flipped light direction pass through the whole module untouched. Welding
    is the defect that five of these readings were added to catch.
    """
    detections = corpus.detections()
    score, survivors = V.mutation_score(detections)
    assert 0.0 < score < 1.0

    c = corpus.build()
    defects = {s.name: s.defect for s in c.mutants}
    undetected = {defects[label] for label in survivors}
    assert MU.WELD in undetected
    assert MU.LIGHTFLIP in undetected
    # And no mutant of these two is detected by anything, which is stronger than "some survive".
    for label, fired_on in detections.items():
        if defects[label] in (MU.WELD, MU.LIGHTFLIP):
            assert fired_on == [], f"{label} was detected by {fired_on}"


@pytest.mark.pure
def test_report():
    """Not an assertion so much as the deliverable. Run with `-s` to read it.

    Kept as a test rather than a script so it cannot rot: it builds every report through the
    same entry point the gates use, so a change to the machinery shows up here too.
    """
    c = corpus.build()
    lines: list[str] = []
    lines.append(
        f"corpus: {len(c.good)} known-good, {len(c.known_bad)} known-bad, "
        f"{len(c.mutants)} seeded mutants across "
        f"{len({s.defect for s in c.mutants})} defects"
    )
    lines.append("")
    lines.append("ABSOLUTE GATE (fixed threshold, across sprites)")
    for measure in M.SPRITE_MEASURES:
        report = corpus.absolute_report(measure)
        if report is None:
            lines.append(f"  {'NO CORPUS':11s} {measure.name:22s} {measure.defect}")
            continue
        lines.append(f"  {report.summary()}")
    lines.append(f"  {corpus.ramp_report().summary()}   [palette corpus]")
    lines.append("")
    lines.append("PAIRED GATE (same sprite, before and after)")
    for measure in M.SPRITE_MEASURES:
        paired = corpus.paired_report(measure)
        if paired is None:
            continue
        lines.append(
            f"  {paired.measure:24s} pairs={paired.pairs:3d} worse={paired.worse:3d} "
            f"tied={paired.tied:3d} better={paired.better:3d} auc={paired.auc:.3f}"
        )
    ramp_paired = corpus.ramp_paired()
    lines.append(
        f"  {ramp_paired.measure:24s} pairs={ramp_paired.pairs:3d} "
        f"worse={ramp_paired.worse:3d} tied={ramp_paired.tied:3d} "
        f"better={ramp_paired.better:3d} auc={ramp_paired.auc:.3f}   [palette corpus]"
    )
    lines.append("")
    profile = corpus.false_positives()
    complained = sum(1 for readings in profile.values() if readings)
    low, high = V.wilson_interval(complained, len(profile))
    lines.append(
        f"false positives: {complained}/{len(profile)} clean sprites draw a complaint "
        f"(95% CI {low:.2f} to {high:.2f}); "
        f"family_wise_error(0.05, {len(M.ALL_MEASURES)}) predicts "
        f"{V.family_wise_error(0.05, len(M.ALL_MEASURES)):.2f}"
    )
    detections = corpus.detections()
    score, survivors = V.mutation_score(detections)
    defects = {s.name: s.defect for s in c.mutants}
    # Two different facts, and conflating them overstates the module. A defect with some
    # surviving mutants is detected at some severities and missed at others; a defect with
    # no detected mutant anywhere passes through all thirteen readings untouched.
    partial = sorted({defects[label] for label in survivors})
    total = sorted(
        defect
        for defect in {s.defect for s in c.mutants}
        if all(not detections[label] for label, d in defects.items() if d == defect)
    )
    lines.append(f"mutation score: {score:.3f} ({len(detections) - len(survivors)} of "
                 f"{len(detections)} seeded defects detected by at least one reading)")
    lines.append(f"  detected at some severities and missed at others: {partial}")
    lines.append(f"  never detected by any reading:                    {total}")
    text = "\n".join(lines)
    # Printed rather than captured. `capsys.readouterr()` consumes the output, so asserting
    # through it would hide the one thing this test exists to show.
    print("\n" + text)
    assert "ABSOLUTE GATE" in text and "PAIRED GATE" in text
    assert "mutation score" in text


@pytest.mark.pure
def test_a_candidate_measure_of_my_own_fails_the_same_gate():
    """The gate has to bite on a measure its author wanted to keep, or it is decoration.

    `light_direction_split` was written for one of the two defects nothing in the module
    detects: it compares where the luminance sits against where the mass sits, separately for
    a figure's upper and lower halves, and reports the disagreement. The idea is sound and
    the ranking is good, AUC around 0.93 with eleven of twelve matched pairs moving the right
    way.

    It is discarded anyway. The clean attack panel scores above a flipped item sprite, so a
    threshold that caught the flip would already be firing on undamaged published art. That
    is the same shape of failure as the four withdrawn alignment measures, and the same
    answer: a high AUC with discordant pairs means the measure works on average over a
    corpus and cannot carry a cut.
    """
    report = corpus.absolute_report(M.REJECTED_CANDIDATE)
    assert report is not None
    assert report.auc > 0.9, "the candidate was supposed to rank well; that was never the problem"
    assert report.discordant, "the candidate's discordant pairs are the finding"
    assert report.verdict == V.DISCARD
    # No cut was proposed, so none is reported. Quoting a detection rate for a measure with
    # no threshold is how a ranking result becomes a sensitivity claim.
    assert report.sensitivity is None
    assert report.specificity is None


@pytest.mark.pure
def test_the_rejected_candidate_still_beats_the_readings_it_was_written_against():
    """Worth recording: nothing in `core/quality.py` scores above a coin on this defect.

    The candidate is not shippable. It is still the only measure examined here that has any
    purchase on a flipped light direction at all, which is the difference between "discard
    this" and "there is nothing here to work from".
    """
    detections = corpus.detections()
    defects = {s.name: s.defect for s in corpus.build().mutants}
    flipped = [label for label, defect in defects.items() if defect == MU.LIGHTFLIP]
    assert flipped
    assert all(detections[label] == [] for label in flipped)

    paired = corpus.paired_report(M.REJECTED_CANDIDATE)
    assert paired is not None
    assert paired.auc > 0.75
    assert paired.better >= 1, "one matched pair inverts, which is part of why it is discarded"


# --- the craft measures, and why none of them judges -----------------------------------


@pytest.mark.pure
def test_the_craft_thresholds_stay_discarded():
    """Pins the verdict, so nobody promotes these on the strength of the idea.

    All three were proposed, measured against the corpus and discarded the same day. The
    failure is not that the thresholds were badly chosen: the orderings invert. Good art
    here runs 0 to 68 percent singleton colour regions and bad art 36 to 47, so the ranges
    overlap almost entirely and the good side is the wider one. Edge variety is worse than
    useless at AUC 0.168, because a sprite sheet's panels have perfectly straight edges and
    are perfectly good art while the known-bad golem has the most varied edges in the set.
    """
    from aseprite_mcp.core import craft

    built = corpus.build()

    def column(samples, fn):
        return [fn(craft.score(s.grid)) for s in samples]

    bad = list(built.known_bad) + [
        s for s in built.mutants if s.defect in ("stray single pixels", "masses welded")]
    for name, fn in (("singleton_share",
                      lambda m: m["clusters"]["singleton_share"]),
                     ("share_in_8plus",
                      lambda m: -m["clusters"]["share_in_8plus"]),
                     ("edge_variety",
                      lambda m: -m["edge_runs"]["distinct"])):
        discordant = V.discordant_pairs(column(built.good, fn), column(bad, fn))
        assert discordant, (
            f"{name} stopped inverting on the corpus. If that is real rather than a "
            "corpus change, re-read the DISCARDED block in core/craft.py before "
            "promoting it: the gate is the ordering, not the threshold.")

    # And the module says so: it reports numbers and judges nothing.
    assert craft.readings(craft.score(built.good[0].grid)) == []


@pytest.mark.pure
def test_the_ramp_floor_guard_survives_because_it_is_definitional():
    """The one craft check that does judge, and the fault it was written for.

    Three separate ramps in one piece bottomed out at or near pure black, which is darker
    than any sensible keyline, so the drawing's darkest colour became a handful of
    interior shadow pixels and the outline stopped being measurable. `ramp_chroma` cannot
    see it, because a step at pure black has no hue and so is not a grey step.
    """
    from aseprite_mcp.core import craft, quality

    keyline = "#07080f"
    assert craft.ramp_floor_clears(["#151823", "#2d3647", "#46536a"], keyline)
    assert not craft.ramp_floor_clears(["#000000", "#2d3647"], keyline)
    assert not craft.ramp_floor_clears(["#040103", "#2d3647"], keyline)
    # The hole it plugs: a pure-black step passes the chroma check it would otherwise
    # have to get past.
    assert quality.ramp_chroma(["#000000", "#40141f", "#95342f", "#d59779"])[
        "grey_steps"] == 0
