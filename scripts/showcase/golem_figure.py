"""The golem's figure, drawn by hand, one character per pixel.
Three versions of this piece placed parametric masses and shaded them, and all three
failed in the same place for different reasons. The first computed a tone per part and gave
each mass three of eight ramp steps. The second handed the shading to
`shade_region_by_light`, which reads a normal out of a distance field and so rounds every
form over: it passed every measurement and read as inflated tubes. The third cut the masses
into chiselled blocks, which fixed the material and cost the gesture, because axis-aligned
rectangles stacked vertically have no pose.
What all three share is that a formula chose where the edges went. This one does not. Every
pixel below is placed, and the character placed there says which way that pixel's surface
faces, so the silhouette and the lighting are decided in the same stroke rather than one
being inferred from the other afterwards.
The vocabulary, which is `shade_facets`' legend and not a palette:
    t   an upward plane, catching the key
    b   a cut edge, tilted toward the viewer, the brightest thing on the figure
    l   a plane facing left, into the light at 130 degrees
    f   a plane facing the viewer
    r   a plane facing right, away from the light
    u   a downward plane, under an overhang, the darkest surface
    .   not part of the figure
The pose is deliberate and asymmetric, because a figure with two matching limbs is not
standing, it is extruded. The near shoulder is heavier and crests a row higher; the head is
sunk between the shoulders rather than perched on them; the near arm hangs lower and ends in
the larger fist; the hips sit a pixel right of the chest's centre so the weight is on the
near leg.
The one structural rule, learned by drawing it wrong: **the shoulders have to overlap the
chest.** A draft with the pauldrons above the torso's first row rendered as two pillars
standing beside a totem, because three masses that never touch are three objects however
well each one is lit.

Three faults measured off this file and not yet fixed, written down with their numbers so
the next pass starts from them rather than from an impression:

1. **The legs are 22.6% of the figure's height** (12 rows of 53, rows 49 to 60). A stocky
   figure wants something closer to 35%, which means they have to start at row 42: seven
   rows higher than they do, taken out of the hip and arm mass below row 42.

2. **There is no lean at all, and the pose the docstring above claims is not in the
   drawing.** The central mass sits at midpoint 30.5 on every row from 23 to 47, exactly
   constant, and the legs' combined span is 30.5 as well. The figure is one pixel left of
   the canvas centre at 31.5 from top to bottom, which is a centring error and not a pose.

   A first pass at this note reported a drift of 1.58px leftward down the body, reversing
   1.97px at the hips. That was wrong: it came from taking the mass centroid of whole
   rows, which below row 22 include both arms, and the near arm is wider and further from
   the body than the far one. Measuring the *central run* instead removes it entirely.
   The lesson is specific and worth keeping: on a figure with limbs, a whole-row centroid
   measures the limbs, so a claim about the body's axis has to come from the run that
   contains the body.

3. **The gap between the legs is 6px wide** (8px at row 49) against a 20px leg pair, so
   the legs read as two separate pillars. The comment below claims three pixels.
"""
W = 64
def row(*spans: tuple[int, str]) -> str:
    """One row of the figure from hand-placed spans, so a miscount is impossible.
    Spans are applied in order, so a mass written later sits in front of one written
    earlier, which is how the near pauldron overlaps the chest.
    """
    line = ["."] * W
    for x, chars in spans:
        for offset, ch in enumerate(chars):
            if 0 <= x + offset < W:
                line[x + offset] = ch
    return "".join(line)
