"""Redraw the 8-direction showcase: one creature, eight facings, on the real template."""
from aseprite_mcp.tools import drawing, effects, export, palette, shading, sprite, workflow

NAME = "walk8.aseprite"
SIZE = 32
DIRS = ["S", "SE", "E", "NE", "N", "NW", "W", "SW"]
VEC = {"N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1),
       "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1)}

BODY = palette.generate_ramp("#59c35a", steps=5, hue_shift=-34.0,
                             saturation_shift=-16.0, light_range=0.70)["colors"]
OUTLINE = "#20281f"
EYE_WHITE = "#f4f7f2"
EYE_DARK = "#20281f"


def px(points):
    return [{"x": x, "y": y} for x, y in sorted(points)]


def disc(cx, cy, rx, ry):
    return {(x, y)
            for y in range(cy - ry, cy + ry + 1)
            for x in range(cx - rx, cx + rx + 1)
            if ((x - cx) / (rx + 0.5)) ** 2 + ((y - cy) / (ry + 0.5)) ** 2 <= 1.0}


sprite.create_sprite(NAME, SIZE, SIZE, overwrite=True)
workflow.make_8_direction_walk_template(NAME, frames_per_direction=1,
                                        frame_duration_ms=180, directions=DIRS)

for index, name in enumerate(DIRS, start=1):
    dx, dy = VEC[name]
    body = disc(16, 15, 9, 8)
    feet = disc(13 + dx * 2, 24, 3, 2) | disc(19 + dx * 2, 24, 3, 2)

    drawing.clear_layer(NAME, frame=index)
    drawing.draw_pixels(NAME, px(feet), BODY[1], frame=index)
    drawing.draw_pixels(NAME, px(body), BODY[2], frame=index)
    shading.shade_region_by_light(NAME, BODY, base_color=BODY[2], light_angle=125,
                                  light_z=0.55, ambient=0.34, rim=0.2, frame=index)

    # A stalk on top, in every facing. It used to appear only when the creature faced
    # away, which made it look like something that grew out of the back of its head.
    stalk = {(16 + dx, 6), (16 + dx, 5), (16 + dx * 2, 4)}
    drawing.draw_pixels(NAME, px(stalk), BODY[1], frame=index)

    # No belly patch. On a body this size a pale shape under the eyes reads as a muzzle
    # whatever it is meant to be, and the face is what carries the facing.

    eyes = set()
    pupils = set()
    def eye(cx, facing=dx):
        """A round white with a small pupil looking where the creature is going."""
        white = disc(cx, 13, 2, 2)
        pupil = {(cx + facing, 13), (cx + facing, 14),
                 (cx + facing + 1, 13), (cx + facing + 1, 14)}
        return white, {p for p in pupil if p in white}

    if dy > 0 or (dy == 0 and dx == 0):          # looking at the viewer
        for side in (-1, 1):
            white, pupil = eye(16 + side * 4 + dx * 2)
            eyes |= white
            pupils |= pupil
    elif dy == 0:                                 # profile: one eye near the leading edge
        white, pupil = eye(16 + dx * 4)
        eyes |= white
        pupils |= pupil
    if eyes:
        drawing.draw_pixels(NAME, px(eyes), EYE_WHITE, frame=index)
        drawing.draw_pixels(NAME, px(pupils), EYE_DARK, frame=index)
        # A small mouth, two pixels below the eyes. The pale patch used to sit here and
        # read as something being eaten.
        mouth = {(16 + dx * 2 + d, 17) for d in (-1, 0, 1)} | {(16 + dx * 2, 18)}
        drawing.draw_pixels(NAME, px(mouth), EYE_DARK, frame=index)

    # Shading a small round body leaves lone pixels at the band boundaries, which read as
    # dirt at this size. assess_sprite counts them; this is what clears them.
    effects.remove_stray_pixels(NAME, frame=index, protect=[EYE_WHITE, EYE_DARK])
    effects.add_outline(NAME, OUTLINE, thickness=1, connectivity=8, where="outside",
                        frame=index)

export.export_spritesheet(NAME, "walk8_sheet.png", sheet_type="horizontal", scale=4,
                          padding=1, overwrite=True)
export.export_gif(NAME, "walk8.gif", scale=5, overwrite=True)
print("wrote walk8_sheet.png and walk8.gif")
