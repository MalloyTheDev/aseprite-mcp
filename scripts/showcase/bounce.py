"""The animation showcase: a shaded ball thrown along an arc, with a shadow that tracks it."""
import json

from aseprite_mcp.tools import (
    animation,
    cels,
    drawing,
    export,
    frames,
    layers,
    palette,
    shading,
    sprite,
)

RAMP = palette.generate_ramp("#e8643c", steps=5, hue_shift=-35.0,
                             saturation_shift=-12.0, light_range=0.72)["colors"]
FLOOR = "#2a2438"
SHADOW = "#3b3350"

NAME = "throw.aseprite"
W, H, FRAMES = 64, 40, 12
BALL, BX, BY = 12, 3, 20
GROUND = 34

sprite.create_sprite(NAME, W, H, overwrite=True)
layers.rename_layer(NAME, "Layer 1", "ball")
layers.add_layer(NAME, "shadow")
layers.add_layer(NAME, "floor")
layers.move_layer(NAME, "floor", 1)
layers.move_layer(NAME, "shadow", 2)

drawing.draw_rectangle(NAME, 0, GROUND + 1, W, 1, FLOOR, filled=True, layer="floor")
drawing.draw_ellipse_in_box(NAME, BX, GROUND - 2, BALL, 4, SHADOW, filled=True, layer="shadow")
drawing.draw_ellipse_in_box(NAME, BX, BY, BALL, BALL, RAMP[2], filled=True, layer="ball")
shading.shade_region_by_light(NAME, RAMP, light_angle=125, light_z=0.55,
                              ambient=0.32, rim=0.2, layer="ball")
shading.outline_smart(NAME, RAMP, darken_steps=2, light_angle=125, layer="ball")

for _ in range(FRAMES - 1):
    frames.add_frame(NAME)
for f in range(2, FRAMES + 1):
    for layer in ("ball", "shadow", "floor"):
        cels.copy_cel(NAME, layer, 1, f)

span = list(range(1, FRAMES + 1))
moved = animation.offset_cels(NAME, "ball", span, dx=46, arc_height=20)
animation.offset_cels(NAME, "shadow", span, dx=46)
timed = animation.apply_timing_curve(NAME, curve="hold_extremes", base_ms=70)

report = animation.validate_loop(NAME, layer="ball", loops=False)
print("arc deltas:", [(d["dx"], d["dy"]) for d in moved["deltas"]])
print("max_error_px:", moved["max_error_px"])
print("durations:", timed["durations_ms"])
print(json.dumps({
    "passed": report["validation"]["passed"],
    "spacing": [s["distance"] for s in report["animation"]["spacing"]],
    "contact_rows": report["animation"]["contact_rows"],
}, indent=None))

export.export_gif(NAME, "throw.gif", scale=6, overwrite=True)
export.export_png(NAME, "throw_frame.png", frame=4, scale=6, overwrite=True)
print("wrote throw.gif")
