"""The structural figure measurements, tested without Aseprite.

Three kinds of test live here, and the middle kind is the reason the file exists.

*By construction.* Synthetic shapes whose answer is known before the code runs: a disc of
radius r has a vertical centre line, a figure whose lower half is shifted 3px has a
discontinuity of exactly 3, a one-pixel-wide arm vanishes under one pixel of erosion.

*The ranking gate.* Every measure is run on the project's reference sprites and asserted
to put the known-good ones ahead of the known-bad one. These assertions exist so that an
inversion breaks the build rather than being noticed later, or not at all. Four earlier
attempts at the centre-line measure were abandoned because they ranked a deliberate pose
worse than a misplaced part, and `test_naive_center_deviation_ranks_both_good_poses_worse`
pins that exact failure so it cannot come back wearing a different name.

*Discard records.* `test_keyline_boundary_share_inverts_the_ranking` measures a proposal
that was dropped, and asserts that it really does invert, so the reason for the discard is
in the build and not only in a docstring.

Every test is marked `pure`: this module is not on `conftest.PURE_PYTHON_TESTS`, and
without the marker the whole file is silently skipped wherever Aseprite is absent, which
is every CI run and looks exactly like passing.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from aseprite_mcp.core import figure

REPO = Path(__file__).resolve().parents[1]

# Tracked in git, so these are present on every checkout and a missing one is a real
# failure rather than a reason to skip. `test_reference_sprites_are_present` enforces that.
ORB = REPO / "docs" / "assets" / "showcase" / "orb.png"            # known good, 32x32 at 8x
DUNGEON = REPO / "docs" / "assets" / "showcase" / "dungeon.png"    # known good, 112x72 at 5x
GOLEM = REPO / "docs" / "assets" / "showcase" / "golem.png"        # known bad, 64x64 at 1x
SKELETON = REPO / "assets" / "skeleton.png"                        # 32x32 at 8x, palette defect

# Untracked: these live in `workspace/`, which holds only a .gitkeep in git. They are the
# files the research quoted its numbers from, so they are asserted exactly when a working
# copy has them and passed over when it does not. Nothing here depends on them alone.
WS_ORB = REPO / "workspace" / "orb_3_full.png"
WS_GOLEM = REPO / "workspace" / "golem.png"


# --------------------------------------------------------------------- shape construction
def mask(rows: list[str]) -> figure.Mask:
    """A silhouette from an ASCII picture, '#' drawn and anything else empty."""
    width = max((len(r) for r in rows), default=0)
    return [[c == "#" for c in row.ljust(width, ".")] for row in rows]


def disc(radius: int) -> figure.Mask:
    size = 2 * radius + 1
    return [
        [(x - radius) ** 2 + (y - radius) ** 2 <= radius * radius for x in range(size)]
        for y in range(size)
    ]


def ellipse(a: int, b: int) -> figure.Mask:
    return [
        [((x - a) / a) ** 2 + ((y - b) / b) ** 2 <= 1.0 for x in range(2 * a + 1)]
        for y in range(2 * b + 1)
    ]


# (y0, y1, half_width) per band: head, chest, hips, legs.
FIGURE_BANDS = ((2, 8, 3), (9, 19, 5), (20, 24, 4), (25, 30, 4))


def posed_figure(offset, *, width: int = 32, height: int = 32, bands=FIGURE_BANDS) -> figure.Mask:
    """A stack of horizontal bands whose centre column is `offset(y)` from the middle.

    Rounding is half-up and not `round()` on purpose. Python's `round()` is banker's, so
    `round(20.5)` is 20 while `round(20.501)` is 21, and a true centre sitting exactly on
    .5 therefore renders one row displaced a whole pixel from its neighbours. That is a
    property of the generator, not of the silhouette it stands for, and it put a spurious
    2.00 into the measure in 24 of 672 sweep figures until it was removed.
    """
    def half_up(value: float) -> int:
        return math.floor(value + 0.5)

    out = [[False] * width for _ in range(height)]
    for y0, y1, half in bands:
        for y in range(y0, y1 + 1):
            centre = width / 2 + offset(y)
            for x in range(half_up(centre - half), half_up(centre + half) + 1):
                if 0 <= x < width:
                    out[y][x] = True
    return out


ALIGNED = posed_figure(lambda y: 0)
OFFSET_3PX = posed_figure(lambda y: 0 if y < 16 else 3)
SMOOTH_LEAN_6PX = posed_figure(lambda y: (y - 2) * 6 / 28)
S_CURVE_POSE = posed_figure(lambda y: 3.6 * math.sin((y - 2) / 28 * 2 * math.pi))


# ------------------------------------------------------------------------- sprite loading
def _scale_of(im: Image.Image) -> int:
    """The largest k up to 16 for which every kxk block of the image is one colour.

    The reference PNGs are exported at an integer zoom, and a measure of pixel structure
    read off an 8x export would be measuring the exporter. Detecting the factor rather
    than hard-coding it means a re-export at a different zoom cannot silently change
    every number in this file.
    """
    width, height = im.size
    px = im.load()
    best = 1
    for k in range(1, 17):
        if width % k or height % k:
            continue
        uniform = all(
            px[bx + dx, by + dy] == px[bx, by]
            for by in range(0, height, k)
            for bx in range(0, width, k)
            for dy in range(k)
            for dx in range(k)
        )
        if uniform:
            best = k
    return best


def _hex(rgba: tuple[int, int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgba)


def native_grid(path: Path) -> figure.Grid:
    """The sprite at its native resolution, as the grid of "#RRGGBBAA" get_pixels returns."""
    with Image.open(path) as opened:
        im = opened.convert("RGBA")
        k = _scale_of(im)
        px = im.load()
        return [
            [_hex(px[x * k, y * k]) for x in range(im.width // k)]
            for y in range(im.height // k)
        ]


def native_mask(path: Path) -> figure.Mask:
    return figure.mask_from_grid(native_grid(path))


@pytest.mark.pure
def test_reference_sprites_are_present():
    """The ranking gate is worthless if its inputs can go missing and the gate still passes.

    These four are tracked in git. If one disappears, the assertions that use it would
    otherwise have to skip, and a skipped gate reads the same as a passed one in a summary
    line, which is how the project's own pure-test allowlist drifted.
    """
    for path in (ORB, DUNGEON, GOLEM, SKELETON):
        assert path.is_file(), f"{path} is tracked in git but missing from this checkout"
    assert _scale_of(Image.open(ORB)) == 8
    assert _scale_of(Image.open(DUNGEON)) == 5
    assert _scale_of(Image.open(GOLEM)) == 1


# =========================================================== 1. centre-line second difference
@pytest.mark.pure
def test_centerline_is_zero_on_an_aligned_figure():
    reading = figure.centerline(ALIGNED)
    assert reading.peak == 0.0
    assert reading.breaks == []
    assert reading.rows_measured == 29


@pytest.mark.pure
def test_centerline_separates_a_misplaced_part_from_a_deliberate_pose():
    """The whole point of the measure, in one table.

    A 3px offset of the lower half reads 3.00. A smooth 6px lean, which is a larger total
    offset, reads 1.00, and so does an S-curve pose. The defect ranks above both poses
    even though it is the smaller displacement, because it is the only one that is a
    discontinuity.
    """
    assert figure.centerline(ALIGNED).peak == 0.0
    assert figure.centerline(OFFSET_3PX).peak == 3.0
    assert figure.centerline(SMOOTH_LEAN_6PX).peak == 1.0
    assert figure.centerline(S_CURVE_POSE).peak == 1.0

    defect = figure.centerline(OFFSET_3PX).peak
    assert defect > figure.centerline(SMOOTH_LEAN_6PX).peak
    assert defect > figure.centerline(S_CURVE_POSE).peak


@pytest.mark.pure
def test_naive_center_deviation_ranks_both_good_poses_worse():
    """The failure mode of four previous attempts, pinned so it cannot return.

    `max |c(y) - mean(c)|` measures the magnitude of the offset, which is exactly the
    quantity a deliberate lean also has. It puts the smooth lean and the S-curve above the
    misplaced part, which is the wrong order, and no threshold on it can be chosen to fix
    that because the bad sprite is in the middle of the good ones.
    """
    naive = {
        "aligned": figure.centerline(ALIGNED).naive_center_deviation,
        "offset3": figure.centerline(OFFSET_3PX).naive_center_deviation,
        "lean6": figure.centerline(SMOOTH_LEAN_6PX).naive_center_deviation,
        "scurve": figure.centerline(S_CURVE_POSE).naive_center_deviation,
    }
    assert naive["aligned"] == 0.0
    assert naive["lean6"] > naive["offset3"], "the inversion this measure replaced"
    assert naive["scurve"] > naive["offset3"], "the inversion this measure replaced"

    second_difference = {
        "offset3": figure.centerline(OFFSET_3PX).peak,
        "lean6": figure.centerline(SMOOTH_LEAN_6PX).peak,
        "scurve": figure.centerline(S_CURVE_POSE).peak,
    }
    assert second_difference["offset3"] > second_difference["lean6"]
    assert second_difference["offset3"] > second_difference["scurve"]


@pytest.mark.pure
@pytest.mark.parametrize("radius", [2, 3, 4, 8, 12, 16, 24, 31])
def test_centerline_is_zero_on_a_raster_disc(radius):
    """The construct gate, against the measure this one replaced.

    A jaggy-corner count on these discs returns 36 at 32x32 and 72 at 64x64: it grows with
    resolution, so no threshold separates craft from geometry. This measure returns 0.00 at
    every radius, because a disc's centre line is a straight line however it rasterizes.
    """
    assert figure.centerline(disc(radius)).peak == 0.0


@pytest.mark.pure
def test_centerline_is_near_zero_across_many_convex_shapes():
    """441 ellipses and 38 discs, none of which is a defect and none of which fires."""
    worst = 0.0
    shapes = 0
    for a in range(3, 24):
        for b in range(3, 24):
            worst = max(worst, figure.centerline(ellipse(a, b)).peak)
            shapes += 1
    for radius in range(2, 40):
        worst = max(worst, figure.centerline(disc(radius)).peak)
        shapes += 1
    assert shapes == 479
    assert worst == 0.0


@pytest.mark.pure
def test_centerline_reports_the_breaking_rows_with_their_evidence():
    """The row number is the actionable part: it says where to look."""
    reading = figure.centerline(OFFSET_3PX)
    rows = [b.y for b in reading.breaks]
    assert rows[:2] == [15, 16]
    top = reading.breaks[0]
    assert (top.center_above, top.center_at, top.center_below) == (16.0, 16.0, 19.0)
    assert top.x_extent == (11, 21)
    assert top.runs == 1


@pytest.mark.pure
def test_centerline_mass_gate_ignores_a_one_pixel_antenna():
    """A row crossing only an antenna has the antenna's midpoint, not the body's.

    Without the gate the antenna rows drag the centre line to the left edge of the canvas
    and the reading is dominated by a decoration. This is the measured reason the gate
    exists: on `workspace/throw_frame.png` an ungated reading is 10.00 against the golem's
    14.00, a separation no threshold survives, and a gated one is 0.00 against 4.50.
    """
    blank = "...................."
    body = ["....######.........."] * 8
    antenna = ["#..................."] * 4

    without = mask([blank] * 4 + body)
    with_antenna = mask(antenna + body)

    assert figure.centerline(without).peak == 0.0
    assert figure.centerline(with_antenna).peak == 0.0
    assert figure.centerline(with_antenna).rows_measured == 8
    assert figure.centerline(with_antenna).rows_gated_out == 4

    # Ungated, the same four antenna pixels are the entire reading: the centre line jumps
    # from the antenna at x=0 to the body at x=6.5 and back again.
    ungated = figure.centerline(with_antenna, mass_floor=0.0)
    assert ungated.peak == 6.5
    assert ungated.breaks[0].y == 3


@pytest.mark.pure
def test_centerline_does_not_read_a_gap_in_the_kept_rows_as_a_jump():
    """Three kept rows have to be y-adjacent, or a thin neck becomes a fake discontinuity.

    The two blocks below are 6px apart in x and separated by rows the mass gate removes.
    A measure that took the kept rows as a list would see the centres 10, 10, 16, 16 and
    report a jump; this one reports nothing, and says so by counting the gated rows.
    """
    picture = [
        "#########.......",
        "#########.......",
        "#########.......",
        "....#...........",
        "....#...........",
        ".......#########",
        ".......#########",
        ".......#########",
    ]
    reading = figure.centerline(mask(picture))
    assert reading.rows_gated_out == 2
    assert reading.peak == 0.0


@pytest.mark.pure
def test_a_spiky_silhouette_reads_as_high_as_the_defect():
    """The limitation, asserted, so the measure is not credited with more than it has.

    Isolated two-pixel spikes on alternating sides of three consecutive rows swing the
    x-extent midpoint by a pixel each way and read 4.00, which is the same order as the
    known-bad golem's 4.50 and above the 3.00 of a genuinely misplaced lower half. So this
    measure separates a misplaced part from a pose, which is what it was built for, and it
    does NOT separate a misplaced part from a silhouette full of single-row spikes.

    Every clean reference sprite in this repository reads exactly 0.00, so art drawn to
    this project's standard does not carry that noise. A sprite that does cannot be
    measured by this, and `quality.isolated_pixels` and `normalize_edge_runs` are what
    speak to the spikes themselves.
    """
    rows = ["....########...."] * 12
    spiky = mask(rows)
    for y, (start, end) in ((5, (2, 11)), (6, (4, 13)), (7, (2, 11))):
        for x in range(len(spiky[y])):
            spiky[y][x] = start <= x <= end

    reading = figure.centerline(spiky)
    assert reading.peak == 4.0
    assert reading.peak > figure.centerline(OFFSET_3PX).peak
    assert figure.centerline(mask(rows)).peak == 0.0


@pytest.mark.pure
def test_centerline_handles_an_empty_mask():
    reading = figure.centerline(mask(["....", "...."]))
    assert reading == (0.0, 0.0, [], 0, 0, 0.0)


@pytest.mark.pure
def test_centerline_rejects_a_ragged_mask_and_bad_arguments():
    with pytest.raises(Exception, match="rectangular"):
        figure.centerline([[True, True], [True]])
    with pytest.raises(Exception, match="mass_floor"):
        figure.centerline(ALIGNED, mass_floor=1.5)
    with pytest.raises(Exception, match="max_breaks"):
        figure.centerline(ALIGNED, max_breaks=0)


# ================================================================== 2. vertical-axis stacking
@pytest.mark.pure
def test_band_stacking_reports_a_rigid_stack():
    tall = posed_figure(
        lambda y: 0,
        width=48,
        height=64,
        bands=((4, 16, 5), (17, 38, 9), (39, 50, 7), (51, 61, 7)),
    )
    reading = figure.band_stacking(tall, {"head": (4, 16), "chest": (17, 38), "hip": (39, 50)})
    assert reading.spread == 0.0
    assert reading.stacked is True
    assert reading.suppressed is None
    assert [b.name for b in reading.bands] == ["head", "chest", "hip"]
    assert all(b.centroid_x == 24.0 for b in reading.bands)


@pytest.mark.pure
def test_a_symmetric_subject_stacks_legitimately_so_this_is_never_an_error():
    """The construct gate for this measure, which it fails as a defect test.

    A front-facing symmetric idle is a perfect rigid stack and is correct. The project's
    own reference for clean art is the clearest case: three equal bands of the orb centre
    on the same column to the pixel. So `stacked` is an observation about the pose and a
    caller that treats it as a failure fails its own best art.
    """
    idle = posed_figure(
        lambda y: 0,
        width=48,
        height=64,
        bands=((4, 16, 5), (17, 38, 9), (39, 50, 7), (51, 61, 7)),
    )
    assert figure.band_stacking(idle, {"h": (4, 16), "c": (17, 38), "p": (39, 50)}).stacked is True

    orb = native_mask(ORB)
    orb_reading = figure.band_stacking(orb, {"h": (3, 10), "c": (11, 19), "p": (20, 28)})
    assert orb_reading.spread == 0.0
    assert [b.centroid_x for b in orb_reading.bands] == [15.5, 15.5, 15.5]
    # ...and at 26px of drawn height the observation is suppressed anyway, because the lean
    # it looks for is 1 to 3px and cannot be told from rounding at that size.
    assert orb_reading.drawn_height == 26
    assert orb_reading.stacked is False
    assert "under 48px" in orb_reading.suppressed


@pytest.mark.pure
def test_band_stacking_sees_a_posed_lean():
    """A 2px chest-versus-hip shear, the offset measured from a working artist's figure."""
    posed = posed_figure(
        lambda y: 2 if y < 39 else 0,
        width=48,
        height=64,
        bands=((4, 16, 5), (17, 38, 9), (39, 50, 7), (51, 61, 7)),
    )
    reading = figure.band_stacking(posed, {"head": (4, 16), "chest": (17, 38), "hip": (39, 50)})
    assert reading.spread == 2.0
    assert reading.stacked is False


