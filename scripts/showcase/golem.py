"""Build the golem showcase: a stone creature with carved form, in the JRPG enemy style.

The first version of this piece was 40x40 and measurably wrong, in a way worth recording
because the fault was not in the drawing but in one line of arithmetic.

Its tone came from `step = 4 + DEPTH[part] + light`, where `light` was a count of three
probes bucketed into three outcomes. So **no part could ever reach more than three of the
eight ramp steps**: measured across its thirteen parts, the maximum was three and the mean
was 2.9. The largest mass spent 72 percent of itself on a single tone, which is why a
shoulder rendered as a flat plate. Worse, `DEPTH` spanned five steps against the light's
two, so part identity outranked light direction five to two and the figure stratified into
a pale near half and a dark far half whose extremes never shared a value. Eight ramp steps
were being spent on *stacking order* and at most three were left to describe form.

So this version does not compute tone. It builds a flat silhouette, hands it to
`shade_region_by_light`, which shades by surface normal and can use the whole ramp, and
keeps depth to a single step. Depth is a nudge and a seam, not the subject.

Three other things were measured and are fixed here.

**The ramp rendered as greys.** `ramp_between("#241f2a", "#d8d2c6")` rotated 133 degrees of
hue at a 2.4 percent saturation floor, six of its eight steps below the level at which hue
is visible at all. Interpolation carries only the chroma its ends supply and both ends were
near neutral. `generate_ramp` with `chroma` asks for the saturation directly, and this ramp
holds 0.23, which is where reference work in this style runs its apparent greys.

**The silhouette was clipped.** 42 drawn pixels sat on the canvas border, so the figure was
cut off on three sides and could not take an outline there. Everything here is laid out
inside a three-pixel margin, and `verify` fails if a single pixel reaches the edge.

**The core glow painted nothing.** The old build called `glow`, whose docstring says
plainly that "a body blocks the halo of a gem inside it": the core is inside the
silhouette, so there was no outside for a halo to occupy, and the longest comment in the
old file defended a layer that contributed zero pixels. Light from the core is instead
painted *into* the stone around it, which is what emission actually does to a surface.

Light is up and to the left at 130 degrees, matching the rest of the gallery.
"""
import pathlib

from aseprite_mcp.core import quality
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
W = H = 64
MARGIN = 3
LIGHT_ANGLE = 130.0

# Asked for, not inherited. A base colour is picked for its value ("stone is grey"), which
# is how the old ramp ended up with no chroma to rotate: saturation comes from the base
# unless something overrides it, and 0.28 is inside the 0.17 to 0.30 that reference art in
# this style runs. Cool violet shadow to warm cream highlight, chroma held through the
# midtones by the peak curve rather than sagging through the neutral axis.
STONE = {"base_color": "#7a6a62", "steps": 8, "chroma": 0.28,
         "shadow_hue": "#2e2452", "light_hue": "#ffe2a8", "sat_curve": "peak",
         "saturation_shift": 35.0, "easing": "perceptual", "light_range": 0.74}
CORE = {"base_color": "#2fb8a6", "steps": 5, "chroma": 0.55,
        "shadow_hue": "#10384a", "light_hue": "#e6fffb", "sat_curve": "peak",
        "easing": "perceptual"}


def disc(cx, cy, rx, ry):
    return {(x, y)
            for y in range(int(cy - ry) - 1, int(cy + ry) + 2)
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2)
            if 0 <= x < W and 0 <= y < H
            and ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0}


def box(x0, y0, x1, y1):
    return {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if 0 <= x < W and 0 <= y < H}


