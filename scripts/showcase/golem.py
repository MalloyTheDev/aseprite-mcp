"""Build the golem showcase: a stone creature with carved form, in the JRPG enemy style.

This piece has been rebuilt three times and each rebuild was caused by a measurement, so
all three are recorded rather than tidied away. They are the argument for how it is drawn
now.

**It computed a tone per part.** `step = 4 + DEPTH[part] + light`, where `light` was three
probes bucketed into three outcomes, so no part could reach more than three of eight ramp
steps: measured across thirteen parts the maximum was three and the mean 2.9, and the
largest mass spent 72 percent of itself on one tone. `DEPTH` spanned five steps against the
light's two, so part identity outranked light direction and the figure split into a pale
near half and a dark far half whose extremes never shared a value.

**It handed the shading to `shade_region_by_light` and passed every measurement while still
being wrong.** That tool infers a normal from how far a pixel sits from the silhouette's
edge, which is right for a sphere and rounds over everything hard, so a carved figure came
out as inflated tubes. Worth stating plainly: the metrics caught the absence of defects and
said nothing about the presence of craft.

**It cut the masses into chiselled blocks, which fixed the material and cost the gesture.**
Axis-aligned rectangles stacked vertically read as a robot, because a formula chose where
every edge went.

So the figure is drawn by hand now, in `golem_figure.py`, one character per pixel, where
the character says which way that pixel's surface faces. The silhouette and the lighting
are decided in the same stroke instead of one being inferred from the other, which is the
whole reason `draw_pixel_map` and `shade_facets` take a character grid.

Two consequences worth knowing. `seam_occlusion` is not called here: on a drawn figure the
contact under an overhang is drawn, as the `u` planes in the grid, and a tool that finds
seams between generated masses has nothing to find. And the depth pass is gone for the same
reason, because which planes face away is now a thing the drawing says.

Light is up and to the left at 130 degrees, matching the rest of the gallery.
"""
import pathlib
import sys

# This piece is drawn in a sibling module, and these scripts are run as files rather than
# as a package, so its directory has to be importable before the figure can be read.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from golem_figure import FACES, FIGURE, W, mass

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
H = W
MARGIN = 3
LIGHT_ANGLE = 130.0

# Asked for, not inherited. A base colour is picked for its value ("stone is grey"), which
# is how the first ramp ended up with no chroma to rotate: saturation comes from the base
# unless something overrides it, and 0.28 is inside the 0.17 to 0.30 that reference art in
# this style runs its apparent greys at.
STONE = {"base_color": "#7a6a62", "steps": 8, "chroma": 0.28,
         "shadow_hue": "#2e2452", "light_hue": "#ffe2a8", "sat_curve": "peak",
         "saturation_shift": 35.0, "easing": "perceptual", "light_range": 0.74}
CORE = {"base_color": "#2fb8a6", "steps": 5, "chroma": 0.55,
        "shadow_hue": "#10384a", "light_hue": "#e6fffb", "sat_curve": "peak",
        "easing": "perceptual"}
# Values that belong to a layer rather than to the stone ramp. This is the point of
# the stack: damage is a different material from the body it is cut into, occlusion
# is a multiply and needs only one flat tone, and the two lights are additive so
# their colours are what gets added rather than what gets painted.
DAMAGE = ["#2a2030", "#3b2d3a", "#8a7a66", "#6d6054"]
OCCLUDE = "#6a5e78"
EMIT = ["#1d4a46", "#102a2c"]
RIM = "#243a52"


