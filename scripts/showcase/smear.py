"""Build the smear showcase: fast movement that reads as speed, on an indexed palette.

Two frames of something moving quickly are two frames of it being in two places, which the
eye reads as teleportation rather than as speed. A **smear** is the frame an animator draws
to fix that: the subject stretched back along where it came from, or drawn several times
faintly. `smear_frame` takes the vector from the cels themselves rather than from the
caller, so there is nothing to keep in sync with the drawing.

**The trail is made of colours the sprite already had.** Each pixel of it is the nearest
ramp entry to the subject's own colour there, stepped toward the dark end and clamped, so
the smear never invents a colour and `palette_conformance` stays at 1.0. The fallback
without a ramp is opacity, which fades off the palette, and on an indexed sprite that is
worse than useless: there is no alpha to fade through, so the tool refuses rather than
producing a trail that snaps back to the subject's own colour.

**Why this piece is indexed.** `smear_frame` resolves its ramp in Python into a
colour-to-colour lookup table, so it never passes a ramp to Lua, so the harness that
reports what a ramp becomes on an indexed palette had nothing to measure and this was the
one ramp-taking tool with no such reading (#173). The snap still happened: those table
targets resolve through the palette like any other colour, and two shift levels landing on
one entry draw two trail copies of identical colour. The reading exists now, and the
assertions below exercise both sides of it: the committed art uses a palette that holds the
whole trail, and a deliberately collapsed palette is checked separately to prove the
warning fires and names the shifts that collided.

That asymmetry is deliberate. A showcase image should be the tool working, so the picture
is the good case; the defect belongs in an assertion, where it can be proved without
shipping a banded sprite as though it were the point.

Three panels, composed into one strip: the movement with no smear, the `stretch` smear, and
the `echo` smear. The strip is the comparison and the GIF is the thing actually moving.
"""
import pathlib

from PIL import Image

from aseprite_mcp.tools import (
    animation,
    drawing,
    export,
    frames,
    inspect,
    layers,
    palette,
    sprite,
)

NAME = "smear.aseprite"
W, H = 96, 40
LAYER = "bolt"
# `create_sprite` names its first layer this, and it holds the room rather than the bolt.
BACKDROP = "Layer 1"

# The subject: a lit sphere, because a sphere is the shape whose shading is hardest to fake
# and easiest to check, and a smear of one is unambiguous about which way it went.
RADIUS = 7
FROM_X, TO_X = 30, 62
CENTRE_Y = 19
# Where the light is, in pixels, relative to the centre. Up and to the left, matching the
# rest of the showcase so the pieces look like one set.
LIGHT = (-0.45, -0.5)

BG = "#121019"
# The bolt's ramp, darkest first, which is also what the trail is allowed to use.
RAMP_ENDS = ("#1b2b4a", "#dff2ff")
# How long the trail is decides how many ramp steps it asks for, at roughly one step per
# three or four pixels, so the movement and the ramp have to be chosen together. A 50-pixel
# jump at strength 0.7 asked for ten steps, which no sensible ramp has below a subject.
# Eleven steps, and the bolt only ever uses the top six of them. That is not decoration:
# the trail steps *down* the ramp from each subject pixel's own colour, so the subject's
# darkest pixel needs as many steps below it as the smear asks for. The first version drew
# the bolt across a seven-step ramp starting at step 5, and both warnings fired at once:
# the headroom one said only four steps existed below while the smear wanted six, and the
# indexed reading said every deep shift therefore landed on the darkest entry and the
# trail banded. A trail needs somewhere to go.
RAMP_STEPS = 11
BOLT_FLOOR = 5
# A palette that cannot hold the trail: the same ramp crushed to three entries, so several
# shift levels resolve to one of them. Used only to prove the reading fires.
CRUSHED_STEPS = 4


