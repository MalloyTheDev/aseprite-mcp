"""Rebuild the baked corpus PNGs from the art that lives elsewhere in this repository.

Run from the repository root:

    uv run --no-sync python tests/corpus/regenerate.py

The corpus is baked rather than read live from `workspace/` and `docs/assets/showcase/`
for two reasons. The first is scale: those files are written at 1x to 8x zoom for looking
at, and measuring the zoom instead of the art gives `isolated_pixels` of zero on an 8x
upscale, because every pixel there has 63 identical neighbours. The second is that they are
regenerated. `scripts/showcase/golem.py` rewrites `workspace/golem.png`, and the known-bad
end of a labelled set cannot be a file that changes underneath the labels; the git history
already contains a commit that regenerated the golem because an outline change moved its
keyline. A baked copy at 1x is a few kilobytes and holds still.

`docs/assets/showcase/quantize_stages.png` is deliberately **not** baked, although it was
offered as a known-good source. It is a three-panel before-and-after sheet showing what
quantisation does, so at least one of its panels is worse art on purpose, and that is the
whole point of the image. Labelling all three panels "good" would put known-degraded art
into the clean set, where it would show up as an irreducible false-positive rate in every
measure at once and be blamed on the measures.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from loader import load_grid, save_grid, split_cells, split_panels  # noqa: E402

# (source, scale, splitter, names). The scale is written down rather than detected, so that
# a source re-exported at a different zoom fails loudly here instead of quietly producing a
# corpus at the wrong resolution.
GOOD_SOURCES = (
    ("workspace/orb_3_full.png", 8, None, ("good_orb",)),
    ("docs/assets/showcase/dungeon.png", 5, None, ("good_dungeon",)),
    (
        "docs/assets/showcase/item_sheet.png",
        5,
        ("cells", 5),
        tuple(f"good_item_{i}" for i in range(5)),
    ),
    ("docs/assets/showcase/attack_sheet.png", 1, ("panels", 0), ()),
)
BAD_SOURCES = (
    ("workspace/golem.png", 1, None, ("bad_golem",)),
    ("assets/skeleton.png", 8, None, ("bad_skeleton",)),
)


def _split(grid, splitter):
    if splitter is None:
        return [grid]
    kind, count = splitter
    return split_cells(grid, count) if kind == "cells" else split_panels(grid)


def main() -> int:
    written = 0
    for source, scale, splitter, names in GOOD_SOURCES + BAD_SOURCES:
        path = ROOT / source
        if not path.exists():
            print(f"MISSING {source}")
            return 1
        grid = load_grid(path, scale=scale)
        pieces = _split(grid, splitter)
        prefix = "good_attack" if not names else None
        for index, piece in enumerate(pieces):
            name = names[index] if names else f"{prefix}_{index}"
            out = HERE / f"{name}.png"
            save_grid(piece, out)
            written += 1
            print(f"{out.name:22s} {len(piece[0])}x{len(piece)}  from {source}")
    print(f"\n{written} file(s) written to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
