"""A palette entry above 31, kept rather than silently erased.

Every drawing tool begins by asking `get_draw_image` for an editable copy of the target
cel. That helper used to compose the copy with `Image:drawImage` at its default blend
mode, and blending an INDEXED image means converting each pixel to RGBA through a palette
and mapping the result back with a best-fit search. The palette that round trip used holds
32 entries, so every pixel drawn in index 32 or above came back as the mask index.

The consequence was data loss with no error, no warning and no count: the pixels were gone
before the tool that was called had written anything, so its own `pixels_written` was
correct and the picture was wrong. It cost a committed showcase animation 421 pixels per
frame, the warm glow on a cavern's rock and the whole of a lava waterline, which existed on
frame 1 and were a hole on the other 23. That piece asserted that its rock never changed
and passed, because the window it sampled did not reach the pixels being destroyed.

These tests are the boundary, measured: 31 survived and 32 did not, which is what named the
cause. They are editor-tier because the fault was in Lua and only an editor can show it.
"""
from __future__ import annotations

import pytest

from aseprite_mcp.tools import drawing, inspect, palette, sprite

# 35 entries: index 0 the mask, then 34 distinct colours. Distinct matters, because the
# read side returns colours rather than indices and duplicates would hide a mix-up.
PALETTE = ["#00000000"] + [
    f"#{(i * 7) % 256:02x}{(i * 13) % 256:02x}{(i * 29) % 256:02x}" for i in range(1, 35)
]


@pytest.fixture
def indexed(request):
    name = f"hi_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, 8, 8, color_mode="indexed", overwrite=True)
    palette.set_palette(name, PALETTE)
    assert len(palette.get_palette(name)["colors"]) == 35
    return name


@pytest.mark.parametrize("index", [1, 16, 30, 31, 32, 33, 34])
def test_a_high_palette_entry_survives_a_later_write_to_the_same_layer(indexed, index):
    """The regression, parameterised across the boundary that was found.

    The second write is the one that matters: it is unrelated, lands somewhere else, and
    used to destroy the first simply by asking for an editable copy of the cel.
    """
    drawing.draw_pixels(indexed, [{"x": 1, "y": 1}], f"index:{index}")
    first = inspect.get_pixels(indexed, 1, 1, 1, 1)["pixels"][0][0]
    assert first.lower() == PALETTE[index].lower() + "ff"[: 9 - len(PALETTE[index])] or \
        first[:7].lower() == PALETTE[index][:7].lower(), (first, PALETTE[index])

    drawing.draw_pixels(indexed, [{"x": 5, "y": 5}], "index:1")
    after = inspect.get_pixels(indexed, 1, 1, 1, 1)["pixels"][0][0]
    assert after == first, (
        f"index {index} was {first} and is now {after} after an unrelated write "
        "elsewhere on the same layer. A drawing tool is erasing pixels it was not asked "
        "to touch.")


def test_every_entry_of_a_large_palette_survives_one_pass(indexed):
    """All of them at once, which is what a real indexed sprite looks like: the lava
    cavern this was found in uses 35 entries, 24 of them a cycled run."""
    cells = [{"x": i % 8, "y": i // 8, "color": f"index:{i + 1}"} for i in range(34)]
    drawing.draw_pixels(indexed, cells)
    before = inspect.get_pixels(indexed, 0, 0, 8, 8)["pixels"]
    kept = {px[:7].lower() for row in before for px in row if px[7:9] != "00"}
    assert len(kept) == 34, f"only {len(kept)} of 34 entries were written at all"

    # One more unrelated write, the trigger.
    drawing.draw_pixels(indexed, [{"x": 7, "y": 7}], "index:1")
    after = inspect.get_pixels(indexed, 0, 0, 8, 8)["pixels"]
    for y in range(8):
        for x in range(8):
            if (x, y) == (7, 7):
                continue
            assert after[y][x] == before[y][x], (
                f"({x},{y}) was {before[y][x]} and is now {after[y][x]}: a write at (7,7) "
                "changed a pixel it was not given")


@pytest.mark.pure
def test_the_fix_is_in_the_shared_helper_not_in_one_tool():
    """Pinned so the blend mode cannot drift back.

    `BlendMode.NORMAL` on an indexed image is the bug. Reading the source is the only way
    to hold this, because the symptom needs a palette larger than 32 entries to appear at
    all and a future change could reintroduce it anywhere.
    """
    import pathlib

    from aseprite_mcp.core import luagen

    source = pathlib.Path(luagen.__file__).read_text(encoding="utf-8")
    start = source.index("local function get_draw_image")
    body = source[start:start + 1600]
    assert "BlendMode.SRC" in body, (
        "get_draw_image no longer copies with BlendMode.SRC. At the default blend mode it "
        "round-trips an indexed cel through a 32-entry palette and silently erases every "
        "pixel in index 32 or above.")
