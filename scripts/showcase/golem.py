"""Build the golem showcase: a creature with carved form, in the JRPG enemy style.

The rest of the gallery is scenes, effects and props. This is the first piece that is a
*creature*, and the order it is built in is the whole lesson. The first attempt shaded
fourteen hand-placed facets straight away and came out as a pile of grey boxes: nearly
axis-aligned plates, a dark seam drawn on every one of them so the figure read as brickwork,
and tones so close together that the facets never disagreed enough to look carved.

So this builds in the order a pixel artist does.

**The silhouette first, as one flat shape.** A creature has to be recognisable in black
before any light touches it. The mass is built from overlapping body parts, deliberately
top-heavy and asymmetric: one pauldron larger than the other, one arm hanging lower, a small
head set back between the shoulders. A figure with two matching limbs is not standing, it is
extruded, which is what made the skeleton piece in this same gallery read as programmer art.

**Then the form, from the inside out.** Tone comes from how far a pixel is from the
silhouette's edge and which way that edge faces, not from which rectangle it belongs to.
That gives rounded masses that still meet at hard boundaries, which is what carved stone
looks like.

**Then the boundaries, and only the ones that matter.** Seams go between *limbs*, where one
mass overlaps another, not around every plate. The outline is `outline_smart`, which picks a
darker version of each edge's own colour rather than ringing the whole thing in black.

Light is up and to the left, matching every other piece so the gallery looks like one set.
"""
import pathlib

from aseprite_mcp.tools import (
    drawing,
    effects,
    export,
    inspect,
    layers,
    palette,
    shading,
    sprite,
)

NAME = "golem.aseprite"
W = H = 40

STONE_ENDS = ("#241f2a", "#d8d2c6")
STONE_STEPS = 8
CORE_ENDS = ("#1d6a5c", "#b6ffe6")
CORE_STEPS = 4
LIGHT = (-0.55, -0.83)


def disc(cx, cy, rx, ry):
    return {(x, y)
            for y in range(int(cy - ry) - 1, int(cy + ry) + 2)
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2)
            if 0 <= x < W and 0 <= y < H
            and ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0}


def box(x0, y0, x1, y1):
    return {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if 0 <= x < W and 0 <= y < H}


# Each part is named because the seams below need to know which masses overlap, and because
# a part list is the thing to edit when the silhouette does not read. Order is back to
# front. The numbers are hand-placed and were moved several times while looking at the
# flat shape: that is the loop this piece is really about.
def parts():
    """The body, back to front, laid out around the gaps rather than around the masses.

    The first layout had thirteen overlapping parts and rendered as one rounded rectangle:
    the head sat *inside* the pauldrons and the arms touched the torso, so there was nothing
    for the eye to separate. What makes a figure read is negative space, so the numbers here
    are chosen for the gaps. Two clear pixels between each arm and the torso, three between
    the legs, one between the feet, and the head's top seven rows clear of the shoulders.
    """
    return [
        # Legs and feet, with a three-pixel gap up the middle and the far leg shorter so
        # the stance has depth.
        ("leg_far", box(23, 28, 28, 35) | disc(25, 31, 3, 4)),
        ("foot_far", box(22, 34, 30, 38)),
        ("leg_near", box(14, 28, 19, 35) | disc(16, 31, 3, 5)),
        ("foot_near", box(12, 34, 20, 38)),
        ("hips", disc(20, 27, 6, 4)),
        # An egg, wider at the chest than the waist, which is most of the difference
        # between a creature and a crate.
        ("torso", disc(20, 20, 6, 8)),
        # Arms outside the torso with air between: the gap is the thing being drawn.
        ("arm_far", disc(33, 23, 4, 6)),
        ("fist_far", disc(33, 31, 5, 4)),
        ("arm_near", disc(6, 24, 5, 8)),
        ("fist_near", disc(5, 33, 6, 5)),
        # The pauldrons bridge torso to arm, which is what shoulders are for. The near
        # side is heavier on purpose, and by enough to count: the first version differed
        # by a radius here and there, and `verify` measured the two halves as seven pixels
        # apart, which is a mirrored figure with asymmetric *shading* painted on it.
        ("pauldron_near", disc(10, 14, 9, 6)),
        ("pauldron_far", disc(30, 16, 6, 4)),
        # Small, and sitting clear above the shoulder line.
        ("head", disc(20, 7, 5, 4)),
    ]


# How far back each mass sits. A creature this wide cannot be separated by its outline
# alone: pushing the far side down the ramp is what stops the pauldrons, the torso and the
# arms reading as one slab, which is what the third silhouette draft did.
DEPTH = {
    "leg_far": -2, "foot_far": -3, "arm_far": -2, "fist_far": -1, "pauldron_far": -2,
    "hips": -1, "torso": 0, "head": -1,
    "leg_near": 1, "foot_near": -1, "arm_near": 1, "fist_near": 1, "pauldron_near": 2,
}

