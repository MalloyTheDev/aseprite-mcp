"""Redraw the skeleton example: a shaded skull over hand-placed bones."""
import itertools

from aseprite_mcp.tools import drawing, effects, export, palette, shading, sprite

NAME = "skeleton.aseprite"
W = H = 32
BONE = palette.generate_ramp("#d9d3c2", steps=5, hue_shift=-18.0,
                             saturation_shift=-22.0, light_range=0.55)["colors"]
DARK = "#241f2b"


def px(points, colour):
    drawing.draw_pixels(NAME, [{"x": x, "y": y} for x, y in sorted(points)], colour)


def block(x0, y0, x1, y1):
    return {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)}


def disc(cx, cy, rx, ry):
    return {(x, y) for y in range(cy - ry, cy + ry + 1) for x in range(cx - rx, cx + rx + 1)
            if ((x - cx) / (rx + 0.5)) ** 2 + ((y - cy) / (ry + 0.5)) ** 2 <= 1.0}


def limb(points, width=1):
    """A jointed limb: straight runs between hand-placed joints, given a thickness.

    Both arms used to be the same two-pixel rectangle at the same angle, which is most of
    why this read as programmer art: a figure with two identical limbs is not standing, it
    is extruded. Joints and a thickness are what make a bone a bone.
    """
    out = set()
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            cx = round(x0 + (x1 - x0) * i / steps)
            cy = round(y0 + (y1 - y0) * i / steps)
            for dx in range(width):
                for dy in range(width):
                    out.add((cx + dx, cy + dy))
    return out


sprite.create_sprite(NAME, W, H, overwrite=True)

# The cranium and a jaw that is its own mass, so the skull reads as two bones rather than
# as an egg with holes in it.
skull = disc(16, 8, 7, 6) | block(12, 12, 20, 14)
bones = set()
bones |= block(15, 16, 17, 21)                        # spine
# Ribs curve down and out from the spine and get shorter toward the waist. Full-width
# horizontal bars at three rows read as a ladder, which is what they were.
for y, reach in ((17, 6), (20, 5)):
    for side in (-1, 1):
        bones |= limb([(16 + side * 2, y), (16 + side * reach, y + 1),
                       (16 + side * (reach - 1), y + 2)])
bones |= block(12, 22, 20, 24)                        # pelvis, so the legs attach
# One arm raised and one hanging. The asymmetry is the whole point: it is the cheapest
# thing that makes a 32-pixel figure look like it is doing something.
bones |= limb([(11, 17), (8, 13), (5, 10)], width=2)   # raised, elbow out
bones |= limb([(21, 17), (25, 21), (26, 25)], width=2)  # hanging, elbow in
bones |= limb([(13, 24), (13, 28)], width=2)           # legs, stopping short of the edge
bones |= limb([(18, 24), (18, 28)], width=2)
bones |= block(10, 29, 15, 30) | block(17, 29, 22, 30)  # feet

px(bones, BONE[2])
px(skull, BONE[3])
shading.shade_region_by_light(NAME, BONE, base_color=BONE[3], light_angle=125,
                              light_z=0.6, ambient=0.36, rim=0.15)
# Thin bones have no interior to shade, so the light goes on by hand: top row lit,
# bottom row in shadow.
top = {(x, y) for x, y in bones if (x, y - 1) not in bones}
bottom = {(x, y) for x, y in bones if (x, y + 1) not in bones}
px(top, BONE[3])
px(bottom, BONE[1])

# The features have to stay *separate* dark masses with lit bone between them. Put the
# jaw line one row under the sockets and add a nose, and all three merge into a single
# shape that reads as one enormous eye, which is what the first attempt at this did. So:
# sockets high, a clear lit row under them, the jaw line below that, and no nose at all,
# which a thirty-two pixel skull does not have room for anyway.
px(disc(13, 8, 2, 2) | disc(19, 8, 2, 2), DARK)      # eye sockets
px({(x, 12) for x in range(12, 21)}, DARK)            # the jaw line, so it is two bones
px({(x, 14) for x in range(12, 21, 2)}, DARK)         # teeth

# The teeth and eye sockets are deliberately lone dark pixels, so they are named
# rather than cleaned away with the shading strays.
effects.remove_stray_pixels(NAME, protect=[DARK])
effects.add_outline(NAME, DARK, thickness=1, connectivity=8, where="outside")
export.export_png(NAME, "skeleton.png", scale=8, overwrite=True)
print("wrote skeleton.png")
