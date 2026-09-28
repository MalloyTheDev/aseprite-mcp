"""Animation inspection: measure a cycle rather than eyeball a GIF.

An agent cannot watch an animation play, and the problems that matter most are the ones a
still frame hides: a loop that shows its first image twice at the wrap, a pose held by
repeating a frame, a character that sinks a pixel as it lands. `validate_loop` renders
every frame once, in a single Aseprite launch, and reports what it measured.
"""

from __future__ import annotations

from itertools import pairwise

from ..app import mcp
from ..core import loopcheck, motion
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_CANVAS_DIMENSION,
    MAX_MOTION_FRAMES,
    check_count,
    check_list_length,
)
from ..core.manifest import workflow_manifest
from ..core.models import FRAME_GUARD_LUA, FrameRef
from ..core.runner import run_lua
from .common import lua_path, resolve_path

# FNV-1a over the frame's raw pixel bytes, 64-bit so that reporting two frames as
# identical is not a coin toss. A hash rather than a pairwise comparison, so frames can
# be compared with each other, with the same sprite after an edit, and across calls.
# `string.byte` is read in blocks because calling it per byte dominates the cost; a
# 64x64 sprite of 8 frames hashes in about 4ms.
_HASH_LUA = """
local function fnv1a(s)
  local hash = 0xcbf29ce484222325
  local len = #s
  local i = 1
  while i <= len do
    local j = math.min(i + 511, len)
    local block = table.pack(string.byte(s, i, j))
    for k = 1, block.n do
      hash = hash ~ block[k]
      hash = hash * 1099511628211
    end
    i = j + 1
  end
  return string.format("%016x", hash)
end
"""

_MEASURE_LUA = _HASH_LUA + """
local spr = open_sprite(ARG.src)
local first, last = 1, #spr.frames
local tag_name, tag_loops = nil, nil
if ARG.tag ~= nil then
  local tag = nil
  for _, t in ipairs(spr.tags) do if t.name == ARG.tag then tag = t end end
  if tag == nil then error("No tag named '" .. tostring(ARG.tag) .. "'", 0) end
  first = tag.fromFrame.frameNumber
  last = tag.toFrame.frameNumber
  tag_name = tag.name
  -- repeats == 0 means "play forever", which is how a cycle is marked in the file.
  if tag.repeats ~= nil then tag_loops = (tag.repeats == 0) end
end

local lay = nil
if ARG.layer ~= nil then lay = find_layer(spr, ARG.layer) end

local frames = {}
local n = 0
for f = first, last do
  local img = Image(spr.spec)
  img:clear()
  if lay ~= nil then
    -- One layer, composited where it sits, so a moving character can be measured
    -- without the background it is drawn over.
    local cel = lay:cel(f)
    if cel ~= nil then img:drawImage(cel.image, cel.position) end
  else
    img:drawSprite(spr, f)
  end
  local entry = {
    frame = f,
    hash = fnv1a(img.bytes),
    duration_ms = math.floor(spr.frames[f].duration * 1000 + 0.5),
  }
  local b = img:shrinkBounds()
  if b ~= nil and b.width > 0 and b.height > 0 then
    entry.bounds = { x = b.x, y = b.y, width = b.width, height = b.height }
  end
  n = n + 1
  frames[n] = entry
end

RESULT = {
  frames = frames,
  tag = tag_name,
  tag_loops = tag_loops,
  width = spr.width,
  height = spr.height,
  sprite_frame_count = #spr.frames,
}
"""


