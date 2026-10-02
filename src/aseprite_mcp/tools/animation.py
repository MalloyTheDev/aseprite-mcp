"""Animation: measure a cycle rather than eyeball a GIF, and synthesise the frames between.

An agent cannot watch an animation play, and the problems that matter most are the ones a
still frame hides: a loop that shows its first image twice at the wrap, a pose held by
repeating a frame, a character that sinks a pixel as it lands. `validate_loop` renders
every frame once, in a single Aseprite launch, and reports what it measured.

The other half of the module generates frames rather than judging them. `offset_cels`
moves a cel along a path, `tween_cels` scales, turns and fades it, and `smear_frame`
draws it along its own path for the one frame where the movement is too fast to read as a
position. All three distribute their change the same way, through `core.motion`, so a
scale series and a position series ease identically; all three leave the frame durations
alone, because easing the spacing and the timing at once applies the curve twice.
"""

from __future__ import annotations

import math
from itertools import pairwise

from ..app import mcp
from ..core import inbetween, loopcheck, motion, timing
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_CANVAS_DIMENSION,
    MAX_COLOR_LIST_LENGTH,
    MAX_MOTION_FRAMES,
    MAX_SMEAR_PIXELS,
    MAX_SMEAR_STEPS,
    MAX_SMEAR_STRENGTH,
    MAX_SMEAR_SUBJECT_COLORS,
    MAX_TWEEN_ROTATION_DEG,
    MAX_TWEEN_SAMPLES,
    MAX_TWEEN_SCALE,
    check_count,
    check_list_length,
)
from ..core.manifest import workflow_manifest
from ..core.models import FRAME_GUARD_LUA, ColorSpec, FrameRef
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


# Which frames a call is about, resolved inside Aseprite because a tag's range and the
# sprite's length are only known there. The same block serves the read and the write.
_RANGE_LUA = FRAME_GUARD_LUA + """
local function frame_range(spr)
  if ARG.tag ~= nil then
    local tag = nil
    for _, t in ipairs(spr.tags) do if t.name == ARG.tag then tag = t end end
    if tag == nil then error("No tag named '" .. tostring(ARG.tag) .. "'", 0) end
    local list = {}
    for f = tag.fromFrame.frameNumber, tag.toFrame.frameNumber do list[#list + 1] = f end
    return list, tag.name
  end
  if ARG.frames ~= nil then
    local list = {}
    for i, f in ipairs(ARG.frames) do
      list[i] = require_frame(spr, f, "frames[" .. i .. "]")
    end
    return list, nil
  end
  local list = {}
  for f = 1, #spr.frames do list[f] = f end
  return list, nil
end
"""

# Cel rectangles, not opaque content: this is only needed to tell eased spacing from even
# spacing, and the union of the cel bounds answers that without touching a pixel.
_FRAME_BOUNDS_LUA = """
local function frame_bounds(spr, n)
  local minx, miny, maxx, maxy
  local function visit(layers)
    for _, lyr in ipairs(layers) do
      if lyr.isGroup then
        visit(lyr.layers)
      else
        local cel = lyr:cel(n)
        if cel ~= nil then
          local b = cel.bounds
          if minx == nil or b.x < minx then minx = b.x end
          if miny == nil or b.y < miny then miny = b.y end
          if maxx == nil or b.x + b.width > maxx then maxx = b.x + b.width end
          if maxy == nil or b.y + b.height > maxy then maxy = b.y + b.height end
        end
      end
    end
  end
  visit(spr.layers)
  if minx == nil then return nil end
  return { x = minx, y = miny, width = maxx - minx, height = maxy - miny }
end
"""

_TIMING_READ_LUA = _RANGE_LUA + _FRAME_BOUNDS_LUA + """
local spr = open_sprite(ARG.src)
local list, tag_name = frame_range(spr)
local out = {}
for i, f in ipairs(list) do
  out[i] = {
    frame = f,
    duration_ms = math.floor(spr.frames[f].duration * 1000 + 0.5),
    bounds = frame_bounds(spr, f),
  }
end
RESULT = { frames = out, tag = tag_name, sprite_frame_count = #spr.frames }
"""

