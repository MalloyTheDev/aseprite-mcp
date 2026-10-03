"""Build the lava showcase: one drawn frame, and the flow that costs no pixels.

Every other animated piece here moves something. `bounce.py` moves a ball, `walk.py` moves
a figure, `zorder.py` moves a cel between layers, and `dungeon.py` redraws its flame four
times. This one moves nothing at all: the drawn frame is the only drawing, and the lava
flows because its *indices* rotate. That is palette cycling, and it is the oldest trick in
the medium.

**The art has to be authored in index space.** Rotating a run makes each lava pixel take
the next colour along it, so a rotation can only *translate* a pattern that is monotone in
index space: along the direction of travel the index sequence has to be non-decreasing mod
N, has to step by exactly one at every change, and has to contain every entry of the run.
Dwelling on an index for several pixels is allowed. Skipping one is not, and that is the
whole of the law here: if an index is missing from a column, a pixel holding its successor
will next show a colour that was nowhere in that line, and the pattern changes shape
instead of moving. That reads as flicker, and no amount of nice colour will save it.

**Dwell is the drawing tool, and it has a price.** The first version read
`(y + x//3 + phase) % 24` on a 64-row canvas, which obeys the law with a constant one row
per index, and a constant is the one profile that cannot say anything. A 24-entry run on a
24-row period repeats verbatim every 24 rows, so the fall showed the same band structure
twice and read as two glowing lumps on a chain: measured, its 46 fall rows carried only 24
distinct band patterns, with rows *y* and *y + 24* identical. `FALL_DWELL` fixes that by
giving each index its own row budget, summing to the height of the fall, so exactly one
period is on show and no structure recurs anywhere.

Spending those rows *unevenly* then buys a second thing and costs a third, and the cost is
what makes this worth writing down. A rotation moves each band into the next band's slot,
so a band entering a wider slot stretches as it travels, which is free-fall acceleration
drawn in a list of twenty-four integers. But the slots are fixed by the drawing while the
colours move through them, and every colour visits every slot over a cycle, so uneven
slots mean the area covered by each colour changes every frame. Nothing in the flicker rule
forbids it and it is plainly visible: a steep profile, one row per dark entry and four per
bright one, gave a 4-to-1 band stretch and swung the cataract's mean lightness by 46.6
percent of its own average, moving the count of bright pixels by a factor of 5.3. That
does not read as acceleration. It reads as the waterfall being switched on and off every
second and a half. The whole trade-off was measured and this is the best point found on
it: two rows for every entry but the five at the lip, which get one, for a doubling of band
width between the lip and the body at a throb of 10.9 percent. That is not free. The flat
profile this replaced throbs by 5.0 percent, which is not zero either, because the fall
spreads as it descends and so the lower depths carry more pixels than the upper ones. So
the honest accounting is that drawing the stretch and killing the repeat roughly doubled
the breathing, from 5.0 to 10.9, and 46.6 was what it cost to draw the stretch properly.

**The pool gets perspective from the same table, and pays the same price.** One period per
row, widening from 30 pixels at the far upper edge to 84 at the near lower edge, with the
crust entries weighted twice the bright ones. So the near water carries a narrow crack in a
wide dark plate, the far water compresses into stripes, and because a full cycle always
takes 24 frames, the near water crosses 84 pixels while the far crosses 30: band
compression toward the horizon and differential apparent speed, both out of the dwell table
rather than out of a second mechanism. The weighting is mild for the reason above. At six
to one the pool throbbed by 34.8 percent; at two to one, with the rounding remainder spread
around the ring instead of landing on consecutive entries, it throbs by 9.3, against the
4.5 of the flat 24-pixel wallpaper it replaces.

**The run has to close, and it has to be long.** The colours loop while the indices
sawtooth: the run heats up and cools back down, so the last entry is as dark as the first
and the wrap is invisible. Twenty-four entries of which twelve are crust, so what travels
is a crack rather than a stripe. Three `ramp_between` calls build it, because that tool
returns both ends exactly as given, which is what lets three legs be joined without a
kink.

**The direction is a sign, and not the sign you would reason your way to.** Measured:
`cycle_palette(step=1)` moves each pixel one place *back* along the run, so the region
holding entry k takes on what entry k+1 was showing, and with the bands laid along
increasing row the pattern travels **down**. `step=-1` runs the cataract uphill, which is
what the first draft did.

**Rock and air need separate index space.** The stone is lit by the lava and nothing else,
as a seven-step falloff over the distance to the nearest lava pixel. The first version ran
rock and open air down *the same* seven entries and merely pushed air two steps darker,
which meant the cave silhouette was never drawn at all, only inferred from a distance
field: measured, 13.7 percent of rock/air boundary pixel pairs carried the identical index
on both sides, and the chamber read as fog. So there are now two disjoint ladders, `ROCK`
and `AIR`, and distance band k writes a rock entry or an air entry depending on which side
of the boundary the pixel is. Both are monotone in lightness, because a falloff that is
not monotone reads as a band rather than as a light, and the ladders are placed so that
the darkest rock stays clear of the lightest air by more than a tenth of Oklab L, which is
"desaturate and squint" written as a number.

**A distance field cannot describe a plane, so the planes are drawn.** The falloff knows
how far a pixel is from the lava and nothing whatever about which way its surface faces,
and facing is most of what makes stone read as stone. The forms are therefore authored as
character grids through `draw_pixel_map`, one character per pixel, with a legend that
writes palette indices exactly and never matches a colour. The counter-intuitive part is
the key: the only light in this picture is the lava, and the lava is *below*. So every
rock form here is lit on its downward-facing plane and dark on its upward-facing one, a
stalactite's brightest pixels are its tip and underside, and the darkest part of it is
where it meets the ceiling. The usual over-the-left-shoulder key light would be exactly
wrong, and drawing it that way is what made the first attempt's shelves read as sticking
plasters.

**Anything that must not move must not be in the run.** This is the rule the first version
broke everywhere, and it has no exceptions. A contact shadow painted inside the run as
"one step darker" is rotated away on the next frame, so the shadow slides along with the
flow and the rock appears to leak. Contact darkening, the crust collars where lava meets
stone, the waterline, the splash at the foot of the fall and the glow on the rock
therefore all live in static entries outside the cycling block, and the splash in
particular is drawn on the rock rather than in the stream, or it would travel downstream
with it.

**The rock is the control.** A picture where everything moves proves nothing, so the stone
is the still half and is held to it: the assertions read the same rock window on every
frame and require it unchanged, which is what separates "the colours rotated" from "the
picture was redrawn".

No tool here lights a scene from a region, and none of the shading tools may be used on
this sprite at all. They all write through nearest-colour matching, and adjacent entries
on the crust leg are 5.4 to 6.4 apart in RGB while those tools default to a tolerance of
24 or 48, so one call can rewrite run pixels as rock or rock pixels as run entries and
report success either way. Everything here is authored by index with `draw_pixels` and
`draw_pixel_map`, and verified by index.
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

# ------------------------------------------------------------------ the two ladders
# Open air, nearest lava first. Near-black on purpose and deliberately *not* a leg of the
# rock ramp: a glow in a cave lights the walls, not the dark between them, so the air gets
# a faint ember haze near the lava and swallows everything further off.
#
# These seven are hand-picked rather than ramped, and the reason is a hard floor in the
# medium: below about 0.085 of Oklab lightness the sRGB grid has almost no distinct
# colours left in it, so these are the seven darkest values that are genuinely different
# from each other, with a breath of ember on the two nearest the lava. Aiming any lower
# collapses three rungs onto #000000, and two palette entries holding the same colour are
# two indices that nothing in the picture can tell apart.
AIR = ["#070605", "#060505", "#040404", "#030303", "#020202", "#010101", "#000000"]
# Stone, nearest lava first: warm where the glow lands, cooling to violet as it falls off,
# because stone next to lava is not lighter grey, it is a different colour. The warm end
# carries real chroma rather than a peach tint, which took a round to learn: a desaturated
# lit rung sitting next to the pool's saturated oranges reads as a *different material*,
# so the drawn rocks in the lava came out looking like grey objects dropped in it.
#
# The floor is where this ladder was hardest to place, and the two pulls are opposite. A
# cave wants its far stone nearly black. The readability rule wants every rock pixel a
# tenth of Oklab L clear of whatever air it touches, and the void is already as black as
# the format goes, so the floor cannot follow it down. Measured, the binding pair is the
# keyline against the faint haze nearest the lava, which leaves the floor at L 0.254. The
# first attempt at this ladder stopped at 0.340 and the result was a pale frame around a
# black hole, with the cave reading inside out; the committed version it replaced had its
# darkest stone at 0.210, so this is about as dark as the rule permits.
ROCK = ["#fea666", "#c0733b", "#8e5226", "#5d4236", "#3f3338", "#2f2835", "#251f30"]
# One step below the rock ladder's floor, for edges that face away from the lava. Against a
# near-black void the readable keyline is the one *inside* the silhouette, darker than the
# rock body and still clear of the air; a line darker than the void is not available.
KEYLINE = "#1f1d23"

# ------------------------------------------------------------------ the cycling run
# The three legs. The crust leg is long and nearly flat, which is the whole point: twelve
# of the twenty-four entries are dark skin, so the bright crack is a few pixels in a plate
# rather than one stripe in eight.
CRUST_ENDS = ("#2b0d06", "#6b2109")
HEAT_END = "#f9a52c"
CRUST_STEPS, HEAT_STEPS, COOL_STEPS = 12, 8, 7
# Joined ends are shared, and the cool leg's last entry is dropped because it is the crust
# leg's first: 12 + 7 + 5.
LAVA_LEN = CRUST_STEPS + (HEAT_STEPS - 1) + (COOL_STEPS - 2)
# Where the run's legs sit, which is what the dwell tables are weighted against.
CRUST_POS = range(0, CRUST_STEPS)
HEAT_POS = range(CRUST_STEPS, CRUST_STEPS + HEAT_STEPS - 1)
COOL_POS = range(CRUST_STEPS + HEAT_STEPS - 1, LAVA_LEN)

# ------------------------------------------------------------------ static lava entries
# Everything that must hold still while the run turns. Dark to light.
COLLAR_DEEP = "#1e0a06"
COLLAR = "#3d1409"
MENISCUS = "#c2763c"
SPLASH_DIM = "#e6994e"
SURFACE = "#ffcf7a"
MOUTH_DIM = "#f1a554"
MOUTH = "#ffc378"
SPLASH = "#ffd695"
STATIC = [COLLAR_DEEP, COLLAR, MENISCUS, SPLASH_DIM, SURFACE, MOUTH_DIM, MOUTH, SPLASH]

SPACER = "#00000000"
# Each block gets an unused entry either side. That is not tidiness: `list_palette_usage`
# reports the contiguous runs of indices the art draws with, so a palette that packs air,
# rock, lava and crust adjacently reports one run and the cycling block is not something
# you can ask about. Reserving a block is also how a cycling palette is really authored,
# for the same reason: the run is a unit, and a neighbour that is not part of the flow must
# not drift into it.
AIR_IX = list(range(1, 1 + len(AIR)))
ROCK_IX = list(range(AIR_IX[-1] + 2, AIR_IX[-1] + 2 + len(ROCK)))
# Adjacent to the rock ladder on purpose, and darker than all of it, so the whole rock
# block reads as one monotone ladder whose last rung is the keyline.
KEYLINE_IX = ROCK_IX[-1] + 1
LAVA_RUN = list(range(KEYLINE_IX + 2, KEYLINE_IX + 2 + LAVA_LEN))
STATIC_IX = list(range(LAVA_RUN[-1] + 2, LAVA_RUN[-1] + 2 + len(STATIC)))
(COLLAR_DEEP_IX, COLLAR_IX, MENISCUS_IX, SPLASH_DIM_IX,
 SURFACE_IX, MOUTH_DIM_IX, MOUTH_IX, SPLASH_IX) = STATIC_IX
PALETTE_SIZE = STATIC_IX[-1] + 1
assert LAVA_LEN == 24, LAVA_LEN
assert list(range(1, 8)) == AIR_IX, AIR_IX
assert list(range(9, 16)) == ROCK_IX, ROCK_IX
assert KEYLINE_IX == 16, KEYLINE_IX
assert list(range(18, 42)) == LAVA_RUN, LAVA_RUN
assert list(range(43, 51)) == STATIC_IX, STATIC_IX
assert PALETTE_SIZE == 51, PALETTE_SIZE
# Four blocks of drawn entries, so `list_palette_usage` reports four runs and the cycling
# block is the separable one.
EXPECTED_RUNS = 4

# Chebyshev distance to the nearest lava pixel, and the rung of the ladder it earns.
BANDS = ((1, 0), (3, 1), (6, 2), (10, 3), (16, 4), (24, 5))

# The legend the sprite is actually written with: digits are rungs of the rock ladder, "1"
# nearest the lava, and the letters are the static entries. "." leaves a pixel alone, which
# is what lets a grid carry a form rather than a rectangle.
LEGEND_IX = {
    "A": ROCK_IX[0], "B": ROCK_IX[1], "C": ROCK_IX[2], "D": ROCK_IX[3],
    "E": ROCK_IX[4], "F": ROCK_IX[5], "G": ROCK_IX[6], "K": KEYLINE_IX,
    "O": COLLAR_DEEP_IX, "o": COLLAR_IX, "m": MENISCUS_IX, "s": SURFACE_IX,
    "p": SPLASH_IX, "P": SPLASH_DIM_IX, "M": MOUTH_IX, "d": MOUTH_DIM_IX,
}
ROCK_LETTERS = "ABCDEFG"
# And the legend the rock forms are *authored* in, which is a different thing and has to
# be. A form drawn in absolute rungs ignores where it is standing: the first version of
# these grids put the brightest rung on every stalactite tip, and since a stalactite hangs
# high up where there is almost no light, the teeth came out as neon spikes against a black
# void. So a grid says which *plane* each pixel is on and the scene says how bright that
# plane is. "#" is the plane that faces the lava and takes the full local brightness;
# everything else steps away from the light by the given number of rungs. Each plane is one
# flat tone across the form rather than a gradient, which is what makes it read as a facet
# instead of a bulge.
# A digit is how many rungs away from the light that plane faces: "0" is square to the
# lava and takes the full local brightness, "6" is turned right away from it. The range
# has to run the whole ladder and the second attempt at these grids proved it: with only
# four steps available, a shelf standing in the lava took its base rung from a pixel one
# step from the glow and every plane on it landed in the bright half, so three rocks came
# out as pale slabs with a dark line on top and read as boats floating in the pool.
RELIEF = {str(step): step for step in range(len(ROCK))}
ROCK_SYMBOLS = frozenset(RELIEF) | {"K"}


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
POOL_TOP = min(POOL)

# The cataract, off-centre so the pool has somewhere to go, spreading as it falls because a
# stream that keeps its width reads as a pipe.
FALL_L, FALL_R = 31, 42
SPREAD_EVERY = 16
EDGE_WOBBLE = (0, -1, 0, 1, 1, 0, -1, -1, 0, 1, 0, -1, 1, 0)
# A wobble on the *index field*, so the crack wanders across the flow instead of ruling a
# straight diagonal. Read along the axis each assertion does not measure, so the field
# still steps by exactly one along the axis it does: per column the fall is untouched, per
# row the pool is.
VEIN_WOBBLE = (0, 0, 1, 1, 2, 1, 1, 0, 0, -1, -1, -2, -1, -1, 0, 1, 1, 0, -1, 0)

# The mouth is static and takes whole rows. Both of those matter. Static, because the lip
# does not move even though the stream through it does; whole rows, because a static patch
# that ate *part* of a run row would delete an index from that column and the flicker rule
# would be broken by the very thing meant to improve it.
MOUTH_ROWS = 3
FALL_TOP = MOUTH_ROWS
FALL_BOTTOM = POOL_TOP
# The row budget per index, which is where the fall is actually drawn. It sums to the
# height of the fall, so the picture shows exactly one period and no band structure recurs
# anywhere in it, which is what fixes the old field's verbatim 24-row repeat.
#
# How *unevenly* those rows are spent is the part that took measuring, because an uneven
# profile buys one thing and costs another and the cost is not obvious. A rotation moves
# each band into the next band's slot, so a band entering a wider slot stretches as it
# travels: that is free-fall acceleration drawn in a list of integers, and a steep profile
# draws a lot of it. But slot widths are fixed by the drawing while the colours move
# through them, so with uneven slots the *area* of each colour changes every frame. Each
# colour visits every slot over the cycle, which means the picture's whole brightness
# breathes in and out, and nothing about the flicker rule forbids it.
#
# Measured over the cycle, as the swing in the cataract's mean Oklab lightness against its
# own average: a steep profile of one row for the dark entries and four for the bright ones
# gave a band stretch of 4.0 to 1 and a throb of 46.6 percent, with the count of bright
# pixels moving by a factor of 5.3. That does not read as acceleration, it reads as the
# waterfall switching on and off every one and a half seconds. The flat profile the first
# version had throbs not at all, and draws nothing.
#
# This is the best point measured on that trade-off: two rows for every entry except the
# five at the lip, which get one. Band widths still double between the lip and the body, so
# the sheet reads as compressed where it comes over the edge and stretched below it, and
# the throb is 10.4 percent, which is small enough to read as lava surging rather than as a
# light being switched.
FALL_DWELL = (2,) * 19 + (1,) * 5
FALL_PERIOD = FALL_BOTTOM - FALL_TOP
# Where the traversal starts, and it is not entry zero. The run closes, so it is dark at
# both ends, and reading it straight through put the cooling leg at the foot of the fall:
# the stream went dark in the last five rows before it hit the pool, which reads as the
# lava fading out just where it should be brightest. Starting on the cooling leg instead
# puts all seventeen dark entries at the lip, where a slow sheet really does skin over,
# and runs the brightening leg all the way down into the splash.
FALL_START = CRUST_STEPS + HEAT_STEPS - 1
assert sum(FALL_DWELL) == FALL_PERIOD, (sum(FALL_DWELL), FALL_PERIOD)
assert len(FALL_DWELL) == LAVA_LEN, len(FALL_DWELL)
# How far the field leans per column. Shallow, plus an amplified vein wobble, so the band
# edges are neither one straight rule across the fall nor a steep diagonal that would tilt
# the whole acceleration.
FALL_SKEW = 4
FALL_VEIN = 2

# One period per pool row, far upper edge first: the bands compress toward the horizon and
# open out toward the viewer. A full cycle is always 24 frames, so a row whose period is 84
# carries its pattern 84 pixels in the time a row of 30 carries it 30, which is the
# differential apparent speed of near and far water, for free.
POOL_PERIODS = (30, 32, 34, 37, 40, 43, 46, 50, 54, 58, 61, 64, 68, 71, 74, 77, 80, 84)
# How each period is shared out: the crust entries take twice the share of the bright ones,
# so what crosses the plate is a crack rather than a stripe. Only twice, not six times,
# which was the first attempt. The run is already half crust, so a mild weighting is enough
# to keep the bright part narrow, and a heavy one costs far more than it buys: it throbbed
# the pool's brightness by 34.8 percent over the cycle against 15.8 for this one, for the
# same reason the cataract's profile is nearly flat.
POOL_WEIGHT = (2,) * 10 + (2, 2) + (1,) * 7 + (2,) * 5
# Where each row's crack starts, placed by eye so it meanders instead of ruling a diagonal
# down the pool.
POOL_PHASE = (0, 5, 11, 14, 12, 7, 2, 4, 9, 15, 19, 16, 10, 3, 1, 6, 13, 18)
assert len(POOL_PERIODS) == len(POOL_PHASE) == H - POOL_TOP, len(POOL_PERIODS)
assert len(POOL_WEIGHT) == LAVA_LEN, len(POOL_WEIGHT)
assert min(POOL_PERIODS) >= LAVA_LEN, min(POOL_PERIODS)

# ------------------------------------------------------------------ the drawn forms
# Stone standing in the pool. Three drafts got this wrong and each was wrong differently,
# which is worth recording because the failures are all the same kind of thing: a shape in
# a dark scene becomes the nearest familiar object before it becomes a rock. Filled
# ellipses read as eyes. A flat two-pixel slab of glow colour with no side plane and no
# contact darkening reads as a sticking plaster. And a ridge built out of the middle of the
# rock ladder read as a *boat*, because those rungs are cool violet and a cool hull under a
# bright rim in warm surroundings is a boat however the pixels are arranged.
#
# So these are built out of the crust entries instead, which are the warm near-blacks: a
# broken ridge line on top, a dark warm mass under it, and one row of lit stone along the
# underside, because the light is below. The outline is irregular on purpose, since a
# four-row rectangle with tidy ends is a manufactured object. Each entry is (left x, top y,
# rows), and the collar where it meets the lava is added by rule further down.
SHELVES = (
    (21, 52, (
        "...OO..OOO......",
        ".OOOOOOOOOOOO...",
        "OOoooooooooooOO.",
        "Oo222ooo2222ooO.",
        ".Oo1.11o.111oO..",
    )),
    (55, 55, (
        "..OOO...OO...OOO....",
        ".OOOOOOOOOOOOOOOO...",
        "OOooooooooooooooOOO.",
        "Oo2222ooo22222ooO...",
        ".Oo11.111o.111oO....",
    )),
    (79, 50, (
        "..OO...OO...",
        ".OOOOOOOOO..",
        "OOoooooooOO.",
        "Oo22oo222oO.",
        ".Oo1.11oO...",
    )),
)
# Stalactites, drawn rather than tapered by formula, because a formula has no notion of a
# plane and each of these needs two: the symbols step across the form so every tooth
# carries a wide dull plane and a narrow lit one with a one-pixel step between them, and
# the lit plane runs down to the tip because the light is underneath. The root is
# keyline-dark, which is the part that surprises everybody: where a stalactite meets the
# ceiling is the *darkest* place on it.
TEETH = (
    (22, 14, (
        "KKKKK",
        "33333",
        ".3223",
        ".3213",
        ".3112",
        "..311",
        "..310",
        "..210",
        "..210",
        "...10",
        "...10",
        "...00",
    )),
    (55, 9, (
        "KKKKKKK",
        "3333333",
        ".322223",
        ".322123",
        ".321123",
        "..32112",
        "..32101",
        "..32100",
        "..3210.",
        "..3210.",
        "...210.",
        "...210.",
        "...100.",
        "...100.",
        "....00.",
        "....00.",
        "....0..",
        "....0..",
        "....0..",
    )),
    (66, 10, (
        "KKKKKK",
        "333333",
        ".32223",
        ".32123",
        ".32112",
        "..3211",
        "..3210",
        "..3210",
        "..3210",
        "..3210",
        "...210",
        "...210",
        "...210",
        "...110",
        "....10",
        "....10",
        "....10",
        "....00",
        "....0.",
        "....0.",
        "....0.",
        "....0.",
        "....0.",
        "....0.",
        "....0.",
    )),
)
# The splash, which is drawn on the rock and the air at the foot of the fall and never in
# the run. Put it in the run as "the bright entries, lower down" and it travels downstream
# with the flow, which is the single most convincing way to prove the lava is a palette
# trick. It starts below the last row of the fall for the same reason the mouth takes whole
# rows: a static patch inside the run's rows would delete an index from a column.
SPLASH_MAP = (26, POOL_TOP, (
    "....PPppppppppPP.......",
    "..PPpppppppppppppPP....",
    ".PPPppp.pppp.pppPPP....",
    "..PP.PPP.PPPP.PPP.P....",
    "...P..PP...PP..P.......",
))
# Chip lines: short irregular strata on the wall faces, placed by eye as (row, how far in
# from the face, length, symbol) and resolved against the wall profile so they stay stuck
# to the stone instead of floating off it when the outline moves.
LEFT_CHIPS = (
    (14, 1, 4, "K"), (15, 2, 3, "3"), (23, 1, 5, "K"), (24, 2, 4, "2"),
    (30, 1, 3, "K"), (31, 1, 6, "2"), (37, 2, 5, "K"), (38, 1, 4, "1"),
    (43, 1, 6, "K"), (44, 2, 3, "1"),
)
RIGHT_CHIPS = (
    (16, 1, 5, "K"), (17, 2, 3, "3"), (25, 1, 4, "K"), (26, 1, 6, "2"),
    (33, 2, 4, "K"), (34, 1, 5, "1"), (40, 1, 5, "K"), (41, 2, 4, "1"),
)
# Drawn ledges: the one feature a distance field can never supply, which is a plane. Each
# is two rows with a one-pixel step between them, a dark top face and a lit face under the
# overhang, cut into a wall. (row, how far in from the face, width, which wall).
LEDGES = (
    (20, 0, 7, "left"), (27, 0, 6, "left"), (35, 0, 8, "left"),
    (22, 0, 6, "right"), (31, 0, 7, "right"), (39, 0, 6, "right"),
)


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


def band_table(dwell, start=0):
    """Depth to run position: the dwell profile expanded one entry per pixel.

    This is the whole of the dwell mechanism. Reading the field through a table that was
    built by *repeating* each position `dwell` times makes the monotone-and-complete rule
    true by construction rather than by argument: every position appears, each appears in
    one unbroken stretch, and consecutive depths differ by one or by nothing. `start`
    rotates which entry the traversal opens on, which changes where in the picture the
    bright leg of the run lands without touching either of those properties.
    """
    table = []
    for step in range(len(dwell)):
        position = (start + step) % len(dwell)
        rows = dwell[position]
        assert rows >= 1, f"position {position} gets {rows} rows, which would skip it"
        table.extend([position] * rows)
    return tuple(table)


FALL_BAND = band_table(FALL_DWELL, FALL_START)


def share_period(total, weights):
    """Split `total` pixels over the run, by weight, with at least one pixel each.

    One pixel per entry is reserved before anything is weighted, because an entry that
    rounded down to zero would be missing from the row and that is the one defect the
    cycle cannot survive. The remainder goes to the heaviest weights, largest first, so
    the answer is a function of its arguments and not of dictionary order.
    """
    n = len(weights)
    assert total >= n, f"a period of {total} cannot hold {n} entries"
    spare = total - n
    scale = sum(weights)
    exact = [spare * w / scale for w in weights]
    extra = [int(v) for v in exact]
    left = spare - sum(extra)
    # Largest fractional share first, and ties broken by spacing rather than by index.
    # The spacing is the part that matters and it is not cosmetic: handing a remainder to
    # consecutive entries builds a clump of wide slots, a clump of wide slots is what makes
    # the colour areas lurch as the run turns through them, and the pool was measured
    # throbbing by a third of its own brightness before this was spread out. Striding by
    # seven walks all twenty-four entries without repeating, so the extra pixels land as
    # far apart as the ring allows.
    order = sorted(range(n), key=lambda k: (int(exact[k]) - exact[k], (k * 7) % n))
    for k in order[:left]:
        extra[k] += 1
    dwell = tuple(1 + e for e in extra)
    assert sum(dwell) == total, (dwell, total)
    return dwell


POOL_BAND = {POOL_TOP + i: band_table(share_period(period, POOL_WEIGHT))
             for i, period in enumerate(POOL_PERIODS)}


def fall_span(y):
    """Left and right edge of the cataract at this row, spreading and wobbling."""
    spread = y // SPREAD_EVERY
    left_wobble = EDGE_WOBBLE[y % len(EDGE_WOBBLE)]
    # The two edges read different entries, so they never wobble in step: edges that move
    # together are a ribbon flexing, not a stream.
    right_wobble = EDGE_WOBBLE[(y + 5) % len(EDGE_WOBBLE)]
    return FALL_L - spread + left_wobble, FALL_R + spread + right_wobble


def fall_phase(x):
    """How far this column's field is shifted down the dwell table."""
    return x // FALL_SKEW + FALL_VEIN * VEIN_WOBBLE[x % len(VEIN_WOBBLE)]


