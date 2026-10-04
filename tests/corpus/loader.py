"""Getting pixel art off disk and into the grid shape the metrics read.

The showcase PNGs in this repository are written at an integer zoom, because they exist to
be looked at: the reference orb is a 32x32 sprite stored as a 256x256 image. Measuring that
file directly would be measuring the zoom. `isolated_pixels` on an 8x upscale is zero by
construction, because every pixel has 63 identical neighbours, and `jaggy_corners` counts
the steps of the magnified staircase rather than the drawn one. So the scale has to come
off first, and `detect_scale` finds it rather than taking it on trust from a filename.

Pillow is used here and nowhere in `core/`. The gate machinery in
`core/validation.py` takes scores, not images, which is what keeps `core/` on the standard
library.
"""

from __future__ import annotations

import pathlib

from PIL import Image

Grid = list[list[str]]

# Sprites in this repository are shown at 1x to 8x. Searching past 16 costs nothing and
# buys nothing, and a bound keeps the scan from reporting a huge scale for a flat image.
MAX_SCALE = 16


def detect_scale(image: Image.Image, limit: int = MAX_SCALE) -> int:
    """The largest integer k for which every kxk block of the image is one flat colour.

    That is exactly the nearest-neighbour zoom the file was written at, for any art with a
    single non-uniform block anywhere in it. A perfectly flat image has no largest k, and
    this reports `limit` for one, which is why the caller for a flat test image passes the
    scale explicitly instead.
    """
    width, height = image.size
    pixels = image.load()
    best = 1
    for k in range(2, limit + 1):
        if width % k or height % k:
            continue
        uniform = True
        for by in range(0, height, k):
            for bx in range(0, width, k):
                first = pixels[bx, by]
                for dy in range(k):
                    for dx in range(k):
                        if pixels[bx + dx, by + dy] != first:
                            uniform = False
                            break
                    if not uniform:
                        break
                if not uniform:
                    break
            if not uniform:
                break
        if uniform:
            best = k
    return best


def load_grid(path: str | pathlib.Path, scale: int | None = None) -> Grid:
    """A PNG as rows of "#RRGGBBAA", at its drawn resolution rather than its stored one."""
    with Image.open(path) as handle:
        image = handle.convert("RGBA")
        k = scale or detect_scale(image)
        pixels = image.load()
        width, height = image.size
        return [
            ["#{:02x}{:02x}{:02x}{:02x}".format(*pixels[x * k, y * k]) for x in range(width // k)]
            for y in range(height // k)
        ]


def save_grid(grid: Grid, path: str | pathlib.Path) -> None:
    """Write a grid back out at 1x, which is how the baked corpus files are stored."""
    height = len(grid)
    width = len(grid[0]) if height else 0
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    for y, row in enumerate(grid):
        for x, color in enumerate(row):
            c = color.lstrip("#")
            pixels[x, y] = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16))
    image.save(path, optimize=True)


def _fully_transparent_column(grid: Grid, x: int) -> bool:
    return all(row[x].lstrip("#")[6:8] == "00" for row in grid)


def split_panels(grid: Grid) -> list[Grid]:
    """Split a contact sheet on its fully transparent columns.

    The sheets in `docs/assets/showcase` separate their panels with a transparent gutter,
    so the gutter is the delimiter and no panel width has to be assumed. Assuming one is
    how a five-frame strip gets read as seven, and every frame after the first then carries
    a slice of its neighbour, which measures as stray pixels on the edge of every panel.
    """
    height = len(grid)
    width = len(grid[0]) if height else 0
    panels: list[Grid] = []
    start: int | None = None
    for x in range(width):
        if _fully_transparent_column(grid, x):
            if start is not None:
                panels.append([row[start:x] for row in grid])
                start = None
        elif start is None:
            start = x
    if start is not None:
        panels.append([row[start:width] for row in grid])
    return panels


def split_cells(grid: Grid, count: int) -> list[Grid]:
    """Split a sheet into `count` equal columns, for a sheet with no gutter to split on."""
    height = len(grid)
    width = len(grid[0]) if height else 0
    if count <= 0 or width % count:
        raise ValueError(f"cannot split a {width}px sheet into {count} equal cells")
    cell = width // count
    return [[row[i * cell:(i + 1) * cell] for row in grid] for i in range(count)]
