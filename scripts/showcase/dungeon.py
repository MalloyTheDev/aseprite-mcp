"""Build the dungeon showcase: one lit scene, and the same scene as a flickering loop.

The other showcase pieces are each about one tool. This one is about what the tools do
together, because that is the thing a sprite-by-sprite gallery cannot show: masonry whose
every block has its own form, a light that falls off across the room, a chest that throws a
shadow onto the floor and not into the air, and a flame whose halo is made of palette
entries rather than of alpha.

Four ideas carry it.

**One shading pass per material, not per object.** `shade_region_by_light` builds a
distance field over everything matching one base colour, and a field over a mask with
forty disconnected parts describes each part on its own. So the whole wall, every block of
it, takes its form from a single call and comes out domed instead of flat. One more call
does the floor. The joints between the blocks are what make this work: they are why the
mask is forty components and not one slab.

**Firelight has a colour, and a ramp grown from a grey cannot say so.** Every hue control
on `generate_ramp` rotates hue; none of them creates saturation, which is inherited from
the base colour and only scaled from there. So a base picked the way a base is usually
picked ("stone is grey", so `#6e7183`) carries almost none, and the rotation renders as
greys. Measured on the draft before this one: the stone ramp turned 17 degrees of hue at a
0.077 saturation floor with ten of its thirteen steps under the chroma at which hue is
visible at all, and its lit end sat at 0.074 saturation against the flame's 0.97. The lit
side of every block was cooler and flatter than its own shadow, which is the exact
inversion of firelight, and the brightest value in the room after the flame core was a
cold grey covering five times as many pixels. `chroma` is the argument that fixes it: it
sets the saturation the ramp holds instead of scaling what the base happened to bring.

**The falloff is zones stepped down a ramp on the wall, and per pixel on the floor,**
because the two surfaces are not the same shape. No tool here lights a scene from a point,
and faking one by blending would put every pixel between palette entries. On the wall,
`shift_along_ramp` moves a rectangle one or two steps down the surface's own ramp, which
is how a pixel artist builds a falloff: a few zones, every pixel still exactly a ramp
colour, and the seams hidden. Hiding them is the whole trick, and it is why this is a
rectangle per course rather than one band across the room. The only cut that does not show
is one along a joint, and because the courses are staggered no single column is a joint on
all of them. Per course, every cut is.

The floor cannot use that, and the draft that did is what made it read as a second wall
lying down. A floor's joints converge on a vanishing point, so no vertical cut can follow
one and every zone boundary showed as a value step straight across a flagstone. So the
floor is lit the way the torch's own pool is: read the surface once, move every pixel along
the floor's ramp by what its distance from the flame allows, write it back. Every pixel is
still exactly a ramp entry. What changes is that the boundary between two zones follows the
light instead of the masonry, which on a receding plane is what it should do anyway.

**The flicker is four frames with four different durations, and the room moves with
them.** `set_all_frame_durations` would give an even pulse, and an even pulse reads as a
machine rather than as fire. The flame also leans a different way and stands a different
height on each frame, because a flame that only changes brightness reads as a lamp with a
loose wire. And the room guttters with it: the wall's pool, the sconce's brass and the
chest's lid each take a few ramp steps off the same four-frame table. The draft before this
one baked the light pool before duplicating the frames, so the wall's lit values were
byte-identical on all four and the four frames differed only inside a 17x17 box around the
flame, 3.6 percent of the canvas. A guttering flame inside a pool of light that is bolted
down reads as a decal.
"""
import colorsys
import itertools
import pathlib
import statistics

from aseprite_mcp.tools import (
    drawing,
    effects,
    export,
    frames,
    inspect,
    layers,
    palette,
    shading,
    sprite,
)

NAME = "dungeon.aseprite"
W, H = 112, 72
# 37 rather than 46, because the wall's courses are 8 rows with a joint between them and
# the old value cut the bottom one in half, right at the most looked-at line in the picture.
# A course ends on 1 + 9k, so 37 is where one ends whole.
WALL_BOTTOM = 37
# A shorter course of stone at the wall's foot, then the floor. The draft put four dead
# flat full-width rows here instead. It did stop two surfaces of grey blocks reading as one
# wall, the way a letterbox bar stops a bad crop.
SKIRT_TOP, FLOOR_TOP = 38, 43
# Block widths, cycled with a per-course phase. Uniform 17px blocks were what made the far
# wall a repeating tile: shade_region_by_light gives every component of the same size the
# same distance field, so same-sized blocks come out identically shaded and differ only in
# how far the falloff pushed them. Varying the widths varies the field.
WALL_WIDTHS = (17, 11, 23, 14, 20)
OUTLINE = "#140f1e"
# Everything in the room is lit by the torch, so the key comes from where the torch is.
LIGHT = 155.0
TORCH_X, TORCH_Y = 20, 17


def ramp(base, *, hue=-18.0, sat=-20.0, light=0.80, steps=9, chroma=None,
         shadow_hue=None, light_hue=None):
    colors = palette.generate_ramp(base, steps=steps, hue_shift=hue,
                                   saturation_shift=sat, light_range=light,
                                   chroma=chroma, shadow_hue=shadow_hue,
                                   light_hue=light_hue)["colors"]
    assert len(set(colors)) == steps, f"{base} at light_range={light} clips: {colors}"
    return colors


def lightness(colour):
    return colorsys.rgb_to_hls(*[int(colour[i:i + 2], 16) / 255
                                 for i in (1, 3, 5)])[1]


# Where the two ends of a fire-lit ramp go. `shadow_hue` and `light_hue` rather than
# `hue_shift`, because the rule an artist states is not symmetric: shadows go toward blue
# and highlights toward the flame, and a single rotation about the base forces the two ends
# to be equal and opposite distances from it. Rotated that way, the warm end of a ramp
# whose shadows reached blue came out green.
FIRE_SHADOW, FIRE_LIGHT = "#3b4f8a", "#ffb347"

# Thirteen steps, not nine. `shift_along_ramp` clamps at the ends, so pushing a block three
# steps down a nine-step ramp collapsed its darks together: 8 of 24 sampled blocks came out
# pixel for pixel identical at 6 tones, all in the dim zone, and the far wall was one tile
# repeated. A longer ramp leaves a darkened block somewhere to go.
#
# `light_range=0.74` from a base at 0.42 lightness, which caps the lit end at 0.79 rather
# than the 0.89 it used to reach. The cap is the point: a stone a step off white put the
# coldest surface in the room second only to the flame core by brightness and five times
# ahead of it by volume. Stone lit by fire is never the brightest thing in the frame, and
# the three steps of headroom left above it belong to the flame.
STONE = ramp("#7a6a5c", steps=13, chroma=0.22, sat=16.0, light=0.74,
             shadow_hue=FIRE_SHADOW, light_hue=FIRE_LIGHT)
