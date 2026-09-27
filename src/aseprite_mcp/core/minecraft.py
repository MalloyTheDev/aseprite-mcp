"""Minecraft resource-pack domain - pure logic for the ``minecraft`` asset-spec kind.

Minecraft is not just "a PNG in a folder". A texture only works if several things line up
at once, and each has its own silent failure mode:

  * **Location.** ``assets/<namespace>/textures/<category>/<name>.png``. A wrong namespace
    or category produces a missing-texture checkerboard, not an error.
  * **Dimensions.** Block/item textures are stitched into an atlas and mipmapped, so a
    non-power-of-two size degrades or breaks mipmapping rather than failing loudly.
  * **Animation.** An animated texture is a *vertical strip* of square frames plus a
    ``<name>.png.mcmeta`` sidecar. Without the sidecar the game treats the strip as one
    very tall texture and squashes it onto the block face - which reads as an art bug,
    not a metadata bug.
  * **Tiling.** A block texture repeats across a wall, so its right edge abuts its own
    left edge. A seam there is invisible in the editor and obvious in the world.

This module is pure Python (no Aseprite, no MCP) so all of that is unit-testable.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Pack formats                                                                #
# --------------------------------------------------------------------------- #
# Resource-pack format numbers for the versions this project targets. Deliberately
# short: a wrong pack_format makes the game reject the pack as incompatible, so
# guessing an unverified version is worse than refusing to. Anything not listed must
# pass `pack_format` explicitly.
PACK_FORMATS: dict[str, int] = {
    "1.20.5": 32,
    "1.20.6": 32,
    "1.21": 34,
    "1.21.1": 34,
    "1.21.2": 42,
    "1.21.3": 42,
    "1.21.4": 46,
    "1.21.5": 55,
}

DEFAULT_MC_VERSION = "1.21.1"

# Texture subdirectories under assets/<ns>/textures/. Anything outside this set is
# either not a texture root or so rare that a typo is the likelier explanation.
TEXTURE_CATEGORIES = (
    "block", "item", "entity", "gui", "particle", "painting",
    "environment", "font", "map", "mob_effect", "models", "misc", "colormap",
)

# Categories whose textures repeat against themselves in world space, so a wrap-around
# seam is a real defect rather than a stylistic choice.
TILING_CATEGORIES = ("block",)

# Resource locations are lowercase-only (enforced by the game since 1.11); the path
# component additionally allows '/'. Uppercase is the classic Windows-authored-pack bug:
# it loads fine from a local folder and 404s from a zip on a case-sensitive server.
NAMESPACE_RE = re.compile(r"^[a-z0-9_.-]+$")
TEXTURE_NAME_RE = re.compile(r"^[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*$")

# One Minecraft tick is 50 ms. `frametime` is in ticks, Aseprite durations are in ms;
# converting keeps the Aseprite timeline previewing at the speed the game will play.
MS_PER_TICK = 50

_MAX_TEXTURE_SIZE = 1024


def is_power_of_two(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and n >= 1 and (n & (n - 1)) == 0


# --------------------------------------------------------------------------- #
# Spec validation (called from asset_spec._check_kind_fields)                 #
# --------------------------------------------------------------------------- #
def validate_fields(spec: dict, check) -> None:
    """Validate the ``minecraft``-kind fields of an asset spec.

    ``check(name, ok, level, detail)`` is the collector supplied by ``validate_spec``.
    """
    ns = spec.get("namespace", "minecraft")
    if check("minecraft.namespace", isinstance(ns, str) and bool(NAMESPACE_RE.match(ns)),
             "error",
             f"namespace {ns!r} must match [a-z0-9_.-]+ (resource locations are lowercase)."):
        check("minecraft.namespace.vanilla", ns != "minecraft", "warning",
              "namespace 'minecraft' overrides vanilla textures; use your own mod id "
              "unless you mean to retexture the base game.")

    category = spec.get("category")
    check("minecraft.category", category in TEXTURE_CATEGORIES, "error",
          f"'category' must be one of {list(TEXTURE_CATEGORIES)} (got {category!r}).")

    name = spec.get("name")
    if isinstance(name, str) and name:
        check("minecraft.name", bool(TEXTURE_NAME_RE.match(name)), "error",
              f"texture name {name!r} is not a valid resource path - lowercase "
              "[a-z0-9_.-] with '/' as the only separator.")

    size = spec.get("texture_size", 16)
    if check("minecraft.texture_size", is_power_of_two(size) and size <= _MAX_TEXTURE_SIZE,
             "error",
             f"'texture_size' must be a power of two in 1..{_MAX_TEXTURE_SIZE} (got {size!r}); "
             "non-power-of-two textures break atlas mipmapping."):
        check("minecraft.texture_size.large", size <= 128, "warning",
              f"texture_size {size} is {size // 16}x vanilla resolution - atlas memory grows "
              "with the square of this.")

    tiling = spec.get("tiling")
    if tiling is not None and check("minecraft.tiling", isinstance(tiling, bool), "error",
                                    "'tiling' must be a boolean."):
        check("minecraft.tiling.category", not (tiling and category not in TILING_CATEGORIES),
              "warning",
              f"'tiling' is set but category {category!r} does not repeat in world space; "
              "the seam check would not mean anything.")

    _validate_animation(spec, check)


def _validate_animation(spec: dict, check) -> None:
    anim = spec.get("animation")
    if anim is None:
        return
    if not check("minecraft.animation", isinstance(anim, dict), "error",
                 "'animation' must be an object {frames, frametime, interpolate}."):
        return

    frames = anim.get("frames")
    check("minecraft.animation.frames",
          isinstance(frames, int) and not isinstance(frames, bool) and frames >= 2, "error",
          f"animation 'frames' must be an integer >= 2 (got {frames!r}); a one-frame "
          "animation is just a static texture.")

    frametime = anim.get("frametime", 1)
    check("minecraft.animation.frametime",
          isinstance(frametime, int) and not isinstance(frametime, bool) and frametime >= 1,
          "error", f"animation 'frametime' must be an integer >= 1 tick (got {frametime!r}).")

    interpolate = anim.get("interpolate", False)
    check("minecraft.animation.interpolate", isinstance(interpolate, bool), "error",
          "animation 'interpolate' must be a boolean.")

    order = anim.get("frame_order")
    if order is not None and check("minecraft.animation.frame_order",
                                   isinstance(order, list) and bool(order), "error",
                                   "'frame_order' must be a non-empty list of frame indices "
                                   "or {index, time} objects."):
        _validate_frame_order(order, frames, check)


def _validate_frame_order(order: list, frames, check) -> None:
    limit = frames if isinstance(frames, int) and not isinstance(frames, bool) else None
    bad: list = []
    for entry in order:
        index = entry.get("index") if isinstance(entry, dict) else entry
        # Ordering matters: the range comparison is only reachable once `index` is known
        # to be an int, or a string frame index would raise instead of being reported.
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            bad.append(entry)
            continue
        if limit is not None and index >= limit:
            bad.append(entry)
            continue
        if isinstance(entry, dict):
            time = entry.get("time", 1)
            if not isinstance(time, int) or isinstance(time, bool) or time < 1:
                bad.append(entry)
    check("minecraft.animation.frame_order.entries", not bad, "error",
          f"invalid frame_order entries {bad}: indices are 0-based and must be < frames "
          f"({limit}); any 'time' must be an integer >= 1.")


# --------------------------------------------------------------------------- #
# Paths and metadata documents                                                #
# --------------------------------------------------------------------------- #
def texture_rel_path(namespace: str, category: str, name: str) -> str:
    """The texture's path inside a resource pack, relative to the pack root."""
    return f"assets/{namespace}/textures/{category}/{name}.png"


