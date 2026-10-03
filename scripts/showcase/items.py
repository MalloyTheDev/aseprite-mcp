"""Build the equipment-sheet showcase: five RPG items, finished with the shading tools.

Five items rather than the four this sheet used to carry, and deliberately five different
*kinds* of thing: a long thin blade, a big flat painted face, a round shell, a part that is
nothing but thin parts, and a matte non-metal. A showcase of one material shaded one way
proves much less than it looks like it does.

**The silhouettes are written out row by row, not derived.** The draft that used ellipses
and implicit curves produced a lumpy heart and an emboss that read as noise. At this size
every row matters, and a curve half a pixel out on four rows has already ruined the shape.
Only the mechanical insets are computed: `erode` takes the rim off the shield's own
outline, which is the one operation no hand-typed second outline stays concentric with.

Each part is drawn flat, given form by `shade_region_by_light`, and detailed only then,
because the shading tool works from a base colour: detail painted first gets shaded as if
it were form. Several parts refuse a form and are lit by hand, and every one of those
refusals is correct: a 2px shield rim, a 3px key shank and a 6px ward have no interior for
a distance field to describe, and inventing one would be drawing rather than shading.
"""
import colorsys
import math

from aseprite_mcp.tools import (
    drawing,
    effects,
    export,
    inspect,
    layers,
    palette,
    selection,
    shading,
    sprite,
)

CELL, SIZE, COUNT = 40, 40, 5
NAME = "items.aseprite"
OUTLINE = "#191326"
LIGHT = 128.0
# One chroma rule for the whole sheet: no ramp runs below the reference band, and a ramp
# whose base is already more saturated than that keeps its own saturation.
#
# `generate_ramp` rotates hue but never creates saturation, which it inherits from the
# base colour. So a base picked for its *value*, which is how a base gets picked ("steel
# is grey", so `#7d8aa8`), builds a ramp that rotates a hue nothing can see. Measured on
# the draft: STEEL ran 0.353 HSV saturation down to 0.008, so its top three steps were
# literally neutral grey and white, and it carried three of the five items including all
# of the helm, while WOOD still held 0.521 at its top step. Half the sheet read as
# hue-shifted wood and half as grey plastic, and that split was an accident of which base
# colours happened to be saturated, not a decision anybody made.
#
# `chroma` is the fix: it sets the saturation the ramp holds, in place of the base's own.
# Reference work in this style runs its apparent greys at 0.17 to 0.30, so the floor sits
# at the middle of that band. A floor rather than a flat value on purpose: gold and paint
# are *meant* to out-saturate steel, and pinning every ramp to one number would have cost
# the crest and the shield face the only chroma on the sheet to fix a problem neither had.
CHROMA_FLOOR = 0.26


