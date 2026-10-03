"""Build the lava showcase: one drawn frame, and the flow that costs no pixels.

Every other animated piece here moves something. `bounce.py` moves a ball, `walk.py` moves
a figure, `zorder.py` moves a cel between layers, and `dungeon.py` redraws its flame four
times. This one moves nothing at all: the drawn frame is the only drawing, and the lava
flows because its *indices* rotate. That is palette cycling, and it is the oldest trick in
the medium.

Four things decide whether it works, and three of them were got wrong first.

**The art has to be authored in index space.** Rotating a run makes each lava pixel take
the next colour along it. A smooth left-to-right gradient would simply brighten and dim
together and the picture would pulse; it reads as *flow* only because the lava is painted
in a repeating sawtooth of consecutive indices laid across the direction of travel. That
sawtooth is forced, not chosen: a rotation can only translate a pattern that is monotone in
index space, so a triangle would reflect instead of travelling.

**The run has to close.** The first draft ran the colours dark to white in one direction,
which put a bright-to-black seam at every wrap and read as a moving staircase. The fix is
to loop the *colours* while the *indices* stay a sawtooth: the run heats up and cools back
down, so entry 24 is as dark as entry 1 and the wrap is invisible.

**The run has to be long, and weighted.** With eight entries the bright one recurs every
eight pixels, which is a bright *line* every eight pixels however the brightnesses are
arranged: draft two came out as a drill thread in the fall and a zebra in the pool. Lava is
mostly dark skin with a crack in it, so this run is twenty-four entries of which twelve are
crust that differ only slightly, and what travels is the crack. Three `ramp_between` calls
build it, because that tool returns both ends exactly as given, which is what lets three
legs be joined without a kink.

**The direction is a sign, and not the sign you would reason your way to.** Measured: with
the bands laid along increasing row, `step=1` puts frame two's row *y* where frame one's
row *y - 1* was, so the pattern travels **down** and the cataract falls. `step=-1` runs it
uphill, which is what draft one did.

**Two currents, one call.** The fall falls and the pool drifts sideways, and both come out
of the same `cycle_palette` call, because the rotation is defined on the palette run rather
than on a region. Nothing here says "move this down and that right"; the banding says it,
and the cycle just turns.

**The rock is the control.** A picture where everything moves proves nothing, so the stone
is the still half and is held to it: the assertions read the same rock window on every
frame and require it unchanged, which is what separates "the colours rotated" from "the
picture was redrawn". The stone is lit by the lava and nothing else, as a seven-step
falloff over the distance to the nearest lava pixel, darker in open air than on a rock face
so the silhouette reads as solid rather than as fog. No tool here lights a scene from a
region, and faking it by blending would put every pixel between palette entries, which is
why `dungeon.py` steps its falloff down a ramp instead of smoothing it too.
"""
import collections
import itertools
import pathlib

from aseprite_mcp.tools import drawing, export, frames, inspect, palette, sprite

NAME = "lava.aseprite"
W, H = 96, 64

# Index 0 is the transparent entry, so the run can never include it: `cycle_palette`
# refuses an entry that cannot draw, because rotating one through the cycle would make
# drawn pixels vanish.
TRANSPARENT = "#00000000"
# Stone, dark to light. Cool on purpose: the lava is the only warm light in the picture and
# it has to win, which it cannot do against warm grey.
STONE = ["#1a1620", "#262131", "#37303f", "#4a4254", "#5f5369"]
# Warm stone for where the glow actually lands. Separate entries rather than more of the
# stone ramp, because stone next to lava is not lighter grey, it is a different colour.
GLOW = ["#6e4433", "#9a6446"]
# The lava's own surface line, and deliberately *not* part of the run: a liquid reads as
# liquid because its edge catches light, and an edge that cycled with the body would go
# dark every few frames and the pool would stop having a top.
SURFACE = "#ffcf7a"

# The three legs of the run. The crust leg is long and nearly flat, which is the whole
# point: twelve of the twenty-four entries are dark skin, so the bright crack is one pixel
# in twenty-four rather than one in eight.
CRUST_ENDS = ("#2b0d06", "#6b2109")
HEAT_END = "#f9a52c"
CRUST_STEPS, HEAT_STEPS, COOL_STEPS = 12, 8, 7
# Joined ends are shared, and the cool leg's last entry is dropped because it is the crust
# leg's first: 12 + 7 + 5.
LAVA_LEN = CRUST_STEPS + (HEAT_STEPS - 1) + (COOL_STEPS - 2)

