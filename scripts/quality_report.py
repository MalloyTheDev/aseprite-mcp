"""Score sprites on the computable quality metrics.

Usage:
    uv run python scripts/quality_report.py sprite.aseprite [more.aseprite ...]
    uv run python scripts/quality_report.py --ramp "#2a1a1a,#603030,#a05050" hero.aseprite
    uv run python scripts/quality_report.py --json sprite.aseprite

The metrics are guardrails against regression, not a quality score. Read
`aseprite_mcp.core.quality` for what they can and cannot see before drawing conclusions
from them, and compare two versions of the same sprite rather than two different sprites.

Needs a real Aseprite, because it reads pixels back through the server's own tools rather
than decoding the file format itself. Reading through the same path a model uses means
the numbers describe what a model would actually see.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aseprite_mcp.core import quality
from aseprite_mcp.tools import inspect as inspect_tools

# get_pixels caps a single read at 4096 pixels, so anything bigger is read in tiles and
# stitched. 64x64 is the largest square that fits the cap.
_TILE = 64


def read_grid(filename: str, frame: int = 1) -> quality.Grid:
    """Read a whole sprite as a pixel grid, tiling around the per-call read cap."""
    info = inspect_tools.get_sprite_info(filename)
    width, height = int(info["width"]), int(info["height"])
    grid: quality.Grid = [["#00000000"] * width for _ in range(height)]

    for top in range(0, height, _TILE):
        for left in range(0, width, _TILE):
            tile_w = min(_TILE, width - left)
            tile_h = min(_TILE, height - top)
            chunk = inspect_tools.get_pixels(
                filename, left, top, tile_w, tile_h, frame=frame
            )
            for y, row in enumerate(chunk["pixels"]):
                grid[top + y][left:left + tile_w] = row[:tile_w]
    return grid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sprites", nargs="+", help="Sprite paths, workspace-relative.")
    parser.add_argument(
        "--ramp",
        help="Comma-separated colours. Enables palette conformance, the fraction of "
             "pixels that are exactly on the ramp.",
    )
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args()

    ramp = [c.strip() for c in args.ramp.split(",")] if args.ramp else None
    report = {}
    for name in args.sprites:
        report[name] = quality.score(read_grid(name, args.frame), ramp)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    for name, metrics in report.items():
        print(f"\n{name}")
        for key, value in metrics.items():
            print(f"  {key:22} {value}")
    print(
        "\nGuardrails, not a score. They cannot see whether the sprite reads as what it "
        "is meant to be,\nwhether the light direction is coherent, or whether shading "
        "follows the form."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