def saturation(colour):
    """HLS saturation, which is the measure `chroma` and `sat_floor` both speak in."""
    r, g, b = (int(colour[k:k + 2], 16) / 255.0 for k in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[2]


def ramp(base, *, hue=-30.0, sat=-14.0, light=0.82, steps=9):
    """A nine-step ramp, with the two checks that matter: no step may clip or go grey.

    `generate_ramp` walks lightness out from the base in both directions and clamps at the
    ends, so a base already near white spends its top three steps on white. That is not a
    theoretical loss. A duplicated top step is what made `specular_highlight` refuse this
    sheet outright on the first run: a glint has to be brighter than the lit side, and a
    ramp whose lit side is already white leaves nowhere brighter to go. Every base below is
    mid-value for that reason, not for its own sake.

    The second check is the chroma floor. The ends clamp to black and white by design and
    carry no saturation at all once they do, so it is asserted over the seven interior
    steps, which are the ones any of this art is actually drawn with.
    """
    colors = palette.generate_ramp(base, steps=steps, hue_shift=hue,
                                   saturation_shift=sat, light_range=light,
                                   chroma=max(CHROMA_FLOOR, saturation(base)))["colors"]
    assert len(set(colors)) == steps, f"{base} at light_range={light} clips: {colors}"
    greyest = min(saturation(c) for c in colors[1:steps - 1])
    assert greyest >= 0.17, f"{base} bottoms out at {greyest:.3f} saturation, a grey"
    return colors


# `light=0.70`, not the 0.82 the rest of the sheet takes, and the glints are the reason.
# At 0.82 the top step is `#fafbfc`, relative luminance 251, and both the blade's lit edge
# and the helm's lit side were painted with it; `specular_highlight` puts a glint where the
# surface best faces the light, which is exactly there, so this sheet's steel "glints" were
# `#ffffff` against 251. A 4-in-255 difference is not a glint, it is a rounding error.
# Pulling the top step down to `#e7ecf0`, luminance 235, is worth doing here and nowhere
# else because it is free: the helm sweep below measured light_range to have *no* effect on
# how the form pass breaks into blocks, only on which colours those blocks get, so this
# buys the helm's glint 20 points of contrast and the blade's 44 and costs the ramp
# nothing but 12% of a span the helm was not using.
STEEL = ramp("#7d8aa8", hue=-22.0, sat=-26.0, light=0.70)
BRONZE = ramp("#8a6a3a", hue=-20.0, sat=-18.0, light=0.78)
BRASS = ramp("#e0a33c", hue=-22.0)
GOLD = ramp("#f2b632", hue=-24.0)
WOOD = ramp("#7a4e2c", hue=-18.0, light=0.62)
PAINT = ramp("#2f6fb5", hue=-26.0, light=0.84)
# Wide enough that `PARCH[0]` is dark enough to pass for ink. The draft wrote on its
# parchment in `PARCH[1]`, which against `PARCH[5]` is a yellow-brown on a yellow-white and
# at this size reads as mould rather than as writing.
PARCH = ramp("#cbb382", hue=-16.0, light=0.90)
# A deep red, not the pink this was. There is one accent colour on this sheet and it is
# used twice, on the scroll's ribbon and on the cord binding the sword's grip, because a
# hue that turns up once reads as an accident. The mint green of an earlier pommel gem was
# exactly that accident and the gem is gone.
RIBBON = ramp("#8f3b32", hue=-26.0, light=0.80)


def rows(ox, spans):
    """Expand {row: [(left, right), ...]} into points, the runs measured from the centre."""
    return {(ox + 20 + dx, y)
            for y, runs in spans.items()
            for left, right in runs
            for dx in range(left, right + 1)}


def erode(points, steps=1):
    """Shrink a shape inward by whole pixels, keeping only what stays fully surrounded."""
    out = set(points)
    for _ in range(steps):
        out = {(x, y) for x, y in out
               if all((x + dx, y + dy) in out
                      for dx in (-1, 0, 1) for dy in (-1, 0, 1))}
    return out


def pts(points):
    return [{"x": x, "y": y} for x, y in sorted(points)]


def items_pixel(point):
    x, y = point
    return inspect.get_pixels(NAME, x, y, 1, 1)["pixels"][0][0][:7].lower()


def band(points, keep):
    return {(x, y) for x, y in points if y in keep}


# ======================================================================= 1. longsword
# A long blade with a six-row taper, ending on the guard's quillon row so it meets the
# guard between the two tips rather than balancing on top of the bar.
#
# **The blade must stop above the bar, and the reason is the painting order, not the
# drawing.** `BLADE_SECTION` in step 3 repaints every blade pixel at or below
# `BLADE_FULL_FROM`, long after the guard went down over it, so a blade row that reaches
# into the bar is a blade row that comes back out on top of it: run one row too far, and
# seven columns of steel punch straight through the middle of the crossguard.
# Narrower and much longer than the draft, which gave 22 rows of 9px blade to 18 rows of
# hilt. 54% blade at a 1 to 2.3 aspect is a spearhead, and at inventory size it read as a
# crystal shard on a stick. 27 rows to 11 is 71%, which is roughly what a longsword is, and
# the hilt is as compact as three readable parts can be in a 40px cell.
# Three rows lower at the top and three shorter at the bottom than the draft, which ran
# rows 0 to 39 of a 40-row cell against 31, 33, 34 and 32 for the other four items: the
# hero item was 6 to 9 rows taller than its neighbours and had no bleed margin at all, on
# either edge. Nothing caught it, because the sheet asserted that the five items agree on
# a centre line and never once asked how tall they are. They did agree on a centre, which
# is how a sword touching both edges of its cell passed. `EXTENTS` at the bottom is that
# missing assertion.
BLADE = {
    4: [(0, 0)], 5: [(-1, 1)], 6: [(-1, 1)], 7: [(-2, 2)], 8: [(-2, 2)], 9: [(-2, 2)],
    **{y: [(-3, 3)] for y in range(10, 27)},
}
# The blade's cross section, by column, because a blade is a prism and not a dome.
# `shade_region_by_light` describes a rounded form, and on the draft's blade it produced a
# soft left-to-right gradient with no edge anywhere in it. These are ramp steps for dx -3
# to 3: a bright lit edge, a lit bevel, the fuller's two walls either side of its floor, a
# shadowed bevel and a rim light catching the far edge.
#
# **Every reversal in here has to name the geometry that causes it**, and the draft's did
# not. Measured left to right, the draft read 251, 196, 224, 108, 137, 83, 167 in relative
# luminance: three reversals in seven columns, and the first of them sat on the lit side,
# between the lit edge and the groove, where the blade is one flat bevel with nothing to
# turn. Repeated identically down twenty full-width rows, which is what made it read as a
# pattern rather than as a surface. This section keeps two reversals and both are real: the
# fuller is *concave*, so its far wall tips back toward the light and comes up a step from
# the floor, and the far edge takes a rim light. The lit side now falls monotonically,
# 211 to 187 to 134 to 87, because a flat plane turning away from a light does that.
#
# **It also stops one step short of the ramp.** The lit edge was `STEEL[8]`, `#fafbfc` at
# luminance 251, and the glint `specular_highlight` lands on this blade is `#ffffff` at
# 255: a 4-in-255 difference, which is not a glint, it is a rounding error. The top step
# is reserved for the glint to be brighter than, here and on the helm, which is the
# arrangement `specular_highlight` documents and the draft had quietly spent.
BLADE_SECTION = {-3: 7, -2: 6, -1: 4, 0: 2, 1: 3, 2: 1, 3: 4}
BLADE_FULL_FROM = 10
# The taper is too narrow to carry seven columns, so it takes a two-tone split instead.
# A step below the full section's lit edge, for the same reason: the glint lands in the
# taper, and the tip of a blade is not the brightest thing on it once a glint is there.
TAPER_LIT, TAPER_DARK = 6, 3
# Quillons: two pixels standing clear of the bar at each end, which is what turns a
# crossbar into a guard.
# A two-row bar rather than the draft's three, which is what buys the compressed hilt a
# grip that still reads. The quillon rows above and below it carry the guard's height.
GUARD = {
    26: [(-11, -10), (10, 11)],
    27: [(-11, 11)], 28: [(-11, 11)],
    29: [(-11, -10), (10, 11)],
}
# The bar's own bottom row, darkened by hand. A guard is a slab seen edge on, and the
# dome the shading pass describes has no reason to put a hard edge where the slab ends.
#
# **Broken around the grip's five columns, which is also a bug fix.** Ruled straight
# across, this row put `BRASS[1]` directly above the grip, and the band-boundary cleanup
# then found the grip's top right pixel surrounded on three sides by darker neighbours and
# resolved it to the brass. The result was one orphan `#70590f` pixel at cell-local
# (22,31), a brass drip running onto the leather, which `remove_stray_pixels` could not
# remove because brass is on its protect list and the material assertion could not see
# because brass is legal in the sword's cell. Breaking the row is the honest drawing
# anyway: the grip's tang passes up through the guard, so the guard's bottom edge is
# interrupted where it crosses rather than ruled behind it.
GUARD_EDGE = {28: [(-9, -3), (3, 9)]}
# Starting on the quillon row, **not** on a bar row. Started a row higher, the grip's five
# columns overpaint the middle of the bar's bottom row, and a crossguard with a brown block
# punched through the centre of it reads as damage rather than as a grip: the bar's whole
# job is to be one unbroken horizontal, and the quillon row below it is where the grip is
# meant to pass through.
GRIP = {y: [(-2, 2)] for y in range(29, 33)}
# The cord binding the grip, in the sheet's one accent colour. One band, not the two the
# draft had: the hilt is three rows more compact now, and two dark bands across a four-row
# grip left one row of visible leather between the guard and the pommel, so two brass
# masses met across a dark smear and the grip stopped reading as a part at all. One band
# leaves three, which is what the draft's taller grip showed.
WRAP = {31: [(-2, 2)]}
POMMEL = {33: [(-3, 3)], 34: [(-4, 4)], 35: [(-3, 3)]}

# ======================================================================= 2. kite shield
# A heater: a wide flat top, sides that fall straight and then draw in two pixels at a
# time, and a point. The taper accelerates down the shape, which is the whole silhouette.
SHIELD = {
    5: [(-10, 10)], 6: [(-12, 12)],
    **{y: [(-13, 13)] for y in range(7, 13)},
    13: [(-12, 12)], 14: [(-12, 12)], 15: [(-12, 12)],
    16: [(-11, 11)], 17: [(-11, 11)], 18: [(-10, 10)], 19: [(-10, 10)],
    20: [(-9, 9)], 21: [(-9, 9)], 22: [(-8, 8)], 23: [(-7, 7)], 24: [(-7, 7)],
    25: [(-6, 6)], 26: [(-5, 5)], 27: [(-5, 5)], 28: [(-4, 4)], 29: [(-3, 3)],
    30: [(-3, 3)], 31: [(-2, 2)], 32: [(-1, 1)], 33: [(0, 0)],
}
CROSS_V = {y: [(-1, 1)] for y in range(5, 34)}
CROSS_H = {13: [(-13, 13)], 14: [(-13, 13)], 15: [(-13, 13)]}
RIVETS = {6: [(0, 0)], 13: [(-11, -11), (11, 11)], 31: [(0, 0)]}

# ======================================================================= 3. great helm
# Two rows lower than the draft, which centred the helm on row 17 while everything else on
# the sheet centred on 19. Five items at five different heights read as five sprites from
# five games.
HELM = {
    8: [(-6, 6)], 9: [(-8, 8)], 10: [(-9, 9)], 11: [(-10, 10)], 12: [(-10, 10)],
    **{y: [(-11, 11)] for y in range(13, 25)},
    25: [(-10, 10)], 26: [(-10, 10)], 27: [(-9, 9)], 28: [(-9, 9)],
    29: [(-10, 10)], 30: [(-11, 11)], 31: [(-11, 11)], 32: [(-10, 10)],
    33: [(-8, 8)], 34: [(-5, 5)],
}
VISOR = {17: [(-8, 8)], 18: [(-8, 8)]}
# Two breath slits, not holes. Five single pixels ruled straight across read as a dotted
# line; the same five stepped to follow the dome read as scattered dirt, which was worse. A
# slit is what the visor already is, and a second and third of them below it is what makes
# a dome of grey steel unmistakably a helm.
BREATHS = {23: [(-6, 2)], 26: [(-4, 3)]}
# A comb, and one that comes to a point. Three pixels wide read as a stick poking out of
# the dome; five pixels wide with a flat bottom edge read as a gold brick resting on it.
# Tapering at both ends is what makes it a crest sitting *in* the helm.
CREST = {
    4: [(-1, 1)], 5: [(-1, 1)],
    **{y: [(-2, 2)] for y in range(6, 12)},
    12: [(-1, 1)], 13: [(-1, 1)], 14: [(0, 0)],
}

# ======================================================================= 4. iron key
# A solid lozenge bow rather than a ring. A ring's band is three pixels wide at this size,
# which is one more refusal and one more hand-lit part than the sheet needs to make its
# point, and the hole is punched after the shading pass instead.
BOW = {
    4: [(-2, 2)], 5: [(-4, 4)], 6: [(-5, 5)], 7: [(-6, 6)],
    8: [(-7, 7)], 9: [(-7, 7)], 10: [(-7, 7)], 11: [(-7, 7)],
    12: [(-6, 6)], 13: [(-5, 5)], 14: [(-4, 4)], 15: [(-2, 2)],
}
BOW_HOLE = {8: [(-1, 1)], 9: [(-2, 2)], 10: [(-1, 1)]}
# The shank is three pixels across, so it is lit as what it is: a rod, bright on the side
# the key comes from and dark opposite. A distance field cannot say that about three
# pixels, and `shade_region_by_light` is right to refuse rather than guess.
SHANK_LIT = {y: [(-1, -1)] for y in range(16, 36)}
SHANK_MID = {y: [(0, 0)] for y in range(16, 36)}
SHANK_DARK = {y: [(1, 1)] for y in range(16, 36)}
# Two wards, and they are declared as two shapes rather than one six-row dict, because
# lighting them together is what went wrong. `hand_lit` takes the minimum and maximum y
# over whatever it is handed, so one call covering both slabs lit the top of the upper ward
# and darkened the bottom of the lower one and nothing else: rows 29, 30, 32 and 33, which
# is 20 of the 30 ward pixels, stayed at the raw `#8a6a3a` flat fill. The lower ward had no
# lit top edge and the upper no shadowed bottom, so the two teeth never separated in value
# and the key read as one forked blob. `edge_lit`'s own docstring below calls this exact
# failure damning when it happened to the shield's rim; the lesson was learned once, on
# another part, and not carried across.
WARD_UPPER = {28: [(2, 7)], 29: [(2, 7)], 30: [(2, 7)]}
WARD_LOWER = {32: [(2, 5)], 33: [(2, 5)], 34: [(2, 5)]}

# ======================================================================= 5. spell scroll
# One roll at the top with the sheet hanging open below it, curling back on itself at the
# bottom. The draft was a roll at each end of a rectangle, which gave the only item on this
# sheet with no silhouette: every other one is recognisable from its outline alone and that
# one was a window frame.
TOP_ROLL = {4: [(-11, 11)], **{y: [(-13, 13)] for y in range(5, 8)}, 8: [(-11, 11)]}
# The roll is a cylinder, so it is banded by row rather than shaded as a form: a row number
# to a `WOOD` step, brightest a third of the way down, which is where the light hits a
# cylinder and never at its top edge.
ROLL_BANDS = {4: 3, 5: 6, 6: 7, 7: 4, 8: 2}
# The two end caps, and they are *not* the same colour, which the draft made them: one
# `WOOD[2]` over both ends is mirror-symmetric lighting on a cylinder, and a cylinder lit
# from 128 degrees has a near end turned toward the light and a far end turned away. Two
# steps apart either side of the step the draft used, so the roll keeps its value and
# gains an axis.
ROLL_CAP_LIT = {y: [(-13, -12)] for y in range(5, 8)}
ROLL_CAP_DARK = {y: [(12, 13)] for y in range(5, 8)}
# Pinched where the ribbon binds it and flaring below, which is what a tied scroll does and
# what finally gives this item an outline. Two drafts of it were a rectangle in a square
# cell: every other item on this sheet is recognisable from its silhouette alone, and the
# scroll was a window frame.
PARCHMENT = {
    9: [(-10, 10)], 10: [(-11, 11)], 11: [(-11, 11)], 12: [(-11, 11)],
    13: [(-10, 10)], 14: [(-10, 10)],
    15: [(-9, 9)], 16: [(-9, 9)], 17: [(-9, 9)], 18: [(-9, 9)],
    19: [(-10, 10)], 20: [(-10, 10)], 21: [(-11, 11)], 22: [(-11, 11)],
    **{y: [(-12, 12)] for y in range(23, 28)},
    28: [(-11, 11)], 29: [(-10, 10)], 30: [(-8, 8)],
}
# The sheet rolling back on itself, wider than the sheet above it so the curl reads as a
# lip rather than as a fold line.
CURL = {31: [(-9, 9)], 32: [(-10, 10)], 33: [(-8, 8)]}
# Writing, as the dashes it would be at this size. Four pixels of text is text; a glyph
# four pixels wide is a smudge pretending to be one. In `PARCH[0]`, which is five steps
# from the paper, rather than the one step the draft used.
WRITING = {11: [(-8, 4)], 13: [(-8, 6)],
           21: [(-8, 2)], 23: [(-9, 5)], 25: [(-9, 1)], 27: [(-9, 6)]}
# Four flat bands and a hanging end. The draft gave the ribbon to
# `shade_region_by_light`, and a 19 by 5 band cannot carry a diagonal terminator: it came
# out as a smear with a torn top and bottom edge.
# At the pinch, and a pixel wider than the sheet there, so it reads as wrapped around it
# rather than painted on it.
RIBBON_BAND = {y: [(-10, 10)] for y in range(15, 19)}
RIBBON_STEPS = {15: 6, 16: 4, 17: 4, 18: 2}
# The tail hangs *outside* the sheet's edge, which is the other half of giving this item a
# silhouette: an outline that is only ever the paper cannot be read as a tied scroll.
RIBBON_TAIL = {19: [(11, 13)], 20: [(11, 13)], 21: [(12, 14)], 22: [(12, 14)],
               23: [(13, 15)], 24: [(13, 15)], 25: [(13, 15)]}


# --------------------------------------------------------------------------- the finish
def flat(points, colour):
    if points:
        drawing.draw_pixels(NAME, pts(points), colour)


def form(base, band_ramp, *, rim=0.20, bulge=1.0, light_z=0.62, ambient=0.30):
    """One shading pass per part, scoped by the exact colour that part was filled with.

    `tolerance=1.0`, not the default 24, and that is the whole difference between this
    sheet and a broken one. Tolerance is a weighted RGB distance, and gold and brass are
    the same colour to within 18 of it: at the default, the pass that shaded the sword's
    guard also matched a gold face two cells away and reshaded it in brass. Nothing looked
    wrong. The flat fills are exact ramp entries, so an exact match is all this ever needs.

    One call can still cover several parts, and does: a mask with two disconnected parts
    gets a distance field that describes each on its own, so the sword's grip and the
    scroll's rolls come out as two rods rather than as one smear.

    `ambient` is exposed because the helm needed it, and because the obvious fix for the
    helm was measured and rejected. Its shadow side was one 4-connected region of 202
    pixels with no second value anywhere inside it, and `shade_region_by_light` has a
    `fill_angle` argument documented for exactly that complaint. Swept over 36 combinations
    of ramp length, fill, rim and ambient against this silhouette alone, counting values
    and the largest single-colour block each time, a fill light did not fix it. The three
    that matter, on a 563-pixel helm:

      rim 0.16, ambient 0.30, no fill   6 values, largest block 209 px, shadow 210 px / 1 value
      rim 0.16, ambient 0.30, fill 0.40 5 values, largest block 173 px, shadow   0 px / 0 values
      rim 0.32, ambient 0.22, no fill   7 values, largest block  89 px, shadow 188 px / 2 values

    The fill shrank the flat block and cost a value doing it, and it did something worse
    than that: at 0.40 there was no shadow side left at all, because a fill lifts the whole
    unlit side by roughly a constant and every pixel of this one came up past the colour it
    was filled with. A shadow that has been lifted out of existence is not a described
    shadow. Raising the rim and lowering the ambient floor won on all three counts at once,
    which is the honest reading of it: the bounce the helm wanted was a rim light, and the
    room to put it in came from dropping the floor, not from adding a second lamp.
    """
    shading.shade_region_by_light(NAME, band_ramp, base_color=base, light_angle=LIGHT,
                                  light_z=light_z, ambient=ambient, rim=rim, bulge=bulge,
                                  tolerance=1.0)


def hand_lit(points, band_ramp, *, lit=7, mid=5, dark=2):
    """Light a slab with no interior: the top row takes the key, the bottom row loses it.

    Right for something flat seen edge on, like a ward on a key. Wrong for anything that
    wraps, which is what `edge_lit` is for.

    **One slab per call.** This reads a global minimum and maximum y, so handing it two
    disconnected slabs lights the top of the upper one and the bottom of the lower one and
    leaves everything between them flat. `mid` is the other half of the same lesson: a
    three-row slab whose middle row is left at the fill colour is two lit rows and a hole,
    so every row of it gets a value and none of them is the colour it was filled with.
    """
    if not points:
        return
    top, bottom = min(y for _, y in points), max(y for _, y in points)
    flat(band(points, set(range(top + 1, bottom))), band_ramp[mid])
    flat(band(points, {top}), band_ramp[lit])
    flat(band(points, {bottom}), band_ramp[dark])


def edge_lit(points, band_ramp, *, lo=1, hi=None):
    """Light a part that wraps, by which way each pixel's edge faces.

    `hand_lit` lit this sheet's shield rim before, and the measurement was damning: every
    row of that rim, both sides, came out at the flat fill colour, because a rim's global
    top row is two pixels and its global bottom row is one. Ninety-odd pixels of steel
    stayed unshaded and the rim read as a second grey outline around the shield.

    A thin part has no interior for a distance field to measure, which is why
    `shade_region_by_light` refuses it. It does still have a direction: on a ring, a rim or
    a small gem, the vector from the part's centre out to a pixel is near enough the way
    that pixel's surface faces. Dot that against the key and take a ramp step from it.
    """
    if not points:
        return
    hi = len(band_ramp) - 2 if hi is None else hi
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    # Screen y grows downward, so the key's vector is (cos, -sin): at 128 degrees that
    # points up and to the left, which is where the light is.
    kx, ky = math.cos(math.radians(LIGHT)), -math.sin(math.radians(LIGHT))
    steps = {}
    for x, y in points:
        dx, dy = x - cx, y - cy
        reach = math.hypot(dx, dy) or 1.0
        facing = (dx / reach) * kx + (dy / reach) * ky
        step = lo + round((hi - lo) * (facing + 1.0) / 2.0)
        steps.setdefault(step, set()).add((x, y))
    for step, group in sorted(steps.items()):
        flat(group, band_ramp[step])


def raised(points, band_ramp, *, face=5, lit=7, dark=2):
    """A part standing proud of the one under it, which is three colours and not one.

    What makes a raised shape read is the pair of edges, not the fill: a lit border on the
    side the key comes from and a dark border opposite. Both fall out of shifting the shape
    a pixel diagonally, down and right being away from a light at 128 degrees.
    """
    flat(points, band_ramp[face])
    flat(points - {(x - 1, y - 1) for x, y in points}, band_ramp[dark])
    flat(points - {(x + 1, y + 1) for x, y in points}, band_ramp[lit])


sprite.create_sprite(NAME, CELL * COUNT, SIZE, overwrite=True)
layers.rename_layer(NAME, "Layer 1", "items")
# A selection lives in a `.msk` sidecar beside the sprite, because every tool call is its
# own Aseprite run and a selection is not stored in the .aseprite file. `overwrite=True`
# replaces the sprite and not the sidecar, so a run that died between the glints below and
# their deselect would hand the next run a selection covering one cell, and every shading
# pass outside it would fail with "no pixel matched". Starting clean costs one call.
selection.deselect(NAME)

SWORD, SHIELD_X, HELM_X, KEY, SCROLL = (CELL * i for i in range(COUNT))

blade = rows(SWORD, BLADE)
guard = rows(SWORD, GUARD) | rows(SWORD, POMMEL)
grip = rows(SWORD, GRIP)

shield = rows(SHIELD_X, SHIELD)
shield_face = erode(shield, 2)
shield_rim = shield - shield_face
cross = (rows(SHIELD_X, CROSS_V) | rows(SHIELD_X, CROSS_H)) & shield_face

helm = rows(HELM_X, HELM)
crest = rows(HELM_X, CREST)

bow = rows(KEY, BOW)
shank = rows(KEY, SHANK_LIT) | rows(KEY, SHANK_MID) | rows(KEY, SHANK_DARK)
ward_upper, ward_lower = rows(KEY, WARD_UPPER), rows(KEY, WARD_LOWER)
wards = ward_upper | ward_lower

roll = rows(SCROLL, TOP_ROLL)
parchment = rows(SCROLL, PARCHMENT)
curl = rows(SCROLL, CURL)
ribbon = rows(SCROLL, RIBBON_BAND) | rows(SCROLL, RIBBON_TAIL)

# 1. flat, every part in its own exact base colour so one shading pass can find it
flat(blade, STEEL[5])
flat(guard, BRASS[4])
flat(grip, WOOD[4])
flat(roll, WOOD[5])
flat(shield_rim, STEEL[4])
flat(shield_face, PAINT[4])
flat(helm, STEEL[3])
flat(bow, BRONZE[5])
flat(shank | wards, BRONZE[4])
flat(parchment | curl, PARCH[4])
flat(ribbon, RIBBON[4])

# 2. form, before any detail
# The helm, and the one pass here that is tuned rather than defaulted. It is the largest
# single smooth surface on the sheet and the only one whose shadow side is big enough to
# need describing rather than merely darkening: the shield's is broken up by its cross, and
# the grip, the rolls and the bow are all small enough that `ambient` covers them in a
# pixel or two. The twice-the-default rim is the bounce and the lowered ambient is the room
# to put it in; `form`'s docstring has the sweep that chose those two numbers over the fill
# light that looked like the right answer.
form(STEEL[3], STEEL, rim=0.32, light_z=0.5, ambient=0.22)
form(BRASS[4], BRASS, bulge=0.8)
form(WOOD[4], WOOD, bulge=0.8)
# `PAINT[:8]`, not the whole ramp. With the top step available, a 27px flat face at this
# rim put its whole upper edge on `PAINT[8]`, so a blue shield had a white stripe along the
# top and lost its hue exactly where the eye goes first.
form(PAINT[4], PAINT[:8], rim=0.10, bulge=0.7)
form(BRONZE[5], BRONZE, rim=0.22)
# What the tool refuses, and is right to: a 2px shield rim, a 3px key shank and a 6px ward
# have no interior, so there is no form for a distance field to find. The rim wraps, so it
# is lit by the direction its edges face; the wards are slabs, so the top row and the
# bottom row is the whole of what they have to say.
edge_lit(shield_rim, STEEL)
# One call per ward, for the reason `WARD_UPPER` gives.
hand_lit(ward_upper, BRONZE)
hand_lit(ward_lower, BRONZE)
flat(rows(KEY, SHANK_LIT), BRONZE[6])
flat(rows(KEY, SHANK_MID), BRONZE[4])
flat(rows(KEY, SHANK_DARK), BRONZE[2])

# 3. the detail that makes each item read as that item
# The blade, by column rather than by form. Everything below `BLADE_FULL_FROM` gets the
# seven-column section; the taper above it is only one to five pixels across, so it takes a
# two-tone split instead and keeps a bright tip.
for dx, step in BLADE_SECTION.items():
    flat({(x, y) for x, y in blade if x == SWORD + 20 + dx and y >= BLADE_FULL_FROM},
         STEEL[step])
taper = {(x, y) for x, y in blade if y < BLADE_FULL_FROM}
flat({(x, y) for x, y in taper if x <= SWORD + 20}, STEEL[TAPER_LIT])
flat({(x, y) for x, y in taper if x > SWORD + 20}, STEEL[TAPER_DARK])
# The grip's lit edge, so five rows of dark leather between a bright guard and a bright
# pommel read as a grip rather than as a gap.
flat({(x, y) for x, y in grip if x == SWORD + 18}, WOOD[7])
flat(rows(SWORD, WRAP), RIBBON[2])
flat(rows(SWORD, GUARD_EDGE), BRASS[1])
raised(cross, GOLD)
flat(rows(SHIELD_X, RIVETS) & shield_rim, STEEL[8])
flat(rows(HELM_X, VISOR), STEEL[0])
flat(rows(HELM_X, BREATHS), STEEL[0])
raised(crest, GOLD)
# The roll banded by row, its near cap up a step and its far cap down two, so it reads as
# a cylinder with ends rather than as a tube open at both.
for y, step in ROLL_BANDS.items():
    flat(band(roll, {y}), WOOD[step])
flat(rows(SCROLL, ROLL_CAP_LIT) & roll, WOOD[3])
flat(rows(SCROLL, ROLL_CAP_DARK) & roll, WOOD[1])
# Paper is flat, so it gets four column bands and not a form. Given to
# `shade_region_by_light`, the pinched silhouette splits the distance field into two lobes
# and the sheet came out with a blotch of darker tan across its lower right that read as a
# water stain. Same reasoning as the blade's columns: the tool describes a rounded form,
# and neither a sheet of paper nor a sword blade is one.
#
# **Exclusive ranges, which is the whole fix.** The draft selected `dx <= -7`, then
# `dx <= -1`, then `dx <= 5`, then `dx <= 13`, so every band was a superset of the one
# before it and each pass repainted everything its predecessor had just done. The last
# pass selected the entire sheet and filled it with `PARCH[4]`, which is also the colour
# the paper was flat-filled with, so four bands of work produced 325 pixels of one dead
# value, 221 of them in a single connected region across rows 19 to 30, and `PARCH[5]` and
# `PARCH[6]` appeared nowhere on the sheet at all. A band that selects "everything left of
# here" has to be written widest-first or bounded on both sides; this one is bounded.
#
# Brightest band on the left, because the light is at 128 degrees and this is a flat
# plane: the side of it facing the light is the side facing the light, and a sheet of paper
# has no curvature to complicate that.
PAPER_BANDS = ((-12, -7, 6), (-6, -1, 5), (0, 5, 4), (6, 12, 3))
for lo, hi, step in PAPER_BANDS:
    flat({(x, y) for x, y in parchment if lo <= x - SCROLL - 20 <= hi}, PARCH[step])
# The curl, lighter than the shadow side of the sheet it folds back from: it is the back of
# the paper catching the light. `PARCH[5]`, not the `PARCH[7]` the draft used. At `PARCH[7]`
# the curl was 38 pixels of `#fefdfc` at rows 32 and 33, which made the brightest thing in
# the cell the *bottom* edge of the item, under a light coming from above and to the left.
flat(curl, PARCH[5])
flat(band(curl, {min(y for _, y in curl)}), PARCH[2])
flat(rows(SCROLL, WRITING) & parchment, PARCH[0])
# The ribbon in flat bands, plus its tail.
for y, step in RIBBON_STEPS.items():
    flat(band(ribbon, {y}), RIBBON[step])
flat(rows(SCROLL, RIBBON_TAIL), RIBBON[3])

# 4. a dithered terminator where a hard band boundary would read as a step. The steps are
#    1-based here, so 4 and 5 are `ramp[3]` and `ramp[4]`, which is where the terminator
#    lands at this ambient. Tolerance tight again, for the reason `form` gives.
#
#    Only on PAINT, which is the one surface here wide enough to carry it. On STEEL the
#    pass landed on the helm, the largest smooth region on the sheet, and a four-pixel
#    checkerboard across a 23px face was the loudest thing here: it read as damage rather
#    than as a widened transition. On PARCH it put a row of tan teeth across the middle of
#    the sheet, which read as a corrupted texture. A dither has to be small against the
#    form it is widening, and on both of those it was a third of the surface.
for band_ramp in (PAINT,):
    shading.dither_band(NAME, band_ramp, from_step=4, to_step=5, pattern="bayer4",
                        width=2, tolerance=1.0)

# 5. clean the band boundaries, protecting the one-pixel details that are strays by the
#    tool's own definition and are meant to be there
#    The roll's two end caps are *not* on this list, though they are two pixels wide: each
#    is a solid 2 by 3 block, so no pixel in one is isolated and the tool leaves them
#    alone. Protecting them by colour instead would have cost more than it bought, because
#    `WOOD[1]` and `WOOD[3]` are also steps the grip's own shading pass can land on, and
#    protecting them there spared a single orphan wood pixel on the leather.
effects.remove_stray_pixels(NAME, protect=[STEEL[8], STEEL[1], STEEL[0], STEEL[6],
                                           GOLD[2], GOLD[7], WOOD[2], WOOD[7],
                                           PARCH[0], PARCH[2], RIBBON[2], BRASS[1]])

# 6. the glints, last, so nothing overpaints them. Scoped by a selection rather than by a
#    base colour: that makes the region one whole item, which is the form a glint belongs
#    to, instead of one band of it. A band after shading is a crescent a pixel or two
#    across, and `specular_highlight` refuses that rather than inventing a form for it.
#    `highlight_color` is off-ramp on purpose, which is what a polished surface does and
#    what the tool documents for metal; the result reports the conformance it costs.
#
#    The scroll gets none. Parchment has no specular, and a glint on it would be the kind
#    of detail that is added because a tool exists rather than because the surface has one.
#    The selection is the *part*, not the cell, and that is the whole fix. Scoped to the
#    cell, the region was the entire compound object and the normals described its overall
#    mass: the sword's two glint pixels landed at (19,29) and (19,30), on the leather grip,
#    while the blade had none, and the key's landed on the lower right of its bow, which at
#    128 degrees is the shadow side. A rectangle that holds one part and no other is enough
#    to say which part should shine.
GLINTS = (
    # Rows 0 to 25, which stops a row short of the guard's quillons: the rectangle has to
    # hold the blade and no other part, and the assertion below is what says it does.
    ("blade", (SWORD, 0, CELL, 26), STEEL, "#ffffff", 2),
    ("shield", (SHIELD_X, 0, CELL, SIZE), PAINT, "#ffffff", 3),
    ("helm", (HELM_X, 0, CELL, SIZE), STEEL, "#ffffff", 3),
    ("bow", (KEY, 0, CELL, 15), BRONZE, "#fff6e4", 2),
)
PARTS = {"blade": blade, "shield": shield, "helm": helm, "bow": bow}
for part, (x, y, w, h), band_ramp, white, size in GLINTS:
    selection.select_region(NAME, "rect", x=x, y=y, width=w, height=h)
    placed = shading.specular_highlight(
        NAME, band_ramp, light_angle=LIGHT, light_z=0.62, size=size, tightness=0.55,
        highlight_color=white)
    landed = {(px, py) for px, py in placed["pixels"]}
    assert landed <= PARTS[part], f"the {part} glint landed outside it: {sorted(landed)}"
    if part == "bow":
        bow_glint = landed
    print(f"  glint on the {part:<6} {sorted(landed)}")
# Before the outline, or the outline traces one cell and leaves the rest bare.
selection.deselect(NAME)

# 6b. the key's hole, punched here and not earlier, and both halves of that matter.
#     Not before the form pass, because a lozenge with a hole in it has less interior than
#     one without and the pass that gives it form wants all of it. Not before the glint
#     either, which is what the first version of this fix got wrong: scoping the glint to
#     the bow put it at (21,10) all the same, on the bow's lower right, because a hole
#     punched above centre takes its own edge out of the eligible interior and pushes the
#     best-aligned pixel away from it. The hole is a feature of the drawing, not of the
#     surface, so it goes in once the surface is finished.
flat(rows(KEY, BOW_HOLE), "transparent")
survivors = {p for p in bow_glint if items_pixel(p) == "#fff6e4"}
assert survivors == bow_glint, f"the hole ate the bow's glint: {sorted(bow_glint - survivors)}"

# 7. one dark outline over everything. It fills the key's hole as well, which is what a
#    hole that small should look like.
effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside")

# ------------------------------------------------------------- the check worth the most
# Every pixel in a cell has to come from that cell's own materials. This is not pedantry:
# it is the assertion that caught the tolerance bug above, after three rounds of redrawing
# a coin's mark to fix a problem that was never in the mark. The sheet looked plausible the
# whole time, which is the reason a showcase needs measuring and not only looking at.
MATERIALS = {
    SWORD: ("sword", STEEL, BRASS, WOOD, RIBBON),
    SHIELD_X: ("shield", STEEL, PAINT, GOLD),
    HELM_X: ("helm", STEEL, GOLD),
    KEY: ("key", BRONZE),
    SCROLL: ("scroll", PARCH, WOOD, RIBBON),
}
everywhere = {OUTLINE.lower()} | {w.lower() for _, _, _, w, _ in GLINTS}
print()
for ox, (item, *band_ramps) in MATERIALS.items():
    allowed = everywhere | {c.lower() for band_ramp in band_ramps for c in band_ramp}
    grid = inspect.get_pixels(NAME, ox, 0, CELL, SIZE)["pixels"]
    used = {p[:7].lower() for row in grid for p in row if not p.endswith("00")}
    assert not used - allowed, f"{item} holds another material: {sorted(used - allowed)}"
    print(f"  {item:<7} {len(used):>2} colours, from {len(band_ramps)} "
          f"ramp{'s' if len(band_ramps) > 1 else ''} and nothing else")

# Every paper band asserted present by colour, because the bug it replaces was silent: four
# passes ran, every one of them reported the pixels it had written, and the sheet came out
# one flat value with two of its four intended steps nowhere in the image. "The call
# succeeded" and "the colour is on the canvas" are different claims, and only the second
# one is worth anything here.
paper = {p[:7].lower()
         for row in inspect.get_pixels(NAME, SCROLL, 0, CELL, SIZE)["pixels"]
         for p in row if not p.endswith("00")}
missing = [s for *_edges, s in PAPER_BANDS if PARCH[s].lower() not in paper]
assert not missing, f"paper bands PARCH{missing} were painted over: {sorted(paper)}"
print("  paper   bands at PARCH steps "
      + ", ".join(str(s) for *_edges, s in PAPER_BANDS) + ", every one of them present")

# Two more things the eye cannot check, both of them a criterion a review set.
#
# The sword has to be mostly blade. The draft was 54% and read as a spearhead, and 54% is
# not something anybody notices as a number.
tops = {}
for ox, (item, *_r) in MATERIALS.items():
    grid = inspect.get_pixels(NAME, ox, 0, CELL, SIZE)["pixels"]
    used_rows = [y for y, row in enumerate(grid) if any(not px.endswith("00") for px in row)]
    tops[item] = (min(used_rows), max(used_rows))
guard_top = min(y for _, y in rows(SWORD, GUARD))
sword_top, sword_bottom = tops["sword"]
share = (guard_top - sword_top) / (sword_bottom - sword_top + 1)
print()
print(f"sword: blade is rows {sword_top} to {guard_top - 1}, {share:.0%} of its height")
assert share >= 0.65, f"the blade is {share:.0%} of the sword, which is a spearhead"

# And the five have to agree on a centre line, or the row reads as five unrelated sprites.
centres = {item: (lo + hi) / 2 for item, (lo, hi) in tops.items()}
spread = max(centres.values()) - min(centres.values())
print("centres: " + "  ".join(f"{i}={c:.1f}" for i, c in centres.items())
      + f"   spread {spread:.1f}")
assert spread <= 2.0, f"the items' centres span {spread:.1f} rows"

# The check that was missing, and the hole the centre check leaves. Agreeing on a centre
# says nothing about size: the draft's sword ran rows 0 to 39 of a 40-row cell against 31,
# 33, 34 and 32 for the other four, so it was 6 to 9 rows taller than everything beside it
# and touched both edges of its cell, and it centred on 19.5 while doing it. A centred
# sprite with no bleed margin is the one that clips the moment anything is drawn around it,
# and a row of items that disagree by nine rows on how big an item is has no scale.
heights = {item: hi - lo + 1 for item, (lo, hi) in tops.items()}
extent = max(heights.values()) - min(heights.values())
margin = min(min(lo for lo, _ in tops.values()), SIZE - 1 - max(hi for _, hi in tops.values()))
print("heights: " + "  ".join(f"{i}={h}" for i, h in heights.items())
      + f"   spread {extent}   bleed margin {margin}")
assert extent <= 4, f"the items' heights span {extent} rows, so the sheet has no scale"
assert margin >= 1, f"an item reaches within {margin} rows of its cell edge"

export.export_png(NAME, "items.png", scale=5, overwrite=True)
print("\nwrote items.png")