@pytest.mark.pure
def test_band_stacking_rejects_bands_it_cannot_measure():
    tall = posed_figure(lambda y: 0, width=48, height=64, bands=((4, 61, 9),))
    with pytest.raises(Exception, match="y0 cannot exceed y1"):
        figure.band_stacking(tall, {"head": (10, 4)})
    with pytest.raises(Exception, match="outside a mask"):
        figure.band_stacking(tall, {"head": (10, 999)})
    with pytest.raises(Exception, match="no drawn pixels"):
        figure.band_stacking(tall, {"head": (0, 2)})
    with pytest.raises(Exception, match="bands is empty"):
        figure.band_stacking(tall, {})


# ============================================= 3. connected components and interior pinholes
@pytest.mark.pure
def test_topology_counts_components_largest_first():
    picture = [
        "##...#",
        "##...#",
        "......",
        "#.....",
    ]
    found = figure.components(mask(picture))
    assert [c.pixels for c in found] == [4, 2, 1]
    assert found[0].box == (0, 0, 1, 1)
    assert found[1].box == (5, 0, 5, 1)
    assert found[2].box == (0, 3, 0, 3)


@pytest.mark.pure
def test_interior_holes_are_enclosed_and_border_air_is_not():
    # Two separate voids, reported largest first. The pillar in row 2 does not split the
    # upper void, because the air flows around nothing: 4-connected air in a ring is one
    # region, which is worth fixing in a fixture rather than discovering in production.
    two_voids = [
        "######",
        "#...##",
        "######",
        "#.####",
        "######",
    ]
    holes = figure.interior_holes(mask(two_voids))
    assert [h.pixels for h in holes] == [3, 1]
    assert holes[0].box == (1, 1, 3, 1)
    assert holes[1].box == (1, 3, 1, 3)

    # The same shape with one wall missing: the air now reaches the border, so it is not a
    # hole. This is the test that keeps the hole count topological rather than visual.
    leaking = ["######", "#.....", "######", "#.####", "######"]
    assert [h.pixels for h in figure.interior_holes(mask(leaking))] == [1]


