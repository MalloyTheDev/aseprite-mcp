"""Light directions, specular geometry, cast-shadow projection and glow ring arithmetic.

The shading tools have carried their lighting maths inside their Lua bodies, which was
fine while there was one light and one term. Three things here are decisions rather than
pixel pushing, and a decision belongs where it can be tested without an editor:

  * **where a specular sits.** Not on the normal facing the light, which is where the
    diffuse peak is, but on the normal facing halfway between the light and the viewer.
    That half-vector is the whole reason a specular reads as a wet or polished surface
    rather than as a brighter patch of the same matte form.
  * **where a cast shadow falls.** A direction and a length, from a light angle and a
    light height. This is the part that is easy to get subtly wrong (shadow on the wrong
    side, or a length that moves the wrong way with the light) and impossible to notice
    in a preview, so it is written once here and asserted at four angles.
  * **which ramp step each glow ring takes.** A glow on a palette is a sequence of ramp
    indices arranged by distance, and that sequence is a list of integers worth checking
    against rather than a curve worth eyeballing.

Screen space throughout: x grows right, y grows **down**, z points at the viewer. An
upward light is therefore negative in y, which is the one sign error that makes every
sprite look lit from below.
"""

from __future__ import annotations

import math

Vector = tuple[float, float, float]

# How flat a ground shadow reads, as the ratio of its depth up the screen to its width
# across it. A ground plane seen from a typical pixel-art three-quarter view foreshortens
# to roughly a third; it is fixed rather than exposed because the alternative is a camera
# pitch argument on a tool whose other arguments are all about the light, and because the
# light's height already controls the one thing a caller actually wants to vary, which is
# how far the shadow reaches.
GROUND_FLATTEN = 0.35

# The viewer, for a sprite: straight out of the screen. Named because it appears in the
# half-vector and reads as a magic triple otherwise.
VIEW: Vector = (0.0, 0.0, 1.0)


def _round_half_up(value: float) -> int:
    """Round with .5 going away from zero, matching `math.floor(v + 0.5)` in Lua.

    Python's built-in `round` is banker's rounding, so `round(20.5)` is 20 while the Lua
    transcription of the same formula gives 21. The cast-shadow geometry is computed here
    for testing and again in Lua for drawing, and a half-pixel disagreement between the
    two would show up as a test that passes on most sprites and fails on the ones whose
    width happens to be even.
    """
    return math.floor(value + 0.5)


def _normalise(v: Vector) -> Vector:
    length = math.sqrt(sum(c * c for c in v))
    if length < 1e-12:
        # Only reachable from a caller-supplied zero vector. Returning the view direction
        # rather than raising keeps the lighting terms finite: a degenerate light lights
        # the form flatly from the front, which is visibly wrong and therefore debuggable,
        # where a NaN propagates into every pixel and shows up as nothing at all.
        return VIEW
    return (v[0] / length, v[1] / length, v[2] / length)


def light_vector(angle_deg: float, z: float) -> Vector:
    """The direction light arrives from, as a unit vector in screen space.

    `angle_deg` is measured the way the shading tools state it: 0 is from the right, 90
    from above, 135 from the upper left. `z` is how much of the light comes from the
    viewer's side, which flattens the terminator as it rises.
    """
    rad = math.radians(angle_deg)
    return _normalise((math.cos(rad), -math.sin(rad), float(z)))


def half_vector(light: Vector) -> Vector:
    """The direction a specular reflects from, halfway between the light and the viewer.

    This is the Blinn half-vector. A surface whose normal points along it sends the light
    straight at the viewer, so this is where the highlight actually appears, and it sits
    between the light direction and the front of the form rather than on the light
    direction itself. That offset toward the viewer is what separates a specular from the
    diffuse peak, and it is why a specular on a sphere lit from the upper left sits
    *inside* the lit side rather than on its outer shoulder.
    """
    return _normalise(tuple(a + b for a, b in zip(light, VIEW, strict=True)))


def specular_direction(angle_deg: float, z: float) -> Vector:
    """The half-vector for a light stated as the shading tools state it."""
    return half_vector(light_vector(angle_deg, z))


def dot(a: Vector, b: Vector) -> float:
    return sum(p * q for p, q in zip(a, b, strict=True))


# --------------------------------------------------------------- cast shadow geometry

# A shadow longer than this many times the subject's own height is already off any
# plausible canvas, and the number exists to stop a very low light turning into an
# ellipse with a radius of millions. cot(1 degree) is about 57, so this is a light about
# a degree above the horizon: lower than any pixel-art sun and well past the point where
# the shadow has left the frame.
_MAX_COT = 60.0


