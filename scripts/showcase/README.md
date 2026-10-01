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
```

Note that two of them are renamed on the way in, and that `tiles.py` and `skeleton.py`
land in `assets/` at the repository root rather than in `docs/assets/showcase/`. `orb.py`
also leaves its three stage PNGs behind (`orb_1_flat.png`, `orb_2_lit.png`,
`orb_3_full.png`); the committed `docs/assets/showcase/orb.png` is `orb_3_full.png`, and
nothing currently links to it.

**They reproduce the committed images byte for byte.** Verified by running all six scripts
into an empty workspace against Aseprite 1.3.18.6 and comparing SHA-256: all eight
committed files matched, the eighth being `orb.png`. If a run stops matching, a tool's
output has changed and the pictures need recommitting (and the change needs explaining),
which is the whole point of keeping the generators.

They need a real Aseprite, like the `--run-aseprite` tests do. `orb.py` also composes its
three stages into one strip with Pillow; the rest export directly.

The art is deliberately built the way the documentation claims: shapes from the geometry
tools, form from `shade_region_by_light`, edges from `outline_smart` or `add_outline`, and
`draw_pixels` only where a part is too thin for a form to be described, which the shading
tool refuses to invent.
