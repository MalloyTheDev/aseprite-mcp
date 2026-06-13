"""Godot 4 `SpriteFrames` (.tres) builder.

Turns Aseprite ``--format json-array`` sprite-sheet metadata into a Godot 4
``SpriteFrames`` resource: one animation per Aseprite tag (or a single ``default``
animation when the sprite is untagged), each frame an ``AtlasTexture`` region into the
exported sheet, with per-frame timing derived from Aseprite frame durations.

v1 scope: SpriteFrames only — no pivot/origin/hitbox/9-slice. Aseprite tag *direction*
(reverse/pingpong) is not represented (Godot animations only carry a ``loop`` flag); every
animation uses the caller's ``default_loop``.

Pure-Python (no Aseprite, no IO). The resource text targets Godot 4 (``format=3``).
"""

from __future__ import annotations

from collections import Counter

RESOURCE_TYPE = "SpriteFrames"
RESOURCE_FORMAT = 3
_TEXTURE_ID = "1_sheet"
DEFAULT_ANIMATION_NAME = "default"


def _fmt_float(x: float) -> str:
    """Godot-style float literal — always has a decimal point (e.g. 10 -> '10.0')."""
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s if "." in s else s + ".0"


def _escape(s: str) -> str:
    """Escape a string for a Godot quoted literal (backslash and double-quote)."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _res_path(path: str) -> str:
    """Normalize a texture resource path: forward slashes, quotes escaped."""
    return _escape(str(path).replace("\\", "/"))


def _mode_ms(durations: list[int]) -> int:
    """Most common frame duration (ms), clamped to >= 1. Falls back to 100ms if empty."""
    if not durations:
        return 100
    base = Counter(durations).most_common(1)[0][0]
    return max(1, int(base))


def _animation_specs(frame_count: int, tags: list[dict], default_loop: bool) -> list[dict]:
    """Resolve (name, frame-index list, loop) for each Godot animation.

    Untagged sprites get one `default` animation over every frame. Tag from/to are
    0-based, inclusive, and clamped to the available frames.
    """
    if not tags:
        return [{"name": DEFAULT_ANIMATION_NAME,
                 "indices": list(range(frame_count)), "loop": default_loop}]
    specs = []
    for tag in tags:
        lo = max(0, int(tag.get("from", 0)))
        hi = min(frame_count - 1, int(tag.get("to", frame_count - 1)))
        indices = list(range(lo, hi + 1)) if lo <= hi else []
        specs.append({"name": str(tag.get("name", "")), "indices": indices, "loop": default_loop})
    return specs


def build_spriteframes(
    sheet_data: dict,
    *,
    texture_res_path: str,
    default_loop: bool = True,
) -> str:
    """Build a Godot 4 ``SpriteFrames`` .tres from Aseprite json-array sheet metadata.

    Args:
        sheet_data: Parsed Aseprite ``--format json-array`` data. Requires ``frames`` as a
            *list* of ``{"frame": {"x","y","w","h"}, "duration": <ms>}``; reads optional
            tags from ``meta.frameTags`` (``[{"name","from","to"}]``).
        texture_res_path: The ``res://`` path of the exported sheet PNG inside the Godot
            project (referenced as the AtlasTexture atlas).
        default_loop: ``loop`` flag applied to every generated animation.

    Returns the .tres file text.
    """
    frames = sheet_data.get("frames")
    if not isinstance(frames, list):
        raise ValueError(
            "sheet_data['frames'] must be a list — export with --format json-array."
        )
    if not frames:
        raise ValueError("sheet_data has no frames.")

    tags = (sheet_data.get("meta") or {}).get("frameTags") or []
    specs = _animation_specs(len(frames), tags, default_loop)

    # One AtlasTexture per frame actually referenced by an animation (sorted, deduped).
    referenced = sorted({i for spec in specs for i in spec["indices"]})
    atlas_id = {i: f"AtlasTexture_{i}" for i in referenced}

    load_steps = 1 + len(referenced) + 1  # ext_resource + sub_resources + [resource]
    out: list[str] = [
        f'[gd_resource type="{RESOURCE_TYPE}" load_steps={load_steps} format={RESOURCE_FORMAT}]',
        "",
        f'[ext_resource type="Texture2D" path="{_res_path(texture_res_path)}" id="{_TEXTURE_ID}"]',
        "",
    ]

    for i in referenced:
        rect = frames[i]["frame"]
        out.append(f'[sub_resource type="AtlasTexture" id="{atlas_id[i]}"]')
        out.append(f'atlas = ExtResource("{_TEXTURE_ID}")')
        out.append(
            f'region = Rect2({int(rect["x"])}, {int(rect["y"])}, '
            f'{int(rect["w"])}, {int(rect["h"])})'
        )
        out.append("")

    out.append("[resource]")
    out.append("animations = [" + ", ".join(_animation_block(s, frames, atlas_id) for s in specs) + "]")
    out.append("")  # trailing newline
    return "\n".join(out)


def _animation_block(spec: dict, frames: list[dict], atlas_id: dict[int, str]) -> str:
    """Render one animation dict (frames + loop + name + speed) for the animations array."""
    indices = spec["indices"]
    durations = [int(frames[i].get("duration", 100)) for i in indices]
    base_ms = _mode_ms(durations)
    speed = _fmt_float(1000.0 / base_ms)

    frame_entries = []
    for i, ms in zip(indices, durations):
        frame_entries.append(
            '{\n'
            f'"duration": {_fmt_float(ms / base_ms)},\n'
            f'"texture": SubResource("{atlas_id[i]}")\n'
            '}'
        )
    frames_arr = "[" + ", ".join(frame_entries) + "]"
    loop = "true" if spec["loop"] else "false"
    return (
        '{\n'
        f'"frames": {frames_arr},\n'
        f'"loop": {loop},\n'
        f'"name": &"{_escape(spec["name"])}",\n'
        f'"speed": {speed}\n'
        '}'
    )
