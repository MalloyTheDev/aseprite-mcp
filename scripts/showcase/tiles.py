"""Redraw the tilemap showcase: four hand-painted tiles and a small scene."""
import random

from aseprite_mcp.tools import export, tilemap, workflow

NAME = "scene.aseprite"
TS, COLS, ROWS = 16, 12, 8
LAYER = "tiles"

GRASS = ["#3f7d3a", "#4f9a44", "#63b451", "#87cf63"]
DIRT = ["#5b3f2c", "#75543a", "#8d6749", "#a67f5c"]
WATER = ["#1f5e86", "#2b7aa8", "#3f9ac6", "#7fc9e6"]
STONE = ["#4a4f5c", "#636b7a", "#7d8695", "#9aa3b2"]

rng = random.Random(7)


def scatter(rows, colours, weights, seed_offset=0, block=2):
    """Variation in small blocks rather than per pixel.

    A different colour chosen for every pixel independently is static, not texture: at
    1x it reads as dirt and assess_sprite counts nearly every pixel as isolated. Picking
    per 2x2 block keeps the variation and gives each patch neighbours of its own colour.
    """
    local = random.Random(11 + seed_offset)
    out = []
    for by in range(0, TS, block):
        for bx in range(0, TS, block):
            roll = local.random()
            total = 0.0
            chosen = colours[-1]
            for colour, weight in zip(colours, weights, strict=True):
                total += weight
                if roll < total:
                    chosen = colour
                    break
            for y in range(by, min(by + block, TS)):
                for x in range(bx, min(bx + block, TS)):
                    out.append({"x": x, "y": y, "color": chosen})
    return out


made = workflow.create_tileset_project(NAME, tile_size=TS, columns=COLS, rows=ROWS)
index = {t["name"]: t["index"] for t in made["tilemap"]["tiles"]}
print("tiles:", index)

# --- grass: a dark base, lit blades, and a bright tip here and there ------------------
grass = scatter(TS, [GRASS[1], GRASS[2]], [0.55, 0.45])
for _ in range(26):
    x, y = rng.randrange(TS), rng.randrange(1, TS)
    grass += [{"x": x, "y": y, "color": GRASS[3]}, {"x": x, "y": y - 1, "color": GRASS[3]}]
for _ in range(18):
    grass.append({"x": rng.randrange(TS), "y": rng.randrange(TS), "color": GRASS[0]})
tilemap.paint_tile_pixels(NAME, LAYER, index["grass"], grass)

# --- dirt: clods and pebbles ---------------------------------------------------------
dirt = scatter(TS, [DIRT[1], DIRT[2]], [0.6, 0.4], seed_offset=3)
for _ in range(14):
    x, y = rng.randrange(TS - 1), rng.randrange(TS - 1)
    dirt += [{"x": x, "y": y, "color": DIRT[0]}, {"x": x + 1, "y": y, "color": DIRT[0]},
             {"x": x, "y": y + 1, "color": DIRT[3]}]
tilemap.paint_tile_pixels(NAME, LAYER, index["dirt"], dirt)

# --- water: bands plus a couple of highlight dashes ----------------------------------
water = []
for y in range(TS):
    band = WATER[0] if y % 6 in (0, 1) else (WATER[1] if y % 6 in (2, 3) else WATER[2])
    water += [{"x": x, "y": y, "color": band} for x in range(TS)]
for y, x0 in ((3, 2), (3, 9), (9, 5), (9, 12), (14, 1)):
    water += [{"x": (x0 + d) % TS, "y": y, "color": WATER[3]} for d in range(3)]
tilemap.paint_tile_pixels(NAME, LAYER, index["water"], water)

# --- stone: blocks with a lit top edge and a dark joint ------------------------------
stone = scatter(TS, [STONE[1], STONE[2]], [0.5, 0.5], seed_offset=5)
for y in (0, 8):
    stone += [{"x": x, "y": y, "color": STONE[3]} for x in range(TS)]
for y in (7, 15):
    stone += [{"x": x, "y": y, "color": STONE[0]} for x in range(TS)]
for x, y0 in ((7, 0), (3, 8), (11, 8)):
    stone += [{"x": x, "y": y0 + d, "color": STONE[0]} for d in range(8)]
tilemap.paint_tile_pixels(NAME, LAYER, index["stone"], stone)

# --- the scene -----------------------------------------------------------------------
pond = {(c, r) for c in range(4, 8) for r in range(3, 6)} | {(3, 4), (8, 4)}
path = {(c, 6) for c in range(COLS)} | {(2, r) for r in range(2, 7)}
tiles = []
for r in range(ROWS):
    for c in range(COLS):
        if (c, r) in pond:
            which = "water"
        elif (c, r) in path:
            which = "stone"
        elif r <= 1:
            which = "grass"
        else:
            which = "dirt" if (c + r) % 5 == 0 or r >= 7 else "grass"
        tiles.append({"column": c, "row": r, "index": index[which]})
tilemap.set_tiles(NAME, LAYER, tiles)

export.export_png(NAME, "scene.png", scale=2, overwrite=True)
print("wrote scene.png")
