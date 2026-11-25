# Development guide

For the path from choosing an issue to opening a pull request, see [Contributing](../CONTRIBUTING.md).

## Where changes go

| Area | What it owns |
| --- | --- |
| [`tools/`](../src/aseprite_mcp/tools/) | MCP tool signatures, docstrings, and adapters that call the core or the editor |
| [`core/`](../src/aseprite_mcp/core/) | Pixel-art algorithms, animation, validation, workspace paths, Lua generation, and Aseprite process execution |
| [`app.py`](../src/aseprite_mcp/app.py) and [`server.py`](../src/aseprite_mcp/server.py) | MCP registration, portable schemas, error handling, and the server entry point |
| [`tests/`](../tests/) | Python tests, editor-backed integration tests, and golden outputs |
| [`gen_tool_docs.py`](../scripts/gen_tool_docs.py) | The script that generates [`TOOLS.md`](TOOLS.md) from registered tools |

Tool modules may import `core/`. Keep the core independent of the tool modules and
the MCP SDK. That lets Python tests exercise the algorithms directly. The import test
checks every core module in a clean interpreter, including its indirect imports.
[Core import test](../tests/test_imports.py)

For Lua-backed tools, `run_lua()` passes the tool's arguments into the Lua `ARG`
table. `assemble_script()` adds the shared prelude and the runner reads the tagged
result from the Aseprite process. Native CLI exports use `run_cli()`. A tool may run
entirely in Python, invoke Aseprite once, or use separate calls to read and write a
sprite. [Lua generator](../src/aseprite_mcp/core/luagen.py) and [runner](../src/aseprite_mcp/core/runner.py)

## Adding or changing a tool

1. Start with the existing module for the operation under `src/aseprite_mcp/tools/`.
   Put reusable geometry, colour, timing, and validation logic in the core.
2. Add or update the `@mcp.tool()` function. Its docstring goes into the tool
   description, so explain the arguments, defaults, result, and any important limits.
   Import new tool modules in [`server.py`](../src/aseprite_mcp/server.py) to register them.
3. For editor changes, check the capabilities of the scripting API in batch mode.
   Reuse the shared prelude and existing drawing helpers, including the `_OPEN`/`_CLOSE`
   harness where appropriate. [Headless API notes](HEADLESS.md) and [drawing tools](../src/aseprite_mcp/tools/drawing.py)
4. Add a focused test. Put arithmetic and input validation in tests that run without
   Aseprite. Use the editor-backed suite for behaviour that depends on a real sprite,
   including the exact pixels, frame or layer metadata, and exported files.
5. When a tool description, signature, or registry entry changes, regenerate the reference
   with the command below and include the diff of `docs/TOOLS.md`.

```bash
uv run --locked python scripts/gen_tool_docs.py
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

Use Aseprite 1.3+ for the editor-backed suite. If detection misses your installation,
set `ASEPRITE_PATH` to the full executable path in the shell you test from.

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

If Windows reports that `.venv\Scripts\aseprite-mcp.exe` is in use during `uv sync`,
stop the client that is running the server from that checkout and retry. [Windows client troubleshooting](CLIENTS.md#5-troubleshooting)

## Running the tests

```bash
uv run --locked pytest -rs
uv run --locked pytest --run-aseprite -rs
```

The first command runs the Python-only tier. The second includes the integration and
golden tests when the editor is available. `-rs` shows why tests were skipped. If the
editor tests skip with `--run-aseprite`, check the reported reason and your
`ASEPRITE_PATH`. GitHub CI runs the Python tier on 3.10 through 3.14.

To run just the existing tilemap round-trip test with the editor, for example, use its
pytest file and test name.

```bash
uv run --locked pytest --run-aseprite -rs tests/test_expansion.py::test_tilemap_roundtrip
```

A new test file that runs entirely in Python needs its filename stem in
`PURE_PYTHON_TESTS` in [`tests/conftest.py`](../tests/conftest.py). For a Python-only
test inside a mixed file, add `@pytest.mark.pure` to the individual test. Run the
targeted test without `--run-aseprite` and check that it was executed. To simulate a
machine without the editor, set `ASEPRITE_PATH` to a path that does not exist for that
run.

On Windows, a temporary-directory cleanup message can appear after pytest finishes.
Use the test summary to check which tests passed, failed, or skipped.

## Local release gate

Use this for the full local check on a machine with Aseprite installed.

```bash
uv run python scripts/release_gate.py
```

The script stops at the first failure. It runs Ruff with the CI rules, the Python
tests, the editor tests, the tool reference check, and a wheel and source build.
Check the pytest summaries for skipped editor tests before recording a full gate pass.

Pass `--skip-aseprite` to the script to run the local checks without the editor tier.
If the Windows console script is locked and your environment is already synced, use
`uv run --no-sync python scripts/release_gate.py --no-sync` to run with that environment.
[Release gate script](../scripts/release_gate.py)

## Cutting a release

1. Run the full gate on the release branch with a working Aseprite install. Record
   the test counts in the pull request.
2. Regenerate the published [showcase outputs](../scripts/showcase/README.md) and
   compare them byte for byte with the tracked files. Record the reason for any
   intentional output change in the changelog.
3. Consolidate `[Unreleased]` in [`CHANGELOG.md`](../CHANGELOG.md) into a dated version
   section with one heading per change type. Leave a fresh `[Unreleased]` section.
4. Update the version in [`pyproject.toml`](../pyproject.toml). Explain the version
   bump in the changelog with the observable changes that justify it.
5. Merge the pull request and create an annotated tag on the merge commit. Describe
   the release and include the gate results in the tag message.
6. Create the GitHub release from the tag. Attach the wheel and source distribution
   from `uv build` so people can install the pinned release.
