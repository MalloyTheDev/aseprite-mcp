# Showcase generators

Every image in the README's showcase is produced by one of these scripts, through the
server's own tools. They are here so the art can be regenerated rather than inherited:
when a drawing or shading tool changes, the pictures that advertise it should change with
it, and a script is the only way to know they still match.

Each script writes into the MCP workspace, so point that at a scratch directory and copy
the results into `docs/assets/showcase/`:

```bash
export ASEPRITE_MCP_WORKSPACE=/tmp/showcase
uv run --no-sync python scripts/showcase/orb.py        # shading_stages.png
uv run --no-sync python scripts/showcase/bounce.py     # throw.gif
uv run --no-sync python scripts/showcase/items.py      # item_sheet.png
uv run --no-sync python scripts/showcase/walk.py       # walk8_sheet.png, walk8.gif
uv run --no-sync python scripts/showcase/tiles.py      # tilemap_scene.png
uv run --no-sync python scripts/showcase/skeleton.py   # skeleton.png
```

They need a real Aseprite, like the `--run-aseprite` tests do. `orb.py` also composes its
three stages into one strip with Pillow; the rest export directly.

The art is deliberately built the way the documentation claims: shapes from the geometry
tools, form from `shade_region_by_light`, edges from `outline_smart` or `add_outline`, and
`draw_pixels` only where a part is too thin for a form to be described, which the shading
tool refuses to invent.