@pytest.mark.pure
def test_four_connectivity_does_not_join_a_diagonal_touch():
    """A diagonal is not a connection, which is what makes the count match what a flood
    fill in the editor would do."""
    assert len(figure.components(mask(["#.", ".#"]))) == 2


@pytest.mark.pure
def test_topology_needs_no_threshold_and_matches_a_hand_count():
    reading = figure.topology(mask(["###", "#.#", "###"]))
    assert len(reading.components) == 1
    assert reading.components[0].pixels == 8
    assert [h.pixels for h in reading.holes] == [1]
    assert reading.holes[0].box == (1, 1, 1, 1)


# ======================================================== 4. chunky pixels, one-pixel parts
@pytest.mark.pure
def test_thin_parts_finds_a_one_pixel_arm():
    """The SOURCED measure: a limb rendered one pixel thick vanishes under one erosion."""
    picture = [
        "...####...#",
        "...####...#",
        "...####...#",
        "...####...#",
    ]
    found = figure.thin_parts(mask(picture))
    assert len(found) == 1
    assert found[0].pixels == 4
    assert found[0].box == (10, 0, 10, 3)


@pytest.mark.pure
def test_thin_parts_ignores_a_two_pixel_arm():
    """Two pixels thick is the fix the rule prescribes, so it must not be reported.

    This is the test that chose the structuring element. Eroding with the 4-neighbour
    cross deletes this bar outright, because every pixel of a two-wide bar has background
    to its left or its right, so a cross-shaped element reports the prescribed fix as the
    defect. A 2x2 square leaves it standing.
    """
    picture = [
        "...####...##",
        "...####...##",
        "...####...##",
        "...####...##",
    ]
    assert figure.thin_parts(mask(picture)) == []

    one_narrower = [row.replace("...##", "....#") for row in picture]
    assert [r.pixels for r in figure.thin_parts(mask(one_narrower))] == [4]


