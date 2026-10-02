"""Ramp arithmetic: building one from its ends, and recovering one from art.

Every shading tool in this server takes a `ramp` argument, and until now the only way to
get one was `generate_ramp`, which grows a ramp outward from a single base colour. Two
other starting points are at least as common and had nothing:

  * a ramp is usually *stated as its ends*, a deliberate cool shadow and a warm highlight,
    with the middle interpolated. Reaching those ends by guessing `hue_shift` is working
    backwards;
  * art that already has a ramp cannot give it back. `extract_palette` reports the colours
    as a set, unordered, which is not a ramp and cannot be handed to a shading tool.

Pure arithmetic, no Aseprite and no MCP: the colour maths is worth testing without an
editor, and the clustering is worth testing against numbers rather than against pictures.
"""

from __future__ import annotations

import colorsys
import math

# Weighted luminance, the same 0.299/0.587/0.114 the ramp matching in shading.py uses, so
# a step chosen here and a step matched there agree about which is darker.
_LUMA = (0.299, 0.587, 0.114)

# Colours of the same brightness but very different hue are two materials sharing a
# sprite, not two steps of one ramp. Hue spread *across* a ramp says nothing, because a
# cool shadow to a warm highlight legitimately crosses half the wheel; spread *within one
# brightness* is the signal.
MAX_WITHIN_BAND_HUE_SPREAD = 60.0
# Below this saturation the hue is noise, so the spread check has nothing to say.
MIN_MEANINGFUL_SATURATION = 0.12


def luminance(rgb: tuple[int, int, int]) -> float:
    """0..1, weighted for the eye rather than the arithmetic mean."""
    return sum(w * c for w, c in zip(_LUMA, rgb, strict=True)) / 255.0


# ------------------------------------------------------------------------------ Oklab
# Interpolating a ramp in RGB darkens and greys the middle; interpolating hue rotates a
# blue-to-cream ramp through magenta, because at that distance both ways round the wheel
# are equally "short". Oklab is a perceptual space where a straight line between two
# colours is the blend a person would draw, so the middle of a ramp lands where a pixel
# artist would put it and the ends keep their hue.


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def to_oklab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c / 255) for c in rgb)
    long_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    medium = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    short = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    lp, mp, sp = (math.copysign(abs(v) ** (1 / 3), v) for v in (long_, medium, short))
    return (
        0.2104542553 * lp + 0.7936177850 * mp - 0.0040720468 * sp,
        1.9779984951 * lp - 2.4285922050 * mp + 0.4505937099 * sp,
        0.0259040371 * lp + 0.7827717662 * mp - 0.8086757660 * sp,
    )


def from_oklab(lab: tuple[float, float, float]) -> tuple[int, int, int]:
    lightness, a, b = lab
    lp = lightness + 0.3963377774 * a + 0.2158037573 * b
    mp = lightness - 0.1055613458 * a - 0.0638541728 * b
    sp = lightness - 0.0894841775 * a - 1.2914855480 * b
    long_, medium, short = (v**3 for v in (lp, mp, sp))
    r = 4.0767416621 * long_ - 3.3077115913 * medium + 0.2309699292 * short
    g = -1.2684380046 * long_ + 2.6097574011 * medium - 0.3413193965 * short
    bl = -0.0041960863 * long_ - 0.7034186147 * medium + 1.7076147010 * short
    return tuple(
        max(0, min(255, round(_linear_to_srgb(max(0.0, min(1.0, c))) * 255)))
        for c in (r, g, bl)
    )


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{c:02x}" for c in rgb)


def interpolate(
    shadow: tuple[int, int, int],
    light: tuple[int, int, int],
    steps: int,
    easing: str = "perceptual",
) -> list[str]:
    """A ramp from its two ends, darkest first.

    The ends come back exactly as given: they were chosen, and a ramp whose endpoints are
    approximations of the caller's own colours is not the ramp that was asked for.

    `perceptual` walks the straight line between them in Oklab, so the middle steps are
    evenly spaced to the eye and the ramp keeps its hue rather than rotating through it.
    `linear` is the naive sRGB blend, which is what most tools do and which tends to
    darken and grey the middle; it is here for when that is what is wanted.
    """
    if steps < 2:
        raise ValueError("a ramp needs at least 2 steps")
    if easing not in ("linear", "perceptual"):
        raise ValueError(f"unknown easing {easing!r}; expected 'linear' or 'perceptual'")

    out: list[str] = []
    if easing == "perceptual":
        start, end = to_oklab(shadow), to_oklab(light)
        for index in range(steps):
            t = index / (steps - 1)
            out.append(_hex(from_oklab(tuple(
                a + (b - a) * t for a, b in zip(start, end, strict=True)
            ))))
    else:
        for index in range(steps):
            t = index / (steps - 1)
            out.append(_hex(tuple(
                round(a + (b - a) * t) for a, b in zip(shadow, light, strict=True)
            )))
    out[0] = _hex(shadow)
    out[-1] = _hex(light)
    return out