# The figure, top to bottom. Read the columns and the pose is visible in the text itself.
FIGURE = [
    row(),                                                                    # 0
    row(),                                                                    # 1
    row(),                                                                    # 2
    row(),                                                                    # 3
    row(),                                                                    # 4
    row(),                                                                    # 5
    row(),                                                                    # 6
    row(),                                                                    # 7
    # The near shoulder crests first and a row higher than the far one.
    row((10, "tttttttttt")),                                                  # 8
    row((8, "tttttttttttttt"), (45, "tttttttt")),                             # 9
    row((7, "bbbbbbbbbbbbbbbb"), (43, "tttttttttttt")),                       # 10
    row((6, "llffffffffffffrr"), (42, "bbbbbbbbbbbbbb")),                     # 11
    # The head is sunk between the shoulders, so its crown sits below both crests.
    row((6, "llffffffffffffrr"), (28, "tttttttt"), (42, "llffffffffrrrr")),  # 12
    row((5, "llffffffffffffffrr"), (28, "bbbbbbbb"),
        (41, "llffffffffffrrrr")),                                            # 13
    row((5, "llffffffffffffffrr"), (28, "llffffrr"),
        (41, "llffffffffffrrrr")),                                            # 14
    row((5, "llffffffffffffffrr"), (8, "tttttttt"), (28, "llffffrr"),
        (41, "llffffffffffrrrr")),                                            # 15
    # The chest is written first and the shoulders over it, so they overlap and the three
    # masses read as one body rather than as three objects standing in a row.
    row((22, "tttttttttttttttttttt"), (5, "llffffffffffffffrr"),
        (8, "uuuuuuuu"), (28, "llffffrr"), (41, "llffffffffffrrrr")),     # 16
    row((21, "bbbbbbbbbbbbbbbbbbbbbb"), (5, "llffffffffffffffrr"),
        (28, "llffffrr"), (41, "llffffffffffrrrr")),                      # 17
    row((21, "llffffffffffffffffrrrr"), (5, "llffffffffffffffr"),
        (27, "llffffffrr"), (41, "llffffffffffrrr")),                         # 18
    row((21, "llffffffffffffffffrrrr"), (5, "llfffffffffffffr"),
        (28, "llffffrr"), (41, "llffffffffffrr")),                            # 19
    row((21, "llffffffffffffffffrrrr"), (5, "llfffffffffffuur"),
        (41, "llffffffffffrr")),                                              # 20
    row((21, "llffffffffffffffffrrrr"), (5, "llffffffffffuuuu"),
        (42, "llffffffffrrr")),                                               # 21
    row((22, "llffffffffffffffrrrr"), (5, "llfffffffffu"),
        (42, "llffffffffrr")),                                                # 22
    row((22, "llffffffffffffffrr"), (5, "llffffffffr"), (45, "llffffffrr")),  # 23
    # A raised chest plate, because a front facing figure is mostly front plane and one
    # flat tone over a third of the drawing is a fill rather than a form.
    row((22, "llffffffffffffffrr"), (27, "tttttttt"), (5, "llfffffffr"),
        (45, "llffffffr")),                                                   # 24
    # The arms clear the chest from here down: three pixels of air on each side, which is
    # the negative space the whole silhouette depends on.
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (5, "llffffffr"),
        (45, "llffffrr")),                                                    # 25
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (5, "llffffffr"),
        (45, "llffffrr")),                                                    # 26
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (5, "llffffffr"),
        (45, "llffffrr")),                                                    # 27
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (5, "llfffffrr"),
        (45, "llffffrr")),                                                    # 28
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (5, "llfffffrr"),
        (45, "llfffffr")),                                                    # 29
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (5, "llfffffrr"),
        (45, "llfffffr")),                                                    # 30
    row((22, "llffffffffffffffrr"), (26, "ll"), (35, "rr"), (6, "llffffrr"),
        (45, "llfffffr")),                                                    # 31
    row((22, "llffffffffffffffrr"), (26, "uuuuuuuuuu"), (6, "llffffrr"),
        (46, "llfffr")),                                                    # 32
    row((23, "llffffffffffffrr"), (7, "llffrr"), (45, "llfffffr")),         # 33
    # A belt course, which is how cut stone segments read where a mass changes width.
    row((23, "llffffffffffffrr"), (25, "tttttttttt"), (7, "llffrr"),
        (46, "llfffr")),                                                    # 34
    row((23, "llffffffffffffrr"), (25, "uuuuuuuuuu"), (7, "llffrr"),
        (47, "llffr")),                                                     # 35
    # The waist narrows, which is what makes the chest read as a chest.
    row((24, "llffffffffffrr"), (7, "llffrr"), (47, "llffr")),            # 36
    row((24, "llffffffffffrr"), (6, "bbbbbbbb"), (46, "llffffr")),            # 37
    row((25, "llffffffffrr"), (6, "llffffrr"), (46, "bbbbbbb")),              # 38
    row((25, "llffffffffrr"), (6, "llffffrr"), (46, "llffffr")),              # 39
    # The hips, a pixel right of the chest's centre: the weight is on the near leg.
    row((23, "tttttttttttttttt"), (6, "llffffrr"), (46, "llffffr")),          # 40
    row((22, "bbbbbbbbbbbbbbbbbb"), (6, "llffffrr"), (46, "llffffr")),        # 41
    row((22, "llffffffffffffffrr"), (6, "llffffrr"), (46, "llffffr")),        # 42
    row((22, "llffffffffffffffrr"), (5, "llffffffr"), (45, "llfffffr")),      # 43
    row((22, "llffffffffffffffrr"), (4, "tttttttttttt"), (45, "ttttttttt")),  # 44
    row((23, "llffffffffffffrr"), (3, "bbbbbbbbbbbbbb"),
        (45, "bbbbbbbbbbb")),                                                 # 45
    # Both fists, the near one lower and heavier.
    row((23, "llffffffffffffrr"), (3, "llffffffffffrr"),
        (45, "llfffffffrr")),                                                 # 46
    row((24, "uuffffffffffuu"), (3, "llffffffffffrr"),
        (45, "llfffffffrr")),                                                 # 47
    # The pelvis, which joins the legs to the body. Without this row the figure measured
    # as THREE separate objects: the body (1461px, rows 8 to 48) and each leg (93px,
    # rows 49 to 60), sharing no connection at all. That is the rule at the top of this
    # file broken in the one place it was not checked, and it is what made the legs read
    # as misplaced: they were not attached. `figure.topology` is the measurement that
    # catches it, and `figure.centerline` is not, because the detached legs sit on the
    # same axis as the torso and a centre line through them is perfectly straight.
    # The span between the legs is a downward plane, being the underside of this pelvis.
    row((22, "llfffuuuuuuuufffrr"), (3, "uuffffffffuu"), (45, "uufffffuu")),  # 48
    # The legs. The background up the middle is six pixels wide here, not the three this
    # comment claimed until it was measured; see fault 3 in the module docstring. Their
    # tops are front planes rather than the upward planes they used to be: an upward
    # plane catches the key, which is what lit them like two free-standing blocks.
    row((22, "fffff"), (35, "fffff")),
    row((21, "bbbbbbb"), (34, "bbbbbbb")),
    row((21, "llfffrr"), (34, "llfffrr")),
    row((21, "llfffrr"), (34, "llfffrr")),          # 52
    row((21, "llfffrr"), (34, "llfffrr")),            # 53
    row((21, "llfffrr"), (34, "llfffrr")),              # 54
    row((21, "llfffrr"), (34, "llfffrr")),                                 # 55
    row((21, "llfffrr"), (34, "llfffrr")),                                 # 56
    # The feet, the near one wider and thrown forward, with two pixels between them.
    row((19, "ttttttttt"), (34, "ttttttttt")),                             # 57
    row((18, "bbbbbbbbbb"), (34, "bbbbbbbbbb")),                          # 58
    row((18, "llfffffffr"), (34, "llfffffffr")),                          # 59
    row((18, "lluuuuuuur"), (34, "lluuuuuuur")),                          # 60
    row(),                                                                    # 61
    row(),                                                                    # 62
    row(),                                                                    # 63
]
# Which way each symbol's surface faces, in the convention every light in this project
# uses: 90 is up, 180 is left, 0 is right. The cut edge is tilted toward the viewer so it
# takes the key almost square, which is what a chisel mark does.
FACES = {
    "t": 90,
    "b": [130.0, 0.2],
    "l": 180,
    "f": "front",
    "r": 0,
    "u": 270,
}
def mass() -> set[tuple[int, int]]:
    """Every drawn pixel of the figure."""
    return {(x, y)
            for y, line in enumerate(FIGURE)
            for x, ch in enumerate(line) if ch != "."}