FLAGS = ramp("#6b5c4e", steps=13, chroma=0.21, sat=16.0, light=0.70,
             shadow_hue=FIRE_SHADOW, light_hue=FIRE_LIGHT)
# The chest and the sconce keep ramps grown from their own saturated bases, because a wood
# and a brass are named by hue in the first place and arrive with chroma already on them.
# `chroma` is for the materials nobody names by hue, which is what made the two greys the
# ones that needed it.
CHESTWOOD = ramp("#7a4a28", light=0.66)
BRASS = ramp("#d99a33", hue=-22.0, sat=-14.0)
FLAME = ramp("#ff9a1f", hue=22.0, sat=-6.0, light=0.84)
# The halo's ends are chosen rather than grown: `ramp_between` returns both exactly, so the
# outer ring is a dark ember and the inner one is the flame's own brightest step. Growing
# this from a single base would mean guessing at hue_shift until the dark end happened to
# land somewhere useful.
#
# Both drafts before this one got the dark end wrong, in opposite directions. Interpolating
# from the stone's own blue-grey passes through neutral and reads as a ball of fog stuck on
# the wall; starting from a dark ember makes the outer rings darker than the wall they lie
# on, and a glow that darkens what it touches reads as a shadow. The end that works is a
# *warm grey a step lighter than the lit stone*, so the outermost ring is the wall with
# light on it, which is what the outside of a pool of light actually is. It moved when the
# stone's lit end was capped: at 0.835 lightness it is one step above `STONE[12]`, where
# the old `#9a8f90` would now sit six steps below it and darken what it touched.
HALO = palette.ramp_between("#e4d8c6", FLAME[7], steps=5)["colors"]


def pts(points):
    return [{"x": x, "y": y} for x, y in sorted(points)]


def rows(ox, spans):
    return {(ox + dx, y)
            for y, runs in spans.items()
            for left, right in runs
            for dx in range(left, right + 1)}


def erode(points, steps=1):
    out = set(points)
    for _ in range(steps):
        out = {(x, y) for x, y in out
               if all((x + dx, y + dy) in out
                      for dx in (-1, 0, 1) for dy in (-1, 0, 1))}
    return out


def flat(points, colour, layer, frame=1):
    if points:
        drawing.draw_pixels(NAME, pts(points), colour, layer=layer, frame=frame)


def course_blocks(y0, height, widths, phase, top, bottom):
    """One course of blocks of cycling widths, with a one-pixel joint between them."""
    rects, x, i = [], -widths[phase % len(widths)] - (phase * 5) % 9, phase
    while x < W:
        width = widths[i % len(widths)]
        left, right = max(x, 0), min(x + width, W)
        upper, lower = max(y0, top), min(y0 + height, bottom + 1)
        if right > left and lower > upper:
            rects.append((left, upper, right - left, lower - upper))
        x += width + 1
        i += 1
    return rects


def wall_courses(top, bottom, block_h, widths):
    """Courses of equal height, each a different sequence of block widths."""
    rects = []
    for course, y0 in enumerate(range(top - block_h + 2, bottom + 1, block_h + 1)):
        rects += course_blocks(y0, block_h, widths, course, top, bottom)
    return rects


def points_of(rects):
    return {(x, y) for rx, ry, rw, rh in rects
            for y in range(ry, ry + rh) for x in range(rx, rx + rw)}


def zone_of(cx, cy, near, mid):
    distance = ((cx - TORCH_X) ** 2 + (cy - TORCH_Y) ** 2) ** 0.5
    return 0 if distance < near else 1 if distance < mid else 2


def falloff_runs(rects, near, mid):
    """Merge each course's blocks into runs of one zone, and return a rectangle per run."""
    by_course = {}
    for x, y, w, h in rects:
        by_course.setdefault((y, h), []).append((x, w))
    out = []
    for (y, h), row in sorted(by_course.items()):
        run = None
        for x, w in sorted(row):
            step = zone_of(x + w / 2, y + h / 2, near, mid)
            if run is not None and run[0] == step and run[2] + 1 >= x:
                out[-1] = run = (step, run[1], x + w, y, h)
                continue
            run = (step, x, x + w, y, h)
            out.append(run)
    return [(step, x0, y, x1 - x0, h) for step, x0, x1, y, h in out if step]


# ---------------------------------------------------------------------------- the floor
# A floor is a different surface from a wall, and the draft before this one ran the same
# `course_blocks` call on both and separated them by value alone. Measured, the bottom 40
# percent of the frame read as a second masonry wall lying down: every joint axis-aligned,
# and native rows 48, 55 and 63 carrying 60, 60 and 56 consecutive pixels of one colour
# starting at x=0, which is a single-colour rule drawn across the whole picture.
#
# Two cues say floor instead. The courses grow taller down the frame (#196), and the
# vertical joints are rays out of a vanishing point in the torch's own column, so they fan
# apart as they come forward and the stones widen with them rather than by a width typed
# out per course.
FLOOR_COURSES = (5, 6, 7, 8)
FLOOR_VANISH_X = TORCH_X
# How far above the floor's first row the vanishing point sits. A point inside the frame
# fans one joint 16 pixels across a single course, which bends the floor into a fisheye;
# 56 puts the far course's stones at two thirds the width of the near one, which is the
# proportion the previous draft typed out as four hand-picked widths and is a consequence
# of the geometry here instead.
FLOOR_DEPTH = 56
FLOOR_SPACING = 30


def ray_x(seed, y):
    """Where the joint seeded at `seed` on the bottom row crosses row `y`."""
    apex = FLOOR_TOP - FLOOR_DEPTH
    return FLOOR_VANISH_X + (seed - FLOOR_VANISH_X) * (y - apex) / (H - 1 - apex)


def course_rows():
    """The rows each course nominally occupies, the near one tallest."""
    out, y = [], FLOOR_TOP
    for i, height in enumerate(FLOOR_COURSES):
        bottom = H - 1 if i == len(FLOOR_COURSES) - 1 else y + height - 1
        out.append((y, min(bottom, H - 1)))
        y = bottom + 2
    return out


def course_cuts():
    """The row each joint between two courses nominally falls on."""
    return [bottom + 1 for _top, bottom in course_rows()[:-1]]