def shadow_projection(light_angle: float, light_height: float) -> dict:
    """How far a shadow reaches per unit of subject height, and which way.

    `light_height` is the light's elevation as a fraction: 1.0 is straight overhead and
    casts nothing sideways, small values are a low sun and cast a long shadow. It maps
    linearly onto an elevation angle and the reach is that angle's cotangent, which is
    the actual trigonometry of a shadow on a flat floor rather than an invented curve.

    `dir_x` is the sign and amount the shadow slides along x: away from the light, so a
    light from the upper left (135) pushes the shadow to the right. A light directly
    above or directly below contributes nothing sideways, which is correct for overhead
    and the only sane answer for a light below a floor.
    """
    elevation = math.radians(90.0 * light_height)
    # tan is safe here: callers are validated to light_height > 0, so the elevation never
    # reaches 0 and the cotangent stays finite. Guarded anyway, because a silent infinity
    # becomes an ellipse the size of the heat death of the universe.
    tangent = math.tan(elevation)
    cot = 0.0 if tangent <= 0 else min(1.0 / tangent, _MAX_COT)
    return {"dir_x": -math.cos(math.radians(light_angle)), "cot_elev": cot}


def shadow_ellipse(
    bbox: tuple[int, int, int, int],
    light_angle: float,
    light_height: float,
    ground_y: int,
) -> tuple[int, int, int, int]:
    """Where a subject's ground shadow sits, as `(cx, cy, rx, ry)`.

    `bbox` is the subject's own drawn box as `(x0, y0, x1, y1)`, inclusive. `ground_y` is
    the row the shadow lies on, normally the subject's contact row.

    The shadow is an ellipse rather than a projected silhouette, which is both what pixel
    artists draw and what survives the projection honestly: a silhouette projected onto a
    floor by a point light needs a light *position*, and inventing one from an angle would
    be a guess dressed up as geometry. An ellipse needs only the direction and the
    height, which is exactly what the caller gave.

    The width grows as the light drops, because that is the shadow lengthening; the depth
    does not, because that is the floor's foreshortening and has nothing to do with the
    light. So `light_height` moves the length and only the length.

    `cast_shadow` transcribes these four lines into Lua, because only the editor knows the
    subject's drawn box. An integration test asserts the two agree on a real sprite, which
    is the only thing that keeps a formula living in two places honest.
    """
    x0, y0, x1, y1 = bbox
    width = x1 - x0 + 1
    height = y1 - y0 + 1
    projection = shadow_projection(light_angle, light_height)
    reach = height * projection["cot_elev"]

    centre_x = (x0 + x1) / 2.0 + projection["dir_x"] * reach / 2.0
    rx = width / 2.0 + reach / 2.0
    ry = (width / 2.0) * GROUND_FLATTEN
    # At least 1 on each axis: a sub-pixel ellipse rounds to nothing, and a tool that
    # reports success having drawn nothing is the failure mode this codebase keeps
    # finding. A 1x1 shadow is visible and honest.
    return (
        _round_half_up(centre_x),
        int(ground_y),
        max(1, _round_half_up(rx)),
        max(1, _round_half_up(ry)),
    )


def filled_ellipse_points(rx: int, ry: int) -> int:
    """An upper bound on the points a filled-ellipse rasterisation emits.

    `ellipse_offsets(rx, ry, filled)` in the Lua prelude emits one entry per pixel of the
    ellipse's **area**, not of its perimeter, and it builds the whole list before
    returning it. So this count is an allocation, it is quadratic in the radii, and it has
    to be checked *before* the call rather than discovered during it.

    The area of an ellipse is `pi * rx * ry`. Each radius is taken one larger, which keeps
    this an over-estimate: a guard that under-counts is not a guard. `cast_shadow`
    transcribes this one line into Lua, because only the editor knows the radii, and it
    reports the count back so a test can assert the two agree.
    """
    return math.ceil(math.pi * (rx + 1) * (ry + 1))


# ------------------------------------------------------------------- glow ring arithmetic

FALLOFFS = ("linear", "quadratic")


def glow_rings(radius: int, ramp_length: int, falloff: str = "linear") -> list[int]:
    """The ramp step each ring of a glow takes, innermost first, as 1-based indices.

    A glow on a fixed palette is not a blur: it is a handful of rings, each one step
    further down the ramp, which is the only way to fade without inventing colours. This
    returns that sequence, so the Lua that paints it does a table lookup rather than
    arithmetic and the curve can be checked against a list of integers.

    Ring 1 touches the artwork and takes the ramp's top step. The outermost ring takes
    `ramp[0]`, the bottom. `quadratic` falls away faster than `linear`, so the glow keeps
    a hotter core and a dimmer skirt; it is the one that reads as a light source rather
    than as a coloured outline.
    """
    if radius < 1:
        raise ValueError("a glow needs a radius of at least 1 ring")
    if ramp_length < 2:
        raise ValueError("a glow needs at least 2 ramp steps to fade through")
    if falloff not in FALLOFFS:
        raise ValueError(f"unknown falloff {falloff!r}; expected one of {FALLOFFS}")

    rings = []
    for ring in range(1, radius + 1):
        # 0 at the ring touching the art, 1 at the outermost. A single-ring glow sits at
        # t = 0 and takes the top step, which is the right answer for "one bright ring"
        # rather than a division by zero.
        t = 0.0 if radius == 1 else (ring - 1) / (radius - 1)
        brightness = (1.0 - t) ** 2 if falloff == "quadratic" else (1.0 - t)
        rings.append(1 + round(brightness * (ramp_length - 1)))
    return rings
