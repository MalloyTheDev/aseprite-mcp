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

If a run stops matching, a tool's output has changed. Find out which tool and why before
recommitting, because the alternative is a showcase that quietly drifts away from what the
tools actually do.

They need a real Aseprite, like the `--run-aseprite` tests do. `orb.py` also composes its
three stages into one strip with Pillow; the rest export directly.

The art is deliberately built the way the documentation claims: shapes from the geometry
tools, form from `shade_region_by_light`, edges from `outline_smart` or `add_outline`, and
`draw_pixels` only where a part is too thin for a form to be described, which the shading
tool refuses to invent.

`zorder.py` and `quantize.py` are shaped a little differently from the rest: each one
**asserts the thing its picture claims**, rather than leaving a reader to take the image on
trust. `zorder.py` reads the composited pixel where the blade crosses the shield and fails
if the two middle frames do not disagree about which ramp owns it, because a z-index that
round-trips through the file while changing nothing about the render would produce an
identical-looking strip. `quantize.py` prints the colour count at each stage, so the
banding in the picture is backed by 117 colours becoming 13 and then 5.

Both went through a draft that demonstrated the mechanic and looked like a test fixture:
two featureless ellipses crossing, and three plain discs. They are drawn properly now, a
sword passing a round shield and a dusk scene behind two ridgelines, because a showcase
that does not look like the work the tool is for is not showing the tool off. The sword
and shield are built the way `items.py` builds its items, which is the standard the rest
of these pictures set.

`quantize.py` also documents a trap worth knowing: `quantize_palette` derives a palette and
does not touch a pixel. Its own warning says so, and the first version of that script
produced three identical discs because of it. Reducing the art is the conversion that
follows, `set_color_mode(..., palette_source="keep")`, so the picture needs both halves of
the pipeline.
