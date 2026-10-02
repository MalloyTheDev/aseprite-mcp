"""Build the z-index showcase: a sword swung past a shield, behind it and then in front.

The problem this picture is about: a blade that crosses a shield is behind it on the
approach and in front of it on the follow-through. A layer stack cannot say that, because
a layer's position applies to every frame at once. Both usual workarounds are bad. Moving
the layer changes the other frames too; duplicating the sword onto a second layer means
hiding one of the two per frame and keeping two drawings in step for the rest of the
sprite's life.

`set_cel_z_index` says it per cel instead. The sword layer stays below the shield for the
whole swing and the layers are never reordered: only the number changes. z=0 leaves that
cel where its layer sits, z=2 lifts one frame's cel above the shield, and no other frame
is touched.

Built the way the item sheet is: hand-authored silhouettes, form from
`shade_region_by_light` per part, thin parts lit by hand because the shading tool refuses
to invent a form it cannot see, then one dark outline over everything.
"""
import pathlib

from PIL import Image

from aseprite_mcp.tools import (
    cels,
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

NAME = "zorder.aseprite"
W, H = 72, 40
SHIELD_CX, SHIELD_CY = 38, 20
OUTLINE = "#241a2e"

STEEL = palette.generate_ramp("#b9c4d6", steps=5, hue_shift=-24.0,
                              saturation_shift=-30.0, light_range=0.66)["colors"]
BRASS = palette.generate_ramp("#f2b632", steps=5, hue_shift=-26.0,
                              saturation_shift=-14.0, light_range=0.72)["colors"]
WOOD = palette.generate_ramp("#8a5a33", steps=5, hue_shift=-20.0,
                             saturation_shift=-14.0, light_range=0.72)["colors"]
OAK = palette.generate_ramp("#5c7a3a", steps=5, hue_shift=-26.0,
                            saturation_shift=-16.0, light_range=0.70)["colors"]

# The swing: the blade sweeps right, passing behind the shield and then in front of it.
# Two positions each side of the crossing, so both the occluded and the overlapping read
# are unmistakable rather than a sliver poking out.
SWING = [
    (-6, 0, "approach, behind the shield"),
    (0, 0, "crossing, still behind"),
    (4, 2, "crossing, now in front"),
    (10, 2, "follow through, in front"),
]


def pixels(points):
    return [{"x": x, "y": y} for x, y in sorted(points)]


def in_ellipse(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def shield_face():
    """The planked face of a round shield, minus the rim."""
    return {(x, y) for y in range(H) for x in range(W)
            if in_ellipse(x, y, SHIELD_CX, SHIELD_CY, 11.4, 15.4)}


def shield_rim():
    """A two-pixel metal rim: the face grown, minus the face."""
    outer = {(x, y) for y in range(H) for x in range(W)
             if in_ellipse(x, y, SHIELD_CX, SHIELD_CY, 13.4, 17.4)}
    return outer - shield_face()


def shield_boss():
    """The metal dome at the centre, which is what makes it read as a shield."""
    return {(x, y) for y in range(H) for x in range(W)
            if in_ellipse(x, y, SHIELD_CX, SHIELD_CY, 4.2, 4.2)}


def blade(ox):
    """A tapered blade, point leading to the right, on the swing's centre line."""
    points = set()
    for x in range(ox + 12, ox + 58):
        from_tip = ox + 57 - x
        half = 0 if from_tip < 1 else 1 if from_tip < 3 else 2
        for y in range(20 - half, 20 + half + 1):
            points.add((x, y))
    return {(x, y) for x, y in points if 0 <= x < W and 0 <= y < H}


def guard(ox):
    points = {(x, y) for x in (ox + 10, ox + 11) for y in range(14, 27)}
    points |= {(x, y) for x in (ox + 9,) for y in range(16, 25)}
    return {(x, y) for x, y in points if 0 <= x < W and 0 <= y < H}


def grip(ox):
    points = {(x, y) for x in range(ox + 3, ox + 10) for y in range(18, 23)}
    return {(x, y) for x, y in points if 0 <= x < W and 0 <= y < H}


def pommel(ox):
    points = {(x, y) for x in range(ox, ox + 3) for y in range(17, 24)}
    return {(x, y) for x, y in points if 0 <= x < W and 0 <= y < H}


def paint(part, colour, ramp, layer, frame, *, shade=True):
    """Draw a part, then give it form the way the item sheet does."""
    if not part:
        return
    drawing.draw_pixels(NAME, pixels(part), colour, layer=layer, frame=frame)
    if shade:
        shading.shade_region_by_light(NAME, ramp, base_color=colour, light_angle=130.0,
                                      light_z=0.6, ambient=0.34, rim=0.18,
                                      layer=layer, frame=frame)
        return
    # Too thin for a form: light the top row and drop the bottom one by hand, which is
    # what `shade_region_by_light` declines to guess at.
    top, bottom = min(y for _, y in part), max(y for _, y in part)
    drawing.draw_pixels(NAME, pixels({p for p in part if p[1] == top}), ramp[3],
                        layer=layer, frame=frame)
    drawing.draw_pixels(NAME, pixels({p for p in part if p[1] == bottom}), ramp[1],
                        layer=layer, frame=frame)


def owner_of(hex_colour):
    """Which ramp a composited pixel came from, which is how the swap is measured."""
    colour = hex_colour[:7].lower()
    for name, ramp in (("sword", STEEL), ("shield", OAK), ("rim", STEEL),
                       ("boss", STEEL), ("brass", BRASS), ("wood", WOOD)):
        if colour in [c.lower() for c in ramp]:
            return name
    return "neither"


sprite.create_sprite(NAME, W, H, overwrite=True)
# The sword is the first layer, so it sits *below* the shield for the whole swing.
# Nothing after this reorders them.
layers.rename_layer(NAME, "Layer 1", "sword")
layers.add_layer(NAME, "shield")
for _ in range(len(SWING) - 1):
    frames.add_frame(NAME)

for frame, (ox, _z, _note) in enumerate(SWING, start=1):
    paint(shield_face(), OAK[2], OAK, "shield", frame)
    paint(shield_rim(), STEEL[2], STEEL, "shield", frame)
    paint(shield_boss(), STEEL[3], STEEL, "shield", frame)
    paint(blade(ox), STEEL[3], STEEL, "sword", frame)
    paint(guard(ox), BRASS[2], BRASS, "sword", frame, shade=False)
    paint(grip(ox), WOOD[2], WOOD, "sword", frame, shade=False)
    paint(pommel(ox), BRASS[2], BRASS, "sword", frame, shade=False)

# Shading small shapes leaves lone pixels at the band boundaries, the same as the item
# sheet, and the outline wants a settled silhouette to trace.
for frame in range(1, len(SWING) + 1):
    for layer in ("sword", "shield"):
        effects.remove_stray_pixels(NAME, layer=layer, frame=frame)
    effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside",
                        layer="shield", frame=frame)
    effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside",
                        layer="sword", frame=frame)

