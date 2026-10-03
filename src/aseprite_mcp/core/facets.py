"""Shading a form made of flat planes, which is what carved and built things are.

`shade_region_by_light` infers a surface normal from how far a pixel sits from the
silhouette's edge. That is right for a sphere, a ball of flesh or a cushion, and it is
wrong for everything hard: a crate, a helm, a sword, a slab of cut stone. Those are flat
planes meeting at hard edges, and a distance field cannot know where an edge is, so it
rounds the form over. Every hard-surface subject in this project's own gallery came out
inflated for that reason, and a four-agent review called the result "grey plastic" and "a
balloon" without either reviewer knowing the cause.

A plane's tone does not depend on where its pixels are. It depends on which way the plane
faces, and every pixel on it takes the same value. That single flat value is what reads as
carved, and it is also why this module is small: the hard part is not the arithmetic, it is
having somewhere to say which way each pixel's plane faces. The character grid that
`draw_pixel_map` introduced is that place. A map whose legend names colours draws a
picture; a map whose legend names *directions* describes a solid, and the tone comes out of
the light.

So this module turns facet directions into ramp steps, and nothing else. It is pure: no
Aseprite, no MCP, no Lua, no knowledge of what a colour is.

The lighting model is deliberately the one pixel artists use rather than the one a renderer
uses:

* a key light, from `light_angle`, which does most of the describing;
* a fill, from roughly opposite and lower, standing in for light bouncing off the ground;
* an ambient floor, so a plane facing away is dark rather than black.

The fill is not a nicety. Without it every plane facing away from the key clamps to the
same ambient value, and the shadow side of a form comes out as one flat region: measured on
seven planes with no fill, "right", "bottom-right" and "bottom" all landed on the same ramp
step, which is exactly the defect found on the helm in this project's item sheet, where one
colour covered 202 pixels of a shaded surface with no second value anywhere in it. At 0.35
those three planes separate into three steps. Past about 0.6 the bounce lifts the shadow
side into the lit side's values and the form flattens again from the other direction.
"""
from __future__ import annotations

import math

from . import lighting
from .errors import ValidationFailed

# How much an angled plane also faces the viewer. Fixed rather than exposed as an argument:
# across the whole plausible range it does not change a single step on a ramp of eight (the
# same seven planes came out identically at 0.45 and at 0.8), so a knob for it would be a
# control that does nothing, which is worse than no control. A caller who needs a plane
# tilted differently says so per facet, in the legend, where it does change the normal.
FACET_TILT = 0.45
# A plane facing away from every light still catches the sky. Zero here would put the
# darkest facet on the ramp's bottom entry, which is the keyline colour, and the form would
# dissolve into its own outline.
AMBIENT = 0.16
FILL_STRENGTH = 0.35
# The fill is lower than the key because it stands for a bounce off the ground.
FILL_Z = 0.25
# Below three steps there is no form to describe: a lit value and a shadow value is a
# silhouette with a highlight.
MIN_RAMP = 3

FRONT = "front"


