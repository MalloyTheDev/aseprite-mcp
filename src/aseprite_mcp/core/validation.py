"""Pure validation logic for `validate_sprite_for_game_export`.

Kept dependency-free (no Aseprite, no MCP) so the decision logic is unit-testable.
The Aseprite-backed facts (sprite info, corner transparency, export existence,
metadata readability) are gathered by the tool wrapper and passed in here.
"""

from __future__ import annotations

import re

_DEFAULT_LAYER_RE = re.compile(r"Layer \d+$")


def _is_suspicious_layer(name: str) -> bool:
    return name.strip() == "" or bool(_DEFAULT_LAYER_RE.fullmatch(name.strip()))


def evaluate(
    info: dict,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
    tile_multiple: int | None = None,
    allowed_color_modes: list[str] | None = None,
    min_frames: int | None = None,
    max_frames: int | None = None,
    required_tags: list[str] | None = None,
    max_palette_size: int | None = None,
    require_transparent_background: bool = False,
    transparent_corners: list[bool] | None = None,
    missing_exports: list[str] | None = None,
    unreadable_metadata: str | None = None,
    oversized_threshold: int = 1024,
) -> dict:
    """Evaluate a sprite's `get_sprite_info` dict against game-export criteria.

    Returns {passed, checks, errors, warnings}. `passed` is True iff no error-level
    check failed (warnings never fail the validation).
    """
    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, level: str, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "level": level, "detail": detail})
        if not ok:
            (errors if level == "error" else warnings).append(detail or name)

    w, h = info["width"], info["height"]
    mode = info["colorMode"]
    frames = info["frameCount"]
    tag_names = [t["name"] for t in info["tags"]]
    layer_names = [layer["name"] for layer in info["layers"]]
    palette_size = info.get("paletteSize")

    if expected_width is not None:
        check("width", w == expected_width, "error", f"width {w} != expected {expected_width}")
    if expected_height is not None:
        check("height", h == expected_height, "error", f"height {h} != expected {expected_height}")
    if tile_multiple:
        ok = w % tile_multiple == 0 and h % tile_multiple == 0
        check("tile_multiple", ok, "error", f"canvas {w}x{h} is not a multiple of {tile_multiple}")
    if allowed_color_modes:
        check("color_mode", mode in allowed_color_modes, "error",
              f"color mode '{mode}' not in {allowed_color_modes}")
    if min_frames is not None:
        check("min_frames", frames >= min_frames, "error", f"frame count {frames} < min {min_frames}")
    if max_frames is not None:
        check("max_frames", frames <= max_frames, "error", f"frame count {frames} > max {max_frames}")
    if required_tags:
        missing = [t for t in required_tags if t not in tag_names]
        check("required_tags", not missing, "error", f"missing required tags: {missing}")
    if max_palette_size is not None and palette_size is not None:
        check("max_palette_size", palette_size <= max_palette_size, "error",
              f"palette size {palette_size} > max {max_palette_size}")
    if require_transparent_background:
        if transparent_corners is None:
            check("transparent_background", False, "warning",
                  "could not read canvas corners to verify transparency")
        else:
            check("transparent_background", all(transparent_corners), "error",
                  "one or more canvas corners are opaque (expected a transparent background)")
    if missing_exports:
        check("expected_exports", False, "error", f"missing export files: {missing_exports}")
    elif missing_exports is not None:
        check("expected_exports", True, "error", "")
    if unreadable_metadata:
        check("spritesheet_metadata", False, "error",
              f"sprite-sheet metadata missing or unreadable: {unreadable_metadata}")

    # Soft warnings (never fail validation).
    if w > oversized_threshold or h > oversized_threshold:
        check("canvas_size", False, "warning",
              f"large canvas {w}x{h} (> {oversized_threshold}px) may be heavy for a sprite")
    if frames > 1 and not tag_names:
        check("animation_tags", False, "warning", "multi-frame sprite has no animation tags")
    suspicious = [n for n in layer_names if _is_suspicious_layer(n)]
    if suspicious:
        check("layer_names", False, "warning", f"default/blank layer names: {suspicious}")

    return {
        "passed": len(errors) == 0,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
