"""import_spritesheet (#93): a sheet image becomes a sprite with one frame per cell.

Most of this needs a real Aseprite (--run-aseprite). The refusals are marked `pure`: they
happen in Python, from the sheet's header, before anything is launched, and a test that
launched Aseprite to learn that a size does not divide would be testing the wrong half.
"""

from __future__ import annotations

import pytest
from PIL import Image

from aseprite_mcp.core.errors import ValidationFailed, WorkspaceError
from aseprite_mcp.core.limits import MAX_SHEET_FRAMES
from aseprite_mcp.core.runner import AsepriteError, run_lua
from aseprite_mcp.tools import image, inspect, sprite
from aseprite_mcp.tools.common import lua_path, resolve_path

RED, BLUE, GREEN = (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255)
YELLOW, MAGENTA = (255, 255, 0, 255), (255, 0, 255, 255)
HEX = {RED: "#ff0000", BLUE: "#0000ff", GREEN: "#00ff00", YELLOW: "#ffff00",
       MAGENTA: "#ff00ff"}


def _sheet(name: str, columns: int, rows: int, cells: list, cell: int = 8) -> str:
    """A sheet of solid cells in row order, written into the workspace. None leaves a
    cell clear."""
    img = Image.new("RGBA", (columns * cell, rows * cell), (0, 0, 0, 0))
    for i, colour in enumerate(cells):
        if colour is not None:
            x, y = (i % columns) * cell, (i // columns) * cell
            img.paste(colour, (x, y, x + cell, y + cell))
    path = resolve_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return name


def _frame_colours(name: str) -> list[str]:
    count = inspect.get_sprite_info(name)["frameCount"]
    return [inspect.get_pixels(name, 1, 1, 1, 1, frame=f)["pixels"][0][0][:7]
            for f in range(1, count + 1)]


@pytest.fixture
def no_launch(monkeypatch):
    """Fail the test if the call reaches Aseprite."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for a call that is refused before it")
    monkeypatch.setattr(image, "run_lua", refuse)


# --- refused before launch ---------------------------------------------------------


@pytest.mark.pure
def test_a_cell_width_that_does_not_divide_the_sheet_is_refused(no_launch):
    src = _sheet("ss/pure_w.png", 4, 1, [RED] * 4)
    with pytest.raises(ValidationFailed,
                       match="frame_width 7 does not divide the sheet's width of 32"):
        image.import_spritesheet("ss/pure_w.aseprite", src, 7, 8)


@pytest.mark.pure
@pytest.mark.parametrize("layout, width, height, says", [
    ("horizontal", 8, 4, "frame_height must be the sheet's height, 8"),
    ("vertical", 8, 8, "frame_width must be the sheet's width, 32"),
])
def test_a_strip_layout_must_span_the_other_axis(no_launch, layout, width, height, says):
    src = _sheet("ss/pure_axis.png", 4, 1, [RED] * 4)
    with pytest.raises(ValidationFailed, match=says):
        image.import_spritesheet("ss/pure_axis.aseprite", src, width, height, layout=layout)


@pytest.mark.pure
def test_an_unknown_layout_is_refused(no_launch):
    src = _sheet("ss/pure_layout.png", 4, 1, [RED] * 4)
    with pytest.raises(ValidationFailed, match="layout must be one of"):
        image.import_spritesheet("ss/pure_layout.aseprite", src, 8, 8, layout="diagonal")


@pytest.mark.pure
def test_more_cells_than_the_cap_is_refused(no_launch):
    """1x1 cells on a 65x64 sheet are 4,160 frames: a cell-size mistake, named as one."""
    src = _sheet("ss/pure_cap.png", 65, 64, [], cell=1)
    with pytest.raises(ValidationFailed, match=f"4160 frames; maximum is {MAX_SHEET_FRAMES}"):
        image.import_spritesheet("ss/pure_cap.aseprite", src, 1, 1, layout="grid")


@pytest.mark.pure
def test_a_missing_sheet_is_refused(no_launch):
    with pytest.raises(ValidationFailed, match="does not exist"):
        image.import_spritesheet("ss/pure_missing.aseprite", "ss/nowhere.png", 8, 8)


@pytest.mark.pure
def test_an_existing_sprite_is_not_replaced_without_overwrite(no_launch):
    src = _sheet("ss/pure_clobber.png", 4, 1, [RED] * 4)
    resolve_path("ss/pure_clobber.aseprite").write_bytes(b"not replaced")
    with pytest.raises(WorkspaceError, match="already exists"):
        image.import_spritesheet("ss/pure_clobber.aseprite", src, 8, 8)
    assert resolve_path("ss/pure_clobber.aseprite").read_bytes() == b"not replaced"


# --- against Aseprite --------------------------------------------------------------


@pytest.mark.parametrize("layout, columns, rows", [("horizontal", 4, 1), ("vertical", 1, 4)])
def test_a_strip_becomes_one_frame_per_cell_in_order(layout, columns, rows):
    cells = [RED, BLUE, GREEN, YELLOW]
    src = _sheet(f"ss/{layout}.png", columns, rows, cells)
    result = image.import_spritesheet(f"ss/{layout}.aseprite", src, 8, 8, layout=layout,
                                      overwrite=True)

    assert (result["frameCount"], result["width"], result["height"]) == (4, 8, 8)
    assert _frame_colours(f"ss/{layout}.aseprite") == [HEX[c] for c in cells]
    assert result["empty_frames"] == []


def test_a_grid_reads_in_rows_and_names_its_spare_cells():
    """A 3x2 grid holding five drawings: row order, and the sixth cell is still a frame,
    which the result says is empty rather than leaving it to be found."""
    cells = [RED, BLUE, GREEN, YELLOW, MAGENTA, None]
    src = _sheet("ss/grid.png", 3, 2, cells)
    result = image.import_spritesheet("ss/grid.aseprite", src, 8, 8, layout="grid",
                                      overwrite=True)

    assert result["frameCount"] == 6
    assert _frame_colours("ss/grid.aseprite")[:5] == [HEX[c] for c in cells[:5]]
    assert result["empty_frames"] == [6]


def test_an_opaque_indexed_sheet_keeps_the_colour_at_its_transparent_index():
    """Measured while building this: Aseprite's importer renders the cells onto a new,
    transparent layer, where the transparent palette index means "no pixel", so on an
    opaque indexed sheet whatever was drawn in that entry vanished: a whole frame here.

    Read as raw indices, because the colour readers decode that index as transparent on a
    Background layer too, which is a separate defect; asserting through them would hide
    exactly what this checks."""
    pal = [255, 255, 0, 0, 255, 0, 255, 0, 0, 0, 0, 255]  # yellow at 0, the transparent index
    img = Image.new("P", (32, 8))
    img.putpalette(pal + [0] * (768 - len(pal)))
    for i, index in enumerate([2, 3, 1, 0]):
        img.paste(index, (i * 8, 0, i * 8 + 8, 8))
    img.save(resolve_path("ss/indexed.png"))

    result = image.import_spritesheet("ss/indexed.aseprite", "ss/indexed.png", 8, 8,
                                      overwrite=True)
    raw = run_lua("""
    local spr = app.open(ARG.src)
    local layer = spr.layers[1]
    local out = {}
    for f = 1, #spr.frames do
      local cel = layer:cel(f)
      out[f] = cel.image:getPixel(1 - cel.position.x, 1 - cel.position.y)
    end
    RESULT = { indices = out, background = layer.isBackground,
               transparent = spr.transparentColor }
    """, {"src": lua_path(resolve_path("ss/indexed.aseprite"))})

    assert result["colorMode"] == "indexed"
    assert raw == {"indices": [2, 3, 1, 0], "background": True, "transparent": 0}


def test_a_sheet_with_frames_of_its_own_is_refused():
    """A GIF is already an animation; slicing its first frame would quietly drop the rest."""
    path = resolve_path("ss/anim.gif")
    Image.new("RGBA", (16, 8), RED).save(
        path, save_all=True, append_images=[Image.new("RGBA", (16, 8), BLUE)])
    with pytest.raises(AsepriteError, match="the sheet has 2 frames"):
        image.import_spritesheet("ss/anim.aseprite", "ss/anim.gif", 8, 8, overwrite=True)


def test_a_sheet_pillow_cannot_read_is_still_checked_inside_aseprite():
    """.aseprite sheets have no header Pillow understands, so the pre-flight cannot see
    their size. The same refusal has to happen once the sheet is open."""
    sprite.create_sprite("ss/sheet.aseprite", 30, 8, overwrite=True)
    with pytest.raises(AsepriteError, match="do not divide this 30x8 sheet"):
        image.import_spritesheet("ss/from_ase.aseprite", "ss/sheet.aseprite", 8, 8,
                                 overwrite=True)


def test_overwrite_replaces_the_sprite():
    src = _sheet("ss/twice.png", 2, 1, [RED, BLUE])
    image.import_spritesheet("ss/twice.aseprite", src, 8, 8, overwrite=True)
    src = _sheet("ss/twice.png", 3, 1, [GREEN, GREEN, GREEN])
    result = image.import_spritesheet("ss/twice.aseprite", src, 8, 8, overwrite=True)

    assert result["frameCount"] == 3
    assert _frame_colours("ss/twice.aseprite") == ["#00ff00"] * 3
