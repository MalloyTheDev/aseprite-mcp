"""Build the attack showcase: five phases, five durations, and a tag that does not loop.

The other animated pieces here are cycles. This one is a *one-shot*, and a one-shot is
where a scaffolded animation usually goes wrong in three ways at once: the frame count is a
guess, the frames are numbered instead of named, and the whole thing is tagged as a loop
with uniform timing. `scaffold_cycle(kind="attack")` settles all three before a pixel is
drawn, and this piece is the drawing laid over what it built.

**The timing is the thing to look at, and it is not the timing you would guess.** The
curve puts the 24-millisecond frame on the **swing**, not on the impact:

```
  anticipation  240 ms   the wind-up, held long enough to be read as intent
  swing          24 ms   one frame you barely see, which is what makes it a snap
  impact        200 ms   held, because the hit has to land rather than flash past
  recoil         80 ms
  recover        80 ms
```

That ordering is the craft: the fast frame is the blur *between* poses, and the pose that
has to be understood is the one that holds. Uniform timing at 80 ms a frame would run the
same five drawings in the same order and read as a shove. The assertions below pin the snap
to frame two for exactly that reason, because "the shortest frame is the impact" is the
plausible wrong answer and a test that only checked for non-uniformity would accept it.

**The tags are named for the pose.** `attack_anticipation` through `attack_recover`, plus
an `attack` tag over the whole cycle, so a later pass can address one phase without
counting frames.

**Every tag is a one-shot.** Each is written with `repeats=1` rather than left at 0, which
means "play forever" in the file format, and that field is what `validate_loop` reads: a
one-shot tagged as a loop makes the checker report a duplicated seam frame on an animation
that has no seam. The per-phase tags matter as much as the whole-cycle one here, since a
single-frame tag left looping says "hold this pose forever".

The post is the control. It is drawn once, before the scaffold copies frame one five times,
so every phase inherits the same post and the assertions can require it unchanged: what
moves is the blade and the flash, and nothing else.
"""
import math
import pathlib

from aseprite_mcp.tools import (
    animation,
    drawing,
    export,
    inspect,
    palette,
    sprite,
    workflow,
)

NAME = "attack.aseprite"
W, H = 80, 56

# The wielder's hand, off-canvas left of centre so the arc has room to open. The blade is
# an annulus sector about this point, which is what makes every phase the same blade at a
# different angle rather than five unrelated drawings.
PIVOT = (26, 30)
BLADE_IN, BLADE_OUT = 12, 31
# Half-thickness of the blade in degrees, so it tapers: wide at the guard, fine at the
# tip. Seven read as a sewing needle at this radius; a sword has to have some blade.
BLADE_DEG = 10.5
TAPER = 0.55
# The grip runs from the fist to the guard, and the guard sits across the blade's base.
GRIP_IN, GUARD_R, GUARD_HALF = 4, 12, 6

GROUND_Y = 48
POST_X, POST_W = 56, 9
POST_TOP = 16
# Rope bands, as rows measured down from the post's top.
BANDS = (6, 15)

# One angle per phase, in degrees, 0 pointing right and positive turning anticlockwise.
# The swing is a span rather than a pose: it is the frame nobody sees in full, so it is
# drawn as the sweep between the two poses either side of it.
PHASE_ANGLE = {
    "anticipation": (118.0, 118.0),
    "swing": (62.0, 30.0),
    "impact": (2.0, 2.0),
    "recoil": (-14.0, -14.0),
    # Not further than this. At -54 the tip reached y=58 and the blade swung clean through
    # the floor, which `validate_loop` reported as the drawn content's bottom row moving
    # 4px: an art bug found by a timing checker. At -34 the centreline cleared the ground
    # and the blade's own *thickness* still did not, which the assertion in `verify` caught
    # after the first one stopped being able to. Both numbers were measured, not reasoned.
    "recover": (-26.0, -26.0),
}
PHASES = ("anticipation", "swing", "impact", "recoil", "recover")
# What `scaffold_cycle` is expected to build, measured from the tool rather than assumed.
EXPECTED_MS = [240, 24, 200, 80, 80]
SNAP_FRAME = 2


def ramp(dark, light, steps):
    """A ramp from its two ends, by the server's own tool, dark first."""
    out = palette.ramp_between(dark, light, steps=steps)
    colors = out["colors"]
    assert len(colors) == steps, out
    # `ramp_between` reports how many came back distinct, and a ramp that clipped would
    # shade two steps the same colour without saying so anywhere else.
    assert out.get("distinct", steps) == steps, (
        f"the {dark} to {light} ramp collapsed to {out.get('distinct')} colours: {colors}")
    return colors


