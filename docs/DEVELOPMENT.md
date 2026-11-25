# Development guide

For the path from choosing an issue to opening a pull request, see [Contributing](../CONTRIBUTING.md).
For a hands-on first look at how one tool runs, see the [walkthrough](WALKTHROUGH.md).

## Where changes go

| Area | What it owns |
| --- | --- |
| [`tools/`](../src/aseprite_mcp/tools/) | MCP tool signatures, docstrings, and adapters that call the core or the editor |
| [`core/`](../src/aseprite_mcp/core/) | Pixel-art algorithms, animation, validation, workspace paths, Lua generation, and Aseprite process execution |
| [`app.py`](../src/aseprite_mcp/app.py) and [`server.py`](../src/aseprite_mcp/server.py) | MCP registration, portable schemas, error handling, and the server entry point |
| [`tests/`](../tests/) | Python tests, editor-backed integration tests, and golden outputs |
| [`gen_tool_docs.py`](../scripts/gen_tool_docs.py) | The script that generates [`TOOLS.md`](TOOLS.md) from registered tools |
| [`check_docs.py`](../scripts/check_docs.py) | The check that the Markdown docs have no broken links, anchors or stale claims |

Tool modules may import `core/`. Keep the core independent of the tool modules and
the MCP SDK. That lets Python tests exercise the algorithms directly. The import test
checks every core module in a clean interpreter, including its indirect imports.
[Core import test](../tests/test_imports.py)

For Lua-backed tools, `run_lua()` passes the tool's arguments into the Lua `ARG`
table. `assemble_script()` adds the shared prelude and the runner reads the tagged
result from the Aseprite process. Native CLI exports use `run_cli()`. A tool may run
entirely in Python, invoke Aseprite once, or use separate calls to read and write a
sprite. [Lua generator](../src/aseprite_mcp/core/luagen.py) and [runner](../src/aseprite_mcp/core/runner.py)

### What a tool call launches

A tool call does not always start Aseprite, and when it does it does not always save the
sprite. Classified over the registered tools on `main` by following each one to the runner,
they fall into these classes (a tool that is refused by a check before it reaches the
editor launches nothing, whatever its class):

| Class | Tools | Launches | Writes |
| --- | --- | --- | --- |
| Never launch Aseprite | `deselect`, `gui_available`, `list_sprites`, `plan_asset_spec`, `validate_asset_spec`, `write_pack_mcmeta`, `write_texture_mcmeta` | none | their own files, or nothing |
| Launch read-only | `assess_sprite`, `diff_sprites`, `get_cel`, `get_palette`, `get_pixels`, `get_properties`, `get_selection`, `get_sprite_info`, `get_tilemap`, `health_check`, `list_palette_usage`, `list_slices`, `render_preview`, `validate_asset_against_spec`, `validate_loop`, `validate_minecraft_texture`, `validate_sprite_for_game_export` | at least one | nothing the caller owns |
| Exports | every `export_*` tool: `export_frames`, `export_game_asset_bundle`, `export_gif`, `export_godot_spriteframes`, `export_layer`, `export_layers`, `export_minecraft_texture`, `export_motion_trail`, `export_onion_skin`, `export_png`, `export_slice_metadata`, `export_spritesheet`, `export_spritesheet_packed`, `export_tag_gif`, `export_tags` | at least one | other files; the source sprite is untouched |
| Selection | `select_by_color`, `select_region`, `modify_selection`, `invert_selection` | at least one | only the `.msk` sidecar beside the sprite |
| Editor window | `open_in_editor` | starts the GUI and does not wait for it | nothing |
| Everything else | the remaining tools, which is most of them | at least one | open the sprite, edit it, and save it in place |