def sphere(colors, cx, cy):
    """A lit sphere as {(x, y): colour}, shaded by how much each pixel faces the light."""
    out = {}
    top = len(colors) - 1
    for dy in range(-RADIUS, RADIUS + 1):
        for dx in range(-RADIUS, RADIUS + 1):
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > RADIUS + 0.2:
                continue
            # The facing term is the dot product of the surface normal with the light, which
            # on a sphere drawn flat is just how far the pixel is toward the light.
            facing = (dx / RADIUS) * LIGHT[0] + (dy / RADIUS) * LIGHT[1]
            lit = 0.5 + facing - 0.45 * (dist / RADIUS) ** 2
            step = max(BOLT_FLOOR, min(top, BOLT_FLOOR + round(lit * (top - BOLT_FLOOR))))
            # A rim one step up on the far side, which is what keeps a sphere from reading
            # as a disc: light wraps a little past the terminator.
            if dist > RADIUS - 1.1 and facing < -0.1:
                step = max(BOLT_FLOOR, step + 1)
            out[(cx + dx, cy + dy)] = colors[step]

    # A specular, and it is load-bearing rather than decorative. A stretch smear asks for
    # one shift level per ramp entry, and it measures the room it has by where the
    # *subject's lightest* colour sits: without a pixel on the ramp's top step the trail
    # is one step short of its own ramp and the tool says so, correctly. Two drafts were
    # spent lengthening the ramp and shortening the movement before reading the message
    # properly: the fix was a highlight.
    sx = round(cx + LIGHT[0] * RADIUS * 0.52)
    sy = round(cy + LIGHT[1] * RADIUS * 0.52)
    for ddx, ddy in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 0), (0, -1)):
        if (sx + ddx - cx) ** 2 + (sy + ddy - cy) ** 2 <= (RADIUS - 1) ** 2:
            out[(sx + ddx, sy + ddy)] = colors[top]
    return out


def plot(frame, pixels, layer=LAYER):
    drawing.draw_pixels(
        NAME,
        [{"x": x, "y": y, "color": c} for (x, y), c in sorted(pixels.items())],
        layer=layer, frame=frame,
    )


def build(ramp_colors, palette_colors):
    """A two-frame sprite: the bolt at the left, then at the right. No smear yet."""
    sprite.create_sprite(NAME, W, H, color_mode="indexed", overwrite=True)
    palette.set_palette(NAME, palette_colors)
    # The background is its own layer, so the smear has something to be drawn against and
    # the bolt's layer holds only the bolt: `smear_frame` takes one layer's cel as the
    # subject, and a subject that included the backdrop would smear the room.
    drawing.fill_layer(NAME, BG, layer=BACKDROP, frame=1)
    layers.add_layer(NAME, LAYER)
    plot(1, sphere(ramp_colors, FROM_X, CENTRE_Y))
    # An appended frame is empty, so the backdrop has to be filled on it too. Copying
    # frame one would have brought the backdrop with it, but `add_frame(copy_from=...)`
    # inserts rather than appends and renumbers what is already there (#222), which is
    # not a thing to rely on from a generator that asserts frame numbers.
    frames.add_frame(NAME, duration_ms=90)
    drawing.fill_layer(NAME, BG, layer=BACKDROP, frame=2)
    plot(2, sphere(ramp_colors, TO_X, CENTRE_Y))


# The panels are composed at 3x, because a smear is a handful of pixels wide and the
# comparison is the point: at 1x the three stages are hard to tell apart in a README.
PANEL_SCALE = 3
GAP = 6


def panel(path, frame):
    """Export one frame and hand back the path the tool actually wrote.

    `export_png` returns its resolved path, which is the one to open: the filename given
    here is relative to the MCP workspace, not to the working directory, and opening the
    relative name is how the first version of this looked for the file in the repo.
    """
    out = export.export_png(NAME, path, frame=frame, scale=PANEL_SCALE, overwrite=True)
    return pathlib.Path(out["output"])