def main():
    made = palette.generate_ramp(**STONE)
    stone = made["colors"]
    core = palette.generate_ramp(**CORE)["colors"]
    chroma = quality.ramp_chroma(stone)
    assert chroma["grey_steps"] == 0, (
        f"the stone ramp has {chroma['grey_steps']} steps below visible chroma: {stone}")
    assert chroma["sat_floor"] > 0.15, chroma

    drawn = mass()
    stray = [p for p in drawn
             if not (MARGIN <= p[0] < W - MARGIN and MARGIN <= p[1] < H - MARGIN)]
    assert not stray, f"{len(stray)} pixels are outside the {MARGIN}px margin: {stray[:6]}"

    sprite.create_sprite(NAME, W, H, overwrite=True)

    # The stack, bottom to top. Everything used to be stamped into one cel, each pass
    # destroying what was under it, and the figure came out in ten colours because every
    # detail had to borrow from the one stone ramp. Layers are where the colours come
    # from: a damage pass with its own values, occlusion that multiplies rather than
    # repainting, and light that adds rather than replacing.
    layers.rename_layer(NAME, "Layer 1", "stone")
    layers.add_layer(NAME, "damage")
    layers.add_layer(NAME, "occlusion", blend_mode="multiply", opacity=150)
    layers.add_layer(NAME, "core")
    layers.add_layer(NAME, "emission", blend_mode="addition", opacity=190)
    layers.add_layer(NAME, "rim", blend_mode="addition", opacity=210)

    # 1. The whole figure in one pass, because it is one drawing. Each of the six planes
    # takes a single flat tone from the light, which is what reads as cut rather than
    # inflated, and the grid's own characters decide which pixel is on which plane.
    shaded = shading.shade_facets(
        NAME, FIGURE, FACES, stone, light_angle=LIGHT_ANGLE, light_z=0.5,
        fill_strength=0.35, layer="stone")
    assert "warnings" not in shaded, shaded["warnings"]
    assert len(set(shaded["facet_steps"].values())) >= 5, (
        f"the six planes collapsed onto {len(set(shaded['facet_steps'].values()))} tones: "
        f"{shaded['facet_steps']}")

    # 2. Damage, on its own layer and in its own values. Cracks run across a mass rather
    # than along it, and a chip takes a bite out of a plane where two of them meet.
    crack = [
        "..a..",
        "..a..",
        ".ab..",
        ".a...",
        "ab...",
        ".a...",
        ".ab..",
        "..a..",
    ]
    for ox, oy in ((28, 24), (9, 26), (47, 32)):
        marks = {(ox + cx, oy + cy)
                 for cy, row in enumerate(crack)
                 for cx, ch in enumerate(row) if ch != "."}
        outside = marks - drawn
        assert not outside, (
            f"the crack at ({ox},{oy}) puts {len(outside)} pixels off the figure: "
            f"{sorted(outside)[:4]}")
        drawing.draw_pixel_map(NAME, crack, {"a": DAMAGE[0], "b": DAMAGE[2]},
                               x=ox, y=oy, layer="damage")
    # Mineral veins: a second material in the stone, which is what stops a carved mass
    # reading as one poured substance.
    vein = ["..c.", ".c..", ".c..", "c..."]
    for ox, oy in ((31, 36), (12, 20), (48, 24)):
        if {(ox + cx, oy + cy) for cy, r in enumerate(vein)
                for cx, ch in enumerate(r) if ch != "."} <= drawn:
            drawing.draw_pixel_map(NAME, vein, {"c": DAMAGE[3]}, x=ox, y=oy,
                                   layer="damage")

    # 3. Occlusion, as a multiply rather than a repaint. The layer holds one flat dark
    # value and the blend works out what each pixel under it becomes, so a contact shadow
    # does not have to know the colour it is darkening.
    shade_cells = []
    for (x, y) in drawn:
        above = FIGURE[y - 1][x] if y > 0 else "."
        if above == "." and (x, y - 1) not in drawn:
            continue
        if FIGURE[y][x] == "u" or above == "u":
            shade_cells.append({"x": x, "y": y})
    for (x, y) in sorted(drawn):
        if FIGURE[y][x] in "fl" and y + 1 < H and FIGURE[y + 1][x] == "u":
            shade_cells.append({"x": x, "y": y})
    drawing.draw_pixels(NAME, shade_cells, OCCLUDE, layer="occlusion")

    # 4. The core, on its own layer so the gem is never flattened into the stone.
    heart = [
        "..c..",
        ".ccc.",
        "cceec",
        ".ccc.",
        "..c..",
    ]
    drawing.draw_pixel_map(NAME, heart, {"c": core[2], "e": core[4]}, x=29, y=27,
                           layer="core")
    drawing.draw_pixel_map(NAME, ["e.e"], {"e": core[4]}, x=30, y=16, layer="core")

    # 5. Emission, on an additive layer. The previous version lifted the stone pixels
    # themselves along the ramp, which worked but spent the stone's own values on it;
    # adding light instead leaves the form underneath intact and produces the in-between
    # colours a single ramp cannot hold.
    bloom = []
    for (x, y) in sorted(drawn):
        d = max(abs(x - 31), abs(y - 29))
        if 1 <= d <= 5:
            bloom.append({"x": x, "y": y,
                          "color": EMIT[0] if d <= 3 else EMIT[1]})
    drawing.draw_pixels(NAME, bloom, layer="emission")

    # 6. A rim light along the shadow-side edge, which is the thing that makes a sprite
    # read against a background instead of sitting on it. Additive and cool, against a
    # warm key, so the two ends of the figure separate by temperature as well as value.
    rim_cells = []
    for (x, y) in sorted(drawn):
        if (x + 1, y) not in drawn or (x, y + 1) not in drawn:
            rim_cells.append({"x": x, "y": y})
    drawing.draw_pixels(NAME, rim_cells, RIM, layer="rim")

    # 7. The outline, weighted by the light and tapered across the terminator. Run on the
    # stone layer, whose silhouette is the figure's.
    outlined = effects.add_outline(
        NAME, stone[0], thickness=2, connectivity=8, where="outside",
        light_angle=LIGHT_ANGLE, lit_thickness=1, layer="stone")
    assert outlined["outline_shadow"] > outlined["outline_lit"], outlined
    if outlined.get("gaps_closed"):
        raise AssertionError(
            f"the outline welded {outlined['gaps_closed']} rows shut: a gap has to be "
            "wider than twice the outline to survive it, so widen the negative space")

    verify(stone, core, shaded)

    out = pathlib.Path(NAME).with_suffix("")
    export.export_png(NAME, f"{out}.png", scale=1, overwrite=True)
    export.export_png(NAME, f"{out}_4x.png", scale=4, overwrite=True)
    print(f"wrote {out}.png: {len(drawn)} drawn pixels, planes "
          f"{shaded['facet_steps']}, {len(bloom)} emission + {len(rim_cells)} rim, outline "
          f"{outlined['outline_shadow']}/{outlined['outline_lit']} shadow/lit")


