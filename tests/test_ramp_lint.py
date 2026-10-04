"""The ramp lints and the value-structure measures, tested without Aseprite.

Three kinds of test here, and the second two are the point of the module.

1. **The maths is checked against published data rather than against itself.** CIEDE2000
   has four places where a plausible implementation is wrong only for hue pairs straddling
   0 degrees, so it is run against all 33 of Sharma, Wu and Dalal's supplementary test
   pairs. The Vienot dichromat matrices are checked against the two structural invariants a
   dichromat projection must satisfy, which is what makes them verifiable offline.

2. **Each lint is run on a constructed ramp whose answer is known by hand**, so a passing
   test means the measure measures what it says and not merely that it returns a number.

3. **The ranking gates are asserted explicitly, including the two that fail.** A measure
   that ranks a known-good example worse than a known-bad one is discarded, and the tests
   below pin the inversions that caused two readings to be discarded. They exist so that
   the next person to reach for a threshold on value-group components, or on the notan
   light half, finds out here that the reference art does not support one.

Every test is marked `pure`: `tests/conftest.py` skips any test in a module outside its
allowlist unless the test is marked, and this module is not on that allowlist.

**Two of the five reference sprites are not in git.** `workspace/` is ignored by
`.gitignore` except for its `.gitkeep`, so `workspace/orb_3_full.png` and
`workspace/golem.png` exist locally and not on a fresh clone. Every load-bearing assertion
below is therefore made against the three tracked references (`assets/skeleton.png`,
`docs/assets/showcase/dungeon.png`, `docs/assets/showcase/item_sheet.png`), which happen to
be enough to demonstrate both ranking-gate failures on their own. The two ignored sprites
carry confirming assertions that skip with a reason naming the gitignore, and their measured
numbers are written into `core/ramplint.py` so the evidence survives the skip.
"""

from __future__ import annotations

import itertools
import pathlib
import subprocess
import sys

import pytest

from aseprite_mcp.core import quality, ramplint

pytestmark = pytest.mark.pure

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------------- ramps
# The eleven ramps this repository's showcase scripts actually declare, materialised as
# literal colour lists. Taken from `generate_ramp` and `ramp_between` with the arguments in
# `scripts/showcase/`, and written out rather than imported: `core/` must not depend on
# `tools/`, and a test that reached into `tools.palette` to build its fixtures would make
# this module's test suite depend on exactly what `test_core_ramplint_is_importable_without_the_mcp_sdk`
# asserts it does not.
#
# Eight belong to known-good art and three to known-bad, which is marked per ramp because
# the specificity claims in `core/ramplint.py` are counted over this split.
GOOD_RAMPS = {
    # scripts/showcase/orb.py, drawn into workspace/orb_3_full.png
    "ORB": ["#17145d", "#283aa7", "#5a7fd4", "#a6c4e6", "#f0f7fb"],
    # scripts/showcase/items.py, drawn into docs/assets/showcase/item_sheet.png
    "STEEL": ["#2b2e47", "#3c4363", "#4e587e", "#606e98", "#7b89aa", "#96a3bb", "#b2bccc",
              "#cdd4de", "#e8ecef"],
    "GOLD": ["#514802", "#826e05", "#b38f08", "#e3ab0c", "#f2b632", "#f4c064", "#f6cf96",
             "#fae2c7", "#fefaf7"],
    "WOOD": ["#060402", "#23190c", "#412c16", "#5d3e21", "#7a4e2c", "#965d37", "#b26b43",
             "#c07d5c", "#cb9179"],
    "PAINT": ["#03050b", "#0d1a37", "#183361", "#234f8b", "#2f6fb5", "#4b91cf", "#76b0d9",
              "#a1cce4", "#cbe4f0"],
    "PARCH": ["#4b421d", "#73632e", "#9c833f", "#bb9e59", "#cbb382", "#dbcaab", "#ece2d3",
              "#fefdfc", "#ffffff"],
    "RIBBON": ["#000000", "#1e0f0a", "#442017", "#6a2f24", "#8f3b32", "#b44540", "#c56263",
               "#d2888c", "#e0adb3"],
    # scripts/showcase/dungeon.py, drawn into docs/assets/showcase/dungeon.png
    "FLAME": ["#481a00", "#7d3400", "#b35200", "#e87500", "#ff9a1f", "#feba55", "#fed58b",
              "#feebc0", "#fffcf5"],
}
BAD_RAMPS = {
    # scripts/showcase/skeleton.py, drawn into assets/skeleton.png
    "BONE": ["#a69f69", "#bfb796", "#d9d3c2", "#f4f2ed", "#ffffff"],
    # scripts/showcase/golem.py, drawn into workspace/golem.png
    "STONE": ["#0e0d12", "#1e1420", "#38212e", "#583332", "#7c5b46", "#a28061", "#baa891",
              "#d6cfc3"],
    "CORE": ["#122f3c", "#1a545a", "#2a9083", "#4acbb8", "#9de3d8"],
}
ALL_RAMPS = {**GOOD_RAMPS, **BAD_RAMPS}

GREY_RAMP = ["#101010", "#404040", "#707070", "#a0a0a0", "#d0d0d0"]


# ------------------------------------------------------------------------- the references
# Native size and the integer factor the committed PNG was exported at. Every one of these
# was exported with nearest-neighbour scaling, which `_load` asserts rather than assumes:
# if a factor were wrong, the blocks would not be uniform and every number measured from
# the file would be measured from the wrong grid.
REFERENCES = {
    "orb": ("workspace/orb_3_full.png", 8, "good"),
    "dungeon": ("docs/assets/showcase/dungeon.png", 5, "good"),
    "item_sheet": ("docs/assets/showcase/item_sheet.png", 5, "good"),
    "golem": ("workspace/golem.png", 1, "bad"),
    "skeleton": ("assets/skeleton.png", 8, "bad"),
}
# The three that are in git. `workspace/` is ignored, so the other two are local-only.
TRACKED = ("dungeon", "item_sheet", "skeleton")


