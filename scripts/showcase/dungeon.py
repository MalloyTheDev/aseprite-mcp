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
WALL_BOTTOM = 46
OUTLINE = "#140f1e"
# Everything in the room is lit by the torch, so the key comes from where the torch is.
LIGHT = 155.0
TORCH_X, TORCH_Y = 20, 17


def ramp(base, *, hue=-18.0, sat=-20.0, light=0.80, steps=9):
    colors = palette.generate_ramp(base, steps=steps, hue_shift=hue,
                                   saturation_shift=sat, light_range=light)["colors"]
    assert len(set(colors)) == steps, f"{base} at light_range={light} clips: {colors}"
    return colors


STONE = ramp("#6e7183", sat=-26.0, light=0.84)
FLAGS = ramp("#4e4348", hue=-12.0, sat=-18.0, light=0.74)
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
HALO = palette.ramp_between("#8d8285", FLAME[7], steps=7)["colors"]


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


def courses(top, bottom, block_w, block_h, *, stagger):
    """Lay a wall or a floor as staggered blocks with a one-pixel joint between them."""
    rects = []
    for course, y0 in enumerate(range(top - block_h + 2, bottom + 1, block_h + 1)):
        shift = stagger if course % 2 else 0
        for x0 in range(shift - block_w, W + block_w, block_w + 1):
            left, right = max(x0, 0), min(x0 + block_w, W)
            upper, lower = max(y0, top), min(y0 + block_h, bottom + 1)
            if right > left and lower > upper:
                rects.append((left, upper, right - left, lower - upper))
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
STRAPS = {y: [(-10, -8), (8, 10)] for y in range(44, 65)}
LOCK = {y: [(-3, 3)] for y in range(49, 54)}

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
wall_rects = courses(0, WALL_BOTTOM, 17, 8, stagger=9)
floor_rects = courses(WALL_BOTTOM + 1, H - 1, 23, 7, stagger=12)
wall_blocks, floor_blocks = points_of(wall_rects), points_of(floor_rects)
flat(wall_blocks, STONE[5], "wall")
flat({(x, y) for y in range(WALL_BOTTOM + 1) for x in range(W)} - wall_blocks,
     STONE[1], "wall")
flat(floor_blocks, FLAGS[5], "floor")
flat({(x, y) for y in range(WALL_BOTTOM + 1, H) for x in range(W)} - floor_blocks,
     FLAGS[1], "floor")

# 2. one call per surface, and every block in it comes out as its own dome
shading.shade_region_by_light(NAME, STONE, base_color=STONE[5], light_angle=LIGHT,
                              light_z=0.55, ambient=0.34, rim=0.10, bulge=0.75,
                              tolerance=1.0, layer="wall")
shading.shade_region_by_light(NAME, FLAGS, base_color=FLAGS[5], light_angle=LIGHT,
                              light_z=0.40, ambient=0.34, rim=0.08, bulge=0.6,
                              tolerance=1.0, layer="floor")

# 3. rubble, before the falloff, so a pebble in the far corner is as dim as the floor
for lump in RUBBLE:
    flat(lump, FLAGS[6], "floor")
    flat({(x, y + 1) for x, y in lump} & floor_blocks, FLAGS[2], "floor")

# 4. the falloff
print("falloff (one rectangle per course per zone)")
for layer, band_ramp, rects, near, mid in (("wall", STONE, wall_rects, 34, 62),
                                           ("floor", FLAGS, floor_rects, 46, 74)):
    runs = falloff_runs(rects, near, mid)
    for step, x, y, w, h in runs:
        # Two steps a zone, not one: at one step the probe below still passed and the
        # picture still looked evenly lit, which is a measurement satisfied by something
        # nobody can see. Capped at three, because four bottomed the far floor out on
        # `FLAGS[0]` and a corner with no value left in it is not dim, it is missing.
        shading.shift_along_ramp(NAME, band_ramp, -min(2 * step, 3), x=x, y=y, width=w,
                                 height=h, tolerance=8.0, layer=layer)
    variants = [r for r in rects if is_variant(r)]
    for x, y, w, h in variants:
        shading.shift_along_ramp(NAME, band_ramp, -1, x=x, y=y, width=w, height=h,
                                 tolerance=8.0, layer=layer)
    print(f"  {layer:<6} {len(rects):>2} blocks, {len(runs):>2} runs darkened, "
          f"{len(variants)} blocks off-value")

# 5. the horizon. Two rows of near-black with one light row above them: without a hard line
#    where the wall meets the floor, two surfaces of domed grey blocks read as one wall.
flat({(x, 44) for x in range(W)}, STONE[3], "wall")
flat({(x, y) for y in (45, 46) for x in range(W)}, STONE[0], "wall")
flat({(x, 47) for x in range(W)}, FLAGS[0], "floor")
flat({(x, 48) for x in range(W)}, FLAGS[2], "floor")