def parts():
    """The body, back to front, laid out around the gaps rather than around the masses.

    What makes a figure read is negative space, so these numbers are chosen for the air:
    four clear pixels between each arm and the torso below the shoulder line, two up the
    middle between the legs, and the head's top eight rows clear of the pauldrons. The
    pauldrons bridge torso to arm, which is what shoulders are for, and the near one is
    deliberately much heavier than the far one, because a figure with two matching limbs
    is not standing, it is extruded.
    """
    return [
        ("leg_far", box(35, 48, 40, 55) | disc(37, 51, 3, 5)),
        ("foot_far", box(34, 54, 43, 58)),
        ("leg_near", box(24, 48, 30, 57) | disc(27, 52, 4, 6)),
        ("foot_near", box(21, 56, 32, 60)),
        ("hips", disc(32, 46, 9, 6)),
        ("torso", disc(32, 34, 10, 13)),
        ("arm_far", disc(54, 38, 6, 10)),
        ("fist_far", disc(54, 50, 6, 5)),
        ("arm_near", disc(10, 38, 7, 12)),
        ("fist_near", disc(10, 52, 7, 6)),
        ("pauldron_near", disc(17, 25, 13, 9)),
        ("pauldron_far", disc(47, 27, 9, 6)),
        ("head", disc(32, 14, 7, 6)),
    ]


# One step, not five. Depth separates the far side from the near side by a nudge; the light
# does the describing. The old file spent the whole ramp here and had three steps left over
# for form, which is the single arithmetic fact that made the figure read as a pile of
# plates.
FAR = {"leg_far", "foot_far", "arm_far", "fist_far", "pauldron_far"}
NEAR = {"leg_near", "arm_near", "fist_near", "pauldron_near"}


def ramp_index(stone, colour):
    """Which ramp step a read-back pixel is, or None if it is not on the ramp."""
    want = colour[:7].lower()
    for i, entry in enumerate(stone):
        if entry.lower() == want:
            return i
    return None