def _load(name: str) -> quality.Grid:
    """One reference sprite as a grid of "#RRGGBBAA", at native resolution.

    Skips, with the reason, when the file is not in the checkout: two of the five live under
    the gitignored `workspace/`.
    """
    relative, scale, _ = REFERENCES[name]
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not in this checkout (workspace/ is gitignored)")
    pil = pytest.importorskip("PIL.Image")
    image = pil.open(path).convert("RGBA")
    width, height = image.size
    assert width % scale == 0 and height % scale == 0, (
        f"{relative} is {width}x{height}, which is not a whole multiple of {scale}")
    pixels = image.load()
    # The export was nearest-neighbour, so every scale x scale block must be one colour.
    # Checked on the corners and the centre of each block rather than every pixel, which
    # keeps a 560x360 file cheap while still failing on a resampled export.
    for by in range(height // scale):
        for bx in range(width // scale):
            origin = pixels[bx * scale, by * scale]
            for dx, dy in {(0, 0), (scale - 1, 0), (0, scale - 1), (scale - 1, scale - 1),
                           (scale // 2, scale // 2)}:
                assert pixels[bx * scale + dx, by * scale + dy] == origin, (
                    f"{relative} is not a clean {scale}x upscale at block ({bx}, {by})")
    def hexed(x: int, y: int) -> str:
        r, g, b, a = pixels[x * scale, y * scale]
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"

    return [[hexed(x, y) for x in range(width // scale)] for y in range(height // scale)]


def _block(*rows: str, legend: dict[str, str]) -> quality.Grid:
    """A grid from an ASCII picture, as `tests/test_quality.py` builds one."""
    return [[legend.get(char, "#00000000") for char in row] for row in rows]


# ============================================================= the maths, against sources

# SOURCED: Sharma, Wu and Dalal (2005), "The CIEDE2000 color-difference formula:
# implementation notes, supplementary test data, and mathematical observations", Color
# Research and Application 30(1), 21-30. Pairs 9 to 16 and 21 to 24 exist specifically to
# catch implementations that mishandle the mean hue across the 0/360 boundary, and pairs 33
# and 34 to catch the lightness term near black.
SHARMA_PAIRS = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


@pytest.mark.parametrize(("lab1", "lab2", "expected"), SHARMA_PAIRS)
def test_ciede2000_matches_the_published_test_data(lab1, lab2, expected):
    """Every published pair, to four decimal places. The thresholds mean nothing otherwise.

    The whole case for using CIEDE2000 rather than Oklab's own distance is that the
    perceptibility numbers the lint quotes are in CIEDE2000 units. That argument is only
    worth anything if this function is CIEDE2000, so it is checked against the data rather
    than against a second implementation of the same recollection.
    """
    assert ramplint.ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)


def test_ciede2000_is_symmetric_and_zero_on_itself():
    for first, second, _ in SHARMA_PAIRS[:8]:
        assert ramplint.ciede2000(first, second) == pytest.approx(
            ramplint.ciede2000(second, first))
        assert ramplint.ciede2000(first, first) == pytest.approx(0.0)


def test_to_lab_puts_the_sRGB_anchors_where_CIELAB_says():
    """White at L 100, black at 0, and both neutral. A wrong white point shows up here."""
    white = ramplint.to_lab((255, 255, 255))
    assert white[0] == pytest.approx(100.0, abs=1e-3)
    assert white[1] == pytest.approx(0.0, abs=1e-2)
    assert white[2] == pytest.approx(0.0, abs=1e-2)

    black = ramplint.to_lab((0, 0, 0))
    assert black == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)

    # Mid grey is famously *not* at L 50: sRGB's #808080 is about 53.6, because the encoding
    # is perceptual and CIELAB's lightness is a different perceptual curve.
    assert ramplint.to_lab((128, 128, 128))[0] == pytest.approx(53.585, abs=0.01)


# ====================================================================== monotone lightness


def test_monotone_lightness_passes_a_ramp_that_only_rises():
    result = ramplint.monotone_lightness(GREY_RAMP)
    assert result["monotone"] is True
    assert result["direction"] == "lighter"
    assert result["reversals"] == [] and result["ties"] == []
    assert result["lightness"] == sorted(result["lightness"])
    assert ramplint.ramp_readings(ramplint.ramp_lints(GREY_RAMP)) == []


def test_monotone_lightness_passes_a_ramp_that_only_falls():
    result = ramplint.monotone_lightness(list(reversed(GREY_RAMP)))
    assert result["monotone"] is True
    assert result["direction"] == "darker"
    assert result["reversals"] == []


def test_monotone_lightness_finds_a_dip_in_the_middle():
    """Known by hand: entry 2 is darker than both its neighbours, so there are two faults.

    One reversal going into it and one coming out, because the ramp as a whole rises and
    the step down into entry 2 is against that direction while the step back up is with it.
    Only the step against the direction is a reversal, so exactly one is expected at index 1.
    """
    dipped = ["#101010", "#a0a0a0", "#404040", "#d0d0d0"]
    result = ramplint.monotone_lightness(dipped)
    assert result["monotone"] is False
    assert [r["at"] for r in result["reversals"]] == [1]
    assert result["reversals"][0]["delta"] < 0
    assert result["max_reversal"] > 0.2

    reading = ramplint.ramp_readings(ramplint.ramp_lints(dipped))
    assert len(reading) == 1
    assert "reverses direction between entry 1 and entry 2" in reading[0]


def test_monotone_lightness_finds_a_clipped_end_as_a_tie():
    """A ramp whose top two entries are the same colour steps nowhere between them."""
    clipped = ["#101010", "#404040", "#a0a0a0", "#ffffff", "#ffffff"]
    result = ramplint.monotone_lightness(clipped)
    assert result["monotone"] is False
    assert result["ties"] == [3]
    assert result["reversals"] == []

    reading = ramplint.ramp_readings(ramplint.ramp_lints(clipped))
    assert any("same lightness" in line for line in reading)


def test_monotone_lightness_is_not_fooled_by_the_yellow_blue_trap():
    """The reason this reuses Oklab instead of HLS lightness, asserted rather than asserted.

    HLS lightness is (max + min) / 2 of the raw channels, so it reports 0.500 for pure
    yellow and 0.500 for pure blue. A ramp running blue, yellow, blue is flat in HLS and so
    would pass a monotonicity check built on it, in both directions at once. In Oklab the
    two are nearly a third of the scale apart and the reversal is found.
    """
    import colorsys

    for colour in ("#ffff00", "#0000ff"):
        rgb = tuple(int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        assert colorsys.rgb_to_hls(*rgb)[1] == pytest.approx(0.5)

    trap = ["#0000ff", "#ffff00", "#0000ff"]
    result = ramplint.monotone_lightness(trap)
    assert result["monotone"] is False
    assert [r["at"] for r in result["reversals"]] == [1]
    assert abs(result["lightness"][1] - result["lightness"][0]) > 0.3


def test_every_showcase_ramp_is_monotone():
    """All eleven, the known-bad ones included, which is why this is not a quality signal."""
    for name, ramp in ALL_RAMPS.items():
        result = ramplint.monotone_lightness(ramp)
        assert result["monotone"] is True, f"{name} is not monotone: {result}"
        assert result["direction"] == "lighter", f"{name} runs the wrong way"


# =========================================================================== step evenness


def test_step_evenness_flags_the_parchment_near_clip():
    """The one known-good ramp this fires on, and it is a true positive.

    `#fefdfc` against `#ffffff` is dE 0.73, under the 1.0 at which a difference becomes
    visible at all, so the nine-step ramp has eight usable entries.
    `scripts/showcase/items.py` asserts `len(set(colors)) == steps` against exactly this
    failure and does not catch it, because two hex strings that differ are distinct however
    identical the colours they name.
    """
    result = ramplint.step_evenness(GOOD_RAMPS["PARCH"])
    assert len(result["imperceptible_pairs"]) == 1
    pair = result["imperceptible_pairs"][0]
    assert pair["at"] == 7
    assert pair["colors"] == ["#fefdfc", "#ffffff"]
    assert pair["de"] == pytest.approx(0.73, abs=0.01)
    assert pair["de"] < ramplint.DE_IMPERCEPTIBLE

    # And the hex-distinctness check the showcase script relies on passes on this ramp,
    # which is the gap this lint closes.
    assert len(set(GOOD_RAMPS["PARCH"])) == len(GOOD_RAMPS["PARCH"])

    # The entry is not merely redundant: in the committed sheet nothing is drawn with it.
    # `#ffffff` covers 8 pixels and `#fefdfc` covers none.
    drawn = [colour for row in _load("item_sheet") for colour in row]
    assert drawn.count("#ffffffff") == 8
    assert drawn.count("#fefdfcff") == 0

    reading = ramplint.ramp_readings(ramplint.ramp_lints(GOOD_RAMPS["PARCH"]))
    assert len(reading) == 1
    assert "#fefdfc" in reading[0] and "buys nothing" in reading[0]


def test_step_evenness_passes_every_other_showcase_ramp():
    """Ten of eleven have no imperceptible pair, and the smallest step on them is 3.60.

    The dE 1.0 line therefore sits in an empty band almost three units wide rather than
    against a cluster of real values, which is the evidence that it separates something.
    """
    smallest = {}
    for name, ramp in ALL_RAMPS.items():
        result = ramplint.step_evenness(ramp)
        smallest[name] = result["min"]
        if name != "PARCH":
            assert result["imperceptible_pairs"] == [], f"{name} fired: {result}"

    others = {n: v for n, v in smallest.items() if n != "PARCH"}
    assert min(others.values()) == pytest.approx(3.60, abs=0.01)
    assert min(others, key=others.get) == "GOLD"
    assert smallest["PARCH"] < ramplint.DE_IMPERCEPTIBLE < min(others.values())


def test_step_evenness_reports_the_ratio_and_passes_judgement_on_none_of_it():
    """The discarded threshold, pinned. `GOLD` is uneven and correct, so it gets no sentence.

    Its ratio is 4.18, the widest of any showcase ramp once the parchment near-clip is set
    aside, and it is a committed known-good ramp built with the easing the documentation
    recommends. Any threshold on evenness fires on it.
    """
    result = ramplint.step_evenness(GOOD_RAMPS["GOLD"])
    assert result["ratio"] == pytest.approx(4.18, abs=0.01)
    assert result["imperceptible_pairs"] == []
    assert ramplint.ramp_readings(ramplint.ramp_lints(GOOD_RAMPS["GOLD"])) == []

    ratios = {name: ramplint.step_evenness(r)["ratio"] for name, r in ALL_RAMPS.items()}
    assert min(ratios.values()) == pytest.approx(1.41, abs=0.01)
    assert max(ratios.values()) == pytest.approx(18.80, abs=0.01)


def test_step_evenness_calls_an_identical_pair_infinitely_uneven_rather_than_crashing():
    result = ramplint.step_evenness(["#404040", "#404040", "#d0d0d0"])
    assert result["min"] == 0.0
    assert result["ratio"] == float("inf")
    assert len(result["imperceptible_pairs"]) == 1


# ========================================================================== step contrast


def test_step_contrast_adjacent_ratios_are_low_on_every_correct_ramp():
    """Why there is no threshold on them: all eleven would fail one.

    Minimum adjacent ratios run 1.02 to 1.66 across the showcase ramps, so a threshold at
    1.7 or above fires on all eleven and one below 1.02 fires on none.
    """
    minima = {name: ramplint.step_contrast(r)["min_adjacent"] for name, r in ALL_RAMPS.items()}
    assert min(minima.values()) == pytest.approx(1.02, abs=0.01)
    assert max(minima.values()) == pytest.approx(1.66, abs=0.01)
    assert all(value < quality.WCAG_GRAPHICAL_CONTRAST for value in minima.values())


def test_step_contrast_span_is_reported_and_carries_no_reading():
    """The discarded span reading, pinned.

    `BONE` is the only showcase ramp whose ends fall under 3:1, at 2.70, and it belongs to a
    known-bad sprite, which is what made the reading look good. It is withdrawn because a
    high-key material ramp with the dark supplied separately reaches 2.70 legitimately, and
    `scripts/showcase/skeleton.py` is that case: it declares `BONE` and `DARK = "#241f2b"`
    side by side. So `span_clears_3to1` is reported and nothing is said about it.
    """
    bone = ramplint.step_contrast(BAD_RAMPS["BONE"])
    assert bone["span"] == pytest.approx(2.70, abs=0.01)
    assert bone["span_clears_3to1"] is False
    assert ramplint.ramp_readings(ramplint.ramp_lints(BAD_RAMPS["BONE"])) == []

    spans = {name: ramplint.step_contrast(r)["span"] for name, r in ALL_RAMPS.items()}
    failing = [name for name, value in spans.items() if value < quality.WCAG_GRAPHICAL_CONTRAST]
    assert failing == ["BONE"]
    assert min(v for n, v in spans.items() if n != "BONE") == pytest.approx(7.67, abs=0.01)

    # And as a continuous ordering it fails the ranking gate outright: a known-bad ramp
    # spans wider than a known-good one.
    assert spans["STONE"] > spans["WOOD"]


# ====================================================================== hue shift direction


def test_hue_shift_direction_reports_the_sign_both_ways_and_judges_neither():
    warm = ramplint.hue_shift_direction(GOOD_RAMPS["ORB"])
    assert warm["warm_highlight"] is True
    assert warm["delta_b"] > 0

    # A fire ramp running from a deep orange-brown to a near-white: its top entry is less
    # yellow than its bottom one, correctly, and a lint on the sign would fire on it.
    cool = ramplint.hue_shift_direction(GOOD_RAMPS["FLAME"])
    assert cool["warm_highlight"] is False
    assert cool["delta_b"] == pytest.approx(-0.0477, abs=0.001)

    assert ramplint.ramp_readings(ramplint.ramp_lints(GOOD_RAMPS["FLAME"])) == []


def test_a_cool_highlight_is_reported_on_half_the_known_good_ramps():
    """Four of the eight known-good ramps invert the convention, so it cannot be a lint."""
    cool = [name for name, ramp in GOOD_RAMPS.items()
            if not ramplint.hue_shift_direction(ramp)["warm_highlight"]]
    assert sorted(cool) == ["FLAME", "GOLD", "PAINT", "PARCH"]


def test_hue_shift_direction_reports_the_chroma_its_sign_rests_on():
    """A near-neutral ramp's hue sign is rounding, and the caller is given what it needs."""
    result = ramplint.hue_shift_direction(GREY_RAMP)
    assert max(result["chroma_ends"]) < 0.01


# ======================================================== value groups, constructed answers


def test_natural_breaks_finds_the_same_optimum_as_brute_force():
    """The clustering is exact, so it is checked against an exhaustive search.

    1-D k-means and Jenks natural breaks minimise the same within-class weighted sum of
    squared deviations, and in one dimension the optimal classes are contiguous in sorted
    order. So the dynamic program is not an approximation and an exhaustive search over
    break positions must agree with it on every input.
    """
    levels = [(0.01, 5), (0.05, 3), (0.06, 11), (0.4, 2), (0.42, 7), (0.9, 4), (0.95, 1)]

    def cost(run):
        weight = sum(n for _, n in run)
        mean = sum(v * n for v, n in run) / weight
        return sum(n * (v - mean) ** 2 for v, n in run)

    for groups in (2, 3, 4):
        best = min(
            (sum(cost(levels[a:b]) for a, b in itertools.pairwise((0, *cuts, len(levels)))),
             cuts)
            for cuts in itertools.combinations(range(1, len(levels)), groups - 1)
        )
        starts = ramplint._natural_breaks(levels, groups)
        mine = sum(cost(levels[a:b])
                   for a, b in itertools.pairwise((*starts, len(levels))))
        assert starts == [0, *best[1]], f"k={groups}: {starts} against {best[1]}"
        assert mine == pytest.approx(best[0])


def test_value_groups_splits_three_bands_it_can_see_by_hand():
    """Three rows of three known luminances: the shares and the component counts are exact."""
    grid = _block(
        "aaaa", "aaaa", "bbbb", "cccc",
        legend={"a": "#101010ff", "b": "#808080ff", "c": "#f0f0f0ff"},
    )
    result = ramplint.value_groups(grid, 3)
    assert result["drawn_pixels"] == 16
    assert result["distinct_colors"] == 3
    assert [group["share"] for group in result["groups"]] == [0.5, 0.25, 0.25]
    # Each band is one solid run of pixels, so each is a single component.
    assert [group["components"] for group in result["groups"]] == [1, 1, 1]
    assert [group["components_for_90pct"] for group in result["groups"]] == [1, 1, 1]
    assert [group["largest_share"] for group in result["groups"]] == [1.0, 1.0, 1.0]


def test_value_groups_tells_a_massed_group_from_a_scattered_one():
    """Same share, same pixel count, different arrangement. This is the whole measure."""
    massed = _block(
        "aabb", "aabb", "aabb", "aabb",
        legend={"a": "#101010ff", "b": "#f0f0f0ff"},
    )
    scattered = _block(
        "abab", "baba", "abab", "baba",
        legend={"a": "#101010ff", "b": "#f0f0f0ff"},
    )
    lhs = ramplint.value_groups(massed, 2)
    rhs = ramplint.value_groups(scattered, 2)
    assert [g["share"] for g in lhs["groups"]] == [g["share"] for g in rhs["groups"]] == [0.5, 0.5]
    assert [g["components"] for g in lhs["groups"]] == [1, 1]
    # A checkerboard is connected diagonally and nothing else, so under the orthogonal
    # connectivity this module uses every cell is its own component.
    assert [g["components"] for g in rhs["groups"]] == [8, 8]
    assert [g["largest_share"] for g in rhs["groups"]] == [0.125, 0.125]


def test_value_groups_ignores_transparent_pixels():
    """Three drawn pixels of six cells, and the transparent ones are not a value group."""
    grid = _block("a.b", ".a.", legend={"a": "#101010ff", "b": "#f0f0f0ff"})
    result = ramplint.value_groups(grid, 2)
    assert result["drawn_pixels"] == 3
    assert result["distinct_colors"] == 2
    assert [group["pixels"] for group in result["groups"]] == [2, 1]


def test_value_groups_refuses_fewer_than_two_groups():
    with pytest.raises(ValueError, match="at least 2 groups"):
        ramplint.value_groups(_block("a", legend={"a": "#101010ff"}), 1)


def test_notan_splits_at_the_median_not_the_midpoint():
    """A sprite that is mostly dark is still split in half, which is the point of the median.

    Nine of twelve pixels are near-black and three are near-white. Posterising at the
    midpoint of the luminance range would call it 75 percent dark and say nothing; the
    median splits it where the pixels are.
    """
    grid = _block(
        "aaaa", "aaaa", "abbb",
        legend={"a": "#0a0a0aff", "b": "#f0f0f0ff"},
    )
    result = ramplint.notan(grid)
    assert result["drawn_pixels"] == 12
    # Dark is "no brighter than the median", so a sprite whose median colour covers most of
    # it comes back lopsided. That is true of the sprite rather than an artefact.
    assert result["dark"]["pixels"] == 9
    assert result["light"]["pixels"] == 3
    assert result["dark"]["components"] == 1
    assert result["light"]["components"] == 1
    assert result["light"]["largest_share"] == 1.0


def test_notan_and_value_groups_are_empty_on_an_empty_frame():
    blank = _block("..", "..", legend={})
    assert ramplint.value_groups(blank)["groups"] == []
    assert ramplint.notan(blank)["drawn_pixels"] == 0


def test_value_groups_gives_back_as_many_groups_as_the_art_allows():
    """Three groups asked of a two-colour sprite is two groups, not a crash or an empty one."""
    grid = _block("ab", "ab", legend={"a": "#101010ff", "b": "#f0f0f0ff"})
    result = ramplint.value_groups(grid, 3)
    assert len(result["groups"]) == 2
    assert [group["pixels"] for group in result["groups"]] == [2, 2]
    assert sum(group["share"] for group in result["groups"]) == pytest.approx(1.0)

    flat = _block("aa", "aa", legend={"a": "#777777ff"})
    only = ramplint.value_groups(flat, 3)
    assert len(only["groups"]) == 1
    assert only["groups"][0]["share"] == 1.0


def test_the_level_folding_fallback_keeps_every_pixel_when_a_photo_is_handed_in():
    """The guard that stops an O(k n^2) exact clustering from hanging on non-pixel-art.

    It cannot fire on pixel art: the five reference sprites run 5 to 49 distinct colours
    against a cap of 256. It is tested anyway, because an untested fallback is a fallback
    that is wrong the first time it matters. A 512-level greyscale gradient exercises it,
    and what must survive the folding is the pixel count: the clustering may land its
    breaks anywhere, but it may not lose or invent a pixel.
    """
    colours = [f"#{v // 2:02x}{v // 2:02x}{v // 2:02x}ff" for v in range(512)]
    grid = [colours[:256], colours[256:]]
    levels = ramplint._levels(ramplint._drawn_histogram(grid))
    assert len(levels) <= ramplint.MAX_CLUSTER_LEVELS
    assert sum(count for _, count in levels) == 512
    assert levels == sorted(levels)

    result = ramplint.value_groups(grid, 3)
    assert result["drawn_pixels"] == 512
    assert sum(group["pixels"] for group in result["groups"]) == 512


# ====================================================== the ranking gates, asserted outright


def test_ramp_lints_fire_on_exactly_one_showcase_ramp():
    """The ramp half of the ranking gate: nothing good is ranked worse than anything bad.

    Ten of the eleven ramps produce no sentence at all, including all three from known-bad
    art. The eleventh is the parchment near-clip, which is a known-good ramp with a real
    wasted entry, so the one firing is a true positive and not an inversion.
    """
    firing = {name: ramplint.ramp_readings(ramplint.ramp_lints(ramp))
              for name, ramp in ALL_RAMPS.items()}
    assert [name for name, lines in firing.items() if lines] == ["PARCH"]
    assert all(not firing[name] for name in BAD_RAMPS)


def test_the_components_per_value_group_ranking_gate_fails():
    """Pinned so nobody adds a threshold on it. The known-good art scatters harder.

    Components per value group, darkest first, on the three references that are in git:

        item_sheet (good)   15, 32, 19
        dungeon    (good)   25, 75, 53
        skeleton   (bad)     5,  6, 19

    The known-bad skeleton is tidier than both known-good examples in the two darker groups.
    No threshold on the count orders these, in either direction, which is why
    `value_groups` carries no reading.
    """
    counts = {
        name: [group["components"] for group in ramplint.value_groups(_load(name), 3)["groups"]]
        for name in TRACKED
    }
    assert counts["item_sheet"] == [15, 32, 19]
    assert counts["dungeon"] == [25, 75, 53]
    assert counts["skeleton"] == [5, 6, 19]

    # The inversion, stated as the gate states it: a known-good example ranks worse than a
    # known-bad one on this measure, so the measure is discarded rather than tuned.
    assert counts["dungeon"][1] > counts["skeleton"][1]
    assert counts["item_sheet"][0] > counts["skeleton"][0]


def test_the_notan_largest_share_ranking_gate_fails():
    """Pinned for the same reason. A known-bad sprite outranks two known-good ones.

    The light half's largest component share, on the references that are in git:

        skeleton   (bad)    0.496
        dungeon    (good)   0.461
        item_sheet (good)   0.249

    The candidate reading was "a figure lit from one side has one large light mass", and the
    skeleton has one: a compact skull. The item sheet has five objects on one sheet and so
    has none. The measure reads the subject, not the craft.
    """
    shares = {name: ramplint.notan(_load(name))["light"]["largest_share"] for name in TRACKED}
    assert shares["skeleton"] == pytest.approx(0.496, abs=0.001)
    assert shares["dungeon"] == pytest.approx(0.461, abs=0.001)
    assert shares["item_sheet"] == pytest.approx(0.249, abs=0.001)

    assert shares["skeleton"] > shares["dungeon"] > shares["item_sheet"]


def test_the_local_only_references_confirm_both_inversions():
    """The same two gates on the two sprites that are not in git, when they are present.

    The orb is the cleanest value structure in the repository, at one component per value
    group, and the golem is the known-bad figure whose notan light half (0.226) sits *below*
    both known-good figures. Together with the tracked three that puts the two known-bad
    sprites at opposite ends of the range, which is the strongest form of the failure.
    """
    orb = ramplint.value_groups(_load("orb"), 3)
    assert [group["components"] for group in orb["groups"]] == [1, 1, 1]
    assert ramplint.notan(_load("orb"))["light"]["largest_share"] == pytest.approx(1.0)

    golem_groups = ramplint.value_groups(_load("golem"), 3)
    assert [group["components"] for group in golem_groups["groups"]] == [3, 33, 23]
    # The golem's recorded defect from a second direction: 75 percent of the drawing in the
    # darkest value group, 99.8 percent of that in one component. A keyline that has become
    # the drawing. The share was 0.740 before the figure gained its pelvis row, which added
    # four drawn pixels and no new value.
    assert golem_groups["groups"][0]["share"] == pytest.approx(0.747, abs=0.001)
    assert golem_groups["groups"][0]["largest_share"] == pytest.approx(0.998, abs=0.001)

    golem_share = ramplint.notan(_load("golem"))["light"]["largest_share"]
    assert golem_share == pytest.approx(0.232, abs=0.001)
    skeleton_share = ramplint.notan(_load("skeleton"))["light"]["largest_share"]
    assert skeleton_share > golem_share


# ========================================================================= the CVD re-check


def test_the_cvd_matrices_satisfy_the_invariants_a_projection_must():
    """What makes the matrices verifiable offline, and what caught them being wrong once.

    They were first written as the LMS-space projection coefficients applied to linear RGB,
    which is a real pair of numbers put in the wrong space. Both invariants below fail for
    that version: its rows sum to 1.74 and 0.50 rather than 1, so white turned cyan.
    """
    for kind, matrix in ramplint._CVD_MATRICES.items():
        for row in matrix:
            assert sum(row) == pytest.approx(1.0, abs=1e-5), f"{kind} does not preserve white"
        assert matrix[0] == matrix[1], f"{kind} does not confuse two primaries"

    for kind in ("protanopia", "deuteranopia"):
        # White, black and grey are fixed points, which follows from the rows summing to 1.
        for neutral in ((255, 255, 255), (0, 0, 0), (128, 128, 128), (64, 64, 64)):
            assert ramplint.simulate_cvd(neutral, kind) == neutral
        # And so is yellow, which sits on the confusion axis for both deficiencies.
        assert ramplint.simulate_cvd((255, 255, 0), kind) == (255, 255, 0)
        # Blue is carried through untouched: neither deficiency is in the S cone.
        assert ramplint.simulate_cvd((0, 0, 255), kind) == (0, 0, 255)


def test_cvd_simulation_collapses_red_and_green_onto_yellows():
    """Red and green both land on the yellow axis, at different lightnesses.

    And the lightnesses differ between the two deficiencies in the documented direction: a
    protanope loses the L cone, which carries most of red's luminance, so red comes back
    much darker for a protanope than for a deuteranope.
    """
    for kind in ("protanopia", "deuteranopia"):
        for pure in ((255, 0, 0), (0, 255, 0)):
            r, g, b = ramplint.simulate_cvd(pure, kind)
            assert r == g, f"{pure} under {kind} is not on the yellow axis"
            assert b < r, f"{pure} under {kind} is not a yellow"

    assert (ramplint.simulate_cvd((255, 0, 0), "protanopia")[0]
            < ramplint.simulate_cvd((255, 0, 0), "deuteranopia")[0])


def _halves(left: str, right: str, size: int = 8) -> quality.Grid:
    """A sprite of two equal blocks that touch along one straight boundary."""
    return [[left] * size + [right] * size for _ in range(size)]


def test_cvd_recheck_fires_on_a_sprite_that_separates_by_hue_alone():
    """The constructed positive: two halves told apart by hue, and by nothing else.

    `#c00000` against `#008000` is dE 68 apart in normal vision, which is as different as
    two colours in a 16-colour palette get, and dE 1.11 apart for a deuteranope, under the
    1.3 at which a difference becomes visible at all.
    """
    grid = _halves("#c00000ff", "#008000ff")
    result = ramplint.cvd_recheck(grid)
    assert result["touching_pairs"] == 1
    assert result["deuteranopia"]["collapsed_pairs"] == 1

    worst = result["deuteranopia"]["worst"][0]
    assert sorted(worst["colors"]) == ["#008000", "#c00000"]
    assert worst["de_before"] == pytest.approx(68.04, abs=0.1)
    assert worst["de_after"] == pytest.approx(1.11, abs=0.05)
    assert worst["de_before"] >= ramplint.DE_ACCEPTABILITY
    assert worst["de_after"] < ramplint.DE_PERCEPTIBLE

    reading = ramplint.cvd_readings(result)
    assert any("deuteranopia" in line for line in reading)


def test_cvd_recheck_fires_on_a_protanopic_collapse_too():
    """The same construction for the other deficiency, which needs a darker green.

    That it needs one is a check on the matrices rather than a detail: a protanope sees red
    much darker than a deuteranope does, so the green that matches it is darker.
    """
    result = ramplint.cvd_recheck(_halves("#fe0000ff", "#006400ff"))
    assert result["protanopia"]["collapsed_pairs"] == 1
    worst = result["protanopia"]["worst"][0]
    assert worst["de_before"] == pytest.approx(69.91, abs=0.1)
    assert worst["de_after"] == pytest.approx(1.23, abs=0.05)


def test_cvd_recheck_is_silent_on_a_sprite_that_separates_by_value():
    """The constructed negative: the same geometry, told apart by value instead of hue."""
    result = ramplint.cvd_recheck(_halves("#1a1a2eff", "#e8e8f0ff"))
    assert result["touching_pairs"] == 1
    assert result["deuteranopia"]["collapsed_pairs"] == 0
    assert result["protanopia"]["collapsed_pairs"] == 0
    assert ramplint.cvd_readings(result) == []


def test_a_wcag_gated_cvd_check_would_have_missed_the_hue_only_collapse():
    """Why the pair test is CIEDE2000 and not the contrast ratio, as a measurement.

    The hue-separated pair is already under 3:1 in normal vision, because WCAG's ratio is a
    function of luminance alone and these two colours are nearly isoluminant. So a check
    gated on "clears 3:1 normally, fails 3:1 simulated" never looks at the pair: it would
    report the sprite clean. And under deuteranopia the ratio barely moves at all, which is
    the deeper problem: composing the projection with WCAG's own coefficients gives
    effective luminance weights of (0.270, 0.658, 0.072) against (0.213, 0.715, 0.072)
    normally.
    """
    result = ramplint.cvd_recheck(_halves("#c00000ff", "#008000ff"))
    worst = result["deuteranopia"]["worst"][0]
    assert worst["ratio_before"] < quality.WCAG_GRAPHICAL_CONTRAST
    assert worst["ratio_after"] == pytest.approx(1.00, abs=0.05)

    # The effective luminance weights, computed rather than quoted.
    coefficients = (0.2126, 0.7152, 0.0722)
    for kind, expected in (("deuteranopia", (0.2700, 0.6578, 0.0722)),
                           ("protanopia", (0.1046, 0.8232, 0.0722))):
        matrix = ramplint._CVD_MATRICES[kind]
        weights = [sum(coefficients[i] * matrix[i][j] for i in range(3)) for j in range(3)]
        assert weights == pytest.approx(expected, abs=1e-3)
    # Deuteranopia moves red's weight away from WCAG's by less than protanopia does, by a
    # wide margin, which is the whole reason a ratio test is blind to it.
    assert abs(0.2700 - 0.2126) < abs(0.1046 - 0.2126)


def test_cvd_recheck_fires_on_none_of_the_tracked_references():
    """Specificity, measured: 449 touching pairs across three sprites and nothing fires."""
    total = 0
    for name in TRACKED:
        result = ramplint.cvd_recheck(_load(name))
        total += result["touching_pairs"]
        assert result["deuteranopia"]["collapsed_pairs"] == 0, name
        assert result["protanopia"]["collapsed_pairs"] == 0, name
        assert ramplint.cvd_readings(result) == [], name
    assert total == 449


def test_the_simulated_notan_moves_only_when_a_simulation_reorders_luminances():
    """The honest bound on the two-value re-run, in both directions.

    It cannot see an equal-area hue swap, because a two-colour image is split in half by its
    own median whatever its colours are. It can see a simulation reordering luminances
    across the median, which is a narrower thing than "the value design collapsed" and is
    why the pair test above carries the question instead.
    """
    # Blind: the hue-separated halves come back with an identical two-value reduction, even
    # though the pair test fires on them.
    hue_only = ramplint.cvd_recheck(_halves("#c00000ff", "#008000ff"))
    assert hue_only["deuteranopia"]["collapsed_pairs"] == 1
    for half in ("dark", "light"):
        assert (hue_only["deuteranopia"]["notan"][half]["pixels"]
                == hue_only["normal"]["notan"][half]["pixels"])

    # Sensitive: a bright red that outranks a mid grey normally and falls below it once
    # simulated moves the partition, and with it the shapes.
    dark, grey, red = "#101018ff", "#8a8a8aff", "#ff1a1aff"
    rows = []
    for y in range(9):
        if y < 3:
            rows.append([dark] * 9)
        elif y < 6:
            rows.append([grey if x % 2 == 0 else red for x in range(9)])
        else:
            rows.append([red] * 9)
    result = ramplint.cvd_recheck(rows)
    before, after = result["normal"]["notan"], result["deuteranopia"]["notan"]
    assert before["light"]["pixels"] == 15 and before["light"]["components"] == 5
    assert after["light"]["pixels"] == 39 and after["light"]["components"] == 1
    assert before["light"]["largest_share"] < after["light"]["largest_share"]


def test_simulate_cvd_refuses_a_deficiency_it_cannot_model():
    """Tritanopia needs the two-plane method, so it is absent rather than approximated."""
    with pytest.raises(ValueError, match="unknown deficiency"):
        ramplint.simulate_cvd((128, 64, 32), "tritanopia")  # type: ignore[arg-type]


# ============================================================================ architecture


def test_core_ramplint_is_importable_without_the_mcp_sdk():
    """`core/` is a library. It may import `core/` and the standard library, nothing else.

    `tests/test_imports.py` discovers every module under `core/` and makes this assertion
    over all of them at once, so this is a second, narrower copy aimed at one module. It is
    worth having separately: this module is the one that wanted a ramp-generating helper
    from `tools.palette` for its fixtures, and the reason its fixtures are literal colour
    lists is that taking that helper would have broken exactly this.
    """
    code = (
        "import sys\n"
        "import aseprite_mcp.core.ramplint as m\n"
        "assert 'aseprite_mcp.app' not in sys.modules, 'ramplint imported the MCP app'\n"
        "assert 'mcp.server' not in sys.modules, 'ramplint imported the MCP server package'\n"
        "assert not any(k.startswith('aseprite_mcp.tools') for k in sys.modules), "
        "'ramplint imported a tools module'\n"
        "assert m.ciede2000 and m.value_groups and m.notan and m.cvd_recheck\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_ramplint_reuses_the_perceptual_maths_rather_than_restating_it():
    """The Oklab and the luminance in this module must be the ones the rest of the code uses.

    A metric with two definitions is a metric that drifts, and the specific drift this
    guards against is the one `quality.luminance` was written for: HLS lightness reports
    0.500 for both pure yellow and pure blue, and a second luminance that got that wrong
    would make this module name a highlight as a shadow.
    """
    from aseprite_mcp.core import ramps

    assert ramplint.ramps is ramps
    assert ramplint.quality is quality
    # The lint's lightness is Oklab's, taken from core.ramps.
    assert ramplint.monotone_lightness(["#0000ff", "#ffff00"])["lightness"] == [
        round(ramps.to_oklab((0, 0, 255))[0], 4),
        round(ramps.to_oklab((255, 255, 0))[0], 4),
    ]
    # And the contrast ratio is quality's, including its sourced 3:1 constant.
    pair = ramplint.step_contrast(["#000000", "#ffffff"])
    assert pair["span"] == pytest.approx(quality.contrast_ratio((0, 0, 0, 255),
                                                                (255, 255, 255, 255)))
    assert quality.WCAG_GRAPHICAL_CONTRAST == 3.0


# --- the colour-vision reading, and how not to test it ---------------------------------


@pytest.mark.pure
def test_cvd_reading_fires_on_a_real_collapse() -> None:
    """A moss green beside a brick red: 45 dE apart normally, 1.2 under deuteranopia.

    This pair was found by search rather than chosen, after two hand-picked "obvious"
    red-against-green cases failed to collapse at all. They failed for the reason the
    reading exists to teach: both differed in lightness as well as in hue, and a
    boundary carried by lightness survives colour vision deficiency. Only a boundary
    drawn in hue alone disappears, which is why the fixture below has two colours of
    nearly equal lightness.

    The pairing is also not contrived. Moss on stone and blood on armour are two of the
    commonest things in this project's subject matter.
    """
    clear, left, right = "#00000000", "#608050ff", "#b05050ff"
    size = 16
    g = [[clear] * size for _ in range(size)]
    for y in range(2, 14):
        for x in range(2, 8):
            g[y][x] = left
        for x in range(8, 14):
            g[y][x] = right

    normal = ramplint.ciede2000(ramplint.to_lab((0x60, 0x80, 0x50)),
                                ramplint.to_lab((0xb0, 0x50, 0x50)))
    assert normal > 40, f"the fixture stopped being distinct in normal vision: {normal}"

    recheck = ramplint.cvd_recheck(g)
    assert recheck["touching_pairs"] == 1, recheck
    assert recheck["deuteranopia"]["collapsed_pairs"] == 1, recheck["deuteranopia"]
    lines = ramplint.cvd_readings(recheck)
    assert [line for line in lines if "deuteranopia" in line], lines


@pytest.mark.pure
def test_cvd_reading_is_silent_when_value_carries_the_boundary() -> None:
    """The same two hues separated in value survive, so this is not a ban on hue."""
    clear = "#00000000"
    size = 16
    g = [[clear] * size for _ in range(size)]
    for y in range(2, 14):
        for x in range(2, 8):
            g[y][x] = "#203018ff"       # the same green, much darker
        for x in range(8, 14):
            g[y][x] = "#e09090ff"       # the same red, much lighter
    recheck = ramplint.cvd_recheck(g)
    assert recheck["deuteranopia"]["collapsed_pairs"] == 0, recheck["deuteranopia"]
    assert ramplint.cvd_readings(recheck) == []