def verify(stone, core, shaded):
    """What this piece claims, read back off the sprite by the project's own measurements.

    Every assertion is one some previous version of this file would have failed, which is
    the only reason to write one: a check that passes on the art it replaced measures
    nothing.
    """
    report = inspect.assess_sprite(NAME, ramp=stone)
    m = report["metrics"]
    rows = m["row_structure"]

    assert m["edge_contact"] == 0, (
        f"{m['edge_contact']} drawn pixels sit on the canvas border, so the silhouette is "
        "clipped and cannot take an outline there")
    assert rows["waists"] >= 2, f"the silhouette has no pose: {rows}"
    assert rows["rows_with_air"] / rows["rows_drawn"] >= 0.40, (
        f"only {rows['rows_with_air']} of {rows['rows_drawn']} rows have background "
        "between two parts; the limbs have welded to the body")
    assert m["ramp_chroma"]["grey_steps"] == 0, m["ramp_chroma"]
    assert m["ramp_chroma"]["sat_floor"] > 0.15, m["ramp_chroma"]

    low, high = quality.SEPARATOR_BAND
    share = m["separator"]["share"]
    assert low <= share <= high * 2, (
        f"the darkest colour is {share:.1%} of the drawing, outside the {low:.0%} to "
        f"{high:.0%} this style spends on separating masses")
    assert m["colors"] >= 9, f"only {m['colors']} colours in the figure"
    assert m["tone_shares"]["top_share"] < 0.35, (
        f"{m['tone_shares']['top_color']} covers {m['tone_shares']['top_share']:.0%} of "
        "the drawing, so one tone is filling rather than describing")

    found = set()
    for row in inspect.get_pixels(NAME, 0, 0, W, H)["pixels"]:
        found.update(px[:7].lower() for px in row)
    assert core[4].lower() in found, "the core's brightest colour is not in the figure"

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