# ------------------------------------------------------------------ recovering a ramp


def _weighted_quantiles(points: list[tuple[float, int]], count: int) -> list[float]:
    """Starting centroids at even shares of the *pixels*, not of the colour list.

    Splitting the luminance range evenly puts centroids where no pixels are whenever the
    art is bunched, which is most art.
    """
    total = sum(weight for _, weight in points)
    marks, seen, index = [], 0, 0
    for step in range(count):
        target = total * (step + 0.5) / count
        while index < len(points) - 1 and seen + points[index][1] < target:
            seen += points[index][1]
            index += 1
        marks.append(points[index][0])

    # Quantiles collapse onto each other when a few colours carry most of the pixels,
    # and two centroids at the same luminance leave a band empty: a five-colour palette
    # asked for five steps then comes back with four. Fall back to even spacing over the
    # colours themselves, which always starts them apart.
    if len(set(marks)) < count and len({lum for lum, _ in points}) >= count:
        marks = [
            points[round(i * (len(points) - 1) / (count - 1))][0] for i in range(count)
        ]
    return marks


def cluster_by_luminance(histogram: dict[str, int], steps: int) -> dict:
    """Group the colours an artwork uses into `steps` bands, dark to light.

    `histogram` maps "#rrggbb" to how many pixels use it. Returns the representative
    colour of each band (the one the most pixels use, because that is the colour the art
    reads as), the share of the art each band covers, and any warning about whether these
    colours are a ramp at all.

    One-dimensional k-means over luminance, weighted by pixel count, started at weighted
    quantiles and run to a fixed point. Deterministic: the same art gives the same ramp.
    """
    if steps < 2:
        raise ValueError("a ramp needs at least 2 steps")
    colours = {c: n for c, n in histogram.items() if n > 0}
    if not colours:
        return {"colors": [], "coverage": [], "warnings": ["Nothing is drawn here."]}

    points = sorted(
        ((luminance(_rgb(c)), n, c) for c, n in colours.items()),
        key=lambda item: item[0],
    )
    warnings: list[str] = []
    if len(points) < steps:
        warnings.append(
            f"The art uses {len(points)} colour(s), fewer than the {steps} steps asked "
            "for, so the ramp is as long as the art allows rather than as long as asked."
        )
        steps = len(points)
    if steps < 2:
        only = points[0][2]
        return {"colors": [only], "coverage": [1.0], "warnings": warnings}

    centroids = _weighted_quantiles([(lum, n) for lum, n, _ in points], steps)
    buckets: list[list[tuple[float, int, str]]] = []
    for _ in range(24):
        buckets = [[] for _ in centroids]
        for lum, n, colour in points:
            nearest = min(range(len(centroids)), key=lambda i: abs(centroids[i] - lum))
            buckets[nearest].append((lum, n, colour))
        moved = False
        for i, bucket in enumerate(buckets):
            if not bucket:
                continue
            weight = sum(n for _, n, _ in bucket)
            centre = sum(lum * n for lum, n, _ in bucket) / weight
            if abs(centre - centroids[i]) > 1e-6:
                centroids[i], moved = centre, True
        if not moved:
            break

    total = sum(n for _, n, _ in points)
    # k-means moves its centroids, and nothing keeps them in the order they started in.
    # A ramp that is not ordered dark to light is not a ramp, so sort before reporting.
    ordered = sorted(
        (bucket for bucket in buckets if bucket),
        key=lambda bucket: sum(lum * n for lum, n, _ in bucket)
        / sum(n for _, n, _ in bucket),
    )
    colors, coverage = [], []
    for bucket in ordered:
        # The colour most of the band's pixels use, not the centroid: a representative
        # that is not in the art is a colour the caller cannot match anything against.
        colors.append(max(bucket, key=lambda item: item[1])[2])
        coverage.append(round(sum(n for _, n, _ in bucket) / total, 3))

    clash = _same_brightness_hue_clash(points, total)
    if clash is not None:
        warnings.append(
            f"Colours of the same brightness differ in hue by about {clash:.0f} degrees, "
            "so this art is several materials rather than one ramp. Scope the read to one "
            "of them with a layer, or shade them one at a time."
        )
    return {"colors": colors, "coverage": coverage, "warnings": warnings}


# Two colours this close in brightness are the same step of a ramp, so a large hue gap
# between them is two materials rather than a hue-shifted ramp. Spread *along* a ramp
# says nothing: a cool shadow to a warm highlight legitimately crosses half the wheel.
SAME_BRIGHTNESS = 0.08
# Colours covering less of the art than this are anti-aliasing and stray pixels, not
# materials, and comparing them produces a warning about nothing.
MATERIAL_SHARE = 0.02


