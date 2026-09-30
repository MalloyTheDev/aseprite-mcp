"""Redraw the item-sheet showcase: four items, shaded with the current tools."""
from aseprite_mcp.tools import drawing, effects, export, layers, palette, shading, sprite

CELL = 32
ITEMS = ["heart", "coin", "potion", "sword"]
NAME = "items.aseprite"


def ramp(base, **kw):
    return palette.generate_ramp(base, steps=5, hue_shift=kw.pop("hue", -32.0),
                                 saturation_shift=kw.pop("sat", -14.0),
                                 light_range=kw.pop("light", 0.72))["colors"]


RED = ramp("#e8365f")
GOLD = ramp("#f2b632", hue=-26.0)
GLASS = ramp("#6fd6e8", hue=-30.0)
STEEL = ramp("#b9c4d6", hue=-24.0, sat=-30.0, light=0.66)
WOOD = ramp("#8a5a33", hue=-20.0)


def pixels(points):
    return [{"x": x, "y": y} for x, y in sorted(points)]


# Row spans for a heart, written out rather than derived: the notch between the lobes is
# the whole difference between a heart and a spade, and no formula gets it right at 21px.
_HEART_ROWS = {
    7: [(-8, -3), (3, 8)],
    8: [(-9, -2), (2, 9)],
    9: [(-10, -1), (1, 10)],
    10: [(-10, 10)],
    11: [(-10, 10)],
    12: [(-10, 10)],
    13: [(-10, 10)],
    14: [(-9, 9)],
    15: [(-8, 8)],
    16: [(-7, 7)],
    17: [(-6, 6)],
    18: [(-5, 5)],
    19: [(-4, 4)],
    20: [(-3, 3)],
    21: [(-2, 2)],
    22: [(-1, 1)],
}


def heart(ox):
    return {(ox + 16 + dx, y)
            for y, spans in _HEART_ROWS.items()
            for left, right in spans
            for dx in range(left, right + 1)}


def coin(ox):
    pts = set()
    for y in range(7, 26):
        for x in range(ox + 7, ox + 26):
            if ((x - (ox + 16)) / 8.6) ** 2 + ((y - 16) / 9.2) ** 2 <= 1.0:
                pts.add((x, y))
    return pts


def potion_glass(ox):
    pts = set()
    for y in range(13, 27):                  # round flask
        for x in range(ox + 8, ox + 25):
            if ((x - (ox + 16)) / 7.4) ** 2 + ((y - 20) / 7.0) ** 2 <= 1.0:
                pts.add((x, y))
    for y in range(7, 14):                   # neck
        for x in range(ox + 13, ox + 20):
            pts.add((x, y))
    return pts


def potion_liquid(ox):
    return {(x, y) for (x, y) in potion_glass(ox) if y >= 17}


def potion_cork(ox):
    return {(x, y) for y in range(4, 8) for x in range(ox + 12, ox + 21)}


def sword_blade(ox):
    """A tapered blade, point up, centred in the cell."""
    pts = set()
    for y in range(3, 21):
        half = {3: 0, 4: 1, 5: 1}.get(y, 2 if y < 8 else 3)
        for x in range(ox + 16 - half, ox + 16 + half + 1):
            pts.add((x, y))
    return pts


def sword_guard(ox):
    pts = {(x, y) for y in (21, 22) for x in range(ox + 8, ox + 25)}
    pts |= {(x, y) for y in (23,) for x in range(ox + 10, ox + 23)}
    pts |= {(x, y) for y in (29, 30) for x in range(ox + 13, ox + 20)}    # pommel
    return pts


def sword_grip(ox):
    return {(x, y) for y in range(24, 29) for x in range(ox + 14, ox + 19)}


OUTLINE = "#241a2e"

sprite.create_sprite(NAME, CELL * len(ITEMS), CELL, overwrite=True)
layers.rename_layer(NAME, "Layer 1", "items")

# `shade` is False where a part is too thin for a form to be described: the tool says so
# rather than inventing one, and a two-tone edge drawn by hand is the right answer there.
plan = [
    (heart(0), RED[2], RED, True),
    (coin(CELL), GOLD[2], GOLD, True),
    (potion_glass(CELL * 2), GLASS[2], GLASS, True),
    (potion_liquid(CELL * 2), RED[1], RED, True),
    (potion_cork(CELL * 2), WOOD[2], WOOD, False),
    (sword_blade(CELL * 3), STEEL[3], STEEL, True),
    (sword_guard(CELL * 3), GOLD[2], GOLD, False),
    (sword_grip(CELL * 3), WOOD[2], WOOD, False),
]
for points, colour, _, _shade in plan:
    drawing.draw_pixels(NAME, pixels(points), colour)
for points, colour, band, shade in plan:
    if shade:
        shading.shade_region_by_light(NAME, band, base_color=colour, light_angle=130,
                                      light_z=0.6, ambient=0.34, rim=0.18)
        continue
    # Light from the upper left: the top row catches it, the bottom row loses it.
    top = min(y for _, y in points)
    bottom = max(y for _, y in points)
    drawing.draw_pixels(NAME, pixels({(x, y) for x, y in points if y == top}), band[3])
    drawing.draw_pixels(NAME, pixels({(x, y) for x, y in points if y == bottom}), band[1])
# Shading small shapes leaves lone pixels at the band boundaries; assess_sprite
# counts them and this clears them, without touching the dithered or hand-lit rows.
effects.remove_stray_pixels(NAME)
effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside")

export.export_png(NAME, "items.png", scale=6, overwrite=True)
print("wrote items.png")
