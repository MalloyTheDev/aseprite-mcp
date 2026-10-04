"""The labelled corpus: twelve known-good sprites, two known-bad, and seeded mutants.

Composition, and why each piece is where it is.

**Good (12).** The reference orb (32x32), the dungeon scene (112x72), five RPG items
(40x40) and five attack frames (80x58), all baked at 1x by `regenerate.py` from art that
ships in this repository as showcase output. "Good" here means published as an example of
what the project produces, which is the strongest label available and is not the same thing
as flawless.

**Known-bad (2).** The golem (64x64) and the skeleton (32x32), the two sprites every
reading in `core/quality.py` was calibrated against. Two is not a corpus, which is the
whole reason the mutants exist, and it is also why a measure validated only against these
two is reported UNVALIDATED rather than SHIP.

**Mutants.** Each good sprite is damaged one defect at a time by `mutations.seed_defects`.
A mutator that cannot seed its defect in a given sprite returns None and contributes
nothing, so the negative count is not a fixed multiple of the positive count and should not
be assumed to be.

Nothing in here is independent in the statistical sense. Five item cells drawn by the same
generator in the same palette are five samples of one style, and seventeen mutants of one
sprite share a parent. A Wilson bound computed over them is narrower than the evidence
deserves, which is noted at the point the bound is reported rather than quietly absorbed.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import NamedTuple

from aseprite_mcp.core import quality, validation

from . import mutations
from .loader import load_grid
from .measures import Sample, declared_ramp, fired, make_sample

HERE = pathlib.Path(__file__).resolve().parent

GOOD_NAMES = (
    "good_orb",
    "good_dungeon",
    "good_item_0",
    "good_item_1",
    "good_item_2",
    "good_item_3",
    "good_item_4",
    "good_attack_0",
    "good_attack_1",
    "good_attack_2",
    "good_attack_3",
    "good_attack_4",
)
BAD_NAMES = ("bad_golem", "bad_skeleton")


class Corpus(NamedTuple):
    """The labelled set, already scored.

    `mutants` and `known_bad` are kept apart rather than merged into one negative set
    because they are negative for different reasons: a mutant is defective by construction
    and carries the name of its defect, while a known-bad sprite is defective in somebody's
    judgement and carries no breakdown at all.
    """

    good: tuple[Sample, ...]
    mutants: tuple[Sample, ...]
    known_bad: tuple[Sample, ...]

    @property
    def parents(self) -> dict[str, Sample]:
        return {s.name: s for s in self.good}

    def mutants_for(self, defects: tuple[str, ...]) -> tuple[Sample, ...]:
        return tuple(s for s in self.mutants if s.defect in defects)


@lru_cache(maxsize=1)
def grids() -> dict[str, list[list[str]]]:
    """Every baked corpus sprite, loaded once, at the resolution it was drawn at."""
    out = {}
    for name in GOOD_NAMES + BAD_NAMES:
        path = HERE / f"{name}.png"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing. Rebuild the corpus with "
                "`uv run --no-sync python tests/corpus/regenerate.py`."
            )
        out[name] = load_grid(path, scale=1)
    return out


@lru_cache(maxsize=1)
def build() -> Corpus:
    """Load, mutate and score the whole corpus.

    Every mutant is scored against **its parent's** declared ramp, which is what makes
    `palette_conformance` mean anything: the question is whether the damage moved pixels off
    the palette the art was drawn with, and scoring a mutant against its own colours would
    answer yes by never.
    """
    loaded = grids()
    good = tuple(
        make_sample(name, "good", loaded[name], declared_ramp=declared_ramp(loaded[name]))
        for name in GOOD_NAMES
    )
    known_bad = tuple(
        make_sample(name, "bad", loaded[name], declared_ramp=declared_ramp(loaded[name]))
        for name in BAD_NAMES
    )
    mutants = []
    for name in GOOD_NAMES:
        parent_ramp = declared_ramp(loaded[name])
        for mutant in mutations.seed_defects(name, loaded[name]):
            mutants.append(
                make_sample(
                    mutant.label,
                    "bad",
                    mutant.grid,
                    declared_ramp=parent_ramp,
                    defect=mutant.defect,
                    parent=mutant.parent,
                )
            )
    return Corpus(good=good, mutants=tuple(mutants), known_bad=known_bad)


class RampPair(NamedTuple):
    name: str
    label: str
    metrics: dict


@lru_cache(maxsize=1)
def ramp_corpus() -> tuple[tuple[RampPair, ...], tuple[RampPair, ...]]:
    """Palettes rather than sprites, for the one measure that reads a palette.

    `quality.ramp_chroma` never sees a pixel: it takes the ramp a caller declared and asks
    whether that ramp's hue rotation is visible or routes through the neutral axis. Scoring
    it on a sprite corpus would be scoring it on an input it does not receive, so it gets
    each good sprite's own palette as the clean side and the same palette with its midpoint
    pulled to grey as the damaged side.
    """
    clean, damaged = [], []
    for name, grid in grids().items():
        if not name.startswith("good_"):
            continue
        ramp = declared_ramp(grid)
        if len(ramp) < 3:
            continue
        faded = mutations.desaturate_ramp(ramp, 1.0)
        if faded is None:
            continue
        clean.append(RampPair(name, "good", {"ramp_chroma": quality.ramp_chroma(ramp)}))
        damaged.append(
            RampPair(f"{name}:desat_100", "bad", {"ramp_chroma": quality.ramp_chroma(faded)})
        )
    return (tuple(clean), tuple(damaged))


class Paired(NamedTuple):
    """One measure's behaviour on matched before-and-after pairs.

    A different question from the absolute report, and the two routinely disagree. The
    absolute report asks whether a fixed threshold can tell good art from bad art across
    sprites, which is what a *reading* claims when it fires. This asks whether the number
    moves the right way when one sprite is damaged, which is what a regression guard claims,
    and is the claim `core/quality.py`'s own docstring actually makes: "Two sprites are only
    comparable when they answer the same prompt."

    A measure can be a sound regression guard and an unsound reading. That is not a
    contradiction and it is the most common outcome here.
    """

    measure: str
    pairs: int
    worse: int
    tied: int
    better: int
    auc: float


def absolute_report(measure, corpus: Corpus | None = None) -> validation.MeasureReport | None:
    """Gate one measure on good sprites against the mutants of the defects it claims.

    None when the measure claims no seeded defect, or when no mutant survives its own gate:
    both mean "this corpus cannot ask the question", which is distinct from a verdict and
    must not be rendered as one.
    """
    c = corpus or build()
    if not measure.targets:
        return None
    good = [s for s in c.good if measure.applies(s)]
    bad = [s for s in c.mutants_for(measure.targets) if measure.applies(s)]
    if not good or not bad:
        return None
    # No declared threshold means no cut, so no sensitivity and no specificity: those
    # numbers describe a cut, and inventing one for a measure that has not got one is how a
    # ranking result gets quoted as a detection rate.
    cut = bool(measure.thresholds)
    scored = validation.ScoredCorpus(
        good_scores=[measure.score(s) for s in good],
        bad_scores=[measure.score(s) for s in bad],
        good_fires=[measure.fires(s) for s in good] if cut else None,
        bad_fires=[measure.fires(s) for s in bad] if cut else None,
    )
    return validation.evaluate_measure(
        measure.name, measure.defect, scored, thresholds=measure.thresholds
    )


def paired_report(measure, corpus: Corpus | None = None) -> Paired | None:
    """The same measure on matched (parent, mutant) pairs it speaks about on both sides."""
    c = corpus or build()
    if not measure.targets:
        return None
    parents = c.parents
    worse = tied = better = 0
    for mutant in c.mutants_for(measure.targets):
        parent = parents[mutant.parent]
        if not (measure.applies(mutant) and measure.applies(parent)):
            continue
        # Reusing the primitive rather than re-deriving ">" keeps one definition of
        # "ranked the wrong way round" in the codebase.
        if validation.discordant_pairs([measure.score(parent)], [measure.score(mutant)]):
            better += 1
        elif measure.score(mutant) == measure.score(parent):
            tied += 1
        else:
            worse += 1
    total = worse + tied + better
    if not total:
        return None
    return Paired(measure.name, total, worse, tied, better, (worse + 0.5 * tied) / total)


def ramp_report(measure=None) -> validation.MeasureReport:
    """Gate the one reading that scores a declared palette rather than a sprite.

    `quality.ramp_chroma` never sees a pixel, so the sprite corpus cannot ask it anything:
    every mutant there is scored against its parent's ramp, which is undamaged by
    construction, and the measure correctly reports no change. Damaging the palette itself is
    the only way to put the defect in front of it.
    """
    from .measures import RAMP_MEASURE

    m = measure or RAMP_MEASURE
    clean, damaged = ramp_corpus()
    scored = validation.ScoredCorpus(
        good_scores=[m.score(s) for s in clean],
        bad_scores=[m.score(s) for s in damaged],
        good_fires=[m.fires(s) for s in clean],
        bad_fires=[m.fires(s) for s in damaged],
    )
    return validation.evaluate_measure(m.name, m.defect, scored, thresholds=m.thresholds)


def ramp_paired(measure=None) -> Paired:
    """The same palette measure on matched clean/damaged ramp pairs."""
    from .measures import RAMP_MEASURE

    m = measure or RAMP_MEASURE
    clean, damaged = ramp_corpus()
    worse = tied = better = 0
    for before, after in zip(clean, damaged, strict=True):
        if validation.discordant_pairs([m.score(before)], [m.score(after)]):
            better += 1
        elif m.score(after) == m.score(before):
            tied += 1
        else:
            worse += 1
    total = worse + tied + better
    return Paired(m.name, total, worse, tied, better, (worse + 0.5 * tied) / total)


def false_positives() -> dict[str, set[str]]:
    """Which readings fire on each piece of known-good art."""
    return {s.name: fired(s) for s in build().good}


def detections() -> dict[str, list[str]]:
    """Per mutant, the readings that fire on it and did not already fire on its parent.

    Parent-relative on purpose. `isolated_pixels` reads 701 on the clean dungeon, because
    dithering is isolated pixels by this definition, so it fires on every mutant of that
    scene; crediting it with detecting any of them would turn a standing false positive into
    apparent sensitivity.
    """
    c = build()
    parents = c.parents
    return {
        s.name: sorted(fired(s) - fired(parents[s.parent]))
        for s in c.mutants
    }


__all__ = [
    "BAD_NAMES",
    "GOOD_NAMES",
    "Corpus",
    "Paired",
    "RampPair",
    "absolute_report",
    "build",
    "detections",
    "false_positives",
    "grids",
    "paired_report",
    "ramp_corpus",
    "ramp_paired",
    "ramp_report",
]
