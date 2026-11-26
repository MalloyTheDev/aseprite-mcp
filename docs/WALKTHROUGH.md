# Walkthrough: call two tools yourself

An MCP client calls a tool by name with arguments. This page makes the same call from
Python, so you can see what the server does with it and check the result without an AI
agent in the loop. You do not need to read any code first; the code is linked where it
matters.

- [Part 1](#part-1-a-tool-that-never-opens-aseprite-ramp_between) calls `ramp_between`. It
  needs only Python. You will change one line and watch a test fail, then pass.
- [Part 2](#part-2-a-tool-that-edits-a-sprite-flip_sprite) calls `flip_sprite`, which edits
  a real sprite, so it needs Aseprite.

Set up once, from a clone of the repository (see [Contributing](../CONTRIBUTING.md#route-2-make-a-first-python-change)):

```bash
uv sync --locked
```

(If an MCP client is running the server from the same folder on Windows, use
`uv run --no-sync` in place of `uv run --locked` below. [Why](../CONTRIBUTING.md#windows-a-client-is-running-the-server-from-your-checkout).)

## Where a tool's arguments come from

There is no separate schema file. A tool is a Python function with a decorator, and the
function's signature is what the client is told. Here is `ramp_between`
([`tools/palette.py`](../src/aseprite_mcp/tools/palette.py), find `def ramp_between`):

```python
@mcp.tool()
def ramp_between(
    shadow_color: str,
    light_color: str,
    steps: int = 5,
    easing: str = "perceptual",
    filename: str | None = None,
    apply: str = "none",
) -> dict:
```

The two colours have no default, so a client must send them; the rest are optional. You
can ask the registry what a client would see:

```bash
uv run --locked python -c "
import asyncio, json
import aseprite_mcp.server
from aseprite_mcp.app import mcp
tool = {t.name: t for t in asyncio.run(mcp.list_tools())}['ramp_between']
schema = tool.input_schema
print(json.dumps({k: {x: v[x] for x in ('type', 'default') if x in v} for k, v in schema['properties'].items()}))
print('required:', schema.get('required'))
"
```

```text
{"shadow_color": {"type": "string"}, "light_color": {"type": "string"}, "steps": {"type": "integer", "default": 5}, "easing": {"type": "string", "default": "perceptual"}, "filename": {"type": "string"}, "apply": {"type": "string", "default": "none"}}
required: ['shadow_color', 'light_color']
```

The function's docstring becomes the tool's description, which is also what
[TOOLS.md](TOOLS.md) is generated from.

## Part 1: a tool that never opens Aseprite (`ramp_between`)

`ramp_between` builds a colour ramp between a shadow colour and a light colour. Call it
exactly as a client would, with the same arguments:

```bash
uv run --locked python -c "from aseprite_mcp.tools import palette; print(palette.ramp_between('#202040', '#f0e0a0', steps=5))"
```

```text
{'steps': 5, 'colors': ['#202040', '#4c4c5a', '#7f7b73', '#b6ac8a', '#f0e0a0'], 'hue_span': 168.0, 'sat_floor': 0.05, 'grey_steps': 2}
```

The two end colours come back exactly as you gave them, and three steps lie between. The
extra fields say how the ramp reads: `hue_span` is how far the hue travels, `sat_floor` the
dullest step, and `grey_steps` how many middle steps are too grey to show a hue. With
`steps=3, easing="linear"` the middle is a plain RGB blend instead:

```bash
uv run --locked python -c "from aseprite_mcp.tools import palette; print(palette.ramp_between('#202040', '#f0e0a0', steps=3, easing='linear')['colors'])"
```

```text
['#202040', '#888070', '#f0e0a0']
```

### What happened in Python

Everything above ran in this one process, and Aseprite was never started. The body of the
function ([`ramp_between`](../src/aseprite_mcp/tools/palette.py)) does this, in order:

1. `parse_color` turns each colour string into numbers, so `'#202040'` becomes
   `{'r': 32, 'g': 32, 'b': 64, 'a': 255}`. A string it cannot read is refused here.
2. `check_count` refuses a `steps` below 2 or above the palette limit:
   `ValidationFailed: steps is 1; minimum is 2.`
3. `easing` must be `"linear"` or `"perceptual"`; anything else is refused with the two
   choices named.
4. [`ramps.interpolate`](../src/aseprite_mcp/core/ramps.py) computes the colours.
   It lives in `core/`, which never imports the MCP SDK, so tests call it directly.
5. `quality.ramp_chroma` measures the result and gives `hue_span`, `sat_floor` and
   `grey_steps`.
6. `_apply_palette` is the only step that could reach Aseprite. With the default
   `apply="none"` it returns at once. With `"append"` or `"replace"` and a `filename` it
   writes the ramp into that sprite's palette, which is one editor run. With `apply` set and
   no `filename` it refuses before any launch: `filename is required when apply is not 'none'.`

### Check it with tests

The tests that pin this behaviour have no need for Aseprite either. They are in the
*pure tier*. Run the file:

```bash
uv run --locked pytest tests/test_ramp_tools.py
```

```text
ss.ssss...                                                               [100%]
4 passed, 6 skipped in 2.28s
```

Four passed. They are the four tests marked `@pytest.mark.pure`: the ends come back
exact, a single-step ramp is refused, an unknown easing is refused, and applying without a
file is refused. The six skips are tests in the same file that write a ramp into a real
sprite; they run only in the *editor tier* (Part 2 shows that command). Add `-rs` to see
the reason for each skip. One more pure test, for `grey_steps`, lives in a file that is
listed wholesale as pure:

```bash
uv run --locked pytest tests/test_ramps.py -k report_whether_their_hue
```

```text
.                                                                        [100%]
1 passed, 31 deselected in 2.16s
```

### An exercise: break it, then fix it

The rule that a ramp needs two steps is enforced in `ramp_between`. Break it and let the
test say so.

1. Open [`src/aseprite_mcp/tools/palette.py`](../src/aseprite_mcp/tools/palette.py) and find
   `ramp_between`. In its `check_count(` call, change `minimum=2` to `minimum=1`. (The file
   has several such calls; edit the one inside `ramp_between`, right after `steps = int(steps)`.)
2. Run the file again:

   ```bash
   uv run --locked pytest tests/test_ramp_tools.py
   ```

   ```text
   E       ValueError: a ramp needs at least 2 steps
   FAILED tests/test_ramp_tools.py::test_a_single_step_ramp_is_refused - ValueEr...
   1 failed, 3 passed, 6 skipped in 2.54s
   ```

   The test expected a clean `ValidationFailed` that tells the caller the minimum. Your change let
   `steps=1` through to the colour maths, which raised a bare `ValueError` instead. The
   message the caller would have seen is worse, and the test caught it.
3. Put it back and run the file once more. It is `4 passed` again:

   ```bash
   git restore src/aseprite_mcp/tools/palette.py
   uv run --locked pytest tests/test_ramp_tools.py
   ```

That is the whole contribution loop for a Python-only change: edit, run the nearest test,
read the failure, fix.

## Part 2: a tool that edits a sprite (`flip_sprite`)

`flip_sprite` ([`tools/transform.py`](../src/aseprite_mcp/tools/transform.py))
mirrors every layer and frame of a sprite. This one needs Aseprite. Check that the
server can find it:

```bash
uv run --locked python -c "from aseprite_mcp.core import config; print(config.find_aseprite())"
```

If that raises an error, set `ASEPRITE_PATH` to the full path of the executable (see
[Configuration](../README.md#configuration)). Then give the server a scratch workspace
so nothing lands in your own sprites.

```bash
export ASEPRITE_MCP_WORKSPACE=/tmp/walkthrough
```

```powershell
$env:ASEPRITE_MCP_WORKSPACE = "$env:TEMP\walkthrough"
```

### What the function does

```python
@mcp.tool()
def flip_sprite(filename: str, direction: str = "horizontal") -> dict:
    d = direction.lower()
    if d not in ("horizontal", "vertical"):
        raise ValidationFailed('direction must be "horizontal" or "vertical"')
    args = {"src": lua_path(resolve_path(filename)), "dir": d}
    body = """
    local spr = open_sprite(ARG.src)
    app.command.Flip{ target = "sprite", orientation = ARG.dir }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    """
    return run_lua(body, args)
```

Python validates `direction` first, so a bad value is refused before Aseprite starts. Then
it makes one editor run. `resolve_path` keeps the filename inside the workspace.
`run_lua` wraps the Lua body in a shared prelude (helpers such as `open_sprite`,
`save_sprite` and `sprite_info`, in [`core/luagen.py`](../src/aseprite_mcp/core/luagen.py)),
writes the script to a temporary file, and runs `aseprite -b --script <that file>`. Your
arguments reach Lua through a table called `ARG`, never by being pasted into the script.
The body sets `RESULT`, and the wrapper prints it back as one tagged line that
`runner` parses into the dictionary you get. [How that line is framed](DEVELOPMENT.md#the-result-protocol).

### Run it

Save this as `flip_demo.py` in a folder outside the repository. It creates a 4 by 2 sprite
with one red pixel at the top left, flips it, and prints what happened around the call,
including how many times Aseprite was started and the Lua that ran.

```python
"""Call flip_sprite on a 4x2 sprite and show what the server does around the call."""

import json

from aseprite_mcp.core import runner
from aseprite_mcp.tools import drawing, sprite, transform
from aseprite_mcp.tools import inspect as peek

launches = []
real = runner._run_bounded


def counting(argv, *args, **kwargs):
    launches.append(argv[1:3])
    script = open(argv[-1], encoding="utf-8").read()
    proc = real(argv, *args, **kwargs)
    if "ARG.dir" in script:  # only describe the flip run
        body = script[script.index("local function _main()"):script.index("local _ok, _err")]
        print("--- generated Lua body ---")
        print(body.strip())
        sentinel = next(l for l in proc.stdout.split("\n") if l.startswith("@@ASEMCP"))
        print("--- first 60 characters of the line Aseprite printed ---")
        print(sentinel[:60])
    return proc


runner._run_bounded = counting

sprite.create_sprite("walkthrough/flip.aseprite", 4, 2, overwrite=True)
drawing.draw_pixels("walkthrough/flip.aseprite", [{"x": 0, "y": 0}], color="#ff0000")
print("before:", json.dumps(peek.get_pixels("walkthrough/flip.aseprite", 0, 0, 4, 2)["pixels"]))

launched_before = len(launches)
result = transform.flip_sprite("walkthrough/flip.aseprite", "horizontal")
print("launches for the flip:", len(launches) - launched_before)
print("result keys:", sorted(result))
print("ok:", result["ok"], "width:", result["width"], "height:", result["height"])
print("after: ", json.dumps(peek.get_pixels("walkthrough/flip.aseprite", 0, 0, 4, 2)["pixels"]))

launched_before = len(launches)
try:
    transform.flip_sprite("walkthrough/flip.aseprite", "sideways")
except Exception as error:
    print(type(error).__name__ + ":", error)
    print("launches for the refused call:", len(launches) - launched_before)
```

Run it from the repository folder, giving the path to the file you saved:

```bash
uv run --locked python /path/to/flip_demo.py
```

This is what it printed here (Aseprite 1.3.18.6). Your 16 hex digits will differ, because
they are new for every run, and the keys of the JSON object come in a different order each
time:

```text
before: [["#ff0000ff", "#00000000", "#00000000", "#00000000"], ["#00000000", "#00000000", "#00000000", "#00000000"]]
--- generated Lua body ---
local function _main()

    local spr = open_sprite(ARG.src)
    app.command.Flip{ target = "sprite", orientation = ARG.dir }
    save_sprite(spr)
    RESULT = sprite_info(spr)
    
end
--- first 60 characters of the line Aseprite printed ---
@@ASEMCP:7a9bcce2ba3293e3@@{"frameCount":1,"paletteSize":1,"
launches for the flip: 1
result keys: ['colorMode', 'filename', 'frameCount', 'frames', 'height', 'layerCount', 'layers', 'ok', 'paletteSize', 'slices', 'tags', 'width']
ok: True width: 4 height: 2
after:  [["#00000000", "#00000000", "#00000000", "#ff0000ff"], ["#00000000", "#00000000", "#00000000", "#00000000"]]
ValidationFailed: direction must be "horizontal" or "vertical"
launches for the refused call: 0
```

Read it from the top. The red pixel moved from the left edge to the right edge of the
top row, so the flip did what it says. One editor run did the flip. Its output was one line
that begins with `@@ASEMCP:` and the run's own 16 hex digits, followed by the result as
JSON; the wrapper at the end of the generated script prints it, and the runner reads only
lines carrying that token. The dictionary is the sprite's state as `sprite_info`
reports it, with `ok` true. And `"sideways"` was refused with zero editor runs, because
Python rejected it first.

### Check it with tests

The editor tier has a test that calls this tool:

```bash
uv run --locked pytest --run-aseprite -rs tests/test_tools.py::test_transforms
```

```text
.                                                                        [100%]
1 passed in 3.00s
```

`--run-aseprite` is what lets a test start Aseprite. Without it, the editor tier is not
run, and with it but with no editor installed, pytest stops with an error rather than
quietly skipping. The test passes whenever `flip_sprite` runs without raising.

### Next steps you could take

That test is weaker than it looks. [`tests/test_tools.py`](../tests/test_tools.py) calls
`flip_sprite(..., "horizontal")` in `test_transforms` and asserts nothing about the pixels
afterwards, so a flip that did nothing would pass. The `"vertical"` direction is never
called by any test. A test that draws one pixel, flips it, and reads it back with
`get_pixels`, the way the script above does, would close both gaps. It is a good first
editor-tier test to write; look for it among the
[good first issues](https://github.com/MalloyTheDev/aseprite-mcp/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## Which command proves what

| You want to know | Run | Needs Aseprite |
| --- | --- | --- |
| The Python side of a tool works: argument checks, arithmetic, refusals | `uv run --locked pytest` (the pure tier), or one file | No |
| A tool really edits a sprite the way it says | `uv run --locked pytest --run-aseprite -rs path/to/test.py::test_name` | Yes |
| The links, anchors and a few checked claims in the docs still hold | `python scripts/check_docs.py` | No |
| The README's tool counts and tables match the server, and no em dash crept in | `uv run --locked pytest tests/test_tool_docs.py tests/test_style.py` | No |
| Everything, as CI and the maintainers run it | [The release gate](DEVELOPMENT.md#local-release-gate) | Yes |
