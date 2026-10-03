"""Edge run lengths, which are what separates a drawn diagonal from a generated one.

A hand-drawn diagonal is made of runs of consistent length. A 1:2 slope is two pixels,
two pixels, two pixels, held steady, and an artist breaks it only on purpose. A generated
diagonal wanders: runs of 3, 1, 2, 1, 4 where a person would have drawn 2, 2, 2, 2. That
wander is the most recognisable tell in generated pixel art, more than colour and more
than shading, because the eye reads a staircase as a rhythm and hears the stumble.

This project can already measure it. `quality.jaggy_corners` counts 2x2 windows holding
exactly three drawn pixels, which is the shape a step makes, and it reported 59 of them
across the golem's 40x38 silhouette and 37 across the skeleton's 25x31. What that metric
counts, on a boundary that only ever steps one way, is **the number of steps**, whatever
their size: a two-pixel step scores the same one as a one-pixel step. So a boundary with
runs of 3, 1, 2 has three runs and two steps, and merging the stray one-row run into its
neighbour leaves two runs, one step, and one fewer jagged corner. That is the whole
mechanic here, and it is why the gain is measurable rather than asserted.

**What it will and will not touch.** Only a run of exactly one, with a run of at least two
on both sides of it, stepping the same way on both sides, by exactly one pixel each time.
Everything else is left alone, and each reason is counted in the result:

* a one-row run next to another one-row run is a 1:1 diagonal, which is the most
  consistent edge there is, and evening it would be vandalism;
* a one-row run that is further out than both its neighbours is a spike, and one further
  in is a notch. Both are local extrema, both are things somebody drew on purpose (a horn,
  a finger, a chipped corner), and neither is a step;
* a step of more than one pixel is a change of slope, not a stumble;
* an edge belonging to something thinner than `min_span` is a hairline, and thickening it
  would reshape the feature rather than smooth its edge.

**It only ever adds.** A one-row run is merged into whichever neighbour lies further out,
which is always one of the two under the monotonicity rule above, so the fix paints one
pixel and never erases one. That is what keeps the two promises this has to keep: the
bounding box cannot move, because every value written is a value the boundary already
held somewhere else, and nothing can be eaten, because nothing is removed. Both are
checked rather than argued: `plan` measures the box before and after and refuses a plan
that moved it.

Every candidate is also scored before it is accepted, on the same metric the result
reports, over the four 2x2 windows that the one new pixel can possibly change. A candidate
that would not lower the count is counted as skipped and left alone, so the reported
before and after cannot fail to improve, and a pass with nothing left to accept is refused
rather than reported as a success that changed nothing.

Pure: it takes a silhouette as rows of booleans and returns the pixels to paint. No
Aseprite, no MCP, no Lua, no idea what a colour is.
"""
from __future__ import annotations

from .errors import ValidationFailed
from .limits import MAX_PIXEL_LIST_LENGTH
from .quality import Mask, jaggy_corners_in_mask

# The four boundaries, in the order they are walked. Fixed so two runs of the same tool on
# the same sprite propose the same pixels in the same order.
SIDES = ("left", "right", "top", "bottom")

# How long a neighbouring run has to be for a one-row run between two of them to read as a
# stumble rather than as part of the slope. Two, because at one the three runs are a 1:1
# diagonal, which is already the most even edge that exists.
MIN_NEIGHBOUR_RUN = 2

# How thick the thing behind an edge has to be before its edge is treated as an edge. A
# two-pixel limb that gains a pixel is half again as wide, which is a change to the
# drawing; the same pixel on a ten-pixel mass is a change to its outline. Three is the
# smallest value at which the added pixel is a minority of what it joins.
MIN_SPAN = 3


def _check_mask(mask: Mask) -> tuple[int, int]:
    """The mask's width and height, or a refusal naming what is wrong with it."""
    if not isinstance(mask, list) or not mask:
        raise ValidationFailed(
            "mask must be a non-empty list of rows of booleans, one row per pixel row."
        )
    width = len(mask[0])
    if width == 0:
        raise ValidationFailed("mask row 0 is empty, so the silhouette has no width.")
    for index, row in enumerate(mask):
        if len(row) != width:
            raise ValidationFailed(
                f"mask row {index} is {len(row)} wide and row 0 is {width}. A silhouette "
                "has to be rectangular, or the coordinates do not mean anything."
            )
    return width, len(mask)


