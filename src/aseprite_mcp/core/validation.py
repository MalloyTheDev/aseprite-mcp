"""Pure validation logic: of a sprite, and of a measurement.

Two things live here, and they validate at two different levels.

`evaluate` and its helpers answer **is this sprite fit to export**, for
`validate_sprite_for_game_export`. Kept dependency-free (no Aseprite, no MCP) so the
decision logic is unit-testable. The Aseprite-backed facts (sprite info, corner
transparency, export existence, metadata readability) are gathered by the tool wrapper and
passed in here.

The `gates` section answers **is this measurement fit to ship**, which is the question
`core/quality.py` was never asked and should have been. It is the release gate for a
metric rather than for a sprite: AUC, the discordant-pair gate, a Wilson bound so a
specificity claim can be stated honestly, and the family-wise error arithmetic. It takes
scores and returns verdicts, so it knows nothing about pixels and imports no image
library, which also keeps `core/` on the standard library.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

_DEFAULT_LAYER_RE = re.compile(r"Layer \d+$")


def _is_suspicious_layer(name: str) -> bool:
    return name.strip() == "" or bool(_DEFAULT_LAYER_RE.fullmatch(name.strip()))


def evaluate(
    info: dict,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
    tile_multiple: int | None = None,
    allowed_color_modes: list[str] | None = None,
    min_frames: int | None = None,
    max_frames: int | None = None,
    required_tags: list[str] | None = None,
    max_palette_size: int | None = None,
    require_transparent_background: bool = False,
    transparent_corners: list[bool] | None = None,
    missing_exports: list[str] | None = None,
    unreadable_metadata: str | None = None,
    oversized_threshold: int = 1024,
) -> dict:
    """Evaluate a sprite's `get_sprite_info` dict against game-export criteria.

    Returns {passed, checks, errors, warnings}. `passed` is True iff no error-level
    check failed (warnings never fail the validation).
    """
    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, level: str, detail: str = "") -> None:
        # `detail` describes the FAILURE, so carrying it on a passing check makes a clean
        # report read like a list of problems ("ok": true beside "is not a valid resource
        # path"). Emit it only when it is true.
        checks.append({"name": name, "ok": ok, "level": level,
                       "detail": "" if ok else detail})
        if not ok:
            (errors if level == "error" else warnings).append(detail or name)

    w, h = info["width"], info["height"]
    mode = info["colorMode"]
    frames = info["frameCount"]
    tag_names = [t["name"] for t in info["tags"]]
    layer_names = [layer["name"] for layer in info["layers"]]
    palette_size = info.get("paletteSize")

    if expected_width is not None:
        check("width", w == expected_width, "error", f"width {w} != expected {expected_width}")
    if expected_height is not None:
        check("height", h == expected_height, "error", f"height {h} != expected {expected_height}")
    if tile_multiple:
        ok = w % tile_multiple == 0 and h % tile_multiple == 0
        check("tile_multiple", ok, "error", f"canvas {w}x{h} is not a multiple of {tile_multiple}")
    if allowed_color_modes:
        check("color_mode", mode in allowed_color_modes, "error",
              f"color mode '{mode}' not in {allowed_color_modes}")
    if min_frames is not None:
        check("min_frames", frames >= min_frames, "error", f"frame count {frames} < min {min_frames}")
    if max_frames is not None:
        check("max_frames", frames <= max_frames, "error", f"frame count {frames} > max {max_frames}")
    if required_tags:
        missing = [t for t in required_tags if t not in tag_names]
        check("required_tags", not missing, "error", f"missing required tags: {missing}")
    if max_palette_size is not None and palette_size is not None:
        check("max_palette_size", palette_size <= max_palette_size, "error",
              f"palette size {palette_size} > max {max_palette_size}")
    if require_transparent_background:
        if transparent_corners is None:
            check("transparent_background", False, "warning",
                  "could not read canvas corners to verify transparency")
        else:
            check("transparent_background", all(transparent_corners), "error",
                  "one or more canvas corners are opaque (expected a transparent background)")
    if missing_exports:
        check("expected_exports", False, "error", f"missing export files: {missing_exports}")
    elif missing_exports is not None:
        check("expected_exports", True, "error", "")
    if unreadable_metadata:
        check("spritesheet_metadata", False, "error",
              f"sprite-sheet metadata missing or unreadable: {unreadable_metadata}")

    # Soft warnings (never fail validation).
    if w > oversized_threshold or h > oversized_threshold:
        check("canvas_size", False, "warning",
              f"large canvas {w}x{h} (> {oversized_threshold}px) may be heavy for a sprite")
    if frames > 1 and not tag_names:
        check("animation_tags", False, "warning", "multi-frame sprite has no animation tags")
    suspicious = [n for n in layer_names if _is_suspicious_layer(n)]
    if suspicious:
        check("layer_names", False, "warning", f"default/blank layer names: {suspicious}")

    return {
        "passed": len(errors) == 0,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


# =========================================================================== gates
# Whether a *measurement* is allowed to ship, which is a different question from the one
# `evaluate` above answers about a sprite.
#
# The module this exists to gate had four separate failures, and none of them was a bug in
# any single metric:
#
#   1. A threshold fitted to one example. "The most-used colour's share" was set to fire
#      above 40 percent because one bad sprite measured 61. Measured afterwards, the clean
#      reference orb runs 51 percent (a five-step ramp on a sphere has to) and the figure
#      the reading was written for runs 19.9. It fired on the good art and never on the
#      bad. Withdrawn. Threshold provenance and the UNVALIDATED verdict exist for this.
#   2. A measure correct about its own definition and wrong about its name. "Jagged
#      corners" counts a 2x2 pattern, and a correct raster circle produces 36 of them at
#      32x32 and 72 at 64x64. No threshold separates craft from geometry. Construct
#      validity is not something a gate can test, so `MeasureReport.defect` forces the
#      claim to be written down next to the evidence, where the mismatch is visible.
#   3. Four candidate alignment measures, each of which ranked a known-good sprite worse
#      than the known-bad one. `discordant_pairs` is the hard gate for this, and it is a
#      gate and not a score: one discordant pair discards the measure.
#   4. Compounding false positives. The module emits about 14 readings, and at a 5 percent
#      false-positive rate each that is `family_wise_error(0.05, 14)` = 0.51, so roughly
#      half of all clean sprites collect at least one spurious complaint.
#
# There is deliberately no combined quality score here, and no helper that would make one
# easy to assemble. A quarter of a million labelled photographs and a neural network reach
# about 0.78 rank correlation with human aesthetic judgement; a weighted sum of a dozen
# unvalidated numbers over a handful of sprites will not come near that, and it makes every
# component undebuggable, because a single number cannot say which of its terms moved.
# Per-measure reports, named defects, and named survivors instead.
#
# Sign convention, which every function below depends on: **a higher score is worse.** A
# measure whose natural direction is "higher is better" must be negated by its caller
# before it reaches these functions. Getting this backwards is the sign error that an AUC
# below 0.5 reports.

# Verdicts.
SHIP = "SHIP"
DISCARD = "DISCARD"
UNVALIDATED = "UNVALIDATED"

# Threshold provenance. UNVALIDATED is reused deliberately: a reading resting on a
# threshold nobody can cite is in the same position as a measure nobody has tested.
SOURCED = "SOURCED"

# Corpus floors below which no claim is worth making. UNVALIDATED, and this is the
# reasoning: at 0 fires in 10 clean examples the Wilson upper bound on the false-positive
# rate is 0.28, so the strongest honest sentence is "probably under 28 percent", which is
# not a specificity claim anybody should act on. 20 brings it to 0.16. These are floors on
# what the gate will *speak* about, not evidence that 10 is enough.
MIN_GOOD = 10
MIN_BAD = 10


class DiscordantPair(NamedTuple):
    """One (good, bad) pair the measure ranked the wrong way round.

    Carries the indices as well as the scores so the caller can name the offending
    sprites: "measure X scored good/orb 0.51 worse than bad/golem 0.20" is actionable and
    "there were 3 discordant pairs" is not.
    """

    good_index: int
    bad_index: int
    good_score: float
    bad_score: float


class ScoredCorpus(NamedTuple):
    """A labelled corpus after a single measure has been run over it.

    `good_fires`/`bad_fires` are the booleans the measure's *threshold* produced, which is
    a separate question from the scores: a measure can rank every pair correctly and still
    have its cut in the wrong place. Leave them None when the measure has no threshold
    yet, and sensitivity and specificity are then reported as unknown rather than invented.
    """

    good_scores: Sequence[float]
    bad_scores: Sequence[float]
    good_fires: Sequence[bool] | None = None
    bad_fires: Sequence[bool] | None = None


@dataclass(frozen=True)
class MeasureReport:
    """What is known about one measure, and what that supports claiming.

    Everything here is evidence or a verdict derived from it. There is no field for how
    important the measure is, because that is the judgement the numbers cannot make.
    """

    measure: str
    defect: str
    good_count: int
    bad_count: int
    auc: float
    discordant: tuple[DiscordantPair, ...]
    verdict: str
    sensitivity: float | None = None
    specificity: float | None = None
    false_positive_upper: float | None = None
    thresholds: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def unvalidated_thresholds(self) -> tuple[str, ...]:
        """The declared thresholds that nobody has sourced."""
        return tuple(sorted(n for n, p in self.thresholds.items() if p != SOURCED))

    def summary(self) -> str:
        """One line, carrying the numbers that justify the verdict rather than the verdict alone."""
        parts = [
            f"{self.verdict:11s} {self.measure}",
            f"detects={self.defect}",
            f"n={self.good_count} good / {self.bad_count} bad",
            f"auc={self.auc:.3f}",
            f"discordant={len(self.discordant)}",
        ]
        if self.sensitivity is not None:
            parts.append(f"sens={self.sensitivity:.2f}")
        if self.specificity is not None:
            parts.append(f"spec={self.specificity:.2f}")
        if self.false_positive_upper is not None:
            parts.append(f"fp<={self.false_positive_upper:.3f}")
        if self.unvalidated_thresholds:
            parts.append(f"unsourced={','.join(self.unvalidated_thresholds)}")
        return "  ".join(parts)


def auc(positive_scores: Sequence[float], negative_scores: Sequence[float]) -> float:
    """Area under the ROC curve, as the Mann-Whitney U statistic over all n1*n2 pairs.

    Which is to say: exactly the probability that the measure ranks a randomly chosen bad
    item worse than a randomly chosen good one. Positives are the defective items, because
    the defect is the thing being detected.

    Read it as follows. **0.5 is a coin.** Below 0.5 means the measure has a sign error and
    is detecting the defect backwards, which is worth knowing because it is fixable by
    negating it, where 0.5 is not fixable by anything. 1.0 is perfect separation.

    Ties count half, which is the only treatment that keeps a constant measure at 0.5
    rather than at 0 or 1, and 0.5 is the truth about a measure that cannot tell anything
    from anything.

    Computed as the pair count and not from a sorted rank sum: at these corpus sizes the
    quadratic cost is irrelevant, and the pairwise form is the definition, so it cannot
    disagree with `discordant_pairs` about which pairs exist.
    """
    positives, negatives = list(positive_scores), list(negative_scores)
    if not positives or not negatives:
        raise ValueError("auc needs at least one positive and one negative score")
    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def discordant_pairs(
    good_scores: Sequence[float], bad_scores: Sequence[float]
) -> list[DiscordantPair]:
    """Every (good, bad) pair where the good item scores strictly worse than the bad one.

    **This is the hard gate.** Any discordant pair at all means the measure is discarded,
    not tuned, because a measure that ranks known-good art worse than known-bad art is not
    measuring the defect it is named for, and no choice of threshold repairs an ordering.
    Four candidate alignment measures died here; a fifth ranked correctly and was still
    withdrawn, because it turned out to be detecting an arm's termination rather than the
    misaligned legs it claimed to find.

    Ties are not discordant. A tie is a failure to discriminate, which `auc` reports, and
    collapsing the two would hide the difference between "wrong" and "blind".

    The pairs are returned rather than counted so the caller can name them.
    """
    out: list[DiscordantPair] = []
    for gi, good in enumerate(good_scores):
        for bi, bad in enumerate(bad_scores):
            if good > bad:
                out.append(DiscordantPair(gi, bi, good, bad))
    return out


def _normal_quantile(p: float) -> float:
    """The inverse standard normal CDF, by bisection on the stdlib error function.

    Deliberately not one of the published rational approximations: those carry a dozen
    magic constants that a typo in any one of them corrupts silently, and this is a
    confidence bound, so a quietly wrong z would make the harness lie in exactly the way
    it exists to prevent. Bisection over plus or minus 40 sigma reaches float precision in
    about 60 steps and is self-evidently correct from `math.erf`.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must lie strictly between 0 and 1")
    lo, hi = -40.0, 40.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if 0.5 * (1.0 + math.erf(mid / math.sqrt(2.0))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def wilson_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """A Wilson score interval for a proportion, so a specificity claim can be stated honestly.

    The normal approximation collapses at the ends: 0 successes in 20 gives it zero width,
    which would license "the false-positive rate is 0 percent" from twenty sprites. Wilson
    does not degenerate there. With 0 fires in 20 clean examples the upper bound is about
    **0.161**, so the only supportable claim is "false-positive rate probably under 16
    percent", and that is the sentence a report should carry instead of "no false positives
    observed".

    Independence is assumed and is the caller's problem. Mirrored or translated copies of
    the same sprite are near-duplicates: they inflate `trials` without adding evidence, so
    augmenting a clean set that way buys a tighter bound that is not true.
    """
    if trials <= 0:
        raise ValueError("wilson_interval needs at least one trial")
    if not 0 <= successes <= trials:
        raise ValueError("successes must lie between 0 and trials")
    z = _normal_quantile(1.0 - (1.0 - confidence) / 2.0)
    phat = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (phat + z * z / (2.0 * trials)) / denominator
    spread = (z / denominator) * math.sqrt(phat * (1.0 - phat) / trials + z * z / (4.0 * trials**2))
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def family_wise_error(per_reading_rate: float, count: int) -> float:
    """The chance that at least one of `count` independent readings fires spuriously.

    `1 - (1 - rate)**count`. At a 5 percent per-reading rate across 14 readings this is
    about **0.51**, which is the arithmetic behind the fourth failure: a module emitting
    fourteen readings hands a spurious complaint to roughly half of all clean sprites, and
    every one of those complaints costs the reader's trust in the other thirteen. Provided
    so a module can state its own compounding risk up front rather than discover it.

    Independence makes this a best case in one direction and a worst case in the other.
    Readings that share an input are correlated, so they fire together and the real figure
    is lower; readings calibrated on the same two sprites are correlated in their errors
    too, which does not help anybody.
    """
    if not 0.0 <= per_reading_rate <= 1.0:
        raise ValueError("per_reading_rate must lie between 0 and 1")
    if count < 0:
        raise ValueError("count must not be negative")
    return 1.0 - (1.0 - per_reading_rate) ** count


def evaluate_measure(
    measure: str,
    defect: str,
    corpus: ScoredCorpus,
    *,
    thresholds: Mapping[str, str] | None = None,
    min_good: int = MIN_GOOD,
    min_bad: int = MIN_BAD,
    confidence: float = 0.95,
) -> MeasureReport:
    """Score one named measure against one labelled corpus and return a verdict.

    The verdict is decided in this order, and the order is the point:

      1. **DISCARD** when any discordant pair exists. The measure ranked known-good art
         worse than known-bad art, and that is not a tuning problem. This outranks the
         corpus floor deliberately: a small corpus cannot prove a measure works, but it can
         certainly catch one that is wrong, and a wrong ordering does not become provisional
         because there were only four examples of it.
      2. **UNVALIDATED** when either side of the corpus is below its floor and nothing was
         caught. Nothing was demonstrated, which is not the same as a failure and must not
         read as a pass.
      3. **DISCARD** when the AUC is at or below 0.5 with no discordant pairs, which can
         only happen through ties: the measure gave the same answer everywhere and is
         blind. Below 0.5 is unreachable at this step, because a sign error produces
         discordant pairs and is caught by the first rule.
      4. **UNVALIDATED** when the ranking holds but a declared threshold is unsourced. The
         ordering is evidence; the cut is still somebody's guess, and sensitivity and
         specificity computed from a guessed cut describe the guess.
      5. **SHIP** otherwise.

    Nothing here aggregates across measures, and `evaluate_measure` takes one measure for
    that reason.
    """
    good_scores = list(corpus.good_scores)
    bad_scores = list(corpus.bad_scores)
    provenance = dict(thresholds or {})
    notes: list[str] = []

    if not good_scores or not bad_scores:
        return MeasureReport(
            measure=measure,
            defect=defect,
            good_count=len(good_scores),
            bad_count=len(bad_scores),
            auc=float("nan"),
            discordant=(),
            verdict=UNVALIDATED,
            thresholds=provenance,
            notes=("corpus has no examples on one side, so no ranking exists",),
        )

    separation = auc(bad_scores, good_scores)
    discordant = tuple(discordant_pairs(good_scores, bad_scores))

    sensitivity = specificity = false_positive_upper = None
    if corpus.good_fires is not None and corpus.bad_fires is not None:
        good_fires = list(corpus.good_fires)
        bad_fires = list(corpus.bad_fires)
        if len(good_fires) != len(good_scores) or len(bad_fires) != len(bad_scores):
            raise ValueError("fires and scores must be the same length on each side")
        false_positives = sum(1 for f in good_fires if f)
        sensitivity = sum(1 for f in bad_fires if f) / len(bad_fires)
        specificity = 1.0 - false_positives / len(good_fires)
        false_positive_upper = wilson_interval(
            false_positives, len(good_fires), confidence=confidence
        )[1]

    if discordant:
        verdict = DISCARD
        worst = min(discordant, key=lambda p: p.bad_score - p.good_score)
        notes.append(
            f"{len(discordant)} discordant pair(s); worst ranks good #{worst.good_index} "
            f"at {worst.good_score:g} above bad #{worst.bad_index} at {worst.bad_score:g}"
        )
    elif len(good_scores) < min_good or len(bad_scores) < min_bad:
        verdict = UNVALIDATED
        notes.append(
            f"corpus below floor ({len(good_scores)}/{min_good} good, "
            f"{len(bad_scores)}/{min_bad} bad)"
        )
    elif separation <= 0.5:
        verdict = DISCARD
        notes.append("no separation: every pair is tied, so the measure discriminates nothing")
    elif any(p != SOURCED for p in provenance.values()):
        verdict = UNVALIDATED
        notes.append(
            "ranking holds but a threshold is unsourced, so sensitivity and specificity "
            "describe a guessed cut"
        )
    else:
        verdict = SHIP

    if not provenance:
        notes.append("no threshold declared, so this is a ranking result only")
    return MeasureReport(
        measure=measure,
        defect=defect,
        good_count=len(good_scores),
        bad_count=len(bad_scores),
        auc=separation,
        discordant=discordant,
        verdict=verdict,
        sensitivity=sensitivity,
        specificity=specificity,
        false_positive_upper=false_positive_upper,
        thresholds=provenance,
        notes=tuple(notes),
    )


def mutation_score(detections: Mapping[str, Sequence[str]]) -> tuple[float, tuple[str, ...]]:
    """The fraction of seeded defects that at least one measure detected, and the survivors.

    `detections` maps a mutant's label to the measures that fired on it. The survivors are
    returned because they are the actionable half: "mutation score 0.62" is a number, and
    "nothing detects a one-pixel offset, a collapsed ramp step, or a desaturated midpoint"
    is a work list.

    This is a property of the *harness*, not of a sprite, and it is the one aggregate in
    this module for that reason. It cannot be computed for a single sprite and so cannot
    become a quality score by accident.
    """
    if not detections:
        return (0.0, ())
    survivors = tuple(sorted(label for label, fired in detections.items() if not fired))
    return (1.0 - len(survivors) / len(detections), survivors)
