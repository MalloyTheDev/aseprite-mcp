"""Build the quantization showcase: a smooth-rendered scene reduced to a pixel palette.

This is the step between a picture and pixel art, and the one the server could not take
before `quantize_palette`: `extract_palette` reports the colours an image already uses and
`set_color_mode` maps art onto a palette that exists, but nothing derived a small palette
*from* the artwork.

So the input has to look rendered rather than drawn. The scene is built from smooth
gradients with dithering off, which is how you get hundreds of colours out of these tools,
and then reduced twice. The banding in the second and third panels is the palette doing
its work, not a filter applied over the top.

It is two calls per stage on purpose, and the first touches no pixels: quantizing derives
the palette and says so in its own warning, and the conversion that follows is what
reduces the art. The first draft of this script had only the first half and produced three
identical panels.
"""
import pathlib

from PIL import Image

from aseprite_mcp.tools import drawing, effects, export, inspect, layers, palette, sprite

W, H = 72, 54
BUDGETS = [14, 6]

SKY = ["#171a3a", "#5e3a7e", "#c05a6e", "#f0a060"]   # night to dusk, top to bottom
SUN = ["#fff3c4", "#ffb03a"]
HILL_FAR = ["#4a3a6a", "#2a2244"]
HILL_NEAR = ["#2a2038", "#140f20"]


def in_ellipse(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def scene(name: str) -> str:
    """A dusk scene in smooth gradients: sky, sun, two ridgelines.

    Each element is its own layer, because `fill_gradient` respects alpha and so paints
    only where that layer already has pixels. On one layer the sky would be repainted by
    every gradient after it.
    """
    sprite.create_sprite(name, W, H, overwrite=True)
    layers.rename_layer(name, "Layer 1", "sky")
    drawing.fill_layer(name, SKY[0], layer="sky")
    effects.fill_gradient(name, SKY, gradient_type="linear", angle=90.0, dither=False,
                          layer="sky")

    layers.add_layer(name, "sun")
    sun = {(x, y) for y in range(H) for x in range(W)
           if in_ellipse(x, y, 46, 26, 7.5, 7.5)}
    drawing.draw_pixels(name, [{"x": x, "y": y} for x, y in sorted(sun)], SUN[0],
                        layer="sun")
    effects.fill_gradient(name, SUN, gradient_type="radial", dither=False, layer="sun")

    layers.add_layer(name, "far")
    far = {(x, y) for y in range(H) for x in range(W)
           if in_ellipse(x, y, 24, 50, 30.0, 16.0) or in_ellipse(x, y, 58, 52, 22.0, 12.0)}
    drawing.draw_pixels(name, [{"x": x, "y": y} for x, y in sorted(far)], HILL_FAR[0],
                        layer="far")
    effects.fill_gradient(name, HILL_FAR, gradient_type="linear", angle=90.0,
                          dither=False, layer="far")

    layers.add_layer(name, "near")
    near = {(x, y) for y in range(H) for x in range(W)
            if in_ellipse(x, y, 14, 58, 26.0, 14.0) or in_ellipse(x, y, 52, 60, 28.0, 15.0)}
    drawing.draw_pixels(name, [{"x": x, "y": y} for x, y in sorted(near)], HILL_NEAR[0],
                        layer="near")
    effects.fill_gradient(name, HILL_NEAR, gradient_type="linear", angle=90.0,
                          dither=False, layer="near")

    sprite.flatten_sprite(name)
    return name


def colours(name: str) -> int:
    return inspect.assess_sprite(name)["metrics"]["colors"]


stages = []

smooth = scene("quant_1_smooth.aseprite")
print(f"  smooth render          {colours(smooth):>4} colours on the canvas")
stages.append(smooth)

for budget in BUDGETS:
    name = scene(f"quant_{len(stages) + 1}_{budget}.aseprite")
    derived = palette.quantize_palette(name, max_colors=budget)
    print(f"  max_colors={budget:<12} palette holds {derived['size']}, "
          f"art has {derived['art_colors']}, "
          f"{derived['art_colors_exact']} of them exactly")
    for note in derived.get("warnings", []):
        print(f"      warning: {note[:150]}")
    converted = sprite.set_color_mode(name, "indexed", palette_source="keep")
    print(f"  converted to indexed   {converted['drawn_pixels']} drawn pixels, "
          f"verified={converted['verified']}, now {colours(name)} colours")
    stages.append(name)

print()
images = []
for name in stages:
    out = export.export_png(name, name.replace(".aseprite", ".png"), scale=4,
                            overwrite=True)
    images.append(Image.open(pathlib.Path(out["output"])).convert("RGBA"))

gap = 14
strip = Image.new(
    "RGBA",
    (sum(i.width for i in images) + gap * (len(images) - 1), max(i.height for i in images)),
    (0, 0, 0, 0),
)
offset = 0
for image in images:
    strip.paste(image, (offset, 0), image)
    offset += image.width + gap
target = pathlib.Path(
    export.export_png(stages[0], "quant_probe.png", scale=1, overwrite=True)["output"]
).parent / "quantize_stages.png"
strip.save(target)
print("strip:", target)