@pytest.mark.pure
def test_thin_parts_also_fires_on_correct_line_art():
    """The construct-gate counterexample, written down as a test.

    A one-pixel-outlined empty box and a single-pixel sparkle are both correct and both
    vanish. The measure cannot tell them from a cardboard limb; the pixel count it returns
    is what lets the caller do it, 1 pixel being a sparkle and 16 spanning 5 rows being a
    frame.
    """
    sparkle = figure.thin_parts(mask(["....", ".#..", "....", "...."]))
    assert [r.pixels for r in sparkle] == [1]

    frame = figure.thin_parts(mask(["#####", "#...#", "#...#", "#...#", "#####"]))
    assert [r.pixels for r in frame] == [16]
    assert frame[0].box == (0, 0, 4, 4)

    # The frame still reports when it encloses something solid. Its bounding box contains
    # that blob's 2x2 squares, so a measure that asked the question over the box instead of
    # over the component's own cells would miss it.
    around_a_blob = ["######", "#....#", "#.##.#", "#.##.#", "#....#", "######"]
    assert [r.pixels for r in figure.thin_parts(mask(around_a_blob))] == [20]


@pytest.mark.pure
def test_thin_parts_cannot_see_a_thin_limb_welded_to_a_solid_body():
    """The documented blind spot, asserted so the limitation is not overstated later.

    The arm here is one pixel thick and attached to a torso that is not. They are one
    component, that component survives erosion, and nothing is reported. Seeing this needs
    part decomposition, which the research ruled out as unstable at this resolution.
    """
    picture = [
        "####.......",
        "####.......",
        "#######....",
        "####.......",
        "####.......",
    ]
    assert figure.thin_parts(mask(picture)) == []
    assert len(figure.components(mask(picture))) == 1