def main():
    stone = palette.ramp_between(*STONE_ENDS, steps=STONE_STEPS)["colors"]
    core = palette.ramp_between(*CORE_ENDS, steps=CORE_STEPS)["colors"]
    top = len(stone) - 1

    body = parts()
    # Painted back to front, so the owner of a pixel is the frontmost mass covering it.
    owner = {}
    for name, pixels in body:
        for position in pixels:
            owner[position] = name
    mass = set(owner)

    # Within a part, light the pixels on the side the light comes from. Distance to that
    # part's own edge rather than to the whole figure's, so each mass is rounded in its
    # own right: a shoulder is not a bump on a torso, it is a shoulder.
    tone = {}
    for (x, y), name in owner.items():
        own = {p for p, n in owner.items() if n == name}
        lit_side = 0.0
        for reach in (1, 2, 3):
            probe = (round(x + LIGHT[0] * reach), round(y + LIGHT[1] * reach))
            if probe in own:
                lit_side += 1.0
        # A pixel with its own mass between it and the light is in that mass's shadow.
        step = 4 + DEPTH[name] + (1 if lit_side <= 1 else 0) - (1 if lit_side >= 3 else 0)
        tone[(x, y)] = max(1, min(top, step))

    # Boundaries, and only where two masses actually meet. The first draft of this piece
    # drew a seam around every plate and came out as brickwork; what has to be dark is the
    # join between one limb and the next, which is the line the eye uses to tell them apart.
    for (x, y), name in list(owner.items()):
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            other = owner.get((x + dx, y + dy))
            if other is not None and other != name and DEPTH[other] < DEPTH[name]:
                tone[(x + dx, y + dy)] = 1

    sprite.create_sprite(NAME, W, H, overwrite=True)
    layers.rename_layer(NAME, "Layer 1", "stone")
    by_step = {}
    for position, step in tone.items():
        by_step.setdefault(step, []).append(position)
    for step, positions in sorted(by_step.items()):
        drawing.draw_pixels(
            NAME, [{"x": x, "y": y} for x, y in sorted(positions)], stone[step])

    # Cracks. Without them the masses read as river pebbles rather than as cut stone,
    # because a rounded shape with a soft gradient is a stone that has been in water. Each
    # one runs across a mass rather than along it, and stops short of the edge so it does
    # not read as a gap between two parts.
    cracks = [((15, 17), (19, 22)), ((22, 23), (25, 19)), ((8, 20), (10, 26)),
              ((31, 21), (34, 25)), ((17, 30), (18, 34)), ((25, 30), (26, 33))]
    crack_px = []
    for (x0, y0), (x1, y1) in cracks:
        steps = max(abs(x1 - x0), abs(y1 - y0))
        for i in range(steps + 1):
            x = round(x0 + (x1 - x0) * i / steps)
            y = round(y0 + (y1 - y0) * i / steps)
            if (x, y) in mass:
                crack_px.append({"x": x, "y": y})
    drawing.draw_pixels(NAME, crack_px, stone[1])

    # The core, on the chest, and the eyes. One warm accent in a grey figure, so the face
    # and the heart are where the eye lands.
    core_px = {(x, y) for y in range(18, 23) for x in range(18, 23)
               if abs(x - 20) + abs(y - 20) <= 2 and (x, y) in mass}
    drawing.draw_pixels(
        NAME, [{"x": x, "y": y} for x, y in sorted(core_px)], core[-1])
    drawing.draw_pixels(
        NAME, [{"x": x, "y": y} for x, y in [(18, 7), (22, 7)]], core[-1])

    # `glow` spreads the core into the stone around it on a layer of its own, which is what
    # keeps the stone's own facets flat: the light is something happening *to* the rock
    # rather than a gradient painted into it.
    effects.glow(NAME, core, radius=4, falloff="quadratic", base_color=core[-1],
                 tolerance=10.0, new_layer="core glow")
    # Left as its own layer rather than merged: `glow` puts it at the *bottom* of the
    # stack, which is where a glow belongs, and `merge_layer_down` correctly refuses a
    # bottom layer because there is nothing under it. The export composites anyway, and
    # keeping it separate means the stone's facets stay flat underneath.

    # A colour-matched outline, not a black one: each edge pixel gets a darker version of
    # its own colour, so the lit shoulder keeps a warm rim and the shadowed arm a cold one.
    shading.outline_smart(NAME, stone, mode="colormatched", darken_steps=2,
                          light_angle=125)

    verify(mass, core)

    out = pathlib.Path(NAME).with_suffix("")
    export.export_png(NAME, f"{out}.png", scale=1, overwrite=True)
    export.export_png(NAME, f"{out}_6x.png", scale=6, overwrite=True)
    print(f"wrote {out}.png: {len(body)} parts, {len(mass)} pixels, "
          f"{len(by_step)} tones in use")


def verify(mass, core):
    """What this piece claims about the figure, read back off the sprite.

    All three are about the silhouette rather than the shading, because the shading was
    never the problem: three drafts of this piece were lost to a figure that was shaded
    beautifully and read as a pile of boxes.
    """
    # 1. The negative space survived. These columns are the gaps between each arm and the
    # torso, and if they ever fill in, the arms have welded themselves back on and the
    # figure is a slab again, which is exactly what drafts one and three were.
    for gap_x, label in ((12, "near arm"), (28, "far arm")):
        column = inspect.get_pixels(NAME, gap_x, 18, 1, 8)["pixels"]
        clear = [row[0] for row in column if row[0][7:9] == "00"]
        assert clear, (
            f"the gap beside the {label} has filled in: {[r[0] for r in column]}. The "
            "arms are welded to the torso and the silhouette has stopped reading.")

    # 2. The figure is not symmetrical. A mirrored creature is not standing, it is
    # extruded, which is what made the skeleton piece in this gallery read as placeholder.
    left = sum(1 for (x, _) in mass if x < W // 2)
    right = len(mass) - left
    assert abs(left - right) >= 40, (
        f"the two halves are within {abs(left - right)} pixels of each other, so the "
        "figure is mirrored and the pose says nothing")

    # 3. The accent is actually in the picture. The eyes and the core are the only warm
    # thing in a grey figure, and a glow that silently failed would leave a grey lump.
    found = set()
    for row in inspect.get_pixels(NAME, 14, 4, 14, 20)["pixels"]:
        found.update(px[:7].lower() for px in row)
    assert core[-1].lower() in found, (
        f"the core colour {core[-1]} is not in the figure; the eyes and the heart are "
        "where the eye is supposed to land")


if __name__ == "__main__":
    main()
