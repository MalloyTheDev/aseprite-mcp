"""Build the dungeon showcase: one lit scene, and the same scene as a flickering loop.

The other showcase pieces are each about one tool. This one is about what the tools do
together, because that is the thing a sprite-by-sprite gallery cannot show: masonry whose
every block has its own form, a light that falls off across the room, a chest that throws a
shadow onto the floor and not into the air, and a flame whose halo is made of palette
entries rather than of alpha.

Three ideas carry it.

**One shading pass per material, not per object.** `shade_region_by_light` builds a
distance field over everything matching one base colour, and a field over a mask with
forty disconnected parts describes each part on its own. So the whole wall, every block of
it, takes its form from a single call and comes out domed instead of flat. One more call
does the floor. The joints between the blocks are what make this work: they are why the
mask is forty components and not one slab.

**The falloff is zones stepped down a ramp, not a radial light.** No tool here lights a
scene from a point, and faking one by blending would put every pixel between palette
entries. `shift_along_ramp` moves a rectangle one or two steps down the surface's own ramp
instead, which is how a pixel artist builds a falloff: a few zones, every pixel still
exactly a ramp colour, and the seams hidden. Hiding them is the whole trick, and it is why
this is a rectangle per course rather than one band across the room. The only cut that does
not show is one along a joint, and because the courses are staggered no single column is a
joint on all of them. Per course, every cut is.

**The flicker is four frames with four different durations.** `set_all_frame_durations`
would give an even pulse, and an even pulse reads as a machine rather than as fire. The
flame also leans a different way and stands a different height on each frame, because a
flame that only changes brightness reads as a lamp with a loose wire.
"""
import pathlib

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
# The floor in perspective: each course taller and its stones wider than the one above.
# Flat equal courses read as a second wall lying down, which is what the horizon bar was
# added to disguise.
FLOOR_PLAN = ((5, 17), (6, 21), (7, 26), (8, 31))
OUTLINE = "#140f1e"
# Everything in the room is lit by the torch, so the key comes from where the torch is.
LIGHT = 155.0
TORCH_X, TORCH_Y = 20, 17


def ramp(base, *, hue=-18.0, sat=-20.0, light=0.80, steps=9):
    colors = palette.generate_ramp(base, steps=steps, hue_shift=hue,
                                   saturation_shift=sat, light_range=light)["colors"]
    assert len(set(colors)) == steps, f"{base} at light_range={light} clips: {colors}"
    return colors


# Thirteen steps, not nine. `shift_along_ramp` clamps at the ends, so pushing a block three
# steps down a nine-step ramp collapsed its darks together: 8 of 24 sampled blocks came out
# pixel for pixel identical at 6 tones, all in the dim zone, and the far wall was one tile
# repeated. A longer ramp leaves a darkened block somewhere to go.
STONE = ramp("#6e7183", sat=-26.0, light=0.84, steps=13)
FLAGS = ramp("#665a61", hue=-12.0, sat=-18.0, light=0.74, steps=13)
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
# light on it, which is what the outside of a pool of light actually is.
HALO = palette.ramp_between("#9a8f90", FLAME[7], steps=5)["colors"]


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


def floor_courses(top, bottom, plan):
    """Courses that grow taller, of stones that grow wider, going down the frame."""
    rects, y0 = [], top
    for course, (height, width) in enumerate(plan):
        if y0 > bottom:
            break
        rects += course_blocks(y0, height, (width,), course, top, bottom)
        y0 += height + 1
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


# --------------------------------------------------------------------------- the sconce
CUP = {24: [(-4, 4)], 25: [(-5, 5)], 26: [(-5, 5)], 27: [(-4, 4)], 28: [(-3, 3)]}
STEM = {y: [(-1, 1)] for y in range(29, 34)}
PLATE = {34: [(-3, 3)], 35: [(-4, 4)], 36: [(-4, 4)], 37: [(-3, 3)]}