SPACER = "#00000000"
STONE_IX = list(range(1, 1 + len(STONE)))
# The run gets a block of its own with an unused entry either side. That is not tidiness:
# `list_palette_usage` reports the contiguous runs of indices the art draws with, so a
# palette that packs stone, lava and warm stone adjacently reports one run and the cycling
# block is not something you can ask about. The first draft did exactly that. Reserving a
# block is also how a cycling palette is really authored, for the same reason: the run is a
# unit, and a neighbour that is not part of the flow must not drift into it.
LAVA_RUN = list(range(2 + len(STONE), 2 + len(STONE) + LAVA_LEN))
GLOW_IX = [LAVA_RUN[-1] + 2, LAVA_RUN[-1] + 3]
# Adjacent to the glow entries on purpose, so the art still draws with three runs and
# the cycling block stays the separable one.
SURFACE_IX = GLOW_IX[-1] + 1
PALETTE_SIZE = SURFACE_IX + 1
assert LAVA_LEN == 24, LAVA_LEN
assert list(range(7, 31)) == LAVA_RUN, LAVA_RUN
assert PALETTE_SIZE == 35, PALETTE_SIZE

# The falloff, nearest lava first. Brightness has to fall monotonically along this list or
# the glow reads as a band rather than as a light, and the two warm entries sit at the hot
# end because that is where warm stone belongs.
FALLOFF = [GLOW_IX[1], GLOW_IX[0], STONE_IX[4], STONE_IX[3],
           STONE_IX[2], STONE_IX[1], STONE_IX[0]]
# Chebyshev distance to the nearest lava pixel, and the step of FALLOFF it earns.
BANDS = ((1, 0), (3, 1), (6, 2), (10, 3), (16, 4), (24, 5))
# Open air is darker than a rock face at the same distance, which is what makes the
# silhouette legible: a glow in a cave lights the walls, not the dark between them.
AIR_PENALTY = 2


def _profile(points, n):
    """A hand-placed outline, linearly interpolated, so the silhouette reads as drawn.

    A sine would be cheaper and would look like a sine. The control points are placed by
    eye, and the straight runs between them are what a pixel artist's line actually is.
    """
    out = []
    for i in range(n):
        for (a, va), (b, vb) in itertools.pairwise(points):
            if a <= i <= b:
                t = 0.0 if b == a else (i - a) / (b - a)
                out.append(round(va + t * (vb - va)))
                break
        else:
            out.append(points[-1][1])
    assert len(out) == n
    return out


# The chamber. Deliberately not symmetrical: the first draft gave the two walls mirrored
# profiles and a level ceiling shelf, and a cave that mirrors itself reads as a corridor in
# a tile set. The left wall is a heavy mass that comes further in; the right opens out.
CEILING = _profile([(0, 26), (9, 19), (17, 23), (26, 12), (34, 9), (43, 11),
                    (52, 6), (63, 13), (71, 10), (80, 17), (88, 14), (95, 21)], W)
LEFT = _profile([(0, 21), (12, 17), (22, 22), (33, 14), (44, 18), (54, 11), (63, 15)], H)
RIGHT = _profile([(0, 78), (11, 84), (21, 80), (32, 89), (43, 85), (55, 91), (63, 88)], H)
POOL = _profile([(0, 49), (8, 47), (15, 48), (23, 46), (31, 48), (39, 47),
                 (48, 49), (57, 46), (66, 48), (75, 47), (84, 49), (95, 47)], W)

# The cataract, off-centre so the pool has somewhere to go, spreading as it falls because a
# stream that keeps its width reads as a pipe.
FALL_L, FALL_R = 31, 42
SPREAD_EVERY = 16
EDGE_WOBBLE = (0, -1, 0, 1, 1, 0, -1, -1, 0, 1, 0, -1, 1, 0)
# A wobble on the *index field*, so the crack wanders across the flow instead of ruling a
# straight diagonal. Indexed by the axis each assertion does not read, so the field still
# steps by exactly one along the axis it does: per column the fall is untouched, per row
# the pool is.
VEIN_WOBBLE = (0, 0, 1, 1, 2, 1, 1, 0, 0, -1, -1, -2, -1, -1, 0, 1, 1, 0, -1, 0)