# 6. the chest: wood, two straps and a lock, each its own material
chest = rows(CHEST_X, LID) | rows(CHEST_X, SEAM) | rows(CHEST_X, BODY) | rows(CHEST_X, TRIM)
straps = rows(CHEST_X, STRAPS) & chest
lock = rows(CHEST_X, LOCK)
flat(chest, CHESTWOOD[5], "chest")
flat(straps | lock, BRASS[5], "chest")
shading.shade_region_by_light(NAME, CHESTWOOD, base_color=CHESTWOOD[5], light_angle=LIGHT,
                              light_z=0.5, ambient=0.26, rim=0.14, tolerance=1.0,
                              layer="chest")
shading.shade_region_by_light(NAME, BRASS, base_color=BRASS[5], light_angle=LIGHT,
                              light_z=0.5, ambient=0.28, rim=0.2, bulge=0.7,
                              tolerance=1.0, layer="chest")
# The lid's seam, and the wood darkened where the straps stand proud of it. A contact
# shadow is the line that stops two shapes on one layer reading as one flat shape.
flat(rows(CHEST_X, SEAM) - straps - lock, CHESTWOOD[1], "chest")
shading.contact_shadow(NAME, CHESTWOOD, occluder_color=BRASS[5], radius=1, depth=2,
                       tolerance=40.0, layer="chest")
effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=4, where="outside",
                    layer="chest")

# 7. the shadow the chest throws, on the floor and clipped to it. `ground_layer` is what
#    stops a shadow running off the flagstones and hanging in the air. The ramp is the
#    floor's and not the chest's, because a shadow is a darkening of what it lies on, and
#    it starts at `FLAGS[1]` rather than `FLAGS[0]` so the core reads as dark and not as a
#    hole cut in the floor.
effects.cast_shadow(NAME, "chest", FLAGS[1:7], light_angle=LIGHT, light_height=0.42,
                    ground_layer="floor", softness=2, new_layer="chest shadow")

# 8. the sconce, then one copy of the whole room per frame of the flicker
flat(rows(TORCH_X, CUP) | rows(TORCH_X, PLATE), BRASS[5], "sconce")
flat(rows(TORCH_X, STEM), BRASS[3], "sconce")
shading.shade_region_by_light(NAME, BRASS, base_color=BRASS[5], light_angle=LIGHT,
                              light_z=0.5, ambient=0.3, rim=0.24, tolerance=1.0,
                              layer="sconce")
effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=4, where="outside",
                    layer="sconce")
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
    halo = effects.glow(NAME, HALO, radius=7, falloff="quadratic", dither_edge=True,
                        layer="flame", frame=frame, new_layer=f"glow {frame}")
    frames.set_frame_duration(NAME, frame, ms)
    print(f"  frame {frame}  {len(profile):>3}  {lean:+.2f}  {ms:>3}  "
          f"{halo['glow_pixels']} pixels in {len(halo['rings'])} rings")

# ------------------------------------------------------------- what the picture claims
# Two numbers, because neither is something the eye can check. The falloff has to actually
# darken: one flagstone course has to be lighter near the torch than across the room, or
# the zones are decoration. And the flame has to move: a flicker whose frames differ only
# in duration is a still image with a slow shutter.
NEAR, FAR, PROBE_Y = 20, 95, 52
steps = [c.lower() for c in FLAGS]
near = inspect.get_pixels(NAME, NEAR, PROBE_Y, 1, 1)["pixels"][0][0][:7].lower()
far = inspect.get_pixels(NAME, FAR, PROBE_Y, 1, 1)["pixels"][0][0][:7].lower()
print()
print(f"floor row {PROBE_Y}: step {steps.index(near)} at x={NEAR}, "
      f"step {steps.index(far)} at x={FAR}")
assert steps.index(near) > steps.index(far), "the falloff darkened nothing"

shapes = {frozenset(flame_points(profile, lean)) for profile, lean, _ms in FLICKER}
assert len(shapes) == len(FLICKER), "two frames share a flame silhouette"
print(f"flame: {len(FLICKER)} frames, {len(shapes)} silhouettes, "
      f"{len({ms for _p, _l, ms in FLICKER})} durations")

still = export.export_png(NAME, "dungeon.png", frame=1, scale=5, overwrite=True)
loop = export.export_gif(NAME, "dungeon.gif", scale=4, overwrite=True)
print()
print("still:", still["output"])
print("loop: ", loop["output"], pathlib.Path(loop["output"]).stat().st_size, "bytes")