def placed(maps):
    """Every (x, y, symbol) a list of placed grids writes, with the ragged ones refused."""
    out = {}
    for ox, oy, rows in maps:
        width = len(rows[0])
        for dy, row in enumerate(rows):
            assert len(row) == width, (
                f"the grid at ({ox},{oy}) is ragged: row {dy} is {len(row)} characters "
                f"and row 0 is {width}. Padding it would shift every pixel after it")
            for dx, symbol in enumerate(row):
                if symbol == ".":
                    continue
                assert symbol in LEGEND_IX or symbol in ROCK_SYMBOLS, (
                    f"no legend entry for {symbol!r}")
                out[(ox + dx, oy + dy)] = symbol
    return out


def resolve_relief(rows, ox, oy, rung):
    """Turn one authored relief grid into the absolute grid the sprite is written with.

    The form takes a single base rung, read from the lighting at the middle of its own
    footprint, and every plane in it is that rung stepped away from the light by a fixed
    amount. One base per form rather than one per pixel, so a plane comes out as a flat
    tone: a plane shaded pixel by pixel off the distance field is a gradient, and a
    gradient reads as a bulge rather than as a facet, which is the fault this whole pass
    exists to fix.
    """
    inside = [rung(ox + dx, oy + dy)
              for dy, row in enumerate(rows)
              for dx, symbol in enumerate(row) if symbol in ROCK_SYMBOLS]
    assert inside, f"the grid at ({ox},{oy}) draws no stone, so it has no base rung"
    base = sorted(inside)[len(inside) // 2]
    out = []
    for row in rows:
        out.append("".join(
            ROCK_LETTERS[min(base + RELIEF[symbol], len(ROCK) - 1)]
            if symbol in RELIEF else symbol
            for symbol in row))
    return tuple(out)


def wall_maps():
    """The chip lines and ledges, resolved against the wall profiles they sit on.

    Placed by eye and glued to the stone by arithmetic, which is the division of labour
    that matters: where a chip goes is a drawing decision and cannot be derived, but *how
    far in from a wall that moves every row* is arithmetic and must not be typed out by
    hand or it comes unstuck the moment the outline is touched.
    """
    maps = []
    for row, inset, length, symbol in LEFT_CHIPS:
        start = LEFT[row] - inset - length
        maps.append((start, row, (symbol * length,)))
    for row, inset, length, symbol in RIGHT_CHIPS:
        maps.append((RIGHT[row] + 1 + inset, row, (symbol * length,)))
    for row, inset, width, side in LEDGES:
        # Two planes with a one-pixel step: a dark top face, then the lit underside of the
        # overhang it makes, offset by one so the step is visible as a step.
        if side == "left":
            top = LEFT[row] - inset - width
            maps.append((top, row, ("K" * width,)))
            maps.append((top + 1, row + 1, ("0" * (width - 1),)))
        else:
            top = RIGHT[row] + 1 + inset
            maps.append((top, row, ("K" * width,)))
            maps.append((top, row + 1, ("0" * (width - 1),)))
    return maps


def rock_forms():
    """Every hand-authored grid of stone, in relief symbols and not yet lit."""
    return [*SHELVES, *TEETH, *wall_maps()]


def lava_forms():
    """Every hand-authored grid of static lava, which needs no lighting to resolve."""
    return [SPLASH_MAP]


def build():
    """The drawn frame as {(x, y): index}, plus the cycled, rock and air masks."""
    authored = placed([*rock_forms(), *lava_forms()])
    # The rock the grids add, which has to be known before the distance field runs: the
    # falloff measures distance to lava, and a tooth that is not yet rock would be measured
    # as a hole in the ceiling.
    stone_extra = {p for p, symbol in authored.items() if symbol in ROCK_SYMBOLS}

    lava = {}
    # The cataract first: it cuts through the ceiling, so the lava arrives from somewhere
    # the picture does not show, which is why it reads as a source rather than as a shape.
    for y in range(FALL_TOP, FALL_BOTTOM):
        left, right = fall_span(y)
        for x in range(max(0, left), min(W, right + 1)):
            depth = (y - FALL_TOP + fall_phase(x)) % FALL_PERIOD
            lava[(x, y)] = LAVA_RUN[FALL_BAND[depth]]

    # The pool, banded across the flow so it drifts sideways while the fall falls: two
    # currents out of one rotation, and one period per row so it has a horizon.
    for x in range(W):
        for y in range(POOL[x], H):
            if x < LEFT[y] or x > RIGHT[y]:
                continue
            table = POOL_BAND[y]
            lava[(x, y)] = LAVA_RUN[table[(x + POOL_PHASE[y - POOL_TOP]) % len(table)]]

    # The mouth, over whole rows of the fall's span so no run row is left part-painted.
    mouth = {}
    for y in range(MOUTH_ROWS):
        left, right = fall_span(y)
        for x in range(max(0, left), min(W, right + 1)):
            mouth[(x, y)] = MOUTH_IX if y == 0 else MOUTH_DIM_IX

    for position in stone_extra:
        lava.pop(position, None)
        mouth.pop(position, None)

    # Distance to the nearest lava pixel, as a multi-source walk over the grid. Chebyshev,
    # because an eight-neighbour step is what makes a glow round rather than diamond.
    far = 10_000
    dist = [[far] * W for _ in range(H)]
    queue = collections.deque()
    for (x, y) in itertools.chain(lava, mouth):
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

    def rung(x, y):
        d = dist[y][x]
        for limit, step in BANDS:
            if d <= limit:
                return step
        return len(ROCK) - 1

    # The relief grids can be lit now that the distance field exists, and not before: a
    # form's base rung is a reading of how much light reaches where it stands.
    forms = [(ox, oy, resolve_relief(rows, ox, oy, rung)) for ox, oy, rows in rock_forms()]
    forms.extend(lava_forms())
    drawn = placed(forms)

    grid = {}
    solid, air = set(), set()
    for y in range(H):
        for x in range(W):
            if (x, y) in lava:
                grid[(x, y)] = lava[(x, y)]
                continue
            if (x, y) in mouth:
                grid[(x, y)] = mouth[(x, y)]
                continue
            step = rung(x, y)
            if (y < CEILING[x] or x < LEFT[y] or x > RIGHT[y]
                    or (x, y) in stone_extra):
                solid.add((x, y))
                grid[(x, y)] = ROCK_IX[step]
            else:
                air.add((x, y))
                grid[(x, y)] = AIR_IX[step]

    # ---- the rules that need the finished masks, and that must all be static.
    # A keyline where the rock faces away from the lava, which here means air directly
    # above it. There are only twenty-three such pixels in the bare silhouette, which is
    # the measurement that says a distance field cannot describe this cave: the planes have
    # to be drawn before there is anything for a keyline to sit on.
    for (x, y) in solid:
        if y > 0 and (x, y - 1) in air:
            grid[(x, y)] = KEYLINE_IX
    # And a brighter rung where it faces the lava, which is air or lava directly below.
    for (x, y) in sorted(solid):
        faces_light = y + 1 < H and ((x, y + 1) in air or (x, y + 1) in lava)
        if faces_light and grid[(x, y)] != KEYLINE_IX:
            step = ROCK_IX.index(grid[(x, y)]) if grid[(x, y)] in ROCK_IX else 0
            grid[(x, y)] = ROCK_IX[max(0, step - 1)]

    # The waterline: one surface pixel per column across the whole pool, and a broken
    # dimmer line under it so the edge reads as a meniscus rather than as a drawn border.
    surface = []
    for x in range(W):
        y = POOL[x]
        if (x, y) in lava and LEFT[y] <= x <= RIGHT[y]:
            surface.append((x, y))
            grid[(x, y)] = SURFACE_IX
    for i, (x, y) in enumerate(surface):
        below = (x, y + 1)
        if below in lava and i % 3 != 2:
            grid[below] = MENISCUS_IX

    # The collars. One pixel of cooled crust on the lava side of every rock boundary,
    # static, because a contact shadow inside the run is rotated away on the next frame and
    # the shadow slides off down the flow.
    for (x, y) in sorted(lava):
        if grid[(x, y)] not in LAVA_RUN:
            continue
        touching = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        if any(p in solid for p in touching):
            grid[(x, y)] = COLLAR_IX
    for (x, y) in sorted(lava):
        if grid[(x, y)] != COLLAR_IX:
            continue
        # The deepest crust goes where the collar meets stone on two sides at once, which
        # is a corner and is where a skin really does thicken.
        if sum((x + dx, y + dy) in solid
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))) >= 2:
            grid[(x, y)] = COLLAR_DEEP_IX

    # The hand-drawn grids win inside their own footprint, which is the point of drawing
    # them: they are the authored layer and the formula is the undercoat.
    for (x, y), symbol in drawn.items():
        if 0 <= x < W and 0 <= y < H:
            grid[(x, y)] = LEGEND_IX[symbol]

    assert len(grid) == W * H, len(grid)
    cycled = {p for p, ix in grid.items() if ix in LAVA_RUN}
    solid = {p for p in solid if grid[p] in ROCK_IX or grid[p] == KEYLINE_IX}
    air = {p for p in air if grid[p] in AIR_IX}
    return grid, cycled, solid, air, drawn, forms