def _bbox(mask: Mask) -> tuple[int, int, int, int] | None:
    width, height = len(mask[0]), len(mask)
    drawn = [(x, y) for y in range(height) for x in range(width) if mask[y][x]]
    if not drawn:
        return None
    xs = [x for x, _ in drawn]
    ys = [y for _, y in drawn]
    return (min(xs), min(ys), max(xs), max(ys))


def _window(mask: Mask, x: int, y: int, width: int, height: int) -> int:
    """How many of the 2x2 window at (x, y) are drawn, off-canvas counting as not."""
    total = 0
    for cx, cy in ((x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)):
        if 0 <= cx < width and 0 <= cy < height and mask[cy][cx]:
            total += 1
    return total


def _jaggy_delta(mask: Mask, x: int, y: int, width: int, height: int) -> int:
    """What painting (x, y) does to the jagged-corner count, computed locally.

    Exact rather than approximate: a 2x2 window can only change if it contains the pixel
    that changed, and exactly four windows do. Scoring the whole canvas per candidate
    would be correct too and is quadratic in the sprite, which on a 256x256 is the
    difference between a tool and a stall.
    """
    tops = ((x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y))

    def score() -> int:
        return sum(
            1
            for tx, ty in tops
            if 0 <= tx < width - 1 and 0 <= ty < height - 1
            and _window(mask, tx, ty, width, height) == 3
        )

    before = score()
    mask[y][x] = True
    after = score()
    mask[y][x] = False
    return after - before


def _boundary(mask: Mask, side: str, key: int, width: int, height: int):
    """Where the boundary sits on one row or column, and how thick it is there.

    Returns `(value, depth)`: the coordinate of the outermost drawn pixel along `side`,
    and the length of the unbroken run of drawn pixels starting there and heading inward.
    The depth is what the thinness rule reads, and it is deliberately the contiguous run
    rather than the whole row's extent: a row crossing two legs is wide and each leg is
    thin, and thickening a thin leg is the reshaping this must not do.
    """
    if side in ("left", "right"):
        line = [x for x in range(width) if mask[key][x]]
    else:
        line = [y for y in range(height) if mask[y][key]]
    if not line:
        return None
    outward = side in ("left", "top")
    value = min(line) if outward else max(line)
    step = 1 if outward else -1
    depth, probe = 0, value
    limit = width if side in ("left", "right") else height
    while 0 <= probe < limit:
        drawn = mask[key][probe] if side in ("left", "right") else mask[probe][key]
        if not drawn:
            break
        depth += 1
        probe += step
    return (value, depth)


def _runs(mask: Mask, side: str, width: int, height: int):
    """The boundary as runs of equal value, as `(first_key, last_key, value, depth)`.

    A row or column with nothing drawn on it ends the current run rather than being
    skipped over. Two blobs stacked with a clear row between them are two staircases, and
    joining their profiles would invent a step across the gap.
    """
    keys = range(height) if side in ("left", "right") else range(width)
    runs: list[tuple[int, int, int, int]] = []
    for key in keys:
        found = _boundary(mask, side, key, width, height)
        if found is None:
            runs.append((-1, -1, -1, -1))  # a break, dropped below
            continue
        value, depth = found
        if runs and runs[-1][0] != -1 and runs[-1][2] == value and runs[-1][1] == key - 1:
            first, _, _, held = runs[-1]
            runs[-1] = (first, key, value, min(held, depth))
            continue
        runs.append((key, key, value, depth))
    return runs