def normal(spec, *, symbol: str = "?") -> tuple[float, float, float]:
    """The unit normal a legend entry describes.

    Accepts the angle alone, in the same convention every light in this project uses (0
    faces right, 90 faces up, 135 faces up and to the left); the word "front" for a plane
    square to the viewer; or `[angle, z]` to say how much a plane faces the viewer as well,
    which is how a chamfer or a shallow bevel is expressed.
    """
    if isinstance(spec, str):
        if spec.strip().lower() != FRONT:
            raise ValidationFailed(
                f"legend[{symbol!r}] is {spec!r}. A facet is an angle in degrees (0 faces "
                f'right, 90 up, 135 up and to the left), the word "{FRONT}" for a plane '
                "square to the viewer, or [angle, z] to tilt one toward the viewer."
            )
        return (0.0, 0.0, 1.0)
    if isinstance(spec, (list, tuple)):
        if len(spec) != 2:
            raise ValidationFailed(
                f"legend[{symbol!r}] has {len(spec)} values; a facet given as a list is "
                "[angle, z]."
            )
        angle, tilt = spec
    elif isinstance(spec, bool) or not isinstance(spec, (int, float)):
        raise ValidationFailed(
            f"legend[{symbol!r}] is {spec!r}, which is not a facet direction. Give an "
            f'angle in degrees, "{FRONT}", or [angle, z].'
        )
    else:
        angle, tilt = spec, FACET_TILT
    try:
        angle, tilt = float(angle), float(tilt)
    except (TypeError, ValueError):
        raise ValidationFailed(
            f"legend[{symbol!r}] is {spec!r}; both parts of a facet have to be numbers."
        ) from None
    if not math.isfinite(angle) or not math.isfinite(tilt):
        raise ValidationFailed(f"legend[{symbol!r}] is {spec!r}; it has to be finite.")
    radians = math.radians(angle)
    vector = (math.cos(radians), -math.sin(radians), tilt)
    length = math.sqrt(sum(c * c for c in vector))
    if length < 1e-9:
        raise ValidationFailed(
            f"legend[{symbol!r}] is {spec!r}, which has no direction at all."
        )
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def step_for(
    face: tuple[float, float, float],
    *,
    steps: int,
    light_angle: float = 135.0,
    light_z: float = 0.5,
    fill_strength: float = FILL_STRENGTH,
    ambient: float = AMBIENT,
) -> int:
    """Which ramp step a plane facing this way takes, 0 being the darkest entry."""
    key = lighting.light_vector(light_angle, light_z)
    fill = lighting.light_vector(light_angle + 180.0, FILL_Z)
    lit = max(0.0, lighting.dot(face, key))
    bounced = max(0.0, lighting.dot(face, fill))
    shade = min(1.0, lit + fill_strength * bounced)
    value = ambient + (1.0 - ambient) * shade
    return max(0, min(steps - 1, round(value * (steps - 1))))


def plan(
    legend: dict,
    *,
    steps: int,
    light_angle: float = 135.0,
    light_z: float = 0.5,
    fill_strength: float = FILL_STRENGTH,
    ambient: float = AMBIENT,
) -> dict[str, int]:
    """The ramp step each legend symbol resolves to, as {symbol: step}.

    Refuses a plan whose facets all land on one step. That happens when the ramp is too
    short to separate them, or when the light points straight at the viewer so every plane
    is lit equally, and the result would be a flat fill produced by a tool whose whole
    purpose is that it is not one. A shading pass that shades nothing is the kind of silent
    success this project treats as worse than an error.
    """
    if steps < MIN_RAMP:
        raise ValidationFailed(
            f"a facet pass needs at least {MIN_RAMP} ramp entries to describe a form; got "
            f"{steps}. Two is a silhouette and a highlight."
        )
    if not isinstance(legend, dict) or not legend:
        raise ValidationFailed(
            "legend must be a non-empty mapping of one-character symbols to facet "
            "directions."
        )
    if not 0.0 <= fill_strength <= 1.0:
        raise ValidationFailed(
            f"fill_strength is {fill_strength}; it is a share of the key light, from 0 to "
            "1. Past about 0.6 the bounce lifts the shadow side into the lit side's values "
            "and the form flattens from the other direction."
        )
    if not 0.0 <= ambient < 1.0:
        raise ValidationFailed(f"ambient is {ambient}; it is a floor from 0 to 1.")

    resolved: dict[str, int] = {}
    for symbol, spec in legend.items():
        if not isinstance(symbol, str) or len(symbol) != 1:
            raise ValidationFailed(
                f"legend key {symbol!r} is not a single character. A map is read one "
                "character per pixel, so every key has to be exactly one."
            )
        resolved[symbol] = step_for(
            normal(spec, symbol=symbol), steps=steps, light_angle=light_angle,
            light_z=light_z, fill_strength=fill_strength, ambient=ambient,
        )
    if len(set(resolved.values())) == 1 and len(resolved) > 1:
        landed = next(iter(set(resolved.values())))
        raise ValidationFailed(
            f"all {len(resolved)} facets resolved to ramp step {landed}, so this pass "
            "would paint one flat colour. Either the ramp is too short to separate the "
            "directions given, or the light is square to every one of them: a light_angle "
            "pointing where the planes already face cannot describe them."
        )
    return resolved