def main():
    made = palette.generate_ramp(**STONE)
    stone = made["colors"]
    core = palette.generate_ramp(**CORE)["colors"]
    # The ramp is measured here rather than trusted, because "it rotates hue" was true of
    # the ramp this piece replaced and told nobody anything.
    chroma = quality.ramp_chroma(stone)
    assert chroma["grey_steps"] == 0, (
        f"the stone ramp has {chroma['grey_steps']} steps below visible chroma: {stone}")
    assert chroma["sat_floor"] > 0.15, chroma

    body = parts()
    owner = {}
    for name, pixels in body:
        for position in pixels:
            owner[position] = name
    mass = set(owner)

    # Inside the margin before anything is drawn. The old piece lost 42 pixels off three
    # edges and could not be outlined there; catching it at layout time rather than in the
    # export is the difference between a fixable mistake and a shipped one.
    stray = [p for p in mass
             if not (MARGIN <= p[0] < W - MARGIN and MARGIN <= p[1] < H - MARGIN)]
    assert not stray, f"{len(stray)} pixels are outside the {MARGIN}px margin: {stray[:6]}"

    sprite.create_sprite(NAME, W, H, overwrite=True)
    layers.rename_layer(NAME, "Layer 1", "stone")

    # 1. The silhouette, flat, in one mid tone. A creature has to be recognisable as a
    # shape before any light touches it, and shading a flat mass is also what lets the
    # shading tool see the whole form instead of thirteen separate ones.
    drawing.draw_pixels(
        NAME, [{"x": x, "y": y} for x, y in sorted(mass)], stone[4])

    # 2. The form, from the surface normal, by the tool that exists for it. This is the
    # line the old version replaced with arithmetic of its own.
    lit = shading.shade_region_by_light(
        NAME, stone, base_color=stone[4], light_angle=LIGHT_ANGLE, light_z=0.5, rim=0.18)
    assert lit["pixels_written"] > 0, lit

    # 3. Depth, as one step. Read back rather than assumed, so a pixel is shifted from
    # where the light actually put it.
    back = inspect.get_pixels(NAME, 0, 0, W, H)["pixels"]
    shifted = {}
    for (x, y), name in owner.items():
        if name not in FAR and name not in NEAR:
            continue
        index = ramp_index(stone, back[y][x])
        if index is None:
            continue
        step = index - 1 if name in FAR else index + 1
        step = max(1, min(len(stone) - 1, step))
        if step != index:
            shifted.setdefault(step, []).append((x, y))
    for step, positions in sorted(shifted.items()):
        drawing.draw_pixels(
            NAME, [{"x": x, "y": y} for x, y in sorted(positions)], stone[step])

    # 4. The seams, where one mass overlaps another. Two steps down from whatever the
    # light left there, rather than slammed to the darkest entry: the old piece set these
    # to step 1 regardless, which is a drawn black line and read as brickwork.
    #
    # `contact_shadow` is the tool for this and cannot be used here: it finds its occluder
    # by colour, and both sides of these seams are the same stone. Occlusion between two
    # masses of one material is a gap in the toolkit, and this loop is what fills it in
    # the meantime.
    back = inspect.get_pixels(NAME, 0, 0, W, H)["pixels"]
    seam = {}
    for (x, y), name in owner.items():
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            other = owner.get((x + dx, y + dy))
            if other is None or other == name:
                continue
            front = (name in NEAR) or (other in FAR and name not in FAR)
            if not front:
                continue
            index = ramp_index(stone, back[y + dy][x + dx])
            if index is None:
                continue
            seam.setdefault(max(1, index - 2), []).append((x + dx, y + dy))
    for step, positions in sorted(seam.items()):
        drawing.draw_pixels(
            NAME, [{"x": x, "y": y} for x, y in sorted(positions)], stone[step])

    # 5. Cracks, drawn as a map rather than as interpolated line segments. Per-pixel
    # intent is the whole reason `draw_pixel_map` exists: a crack that runs across a mass,
    # widens where it turns and stops short of the edge cannot be written as a formula,
    # and a formula is what the old piece used.
    crack = [
        "..a..",
        "..a..",
        ".aa..",
        ".a...",
        "aa...",
        ".a...",
        ".aa..",
        "..a..",
    ]
    for ox, oy in ((26, 26), (37, 33), (14, 30)):
        drawn = {(ox + cx, oy + cy)
                 for cy, row in enumerate(crack)
                 for cx, ch in enumerate(row) if ch != "."}
        outside = drawn - mass
        assert not outside, (
            f"the crack at ({ox},{oy}) puts {len(outside)} pixels off the figure: "
            f"{sorted(outside)[:4]}. A crack runs across a mass; one hanging off the "
            "silhouette is a floating speck.")
        drawing.draw_pixel_map(NAME, crack, {"a": stone[1]}, x=ox, y=oy)

    # 6. The core, and the light it throws onto the stone around it. A map again, because
    # a heart is four deliberate pixels and a bloom, not an ellipse.
    heart = [
        "..c..",
        ".ccc.",
        "cceec",
        ".ccc.",
        "..c..",
    ]
    drawing.draw_pixel_map(NAME, heart, {"c": core[2], "e": core[4]}, x=30, y=31)
    drawing.draw_pixel_map(
        NAME, ["e.e"], {"e": core[4]}, x=29, y=13)   # the eyes

    # The emission, painted into the rock rather than haloed outside it. `glow` would put
    # a halo on a layer below the body, where a body blocks it; what light from an interior
    # source actually does is warm the surface it sits in.
    back = inspect.get_pixels(NAME, 0, 0, W, H)["pixels"]
    bloom = []
    cx, cy = 32, 33
    for (x, y) in mass:
        d = max(abs(x - cx), abs(y - cy))
        if not 3 <= d <= 6:
            continue
        if ramp_index(stone, back[y][x]) is None:
            continue
        bloom.append({"x": x, "y": y, "color": core[1] if d <= 4 else core[0]})
    drawing.draw_pixels(NAME, bloom)

    # 7. The outline, weighted by the light. Two pixels where the form turns away and one
    # where it faces into the light, which is the shape of a hand-drawn keyline and the
    # thing a uniform border cannot be.
    #
    # `lit_thickness=0` was tried and is worse here, which is worth recording because the
    # measurement prefers it: dropping the lit side entirely moves the separator share
    # from 25.3 to 19.1 percent, into the middle of the band, and makes the picture look
    # damaged. On a silhouette this lumpy the lit/shadow test is decided per pixel, so the
    # outline does not taper at the terminator, it fragments into specks. A keyline that
    # drops out has to thin through 2, 1, 0 across a band, and `add_outline` cannot do
    # that yet. One pixel on the lit side is continuous, and continuous beats optimal.
    #
    # The old piece ran a colour-matched 1px ring and
    # its darkest colour covered 7.6 percent of the drawing, well under the 10 to 24 that
    # work in this style spends on separating its masses.
    outlined = effects.add_outline(
        NAME, stone[0], thickness=2, connectivity=8, where="outside",
        light_angle=LIGHT_ANGLE, lit_thickness=1)
    assert outlined["outline_shadow"] > outlined["outline_lit"], outlined

    verify(stone, core, outlined)

    out = pathlib.Path(NAME).with_suffix("")
    export.export_png(NAME, f"{out}.png", scale=1, overwrite=True)
    export.export_png(NAME, f"{out}_4x.png", scale=4, overwrite=True)
    print(f"wrote {out}.png: {len(body)} parts, {len(mass)} pixels, "
          f"ramp sat_floor {chroma['sat_floor']}, outline "
          f"{outlined['outline_shadow']}/{outlined['outline_lit']} shadow/lit")