Three tools change class with their arguments. `generate_ramp` and `ramp_between` launch
Aseprite only when `apply` is not `"none"`. `apply_operations(dry_run=True)` launches
nothing. To check a tool yourself, wrap `aseprite_mcp.core.runner._run_bounded` with a
counter, as the [walkthrough](WALKTHROUGH.md#part-2-a-tool-that-edits-a-sprite-flip_sprite)
does. The classes are not asserted by a test, so a new tool needs a line here only if it
does not fit one of them.

### The result protocol

A Lua-backed tool body sets a global `RESULT` table. The harness that `assemble_script()`
wraps around it runs the body inside `pcall` and prints exactly one line to stdout:

```text
@@ASEMCP:<16 hex digits>@@<json>
@@ASEMCP_ERR:<16 hex digits>@@<json-encoded message>
```

The first is a result and the second a failure. The 16 hex digits are a fresh nonce made
by `new_nonce()` for each run ([`core/luagen.py`](../src/aseprite_mcp/core/luagen.py),
`result_prefix` and `error_prefix`). The nonce exists so that user-supplied text that
reaches stdout, such as a layer name, cannot pass for the protocol: the payload is
serialised before the nonce is chosen and never appears in the script's input.

The runner ([`core/runner.py`](../src/aseprite_mcp/core/runner.py), `_parse_result`) reads
stdout like this:

- It looks only for lines that begin with this run's own prefixes. More than one result
  line, more than one error line, or one of each is refused with a `LuaToolError` rather
  than guessing which to trust.
- An error line is decoded as JSON and raised as a `LuaToolError`. The temporary script's
  path and line number are stripped from the message (`strip_script_location`), because
  they name a file that no longer exists and leak the host's temp directory.
- With no sentinel at all (a Lua compile error, for example, where the harness never
  ran), the error is whatever Aseprite wrote to stderr, or to stdout if stderr is empty,
  again with the script location stripped.
- A result that is not a JSON object is refused. An empty Lua table, which JSON cannot
  tell from an empty list, is normalised to `{}`.
- Native CLI exports go through `run_cli()` instead and have no sentinel. It treats any
  text on stderr as a failure even when the exit code is 0, because Aseprite exits 0 for
  arguments it rejected.

The older names `@@ASEMCP@@` and `@@ASEMCP_ERR@@` are legacy constants in `luagen.py`,
kept so that code importing them still works. They no longer frame real output.

## Adding or changing a tool

1. Start with the existing module for the operation under `src/aseprite_mcp/tools/`.
   Put reusable geometry, colour, timing, and validation logic in the core.
2. Add or update the `@mcp.tool()` function. Its docstring goes into the tool
   description, so explain the arguments, defaults, result, and any important limits.
   Import new tool modules in [`server.py`](../src/aseprite_mcp/server.py) to register them.
   Two groups register differently, so edit the source, not the registered text:
   nine drawing tools (`draw_pixels`, `draw_pixel_map`, `draw_line`, `draw_polyline`,
   `draw_curve`, `draw_rectangle`, `draw_ellipse`, `draw_ellipse_in_box`, `fill_area`) are
   decorated with `_geometry_tool`, which appends the shared coordinate note to the
   docstring at import ([`tools/drawing.py`](../src/aseprite_mcp/tools/drawing.py), `_geometry_tool`),
   and `apply_operations` has the list of operations appended to its docstring when
   [`tools/batch.py`](../src/aseprite_mcp/tools/batch.py) is imported. What a client sees
   for those is the composed text.
3. For editor changes, check the capabilities of the scripting API in batch mode.
   Reuse the shared prelude and existing drawing helpers, including the `_OPEN`/`_CLOSE`
   harness where appropriate. [Headless API notes](HEADLESS.md) and [drawing tools](../src/aseprite_mcp/tools/drawing.py)
4. Add a focused test. Put arithmetic and input validation in tests that run without
   Aseprite. Use the editor-backed suite for behaviour that depends on a real sprite,
   including the exact pixels, frame or layer metadata, and exported files.
5. When a tool description, signature, or registry entry changes, regenerate the reference
   with the command below and include the diff of `docs/TOOLS.md`. When the file is stale,
   the check form names the tool whose text drifted (here `draw_line`), then prints a
   diff of up to 40 lines and the command to run:

   ```text
   docs/TOOLS.md is OUT OF DATE.
     changed (1): draw_line
   Regenerate it with: uv run --locked python scripts/gen_tool_docs.py
   ```

```bash
uv run --locked python scripts/gen_tool_docs.py
uv run --locked python scripts/gen_tool_docs.py --check
```

### Tool conventions

- Frame numbers are 1-based. Palette indices are 0-based.
- Use `parse_color` for colour strings, `resolve_path` for workspace-relative
  filenames, and `lua_path` for paths passed to Lua. [Shared tool helpers](../src/aseprite_mcp/tools/common.py)
- Keep each MCP argument's advertised wire type concrete. Optional arguments still
  need one wire type. When a tool can accept a second input shape, the existing
  Pydantic `BeforeValidator` pattern can normalize it before validation.
  [Schema tests](../tests/test_schema_portability.py)
- Use the typed exceptions at tool boundaries. Use `ValidationFailed` for
  rejected input and the existing workspace, Lua, CLI, export, and timeout errors
  for their respective failures. These inherit from `AsepriteMCPError`, also
  available as `AsepriteError`. [Error types](../src/aseprite_mcp/core/errors.py)
- Workflow tools return `workflow_manifest.v1`. Use `workflow_manifest` and the
  existing file, export, and sprite helpers for that result. [Manifest helpers](../src/aseprite_mcp/core/manifest.py)

## Local editor setup

The editor-backed suite was developed and tested on Aseprite 1.3.18.6. Other versions are
not tested. If detection misses your installation, set `ASEPRITE_PATH` to the full
executable path in the shell you test from. Detection order is `ASEPRITE_PATH` (a wrong
value is an error, with no fallback), then `aseprite` on `PATH`, then the usual install
locations. [`core/config.py`](../src/aseprite_mcp/core/config.py)

Example for a Windows Steam install in PowerShell.

```powershell
$env:ASEPRITE_PATH = "C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe"
```

Example for a macOS application in `/Applications`.

```bash
export ASEPRITE_PATH="/Applications/Aseprite.app/Contents/MacOS/aseprite"
```

On Linux, use the same `export` syntax with the path to your installed binary. To
test from an MCP client, point it at your working checkout and use a scratch workspace.
Verify the connection with `health_check`. [Client setup](CLIENTS.md#4-verify-it-works)

If Windows reports that `.venv\Scripts\aseprite-mcp.exe` is in use, or `uv` fails with
"os error 32", a client is running the server from that checkout. Stop the client, or run
with `uv run --no-sync ...`, or launch the server from the client as
`python -m aseprite_mcp`. [Windows client troubleshooting](CLIENTS.md#5-troubleshooting)

## Running the tests

```bash
uv run --locked pytest
uv run --locked pytest --run-aseprite -rs
```

The first command runs the pure tier, which needs no Aseprite and is what CI runs. The
second adds the editor tier: the integration and golden tests that drive a real Aseprite.
`-rs` prints the reason for every skip. With `--run-aseprite` and no editor found, pytest
stops with an error instead of skipping the editor tests, so a green run means the editor
tests ran. GitHub CI runs the pure tier on Python 3.10 through 3.14 and prints its summary
line.

With `--run-aseprite` and no editor, the run stops with exit code 4 and prints:

```text
ERROR: --run-aseprite was given but Aseprite was not found: ASEPRITE_PATH is set to '<path>' but no file exists there.
The editor tier needs a real Aseprite. Set ASEPRITE_PATH to the Aseprite executable (or put `aseprite` on PATH), or leave out --run-aseprite to run the pure tier only.
```

The words after the first colon are the search's own message and vary with the cause. CI
runs `uv run --python <version> pytest`, whose log ends in a single summary line with the
passed and skipped counts, and then a step "Check documentation links" that runs
`uv run --python <version> python scripts/check_docs.py`.

To run one editor test, give its file and name.

```bash
uv run --locked pytest --run-aseprite -rs tests/test_expansion.py::test_tilemap_roundtrip
```

### Registering a test in a tier

Every `tests/test_*.py` has to say which tier it is in. A file that says nothing fails at
setup with an instruction instead of being skipped. There are three ways to say it:

1. Add the filename stem to `PURE_PYTHON_TESTS` in [`tests/conftest.py`](../tests/conftest.py)
   when every test in the file is pure. Add it to `EDITOR_ONLY_TESTS` there when none is.
2. Decorate individual tests with `@pytest.mark.pure` in a file that mixes both kinds.
3. Put `pytestmark = pytest.mark.pure` at the top of the module when every test in it is
   pure and you would rather not touch `conftest.py`. This is what `tests/test_check_docs.py` does.

An undeclared file errors at setup, even in a targeted run, with a message such as:

```text
tests/test_brand_new.py does not say whether it needs Aseprite, so it would be skipped in silence. In tests/conftest.py, add 'test_brand_new' to PURE_PYTHON_TESTS if none of its tests launch the editor, or to EDITOR_ONLY_TESTS if all of them do. If it mixes the two, mark the editor-free tests @pytest.mark.pure instead (or the whole module, with `pytestmark = pytest.mark.pure`).
```

A marker counts whether it is a decorator or `pytestmark = pytest.mark.pure` at module or
class level (the list form included). A file that declares its tier more than once fails
with "declares its tier more than once", so keep exactly one way.

The rule has a second half. Without `--run-aseprite`, the suite points `ASEPRITE_PATH` for
the whole session at a path that does not exist (under the temporary directory, in a folder
named `editor-disabled-without--run-aseprite`), so a test marked pure that launches Aseprite
fails at once on your machine, the way it would on CI:

```text
AsepriteNotFoundError: ASEPRITE_PATH is set to '...editor-disabled-without--run-aseprite\aseprite' but no file exists there.
```

Before this was enforced, such a test passed locally on any machine with an editor
installed and failed only on CI. If a test marked pure fails like this, it needs the
editor, so unmark it.

On a machine without the editor, run a single test to check that it was executed and
not skipped:

```bash
uv run --locked pytest -rs tests/test_ramp_tools.py
```

On Windows, a temporary-directory cleanup message can appear after pytest finishes. The
summary line is what says how many passed, failed or skipped.

## Local release gate

Use this for the full local check on a machine with Aseprite installed.

```bash
uv run --locked python scripts/release_gate.py
```

Before it runs anything the gate prints the interpreter, the package tree it will test,
and the Aseprite path and version it found. It stops at the first failure, and it prints
each tier's passed, skipped and failed counts. It runs Ruff with the CI rules, the pure
tier, the editor tier, the tool reference check, and a wheel and source build. Without
`--skip-aseprite`, a machine with no editor fails at the start instead of reporting an
editor tier that never ran.

The header looks like this (paths shortened):

```text
release-gate: 6 steps (cwd=...)
release-gate: python 3.12.13 | <package version> | ...\src\aseprite_mcp
release-gate: aseprite C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe (Aseprite 1.3.18.6-x64)
```

Each step prints a line such as `ok (48.4s): 1814 passed, 846 skipped` (counts grow, so do
not compare against this page), and the closing summary has one row per step:

```text
  PASS  pure tests (pytest) (48.4s): 1814 passed, 846 skipped
```

The editor step also fails if any test was skipped for want of an editor, or if nothing
passed. With no editor and no `--skip-aseprite` the gate exits 1 before any step:

```text
release-gate: aseprite NOT FOUND: ASEPRITE_PATH is set to 'C:\nowhere\Aseprite.exe' but no file exists there.
release-gate: FAILED before any step: the integration step needs a real Aseprite and none was found. Set ASEPRITE_PATH to the Aseprite executable, or pass --skip-aseprite to run only what CI runs.
```

Flags: `--skip-aseprite` runs everything that CI runs and nothing that needs the editor. The
summary then carries `SKIP  integration (pytest --run-aseprite): NOT RUN (--skip-aseprite);
nothing was tested against Aseprite`, and a passing run ends with
`all run steps passed; the editor tier was NOT run (--skip-aseprite).`
`--no-sync` runs with the environment as it is instead of syncing it from `uv.lock`, for
when a client holds the console script (on Windows, launch it as
`uv run --no-sync python scripts/release_gate.py --no-sync`). `--showcase` adds a step that
runs `scripts/verify_showcase.py`; it cannot be combined with `--skip-aseprite`. Steps run
under `uv run --locked`, or `uv run --no-sync` when you pass `--no-sync`.
[Release gate script](../scripts/release_gate.py)

The gate runs the documentation check as a step, as CI does. It also runs on its own in a
second:

```bash
python scripts/check_docs.py
```

It needs no environment and no network. It checks relative links, in-page and cross-file
anchors using GitHub's rules, reference-style link definitions, and a few claims that went
stale once: the documented result sentinels against `core/luagen.py`, contributor
commands using `--locked` or `--no-sync`, and repository paths named in backticks.
External links are not fetched; `--external` lists them.

## Cutting a release

1. Run the full gate on the release branch with a working Aseprite install. Record
   the test counts in the pull request.
2. Regenerate the published [showcase outputs](../scripts/showcase/README.md) and
   compare them with the tracked files by running
   [`scripts/verify_showcase.py`](../scripts/verify_showcase.py)
   (`uv run --locked python scripts/verify_showcase.py`).
   It takes about 3.5 minutes, needs a real Aseprite, and runs the 13 generators into a
   temporary workspace that is deleted afterwards, then compares the SHA-256 of each of the
   18 published images with its copy at `HEAD`. It exits 0 when all are identical, 1 on
   any difference, missing output or generator failure, and 2 when no editor is found or
   the workspace is not empty. A match ends with:

   ```text
   verify-showcase: 18 identical, 0 different, 0 missing of 18 published files; 0 generator(s) failed. Aseprite: Aseprite 1.3.18.6-x64
   verify-showcase: PASS
   ```

   Use `--only GENERATOR ...` to run some generators, and `--workspace DIR` to keep the
   output in an empty directory you name.
   Record the reason for any intentional output change in the changelog.
3. Consolidate `[Unreleased]` in [`CHANGELOG.md`](../CHANGELOG.md) into a dated version
   section with one heading per change type. Leave a fresh `[Unreleased]` section, and add
   a link definition at the bottom of the file for the new version.
4. Update the version in [`pyproject.toml`](../pyproject.toml). Explain the version
   bump in the changelog with the observable changes that justify it. `__version__` in
   [`src/aseprite_mcp/__init__.py`](../src/aseprite_mcp/__init__.py) is what `health_check`
   reports, and it is a separate edit.
5. Merge the pull request and create an annotated tag on the merge commit. Describe
   the release and include the gate results in the tag message.
6. Create the GitHub release from the tag. Attach the wheel and source distribution
   from `uv build` so people can install the pinned release.