# Stone breaking the pool's surface, as thin spines. Two earlier drafts got this wrong in
# the same way: filled ellipses read as eyes, and a four-pixel shelf with a lit top over a
# dark body reads as a bowl. Anything in a dark scene with a bright rim and a shadowed
# interior becomes a face or a vessel before it becomes a rock, so these are two pixels
# tall and wide enough that the eye reads them as a ridge. Each is (left x, top y, w, h).
SHELVES = ((22, 53, 15, 2), (56, 56, 19, 2), (80, 51, 10, 2))
# Stalactites: (tip x, tip y, half-width at the ceiling).
TEETH = ((14, 31, 3), (25, 24, 2), (58, 27, 3), (69, 34, 2), (84, 28, 2))


def lava_run_colors():
    """The twenty-four colours of the run, built by the server's own ramp tool.

    Three legs, joined at shared ends. `ramp_between` returns both ends exactly as given,
    which is the property that lets them be joined without a kink at the seam, and it
    interpolates in Oklab so the middle of a leg is a blend rather than a hue rotation.
    """
    crust = palette.ramp_between(*CRUST_ENDS, steps=CRUST_STEPS)["colors"]
    heat = palette.ramp_between(CRUST_ENDS[1], HEAT_END, steps=HEAT_STEPS)["colors"]
    cool = palette.ramp_between(HEAT_END, CRUST_ENDS[0], steps=COOL_STEPS)["colors"]
    # Drop each leg's shared first entry, and the cool leg's last, which is the crust
    # leg's first: the run has to close without repeating a colour at the wrap.
    run = crust + heat[1:] + cool[1:-1]
    assert len(run) == LAVA_LEN, f"{len(run)} colours, expected {LAVA_LEN}"
    assert len(set(run)) == LAVA_LEN, (
        f"the run repeats a colour, so two indices are indistinguishable: {run}")
    return run


def fall_span(y):
    """Left and right edge of the cataract at this row, spreading and wobbling."""
    spread = y // SPREAD_EVERY
    left_wobble = EDGE_WOBBLE[y % len(EDGE_WOBBLE)]
    # The two edges read different entries, so they never wobble in step: edges that move
    # together are a ribbon flexing, not a stream.
    right_wobble = EDGE_WOBBLE[(y + 5) % len(EDGE_WOBBLE)]
    return FALL_L - spread + left_wobble, FALL_R + spread + right_wobble