# ================================================== 5. base of support and stability margin
def _standing(extra_rows: list[str] | None = None) -> figure.Mask:
    """A blocky figure on two feet, 16 wide, with an optional extra picture appended."""
    picture = [
        "....####....",
        "....####....",
        "...######...",
        "...######...",
        "...######...",
        "...##..##...",
        "...##..##...",
        "..###..###..",
    ]
    return mask(picture + (extra_rows or []))


@pytest.mark.pure
def test_base_of_support_needs_the_caller_to_say_it_is_standing():
    """Without the flag this measure fires on every jump frame, projectile and item icon.

    So there is no default: a caller that cannot say whether the subject stands gets None
    rather than a number it would have no basis to interpret.
    """
    standing = _standing()
    assert figure.base_of_support(standing, standing=False) is None
    assert figure.base_of_support(standing, standing=True) is not None


@pytest.mark.pure
def test_base_of_support_measures_the_margin_from_the_contact_band():
    reading = figure.base_of_support(_standing(), standing=True)
    assert reading.base == (2, 9)
    assert reading.contact_runs == 2
    assert reading.band == (7, 7)
    assert reading.margin == pytest.approx(reading.centroid_x - 2)
    assert reading.margin > 0


@pytest.mark.pure
def test_the_margin_goes_negative_when_the_mass_leaves_the_base():
    """The published condition for a figure that is falling rather than standing."""
    toppling = mask([
        "..........######",
        "..........######",
        "..........######",
        ".........#######",
        "........########",
        "##..............",
        "##..............",
    ])
    reading = figure.base_of_support(toppling, standing=True)
    assert reading.base == (0, 1)
    assert reading.margin < 0


