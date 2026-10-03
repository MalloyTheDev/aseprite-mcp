"""Occlusion between two masses of the same material, which colour cannot find.

`contact_shadow` is ambient occlusion along a ramp and it works: a line one or two steps
darker where two shapes touch, which is what stops a shaded object looking like it is
floating in front of the thing it is standing on. It finds the thing doing the occluding by
colour, though, with `occluder_color`, and that is exactly the case a figure does not
present. An arm against a torso, a pauldron over a shoulder, a thigh against a hip: both
sides are the same stone, lit by the same light, and there is no colour that separates
them. Measured on this project's golem, an armpit where a real artist darkens the contact
came out +131 in luminance, because nothing in the toolkit could see the seam.

What a colour cannot say, the caller can, and the notation already exists: a character
grid, one character per pixel, which is what `draw_pixel_map` and `shade_facets` take. A
map whose legend names colours draws a picture and a map whose legend names directions
describes a solid; a map whose legend names **masses** says which part of the figure each
pixel belongs to, which is the one fact the pixels cannot carry themselves.

Occlusion is asymmetric, so the legend gives each mass a `z`: higher is nearer the viewer.
The arm in front of the torso darkens the torso and not itself, which is why a legend of
bare labels would not be enough. That asymmetry is also the difference between this and a
drawn line: darken both sides of a seam and you have drawn brickwork; darken the side
behind and you have put one mass in front of another.

The falloff is the same curve `contact_shadow` uses, deliberately, so the two agree about
what "one step at the contact, tapering to nothing at the radius" means. A hard one-pixel
line at full depth reads as a drawn edge rather than as contact, which is the failure this
is shaped to avoid: the workaround in this project's golem generator slammed seam pixels
two steps down at a fixed width and the result read as masonry.

Pure: it takes rows of characters and returns which pixels to darken and by how much. It
knows nothing about colours, ramps, Aseprite or MCP; what a ramp step is remains the tool
layer's business.
"""
from __future__ import annotations

import math

from .errors import ValidationFailed
from .limits import MAX_PIXEL_LIST_LENGTH
from .pixelmap import TRANSPARENT_CHAR, read_rows

# A seam needs two masses. One mass is a silhouette, and a pass over it would find no
# occluder and darken nothing.
MIN_MASSES = 2