# --------------------------------------------------------------------------- the flame
# Derived rather than typed out, which is the opposite of the item sheet's rule and for the
# opposite reason: a heart has a notch a formula gets wrong, and a flame has no feature at
# all a reader could catch being a pixel off. The profile is half-widths from the tip down,
# and each frame takes a different length and a different lean.
FLAME_BASE_Y = 23
PROFILE = [0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 3, 3, 2]
FLICKER = [
    (PROFILE, 0.00, 90),
    (PROFILE[2:], 0.18, 70),
    ([0, 0, *PROFILE[1:]], -0.14, 110),
    (PROFILE[1:-1], 0.10, 80),
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
floor_rects = floor_courses(FLOOR_TOP, H - 1, FLOOR_PLAN)
wall_blocks = points_of(wall_rects) | points_of(skirt_rects)
floor_blocks = points_of(floor_rects)
flat(wall_blocks, STONE[8], "wall")
flat({(x, y) for y in range(FLOOR_TOP) for x in range(W)} - wall_blocks, STONE[2], "wall")
flat(floor_blocks, FLAGS[8], "floor")
flat({(x, y) for y in range(FLOOR_TOP, H) for x in range(W)} - floor_blocks,
     FLAGS[2], "floor")

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

# 4. the falloff
print("falloff (one rectangle per course per zone)")
for layer, band_ramp, rects, near, mid in (
        ("wall", STONE, wall_rects + skirt_rects, 34, 62),
        ("floor", FLAGS, floor_rects, 46, 74)):
    runs = falloff_runs(rects, near, mid)
    for step, x, y, w, h in runs:
        # Three steps a zone on a thirteen-step ramp. At one step on nine the probe below
        # still passed and the picture still looked evenly lit, which is a measurement
        # satisfied by something nobody can see; at three on nine the far blocks bottomed
        # out and the far wall became one tile repeated. The ramp is longer now, so the
        # stride can be too, though capped at four: six left the far corner reading as
        # black with masonry somewhere inside it.
        shading.shift_along_ramp(NAME, band_ramp, -min(3 * step, 4), x=x, y=y, width=w,
                                 height=h, tolerance=8.0, layer=layer)
    variants = [r for r in rects if is_variant(r)]
    for x, y, w, h in variants:
        shading.shift_along_ramp(NAME, band_ramp, -1, x=x, y=y, width=w, height=h,
                                 tolerance=8.0, layer=layer)
    print(f"  {layer:<6} {len(rects):>2} blocks, {len(runs):>2} runs darkened, "
          f"{len(variants)} blocks off-value")

# 5. the horizon, as a value progression rather than as a bar. Wall blocks, then a shorter
#    and darker skirting course, then the floor darkest where it meets the wall and
#    lightening down the frame. Three rows of the floor stepped down its own ramp does that
#    without a single flat full-width run in it: a shift keeps the stones and their grout
#    distinct, which a painted row cannot.
shading.shift_along_ramp(NAME, STONE, -2, x=0, y=SKIRT_TOP, width=W,
                         height=FLOOR_TOP - SKIRT_TOP, tolerance=8.0, layer="wall")
for offset, drop in ((0, 4), (1, 3), (2, 2), (3, 1)):
    shading.shift_along_ramp(NAME, FLAGS, -drop, x=0, y=FLOOR_TOP + offset, width=W,
                             height=1, tolerance=8.0, layer="floor")

# 5b. the torchlight, as the wall brightened up its own ramp inside a circle on the flame
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
moved, missed = light_pool("wall", STONE, 0, FLOOR_TOP)
print(f"light pool: lifted {moved} wall pixels up their own ramp, "
      f"{missed} off-ramp and left alone")

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
#    hole cut in the floor.
effects.cast_shadow(NAME, "chest", FLAGS[2:10], light_angle=LIGHT, light_height=0.42,
                    ground_layer="floor", softness=2, new_layer="chest shadow")

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

# 9. the flame, three nested shapes per frame, and its halo. `glow` refuses to write into a
#    layer that already exists, so a four-frame flicker is four glow layers with one cel
#    each rather than one layer written four times: two halos composited into one cel would
#    be a picture neither call describes.
print()
print("flame     rows  lean   ms  halo")
for frame, (profile, lean, ms) in enumerate(FLICKER, start=1):
    body = flame_points(profile, lean)
    for points, colour in ((body, FLAME[4]), (erode(body, 1), FLAME[6]),
                           (erode(body, 2), FLAME[8])):
        flat(points, colour, "flame", frame=frame)
    halo = effects.glow(NAME, HALO, radius=3, falloff="quadratic", dither_edge=True,
                        layer="flame", frame=frame, new_layer=f"glow {frame}")
    frames.set_frame_duration(NAME, frame, ms)
    print(f"  frame {frame}  {len(profile):>3}  {lean:+.2f}  {ms:>3}  "
          f"{halo['glow_pixels']} pixels in {len(halo['rings'])} rings")

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

heights = [h for _x, _y, _w, h in floor_courses(FLOOR_TOP, H - 1, FLOOR_PLAN)]
planned = [h for h, _w in FLOOR_PLAN]
assert planned == sorted(planned), "the floor's courses do not grow taller down the frame"
print(f"floor: course heights {planned}, stone widths "
      f"{[w for _h, w in FLOOR_PLAN]}, down the frame")

NEAR, FAR, PROBE_Y = 20, 95, 56
steps = [c.lower() for c in FLAGS]
near = inspect.get_pixels(NAME, NEAR, PROBE_Y, 1, 1)["pixels"][0][0][:7].lower()
far = inspect.get_pixels(NAME, FAR, PROBE_Y, 1, 1)["pixels"][0][0][:7].lower()
print()
print(f"floor row {PROBE_Y}: step {steps.index(near)} at x={NEAR}, "
      f"step {steps.index(far)} at x={FAR}")
assert steps.index(near) > steps.index(far), "the falloff darkened nothing"

seam_row = [x for x in range(CHEST_X - 14, CHEST_X + 15)
            if inspect.get_pixels(NAME, x, 51, 1, 1)["pixels"][0][0][:7].lower()
            == CHESTWOOD[1].lower()]
print(f"lid seam: {len(seam_row)} of 27 pixels on row 51, in "
      f"{sum(1 for i, x in enumerate(seam_row) if i == 0 or x != seam_row[i - 1] + 1)} runs")
assert len(seam_row) >= 18, f"the lid seam is {len(seam_row)} pixels, too broken to read"

shapes = {frozenset(flame_points(profile, lean)) for profile, lean, _ms in FLICKER}
assert len(shapes) == len(FLICKER), "two frames share a flame silhouette"
print(f"flame: {len(FLICKER)} frames, {len(shapes)} silhouettes, "
      f"{len({ms for _p, _l, ms in FLICKER})} durations")

still = export.export_png(NAME, "dungeon.png", frame=1, scale=5, overwrite=True)
loop = export.export_gif(NAME, "dungeon.gif", scale=4, overwrite=True)
print()
print("still:", still["output"])
print("loop: ", loop["output"], pathlib.Path(loop["output"]).stat().st_size, "bytes")