def _next_actions(report: dict, measurements: dict) -> list[str]:
    failed = {c["name"] for c in report["checks"] if not c["ok"]}
    actions: list[str] = []
    if "no_seam_duplicate" in failed:
        actions.append(
            f"remove_frame(frame={measurements['frames'][-1]['frame']}) to drop the "
            "repeated wrap frame, then validate_loop again."
        )
    if "no_duplicate_adjacent_frames" in failed:
        first_pair = measurements["duplicate_pairs"][0]
        actions.append(
            f"remove_frame(frame={first_pair[1]}) and lengthen frame {first_pair[0]} with "
            "set_frame_duration, so the hold costs a duration instead of a frame."
        )
    if "timing_varies" in failed:
        actions.append(
            "set_frame_duration on the extreme poses (two to four times the passing "
            "frames) so the cycle has a shape in time."
        )
    if "contact_edge_stable" in failed:
        actions.append(
            "Compare contact_rows in the animation section: for a grounded cycle every "
            "frame should share one bottom row."
        )
    if not actions:
        actions.append("export_gif or render_preview to look at a cycle that measures clean.")
    return actions


@mcp.tool()
def validate_loop(
    filename: str,
    tag: str | None = None,
    layer: str | None = None,
    loops: bool | None = None,
    jitter_tolerance: float = loopcheck.DEFAULT_JITTER_TOLERANCE,
) -> dict:
    """Measure an animation and report what is wrong with it, without playing it.

    Renders each frame once (one Aseprite launch), then reports per-frame hashes, content
    bounding boxes, centroids, the bottom row of the drawn content, the spacing series
    between frames, and the durations. On top of the numbers it checks for: a last frame
    identical to the first (a loop's wrap showing one image twice), identical adjacent
    frames (a pose held by repeating a frame instead of lengthening one), uniform frame
    durations, a spacing series that wobbles rather than eases, a contact edge that moves,
    and frames with nothing drawn on them.

    Args:
        tag: Limit the check to one animation tag's frames. Its repeat setting also
            decides whether the seam is treated as a loop's wrap.
        layer: Measure one layer's cels instead of the flattened frame, so a moving
            character can be measured without the background it sits on.
        loops: Override whether these frames are a cycle. One-shots (attack, hurt, death)
            do not wrap, so a repeated last frame is only a warning for them.
        jitter_tolerance: Pixels of spacing wobble to ignore. Integer cel positions make
            1px unavoidable, so that is the default; pass 0 to see every reversal.

    Returns a ``workflow_manifest.v1`` manifest (kind "validation") whose `validation`
    section is `{passed, checks[], errors[], warnings[]}` and whose `animation` section
    carries every measurement. `validation.passed` is the verdict and is false only for
    faults that are wrong whatever the animation is doing; the rest are warnings, because
    a bouncing ball is meant to leave the ground and a flicker is meant to go blank.
    """
    src = resolve_path(filename)
    measured = run_lua(_MEASURE_LUA, {"src": lua_path(src), "tag": tag, "layer": layer})
    wraps = loops if loops is not None else measured.get("tag_loops", True)
    report, measurements = loopcheck.evaluate(
        measured["frames"],
        tag=measured.get("tag"),
        loops=bool(wraps),
        jitter_tolerance=float(jitter_tolerance),
    )
    measurements["layer"] = layer
    measurements["sprite_frame_count"] = measured["sprite_frame_count"]
    return workflow_manifest(
        "validation",
        validation=report,
        animation=measurements,
        warnings=report["warnings"],
        suggested_next_actions=_next_actions(report, measurements),
    )


_OFFSET_LUA = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)

local function cel_at(n)
  local cel = layer:cel(n)
  if cel == nil then
    error("layer '" .. tostring(ARG.layer) .. "' has no cel on frame " .. n ..
          "; draw it or copy_cel onto that frame first", 0)
  end
  return cel
end

-- The first listed frame stays where it is and every other frame is placed relative to
-- it, so the caller describes a movement rather than a set of coordinates.
local anchor = cel_at(require_frame(spr, ARG.steps[1].frame, "frame")).position
local ax, ay = anchor.x, anchor.y

local placed = {}
app.transaction(function()
  for i, step in ipairs(ARG.steps) do
    local n = require_frame(spr, step.frame, "frame")
    local cel = cel_at(n)
    cel.position = Point(ax + step.x, ay + step.y)
    placed[i] = { frame = n, x = ax + step.x, y = ay + step.y }
  end
end)
save_sprite(spr)