def build():
    """The drawn frame as {(x, y): palette index}, the lava mask, and the stone mask."""
    lava = {}
    period = len(LAVA_RUN)

    # The cataract first: it cuts through the ceiling, so the lava arrives from somewhere
    # the picture does not show, which is why it reads as a source rather than as a shape.
    for y in range(H):
        left, right = fall_span(y)
        if y >= POOL[max(0, min(W - 1, (left + right) // 2))] + 2:
            break
        for x in range(max(0, left), min(W, right + 1)):
            # The sawtooth read along a diagonal. Along any single column it still steps
            # by one per row, which is what the assertion checks; the diagonal is what
            # stops the band edges being one straight line across the whole fall.
            phase = VEIN_WOBBLE[x % len(VEIN_WOBBLE)]
            lava[(x, y)] = LAVA_RUN[(y + x // 3 + phase) % period]

    # The pool, banded across the flow so it drifts sideways while the fall falls: two
    # currents out of one rotation, and still exactly one step per column.
    for x in range(W):
        for y in range(POOL[x], H):
            if x < LEFT[y] or x > RIGHT[y]:
                continue
            # Snaked rather than slanted. A `- y // 2` diagonal here closed the bands
            # into rounded shapes and the pool came out as a row of brown barrels; the
            # bands have to stay broadly vertical for the surface to read as flat, so the
            # wobble is amplified to bend them instead and the slant is gone. Per row it
            # is still a plain `x + constant`, which is what the assertion reads.
            phase = 3 * VEIN_WOBBLE[y % len(VEIN_WOBBLE)]
            lava[(x, y)] = LAVA_RUN[(x + phase) % period]

    # Shelves and stalactites are stone, so they come out of the lava mask again.
    stone_extra = set()
    for sx, sy, sw, sh in SHELVES:
        for y in range(sy, sy + sh):
            # A shelf narrows going down, so its lit top overhangs its dark side.
            inset = max(0, y - sy - 1)
            for x in range(sx + inset, sx + sw - inset):
                stone_extra.add((x, y))
    for tip_x, tip_y, half in TEETH:
        top = CEILING[max(0, min(W - 1, tip_x))]
        for y in range(top, tip_y + 1):
            if tip_y == top:
                continue
            t = (y - top) / (tip_y - top)
            w = max(0, round(half * (1.0 - t)))
            for x in range(tip_x - w, tip_x + w + 1):
                stone_extra.add((x, y))
    for position in stone_extra:
        lava.pop(position, None)

    # Distance to the nearest lava pixel, as a multi-source walk over the grid. Chebyshev,
    # because an eight-neighbour step is what makes a glow round rather than diamond.
    far = 10_000
    dist = [[far] * W for _ in range(H)]
    queue = collections.deque()
    for (x, y) in lava:
        dist[y][x] = 0
        queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        d = dist[y][x] + 1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and dist[ny][nx] > d:
                    dist[ny][nx] = d
                    queue.append((nx, ny))

    def falloff_step(d):
        for limit, step in BANDS:
            if d <= limit:
                return step
        return len(FALLOFF) - 1

    grid = {}
    solid = set()
    surface = {(x, POOL[x]) for x in range(W)
               if (x, POOL[x]) in lava and LEFT[POOL[x]] <= x <= RIGHT[POOL[x]]}
    for position in surface:
        lava.pop(position, None)
    for y in range(H):
        for x in range(W):
            if (x, y) in surface:
                grid[(x, y)] = SURFACE_IX
                continue
            if (x, y) in lava:
                grid[(x, y)] = lava[(x, y)]
                continue
            is_stone = (y < CEILING[x] or x < LEFT[y] or x > RIGHT[y]
                        or (x, y) in stone_extra)
            step = falloff_step(dist[y][x])
            if is_stone:
                solid.add((x, y))
            else:
                step = min(step + AIR_PENALTY, len(FALLOFF) - 1)
            grid[(x, y)] = FALLOFF[step]
    return grid, lava, solid


def main():
    grid, lava, solid = build()
    lava_colors = lava_run_colors()
    full = [TRANSPARENT, *STONE, SPACER, *lava_colors, SPACER, *GLOW, SURFACE]
    assert len(full) == PALETTE_SIZE, len(full)

    sprite.create_sprite(NAME, W, H, color_mode="indexed", overwrite=True)
    palette.set_palette(NAME, full)
    drawing.draw_pixels(
        NAME,
        [{"x": x, "y": y, "color": f"index:{ix}"} for (x, y), ix in sorted(grid.items())],
    )

    # The run worth cycling is a property of the art, not of the palette, so it is read
    # back off the drawing rather than assumed from the list above.
    usage = palette.list_palette_usage(NAME)
    runs = [(run["first"], run["last"]) for run in usage["runs"]]
    assert (LAVA_RUN[0], LAVA_RUN[-1]) in runs, (
        f"the lava is not a run of its own: the art draws with runs {runs}, so either a "
        "spacer got painted or the block moved")
    assert len(runs) == 3, (
        f"expected three runs (stone, lava, warm stone) and got {runs}; the spacers are "
        "what keep the cycling block separable")

    before = palette.get_palette(NAME)["colors"]
    cycled = palette.cycle_palette(NAME, LAVA_RUN, step=1)
    assert cycled["frame_count"] == len(LAVA_RUN), cycled
    # The loop has to close or the GIF stutters at the wrap, and it closes because the band
    # period and the run length are the same twenty-four.
    assert cycled["closes"] is True, f"the loop does not close: {cycled}"
    # The tool says which mechanism it used rather than implying the other, and this piece
    # is the one that would be a lie if it ever stopped saying so.
    assert cycled["method"] == "pixel_remap", cycled
    assert cycled["pixels_written"] == len(lava) * (len(LAVA_RUN) - 1), (
        f"{cycled['pixels_written']} pixels moved, expected "
        f"{len(lava)} lava pixels on each of {len(LAVA_RUN) - 1} generated frames")
    assert palette.get_palette(NAME)["colors"] == before, (
        "cycling changed the palette; it is supposed to move the pixels' indices")

    # Even durations, which `dungeon.py` argues against for a flame and which are right
    # here: a flame gutters, a flow does not, and an uneven flow reads as a stutter.
    frames.set_all_frame_durations(NAME, 70)

    verify(lava, solid)

    out = pathlib.Path(NAME).with_suffix("")
    export.export_png(NAME, f"{out}.png", frame=1, overwrite=True)
    export.export_gif(NAME, f"{out}.gif", overwrite=True)
    print(f"wrote {out}.png and {out}.gif: {len(lava)} lava pixels, "
          f"{len(LAVA_RUN)} frames, {len(full)} palette entries")


def window(frame, x, y, w, h):
    """A patch of one frame as rows of hex, kept under the 4,096-pixel read cap."""
    return inspect.get_pixels(NAME, x, y, w, h, frame=frame)["pixels"]


def longest_run(holds, limit, least):
    """Start and length of the longest unbroken stretch where `holds` holds.

    So a window that measures the flow contains only the flow. Refuses a stretch shorter
    than `least`, because a three-pixel window would pass a shifted comparison by accident.
    """
    best_start, best_len, start = 0, 0, None
    for i in range(limit + 1):
        if i < limit and holds(i):
            start = i if start is None else start
            continue
        if start is not None and i - start > best_len:
            best_start, best_len = start, i - start
        start = None
    assert best_len >= least, (
        f"no unbroken stretch of {least} to measure; longest was {best_len}")
    return best_start, best_len


def verify(lava, solid):
    """The three claims this piece makes, each read back off the saved frames."""
    # 1. The stone does not move. A window of wall well away from the lava, every frame.
    rock_box = (2, 2, 24, 16)
    first_rock = window(1, *rock_box)
    for frame in range(2, len(LAVA_RUN) + 1):
        assert window(frame, *rock_box) == first_rock, (
            f"the stone changed on frame {frame}; only the lava run may travel")
    assert any((x, y) in solid for x in range(2, 26) for y in range(2, 18)), (
        "the rock window does not contain rock, so holding it still proves nothing")

    # 2. The cataract moves down exactly one row per frame, which is the claim that the
    # banding and the sign of `step` are both right.
    #
    # The window is derived from the lava mask rather than from the geometry constants, and
    # bounded above the pool surface. Two runs were lost to that: a hand-picked rectangle
    # that overran the lava by one column included stone, which is supposed to hold still;
    # and a window that crossed into the pool measured the pool's banding, which shifts a
    # column by two rows rather than one. A window has to end where its subject ends.
    col_x = (FALL_L + FALL_R) // 2
    top, rows = longest_run(lambda y: (col_x, y) in lava and y < POOL[col_x], H, 16)
    fall_first = [row[0] for row in window(1, col_x, top, 1, rows)]
    fall_second = [row[0] for row in window(2, col_x, top, 1, rows)]
    assert fall_second[1:] == fall_first[:-1], (
        "the cataract is not flowing down one row per frame:\n"
        f"  frame 1 {fall_first}\n  frame 2 {fall_second}")

    # 3. The pool drifts one column per frame, from the same rotation and the same call.
    row_y = POOL[40] + 4
    left, cols = longest_run(lambda x: (x, row_y) in lava, W, 16)
    pool_first = window(1, left, row_y, cols, 1)[0]
    pool_second = window(2, left, row_y, cols, 1)[0]
    assert pool_second[1:] == pool_first[:-1], (
        "the pool is not drifting one column per frame:\n"
        f"  frame 1 {pool_first}\n  frame 2 {pool_second}")

    # And the two are not the same motion: a picture whose every lava pixel moved the same
    # way would not need two banding rules, so this is what makes the second one earn its
    # place.
    assert fall_first != pool_first, "the fall and the pool are banded identically"
    print("verified: stone still, cataract down one row, pool right one column")


if __name__ == "__main__":
    main()