def plan(mask: Mask, *, min_span: int = MIN_SPAN) -> dict:
    """The pixels to paint to even out this silhouette's edge runs.

    Each entry of `add` carries the pixel to paint and the already-drawn pixel beside it to
    take the colour from, which is the neighbour the run is being merged into. Copying
    rather than choosing keeps the pass on the palette by construction: every pixel written
    is literally a colour the drawing already uses.
    """
    width, height = _check_mask(mask)
    if min_span < 2:
        raise ValidationFailed(
            f"min_span is {min_span}; the minimum is 2. It is how thick a mass has to be "
            "before its edge counts as an edge, and at 1 this would thicken hairlines, "
            "which reshapes a drawing rather than smoothing it."
        )
    box = _bbox(mask)
    if box is None:
        raise ValidationFailed(
            "nothing is drawn in this silhouette, so it has no edges to even out."
        )

    before = jaggy_corners_in_mask(mask)
    working = [list(row) for row in mask]
    add: list[dict] = []
    by_side: dict[str, int] = {}
    examined = 0
    kept = {"diagonal": 0, "feature": 0, "step": 0, "thin": 0, "overlap": 0, "no_gain": 0}

    for side in SIDES:
        # Read once per side, against the silhouette as the earlier sides left it. A merge
        # only ever lengthens a neighbouring run, so a profile that is one merge out of
        # date can miss a candidate and cannot invent one, and missing one is the
        # direction this tool is supposed to err in.
        runs = _runs(working, side, width, height)
        for index in range(1, len(runs) - 1):
            first, last, value, depth = runs[index]
            if first == -1 or last != first:
                continue  # a break in the profile, or a run longer than one
            previous, following = runs[index - 1], runs[index + 1]
            if previous[0] == -1 or following[0] == -1:
                continue  # the run is at the end of its staircase, so it has no pair
            examined += 1
            lengths = (previous[1] - previous[0] + 1, following[1] - following[0] + 1)
            if min(lengths) < MIN_NEIGHBOUR_RUN:
                kept["diagonal"] += 1
                continue
            rises = (previous[2] - value, following[2] - value)
            if rises[0] * rises[1] >= 0:
                # Both neighbours on the same side of this run: a spike or a notch, which
                # is a local extremum and therefore a feature somebody drew.
                kept["feature"] += 1
                continue
            if abs(rises[0]) != 1 or abs(rises[1]) != 1:
                kept["step"] += 1
                continue
            if depth < min_span:
                kept["thin"] += 1
                continue
            outward = -1 if side in ("left", "top") else 1
            target = value + outward
            if side in ("left", "right"):
                px, py, from_x, from_y = target, first, value, first
            else:
                px, py, from_x, from_y = first, target, first, value
            if not (0 <= px < width and 0 <= py < height) or working[py][px]:
                # Off the canvas is unreachable from a monotone staircase, since the value
                # written is one a neighbouring run already holds; already drawn is
                # reachable, when two sides propose the same pixel. Both are skipped rather
                # than trusted, because the alternative to a cheap check is a silent
                # off-canvas write and a double-counted merge.
                kept["overlap"] += 1
                continue
            if _jaggy_delta(working, px, py, width, height) >= 0:
                kept["no_gain"] += 1
                continue
            working[py][px] = True
            add.append({"x": px, "y": py, "from_x": from_x, "from_y": from_y})
            by_side[side] = by_side.get(side, 0) + 1

    after = jaggy_corners_in_mask(working)
    if not add:
        raise ValidationFailed(
            f"no edge run qualified, so this pass would leave the sprite exactly as it "
            f"is. {examined} one-pixel run(s) had a run on either side, and of those: "
            f"{kept['diagonal']} sit next to another one-pixel run (a 1:1 diagonal, which "
            f"is already even), {kept['feature']} are further out or further in than both "
            f"neighbours (a spike or a notch, which is a feature), {kept['step']} step by "
            f"more than one pixel (a change of slope), {kept['thin']} belong to something "
            f"thinner than min_span {min_span}, {kept['overlap']} land on a pixel another "
            f"side already took, and {kept['no_gain']} would not lower the jagged-corner "
            f"count of {before}. A silhouette this tool cannot improve is the usual case "
            "for art that was drawn rather than generated."
        )
    if len(add) > MAX_PIXEL_LIST_LENGTH:
        # The same ceiling a character map is held to, and reachable by the same route: a
        # comb-shaped silhouette on a large canvas has a boundary far longer than its area
        # suggests, and the plan is one write per merge.
        raise ValidationFailed(
            f"this silhouette's edges yield {len(add)} merges; the maximum per call is "
            f"{MAX_PIXEL_LIST_LENGTH}. Scope the pass to part of the sprite with a "
            "selection, or normalise a smaller sprite."
        )
    moved = _bbox(working)
    if moved != box:
        raise ValidationFailed(
            f"this plan would move the silhouette's extent from {box} to {moved}, which "
            "this pass promises not to do. Nothing was written. Please report the "
            "silhouette that caused it."
        )
    return {
        "add": add,
        "runs_examined": examined,
        "runs_merged": len(add),
        "jaggy_before": before,
        "jaggy_after": after,
        "bbox": list(box),
        "by_side": by_side,
        # Absent rather than zero, so a reason that is present is a reason that fired.
        "kept": {reason: count for reason, count in kept.items() if count},
    }