print("steel:", STEEL)
print("oak:  ", OAK)
print()
for frame, (_ox, z, note) in enumerate(SWING, start=1):
    result = cels.set_cel_z_index(NAME, "sword", frame, z)
    back_to_front = " then ".join(cel["layer"] for cel in result["order"])
    print(f"frame {frame}  z={z}  {note:<28} renders: {back_to_front}")

# The claim the picture rests on, measured rather than asserted: on the shield's own face
# the two crossing frames must disagree about which ramp owns the pixel. A z-index that
# round-tripped through the file while changing nothing about the render would produce an
# identical-looking strip, which is exactly the failure worth catching.
probe = (SHIELD_CX + 7, 20)
print()
seen = {}
for frame in (2, 3):
    pixel = inspect.get_pixels(NAME, probe[0], probe[1], 1, 1, frame=frame)["pixels"][0][0]
    seen[frame] = owner_of(pixel)
    print(f"frame {frame}  pixel {probe} is {pixel}, from the {seen[frame]}")
assert seen[2] != seen[3], f"the ordering did not swap at the crossing point: {seen}"
print("the ordering swaps between frames 2 and 3, with the layers never reordered")

frames.set_all_frame_durations(NAME, 260)
print()
print("gif:  ", export.export_gif(NAME, "zorder.gif", scale=5, overwrite=True)["output"])

sheet = export.export_spritesheet_packed(
    NAME, "zorder_sheet.png", sheet_type="horizontal", padding=1,
    data_output="zorder_sheet.json", data_format="json-array", overwrite=True)
print("sheet:", sheet["output"], sheet["sheet_size"])

# A still pair for the README, so the swap reads without waiting for the loop.
stills = [
    pathlib.Path(export.export_png(NAME, f"zorder_f{frame}.png", frame=frame, scale=5,
                                   overwrite=True)["output"])
    for frame in (2, 3)
]
images = [Image.open(path).convert("RGBA") for path in stills]
gap = 14
strip = Image.new(
    "RGBA",
    (sum(i.width for i in images) + gap * (len(images) - 1), max(i.height for i in images)),
    (0, 0, 0, 0),
)
offset = 0
for image in images:
    strip.paste(image, (offset, 0), image)
    offset += image.width + gap
pair = stills[0].parent / "zorder_pair.png"
strip.save(pair)
print("pair: ", pair)
