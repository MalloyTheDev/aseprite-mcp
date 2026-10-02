# Showcase generators

Almost every image the README shows is produced by one of these scripts, through the
server's own tools. They are here so the art can be regenerated rather than inherited:
when a drawing or shading tool changes, the pictures that advertise it should change with
it, and a script is the only way to know they still match. The two exceptions are
`assets/slime.gif` and `assets/ramp.png`, under *More examples*, which predate the
generators and have none here.

Each script writes into the MCP workspace, so point that at a scratch directory and copy
the results out. The scripts write the names on the left; the repository commits them
under the names on the right:

```bash
export ASEPRITE_MCP_WORKSPACE=/tmp/showcase
uv run --no-sync python scripts/showcase/orb.py        # shading_stages.png -> docs/assets/showcase/
uv run --no-sync python scripts/showcase/bounce.py     # throw.gif          -> docs/assets/showcase/
uv run --no-sync python scripts/showcase/items.py      # items.png          -> docs/assets/showcase/item_sheet.png
uv run --no-sync python scripts/showcase/walk.py       # walk8_sheet.png, walk8.gif -> docs/assets/showcase/
uv run --no-sync python scripts/showcase/tiles.py      # scene.png          -> assets/tilemap_scene.png
uv run --no-sync python scripts/showcase/skeleton.py   # skeleton.png       -> assets/skeleton.png
uv run --no-sync python scripts/showcase/zorder.py     # zorder.gif, zorder_pair.png -> docs/assets/showcase/
uv run --no-sync python scripts/showcase/quantize.py   # quantize_stages.png -> docs/assets/showcase/
uv run --no-sync python scripts/showcase/dungeon.py    # dungeon.png, dungeon.gif  -> docs/assets/showcase/
```

Note that two of them are renamed on the way in, and that `tiles.py` and `skeleton.py`
land in `assets/` at the repository root rather than in `docs/assets/showcase/`. `orb.py`
also leaves its three stage PNGs behind (`orb_1_flat.png`, `orb_2_lit.png`,
`orb_3_full.png`); the committed `docs/assets/showcase/orb.png` is `orb_3_full.png`, and
nothing currently links to it.

**They reproduce the committed images byte for byte**, and the one time that stopped being
true it earned its keep. Running all of them into an empty workspace against Aseprite
1.3.18.6 and comparing SHA-256: seven of the eight original files matched, and
`item_sheet.png` did not.

Three source pixels had changed, two in the heart and one in the potion, from a cool grey
to their own item's ramp colour. The cause was the fix for #177: `remove_stray_pixels`
used to let a stray take a colour from a neighbour that was itself a stray, so a pair with
no settled neighbour traded colours instead of being cleaned. `items.py` calls that tool,
so three of its pixels moved. The image was recommitted and the reason recorded here,
which is exactly the procedure below.

(That heart, coin, potion and sword have since been replaced. `items.py` now draws a
longsword, a kite shield, a great helm, a bronze key and a spell scroll, for the reason
given under *What these scripts assert* below.)

If a run stops matching, a tool's output has changed. Find out which tool and why before
recommitting, because the alternative is a showcase that quietly drifts away from what the
tools actually do.

They need a real Aseprite, like the `--run-aseprite` tests do. `orb.py`, `zorder.py` and
`quantize.py` compose their panels into one strip with Pillow; the rest export directly.
`dungeon.py` is the slowest by a distance, because its light falloff is one
`shift_along_ramp` call per run of masonry and each call is its own Aseprite launch.

## What these scripts assert

`zorder.py`, `quantize.py`, `items.py` and `dungeon.py` are shaped differently from the
rest: each one **asserts the thing its picture claims**, rather than leaving a reader to
take the image on trust. Every one of those assertions exists because the thing it checks
went wrong first.

- `zorder.py` reads the composited pixel where the blade crosses the shield and fails if
  the two middle frames do not disagree about which ramp owns it. A z-index that
  round-trips through the file while changing nothing about the render would produce an
  identical-looking strip.
- `quantize.py` prints the colour count at each stage, so the banding in the picture is
  backed by 117 colours becoming 13 and then 5. Its first draft produced three identical
  panels, because `quantize_palette` derives a palette and does not touch a pixel.