def main():
    grid, cycled, solid, air, drawn, forms = build()
    lava_colors = lava_run_colors()
    full = [TRANSPARENT, *AIR, SPACER, *ROCK, KEYLINE, SPACER,
            *lava_colors, SPACER, *STATIC]
    assert len(full) == PALETTE_SIZE, len(full)

    sprite.create_sprite(NAME, W, H, color_mode="indexed", overwrite=True)
    palette.set_palette(NAME, full)
    # The undercoat: everything the hand-drawn grids do not claim. Written first and
    # exactly once, so no pixel is painted twice and the grids are the only thing that
    # could have authored what is inside their footprints.
    drawing.draw_pixels(
        NAME,
        [{"x": x, "y": y, "color": f"index:{ix}"}
         for (x, y), ix in sorted(grid.items()) if (x, y) not in drawn],
    )
    # And the drawn forms, each as the character grid it was authored as. `draw_pixel_map`
    # writes `index:N` exactly, with no colour matching anywhere near it, which is the only
    # safe way to author on this sprite: adjacent crust entries are six apart in RGB and
    # any tool with a tolerance would rewrite run pixels as rock or rock as run.
    legend = {symbol: f"index:{ix}" for symbol, ix in LEGEND_IX.items()}
    for ox, oy, rows in forms:
        drawing.draw_pixel_map(NAME, list(rows), legend, x=ox, y=oy)

    # The run worth cycling is a property of the art, not of the palette, so it is read
    # back off the drawing rather than assumed from the list above.
    usage = palette.list_palette_usage(NAME)
    runs = [(run["first"], run["last"]) for run in usage["runs"]]
    assert (LAVA_RUN[0], LAVA_RUN[-1]) in runs, (
        f"the lava is not a run of its own: the art draws with runs {runs}, so either a "
        "spacer got painted or the block moved")
    assert len(runs) == EXPECTED_RUNS, (
        f"expected {EXPECTED_RUNS} runs (air, rock, lava, crust) and got {runs}; the "
        "spacers are what keep the cycling block separable, and a block with an entry "
        "nobody drew with splits into two runs here rather than failing later")

    before = palette.get_palette(NAME)["colors"]
    cycle = palette.cycle_palette(NAME, LAVA_RUN, step=1)
    assert cycle["frame_count"] == len(LAVA_RUN), cycle
    # The loop has to close or the GIF stutters at the wrap, and it closes because every
    # banding rule in the picture is laid out over a whole number of runs.
    assert cycle["closes"] is True, f"the loop does not close: {cycle}"
    # The tool says which mechanism it used rather than implying the other, and this piece
    # is the one that would be a lie if it ever stopped saying so.
    assert cycle["method"] == "pixel_remap", cycle
    assert cycle["pixels_written"] == len(cycled) * (len(LAVA_RUN) - 1), (
        f"{cycle['pixels_written']} pixels moved, expected "
        f"{len(cycled)} cycled pixels on each of {len(LAVA_RUN) - 1} generated frames")
    assert palette.get_palette(NAME)["colors"] == before, (
        "cycling changed the palette; it is supposed to move the pixels' indices")

    # Even durations, which `dungeon.py` argues against for a flame and which are right
    # here: a flame gutters, a flow does not, and an uneven flow reads as a stutter.
    frames.set_all_frame_durations(NAME, 70)

    verify(grid, cycled, solid, air)

    out = pathlib.Path(NAME).with_suffix("")
    # No still frame is published. The animation is the piece, and a PNG of one frame of a
    # palette cycle is a picture of the half of it that does not work.
    export.export_gif(NAME, f"{out}.gif", overwrite=True)
    print(f"wrote {out}.gif: {len(cycled)} cycled pixels, {len(solid)} rock, "
          f"{len(air)} air, {len(LAVA_RUN)} frames, {len(full)} palette entries")