def resolve_pack_format(mc_version: str | None = None, pack_format: int | None = None) -> int:
    """Resolve a pack_format from an explicit number or a known Minecraft version."""
    if pack_format is not None:
        if not isinstance(pack_format, int) or isinstance(pack_format, bool) or pack_format < 1:
            raise ValueError(f"pack_format must be a positive integer (got {pack_format!r}).")
        return pack_format
    version = mc_version or DEFAULT_MC_VERSION
    if version not in PACK_FORMATS:
        raise ValueError(
            f"Unknown Minecraft version {version!r}. Known: {sorted(PACK_FORMATS)}. "
            "Pass pack_format explicitly for other versions - guessing it would produce "
            "a pack the game silently refuses to load."
        )
    return PACK_FORMATS[version]


def pack_mcmeta(
    pack_format: int,
    description: str = "Generated by aseprite-mcp",
    supported_formats: dict | None = None,
) -> dict:
    """The ``pack.mcmeta`` document that makes a directory a resource pack."""
    pack: dict = {"pack_format": int(pack_format), "description": description}
    if supported_formats:
        pack["supported_formats"] = {
            "min_inclusive": int(supported_formats["min_inclusive"]),
            "max_inclusive": int(supported_formats["max_inclusive"]),
        }
    return {"pack": pack}