@pytest.mark.pure
def test_dangling_limb_does_not_widen_the_base():
    """The trap this measure was rebuilt around, reproduced on the sprite it was found on.

    A one-pixel-wide limb hanging to the floor widens a naive base from [9, 22] to
    [3, 22], and because the margin is the distance from the centre of mass to the nearer
    edge, the figure then reads as MORE stable than before: the defect improves the score.
    Requiring contact runs wider than one pixel leaves the base where it was, and the
    margin then moves the way physics says it should, slightly down, because mass was
    added to the left of the centre.
    """
    orb = native_mask(ORB)
    before = figure.base_of_support(orb, standing=True)
    assert before.base == (9, 22)
    assert before.naive_base == (9, 22)
    assert before.margin == pytest.approx(6.5)

    polluted = [row[:] for row in orb]
    drawn = [y for y, row in enumerate(polluted) if any(row)]
    for y in range(drawn[0] + 13, drawn[-1] + 1):
        polluted[y][3] = True
    after = figure.base_of_support(polluted, standing=True)

    # The naive reading: base widened, margin went UP, the figure looks steadier.
    assert after.naive_base == (3, 22)
    assert after.naive_margin > before.naive_margin
    # The fix: the base is unchanged and the margin moves the correct way.
    assert after.base == (9, 22)
    assert after.margin < before.margin


@pytest.mark.pure
def test_a_minimum_row_mass_gate_does_not_fix_the_dangling_limb():
    """Recorded because it is the obvious fix and it does not work.

    The limb is one pixel wide, so it barely changes the row's mass and any gate on mass
    lets it through. The run-width requirement is what separates ground contact from a
    dangling thread, and `min_contact=1` here is the broken behaviour, kept only to show
    the difference.
    """
    orb = native_mask(ORB)
    polluted = [row[:] for row in orb]
    drawn = [y for y, row in enumerate(polluted) if any(row)]
    for y in range(drawn[0] + 13, drawn[-1] + 1):
        polluted[y][3] = True

    # The gate, applied by hand to the same band this function uses, so the negative
    # result is asserted rather than asserted about.
    reading = figure.base_of_support(polluted, standing=True)
    y0, y1 = reading.band
    widest = max(sum(row) for row in polluted)
    kept = [y for y in range(y0, y1 + 1) if sum(polluted[y]) >= 0.25 * widest]
    assert kept == list(range(y0, y1 + 1)), "the limb rows clear a quarter-mass gate"
    gated = [x for y in kept for x, drawn in enumerate(polluted[y]) if drawn]
    assert (min(gated), max(gated)) == (3, 22), "so a row-mass gate leaves the base polluted"

    unfixed = figure.base_of_support(polluted, standing=True, min_contact=1)
    assert unfixed.base == (3, 22)
    fixed = figure.base_of_support(polluted, standing=True, min_contact=2)
    assert fixed.base == (9, 22)


@pytest.mark.pure
def test_the_support_band_is_more_than_the_lowest_row():
    """One toe or one pixel of shadow is not the footprint a figure stands on.

    This figure stands on two feet at x 0..1 and 6..7, with a two-pixel contact shadow
    below them in the middle. Read off the single lowest row, its base is the shadow and
    the figure is a tightrope walker. Read off a band, its base is its feet.
    """
    on_two_feet = mask([
        "..####..",
        "..####..",
        "..####..",
        "##....##",
        "...##...",
    ])
    lowest_row_only = figure.base_of_support(on_two_feet, standing=True, band_fraction=0.06)
    assert lowest_row_only.band == (4, 4)
    assert lowest_row_only.base == (3, 4)

    banded = figure.base_of_support(on_two_feet, standing=True, band_fraction=0.5)
    assert banded.band == (2, 4)
    assert banded.base == (0, 7)
    assert banded.margin > lowest_row_only.margin


