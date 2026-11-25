"""Show what `assess_sprite(subject="prop")` changes, on a vase drawn without an outline.

Usage (needs a real Aseprite; point the workspace at a scratch directory, never at a folder
you keep sprites in):

    export ASEPRITE_MCP_WORKSPACE=/tmp/prop-example
    uv run --no-sync python scripts/assess_prop_example.py

What it does: it draws a 32x32 terracotta vase, shaded from the upper left and deliberately
left without a dark keyline, then assesses the same file twice, once with the default
`subject` ("character") and once with `subject="prop"`, and prints the `defects` and
`observations` of each. The drawing is deterministic (no randomness, no clock), so the
output is the same on every run against the same Aseprite.

What to look for: a vase has a narrow neck between a rim and a belly, so the character
reading takes its masses for limbs and its bare edge for a missing keyline, and reports
them. A prop has neither, so `subject="prop"` withholds the limb-separation reading and the
character keyline finding. General findings (art touching the canvas border, pixels off the
declared ramp) are not subject-dependent and appear in both. An unknown `subject` is refused
before anything is launched or written.

This is a reproducible example, not a showcase generator: it publishes nothing, and it is
not listed in `scripts/showcase/README.md` or covered by its byte-for-byte comparison.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aseprite_mcp.tools import drawing, inspect, palette, sprite

NAME = "prop_example/vase.aseprite"
SIZE = 32

# Half the width of each row, from the rim at row 3 to the foot at row 28. A narrow neck
# between the rim and the belly is what gives the figure the waist and the air the
# character readings look for.
PROFILE = {
    3: 6, 4: 6,                                   # rim
    5: 3, 6: 3, 7: 3, 8: 3, 9: 3,                 # neck
    10: 5, 11: 7, 12: 9,                          # shoulder
    13: 10, 14: 11, 15: 11, 16: 11, 17: 11, 18: 11, 19: 10, 20: 10,   # belly
    21: 9, 22: 8, 23: 7, 24: 6, 25: 6,            # taper
    26: 5, 27: 7, 28: 7,                          # foot
}
CENTRE = 15.5


def build_rows(ramp: list[str]) -> tuple[list[str], dict]:
    """The vase as character rows plus a legend: light from the upper left, no outline."""
    last = len(ramp) - 1
    legend = {".": "#00000000"}
    for i, colour in enumerate(ramp):
        legend[str(i)] = colour
    rows = []
    for y in range(SIZE):
        half = PROFILE.get(y)
        cells = []
        for x in range(SIZE):
            if half is None or abs(x + 0.5 - (CENTRE + 0.5)) > half - 0.5 + 0.5:
                cells.append(".")
                continue
            u = (x - CENTRE) / half                      # -1 at the left edge, +1 at the right
            lit = 0.70 - 0.45 * u - 0.10 * (y - 14) / 14  # brighter to the left and up
            index = max(0, min(last, int(lit * (last + 1))))
            if y in (3, 4):                              # the rim catches the light
                index = min(last, index + 1)
            cells.append(str(index))
        rows.append("".join(cells))
    return rows, legend


def show(title: str, result: dict) -> None:
    print(f"\n== {title}")
    for key in ("defects", "observations"):
        items = result[key]
        print(f"{key} ({len(items)}):")
        for text in items:
            print(f"  - {text}")
        if not items:
            print("  (none)")


def main() -> int:
    if "ASEPRITE_MCP_WORKSPACE" not in os.environ:
        print("Set ASEPRITE_MCP_WORKSPACE to a scratch directory first.", file=sys.stderr)
        return 2

    ramp = palette.generate_ramp("#b5653a", steps=5, hue_shift=-14.0, saturation_shift=-10.0,
                                 light_range=0.5, chroma=0.45)["colors"]
    sprite.create_sprite(NAME, SIZE, SIZE, overwrite=True)
    rows, legend = build_rows(ramp)
    drawing.draw_pixel_map(NAME, rows, legend)
    print(f"Drew {NAME} with ramp {ramp}")

    as_character = inspect.assess_sprite(NAME, ramp=ramp)
    as_prop = inspect.assess_sprite(NAME, ramp=ramp, subject="prop")
    show('assess_sprite(subject="character")  [the default]', as_character)
    show('assess_sprite(subject="prop")', as_prop)

    withheld = [t for t in as_character["defects"] + as_character["observations"]
                if t not in as_prop["defects"] + as_prop["observations"]]
    print(f"\nWithheld for a prop: {len(withheld)} reading(s).")
    for text in withheld:
        print(f"  - {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