def animation_mcmeta(
    frametime: int = 1,
    interpolate: bool = False,
    frame_order: list | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """The ``<texture>.png.mcmeta`` sidecar that tells the game a PNG is a frame strip.

    Only non-default keys are emitted, so a plain 1-tick animation produces the minimal
    ``{"animation": {}}`` the game expects rather than a document restating defaults.
    """
    animation: dict = {}
    if frametime != 1:
        animation["frametime"] = int(frametime)
    if interpolate:
        animation["interpolate"] = True
    if frame_order:
        animation["frames"] = [
            {"index": int(e["index"]), "time": int(e.get("time", frametime))}
            if isinstance(e, dict) else int(e)
            for e in frame_order
        ]
    if width is not None:
        animation["width"] = int(width)
    if height is not None:
        animation["height"] = int(height)
    return {"animation": animation}


# --------------------------------------------------------------------------- #
# Tiling-seam analysis                                                        #
# --------------------------------------------------------------------------- #
def _parse_hex(value: str) -> tuple[int, int, int, int]:
    s = value.lstrip("#")
    if len(s) == 6:
        s += "ff"
    if len(s) != 8:
        raise ValueError(f"expected #RRGGBB or #RRGGBBAA, got {value!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))


def _pixel_distance(a: str, b: str) -> float:
    """Distance between two pixels, 0..255.

    RGB is premultiplied by alpha before comparing, so two fully transparent pixels are
    equal whatever colour data they carry - Aseprite keeps RGB under erased pixels, and
    comparing it raw reports seams between two invisible edges.
    """
    ar, ag, ab, aa = _parse_hex(a)
    br, bg, bb, ba = _parse_hex(b)
    fa, fb = aa / 255.0, ba / 255.0
    return (
        abs(ar * fa - br * fb) + abs(ag * fa - bg * fb) + abs(ab * fa - bb * fb) + abs(aa - ba)
    ) / 4.0


def _mean_distance(line_a: list[str], line_b: list[str]) -> float:
    # strict=True: every caller passes two lines of one rectangular image, so unequal
    # lengths are a bug, and silently truncating would skew the mean it divides by.
    return sum(_pixel_distance(p, q) for p, q in zip(line_a, line_b, strict=True)) / len(line_a)


def _axis_report(wrap: float, interior: list[float], warn_ratio: float,
                 error_ratio: float) -> dict:
    mean_interior = sum(interior) / len(interior) if interior else 0.0
    peak_interior = max(interior) if interior else 0.0
    if mean_interior < 1e-9:  # noqa: SIM108 - the branch comment below is the point
        # Every interior transition is identical, so all lines are identical and the wrap
        # transition must be too; a non-zero wrap here would be arithmetically impossible.
        ratio = 0.0 if wrap < 1e-9 else float("inf")
    else:
        ratio = wrap / mean_interior

    # A seam is a transition at the wrap that occurs *nowhere inside* the texture. Being
    # an outlier against the mean is not enough on its own: a smooth tile that wraps
    # perfectly (a full sine period) still has its steepest transition at the wrap, and a
    # texture whose last column already differs from its neighbours has a high ratio while
    # tiling to an evenly spaced stripe - both are correct art the mean alone rejects.
    # Requiring the wrap to also exceed every interior transition removes those without
    # weakening the real cases, where the wrap dwarfs the peak many times over.
    exceeds_peak = wrap > peak_interior + 1e-9
    verdict = "seamless"
    if exceeds_peak:
        if ratio >= error_ratio:
            verdict = "seam"
        elif ratio >= warn_ratio:
            verdict = "suspect"
    return {
        "wrap_distance": round(wrap, 3),
        "mean_interior_distance": round(mean_interior, 3),
        "peak_interior_distance": round(peak_interior, 3),
        "ratio": None if ratio == float("inf") else round(ratio, 3),
        "exceeds_peak_interior": exceeds_peak,
        "verdict": verdict,
    }


def evaluate_tiling(rows: list[list[str]], *, warn_ratio: float = 2.0,
                    error_ratio: float = 4.0) -> dict:
    """Measure how visible the wrap-around seams of a tiling texture are.

    ``rows`` is the pixel grid as ``#RRGGBBAA`` strings, row-major from the top-left.

    A tiling texture's last column sits against its own first column when it repeats, so
    the question is not "are those two columns identical" - that is only true of a texture
    with no horizontal variation at all, and would reject most real block art. It is
    whether the wrap transition is an *outlier* among the texture's own column-to-column
    transitions. A texture whose interior changes by 8 units per column and whose wrap
    changes by 90 has a seam; one that changes by 40 throughout and wraps at 45 does not.

    Returns ``{horizontal, vertical}`` reports, each carrying the measured distances and
    the ratio behind the verdict, so a borderline call can be judged rather than trusted.
    """
    if not rows or not rows[0]:
        raise ValueError("no pixel data")
    height, width = len(rows), len(rows[0])
    if any(len(r) != width for r in rows):
        raise ValueError("pixel rows are ragged")
    if width < 3 or height < 3:
        raise ValueError(f"texture is {width}x{height}; need at least 3x3 to have interior "
                         "transitions to compare the wrap against")

    columns = [[rows[y][x] for y in range(height)] for x in range(width)]
    h_interior = [_mean_distance(columns[x], columns[x + 1]) for x in range(width - 1)]
    h_wrap = _mean_distance(columns[width - 1], columns[0])

    v_interior = [_mean_distance(rows[y], rows[y + 1]) for y in range(height - 1)]
    v_wrap = _mean_distance(rows[height - 1], rows[0])

    return {
        "horizontal": _axis_report(h_wrap, h_interior, warn_ratio, error_ratio),
        "vertical": _axis_report(v_wrap, v_interior, warn_ratio, error_ratio),
    }


# --------------------------------------------------------------------------- #
# Texture validation                                                          #
# --------------------------------------------------------------------------- #
def evaluate_texture(
    info: dict,
    *,
    category: str | None = None,
    texture_size: int | None = None,
    tiling: bool = False,
    frame_tilings: list[dict] | None = None,
    max_palette_size: int | None = None,
    expected_frames: int | None = None,
    has_mcmeta: bool | None = None,
) -> dict:
    """Check a sprite against Minecraft's texture rules.

    Returns ``{passed, checks, errors, warnings}``. Aseprite-backed facts (sprite info,
    per-frame pixel grids, sidecar existence) are gathered by the tool wrapper and passed
    in, keeping the decision logic testable without launching Aseprite - the same split
    ``core/validation.py`` uses.
    """
    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, level: str, detail: str = "") -> None:
        # `detail` describes the FAILURE, so carrying it on a passing check makes a clean
        # report read like a list of problems ("ok": true beside "is not a valid resource
        # path"). Emit it only when it is true.
        checks.append({"name": name, "ok": ok, "level": level,
                       "detail": "" if ok else detail})
        if not ok:
            (errors if level == "error" else warnings).append(detail or name)

    width, height = info["width"], info["height"]
    frames = info["frameCount"]

    check("square", width == height, "error",
          f"frame is {width}x{height}; Minecraft texture frames must be square.")
    check("power_of_two", is_power_of_two(width), "error",
          f"width {width} is not a power of two - the block/item atlas mipmaps it, and "
          "non-power-of-two sizes degrade or fail there.")
    if texture_size is not None:
        check("texture_size", width == texture_size, "error",
              f"frame width {width} != declared texture_size {texture_size}.")
    if category is not None:
        check("category", category in TEXTURE_CATEGORIES, "error",
              f"unknown texture category {category!r}.")
    if expected_frames is not None:
        check("frames", frames == expected_frames, "error",
              f"sprite has {frames} frame(s); the spec declares {expected_frames}.")
    if has_mcmeta is not None and frames > 1:
        check("mcmeta", has_mcmeta, "error",
              f"{frames} frames export as a vertical strip, but no .png.mcmeta sidecar was "
              "found - the game would squash the whole strip onto one face.")

    palette_size = info.get("paletteSize")
    if max_palette_size is not None and palette_size is not None:
        check("palette_size", palette_size <= max_palette_size, "warning",
              f"palette has {palette_size} colours; the target style allows {max_palette_size}.")

    if tiling and frame_tilings:
        for i, report in enumerate(frame_tilings, start=1):
            for axis in ("horizontal", "vertical"):
                axis_report = report[axis]
                verdict = axis_report["verdict"]
                label = f"tiling.frame{i}.{axis}"
                detail = (
                    f"frame {i} {axis} wrap differs by {axis_report['wrap_distance']} against a "
                    f"mean interior transition of {axis_report['mean_interior_distance']} "
                    f"(ratio {axis_report['ratio']}) - the edge will show as a seam where the "
                    "block repeats."
                )
                if verdict == "seam":
                    check(label, False, "error", detail)
                elif verdict == "suspect":
                    check(label, False, "warning", detail.replace("will show", "may show"))
                else:
                    check(label, True, "error")

    return {"passed": not errors, "checks": checks, "errors": errors, "warnings": warnings}