def ray_edges(band, y):
    """The joint columns of one course at one row, left to right.

    The seed set is a third of a stone out of step per course, so a joint in one course is
    not the continuation of a joint in the course above it even before the rays fan them
    apart. Eleven is coprime with the spacing, which is what keeps all four courses on
    different phases.
    """
    first = FLOOR_VANISH_X - 2 * FLOOR_SPACING + (band * 11) % FLOOR_SPACING
    return [round(ray_x(first + k * FLOOR_SPACING, y))
            for k in range(2 + (W + 3 * FLOOR_SPACING) // FLOOR_SPACING)]


def cell_at(band, x, y):
    """Which stone of course `band` column x falls in at row y, and that stone's left edge."""
    edges = ray_edges(band, y)
    for cell in range(len(edges) - 1):
        if edges[cell] <= x < edges[cell + 1]:
            return cell, edges[cell]
    return 0, edges[0]


def cut_rows():
    """The row each course joint actually falls on, per column: a stepped line, not a rule.

    An unbroken row of one value across all 112 pixels is most of what made the floor read
    as a wall, and three of them were what the courses were separated by. Coursing is laid
    stone by stone, so the line steps at every joint, by that stone's own deterministic
    amount. Three possible rows rather than two, because two alternating values still let
    half the stones share a line.
    """
    return [[nominal - (cell_at(band, x, nominal)[0] * 5 + nominal * 3) % 3
             for x in range(W)]
            for band, nominal in enumerate(course_cuts())]


def floor_surface():
    """Every floor pixel, as part of a flagstone or as the mortar between two of them.

    Returns the stones keyed by (course, stone), and the mortar as a point set. The cut row
    is always mortar, so two courses can never touch however far their lines have stepped,
    and each stone stays its own component for `shade_region_by_light` to find.
    """
    cuts = cut_rows()
    stones, mortar = {}, set()
    for y in range(FLOOR_TOP, H):
        for x in range(W):
            if any(y == cut[x] for cut in cuts):
                mortar.add((x, y))
                continue
            band = sum(1 for cut in cuts if y > cut[x])
            cell, left = cell_at(band, x, y)
            if x == left:
                mortar.add((x, y))
            else:
                stones.setdefault((band, cell), set()).add((x, y))
    return stones, mortar


def mortar_sources(stones, mortar):
    """Each mortar pixel paired with the flagstone pixel it is a darkening of.

    Mortar is not a colour, it is the stone beside it in shadow, and filling it as one flat
    value is what put `#231f21` across 777 pixels of the previous draft: the single
    most-used colour in the whole picture was the grout. Derived instead, it follows the
    light across the room, and because it is pinned a fixed number of steps under whatever
    stone it borders it can never collapse into that stone in the dark corners, which is
    the other half of why the foreground went flat.
    """
    owned = {point for points in stones.values() for point in points}
    pairs = {}
    for x, y in sorted(mortar):
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1),
                       (1, 1), (-1, 1), (1, -1), (-1, -1)):
            if (x + dx, y + dy) in owned:
                pairs[(x, y)] = (x + dx, y + dy)
                break
    return pairs


# The floor's own light. `FLOOR_LIT` steps of lift at the flame falling linearly to none at
# `FLOOR_REACH`, against `FLOOR_DARK` steps taken off the whole surface, so the near-left
# flagstones sit above where they were drawn and the far corners well below.
# Three steps off the whole surface and not four: at four, the stones whose shading had
# already put them near the bottom of the ramp clamped onto its last step, and a clamp is
# how the far corner stops carrying information at all. The lit term is unchanged, so the
# distance between the near flagstones and the far ones is the same five ramp steps either
# way; what changes is that the far ones still have somewhere to go.
FLOOR_REACH, FLOOR_LIT, FLOOR_DARK = 100.0, 8, 3
# The corner where the floor meets the wall, tapered over four rows rather than painted as
# four full-width rules. Two planes meeting need a dark line between them, and the previous
# draft got one by shifting whole rows, which is a letterbox bar by another name (#196).
FLOOR_CREASE = 3
# How far under its own flagstone a mortar pixel sits.
MORTAR_DROP = 2