def window(frame, x, y, w, h):
    """A patch of one frame as rows of hex, kept under the 4,096-pixel read cap."""
    return inspect.get_pixels(NAME, x, y, w, h, frame=frame)["pixels"]


def frame_indices(frame, colors):
    """One whole frame as {(x, y): index}, read back in tiles and mapped by colour.

    Read back rather than trusted. Every number the verification quotes is measured off
    the saved file, because the point of this piece is a claim about what the file does.
    """
    by_color = {}
    for index, color in enumerate(colors):
        by_color.setdefault(color.upper(), index)
    out = {}
    for y0 in range(0, H, 32):
        for x0 in range(0, W, 48):
            rows = window(frame, x0, y0, min(48, W - x0), min(32, H - y0))
            for dy, row in enumerate(rows):
                for dx, hexcol in enumerate(row):
                    index = by_color.get(hexcol.upper())
                    assert index is not None, (
                        f"({x0 + dx},{y0 + dy}) on frame {frame} is {hexcol}, which is "
                        "not a palette entry, so the sprite is no longer indexed")
                    out[(x0 + dx, y0 + dy)] = index
    return out


def oklab_lightness(hexcol):
    """Oklab L of a "#RRGGBBAA" entry, 0 to 1, for the readability measurement below."""
    raw = hexcol.lstrip("#")[:6]
    rgb = tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    linear = [c / 12.92 if (c := v / 255) <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for v in rgb]
    r, g, b = linear
    long_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    medium = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    short = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    lp, mp, sp = (abs(v) ** (1 / 3) for v in (long_, medium, short))
    return 0.2104542553 * lp + 0.7936177850 * mp - 0.0040720468 * sp