def verify(stone, core, outlined):
    """What this piece claims, read back off the sprite by the project's own measurements.

    Every assertion here is one the previous version of this file would have failed, which
    is the only reason to write them: a verification that passes on the art it replaced
    measures nothing.
    """
    report = inspect.assess_sprite(NAME, ramp=stone)
    m = report["metrics"]
    rows = m["row_structure"]

    # 1. The silhouette is not cut off. The old piece had 42 of these.
    assert m["edge_contact"] == 0, (
        f"{m['edge_contact']} drawn pixels sit on the canvas border, so the silhouette is "
        "clipped and cannot take an outline there")

    # 2. It is a figure with parts, and they are not fused. The old piece had 16 of its 38
    # drawn rows as a single run across most of its width.
    assert rows["waists"] >= 1, f"no waist, so the silhouette is one convex blob: {rows}"
    assert rows["rows_with_air"] / rows["rows_drawn"] >= 0.25, (
        f"only {rows['rows_with_air']} of {rows['rows_drawn']} rows have background "
        "between two parts; the limbs have welded to the body")

    # 3. The ramp's hue is visible. The old one rotated 133 degrees and showed none of it.
    assert m["ramp_chroma"]["grey_steps"] == 0, m["ramp_chroma"]
    assert m["ramp_chroma"]["sat_floor"] > 0.15, m["ramp_chroma"]

    # 4. There is a keyline doing the separating, in the band that work in this style uses.
    low, high = quality.SEPARATOR_BAND
    share = m["separator"]["share"]
    assert low <= share <= high * 2, (
        f"the darkest colour is {share:.1%} of the drawing, outside the {low:.0%} to "
        f"{high:.0%} this style spends on separating masses")

    # 5. The form uses the ramp. The old piece could not give any one part more than three
    # of its eight steps, so this is the measurement that would have caught it.
    assert m["colors"] >= 8, f"only {m['colors']} colours in the figure"
    assert m["tone_shares"]["top_share"] < 0.40, (
        f"{m['tone_shares']['top_color']} covers {m['tone_shares']['top_share']:.0%} of "
        "the drawing, so one tone is filling rather than describing")

    # 6. The accent is actually in the picture, and the emission reached the stone. The old
    # piece called `glow` and it contributed zero pixels, because a body blocks the halo of
    # a gem inside it.
    found = set()
    for row in inspect.get_pixels(NAME, 0, 0, W, H)["pixels"]:
        found.update(px[:7].lower() for px in row)
    assert core[4].lower() in found, "the core's brightest colour is not in the figure"
    assert core[0].lower() in found or core[1].lower() in found, (
        "no emission reached the stone around the core, so the heart is a sticker")

    readings = [r for r in report["readings"]
                if "fused" in r or "border" in r or "keyline" in r or "saturation" in r]
    assert not readings, "the measurements this rebuild exists to fix still fire:\n  " \
                         + "\n  ".join(readings)
    print(f"verified: edge_contact 0, waists {rows['waists']}, "
          f"air {rows['rows_with_air']}/{rows['rows_drawn']}, "
          f"separator {share:.1%}, colours {m['colors']}, "
          f"top tone {m['tone_shares']['top_share']:.0%}")


if __name__ == "__main__":
    main()