@pytest.mark.pure
def test_the_support_band_scales_with_the_figure_and_never_vanishes():
    """0.06 of drawn height is 4 rows at 64px and 2 at 32px, and 1 row at the small end
    rather than none."""
    for height, expected_rows in ((64, 4), (32, 2), (8, 1)):
        column = mask(["..####.."] * height)
        band = figure.base_of_support(column, standing=True).band
        assert band[1] - band[0] + 1 == expected_rows, height


@pytest.mark.pure
def test_base_of_support_rejects_bad_arguments():
    with pytest.raises(Exception, match="band_fraction"):
        figure.base_of_support(_standing(), standing=True, band_fraction=0.0)
    with pytest.raises(Exception, match="min_contact"):
        figure.base_of_support(_standing(), standing=True, min_contact=0)


# =============================================================== the ranking gate, asserted
@pytest.mark.pure
def test_ranking_gate_centerline_puts_the_good_sprites_ahead_of_the_bad_one():
    """An inversion here is a failed build, which is the only way this gate means anything.

    Four earlier attempts at this measure were discarded for inverting on these files. The
    assertion is strict inequality against every known-good reference, not a threshold:
    a threshold could be moved to make a bad result pass, and an ordering cannot.

    The known-bad side is read from `tests/corpus/bad_golem.png` rather than from the
    showcase golem, which is the file this test used to pin at 6.50. That pin broke the
    moment the showcase art improved, which is the wrong way round: a ranking gate has to
    be anchored to something that stays bad, and the corpus is baked for exactly that
    reason. The showcase art is checked below for being no worse than the anchor, which
    is a statement that survives the art getting better.
    """
    import corpus

    bad = next(s for s in corpus.build().known_bad if s.name == "bad_golem")
    orb = figure.centerline(native_mask(ORB)).peak
    dungeon = figure.centerline(native_mask(DUNGEON)).peak
    golem = figure.centerline(figure.mask_from_grid(bad.grid))

    assert orb == 0.0
    assert dungeon == 0.0
    assert golem.peak == 4.5
    assert golem.breaks[0].y == 50
    assert golem.peak > orb
    assert golem.peak > dungeon
    # Normalized by the silhouette's own width, not the canvas, so a sprite re-exported
    # on a bigger canvas reads the same.
    assert golem.normalized == pytest.approx(4.5 / 58)

    # And the live showcase figure, which may be improved at any time, must not drift
    # past the anchor. An equality here would forbid progress; this forbids regression.
    assert figure.centerline(native_mask(GOLEM)).peak <= golem.peak


@pytest.mark.pure
def test_ranking_gate_centerline_on_the_untracked_research_sprites():
    """The exact numbers the research quoted, where the working copy still has the files.

    `workspace/` is not tracked, so these cannot be the gate; they are a check that this
    implementation reproduces the measurements the design was argued from.
    """
    if not (WS_ORB.is_file() and WS_GOLEM.is_file()):
        pytest.skip("workspace/ is untracked; the tracked gate above covers this")
    assert figure.centerline(native_mask(WS_ORB)).peak == 0.0
    golem = figure.centerline(native_mask(WS_GOLEM))
    assert golem.peak == 4.5
    assert golem.breaks[0].y == 50
    assert golem.peak > figure.centerline(native_mask(WS_ORB)).peak


@pytest.mark.pure
def test_ranking_gate_holes_puts_the_good_sprites_ahead_of_the_bad_one():
    """The golem is the only reference sprite with a void inside it."""
    assert figure.topology(native_mask(ORB)).holes == []
    assert figure.topology(native_mask(DUNGEON)).holes == []
    golem = figure.topology(native_mask(GOLEM))
    assert len(golem.holes) >= 1
    assert max(h.pixels for h in golem.holes) >= 10
    assert len(golem.components) == 1


@pytest.mark.pure
def test_thin_parts_fires_on_no_reference_sprite():
    """Specificity, stated as what it supports: 0 fires on 4 clean inputs bounds the
    false-positive rate at about 49 percent and no lower. The sample is the claim's
    limit, not the measure's."""
    for path in (ORB, DUNGEON, SKELETON, GOLEM):
        assert figure.thin_parts(native_mask(path)) == [], path


@pytest.mark.pure
def test_base_of_support_is_positive_on_every_reference_figure():
    # The golem's base was (5, 45) when this was written, against the drawing that stood
    # there before the hand-authored rebuild. It is (16, 45) now because the sprite is a
    # different one, and that is the whole footprint of it: its lowest row spans x16 to
    # x45. The right edge is the far arm, which does reach the floor and is support.
    for path, expected_base in ((GOLEM, (16, 45)), (SKELETON, (9, 23)), (ORB, (9, 22))):
        reading = figure.base_of_support(native_mask(path), standing=True)
        assert reading.margin > 0, path
        assert reading.base == expected_base, path