def main():
    ramp_colors = palette.ramp_between(*RAMP_ENDS, steps=RAMP_STEPS)["colors"]
    palette_colors = ["#00000000", BG, *ramp_colors]

    out = pathlib.Path(NAME).with_suffix("")

    # Panel one: the movement as it arrives, with no smear. Two positions and nothing
    # between them, which is the problem the tool exists for.
    build(ramp_colors, palette_colors)
    bare_path = panel(f"{out}_bare.png", 2)

    # Panel two: the classic one-frame smear.
    build(ramp_colors, palette_colors)
    stretched = animation.smear_frame(NAME, LAYER, 2, mode="stretch", strength=0.45,
                                      ramp=ramp_colors)
    assert stretched["pixels_written"] > 0, stretched
    # A stretch trail is as long as the ramp, which is the one thing about this mode worth
    # knowing: it asks for one shift level per ramp entry, so on a *shaded* subject the
    # darker pixels run out of ramp before the trail ends and clamp at the dark entry.
    # The reading says so, and it is right. It cannot be drawn around: avoiding it would
    # mean a subject painted in a single colour. So the piece reports it rather than
    # pretending, and asserts that this is the clamp and not a palette that is too small.
    stretch_warning = " ".join(str(w) for w in stretched.get("warnings", []))
    assert "same colour" in stretch_warning, (
        f"the stretch trail no longer reports its clamp: {stretch_warning}")
    # Asserted on the numbers rather than on the sentence, because the sentence is wrong
    # here and is filed as #226: it blames the palette and suggests adding colours, while
    # `declared == resolved == exact` says the palette holds every target exactly. The
    # colliding targets are all the ramp's darkest entry, identical before the palette is
    # ever consulted. When that issue is fixed the prose will change and these numbers
    # will not, which is the point of asserting them.
    reading = stretched["trail_on_palette"]
    assert reading["exact"] == reading["declared"] == reading["resolved"], reading
    # `steps` describes the *ramp* against the palette, every entry distinct and exact,
    # which is the proof that the palette is not the problem. The collision the warning
    # reports is computed per subject colour through the shift table and is not in here,
    # which is itself part of why the message can disagree with the numbers.
    assert all(s["exact"] for s in reading["steps"]), reading["steps"]
    stretch_path = panel(f"{out}_stretch.png", 2)

    # Panel three: the multiple-exposure smear.
    build(ramp_colors, palette_colors)
    echoed = animation.smear_frame(NAME, LAYER, 2, mode="echo", steps=3, strength=0.45,
                                   ramp=ramp_colors)
    assert echoed["pixels_written"] > 0, echoed
    # `echo` takes its step count explicitly, but the three copies are spread across the
    # ramp rather than placed at shifts one, two and three, so the deepest one clamps too.
    # Measured: shifts 7 and 10 both land on the ramp's darkest entry. Which means **this
    # reading fires for any shaded subject on an indexed sprite**, because the only subject
    # that cannot clamp somewhere is one painted in a single colour. There is no clean case
    # to ship, so the piece stops pretending there is and asserts the thing that actually
    # separates the two causes instead. See #226.
    echo_reading = echoed["trail_on_palette"]
    assert echo_reading["exact"] == echo_reading["declared"], echo_reading
    echo_path = panel(f"{out}_echo.png", 2)
    export.export_gif(NAME, f"{out}.gif", overwrite=True)

    # Stacked rather than side by side: the three stages differ along the direction of
    # travel, so stacking keeps them in register and the eye compares straight down.
    images = [Image.open(path).convert("RGB")
              for path in (bare_path, stretch_path, echo_path)]
    height = sum(i.height for i in images) + GAP * (len(images) - 1)
    strip = Image.new("RGB", (max(i.width for i in images), height), (10, 9, 14))
    offset = 0
    for image in images:
        strip.paste(image, (0, offset))
        offset += image.height + GAP
    stages = bare_path.with_name("smear_stages.png")
    strip.save(stages)

    verify(ramp_colors, palette_colors, stretched, echoed)
    print(f"wrote {stages.name} and {out}.gif: stretch "
          f"{stretched['pixels_written']} px, echo {echoed['pixels_written']} px")