def background_pixels(wall, earth):
    """The room: a dim wall and an earth floor, full width.

    The first draft left this transparent and every frame read as a blade floating in
    white. A prop needs a floor to stand on before the animation on top of it can be
    judged, and the wall also gives the steel something to be brighter than.
    """
    out = {}
    for y in range(H):
        for x in range(W):
            if y >= GROUND_Y:
                # A lit top course of earth, then darker as it comes forward.
                depth = min(len(earth) - 1, (y - GROUND_Y) // 3)
                out[(x, y)] = earth[len(earth) - 1 - depth]
            else:
                # Darker toward the top, so the eye settles on the post and the arc.
                out[(x, y)] = wall[min(len(wall) - 1, y * len(wall) // GROUND_Y)]
    return out


def hand_pixels(angle, steel, leather):
    """The fist, the grip, the cross-guard and a forearm, so the blade is held.

    The forearm is a *line* with a thickness, from an off-canvas shoulder to the fist. The
    first version stacked a five-row vertical bar at every column, which drew a brown wedge
    that read as a hill of earth rather than as an arm. A limb is a stroke along its own
    length, lit on top, and it tapers.
    """
    out = {}
    a = math.radians(angle)
    dx, dy = math.cos(a), -math.sin(a)
    px, py = -dy, dx

    # Two segments with an elbow, because one straight run from the corner to the hand
    # read as a branch. The upper arm comes in from the left edge and the forearm angles
    # up to the fist, and both are lit along the top so they are round.
    elbow = (PIVOT[0] - 13, PIVOT[1] + 9)
    for a_end, b_end, thick in (((-2, elbow[1] + 3), elbow, 3.0), (elbow, PIVOT, 2.6)):
        span = max(abs(b_end[0] - a_end[0]), abs(b_end[1] - a_end[1]), 1)
        for i in range(span + 1):
            t_along = i / span
            cx = a_end[0] + (b_end[0] - a_end[0]) * t_along
            cy = a_end[1] + (b_end[1] - a_end[1]) * t_along
            half = thick - 0.7 * t_along
            for off in range(-4, 5):
                if abs(off) > half:
                    continue
                x, y = round(cx), round(cy + off)
                if 0 <= x < W and 0 <= y < H:
                    # Three steps across the limb: lit top, body, dark underside.
                    if off <= -half + 0.9:
                        shade = len(leather) - 1
                    elif off >= half - 0.9:
                        shade = 0
                    else:
                        shade = len(leather) // 2
                    out[(x, y)] = leather[shade]

    # The fist: a small round mass at the pivot, lit from above.
    for ddx in range(-3, 4):
        for ddy in range(-3, 4):
            if ddx * ddx + ddy * ddy > 8:
                continue
            x, y = PIVOT[0] + ddx, PIVOT[1] + ddy
            if 0 <= x < W and 0 <= y < H:
                out[(x, y)] = leather[len(leather) - 1 if ddy < 0 else 0]

    # The grip runs from the fist out to the guard, and the guard sits across the base of
    # the blade. Both turn with the wrist.
    for r in range(GRIP_IN, GUARD_R):
        for off in (-1, 0, 1):
            x = round(PIVOT[0] + r * dx + off * px)
            y = round(PIVOT[1] + r * dy + off * py)
            if 0 <= x < W and 0 <= y < H:
                out[(x, y)] = leather[0 if off else len(leather) - 1]
    for side in range(-GUARD_HALF, GUARD_HALF + 1):
        taper = 1 if abs(side) < GUARD_HALF - 1 else 0
        for along in range(0, 1 + taper):
            x = round(PIVOT[0] + (GUARD_R + along) * dx + side * px)
            y = round(PIVOT[1] + (GUARD_R + along) * dy + side * py)
            if 0 <= x < W and 0 <= y < H:
                out[(x, y)] = steel[len(steel) - 2 if along else len(steel) // 2]
    return out


def post_pixels(wood, rope):
    """The training post and the ground it stands in, which never move."""
    out = {}
    for y in range(POST_TOP, GROUND_Y):
        for x in range(POST_X, POST_X + POST_W):
            # Lit from the left, so the post is round rather than a plank: the column
            # position picks the step, and the two edge columns are the darkest.
            across = (x - POST_X) / (POST_W - 1)
            step = (len(wood) - 1) - round(abs(across - 0.32) * (len(wood) - 1) * 1.6)
            out[(x, y)] = wood[max(0, min(len(wood) - 1, step))]
        # Grain: one darker column that wanders, so the wood is not a gradient.
        grain = POST_X + 2 + (y // 7) % 3
        out[(grain, y)] = wood[max(0, (len(wood) - 1) // 2 - 1)]
    for band in BANDS:
        for y in range(POST_TOP + band, POST_TOP + band + 2):
            for x in range(POST_X - 1, POST_X + POST_W + 1):
                edge = x in (POST_X - 1, POST_X + POST_W)
                out[(x, y)] = rope[0 if edge else len(rope) - 1]
    # The ground: a lip of earth either side of the post, not a ruled line.
    for x in range(POST_X - 7, POST_X + POST_W + 7):
        lip = (x * 7 % 3) - 1
        for y in range(GROUND_Y + lip, min(H, GROUND_Y + lip + 3)):
            if 0 <= x < W:
                out[(x, y)] = rope[0]
    return out


def blade_pixels(angle, steel, width=1.0, dim=0):
    """One blade at one angle, stepped in pixels across its width rather than in degrees.

    Sampling five fixed fractions of an angular half-width put two bright samples on some
    rows and none on others once they rounded to pixels, which drew a ladder across the
    blade: it read as a zipper. Stepping the perpendicular offset in whole pixels gives a
    solid blade with one bright edge, one dark spine and a lit tip, which is how a bevel
    actually reads.

    `width` and `dim` exist for the echoes of a sweep: a thinner, darker copy of the same
    blade at an earlier angle.
    """
    out = {}
    a = math.radians(angle)
    dx, dy = math.cos(a), -math.sin(a)
    px, py = -dy, dx
    top = len(steel) - 1
    # Half steps along both axes. Whole steps in polar coordinates leave gaps once they
    # rasterise at an angle, and the blade came out speckled, as though it had holes.
    for r_half in range(BLADE_IN * 2, (BLADE_OUT + 1) * 2):
        r = r_half / 2
        along = (r - BLADE_IN) / (BLADE_OUT - BLADE_IN)
        half_deg = BLADE_DEG * (1.0 - TAPER * along) * width
        half = max(1, round(r * math.radians(half_deg)))
        for off_half in range(-half * 2, half * 2 + 1):
            off = off_half / 2
            x = round(PIVOT[0] + r * dx + off * px)
            y = round(PIVOT[1] + r * dy + off * py)
            if not (0 <= x < W and 0 <= y < H):
                continue
            if off >= half - 0.5:
                step = top                      # the leading edge catches the light
            elif off <= -half + 0.5:
                step = 1                        # the trailing spine stays dark
            else:
                step = top - 2 + round(along)    # the body, brighter toward the tip
            out[(x, y)] = steel[max(0, min(top, step - dim))]
    # The tip, so the blade ends in a point rather than a flat cut.
    for extra in (1, 2):
        x = round(PIVOT[0] + (BLADE_OUT + extra) * dx)
        y = round(PIVOT[1] + (BLADE_OUT + extra) * dy)
        if 0 <= x < W and 0 <= y < H:
            out[(x, y)] = steel[max(0, top - dim - extra)]
    return out


def sweep_pixels(angle_from, angle_to, steel):
    """The swing: three discrete echoes, not a filled fan.

    A continuous sweep drawn opaque was a grey quadrilateral that read as a dustpan. A blur
    on an opaque sprite is made of *fewer* pixels at *earlier* positions, which is the same
    thing `smear_frame`'s echo mode does, so the trail is three thinning copies and only
    the leading one is a whole blade.
    """
    out = {}
    for index, (frac, width, dim) in enumerate(((0.0, 0.45, 3), (0.5, 0.7, 2), (1.0, 1.0, 0))):
        angle = angle_from + (angle_to - angle_from) * frac
        echo = blade_pixels(angle, steel, width=width, dim=dim)
        if index < 2:
            # Dithered, so an echo is see-through rather than a paler solid.
            echo = {pos: c for pos, c in echo.items() if (pos[0] + pos[1]) % 2 == 0}
        out.update(echo)
    return out


def flash_pixels(hot):
    """The impact: spokes thrown off the contact point, and a lit dent in the post."""
    out = {}
    contact = (POST_X, PIVOT[1] - 1)
    for deg in (-62, -34, -8, 14, 40, 66):
        a = math.radians(deg)
        for r in range(3, 11):
            x = round(contact[0] + r * math.cos(a))
            y = round(contact[1] - r * math.sin(a))
            if 0 <= x < W and 0 <= y < H:
                out[(x, y)] = hot[max(0, len(hot) - 1 - r // 3)]
    for dy in (-2, -1, 0, 1, 2):
        for dx in (0, 1, 2):
            x, y = contact[0] + dx, contact[1] + dy
            if 0 <= x < W and 0 <= y < H:
                out[(x, y)] = hot[-1 if abs(dy) < 2 else len(hot) - 2]
    return out


def plot(frame, pixels):
    if pixels:
        drawing.draw_pixels(
            NAME,
            [{"x": x, "y": y, "color": c} for (x, y), c in sorted(pixels.items())],
            frame=frame,
        )


def main():
    steel = ramp("#1d2531", "#eef3f8", 7)
    wood = ramp("#33210f", "#b07e4d", 5)
    rope = ramp("#2a2016", "#c8a86a", 3)
    hot = ramp("#f0902a", "#fffbe8", 4)
    wall = ramp("#171621", "#3c3949", 4)
    earth = ramp("#241a10", "#6d5134", 4)
    leather = ramp("#241611", "#8a5531", 4)

    sprite.create_sprite(NAME, W, H, color_mode="rgb", overwrite=True)
    # The room and the post go on before the scaffold, because the scaffold copies frame
    # one: draw what does not move once and every phase inherits it identically. Drawing a
    # static prop five times is how it develops a twitch.
    post = post_pixels(wood, rope)
    plot(1, {**background_pixels(wall, earth), **post})

    built = workflow.scaffold_cycle(NAME, "attack")
    animation = built["animation"]
    assert animation["durations_ms"] == EXPECTED_MS, animation
    assert animation["loops"] is False, animation
    phases = [p["phase"] for p in animation["phases"]]
    assert phases == list(PHASES), phases

    flash = flash_pixels(hot)
    blades = {}
    for index, phase in enumerate(PHASES, start=1):
        lo, hi = PHASE_ANGLE[phase]
        blades[phase] = (sweep_pixels(lo, hi, steel) if lo != hi
                         else blade_pixels(lo, steel))
        # The hand turns with the blade and is drawn under it, so the guard sits behind
        # the steel rather than on top of it.
        plot(index, {**hand_pixels(PHASE_ANGLE[phase][1], steel, leather),
                     **blades[phase]})
        if phase == "impact":
            plot(index, flash)

    verify(post, flash, blades)

    out = pathlib.Path(NAME).with_suffix("")
    export.export_spritesheet(NAME, f"{out}_sheet.png", sheet_type="horizontal",
                              padding=1, overwrite=True)
    export.export_gif(NAME, f"{out}.gif", overwrite=True)
    print(f"wrote {out}_sheet.png and {out}.gif: {len(PHASES)} phases, "
          f"{animation['total_duration_ms']} ms, loops={animation['loops']}")


def still_window(post, moving):
    """The largest patch of post that nothing moving ever enters, searched exhaustively.

    Returned as (x, y, w, h) for `get_pixels`. Three hand-picked rectangles failed before
    this, each for the one reason that is not a defect: one sat over the contact point
    where the flash lands, one was crossed by the recoil blade, and a one-directional
    search for a four-row band found nothing once the blade got thicker. So this tries
    every band and every height and keeps the one with the most post in it, which means
    the control can only fail when there is genuinely nothing still left to hold.
    """
    best = None
    for height in (4, 3, 2):
        for top in range(POST_TOP, GROUND_Y - height + 1):
            box = (POST_X - 1, top, POST_W + 2, height)
            inside = {(x, y)
                      for x in range(box[0], box[0] + box[2])
                      for y in range(box[1], box[1] + box[3])}
            if inside & moving:
                continue
            posts = len(inside & set(post))
            if posts and (best is None or posts > best[0]):
                best = (posts, box)
        if best is not None:
            return best[1]
    raise AssertionError(
        "no patch of the post is free of the blade and the flash on every frame, so "
        "there is nothing this piece can hold still as a control")


def verify(post, flash, blades):
    """What this piece claims, read back off the saved sprite rather than off the call."""
    info = inspect.get_sprite_info(NAME)
    assert info["frameCount"] == len(PHASES), info["frameCount"]

    # 1. The timing is shaped, and the snap is on the swing. "Not uniform" is the weak
    # version of this claim and would accept the snap being anywhere.
    durations = [round(f["duration"] * 1000) for f in info["frames"]]
    assert durations == EXPECTED_MS, durations
    assert len(set(durations)) > 1, "uniform timing is the placeholder, not the animation"
    assert durations.index(min(durations)) + 1 == SNAP_FRAME, (
        f"the shortest frame is {durations.index(min(durations)) + 1} and should be the "
        f"swing at {SNAP_FRAME}: the blur goes between the poses, and the pose that has "
        "to be understood is the one that holds")
    assert durations[2] > durations[1] * 4, (
        "the impact has to hold much longer than the swing or the hit does not land")

    # 2. A tag per phase, named for the pose, plus the whole cycle, and every one a
    # one-shot. A per-phase tag left at 0 says "hold this pose forever".
    tags = {t["name"]: t for t in info["tags"]}
    expected = {"attack", *(f"attack_{p}" for p in PHASES)}
    assert set(tags) == expected, f"tags are {sorted(tags)}, expected {sorted(expected)}"
    looping = [name for name, t in tags.items() if t["repeats"] == 0]
    assert not looping, f"these tags still say play forever: {looping}"
    assert tags["attack"]["from"] == 1 and tags["attack"]["to"] == len(PHASES)
    for index, phase in enumerate(PHASES, start=1):
        one = tags[f"attack_{phase}"]
        assert one["from"] == one["to"] == index, (phase, one)

    # 3. `validate_loop` agrees it is not a loop, which is the observable consequence of
    # `repeats` and the reason the field is worth setting: on a one-shot it must not go
    # looking for a seam between the last frame and the first.
    checked = animation.validate_loop(NAME, tag="attack")
    measured = checked["animation"]
    assert measured["loops"] is False, measured
    assert measured["seam_duplicate"] is False, measured
    assert measured["uniform_timing"] is False, measured
    assert not measured["duplicate_pairs"], measured["duplicate_pairs"]
    assert not measured["empty_frames"], measured["empty_frames"]
    seam = [c for c in checked["validation"]["checks"]
            if c["name"] == "no_seam_duplicate"]
    assert seam and seam[0]["ok"], (
        f"a one-shot was faulted for a seam it does not have: {seam}")
    # The blade must not swing through the floor, which `validate_loop` reported as a
    # 4px contact drift when it did. That measurement stopped being able to say so once
    # the room got a background: the drawn content now reaches the canvas edge on every
    # frame, so the drift is zero whatever the blade does, and asserting it would be
    # asserting nothing. The check moved to where it still bites.
    assert measured["contact_drift_px"] == 0, measured["contact_rows"]
    below = {phase: sorted((x, y) for (x, y) in pixels if y >= GROUND_Y)[:3]
             for phase, pixels in blades.items()}
    through = {phase: hits for phase, hits in below.items() if hits}
    assert not through, (
        f"the blade swings into the ground on {sorted(through)}: {through}. An arc that "
        "passes through the floor is the defect the contact drift used to catch.")

    # 4. The post never moves, and the blade always does. The first is what makes the
    # second mean something: five frames that all changed could be five unrelated drawings.
    # A window on the post that nothing moving ever touches, searched for rather than
    # chosen. Two hand-picked rectangles failed here before this, each for the one reason
    # that is not a defect: the first sat over the contact point, where the flash
    # legitimately lands, and the second was crossed by the recoil blade. Both times the
    # fix was not a better guess. The window is derived from the union of everything that
    # is supposed to move, so it cannot be wrong and cannot silently stop containing post.
    moving = set(flash)
    for pixels in blades.values():
        moving |= set(pixels)
    box = still_window(post, moving)
    first_post = inspect.get_pixels(NAME, *box, frame=1)["pixels"]
    seen = []
    for frame in range(1, len(PHASES) + 1):
        if frame > 1:
            assert inspect.get_pixels(NAME, *box, frame=frame)["pixels"] == first_post, (
                f"the post changed on frame {frame}; only the blade and the flash move")
        blade_box = (PIVOT[0] - 4, 2, 34, 44)
        seen.append(str(inspect.get_pixels(NAME, *blade_box, frame=frame)["pixels"]))
    assert len(set(seen)) == len(PHASES), (
        "two phases drew the same blade, so the arc is not moving through all five")
    print("verified: 5 named one-shot phases, snap on the swing, post still, blade moving")


if __name__ == "__main__":
    main()
