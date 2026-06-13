# Contributing to Aseprite MCP

Thanks for your interest! This document covers local setup, the architecture, and
how to add or change tools.

## Local setup

```bash
git clone https://github.com/MalloyTheDev/aseprite-mcp.git
cd aseprite-mcp
uv sync                     # creates .venv and installs deps (incl. dev)
```

You'll also need **Aseprite 1.3+**. Point the server at it if it isn't auto-detected:

```bash
# Windows (PowerShell)
$env:ASEPRITE_PATH = "C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe"
# macOS / Linux
export ASEPRITE_PATH="/Applications/Aseprite.app/Contents/MacOS/aseprite"
```

## Running the tests

There are two tiers:

```bash
uv run pytest                 # fast: pure-Python unit tests only (no Aseprite needed)
uv run pytest --run-aseprite  # full: unit + Aseprite integration + golden-output tests
```

- **Pure-Python tests** (`tests/test_unit.py`, plus `test_properties.py`,
  `test_limits.py`, `test_output_paths.py`, `test_oplib.py`, `test_manifest.py`, …) cover
  colour parsing, Python→Lua serialization, the path sandbox, size limits, and the batch
  registry — including Hypothesis property tests. They always run — this is what CI
  exercises on every push. (The always-run set is listed in `tests/conftest.py`.)
- **Integration & golden tests** drive a real Aseprite install and run only with
  `--run-aseprite` (and require Aseprite to be found). Golden tests assert exact
  dimensions, pixel colours, frame/layer counts, tag metadata, and exported geometry.

> On Windows, pytest may print a harmless `PermissionError` from an `atexit` temp-dir
> cleanup handler *after* the run finishes. It does not affect results.

## Local release gate

Run the whole gate with one command:

```bash
uv run python scripts/release_gate.py            # runs every step below, fail-fast
```

It runs each of these in order and stops at the first failure:

```bash
uv run ruff check . --select F,E9               # lint (no unused imports / undefined names)
uv run pytest                                   # pure-Python tests
uv run pytest --run-aseprite                    # full integration + golden tests
uv run python scripts/gen_tool_docs.py --check  # docs/TOOLS.md is in sync with the registry
uv build                                        # wheel + sdist build
```

> CI runs the pure/headless steps on every push (it has no Aseprite). The
> `--run-aseprite` step is local-only. Pass `--skip-aseprite` to `release_gate.py` to
> mirror CI when Aseprite isn't installed.

## Architecture (how a tool works)

```
client → FastMCP tool (Python)  →  luagen.assemble_script  →  temp .lua
                                        │  (ARG table + shared PRELUDE)
                                        ▼
                              Aseprite.exe -b --script …
                                        │  prints @@ASEMCP@@<json>
                                        ▼
                              runner parses sentinel → dict
```

- [`src/aseprite_mcp/core/luagen.py`](src/aseprite_mcp/core/luagen.py) — the Python→Lua
  value serializer (`to_lua`) and the shared Lua **PRELUDE** (JSON encoder, colour/pixel
  helpers, deterministic drawing primitives, AA/pixel-perfect helpers, `sprite_info`).
- [`src/aseprite_mcp/core/runner.py`](src/aseprite_mcp/core/runner.py) — `run_lua()` and
  `run_cli()`; parses the result/error sentinels.
- [`src/aseprite_mcp/core/config.py`](src/aseprite_mcp/core/config.py) — locating Aseprite,
  the workspace, path resolution.
- [`src/aseprite_mcp/core/`](src/aseprite_mcp/core/) — reusable, Aseprite-/MCP-free logic
  (also `errors`, `models`, `manifest`, `oplib`, `validation`, `limits`, `paths`); importable
  without the FastMCP app. Backwards-compatible top-level shims (`luagen`/`runner`/`config`/
  `errors`) are preserved.
- [`src/aseprite_mcp/tools/`](src/aseprite_mcp/tools/) — one module per domain (the
  `@mcp.tool()` layer).

## Adding a tool

1. Pick (or create) the right module in `src/aseprite_mcp/tools/`.
2. Write the function, decorate with `@mcp.tool()`, and add a clear docstring (it
   becomes the tool description the model sees — document every argument).
3. Build a Lua **body** that uses the prelude helpers (`open_sprite`, `find_layer`,
   `to_pixel`, `get_draw_image`/`commit_image`, `sprite_info`, …), set the `RESULT`
   table, and call `run_lua(body, args)`. For drawing-style edits, reuse the
   `_OPEN`/`_CLOSE` harness in `tools/drawing.py`. For exports/preview, use `run_cli`.
4. If you created a new module, import it in
   [`src/aseprite_mcp/server.py`](src/aseprite_mcp/server.py) so its tools register.
5. Add a test in `tests/`.
6. Regenerate the tool reference:

   ```bash
   uv run python scripts/gen_tool_docs.py
   ```

### Conventions

- Frames are **1-based**; palette indices are **0-based**.
- Accept colours as flexible strings and parse with `tools/common.parse_color`.
- Resolve user paths with `tools/common.resolve_path` (relative → workspace).
- Pass paths to Lua via `tools/common.lua_path` (forward slashes).
- Keep operations deterministic and headless — no GUI/persistent-state assumptions.
- Raise **typed errors** from `errors.py` at boundaries: `AsepriteNotFoundError` /
  `WorkspaceError` (config & path sandbox), `LuaToolError` (a Lua body failed),
  `AsepriteCLIError` / `ExportError` (CLI/export), `AsepriteTimeoutError` (timeout).
  All subclass `AsepriteMCPError`, aliased as `AsepriteError` for backwards
  compatibility (`from aseprite_mcp.runner import AsepriteError` still works and still
  catches every aseprite-mcp error).
- **Workflow tools** (high-level scaffolding in `tools/workflow.py`) must return a
  `workflow_manifest.v1` object built with the helpers in `core/manifest.py`
  (`workflow_manifest`, `file_entry`, `export_entry`, `sprite_summary`) — don't hand-roll
  a bespoke result dict. Add the `kind`/roles to `core/manifest.py` if you need new ones.

## Pull requests

- Keep changes focused and include tests where practical.
- Run `uv run pytest` and regenerate `docs/TOOLS.md` before submitting.
- Describe what you changed and why.