MIN_BOUNDARY_LIGHTNESS = 0.10


def segments(values):
    """Split a line of (key, position) readings into its unbroken stretches."""
    out, run = [], []
    for key, position in values:
        if run and position != run[-1][1] + 1:
            out.append(run)
            run = []
        run.append((key, position))
    if run:
        out.append(run)
    return out


def check_translates(line, where, length=24):
    """A line of run positions that a rotation can only translate, not reshape.

    The one rule the whole piece stands on, and the reason the old assertion had to go.
    That one read `second[1:] == first[:-1]`, which is a test for a *uniform* one-pixel
    spacing and would reject this field for being drawn instead of computed. What actually
    has to hold is weaker and stronger at once: non-decreasing mod N, a step of exactly one
    at every change, and no entry missing. Dwelling is allowed. Skipping is not, because a
    pixel whose successor is absent from the line will next show a colour that was nowhere
    in that line, and the pattern changes shape rather than moving.
    """
    assert line, f"{where}: nothing to measure"
    for a, b in itertools.pairwise(line):
        gap = (b - a) % length
        assert gap in (0, 1), (
            f"{where}: the run position jumps from {a} to {b}, a step of {gap}. A "
            f"rotation would reshape this line rather than translate it:\n  {line}")
    return len(set(line))