_TIMING_WRITE_LUA = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
local before = #spr.frames
app.transaction(function()
  for _, item in ipairs(ARG.timings) do
    local n = require_frame(spr, item.frame, "frame")
    spr.frames[n].duration = item.duration_ms / 1000.0
  end
end)
save_sprite(spr)
-- A hold is a duration. If this count ever moved, something duplicated a frame.
RESULT = { frame_count = #spr.frames, frames_added = #spr.frames - before }
"""


@mcp.tool()
def apply_timing_curve(
    filename: str,
    curve: str = "hold_extremes",
    frames: list[int] | None = None,
    tag: str | None = None,
    base_ms: int = 100,
    hold_frames: list[int] | None = None,
    snap_frames: list[int] | None = None,
) -> dict:
    """Give an animation a shape in time, by setting durations and never duplicating frames.

    Uniform timing is the placeholder every animation starts with and almost none should
    keep. A cycle holds its extremes two to four times as long as the poses it passes
    through; an attack holds the anticipation, snaps through the strike in 20 to 40ms, and
    holds the impact.

    Args:
        curve: `hold_extremes` (the ends of a cycle are held, the passing frames are not),
            `attack` (anticipation, snap, impact, recovery), `ease_in` (starts slow),
            `ease_out` (ends slow), or `flat` (every frame the same, to start over).
        frames: The frames to time, in order. Defaults to a tag's frames, or all of them.
        tag: Time one tag's frames instead of naming them.
        base_ms: The duration of a passing frame. Everything else is a multiple of it.
        hold_frames: Frames to hold whatever the curve says, at three times `base_ms`.
        snap_frames: Frames to snap through, at the shortest duration that still registers.

    A hold is a longer duration on one frame, never a repeated frame: duplicating costs a
    frame, shifts every tag index, and hides the repeat from `validate_loop`. The returned
    `frames_added` is always 0, and it is returned so that claim can be checked.

    Easing here and easing the spacing elsewhere are the same curve applied twice, which
    reads as slow motion rather than as weight. The cels are measured on the way through,
    so asking for an eased curve over spacing that is already eased comes back with a
    warning rather than quietly doing it.
    """
    if curve not in timing.CURVES:
        raise ValidationFailed(
            f"bad value for 'curve': {curve!r}; expected one of {', '.join(timing.CURVES)}."
        )
    if frames is not None and tag is not None:
        raise ValidationFailed(
            "give either frames or tag, not both: a tag already names its frames."
        )
    if frames is not None:
        check_list_length("frames", frames, MAX_MOTION_FRAMES,
                          remedy="Time fewer frames per call.")
        frames = [FrameRef.arg(f"frames[{i}]", f) for i, f in enumerate(frames)]
    holds = [FrameRef.arg("hold_frames", f) for f in (hold_frames or [])]
    snaps = [FrameRef.arg("snap_frames", f) for f in (snap_frames or [])]

    src = lua_path(resolve_path(filename))
    measured = run_lua(_TIMING_READ_LUA, {"src": src, "tag": tag, "frames": frames})
    numbered = [f["frame"] for f in measured["frames"]]
    distances = [entry["distance"] for entry in loopcheck.spacing(measured["frames"])]

    try:
        planned = timing.plan(
            numbered, curve=curve, base_ms=int(base_ms),
            hold_frames=holds, snap_frames=snaps, spacing=distances,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc

    timings = [{"frame": frame, "duration_ms": duration}
               for frame, duration in zip(numbered, planned["durations_ms"], strict=True)]
    applied = run_lua(_TIMING_WRITE_LUA, {"src": src, "timings": timings})

    return {
        # Lua drops a nil field, so an untagged run simply has no `tag` key coming back.
        "tag": measured.get("tag"),
        "curve": curve,
        "base_ms": int(base_ms),
        "snap_ms": planned["snap_ms"],
        "frames": numbered,
        "previous_ms": [f["duration_ms"] for f in measured["frames"]],
        "durations_ms": planned["durations_ms"],
        "roles": planned["roles"],
        "total_duration_ms": sum(planned["durations_ms"]),
        "frame_count": applied["frame_count"],
        "frames_added": applied["frames_added"],
        "warnings": planned["warnings"],
    }


# =============================================================== inbetweens (#124, #126)
# Writing a new image to one frame of a link group writes it to every frame in the group:
# linked cels share one CelData, which carries the image, the position *and* the opacity.
# A generator whose whole job is to give each frame its own drawing therefore cannot run
# over a link group without silently changing frames nobody asked about, so it refuses.
# Measured rather than assumed: assigning to one of four linked cels changed all four.
_LINK_GUARD_LUA = """
local function require_unlinked(spr, layer, frames, who)
  -- Counted in one pass over the timeline rather than once per frame being written: the
  -- frame list may be 512 long, and the nested form was a quarter of a million cel reads.
  local uses = {}
  for f = 1, #spr.frames do
    local cel = layer:cel(f)
    if cel ~= nil then
      local id = cel.image.id
      uses[id] = (uses[id] or 0) + 1
    end
  end
  local shared = {}
  for _, n in ipairs(frames) do
    local cel = layer:cel(n)
    if cel ~= nil and (uses[cel.image.id] or 0) > 1 then
      shared[#shared + 1] = n
    end
  end
  if #shared > 0 then
    error(who .. " writes frame(s) " .. table.concat(shared, ", ") .. " of layer '" ..
          layer.name .. "', and each of those shares one image with another frame (a " ..
          "linked cel), so the write would land on every frame in the group. Nothing " ..
          "was written. Call unlink_cels on those frames first.", 0)
  end
end
"""

# A cel written back trimmed to its own content, through `newCel` rather than through an
# assignment to `cel.image`.
#
# `newCel` because assigning to a linked cel's image writes through to the whole group
# while `newCel` replaces this frame's cel alone; the frames are checked for links before
# anything is written, so this is belt and braces, but it is the right primitive anyway.
#
# Trimmed because a cel's position is a fact other tools read: `offset_cels` anchors on
# it and `smear_frame` takes its movement vector from where the content sits. A
# canvas-sized cel reports the whole canvas as its bounds, which is a claim about the
# drawing that is not true.
_COMMIT_LUA = """
local function commit_trimmed(spr, layer, framenum, img)
  local b = img:shrinkBounds()
  if b == nil or b.width <= 0 or b.height <= 0 then return nil end
  local small = Image(ImageSpec{
    width = b.width, height = b.height,
    colorMode = spr.colorMode, transparentColor = spr.transparentColor,
  })
  small:clear()
  small:drawImage(img, Point(-b.x, -b.y))
  spr:newCel(layer, framenum, small, Point(b.x, b.y))
  return b
end
"""

# Group and tilemap layers hold no pixels of their own, and that is worth naming rather
# than discovering as an empty cel or as a crash deep inside the sampler.
_PIXEL_LAYER_LUA = """
local function require_pixel_layer(layer, who)
  if layer.isGroup then
    error("'" .. layer.name .. "' is a group layer and holds no cels of its own, so " ..
          who .. " has nothing to read; name one of the layers inside it.", 0)
  end
  if layer.isTilemap then
    error("'" .. layer.name .. "' is a tilemap layer: its cels are references to tiles " ..
          "rather than pixels, so there is nothing for " .. who .. " to resample. Edit " ..
          "the tiles themselves with the tilemap tools.", 0)
  end
end
"""

_TWEEN_LUA = (
    FRAME_GUARD_LUA + _LINK_GUARD_LUA + _COMMIT_LUA + _PIXEL_LAYER_LUA + """
-- The point the transform holds still, taken from the cel's own drawn bounds so the
-- caller never has to work out where a contact edge is. `bottom` is the last drawn row
-- rather than one past it: that row then maps to itself exactly, which is the difference
-- between a squash that lands on the ground and one that lands near it.
-- A transcription of `inbetween.anchor_point`, which is the authority. It lives in Python
-- so the pure tier can test every mode, including the degenerate one-pixel box, on CI
-- where there is no editor; it is copied here because the bounds are the editor's to
-- measure and this tool is one Aseprite launch by design, so there is no read pass in
-- which Python could decide first.
--
-- `test_the_lua_anchor_agrees_with_the_python_one` holds the two together, which is the
-- only thing that makes a dual implementation safe. Change one, change both, or the test
-- will say so.
local function anchor_point(b, mode)
  local cx = b.x + (b.width - 1) / 2.0
  local cy = b.y + (b.height - 1) / 2.0
  if mode == "top" then return cx, b.y end
  if mode == "bottom" then return cx, b.y + b.height - 1 end
  if mode == "left" then return b.x, cy end
  if mode == "right" then return b.x + b.width - 1, cy end
  return cx, cy
end

local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
require_pixel_layer(layer, "tween_cels")

local frames = {}
for i, step in ipairs(ARG.steps) do
  frames[i] = require_frame(spr, step.frame, "frames[" .. i .. "]")
end
if layer:cel(frames[1]) == nil then
  error("layer '" .. layer.name .. "' has no cel on frame " .. frames[1] .. ", and that " ..
        "is the frame a tween reads its drawing from. Draw it, or copy_cel onto it first.", 0)
end
require_unlinked(spr, layer, frames, "tween_cels")

local src_img = get_draw_image(spr, layer, frames[1])
local sb = src_img:shrinkBounds()
if sb == nil or sb.width <= 0 or sb.height <= 0 then
  error("the cel on frame " .. frames[1] .. " of layer '" .. layer.name .. "' has " ..
        "nothing drawn on it, so there is nothing to tween. Draw the pose first.", 0)
end
local ax, ay = anchor_point(sb, ARG.anchor)

-- Where each frame's content will land, and so how many samples this call is about to
-- take. Counted before anything is written, because a request too big to run should come
-- back as a number rather than as a stall. The source cel's size is the multiplier and is
-- only knowable with the file open, which is why this cap is enforced here rather than in
-- Python: the tool is one launch by design, so there is no read pass to learn it in.
--
-- The source scan below is in the budget rather than on top of it: on a 4096x4096 canvas
-- that one pass is already 16 million reads, so a cap that ignored it would not bound the
-- call it is there to bound.
--
-- A transcription of `inbetween.tween_sample_budget`, for the same reason as
-- anchor_point above, and held to it by
-- `test_the_lua_sample_budget_agrees_with_the_python_one`. The result reports `samples`
-- and `source_bounds`, which is what lets that test recompute this number from outside
-- and compare rather than trust.
local boxes, samples = {}, sb.width * sb.height
for i, step in ipairs(ARG.steps) do
  local xs, ys = {}, {}
  local corners = {
    { sb.x, sb.y }, { sb.x + sb.width - 1, sb.y },
    { sb.x, sb.y + sb.height - 1 }, { sb.x + sb.width - 1, sb.y + sb.height - 1 },
  }
  for k, c in ipairs(corners) do
    local ox, oy = c[1] - ax, c[2] - ay
    xs[k] = ax + step.f00 * ox + step.f01 * oy
    ys[k] = ay + step.f10 * ox + step.f11 * oy
  end
  local x0 = math.floor(math.min(xs[1], xs[2], xs[3], xs[4]))
  local x1 = math.ceil(math.max(xs[1], xs[2], xs[3], xs[4]))
  local y0 = math.floor(math.min(ys[1], ys[2], ys[3], ys[4]))
  local y1 = math.ceil(math.max(ys[1], ys[2], ys[3], ys[4]))
  local reaches = (x0 < 0) or (y0 < 0) or (x1 > spr.width - 1) or (y1 > spr.height - 1)
  -- A pixel of slop each way, because a nearest-neighbour sample can round into the box
  -- from just outside it, and a dropped edge row is a shape that loses its outline.
  x0, y0 = math.max(0, x0 - 1), math.max(0, y0 - 1)
  x1, y1 = math.min(spr.width - 1, x1 + 1), math.min(spr.height - 1, y1 + 1)
  boxes[i] = { x0 = x0, y0 = y0, x1 = x1, y1 = y1, off_canvas = reaches }
  if x1 >= x0 and y1 >= y0 then samples = samples + (x1 - x0 + 1) * (y1 - y0 + 1) end
end
if samples > ARG.max_samples then
  error("this tween would resample " .. samples .. " pixels across " .. #ARG.steps ..
        " frame(s); maximum is " .. ARG.max_samples .. ". Nothing was written. Tween " ..
        "fewer frames per call, or a smaller scale.", 0)
end

local source_pixels = 0
for y = sb.y, sb.y + sb.height - 1 do
  for x = sb.x, sb.x + sb.width - 1 do
    local _, _, _, a = px_to_rgba(spr, src_img:getPixel(x, y))
    if a > 0 then source_pixels = source_pixels + 1 end
  end
end

local written = {}
app.transaction(function()
  for i, step in ipairs(ARG.steps) do
    local n, box = frames[i], boxes[i]
    local img = Image(spr.spec)
    img:clear()
    local drawn = 0
    for dy = box.y0, box.y1 do
      for dx = box.x0, box.x1 do
        local ox, oy = dx - ax, dy - ay
        local ix = math.floor(ax + step.m00 * ox + step.m01 * oy + 0.5)
        local iy = math.floor(ay + step.m10 * ox + step.m11 * oy + 0.5)
        -- Bounds-checked against the content box, not against the image: Aseprite's
        -- getPixel returns 0xFFFFFFFF off the edge, which decodes as opaque white, so an
        -- unchecked sample paints a white halo around every scaled cel.
        if ix >= sb.x and iy >= sb.y and ix < sb.x + sb.width and iy < sb.y + sb.height then
          local px = src_img:getPixel(ix, iy)
          local _, _, _, a = px_to_rgba(spr, px)
          if a > 0 then
            -- The source pixel, copied: nothing is blended and nothing is averaged, so
            -- no colour appears that the drawing did not already contain.
            img_set(img, dx, dy, px)
            drawn = drawn + 1
          end
        end
      end
    end
    local bounds = commit_trimmed(spr, layer, n, img)
    if bounds == nil then
      error("frame " .. n .. " came out empty: at scale " ..
            string.format("%.4g by %.4g", step.scale_x, step.scale_y) .. " the " ..
            "transformed cel falls entirely outside the " .. spr.width .. "x" ..
            spr.height .. " canvas, or an active selection masked all of it. Nothing " ..
            "was written. Anchor the tween where the result fits, resize_canvas, or " ..
            "deselect first.", 0)
    end
    layer:cel(n).opacity = step.opacity
    written[i] = {
      frame = n, drawn_pixels = drawn, off_canvas = box.off_canvas,
      scale_x = step.scale_x, scale_y = step.scale_y,
      rotate_deg = step.rotate_deg, opacity = step.opacity,
      bounds = { x = bounds.x, y = bounds.y,
                 width = bounds.width, height = bounds.height },
    }
  end
end)
save_sprite(spr)

RESULT = {
  layer = layer.name,
  source_frame = frames[1],
  source_bounds = { x = sb.x, y = sb.y, width = sb.width, height = sb.height },
  source_pixels = source_pixels,
  anchor = { x = ax, y = ay },
  samples = samples,
  frames = written,
}
""")


def _tween_scale(name: str, value: float) -> float:
    """A scale factor, or a refusal naming the number and the cap."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        raise ValidationFailed(f"{name} must be a number; got {value!r}.") from None
    if not scale > 0:
        raise ValidationFailed(
            f"{name} is {scale}; a scale must be greater than 0. A scale of 0 erases the "
            "cel rather than shrinking it, so to end a tween on nothing pass "
            "opacity_to=0 instead."
        )
    if scale > MAX_TWEEN_SCALE:
        raise ValidationFailed(
            f"{name} is {scale}; maximum is {MAX_TWEEN_SCALE}. The sampled area grows "
            "with the product of the two axes, so a bigger scale buys work rather than "
            "size. Scale in stages, or scale_sprite a copy."
        )
    return scale


def _tween_rotation(name: str, value: float) -> int:
    """A rotation in whole degrees. Pixel art has no half-degree rotation to offer."""
    try:
        degrees = round(float(value))
    except (TypeError, ValueError, OverflowError):
        raise ValidationFailed(
            f"{name} must be a number of degrees; got {value!r}."
        ) from None
    if abs(degrees) > MAX_TWEEN_ROTATION_DEG:
        raise ValidationFailed(
            f"{name} is {degrees} degrees; maximum is {MAX_TWEEN_ROTATION_DEG}. Rotation "
            "is periodic, so a larger angle says the same thing as a smaller one."
        )
    return int(degrees)


@mcp.tool()
def tween_cels(
    filename: str,
    layer: str,
    frames: list[int],
    scale_from: float = 1.0,
    scale_to: float = 1.0,
    scale_y_from: float | None = None,
    scale_y_to: float | None = None,
    rotate_from: float = 0.0,
    rotate_to: float = 0.0,
    opacity_from: int = 255,
    opacity_to: int = 255,
    ease: str = "linear",
    anchor: str = "center",
) -> dict:
    """Scale, turn and fade one drawn cel across frames, in one Aseprite launch.

    `offset_cels` moves a cel along a path, which is one of the four things an inbetween
    does. This is the other three. The cel on the **first listed frame is the source**,
    and every listed frame becomes that one drawing resampled by its share of the change:
    frame nine is sampled from the original and not from frame eight, so the rounding
    never compounds.

    **It interpolates a transform, not pixels.** Blending two different drawings gives a
    double exposure, two silhouettes at half strength, which reads as a mistake rather
    than as motion. So this takes one drawing, and when two cels genuinely differ in shape
    there is no honest automatic inbetween: draw the second pose and tween each one out
    from its own extreme, or express the difference as a scale and a turn, which most of
    them are.

    Args:
        frames: The frames to write, in the order the change passes through them. The
            first is the source, and it is rewritten too when `scale_from`, `rotate_from`
            or `opacity_from` is not the identity.
        scale_from, scale_to: The scale at the first and last frame, on both axes.
        scale_y_from, scale_y_to: Override the vertical scale, for squash and stretch,
            where the two axes go opposite ways (0.7 tall against 1.25 wide is a squash
            that keeps its volume). Unset means the same as the horizontal, which is a
            zoom and not a squash.
        rotate_from, rotate_to: Clockwise degrees at the first and last frame, snapped to
            whole degrees. Quarter turns are exact and lose nothing; sampling within about
            15 degrees of one shuffles the edge pixels rather than turning the shape, and
            the result says so in `warnings` instead of pretending otherwise.
        opacity_from, opacity_to: Cel opacity, 0 to 255. This sets the cel's own opacity
            and never bakes alpha into the pixels: a baked fade invents colours that are
            not on the palette. It is the per-frame `set_cel_opacity` done in one call.
        ease: How the change is *spaced*: `linear`, `ease_in` (starts slow), `ease_out`
            (arrives slow), `ease_in_out`, or `gravity` (accelerating, as a falling object
            does). Easing belongs in one place at a time, and `apply_timing_curve` carries
            the durations.
        anchor: The point the transform holds still, taken from the cel's own drawn
            bounds: `center`, `top`, `bottom`, `left` or `right`. This matters more than it
            looks. A scale about the centre makes a ball grow in every direction; a scale
            about `bottom` makes it squash *onto the ground*, which is the one that reads
            as weight, and `validate_loop`'s contact-edge check then confirms that the
            contact row did not move.

    Refuses rather than doing something approximate: fewer than two frames, a frame listed
    twice, a from and to that are identical on every channel (each frame would be
    rewritten with the drawing the source already holds), a scale of zero or below, a
    group or tilemap layer, a source frame with no cel or nothing drawn on it, a frame
    whose transform lands entirely off the canvas, and any frame that shares its image
    with another frame. That last one is the sharp edge: linked cels share one image, one
    position and one opacity, so a tween written into a link group would change every
    frame in it. The refusal names the frames and points at `unlink_cels`.

    Every listed frame after the first is **overwritten** with the transformed source
    rather than blended with what was there. `steps[].bounds` is the written cel's own
    content box, so a scale series can be checked instead of trusted: `rendered_monotone`
    is that check, and it is omitted while the cel is also rotating, because a turning
    shape's bounding box oscillates by design. `steps[].drawn_pixels` is how many opaque
    samples that frame took; `pixels_written` is what landed, and the two differ only when
    an active selection masked part of it, which `pixels_outside_selection` then reports.

    Sampling is nearest-neighbour and copies the source pixel whole, so no colour appears
    that the drawing did not already contain and `palette_conformance` is unchanged.
    """
    if len(frames) < 2:
        raise ValidationFailed(
            f"frames needs at least two frames to distribute a change over; got "
            f"{len(frames)}. A single cel has nothing to be tweened against."
        )
    check_list_length(
        "frames", frames, MAX_MOTION_FRAMES,
        remedy="Tween across fewer frames per call.",
    )
    numbered = [FrameRef.arg(f"frames[{i}]", f) for i, f in enumerate(frames)]
    duplicates = sorted({f for f in numbered if numbered.count(f) > 1})
    if duplicates:
        raise ValidationFailed(
            f"frames lists {duplicates} more than once; a frame holds one image, so the "
            "later entry would silently win."
        )
    if ease not in motion.EASINGS:
        raise ValidationFailed(
            f"bad value for 'ease': {ease!r}; expected one of {', '.join(motion.EASINGS)}."
        )
    if anchor not in inbetween.ANCHORS:
        raise ValidationFailed(
            f"bad value for 'anchor': {anchor!r}; expected one of "
            f"{', '.join(inbetween.ANCHORS)}. The anchor is the point the transform holds "
            "still, and it is read from the cel's own drawn bounds."
        )

    opacity_remedy = "Cel opacity runs from 0 (invisible) to 255 (solid)."
    start = (
        _tween_scale("scale_from", scale_from),
        _tween_scale("scale_y_from", scale_from if scale_y_from is None else scale_y_from),
        _tween_rotation("rotate_from", rotate_from),
        check_count("opacity_from", opacity_from, 255, remedy=opacity_remedy),
    )
    end = (
        _tween_scale("scale_to", scale_to),
        _tween_scale("scale_y_to", scale_to if scale_y_to is None else scale_y_to),
        _tween_rotation("rotate_to", rotate_to),
        check_count("opacity_to", opacity_to, 255, remedy=opacity_remedy),
    )
    if start == end:
        raise ValidationFailed(
            "nothing to tween: the from and to values are identical on every channel, so "
            "each listed frame would be rewritten with the drawing the source already "
            "holds. Give a different scale_to, scale_y_to, rotate_to or opacity_to, or "
            "use offset_cels to move the cel instead."
        )

    plan = inbetween.plan_tween(
        len(numbered),
        scale_from=start[0], scale_to=end[0],
        scale_y_from=start[1], scale_y_to=end[1],
        rotate_from=start[2], rotate_to=end[2],
        opacity_from=start[3], opacity_to=end[3],
        ease=ease,
    )
    steps = [
        {**step, "frame": frame}
        for frame, step in zip(numbered, plan["steps"], strict=True)
    ]
    result = run_lua(_TWEEN_LUA, {
        "src": lua_path(resolve_path(filename)),
        "layer": layer,
        "anchor": anchor,
        "steps": steps,
        "max_samples": MAX_TWEEN_SAMPLES,
    })

    written = result["frames"]
    warnings = list(plan["warnings"])
    clipped = [f["frame"] for f in written if f.get("off_canvas")]
    if clipped:
        warnings.append(
            f"the transformed cel reaches outside the canvas on frames {clipped} and was "
            "clipped there, so those cels hold less than the transform asked for. "
            "resize_canvas, or anchor the tween where the result fits."
        )
    # The rendered extents are the honest check on the scale series. A rotating cel's
    # bounding box oscillates by design, so the check only applies while the angle holds.
    monotone: dict | None = None
    if len({f["rotate_deg"] for f in written}) == 1:
        monotone = {}
        for axis, requested in (
            ("width", [f["scale_x"] for f in written]),
            ("height", [f["scale_y"] for f in written]),
        ):
            if not inbetween.is_monotone(requested):
                continue
            rendered = [f["bounds"][axis] for f in written]
            monotone[axis] = inbetween.is_monotone(rendered)
            if not monotone[axis]:
                warnings.append(
                    f"the requested scale only goes one way but the rendered {axis} "
                    f"({rendered}) reverses, so the series reads as the subject changing "
                    "its mind. Scale further per frame, or over fewer frames."
                )

    return {
        "layer": result["layer"],
        "frames": numbered,
        "source_frame": result["source_frame"],
        "source_bounds": result["source_bounds"],
        "source_pixels": result["source_pixels"],
        "anchor_mode": anchor,
        "anchor": result["anchor"],
        "ease": ease,
        "requested": {
            "scale_from": start[0], "scale_to": end[0],
            "scale_y_from": start[1], "scale_y_to": end[1],
            "rotate_from": start[2], "rotate_to": end[2],
            "opacity_from": start[3], "opacity_to": end[3],
        },
        "steps": [{k: v for k, v in f.items() if k != "off_canvas"} for f in written],
        "samples": result["samples"],
        "rendered_monotone": monotone,
        "pixels_written": result.get("pixels_written", 0),
        "warnings": warnings,
    }


# A smear is two launches, not one: the subject is measured, the trail is planned in
# Python, and the plan is handed back to be drawn. #126 sets no launch budget, and what
# the read pass buys is the whole of the colour judgement. The script never matches a
# colour to a ramp; it is given a lookup table keyed by the raw pixel values the read
# pass found and asked to look things up, so there is one matcher, in Python, with tests,
# rather than a second one in Lua that nearly agrees with `shading.py`'s.
_SMEAR_READ_LUA = FRAME_GUARD_LUA + _PIXEL_LAYER_LUA + """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
require_pixel_layer(layer, "smear_frame")

local here = require_frame(spr, ARG.frame, "frame")
local there = require_frame(spr, ARG.from_frame, "from_frame")

local function content(n)
  if layer:cel(n) == nil then return nil, nil end
  local img = get_draw_image(spr, layer, n)
  local b = img:shrinkBounds()
  if b == nil or b.width <= 0 or b.height <= 0 then return img, nil end
  return img, b
end

local here_img, here_b = content(here)
if here_b == nil then
  error("layer '" .. layer.name .. "' has nothing drawn on frame " .. here .. ", so " ..
        "there is no subject to smear. Draw the pose first, or copy_cel onto it.", 0)
end
local _, there_b = content(there)
if there_b == nil then
  error("layer '" .. layer.name .. "' has nothing drawn on frame " .. there .. ", so " ..
        "there is nothing to measure the movement from. A smear needs two drawn frames: " ..
        "pass from_frame to name a different one.", 0)
end

-- The scan below is per pixel of the subject's content box, and that box is only knowable
-- with the file open, so the cap is enforced here: on a 4096x4096 canvas a full-frame
-- subject is 16 million reads before anything has been planned, let alone drawn.
local area = here_b.width * here_b.height
if area > ARG.max_pixels then
  error("the subject on frame " .. here .. " covers a " .. here_b.width .. "x" ..
        here_b.height .. " box, which is " .. area .. " pixels; maximum is " ..
        ARG.max_pixels .. ". A smear is a moving subject rather than a whole canvas, so " ..
        "name the layer the subject is drawn on.", 0)
end

-- The subject's distinct colours, carried as the raw pixel values the sprite stores so
-- the lookup table built from them can be keyed exactly rather than by a hex round trip.
local seen, colors, color_count, drawn = {}, {}, 0, 0
for y = here_b.y, here_b.y + here_b.height - 1 do
  for x = here_b.x, here_b.x + here_b.width - 1 do
    local px = here_img:getPixel(x, y)
    local r, g, b, a = px_to_rgba(spr, px)
    if a > 0 then
      drawn = drawn + 1
      if seen[px] == nil then
        seen[px] = true
        color_count = color_count + 1
        if color_count <= ARG.max_colors then
          colors[color_count] = { px = px, r = r, g = g, b = b }
        end
      end
    end
  end
end

local shared = {}
local cel = layer:cel(here)
for f = 1, #spr.frames do
  local other = layer:cel(f)
  if f ~= here and other ~= nil and other.image.id == cel.image.id then
    shared[#shared + 1] = f
  end
end

RESULT = {
  layer = layer.name, frame = here, from_frame = there,
  -- Reported because it decides whether the no-ramp fallback can work at all: an
  -- indexed pixel is an offset into a palette and carries no alpha of its own.
  color_mode = colormode_name(spr.colorMode),
  canvas = { width = spr.width, height = spr.height },
  bounds = { x = here_b.x, y = here_b.y, width = here_b.width, height = here_b.height },
  from_bounds = { x = there_b.x, y = there_b.y,
                  width = there_b.width, height = there_b.height },
  drawn_pixels = drawn, color_count = color_count, colors = colors,
  linked_with = shared,
}
"""

_SMEAR_WRITE_LUA = (
    FRAME_GUARD_LUA + _LINK_GUARD_LUA + _COMMIT_LUA + _PIXEL_LAYER_LUA + """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
require_pixel_layer(layer, "smear_frame")
local n = require_frame(spr, ARG.frame, "frame")
if layer:cel(n) == nil then
  error("layer '" .. layer.name .. "' has no cel on frame " .. n .. " any more.", 0)
end
require_unlinked(spr, layer, { n }, "smear_frame")

local src = get_draw_image(spr, layer, n)
local sb = src:shrinkBounds()
if sb == nil or sb.width <= 0 or sb.height <= 0 then
  error("layer '" .. layer.name .. "' has nothing drawn on frame " .. n .. " any more.", 0)
end
-- The vector, the trail length and the colour table were all planned from a measurement
-- taken in the earlier pass, so the subject has to still be where it was. One global lock
-- serializes the Aseprite runs of this process but not the pair of them, so two calls on
-- one sprite can interleave between the passes; without this check the second would draw
-- its trail along the first one's movement and report success.
local e = ARG.expect_bounds
if sb.x ~= e.x or sb.y ~= e.y or sb.width ~= e.width or sb.height ~= e.height then
  error("the subject on frame " .. n .. " moved between the two passes of this call: it " ..
        "was measured at " .. e.x .. "," .. e.y .. " " .. e.width .. "x" .. e.height ..
        " and is now at " .. sb.x .. "," .. sb.y .. " " .. sb.width .. "x" .. sb.height ..
        ", so the planned smear no longer describes its movement. Nothing was written; " ..
        "try again.", 0)
end

local img = Image(spr.spec)
img:clear()

-- Nearest copy last, so the lighter end of the trail covers the darker end where they
-- overlap and the whole thing reads as one shape receding rather than as stripes.
local on_palette = ARG.lut ~= nil
for _, plot in ipairs(ARG.plots) do
  -- Whether a ramp was given decides this once, outside the loop. A missing lookup must
  -- never fall back to the alpha path: that path leaves the palette, and a smear that
  -- quietly did so while reporting a ramp is the exact failure the ramp is here to
  -- prevent. So the table is required to answer, and says so when it cannot.
  local map = nil
  if on_palette then
    map = ARG.lut[plot.shift]
    if map == nil then
      error("no colour table was planned for ramp shift " .. tostring(plot.shift) ..
            "; nothing was written. This is a bug in smear_frame rather than anything " ..
            "about the sprite.", 0)
    end
  end
  for y = sb.y, sb.y + sb.height - 1 do
    for x = sb.x, sb.x + sb.width - 1 do
      local px = src:getPixel(x, y)
      local r, g, b, a = px_to_rgba(spr, px)
      if a > 0 then
        local keep = true
        if ARG.half_perp ~= nil then
          -- Thinning across the movement: the trail is the subject's full width where it
          -- leaves and a single pixel at the tip, which is the shape of a smear rather
          -- than the shape of a rectangle.
          local perp = (x - ARG.centre_x) * ARG.perp_x + (y - ARG.centre_y) * ARG.perp_y
          if perp < 0 then perp = -perp end
          keep = perp <= ARG.half_perp * (1 - plot.t) + 0.5
        end
        if keep then
          if on_palette then
            local c = map[px]
            if c == nil then
              error("the subject on frame " .. n .. " uses a colour that was not there " ..
                    "when it was measured a moment ago, so the sprite changed between " ..
                    "the two passes of this call. Nothing was written; try again.", 0)
            end
            -- The source pixel's own alpha is carried through untouched, so a smear
            -- never alters a silhouette's edge coverage.
            img_set(img, x + plot.dx, y + plot.dy, rgba_to_px(spr, c.r, c.g, c.b, a))
          else
            img_set(img, x + plot.dx, y + plot.dy,
                    rgba_to_px(spr, r, g, b, math.floor(a * plot.alpha / 255 + 0.5)))
          end
        end
      end
    end
  end
end

-- The subject on top and unaltered. A smear describes the movement behind a drawing; it
-- does not replace it, and the pixels the trail was made from have to survive it.
for y = sb.y, sb.y + sb.height - 1 do
  for x = sb.x, sb.x + sb.width - 1 do
    local px = src:getPixel(x, y)
    local _, _, _, a = px_to_rgba(spr, px)
    if a > 0 then img_set(img, x, y, px) end
  end
end

local b = commit_trimmed(spr, layer, n, img)
if b == nil then
  error("frame " .. n .. " came out empty, although its subject was not: an active " ..
        "selection masked every pixel of the smear. Nothing was written. deselect, or " ..
        "select a region the smear lands in.", 0)
end
save_sprite(spr)
RESULT = {
  layer = layer.name, frame = n,
  subject_bounds = { x = sb.x, y = sb.y, width = sb.width, height = sb.height },
  bounds = { x = b.x, y = b.y, width = b.width, height = b.height },
}
""")


def _smear_ramp(ramp: list[str] | None) -> list[tuple[int, int, int]] | None:
    """The ramp as RGB triples, darkest first, or a refusal saying what is wrong with it."""
    if ramp is None:
        return None
    if len(ramp) < 2:
        raise ValidationFailed(
            f"ramp has {len(ramp)} colour(s); a smear needs at least 2 to step down. "
            "Leave ramp unset to fall back to opacity, which fades off the palette."
        )
    check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    out: list[tuple[int, int, int]] = []
    for index, entry in enumerate(ramp):
        try:
            spec = ColorSpec.parse(entry)
        except ValueError as exc:
            raise ValidationFailed(f"ramp[{index}]: {exc}") from exc
        if spec.r is None or spec.g is None or spec.b is None:
            raise ValidationFailed(
                f"ramp[{index}] is {entry!r}, a palette index, and an index does not say "
                "what colour it is outside the sprite holding that palette. Give the ramp "
                "as colours, the way generate_ramp returns it."
            )
        out.append((spec.r, spec.g, spec.b))
    return out


@mcp.tool()
def smear_frame(
    filename: str,
    layer: str,
    frame: int,
    from_frame: int | None = None,
    mode: str = "stretch",
    strength: float = 0.6,
    steps: int | None = None,
    ramp: list[str] | None = None,
) -> dict:
    """Draw one frame's subject along its own path, so fast movement reads as speed.

    Between two frames of a fast movement the eye expects a **smear**: one frame where the
    subject is stretched along where it came from, or drawn several times faintly, so the
    movement reads as speed rather than as teleportation. `offset_cels` produces the
    movement; this describes one frame of it.

    The movement vector is taken from the sprite rather than restated by the caller: it is
    the shift between the centre of the drawn content on `from_frame` and on `frame`. The
    *content* box, not `cel.position`, because any tool here that writes a whole canvas
    back leaves the position at (0, 0) on every frame, and a position diff would then read
    zero while the drawing plainly moved.

    Args:
        frame: The frame to smear. Its own cel is the subject and stays on top, unchanged;
            the trail is drawn behind it. Only this frame is written.
        from_frame: The frame the movement came from. Defaults to the one before `frame`.
        mode: `stretch` draws the subject once, elongated back along the vector and
            thinning to a single pixel at the tip, which is the classic one-frame smear.
            `echo` draws it `steps` times along the vector, each copy a step further down
            the ramp, which is the multiple-exposure smear.
        strength: How far back the smear reaches, as a fraction of the movement. 0.6 is a
            trail that clearly trails; 1.0 reaches all the way to the previous position;
            above 1 it overshoots, which is a real choice an animator makes.
        steps: How many copies `echo` draws. Defaults to 3, and is refused with
            `mode="stretch"` rather than silently ignored.
        ramp: The colours, darkest first, the trail is allowed to use, as `generate_ramp`
            returns them. **Pass this.** Each pixel of the trail is the nearest ramp entry
            to the subject's own colour there, stepped toward the dark end and clamped
            (never wrapped), so `palette_conformance` stays at 1.0, which is the property
            every shading tool here holds to and what a pixel artist actually draws.
            Without it the fallback is opacity, and the fallback **leaves the palette**:
            the trail is then made of colours that are not in the sprite, which is motion
            blur rather than a smear. On an *indexed* sprite the ramp is required rather
            than preferred, and the call is refused without one: an indexed pixel is an
            offset into a palette and carries no alpha, so the fallback would snap every
            copy back to the subject's own colour and draw a solid blob.

    Refuses rather than producing a blur of nothing: a frame with no movement to smear
    (the two content boxes sit at the same place, and the message says where they are), a
    movement too short to smear at this strength (it names the pixels and the length that
    would result), `frame` 1 with no earlier frame, `from_frame` equal to `frame`, either
    frame undrawn, a group or tilemap layer, a ramp of fewer than two colours or one given
    as palette indices, `steps` with `stretch`, and a frame that shares its image with
    another frame, since a linked cel would put the smear on every frame in the group and
    the whole point is that the unsmeared frames are untouched.

    Returns the vector it measured and where it came from, the plots it drew, and the
    cel's bounds before and after, so the claim that the smear lies along the movement can
    be checked. `validate_loop` will now report this frame as breaking the spacing series,
    which is correct: a smear frame is one that legitimately does.
    """
    if mode not in inbetween.SMEAR_MODES:
        raise ValidationFailed(
            f"bad value for 'mode': {mode!r}; expected one of "
            f"{', '.join(inbetween.SMEAR_MODES)}."
        )
    if steps is not None and mode == "stretch":
        raise ValidationFailed(
            "steps only applies to mode='echo', which draws that many copies; a stretch "
            "is one elongated copy whose length comes from strength. Drop steps, or pass "
            "mode='echo'."
        )
    copies = 3 if steps is None else check_count(
        "steps", steps, MAX_SMEAR_STEPS, minimum=1,
        remedy="Past a handful the copies overlap into a solid bar.",
    )
    try:
        reach = float(strength)
    except (TypeError, ValueError):
        raise ValidationFailed(f"strength must be a number; got {strength!r}.") from None
    if not reach > 0:
        raise ValidationFailed(
            f"strength is {reach}; it must be greater than 0. A smear of length zero is "
            "the frame you already have."
        )
    if reach > MAX_SMEAR_STRENGTH:
        raise ValidationFailed(
            f"strength is {reach}; maximum is {MAX_SMEAR_STRENGTH}. Past that the trail "
            "is longer than the movement it is meant to describe."
        )

    here = FrameRef.arg("frame", frame)
    if from_frame is None:
        if here == 1:
            raise ValidationFailed(
                "frame 1 has no earlier frame to have moved from, so there is no vector "
                "to smear along. Smear a later frame, or pass from_frame to name the "
                "frame the movement came from."
            )
        there = here - 1
    else:
        there = FrameRef.arg("from_frame", from_frame)
    if there == here:
        raise ValidationFailed(
            f"from_frame and frame are both {here}, so the measured movement would be "
            "zero by construction. from_frame names where the subject came from."
        )

    ramp_rgb = _smear_ramp(ramp)
    src = lua_path(resolve_path(filename))
    measured = run_lua(_SMEAR_READ_LUA, {
        "src": src, "layer": layer, "frame": here, "from_frame": there,
        "max_colors": MAX_SMEAR_SUBJECT_COLORS, "max_pixels": MAX_SMEAR_PIXELS,
    })

    if measured["linked_with"]:
        raise ValidationFailed(
            f"frame {here} of layer '{measured['layer']}' shares its image with frame(s) "
            f"{measured['linked_with']} (a linked cel), so a smear written here would "
            "appear on all of them and the unsmeared frames would not be untouched. Call "
            f"unlink_cels('{measured['layer']}', [{here}]) first."
        )
    if ramp_rgb is None and measured.get("color_mode") == "indexed":
        raise ValidationFailed(
            "this sprite is indexed, and an indexed pixel is an offset into a palette "
            "with no alpha of its own, so the opacity fallback has nothing to fade: every "
            "trail copy would snap back to the subject's own colour and draw a solid blob "
            "behind it rather than a smear. Pass ramp= so the trail steps down the "
            "palette, which is what indexed art does anyway."
        )
    if measured["color_count"] > MAX_SMEAR_SUBJECT_COLORS:
        raise ValidationFailed(
            f"the subject on frame {here} uses {measured['color_count']} distinct "
            f"colours; maximum is {MAX_SMEAR_SUBJECT_COLORS}. Art with that many colours "
            "has no single colour that is one step darker, which is what a smear is made "
            "of. Smear a layer holding one material, or index the art down first."
        )

    vector = inbetween.smear_vector(measured["from_bounds"], measured["bounds"])
    if vector == (0, 0):
        raise ValidationFailed(
            f"the subject does not move between frames {there} and {here}: its drawn "
            f"content sits at {measured['from_bounds']} on {there} and "
            f"{measured['bounds']} on {here}. There is no vector to smear along, and a "
            "smear of nothing is a blur. Move the cel first (offset_cels), or smear a "
            "pair of frames that do differ."
        )

    plan = inbetween.plan_smear(
        vector, mode=mode, strength=reach, steps=copies,
        ramp_length=0 if ramp_rgb is None else len(ramp_rgb),
    )
    if not plan["plots"]:
        travelled = round(math.hypot(*vector), 2)
        raise ValidationFailed(
            f"the subject moves {travelled}px between frames {there} and {here}, and at "
            f"strength={reach} the smear would be 0px long, so nothing would be drawn. "
            "Raise strength, or smear a pair of frames further apart."
        )

    plots = plan["plots"]
    budget = measured["drawn_pixels"] * len(plots)
    if budget > MAX_SMEAR_PIXELS:
        raise ValidationFailed(
            f"this smear would plot up to {budget} pixels ({measured['drawn_pixels']} in "
            f"the subject times {len(plots)} copies); maximum is {MAX_SMEAR_PIXELS}. "
            "Lower strength, ask for fewer steps, or smear a smaller subject."
        )

    warnings = list(plan["warnings"])
    args = {
        "src": src, "layer": layer, "frame": here, "plots": plots,
        "expect_bounds": measured["bounds"],
        "lut": None, "half_perp": None,
        "centre_x": None, "centre_y": None, "perp_x": None, "perp_y": None,
    }
    if ramp_rgb is None:
        warnings.append(
            "no ramp was given, so the trail is the subject's own colours at reduced "
            "opacity: those blended pixels are not on the palette, and assess_sprite's "
            "palette_conformance will drop. Pass ramp= to keep the smear on the sprite's "
            "own colours."
        )
    else:
        deepest = max(p["shift"] for p in plots)
        headroom = inbetween.ramp_headroom(measured["colors"], ramp_rgb)
        if deepest > headroom:
            warnings.append(
                f"the subject's lightest colour is step {headroom + 1} of "
                f"{len(ramp_rgb)} on this ramp, so only {headroom} step(s) exist below it "
                f"while the smear asks for {deepest}: the copies past that all land on "
                "the darkest entry and read as one band rather than as a trail. Give a "
                "ramp that reaches further down, or ask for fewer steps."
            )
        args["lut"] = inbetween.shift_table(
            measured["colors"], ramp_rgb, sorted({p["shift"] for p in plots})
        )
    if mode == "stretch":
        centre = inbetween.box_centre(measured["bounds"])
        axis = inbetween.perpendicular(vector)
        args.update({
            "centre_x": centre[0], "centre_y": centre[1],
            "perp_x": axis[0], "perp_y": axis[1],
            "half_perp": inbetween.box_half_extent(measured["bounds"], axis),
        })

    applied = run_lua(_SMEAR_WRITE_LUA, args)

    return {
        "layer": applied["layer"],
        "frame": applied["frame"],
        "from_frame": there,
        "mode": mode,
        "strength": reach,
        "copies": len(plots),
        "distinct_positions": plan["distinct_positions"],
        "vector": {"dx": vector[0], "dy": vector[1]},
        "measured_from": {
            "from_bounds": measured["from_bounds"], "bounds": measured["bounds"],
        },
        "on_palette": ramp_rgb is not None,
        "ramp_size": 0 if ramp_rgb is None else len(ramp_rgb),
        "subject_pixels": measured["drawn_pixels"],
        "subject_colors": measured["color_count"],
        "plots": [
            {"dx": p["dx"], "dy": p["dy"], "shift": p["shift"], "alpha": p["alpha"]}
            for p in plots
        ],
        "subject_bounds": applied["subject_bounds"],
        "bounds": applied["bounds"],
        "pixels_written": applied.get("pixels_written", 0),
        "warnings": warnings,
    }
