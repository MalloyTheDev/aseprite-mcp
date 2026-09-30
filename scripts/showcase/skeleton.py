"""Redraw the skeleton example: a shaded skull over hand-placed bones."""
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


sprite.create_sprite(NAME, W, H, overwrite=True)

skull = disc(16, 9, 7, 6) | block(11, 13, 21, 15)
bones = set()
bones |= block(15, 17, 17, 27)                       # spine
for y, half in ((18, 6), (21, 5), (24, 4)):          # ribs, tapering to the waist
    bones |= block(16 - half, y, 16 + half, y)
    bones |= {(16 - half, y + 1), (16 + half, y + 1)}  # the turn of each rib
bones |= block(6, 18, 8, 19) | block(24, 18, 26, 19)  # shoulders
bones |= block(6, 20, 7, 26) | block(25, 20, 26, 26)  # arms
bones |= block(5, 26, 8, 27) | block(24, 26, 27, 27)  # hands
bones |= block(12, 28, 14, 31) | block(18, 28, 20, 31)  # legs

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

px(disc(13, 9, 2, 2) | disc(19, 9, 2, 2), DARK)      # eye sockets
px({(16, 11), (16, 12)}, DARK)                        # nose
px({(x, 14) for x in range(12, 21, 2)}, DARK)         # teeth

# The teeth and eye sockets are deliberately lone dark pixels, so they are named
# rather than cleaned away with the shading strays.
effects.remove_stray_pixels(NAME, protect=[DARK])
effects.add_outline(NAME, DARK, thickness=1, connectivity=8, where="outside")
export.export_png(NAME, "skeleton.png", scale=8, overwrite=True)
print("wrote skeleton.png")