def verify(model, cycled, solid, air):
    """Every claim this piece makes, read back off the saved frames."""
    colors = palette.get_palette(NAME)["colors"]
    first = frame_indices(1, colors)
    second = frame_indices(2, colors)
    last = frame_indices(len(LAVA_RUN), colors)
    assert first == model, (
        "the saved frame is not the drawing that was planned, so either the undercoat and "
        "a grid disagreed about a pixel or a write was clipped")

    # 1. The stone does not move. A window of wall well away from the lava, every frame.
    rock_box = (2, 2, 24, 16)
    first_rock = window(1, *rock_box)
    for frame in range(2, len(LAVA_RUN) + 1):
        assert window(frame, *rock_box) == first_rock, (
            f"the stone changed on frame {frame}; only the lava run may travel")
    assert any(p in solid for p in itertools.product(range(2, 26), range(2, 18))), (
        "the rock window does not contain rock, so holding it still proves nothing")

    # 2. Rock and air are drawn in disjoint index space, and far enough apart in lightness
    # to read when the picture is desaturated and squinted at. This is the measurement the
    # first version failed: 13.7 percent of these pairs were the identical index.
    shared = sorted({first[p] for p in solid} & {first[p] for p in air})
    assert not shared, (
        f"rock and air share palette entries {shared}, so the silhouette is inferred from "
        "a distance field rather than drawn and the chamber reads as fog")
    pairs = identical = 0
    worst = (1.0, None)
    for (x, y) in sorted(solid):
        for neighbour in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if neighbour not in air:
                continue
            pairs += 1
            here, there = first[(x, y)], first[neighbour]
            identical += here == there
            gap = abs(oklab_lightness(colors[here]) - oklab_lightness(colors[there]))
            worst = min(worst, (gap, ((x, y), here, neighbour, there)))
    assert pairs, "no rock/air boundary was found, so this measures nothing"
    assert identical == 0, f"{identical} of {pairs} boundary pairs share an index"
    assert worst[0] >= MIN_BOUNDARY_LIGHTNESS, (
        f"the faintest rock/air boundary differs by {worst[0]:.4f} in Oklab lightness, "
        f"under the {MIN_BOUNDARY_LIGHTNESS} a squint needs: {worst[1]}")

    # 3. The cataract is a field a rotation can translate, it shows no band structure
    # twice, and it travels downward.
    column = (FALL_L + FALL_R) // 2
    down = [LAVA_RUN.index(first[(column, y)])
            for y in range(H) if (column, y) in cycled and y < POOL[column]]
    seen = check_translates(down, f"the cataract down column {column}")
    assert seen == len(LAVA_RUN), (
        f"column {column} carries {seen} of {len(LAVA_RUN)} run entries. A missing entry "
        f"is a hole the rotation drags through the stream:\n  {down}")
    # The band structure, read over the columns the fall occupies in every one of its rows,
    # which is the only window in which two rows are comparable at all. One pattern per row
    # or some row is a copy of another and the stream repeats itself in mid-air.
    rows = sorted({y for (x, y) in cycled if FALL_TOP <= y < FALL_BOTTOM})
    core = set.intersection(*({x for (x, yy) in cycled if yy == y} for y in rows))
    patterns = {tuple(LAVA_RUN.index(first[(x, y)])
                      if (x, y) in cycled else -1 for x in sorted(core)) for y in rows}
    assert len(patterns) == len(rows), (
        f"{len(rows)} rows of cataract carry only {len(patterns)} distinct band patterns, "
        "so the fall repeats itself verbatim and reads as lumps on a chain")
    brightest = max(range(len(LAVA_RUN)),
                    key=lambda k: oklab_lightness(colors[LAVA_RUN[k]]))
    hot = LAVA_RUN[brightest]

    def centroid(frame):
        ys = [y for (x, y) in cycled if y < FALL_BOTTOM and frame[(x, y)] == hot]
        assert ys, "the brightest entry is nowhere in the fall"
        return sum(ys) / len(ys)

    assert centroid(second) > centroid(first), (
        f"the brightest band's centre of mass is at row {centroid(first):.2f} on frame 1 "
        f"and {centroid(second):.2f} on frame 2, so the cataract is not falling")

    # 4. The pool is the same rotation read across the flow, with a period per row.
    widths = {}
    for y in range(POOL_TOP, H):
        line = [(x, x) for x in range(W) if (x, y) in cycled]
        if not line:
            continue
        # Counted over adjacent steps rather than over columns, because the collars and the
        # splash cut most rows into pieces: dividing by every column in the row would
        # credit each gap with a band it does not have and report a period half again too
        # long, which is how this measurement first read 64 pixels on a row built at 34.
        steps = changes = 0
        for part in segments(line):
            positions = [LAVA_RUN.index(first[(x, y)]) for x, _ in part]
            if len(part) >= 8:
                check_translates(positions, f"the pool along row {y}, columns "
                                            f"{part[0][0]} to {part[-1][0]}")
            for a, b in itertools.pairwise(positions):
                steps += 1
                changes += a != b
        if changes and steps >= len(LAVA_RUN):
            widths[y] = steps * len(LAVA_RUN) / changes
    # The topmost and bottommost rows wide enough to measure a period on. Not the literal
    # first and last pool row: the far fringe is a dozen pixels of lava behind the
    # waterline and carries no whole band at all.
    far, near = min(widths), max(widths)
    assert widths[far] < widths[near] / 1.5, (
        "the pool's bands do not open out toward the viewer, so it has no horizon: "
        f"period {widths[far]:.1f}px at row {far} and {widths[near]:.1f}px at row {near}")

    # Which way the rotation actually moves a pixel along the run, stated once over every
    # cycled pixel rather than inferred. `step=1` moves each pixel one place *back*, so the
    # stretch holding entry k takes on what k+1 was showing; with the positions laid out
    # increasing, the pattern therefore travels toward increasing coordinate. This is the
    # sign the first draft got backwards and could not have argued its way to.
    for position in sorted(cycled):
        was = LAVA_RUN.index(first[position])
        now = LAVA_RUN.index(second[position])
        assert now == (was - 1) % len(LAVA_RUN), (
            f"{position} went from run entry {was} to {now} between frames 1 and 2, which "
            "is not a one-step rotation, so the whole translation argument is void")

    # And the pool's drift, measured on a band placed centrally enough that it cannot be
    # the period wrapping round. The mean column of the whole brightest entry is no use
    # here: the near rows carry the crack more than once, so as one crossed the right-hand
    # wall the mean jumped backwards and reported the pool running uphill.
    row = max(widths)
    part = max(segments([(x, x) for x in range(W) if (x, row) in cycled]), key=len)
    columns = [x for x, _ in part]
    inside = [LAVA_RUN.index(first[(x, row)]) for x in columns]
    middle = inside[len(inside) // 2]
    assert inside.count(middle) and middle + 1 in inside, (
        f"row {row} has no band with a right-hand neighbour to move into: {inside}")

    def mean_column(frame):
        xs = [x for x in columns if LAVA_RUN.index(frame[(x, row)]) == middle]
        assert xs, f"run entry {middle} left row {row} entirely"
        return sum(xs) / len(xs)

    assert mean_column(second) > mean_column(first), (
        f"on row {row}, run entry {middle} is centred on column "
        f"{mean_column(first):.2f} on frame 1 and {mean_column(second):.2f} on frame 2, "
        "so the pool is not drifting")

    # 5. The waterline is a line: one pixel per column, never stepping more than a row,
    # reaching stone at both ends rather than stopping in mid-air, and interrupted only
    # where the cataract lands. That last exception is the art and not a let-off: a pool
    # with a calm drawn edge ruled straight through the place a waterfall hits it is a
    # worse drawing than one that breaks there, so what has to be unbroken is the *top
    # edge*, of which the waterline is the calm part and the splash is the rest.
    heights = {x: y for (x, y) in model if model[(x, y)] == SURFACE_IX}
    line = sorted(heights)
    broken = {x for (x, y) in model if model[(x, y)] in (SPLASH_IX, SPLASH_DIM_IX)}
    missing = set(range(line[0], line[-1] + 1)) - set(line)
    assert missing <= broken, (
        f"the waterline has holes in it that the splash does not account for: "
        f"{sorted(missing - broken)}")
    edge = sorted(set(line) | broken)
    assert edge == list(range(edge[0], edge[-1] + 1)), (
        f"the pool's top edge is not continuous: "
        f"{sorted(set(range(edge[0], edge[-1] + 1)) - set(edge))}")
    for part in segments([(x, x) for x in line]):
        columns = [x for x, _ in part]
        steps = max((abs(heights[b] - heights[a])
                     for a, b in itertools.pairwise(columns)), default=0)
        assert steps <= 1, (
            f"the waterline jumps {steps} rows between two columns near {columns[0]}")
    for end, step in ((edge[0], -1), (edge[-1], 1)):
        touch = [y for (x, y) in model if x == end and model[(x, y)] in
                 (SURFACE_IX, SPLASH_IX, SPLASH_DIM_IX)]
        assert any((end + step, y) in solid for y in touch), (
            f"the pool's top edge ends at column {end} against "
            f"{'open air' if 0 <= end + step < W else 'the canvas edge'} rather than on "
            "stone, so the pool floats")
    assert sum(1 for p in model if model[p] == MENISCUS_IX) >= len(line) // 2, (
        "too little meniscus was drawn to read as one")

    # 6. The palette survives every frame. A bug that wiped every entry above index 31
    # after the first frame used to take the glow and the waterline with it, and this is
    # the piece that would show it: everything static in this picture lives up there.
    used = [sorted(entry["index"] for entry in
                   palette.list_palette_usage(NAME, frame=frame)["used"])
            for frame in (1, len(LAVA_RUN))]
    assert used[0] == used[1], (
        f"frame 1 draws with {used[0]} and frame {len(LAVA_RUN)} with {used[1]}; an entry "
        "that survives the first frame and not the last is a destroyed palette")
    assert max(used[0]) > 31, (
        "nothing above index 31 is drawn, so this check would not notice the bug it is for")
    assert first != last, "every frame is identical, so nothing cycled at all"

    print(f"verified: {pairs} rock/air boundary pairs, 0 sharing an index, faintest "
          f"{worst[0]:.3f} Oklab L apart; {len(patterns)} band patterns over "
          f"{len(rows)} fall rows; pool period {widths[far]:.0f}px far to "
          f"{widths[near]:.0f}px near; waterline unbroken across {len(line)} columns")


if __name__ == "__main__":
    main()