def _same_brightness_hue_clash(
    points: list[tuple[float, int, str]], total: int
) -> float | None:
    """The worst hue gap between two colours of near-equal brightness, if any."""
    material = [
        (lum, colour) for lum, n, colour in points
        if n >= total * MATERIAL_SHARE and _saturated(colour)
    ]
    worst = None
    for index, (lum_a, colour_a) in enumerate(material):
        for lum_b, colour_b in material[index + 1:]:
            if abs(lum_a - lum_b) > SAME_BRIGHTNESS:
                continue
            gap = _hue_spread([colour_a, colour_b])
            if gap is not None and gap > MAX_WITHIN_BAND_HUE_SPREAD:
                worst = gap if worst is None else max(worst, gap)
    return worst


def _saturated(colour: str) -> bool:
    _, _, s = colorsys.rgb_to_hls(*(c / 255 for c in _rgb(colour)))
    return s >= MIN_MEANINGFUL_SATURATION


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _hue_spread(colours: list[str]) -> float | None:
    """The widest gap between the hues that carry enough saturation to have one."""
    hues = []
    for colour in colours:
        h, _, s = colorsys.rgb_to_hls(*(c / 255 for c in _rgb(colour)))
        if s >= MIN_MEANINGFUL_SATURATION:
            hues.append(h * 360.0)
    if len(hues) < 2:
        return None
    widest = 0.0
    for i, a in enumerate(hues):
        for b in hues[i + 1:]:
            gap = abs(a - b) % 360.0
            widest = max(widest, min(gap, 360.0 - gap))
    return widest


# ===== clipping =======================================================================
# `generate_ramp` walks lightness outward from a base and clamps at 0 and 1, so a base
# already near either end spends its outermost steps on the same colour. Nine steps in,
# eight distinct colours out, and until these two functions existed the result said
# nothing about it.
#
# A collapsed end step costs more than one colour. `specular_highlight` exists to put a
# glint above the lit side, so it needs the ramp's top step to be brighter than what
# `shade_region_by_light` spread across that side; given a ramp whose top two entries are
# both white it refuses, correctly, with a message about the shading pass. The cause is two
# calls earlier, in one that reported success.


def clipped_ends(colours: list[str]) -> tuple[int, int]:
    """How many steps collapsed onto the first colour, and onto the last.

    Counts the *extra* entries equal to each end, so `(0, 0)` means neither end collapsed.
    Duplicates can also appear in the middle, from two neighbouring steps rounding to the
    same hex, and those show up as a shortfall in `distinct` with `(0, 0)` here.
    """
    if len(colours) < 2:
        return 0, 0
    at_dark = 0
    while at_dark + 1 < len(colours) and colours[at_dark + 1] == colours[0]:
        at_dark += 1
    at_light = 0
    while at_light + 1 < len(colours) and colours[-at_light - 2] == colours[-1]:
        at_light += 1
    return at_dark, at_light


def nearest_unclipped(rebuild, steps: int, requested: float,
                      *, low: float = 0.02, high: float = 1.0,
                      grid: float = 0.01) -> float | None:
    """The `light_range` closest to `requested` that returns `steps` distinct colours.

    Scanned rather than searched, because distinctness is **not monotonic** in
    `light_range` and a bisection would be wrong in both directions: too wide clamps the
    ends onto each other, and too narrow rounds neighbouring steps onto the same hex. So
    the answer can lie either side of what was asked for, and the nearest one is the useful
    one to name.

    `rebuild` takes a `light_range` and returns the colours for it. Returns None when
    nothing on the grid works, which is what asking for more steps than the base can
    express looks like.
    """
    ticks = round((high - low) / grid) + 1
    workable = [
        value for value in (round(low + i * grid, 2) for i in range(ticks))
        if len(set(rebuild(value))) == steps
    ]
    if not workable:
        return None
    # Ties broken toward the narrower range, which is the safer direction: it clamps less.
    return min(workable, key=lambda value: (abs(value - requested), value))


def clip_warning(colours: list[str], steps: int, suggestion: float | None) -> str:
    """One sentence a caller can act on, for a ramp that came back short."""
    distinct = len(set(colours))
    at_dark, at_light = clipped_ends(colours)
    if at_light:
        where = f"the top {at_light + 1} entries are all {colours[-1]}"
    elif at_dark:
        where = f"the bottom {at_dark + 1} entries are all {colours[0]}"
    else:
        where = ("neighbouring steps round to the same colour, so the range is too "
                 "narrow for this many steps")
    fix = (f"light_range={suggestion} is the nearest value that returns {steps} distinct "
           "colours." if suggestion is not None else
           f"No light_range returns {steps} distinct colours from this base, so ask for "
           "fewer steps.")
    # Only said when the *top* collapsed, because that is the end the sentence is about. A
    # ramp that lost steps to black, or to rounding in the middle, has a different problem
    # and does not need to be told about speculars.
    cost = (" A collapsed top step costs more than one colour: specular_highlight needs "
            "the ramp's top step to be brighter than the lit side, and refuses a ramp "
            "whose lit side is already there." if at_light else "")
    return f"{steps} steps were asked for and {distinct} are distinct: {where}. {fix}{cost}"
