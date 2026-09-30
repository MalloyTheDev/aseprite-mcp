"""Build the shading showcase: one flat disc taken through the shading tools."""
import pathlib

from PIL import Image

from aseprite_mcp.tools import drawing, effects, export, palette, shading, sprite

RAMP = palette.generate_ramp("#5a7fd4", steps=5, hue_shift=-40.0,
                             saturation_shift=-18.0, light_range=0.74)["colors"]
print("ramp:", RAMP)

SIZE, BOX, OFF = 32, 24, 4


def disc(name: str) -> str:
    sprite.create_sprite(name, SIZE, SIZE, overwrite=True)
    drawing.draw_ellipse_in_box(name, OFF, OFF, BOX, BOX, RAMP[2], filled=True)
    return name


flat = disc("orb_1_flat.aseprite")

lit = disc("orb_2_lit.aseprite")
shading.shade_region_by_light(lit, RAMP, light_angle=125, light_z=0.55, bulge=1.0,
                              ambient=0.30, rim=0.25)

full = disc("orb_3_full.aseprite")
shading.shade_region_by_light(full, RAMP, light_angle=125, light_z=0.55, bulge=1.0,
                              ambient=0.30, rim=0.25)
shading.dither_band(full, RAMP, from_step=1, to_step=2, pattern="bayer4", width=2)
# Strays first, outline second. The dithered band survives: its pixels have
# diagonal neighbours of their own colour, which is what makes it a pattern.
effects.remove_stray_pixels(full)
shading.outline_smart(full, RAMP, mode="colormatched", darken_steps=2, light_angle=125)

stages = []
for name in (flat, lit, full):
    out = export.export_png(name, name.replace(".aseprite", ".png"), scale=8, overwrite=True)
    stages.append(pathlib.Path(out["output"]))

# The three stages side by side, which is how the README shows the progression. Pillow is
# already a dependency (render_preview uses it), so composing here keeps the whole picture
# reproducible from one script.
GAP = 28
images = [Image.open(path).convert("RGBA") for path in stages]
width = sum(image.width for image in images) + GAP * (len(images) - 1)
strip = Image.new("RGBA", (width, max(image.height for image in images)), (0, 0, 0, 0))
offset = 0
for image in images:
    strip.paste(image, (offset, 0), image)
    offset += image.width + GAP
strip.save(stages[0].with_name("shading_stages.png"))
print("wrote shading_stages.png")