- `items.py` counts the colours in each cell and fails if any of them came from another
  item's material. `base_color` scopes a shading pass by colour *distance*, and at the
  default tolerance of 24 every step of a gold ramp is within reach of a step of a brass
  one, so the pass meant for one cell reshaded art in another. Nothing looked wrong. Three
  rounds went into redrawing the wrong thing before the colours were counted, which is
  now [issue #183](https://github.com/MalloyTheDev/aseprite-mcp/issues/183).
- `items.py` also asserts **where each glint landed**, because the colour census did not.
  It proved no colour crossed a cell and said nothing about whether the glint inside that
  cell was on the right object, and two of the four were not: the sword's was on its
  leather grip and the key's was on the shadow side of its bow. Each glint is now scoped to
  a rectangle holding one part, and the script checks its pixels are inside that part's own
  point set ([#187](https://github.com/MalloyTheDev/aseprite-mcp/issues/187)).
- `dungeon.py` asserts the chest's lid seam is at least 18 of its 27 pixels, and that
  `contact_shadow` darkened something. The seam was 10 pixels in four dashes, because the
  straps and the lock were drawn over it, and the contact shadow was a no-op because the
  occluder colour it was given no longer existed by the time it ran
  ([#194](https://github.com/MalloyTheDev/aseprite-mcp/issues/194)).
- `dungeon.py` probes two points on the same flagstone course and fails if the far one is
  not darker, and it checks that all four flame frames have different silhouettes. At one
  ramp step a zone the first of those still passed while the room still looked evenly
  lit, which is a measurement satisfied by something no reader can see; the falloff is two
  steps a zone now. That probe is also the clearest example here of an assertion covering
  only the failure it was written for: it passes, and the far wall is still a repeating
  tile, because nothing measures the *variety* of the blocks
  ([#193](https://github.com/MalloyTheDev/aseprite-mcp/issues/193)).

## What these scripts are drawn like

Every one of them went through a draft that demonstrated a mechanic and looked like a test
fixture: two featureless ellipses crossing, three plain discs, a heart that came out lumpy
because it was derived from a curve rather than written out row by row. They are drawn
properly now, because a showcase that does not look like the work the tool is for is not
showing the tool off.

The standard the rest follow is `items.py`: silhouettes typed out one row at a time, form
from `shade_region_by_light` per part, thin parts lit by hand because the shading tool
refuses to invent a form it cannot see, and one dark outline over everything. Where a shape
genuinely is derived, the script says why. `dungeon.py` computes its flame from a profile
and a lean, on the grounds that a heart has a notch a formula gets wrong and a flame has no
feature at all a reader could catch being a pixel off.

## Issues these scripts turned up

Drawing with the tools is the best test the tools get, and reviewing the drawing at 12x is
the best test the drawing gets. Sixteen issues came out of this round, ten of them from
zooming in on art that looked finished at thumbnail size.

Against the tools, with the failing call and the measurement in each:
[#181](https://github.com/MalloyTheDev/aseprite-mcp/issues/181) (a fully masked write
reports no counts), [#182](https://github.com/MalloyTheDev/aseprite-mcp/issues/182) (the
`.msk` sidecar outlives its sprite),
[#183](https://github.com/MalloyTheDev/aseprite-mcp/issues/183) (`base_color` tolerance
merges two materials), [#184](https://github.com/MalloyTheDev/aseprite-mcp/issues/184)
(`generate_ramp` clips silently),
[#185](https://github.com/MalloyTheDev/aseprite-mcp/issues/185) (`glow` needs one layer per
frame), [#186](https://github.com/MalloyTheDev/aseprite-mcp/issues/186) (`dither_band`
counts from 1 beside a list that counts from 0).

Against the art in this directory:
[#187](https://github.com/MalloyTheDev/aseprite-mcp/issues/187) and
[#188](https://github.com/MalloyTheDev/aseprite-mcp/issues/188) and
[#194](https://github.com/MalloyTheDev/aseprite-mcp/issues/194) are fixed, along with the
helm's half of [#189](https://github.com/MalloyTheDev/aseprite-mcp/issues/189). Still open:
[#189](https://github.com/MalloyTheDev/aseprite-mcp/issues/189) (the shield's blown-out top
and the scroll's ribbon),
[#190](https://github.com/MalloyTheDev/aseprite-mcp/issues/190) (the longsword is half
hilt), [#191](https://github.com/MalloyTheDev/aseprite-mcp/issues/191) (the scroll has no
silhouette), [#192](https://github.com/MalloyTheDev/aseprite-mcp/issues/192) (the sheet has
no shared weight or palette family),
[#193](https://github.com/MalloyTheDev/aseprite-mcp/issues/193) (the far wall repeats),
[#195](https://github.com/MalloyTheDev/aseprite-mcp/issues/195) (the torchlight is a
sticker) and [#196](https://github.com/MalloyTheDev/aseprite-mcp/issues/196) (the horizon is
a letterbox bar).

What fixed `#188` is worth keeping in mind for any thin part: `hand_lit` lights a part's
global top row and global bottom row, which is right for a slab and useless for anything
that wraps. On the shield's rim it lit two pixels and left ninety at the flat fill colour.
`edge_lit` lights by the direction each pixel's edge faces instead, taken as the vector from
the part's centre, which is near enough the surface normal on a ring, a rim or a small gem.