def _check_legend(legend: dict) -> dict[str, float]:
    """The legend as {character: z}, higher being nearer the viewer."""
    if not isinstance(legend, dict) or not legend:
        raise ValidationFailed(
            "legend must be a non-empty mapping of one-character symbols to a z, where a "
            "higher z is nearer the viewer: {\"a\": 1, \"b\": 0} says mass 'a' is in "
            "front of mass 'b', so the seam darkens on 'b'."
        )
    resolved: dict[str, float] = {}
    for symbol, value in legend.items():
        if not isinstance(symbol, str) or len(symbol) != 1:
            raise ValidationFailed(
                f"legend key {symbol!r} is not a single character. A map is read one "
                "character per pixel, so every key has to be exactly one."
            )
        if symbol == TRANSPARENT_CHAR:
            raise ValidationFailed(
                f"legend defines {TRANSPARENT_CHAR!r}, which already means 'not part of "
                "any mass' and cannot be given a z. Use another character for the mass."
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationFailed(
                f"legend[{symbol!r}] is {value!r}, which is not a z. A mass's z is a "
                "number, and a higher one is nearer the viewer: the mass in front "
                "darkens the one behind it, not the other way round."
            )
        if not math.isfinite(float(value)):
            raise ValidationFailed(f"legend[{symbol!r}] is {value!r}; a z has to be finite.")
        resolved[symbol] = float(value)
    return resolved


def plan(
    rows,
    legend: dict,
    *,
    radius: int,
    depth: int,
    origin_x: int = 0,
    origin_y: int = 0,
) -> dict:
    """Which pixels a seam occludes and by how many ramp steps each.

    Returns `darken` as a list of `{"x", "y", "steps"}` in sprite coordinates, plus what
    the map said about itself: the pixel count per mass, the z each symbol resolved to, and
    how many pixels took each step count so a flat band cannot be mistaken for a falloff.
    """
    lines, width, height = read_rows(rows)
    if radius < 1:
        raise ValidationFailed(
            f"radius is {radius}; the minimum is 1. It is how far the darkening reaches "
            "from the seam, and at 0 there is no seam to reach from."
        )
    if depth < 1:
        raise ValidationFailed(
            f"depth is {depth}; the minimum is 1 ramp step. A pass that moves a pixel "
            "zero steps along its ramp leaves the sprite exactly as it was."
        )
    resolved = _check_legend(legend)

    # Where each mass is, and which z it sits at. One pass, because every test below is a
    # question about one pixel's neighbourhood and the neighbourhood is read many times.
    owner: dict[tuple[int, int], str] = {}
    counts: dict[str, int] = {}
    for row_index, line in enumerate(lines):
        for col_index, symbol in enumerate(line):
            if symbol == TRANSPARENT_CHAR:
                continue
            if symbol not in resolved:
                known = "".join(sorted(resolved))
                raise ValidationFailed(
                    f"rows[{row_index}][{col_index}] is {symbol!r}, which the legend does "
                    f"not define. The legend has {known!r} plus {TRANSPARENT_CHAR!r} for "
                    "a pixel that belongs to no mass. A character with no mass is refused "
                    "rather than skipped, because a typo in a grid would otherwise leave "
                    "a seam unshaded and report success."
                )
            owner[(col_index, row_index)] = symbol
            counts[symbol] = counts.get(symbol, 0) + 1

    if len(counts) < MIN_MASSES:
        named = ", ".join(sorted(counts)) or "none"
        raise ValidationFailed(
            f"the map uses {len(counts)} mass(es) ({named}); occlusion needs at least "
            f"{MIN_MASSES}, because it darkens where one mass meets another. One mass is "
            "a silhouette, and contact_shadow is the tool for a mass meeting something "
            "of a different colour."
        )
    present = {symbol: resolved[symbol] for symbol in counts}
    if len(set(present.values())) == 1:
        landed = next(iter(set(present.values())))
        raise ValidationFailed(
            f"all {len(present)} masses in the map sit at z {landed:g}, so none of them is "
            "in front of another and nothing would be occluded. Occlusion is asymmetric: "
            "raise the z of the mass that overlaps, and the seam darkens on the one "
            "behind it."
        )

    offsets = [
        (dx, dy, math.sqrt(dx * dx + dy * dy))
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if (dx, dy) != (0, 0) and math.sqrt(dx * dx + dy * dy) <= radius
    ]

    darken: list[dict] = []
    by_steps: dict[int, int] = {}
    in_reach = 0
    for (x, y), symbol in sorted(owner.items(), key=lambda item: (item[0][1], item[0][0])):
        mine = resolved[symbol]
        nearest = None
        for dx, dy, distance in offsets:
            other = owner.get((x + dx, y + dy))
            if other is None or resolved[other] <= mine:
                continue
            if nearest is None or distance < nearest:
                nearest = distance
        if nearest is None:
            continue
        in_reach += 1
        # The curve `contact_shadow` uses, to the letter: full depth against the seam,
        # tapering to nothing at the radius. Shared so the two tools cannot disagree about
        # what a contact falloff is.
        falloff = min(1.0, 1.0 - (nearest - 1) / max(1, radius))
        steps = math.floor(depth * falloff + 0.5)
        if steps <= 0:
            continue
        darken.append({"x": origin_x + x, "y": origin_y + y, "steps": steps})
        by_steps[steps] = by_steps.get(steps, 0) + 1

    if not darken:
        raise ValidationFailed(
            f"no pixel of any mass lies within {radius} of a nearer mass, so this pass "
            f"would darken nothing. The map holds "
            f"{', '.join(f'{sym} ({n} px at z {present[sym]:g})' for sym, n in sorted(counts.items()))}"
            ". Either the masses do not touch, in which case raise radius, or the one you "
            "meant to put in front has the lower z."
        )
    if len(darken) > MAX_PIXEL_LIST_LENGTH:
        raise ValidationFailed(
            f"the seams in this map occlude {len(darken)} pixels; the maximum per call is "
            f"{MAX_PIXEL_LIST_LENGTH}. Split the map into bands and give each one an "
            "origin, the way a large character map is drawn."
        )
    return {
        "darken": darken,
        "masses": dict(sorted(counts.items())),
        "depths": {symbol: present[symbol] for symbol in sorted(present)},
        "pixels_in_reach": in_reach,
        "by_steps": dict(sorted(by_steps.items())),
        "width": width,
        "height": height,
    }


def flat_band_note(by_steps: dict[int, int], *, radius: int, depth: int) -> str | None:
    """Why a falloff that was asked for came out as one flat band, when it did.

    A hard line of uniform darkness at the seam reads as drawn brickwork rather than as one
    mass sitting in front of another, and the arithmetic that produces one is quiet: at
    `radius=2, depth=1` the two distances round to the same single step, so the pass does
    exactly what a 2px line would do and reports a falloff it did not deliver. Surfaced
    rather than refused, because a flat band at `radius=1` is a legitimate thing to ask for
    and the caller is the only one who knows which they wanted.
    """
    if radius <= 1 or len(by_steps) > 1:
        return None
    return (
        f"every darkened pixel moved the same {next(iter(by_steps))} step(s), so this is a "
        f"flat band {radius} pixels wide rather than a falloff: at depth {depth} over "
        f"radius {radius} the distances round to one value. A hard line of uniform "
        f"darkness reads as drawn brickwork; raise depth to at least {radius} so the near "
        "pixels go further down the ramp than the far ones."
    )