def scuff(x, y):
    """One ramp step of wear on a flagstone, denser the nearer the stone is to the viewer.

    The foreground was the flattest part of the picture, which is backwards. Measured on the
    previous draft, native rows 64..71 from x=60 rightward were 64.4 percent a single
    colour and row 68 carried a 50 pixel run of it: the nearest, largest and most looked-at
    stones in the scene held the least information in them. Stone that close to the eye
    shows its surface, so the period shortens with depth, from one chip in seventeen pixels
    at the far wall to one in eight at the bottom edge.

    Two pixels wide, because a lone pixel of another value is read as dirt rather than as
    texture (`assess_sprite` counts those as `isolated_pixels`), and a pair is read as a
    chip.
    """
    depth = (y - FLOOR_TOP) / (H - 1 - FLOOR_TOP)
    period = round(17 - 9 * depth)
    key = ((x // 2) * 31 + y * 17) % period
    return 1 if key == 0 else -1 if key == 1 else 0


def grit(x, y):
    """A lighter fleck in a mortar joint, one run of two pixels in nine.

    Derived mortar follows the light, which varies slowly, so a joint laid along one course
    can still be thirty pixels of a single step even after the courses are staggered:
    measured on the geometry alone, the longest stretch of one course joint sitting on one
    row is 27 pixels. Mortar is the crumbliest thing in the room and has no business being
    the smoothest, so it gets grit.
    """
    return 1 if ((x // 2) * 13 + y * 29) % 9 == 0 else 0


def flagstone_light(stones, sources):
    """Light, wear and mortar the whole floor, in one read and one write.

    Every pixel here is already an exact ramp entry, so moving one is a table lookup: find
    its step, add what the distance from the flame allows, subtract the crease and the
    stone's own tint, chip it, clamp. The mortar is then set from the stone it borders
    rather than from what it was filled with, which is the one thing a rectangle of
    `shift_along_ramp` cannot do.
    """
    index = {colour.lower(): step for step, colour in enumerate(FLAGS)}
    grid = inspect.get_pixels(NAME, 0, FLOOR_TOP, W, H - FLOOR_TOP,
                              layer="floor")["pixels"]
    was = {(x, FLOOR_TOP + row): pixel[:7].lower()
           for row, line in enumerate(grid)
           for x, pixel in enumerate(line)}
    moved, skipped = {}, 0
    for key, points in sorted(stones.items()):
        # About a fifth of the stones a step off their neighbours, the same rule the wall
        # uses and for the same reason: masonry at one value per course is wallpaper.
        tint = -1 if (key[0] * 7 + key[1] * 13) % 5 == 0 else 0
        for x, y in sorted(points):
            step = index.get(was[(x, y)])
            if step is None:
                skipped += 1
                continue
            reach = ((x - TORCH_X) ** 2 + (y - TORCH_Y) ** 2) ** 0.5
            lit = round(FLOOR_LIT * max(0.0, 1.0 - reach / FLOOR_REACH))
            crease = max(0, FLOOR_CREASE - (y - FLOOR_TOP))
            moved[(x, y)] = min(max(step + lit - FLOOR_DARK - crease + tint
                                    + scuff(x, y), 0), len(FLAGS) - 1)
    for point, source in sorted(sources.items()):
        if source in moved:
            moved[point] = max(moved[source] - MORTAR_DROP + grit(*point), 0)
        else:
            skipped += 1
    write = [{"x": x, "y": y, "color": FLAGS[step]}
             for (x, y), step in sorted(moved.items())
             if FLAGS[step] != was[(x, y)]]
    if write:
        drawing.draw_pixels(NAME, write, layer="floor")
    return len(write), skipped


# --------------------------------------------------------------------------- the sconce
CUP = {24: [(-4, 4)], 25: [(-5, 5)], 26: [(-5, 5)], 27: [(-4, 4)], 28: [(-3, 3)]}
STEM = {y: [(-1, 1)] for y in range(29, 34)}
PLATE = {34: [(-3, 3)], 35: [(-4, 4)], 36: [(-4, 4)], 37: [(-3, 3)]}

# --------------------------------------------------------------------------- the flame
# Derived rather than typed out, which is the opposite of the item sheet's rule and for the
# opposite reason: a heart has a notch a formula gets wrong, and a flame has no feature at
# all a reader could catch being a pixel off. The profile is half-widths from the tip down,
# and each frame takes a different length and a different lean.
#
# The fourth column is how many ramp steps the room gives up on that frame, and it is typed
# out beside the duration rather than derived from the profile's length, because two of
# these flames are the same height and no two frames should share a lighting state. It is
# never positive: the baked pool is the brightest the room gets and the flicker gutters
# down from it, which is both the direction a torch moves and the reason this can be
# applied on top of the pool without a ceiling to clamp against.
FLAME_BASE_Y = 23
PROFILE = [0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 3, 3, 2]
FLICKER = [
    (PROFILE, 0.00, 90, -1),
    (PROFILE[2:], 0.18, 70, -3),
    ([0, 0, *PROFILE[1:]], -0.14, 110, 0),
    (PROFILE[1:-1], 0.10, 80, -2),
]


def flame_points(profile, lean):
    out = set()
    tall = len(profile)
    for i, half in enumerate(profile):
        up = tall - 1 - i
        drift = round(lean * up)
        out |= {(TORCH_X + dx + drift, FLAME_BASE_Y - up)
                for dx in range(-half, half + 1)}
    return out


# --------------------------------------------------------------------------- the chest
CHEST_X = 74
LID = {
    44: [(-9, 9)], 45: [(-11, 11)], 46: [(-12, 12)],
    **{y: [(-13, 13)] for y in range(47, 51)},
}
SEAM = {51: [(-13, 13)]}
BODY = {y: [(-13, 13)] for y in range(52, 64)}
TRIM = {64: [(-14, 14)]}
# Two pixels wide, not three, and a five-pixel lock rather than seven. The straps and the
# lock are drawn over the lid's seam, which is correct (a strap covers a seam), but at the
# old widths they covered 17 of the lid's 27 pixels and the seam survived as four dashes.
# A chest whose lid you cannot find is a box.
STRAPS = {y: [(-10, -9), (9, 10)] for y in range(44, 65)}
LOCK = {y: [(-2, 2)] for y in range(49, 54)}
# The body's top edge, catching the light the lid's overhang does not block. This is what
# actually sells a lid: not the dark seam, but the lit line under it.
LIP = {52: [(-13, 13)]}

def is_variant(rect):
    """Pick about a fifth of the blocks to sit a step darker than their neighbours.

    Masonry where every block is the same value reads as wallpaper, and the fix is not a
    crack drawn on top: the draft with three hand-placed cracks read as scratches on a
    clean wall. Real stone varies block to block, and one `shift_along_ramp` per chosen
    block is that, in the block's own ramp. Deterministic on the block's own position,
    because a showcase generator has to produce the same picture every run.
    """
    x, y, _w, _h = rect
    return (x * 7 + y * 13) % 5 == 0


# ----------------------------------------------------------- the rubble, placed by hand
RUBBLE = [
    {(13, 64), (14, 64), (14, 65), (15, 65)},
    {(43, 57), (44, 57)},
    {(94, 68), (95, 68), (95, 69), (96, 69)},
    {(66, 69), (67, 69)},
]

sprite.create_sprite(NAME, W, H, overwrite=True)
layers.rename_layer(NAME, "Layer 1", "wall")
# The sconce is above the flame, so the halo below it cannot paint over the brass. On the
# first run the glow layer landed on top and swallowed the whole fitting.
for name in ("floor", "chest", "flame", "sconce"):
    layers.add_layer(NAME, name)

# 1. masonry, flat. Blocks and joints are two colours on one layer.
wall_rects = wall_courses(0, WALL_BOTTOM, 8, WALL_WIDTHS)
skirt_rects = course_blocks(SKIRT_TOP, FLOOR_TOP - SKIRT_TOP, (11,), 3,
                            SKIRT_TOP, FLOOR_TOP - 1)
floor_stones, floor_mortar = floor_surface()
wall_blocks = points_of(wall_rects) | points_of(skirt_rects)
floor_blocks = {point for points in floor_stones.values() for point in points}
flat(wall_blocks, STONE[8], "wall")
flat({(x, y) for y in range(FLOOR_TOP) for x in range(W)} - wall_blocks, STONE[2], "wall")
flat(floor_blocks, FLAGS[8], "floor")
flat(floor_mortar, FLAGS[2], "floor")
print(f"floor: {len(floor_stones)} flagstones, {len(floor_mortar)} pixels of mortar "
      f"between them, over {len(FLOOR_COURSES)} courses")

# 2. one call per surface, and every block in it comes out as its own dome
shading.shade_region_by_light(NAME, STONE, base_color=STONE[8], light_angle=LIGHT,
                              light_z=0.55, ambient=0.34, rim=0.10, bulge=0.75,
                              tolerance=1.0, layer="wall")
shading.shade_region_by_light(NAME, FLAGS, base_color=FLAGS[8], light_angle=LIGHT,
                              light_z=0.40, ambient=0.34, rim=0.08, bulge=0.6,
                              tolerance=1.0, layer="floor")

# 3. rubble, before the falloff, so a pebble in the far corner is as dim as the floor
for lump in RUBBLE:
    flat(lump & floor_blocks, FLAGS[10], "floor")
    flat({(x, y + 1) for x, y in lump} & floor_blocks, FLAGS[3], "floor")

# 4. the wall's falloff
print()
print("falloff (one rectangle per course per zone)")
runs = falloff_runs(wall_rects + skirt_rects, 34, 62)
for step, x, y, w, h in runs:
    # Three steps a zone on a thirteen-step ramp. At one step on nine the probe below
    # still passed and the picture still looked evenly lit, which is a measurement
    # satisfied by something nobody can see; at three on nine the far blocks bottomed
    # out and the far wall became one tile repeated. The ramp is longer now, so the
    # stride can be too, though capped at four: six left the far corner reading as
    # black with masonry somewhere inside it.
    shading.shift_along_ramp(NAME, STONE, -min(3 * step, 4), x=x, y=y, width=w,
                             height=h, tolerance=8.0, layer="wall")
variants = [r for r in wall_rects + skirt_rects if is_variant(r)]
for x, y, w, h in variants:
    shading.shift_along_ramp(NAME, STONE, -1, x=x, y=y, width=w, height=h,
                             tolerance=8.0, layer="wall")
print(f"  wall   {len(wall_rects + skirt_rects):>2} blocks, {len(runs):>2} runs darkened, "
      f"{len(variants)} blocks off-value")

# 5. the horizon, as a value progression rather than as a bar. Wall blocks, then a shorter
#    and darker skirting course, then the floor, which takes its own crease at the wall
#    line inside the pass below rather than from four full-width rows.
shading.shift_along_ramp(NAME, STONE, -2, x=0, y=SKIRT_TOP, width=W,
                         height=FLOOR_TOP - SKIRT_TOP, tolerance=8.0, layer="wall")

# 5b. the floor, lit per pixel
lit, off_ramp = flagstone_light(floor_stones, mortar_sources(floor_stones, floor_mortar))
print(f"  floor  {lit} pixels moved along their own ramp, {off_ramp} off-ramp "
      f"and left alone")

# 5c. the torchlight, as the wall brightened up its own ramp inside a circle on the flame
#     rather than as a halo painted over it. `glow` grows rings outward from the subject's
#     silhouette, so a tall narrow flame gave a tall narrow egg with a hard elliptical
#     boundary, and it painted at full opacity, so inside it the mortar joints and the block
#     shading disappeared into a smooth beige oval. Light brightens a surface. It does not
#     erase it, and that was the clearest tell that the glow was sitting on top of the
#     picture rather than in it.
#
#     Every pixel here is already an exact ramp entry, so lifting one is a table lookup:
#     find its step, move up by however much the distance from the flame allows, clamp. The
#     joints lift too, which is why the masonry survives. One read and one write a surface.
#
#     This is the pool every frame shares, and it runs before the frames are duplicated
#     because the sconce's own cast shadow is measured off the lit wall and has to agree
#     with it. What the flicker moves is a few steps either side of this, per frame, below.
POOL_RADIUS, POOL_GAIN = 34, 5


def light_pool(layer, band_ramp, rows_from, rows_to):
    # Only the pool's own bounding box is read, not the layer. `get_pixels` caps a region at
    # 4096 pixels, which the whole wall is not, and reading rows the light never reaches
    # would be wasted either way.
    index = {colour.lower(): step for step, colour in enumerate(band_ramp)}
    x0, x1 = max(TORCH_X - POOL_RADIUS, 0), min(TORCH_X + POOL_RADIUS + 1, W)
    y0 = max(TORCH_Y - POOL_RADIUS, rows_from)
    y1 = min(TORCH_Y + POOL_RADIUS + 1, rows_to)
    if y1 <= y0:
        return 0, 0
    grid = inspect.get_pixels(NAME, x0, y0, x1 - x0, y1 - y0, layer=layer)["pixels"]
    lifted, skipped = [], 0
    for row, line in enumerate(grid):
        y = y0 + row
        for column, pixel in enumerate(line):
            x = x0 + column
            reach = ((x - TORCH_X) ** 2 + (y - TORCH_Y) ** 2) ** 0.5
            if reach >= POOL_RADIUS:
                continue
            step = index.get(pixel[:7].lower())
            if step is None:
                skipped += 1
                continue
            lift = round(POOL_GAIN * (1.0 - reach / POOL_RADIUS) ** 2)
            target = min(step + lift, len(band_ramp) - 1)
            if target != step:
                lifted.append({"x": x, "y": y, "color": band_ramp[target]})
    if lifted:
        drawing.draw_pixels(NAME, lifted, layer=layer)
    return len(lifted), skipped


print()
#     The wall only. The torch is high on it and the flagstones start 26 pixels below the
#     flame, which this falloff puts at a lift of zero: calling it on the floor reported
#     "lifted 0 pixels", which is a line of output that looks like a bug and is not one.
#     The floor gets its own pass, with its own reach, in 5b.
moved, missed = light_pool("wall", STONE, 0, FLOOR_TOP)
print(f"light pool: lifted {moved} wall pixels up their own ramp, "
      f"{missed} off-ramp and left alone")

# Linear rather than quadratic, which the baked pool above is, and reaching further than
# it. A quadratic breath moves only the few pixels nearest the flame by a whole step and
# rounds the rest to nothing, so it reproduces the fault it is here to fix: measured at a
# reach of 34, one step of quadratic breath carries 10 pixels out. Linear carries a step to
# half the reach, so the smallest breath in the table, one step, moves a 52 pixel width of
# wall and the largest moves all of it. At a reach of 40 that smallest breath measured a 39
# pixel box, which is narrower than the halo and would have left the quietest frame looking
# like the decal this replaced.
#
# 52 is also as far as this can go in one call: the read is 75 by 43 at the widest lean and
# `get_pixels` caps a region at 4096 pixels.
BREATH_REACH = 52.0


def pool_breath(frame, centre_x, steps):
    """Gutter the wall's light pool by a few steps, for one frame of the flicker.

    The pool leans with the flame as well as dimming with it: `centre_x` comes from that
    frame's own lean, so no two frames put the brightest column in the same place even
    where two of them give up the same number of steps.
    """
    if not steps:
        return 0
    index = {colour.lower(): step for step, colour in enumerate(STONE)}
    span = int(BREATH_REACH)
    x0, x1 = max(centre_x - span, 0), min(centre_x + span + 1, W)
    grid = inspect.get_pixels(NAME, x0, 0, x1 - x0, FLOOR_TOP, layer="wall",
                              frame=frame)["pixels"]
    write = []
    for y, line in enumerate(grid):
        for column, pixel in enumerate(line):
            x = x0 + column
            reach = ((x - centre_x) ** 2 + (y - TORCH_Y) ** 2) ** 0.5
            if reach >= BREATH_REACH:
                continue
            step = index.get(pixel[:7].lower())
            if step is None:
                continue
            target = min(max(step + round(steps * (1.0 - reach / BREATH_REACH)), 0),
                         len(STONE) - 1)
            if target != step:
                write.append({"x": x, "y": y, "color": STONE[target]})
    if write:
        drawing.draw_pixels(NAME, write, layer="wall", frame=frame)
    return len(write)


# 6. the chest: wood, two straps and a lock, each its own material
chest = rows(CHEST_X, LID) | rows(CHEST_X, SEAM) | rows(CHEST_X, BODY) | rows(CHEST_X, TRIM)
straps = rows(CHEST_X, STRAPS) & chest
lock = rows(CHEST_X, LOCK)
flat(chest, CHESTWOOD[5], "chest")
flat(straps | lock, BRASS[5], "chest")
shading.shade_region_by_light(NAME, CHESTWOOD, base_color=CHESTWOOD[5], light_angle=LIGHT,
                              light_z=0.5, ambient=0.26, rim=0.14, tolerance=1.0,
                              layer="chest")
# Before the brass is shaded, not after, and that ordering is the whole call. A contact
# shadow needs an occluder to measure from, and `BRASS[5]` is the strap's flat fill: run
# after the brass pass, only 3 pixels of the whole chest were still that colour and the
# call did nothing visible. The wood is already shaded by this point, which is what the
# darkening is applied to, so nothing is lost by going first.
contact = shading.contact_shadow(NAME, CHESTWOOD, occluder_color=BRASS[5], radius=1,
                                 depth=2, tolerance=12.0, layer="chest")
assert contact["pixels_written"], "the contact shadow found no occluder to measure from"
print(f"chest: contact shadow darkened {contact['pixels_written']} wood pixels")
# `BRASS[:7]`, not the whole ramp. On two-pixel-wide vertical strips the full ramp puts the
# lit column at `#efd2b6`, which is nearly white, so the least important detail on the
# chest became the most contrasted thing on it. Reserving the top two steps keeps it brass.
shading.shade_region_by_light(NAME, BRASS[:7], base_color=BRASS[5], light_angle=LIGHT,
                              light_z=0.5, ambient=0.28, rim=0.2, bulge=0.7,
                              tolerance=1.0, layer="chest")
# The lid's seam and the body's lit lip, both after the furniture so neither is drawn over.
flat(rows(CHEST_X, SEAM) - straps - lock, CHESTWOOD[1], "chest")
flat(rows(CHEST_X, LIP) - straps - lock, CHESTWOOD[7], "chest")
# `connectivity=8`, as everything else in the showcase uses. At 4 the lid's chamfered
# corners had their diagonal neighbours left unpainted, so the outline opened at each one.
effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside",
                    layer="chest")

# 7. the shadow the chest throws, on the floor and clipped to it. `ground_layer` is what
#    stops a shadow running off the flagstones and hanging in the air. The ramp is the
#    floor's and not the chest's, because a shadow is a darkening of what it lies on, and
#    it starts at `FLAGS[2]` rather than `FLAGS[0]` so the core reads as dark and not as a
#    hole cut in the floor. After the floor's own pass, so the shadow is a darkening of the
#    flagstones as they finally are rather than as they were drawn.
effects.cast_shadow(NAME, "chest", FLAGS[2:10], light_angle=LIGHT, light_height=0.42,
                    ground_layer="floor", softness=2, new_layer="chest shadow")

# 7b. and the shadow re-read off the flagstones it lies on, which is the rest of why the
#     foreground was flat. `cast_shadow` gets the hard part right: the projection away from
#     the light, the foreshortening, the rings of softness and the clip to the ground layer
#     that stops a shadow hanging in the air. What it cannot do is read the ground. Its core
#     is `ramp[0]` whatever is underneath, so it arrives as one flat value, and measured on
#     the previous draft that single `FLAGS[2]` ran 50 unbroken pixels across row 68 and
#     covered 64.4 percent of the near-right foreground: the flattest thing in the picture
#     was not the floor at all, it was the shadow lying on it.
#
#     The floor underneath has mortar, a falloff and chipping in it, and a shadow showing
#     none of that is the same decal the halo used to be. So the shape is kept and the
#     values are replaced: every shadow pixel becomes the flagstone under it, moved down the
#     floor's own ramp by how deep in the shadow that pixel was. Three steps at the core and
#     one at the outer ring of softness, so the penumbra still reads as a penumbra.
SHADOW_CORE = 3


def shadow_on_floor():
    """Make the chest's shadow a darkening of the floor rather than a shape laid over it."""
    index = {colour.lower(): step for step, colour in enumerate(FLAGS)}
    read = {name: inspect.get_pixels(NAME, 0, FLOOR_TOP, W, H - FLOOR_TOP,
                                     layer=name)["pixels"]
            for name in ("chest shadow", "floor")}
    # Keyed on the ramp step the shadow was painted at, which is how deep in it a pixel is:
    # `cast_shadow` puts its core on the darkest colour it was given and each ring of
    # softness one step lighter, so the step is the depth and nothing has to be guessed.
    depth = {}
    for row, line in enumerate(read["chest shadow"]):
        for x, pixel in enumerate(line):
            if pixel[7:9].lower() == "00":
                continue
            step = index.get(pixel[:7].lower())
            if step is not None:
                depth[(x, FLOOR_TOP + row)] = step
    if not depth:
        return 0
    core = min(depth.values())
    write = []
    for (x, y), step in sorted(depth.items()):
        under = index.get(read["floor"][y - FLOOR_TOP][x][:7].lower())
        if under is None:
            continue
        # A share of the light rather than a fixed number of steps, which matters most
        # where there is least light to take: three flat steps off a far corner already
        # down at step 2 crushes it to the bottom of the ramp, and that is how 31.5
        # percent of the near-right foreground came back as one near-black value even
        # after the shadow started reading the floor. Scaled by what is actually there,
        # and never taking the surface to its last step, a shadow stays a shadow instead
        # of becoming a hole cut in the floor.
        drop = max(1, min(SHADOW_CORE - (step - core), under // 2))
        write.append({"x": x, "y": y, "color": FLAGS[max(under - drop, 1)]})
    if write:
        drawing.draw_pixels(NAME, write, layer="chest shadow")
    return len(write)


print(f"chest shadow: {shadow_on_floor()} pixels re-read off the flagstones under them")

# 8. the sconce, then one copy of the whole room per frame of the flicker
flat(rows(TORCH_X, CUP) | rows(TORCH_X, PLATE), BRASS[5], "sconce")
flat(rows(TORCH_X, STEM), BRASS[3], "sconce")
shading.shade_region_by_light(NAME, BRASS, base_color=BRASS[5], light_angle=LIGHT,
                              light_z=0.5, ambient=0.3, rim=0.24, tolerance=1.0,
                              layer="sconce")
effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside",
                    layer="sconce")
# The shadow the sconce throws on the wall it is bolted to. Every other object in this
# scene that touches a surface had one; the one object literally attached to the wall did
# not, and an object with no shadow on the surface behind it reads as a sticker. The light
# is the flame directly above it, so `light_angle=90` and a high `light_height`: straight
# down and short.
effects.cast_shadow(NAME, "sconce", STONE[1:8], light_angle=90.0, light_height=0.72,
                    ground_layer="wall", softness=1, new_layer="sconce shadow")
for _ in range(len(FLICKER) - 1):
    frames.duplicate_frame(NAME, 1)

# 9. the flame, three nested shapes per frame, its halo, and the room guttering with it.
#    One `glow` layer carrying a cel per frame, which it could not do when this scene was
#    first drawn: the refusal that stops two halos compositing into one cel used to be
#    enforced on the layer, and a layer spans every frame, so a four-frame flicker meant
#    `glow 1` through `glow 4`, each with a single cel and empty on the other three. That is
#    issue #185, and this is what it was filed from.
#
#    `tolerance=4.0` on the two metal shifts, which is tight for a reason rather than tidy.
#    Every brass and wood pixel is an exact ramp entry so it matches at a distance of zero,
#    while the outline `#140f1e` sits 8.9 from the nearest `CHESTWOOD` step and `BRASS[0]`
#    sits 7.4 from one. At the default tolerance of 48 the lid's breath would take the
#    chest's outline and its straps with it.
print()
print("flame     rows  lean   ms  gives up  wall px  metal  halo")
for frame, (profile, lean, ms, breath) in enumerate(FLICKER, start=1):
    body = flame_points(profile, lean)
    for points, colour in ((body, FLAME[4]), (erode(body, 1), FLAME[6]),
                           (erode(body, 2), FLAME[8])):
        flat(points, colour, "flame", frame=frame)
    halo = effects.glow(NAME, HALO, radius=3, falloff="quadratic", dither_edge=True,
                        layer="flame", frame=frame, new_layer="halo")
    breathed = pool_breath(frame, TORCH_X + round(lean * 10), breath)
    # Capped at two steps where the wall takes three. The sconce is a 13 pixel fitting and
    # the lid a 27 pixel panel, and a three-step swing on either reads as the object
    # changing colour rather than as the light on it changing.
    metal = max(breath, -2)
    if metal:
        shading.shift_along_ramp(NAME, BRASS, metal, x=TORCH_X - 7, y=23, width=15,
                                 height=16, tolerance=4.0, layer="sconce", frame=frame)
        # Rows 43 to 50: the lid, and not row 51. The seam is `CHESTWOOD[1]` and the
        # measurement below counts the pixels still exactly that colour, so a lid that
        # breathed over its own seam would be reported as a lid with no seam.
        shading.shift_along_ramp(NAME, CHESTWOOD, metal, x=CHEST_X - 16, y=FLOOR_TOP,
                                 width=33, height=8, tolerance=4.0, layer="chest",
                                 frame=frame)
    frames.set_frame_duration(NAME, frame, ms)
    print(f"  frame {frame}  {len(profile):>3}  {lean:+.2f}  {ms:>3}  {breath:>8}  "
          f"{breathed:>7}  {metal:>5}  "
          f"{halo['glow_pixels']} px in {len(halo['rings'])} rings")

stack = [lyr["name"] for lyr in inspect.get_sprite_info(NAME)["layers"]]
print(f"layers: {len(stack)}, one halo rather than one a frame: {stack}")
assert stack.count("halo") == 1, stack

# ------------------------------------------------------------- what the picture claims
# Two numbers, because neither is something the eye can check. The falloff has to actually
# darken: one flagstone course has to be lighter near the torch than across the room, or
# the zones are decoration. And the flame has to move: a flicker whose frames differ only
# in duration is a still image with a slow shutter.
# Variety, which is the thing the old falloff probe passed while failing. Two blocks count
# as the same pattern when their pixels rank the same, whatever their absolute brightness.
patterns = {}
for rx, ry, rw, rh in wall_rects:
    cell = [inspect.get_pixels(NAME, rx, ry, rw, rh, layer="wall")["pixels"]]
    flatten = [c[:7].lower() for grid in cell for line in grid for c in line]
    order = sorted(set(flatten))
    patterns.setdefault(tuple(order.index(c) for c in flatten), []).append((rx, ry))
    assert len(order) >= 4, f"the block at {(rx, ry)} has {len(order)} tones left in it"
unique = sum(1 for blocks in patterns.values() if len(blocks) == 1)
print()
print(f"wall: {len(wall_rects)} blocks, {len(patterns)} distinct shading patterns, "
      f"{unique} of them unique, every block at 4 tones or more")
assert unique >= 0.75 * len(wall_rects), (
    f"only {unique} of {len(wall_rects)} blocks are shaded unlike every other")

# The floor's perspective, measured off the geometry rather than taken from the plan. The
# courses have to grow taller down the frame (#196) and the stones have to grow wider with
# them, which under the previous draft was two hand-typed tuples and is now a consequence
# of where the vanishing point is.
planned = list(FLOOR_COURSES)
assert planned == sorted(planned), "the floor's courses do not grow taller down the frame"
spans = []
for band, (top, bottom) in enumerate(course_rows()):
    edges = ray_edges(band, (top + bottom) // 2)
    spans.append(round(statistics.mean(
        right - left for left, right in itertools.pairwise(edges))))
print(f"floor: course heights {planned}, stone widths {spans}, down the frame")
assert spans == sorted(spans), f"the floor's stones do not widen down the frame: {spans}"

# No row of the floor is one continuous value across the frame. This is the measurement
# that says "floor" rather than "wall lying down": the previous draft's course joints were
# single-colour rules 60, 60 and 56 pixels long at x=0, on rows 48, 55 and 63.
#
# On the composite, not on the floor layer, and that distinction caught a real fault. Read
# per layer, the flagstones came back at a worst run of 15 pixels while the picture a reader
# sees still had 54, because the chest's shadow lies on top of them and was flat. A
# measurement scoped to the layer you happened to edit will confirm the edit and miss the
# frame. The chest's own outline is excluded: an outline is a continuous line on purpose,
# and this is a question about surfaces.
floor_grid = inspect.get_pixels(NAME, 0, FLOOR_TOP, W, H - FLOOR_TOP)["pixels"]
longest = []
for row, line in enumerate(floor_grid):
    best = run = 0
    for column in range(W):
        run = run + 1 if column and line[column] == line[column - 1] else 1
        if line[column][:7].lower() != OUTLINE.lower():
            best = max(best, run)
    longest.append((best, FLOOR_TOP + row))
worst, worst_row = max(longest)
print()
print(f"floor: the longest run of one colour in any of its {len(floor_grid)} rows is "
      f"{worst} px, on row {worst_row}; it was 60 px on row 48 and 54 px on row 66")
assert worst <= 22, f"row {worst_row} is {worst} consecutive pixels of one value"

# And the foreground is not the flattest part of it, which is what it used to be: rows
# 64..71 from x=60 rightward were 64.4 percent one colour across 9 of them.
near = [c for line in floor_grid[-8:] for c in line[60:]]
share = max(near.count(c) for c in set(near)) / len(near)
print(f"foreground rows {H - 8}..{H - 1} from x=60: {len(set(near))} colours, the "
      f"most-used one {share:.1%} of them; it was 9 colours and 64.4%")
assert share < 0.35, f"the nearest flagstones are {share:.1%} a single colour"

# Both greys hold a chroma a reader can see. `assess_sprite` reports this off the declared
# ramp, and the two numbers that matter are the saturation floor over the ramp's interior
# and how many of those steps fall under the chroma at which hue is visible at all. The
# stone ramp used to measure 0.077 and ten; the floor's 0.056 and eleven.
print()
for label, band_ramp in (("stone", STONE), ("flags", FLAGS)):
    chroma = inspect.assess_sprite(NAME, ramp=band_ramp)["metrics"]["ramp_chroma"]
    print(f"{label} ramp: {chroma['hue_span']:.0f} deg of hue, saturation floor "
          f"{chroma['sat_floor']:.3f}, {chroma['grey_steps']} grey steps")
    assert chroma["grey_steps"] == 0, f"{label} has {chroma['grey_steps']} grey steps"
    assert chroma["sat_floor"] > 0.15, f"{label} floors at {chroma['sat_floor']}"
# And the stone's lit end stays under the flame's, by enough that the flame still owns the
# top of the picture. It used to reach 0.894 against the core's 0.980.
stone_top, flame_core = lightness(STONE[-1]), lightness(FLAME[-1])
print(f"lit stone tops out at {stone_top:.3f} lightness, flame core at "
      f"{flame_core:.3f}, halo's outer ring at {lightness(HALO[0]):.3f}")
assert stone_top < flame_core - 0.12, "the stone's lit end is not capped short of the flame"
assert lightness(HALO[0]) > stone_top, "the halo's outer ring darkens the wall it lies on"

# The falloff, probed on the floor's own layer rather than on the composite, so the chest
# and the shadow it throws cannot stand in for the light. Seven pixels a side and the
# median of each, because a single pixel can be mortar or a chip and prove nothing.
NEAR, FAR, PROBE_Y = 14, 92, 56
steps = [c.lower() for c in FLAGS]


def probe(x):
    read = inspect.get_pixels(NAME, x, PROBE_Y, 7, 1, layer="floor")["pixels"][0]
    return statistics.median(steps.index(c[:7].lower()) for c in read)


near_step, far_step = probe(NEAR), probe(FAR)
print()
print(f"floor row {PROBE_Y}: median step {near_step} at x={NEAR}..{NEAR + 6}, "
      f"{far_step} at x={FAR}..{FAR + 6}")
assert near_step > far_step, "the falloff darkened nothing"

seam_row = [x for x in range(CHEST_X - 14, CHEST_X + 15)
            if inspect.get_pixels(NAME, x, 51, 1, 1)["pixels"][0][0][:7].lower()
            == CHESTWOOD[1].lower()]
print(f"lid seam: {len(seam_row)} of 27 pixels on row 51, in "
      f"{sum(1 for i, x in enumerate(seam_row) if i == 0 or x != seam_row[i - 1] + 1)} runs")
assert len(seam_row) >= 18, f"the lid seam is {len(seam_row)} pixels, too broken to read"

shapes = {frozenset(flame_points(profile, lean)) for profile, lean, _ms, _b in FLICKER}
assert len(shapes) == len(FLICKER), "two frames share a flame silhouette"
print(f"flame: {len(FLICKER)} frames, {len(shapes)} silhouettes, "
      f"{len({ms for _p, _l, ms, _b in FLICKER})} durations")

# The flicker moves the room and not just the flame. Measured per layer, because the flame
# and its halo have layers of their own: a diff of the *wall* between two frames cannot see
# the flame at all, so what it counts is the light on the masonry. On the previous draft
# every one of these was zero, and the whole four-frame difference was 183 pixels inside a
# 17x17 box, 3.6 percent of the canvas.
print()
print("frame vs 1   wall px   sconce px   chest px   box the wall changed in")
moved_metal = []
for frame in range(2, len(FLICKER) + 1):
    counts = {}
    for layer in ("wall", "sconce", "chest"):
        counts[layer] = inspect.diff_sprites(
            NAME, frame=1, other_frame=frame, layer=layer)["metrics"]
    box = counts["wall"]["change_box"]
    if counts["sconce"]["changed_pixels"]:
        moved_metal.append(frame)
    print(f"  frame {frame}     {counts['wall']['changed_pixels']:>7}   "
          f"{counts['sconce']['changed_pixels']:>9}   "
          f"{counts['chest']['changed_pixels']:>8}   "
          f"{box['width']}x{box['height']} at ({box['x']}, {box['y']})")
    assert counts["wall"]["changed_pixels"] >= 300, (
        f"frame {frame} differs from frame 1 by "
        f"{counts['wall']['changed_pixels']} wall pixels, so the pool is bolted down")
    # Wider than the flame, which is the whole point: the flame's own box is 17 pixels
    # across and the light it throws has to reach further than the thing throwing it.
    assert box["width"] >= 40, (
        f"frame {frame} only changes the wall inside a {box['width']}x{box['height']} "
        "box, which is a decal rather than a room")
assert len(moved_metal) >= 2, f"the sconce's brass only moves on frames {moved_metal}"

still = export.export_png(NAME, "dungeon.png", frame=1, scale=5, overwrite=True)
loop = export.export_gif(NAME, "dungeon.gif", scale=4, overwrite=True)
print()
print("still:", still["output"], pathlib.Path(still["output"]).stat().st_size, "bytes")
print("loop: ", loop["output"], pathlib.Path(loop["output"]).stat().st_size, "bytes")