# ============================================================ the discard, kept as evidence
def _keyline_boundary_share(grid: figure.Grid, keyline: str) -> float:
    """The share of a silhouette's boundary pixels that are not the declared keyline.

    Deliberately NOT in `core.figure`: it is the measure that was proposed for outline
    gaps and discarded for inverting the reference ranking. It lives here so the inversion
    is asserted by the build.
    """
    silhouette = figure.mask_from_grid(grid)
    height = len(silhouette)
    width = len(silhouette[0])
    total = off = 0
    for y in range(height):
        for x in range(width):
            if not silhouette[y][x]:
                continue
            exposed = any(
                not (0 <= x + dx < width and 0 <= y + dy < height) or not silhouette[y + dy][x + dx]
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            if exposed:
                total += 1
                off += grid[y][x] != keyline
    return off / total if total else 0.0


def _darkest(grid: figure.Grid) -> str:
    def relative_luminance(colour: str) -> float:
        channels = []
        for raw in (colour[1:3], colour[3:5], colour[5:7]):
            c = int(raw, 16) / 255
            channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    drawn = Counter(c for row in grid for c in row if int(c[7:9], 16) > 0)
    return min(drawn, key=relative_luminance)


@pytest.mark.pure
def test_keyline_boundary_share_inverts_the_ranking():
    """Why "boundary pixels that are not the keyline colour" is not in the module.

    The orb is known good and 42 percent of its boundary is not its darkest colour,
    because it is lit and its top rim is drawn in two lighter ramp steps, which is correct
    practice. The golem is known bad and outlined uniformly, so its share is zero. The
    known-good sprite ranks worse than the known-bad one, which means the measure does not
    see outline integrity at all: it sees whether the artist used a selective outline.

    This test asserts the inversion. If someone revives the measure, this is the reason
    waiting for them, with numbers.
    """
    orb_grid = native_grid(ORB)
    golem_grid = native_grid(GOLEM)
    orb_share = _keyline_boundary_share(orb_grid, _darkest(orb_grid))
    golem_share = _keyline_boundary_share(golem_grid, _darkest(golem_grid))

    assert orb_share == pytest.approx(0.421, abs=0.002)
    assert golem_share == pytest.approx(0.0, abs=0.002)
    assert orb_share > golem_share, "if this ever stops inverting, re-examine the discard"

    # And a third reason it cannot be a defect test: a full-bleed scene has no outline, so
    # every canvas-edge pixel counts against it.
    dungeon_grid = native_grid(DUNGEON)
    assert _keyline_boundary_share(dungeon_grid, _darkest(dungeon_grid)) > 0.9


# --- what the labelled corpus says about this measure ----------------------------------


def _offset_corpus():
    """The good sprites and the offset mutants, with their centre-line peaks."""
    import corpus

    built = corpus.build()
    peaks = {}
    for group in ("good", "mutants"):
        for sample in getattr(built, group):
            if group == "good" or sample.defect == "lower half offset":
                peaks[sample.name] = figure.centerline(
                    figure.mask_from_grid(sample.grid)).peak
    # A mutant's name is "<parent>:<defect>"; a parent's carries no colon.
    good = [v for name, v in peaks.items() if ":" not in name]
    bad = [v for name, v in peaks.items() if ":" in name]
    return good, bad


@pytest.mark.pure
def test_centerline_fails_the_absolute_ranking_gate_on_the_corpus() -> None:
    """Pins the DISCARD, so nobody promotes this number to a reading on its idea alone.

    The docstring once recorded PASSED here on the strength of five hand-picked files.
    A labelled set says otherwise, and the specific reason is worth keeping: small
    correct art reaches a peak that real defects in larger art do not, so the ordering
    is broken rather than the threshold being badly chosen.
    """
    from aseprite_mcp.core import validation

    good, bad = _offset_corpus()
    assert len(good) == 12 and len(bad) == 22, (len(good), len(bad))
    discordant = validation.discordant_pairs(good, bad)
    assert discordant, "the absolute gate started passing; re-read the docstring verdict"
    assert max(good) >= min(bad), (max(good), min(bad))


@pytest.mark.pure
def test_centerline_never_inverts_against_a_sprite_own_parent() -> None:
    """And pins the use that survives: the same sprite, before and after one edit."""
    import corpus

    built = corpus.build()
    parents = built.parents
    better = 0
    for sample in built.mutants:
        if sample.defect != "lower half offset":
            continue
        parent = parents.get(sample.parent)
        if parent is None:
            continue
        damaged = figure.centerline(figure.mask_from_grid(sample.grid)).peak
        original = figure.centerline(figure.mask_from_grid(parent.grid)).peak
        if damaged < original:
            better += 1
    assert better == 0, f"{better} offset mutants scored better than their own parent"