def verify(ramp_colors, palette_colors, stretched, echoed):
    """What this piece claims, including the reading that only an indexed sprite gets."""
    # 1. The trail lies between the two positions and behind the subject, which is what
    # makes it a smear rather than a second bolt. Read a band left of the subject.
    build(ramp_colors, palette_colors)
    animation.smear_frame(NAME, LAYER, 2, mode="stretch", strength=0.45, ramp=ramp_colors)
    gap = inspect.get_pixels(NAME, FROM_X + RADIUS + 4, CENTRE_Y - 2,
                             TO_X - FROM_X - 2 * RADIUS - 8, 4, frame=2)["pixels"]
    painted = {px for row in gap for px in row if px[:7].lower() != BG}
    assert painted, "nothing was drawn between the two positions, so there is no trail"

    # 2. Every trail colour is on the ramp. The trail is allowed the ramp and nothing else,
    # which is the property that keeps palette_conformance at 1.0.
    allowed = {c.lower() for c in ramp_colors}
    off = {px[:7].lower() for px in painted} - allowed
    assert not off, f"the trail used colours that are not on the ramp: {sorted(off)}"

    # 3. The subject itself is untouched: the trail goes behind it.
    build(ramp_colors, palette_colors)
    box = (TO_X - RADIUS, CENTRE_Y - RADIUS, 2 * RADIUS + 1, 2 * RADIUS + 1)
    before = inspect.get_pixels(NAME, *box, frame=2)["pixels"]
    animation.smear_frame(NAME, LAYER, 2, mode="stretch", strength=0.45, ramp=ramp_colors)
    after = inspect.get_pixels(NAME, *box, frame=2)["pixels"]
    # Only the sphere's own pixels, not its bounding box. A circle's box corners are
    # backdrop, and the trail arrives from the left and legitimately crosses the left
    # ones, so comparing the whole box fails for the one reason that is not a defect.
    own = sphere(ramp_colors, TO_X, CENTRE_Y)
    changed = [(x, y) for (x, y) in own
               if before[y - box[1]][x - box[0]] != after[y - box[1]][x - box[0]]]
    assert not changed, (
        f"the smear wrote over {len(changed)} of the subject's own pixels, starting at "
        f"{sorted(changed)[:3]}; the trail belongs behind it")

    # 4. The reading (#173). With a palette that holds the whole ramp there is nothing to
    # say, and the calls above already assert that. With one that cannot, the tool has to
    # say which copies will come out the same colour: that is the whole finding, and a
    # showcase that only ever ran the good case would not prove the warning exists.
    crushed_ramp = palette.ramp_between(*RAMP_ENDS, steps=CRUSHED_STEPS)["colors"]
    build(ramp_colors, ["#00000000", BG, *crushed_ramp])
    collided = animation.smear_frame(NAME, LAYER, 2, mode="echo", steps=3, strength=0.45,
                                     ramp=ramp_colors)
    warnings = " ".join(str(w) for w in collided.get("warnings", []))
    assert warnings, (
        "a four-entry palette cannot hold an eleven-step trail, and the tool said nothing: "
        "that is exactly the gap #173 was about")
    # The discriminator, and the whole reason this piece asserts numbers rather than
    # sentences: when the *palette* is short, fewer targets resolve exactly than were
    # declared. When only the ramp clamped, every one is exact. The prose is the same
    # either way today, which is #226.
    short = collided["trail_on_palette"]
    assert short["exact"] < short["declared"], (
        f"a crushed palette is supposed to hold fewer of the trail's colours than the "
        f"ramp declares: {short}")
    print("verified: trail between the positions, on the ramp, behind the subject, "
          "and the indexed reading fires when the palette cannot hold it")


if __name__ == "__main__":
    main()