RESULT = { layer = layer.name, anchor = { x = ax, y = ay }, positions = placed }
"""


@mcp.tool()
def offset_cels(
    filename: str,
    layer: str,
    frames: list[int],
    dx: int = 0,
    dy: int = 0,
    ease: str = "linear",
    arc_height: float = 0.0,
) -> dict:
    """Move one layer's drawn cel along a path across frames, in one Aseprite launch.

    The cel on the first listed frame stays where it is; every later frame is placed
    along the way to `(dx, dy)` from it, and the last frame lands exactly there. This is
    the same work as one `set_cel_position` per frame, minus the launches and minus
    computing the intermediate positions by hand.

    Args:
        frames: The frames to place, in the order the movement passes through them.
        dx, dy: The whole movement, in pixels, from the first frame to the last.
        ease: How the movement is *spaced*: `linear`, `ease_in` (starts slow),
            `ease_out` (arrives slow), `ease_in_out`, or `gravity` (horizontal speed
            stays even while the vertical accelerates, as a thrown object does).
        arc_height: Bend the path into an arc this many pixels high at its midpoint,
            perpendicular to the straight line between the ends. A jump or a thrown
            object needs this; a slide does not.

    Easing belongs here, in the spacing, and not in the frame durations. Applying a curve
    to both applies it twice, and the result reads as slow motion rather than as weight.

    Positions are whole pixels, so it is the running position that gets rounded and not
    each step: the leftover fraction carries forward instead of being reintroduced every
    frame, which is the difference between spacing that reads as speed and spacing that
    reads as a limp. The returned `deltas` are the spacing a viewer actually sees, and
    `max_error_px` is how far the furthest frame sits from the ideal curve, which stays
    below one pixel.
    """
    if len(frames) < 2:
        raise ValidationFailed(
            f"frames needs at least two frames to distribute a movement over; got "
            f"{len(frames)}. To place a single cel, use set_cel_position."
        )
    check_list_length(
        "frames", frames, MAX_MOTION_FRAMES,
        remedy="Move the cel across fewer frames per call.",
    )
    numbered = [FrameRef.arg(f"frames[{i}]", f) for i, f in enumerate(frames)]
    duplicates = sorted({f for f in numbered if numbered.count(f) > 1})
    if duplicates:
        raise ValidationFailed(
            f"frames lists {duplicates} more than once; a frame can only be placed at one "
            "position, so the later entry would silently win."
        )
    if ease not in motion.EASINGS:
        raise ValidationFailed(
            f"bad value for 'ease': {ease!r}; expected one of {', '.join(motion.EASINGS)}."
        )
    for name, value in (("dx", dx), ("dy", dy), ("arc_height", arc_height)):
        check_count(name, abs(int(value)), MAX_CANVAS_DIMENSION,
                    remedy="That is further than any canvas is wide.")

    plan = motion.plan(len(numbered), int(dx), int(dy),
                       ease=ease, arc_height=float(arc_height))
    steps = [{"frame": frame, "x": x, "y": y}
             for frame, (x, y) in zip(numbered, plan["offsets"], strict=True)]
    result = run_lua(_OFFSET_LUA, {
        "src": lua_path(resolve_path(filename)), "layer": layer, "steps": steps,
    })

    spacing = motion.deltas(plan["offsets"])
    for entry, (before, after) in zip(spacing, pairwise(numbered), strict=True):
        entry["from"], entry["to"] = before, after
    return {
        "layer": result["layer"],
        "frames": numbered,
        "anchor": result["anchor"],
        "positions": result["positions"],
        "requested": {"dx": int(dx), "dy": int(dy)},
        "ease": ease,
        "arc_height": float(arc_height),
        "deltas": spacing,
        "max_error_px": plan["max_error_px"],
    }
