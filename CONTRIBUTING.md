# Contributing to Aseprite MCP

Thanks for your interest! This document covers local setup, the architecture, and
how to add or change tools.

## Local setup

```bash
git clone https://github.com/MalloyTheDev/aseprite-mcp.git
cd aseprite-mcp
uv sync                     # creates .venv and installs deps (incl. dev)
```

The package targets **Python 3.10+** (`requires-python = ">=3.10"`), and CI runs the whole
headless tier on 3.10, 3.11, 3.12 and 3.13. Anything that only works on a newer
interpreter will fail the 3.10 job, so check the version floor before reaching for recent
syntax.

> If a client is running the server out of this checkout, `uv sync` fails on Windows with
> a "file in use" error: it has to replace `.venv\Scripts\aseprite-mcp.exe`, which the
> live server holds open. Stop the client first.

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
  registry, including Hypothesis property tests. They always run; this is what CI
  exercises on every push.
- **Integration & golden tests** drive a real Aseprite install and run only with
  `--run-aseprite` (and require Aseprite to be found). Golden tests assert exact
  dimensions, pixel colours, frame/layer counts, tag metadata, and exported geometry.

> **Adding a pure-Python test file? Add it to `PURE_PYTHON_TESTS` too.** That tuple in
> [`tests/conftest.py`](tests/conftest.py) is an **allowlist of module names**, so a new
> test file that needs no Aseprite is **skipped** by default, on your machine and on CI.
> A skipped file is reported as `s` in a dot line and folded into the "N skipped" count,
> which is indistinguishable from passing unless you go looking. Entries are whole module
> names: `test_timing` means `tests/test_timing.py` and nothing else. The matching has
> been got wrong in both directions before (see the comments in that file), and a test
> that never runs is worse than no test, because it reads as coverage.

> **A pure test inside an integration file? Mark it `@pytest.mark.pure`.** The allowlist
> can only speak about whole files, and most integration files hold a few tests that need
> no editor, typically the pre-flight refusals that assert a bad argument is rejected in
> Python *before* Aseprite is launched. Fifty-five of those were being skipped on CI.
>
> **Do not add a mixed file to `PURE_PYTHON_TESTS` to fix that.** It would be worse than
> the gap: the Aseprite-backed tests in the same file would then run with no editor and
> pass vacuously, which looks like coverage and is not. Mark the individual test instead.
>
> Marking is safe in the direction that matters: a test marked `pure` that actually needs
> Aseprite fails on CI immediately, because CI is precisely the environment with no
> Aseprite in it. Check your own marking the same way before you push, by pointing
> `ASEPRITE_PATH` at a path that does not exist and running the pure tier:
>
> ```bash
> ASEPRITE_PATH=/no/such/aseprite uv run --no-sync pytest
> ```
>
> Point it at a path that does not **exist**, not at some other file: `find_aseprite()`
> only checks `is_file()`, so any real file makes detection *succeed* and a test asserting
> `aseprite_found is True` then passes for a reason that will not hold on a runner.

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

> **The gate's lint step is narrower than CI's.** `--select F,E9` overrides the
> `[tool.ruff.lint]` selection in `pyproject.toml`, so the gate checks pyflakes and syntax
> errors only, while CI runs `ruff check src tests scripts` under the full configured set
> (`E`, `W`, `F`, `I`, `B`, `UP`, `C4`, `SIM`, `RUF`). Import sorting, bugbear and
> pyupgrade findings therefore pass the local gate and fail CI. Run the CI form yourself
> before pushing:
>
> ```bash
> uv run ruff check src tests scripts
> ```

> CI runs the pure/headless steps on every push (it has no Aseprite). The
> `--run-aseprite` step is local-only. Pass `--skip-aseprite` to `release_gate.py` to
> mirror CI when Aseprite isn't installed, bearing the lint difference above in mind,
> since that flag does not make the lint step match CI either.

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

- [`src/aseprite_mcp/core/luagen.py`](src/aseprite_mcp/core/luagen.py): the Python→Lua
  value serializer (`to_lua`) and the shared Lua **PRELUDE** (JSON encoder, colour/pixel
  helpers, deterministic drawing primitives, AA/pixel-perfect helpers, `sprite_info`).
- [`src/aseprite_mcp/core/runner.py`](src/aseprite_mcp/core/runner.py): `run_lua()` and
  `run_cli()`; parses the result/error sentinels.
- [`src/aseprite_mcp/core/config.py`](src/aseprite_mcp/core/config.py): locating Aseprite,
  the workspace, path resolution.
- [`src/aseprite_mcp/core/`](src/aseprite_mcp/core/): reusable, Aseprite-/MCP-free logic
  (also `errors`, `models`, `manifest`, `oplib`, `validation`, `limits`, `paths`); importable
  without the FastMCP app. Backwards-compatible top-level shims (`luagen`/`runner`/`config`/
  `errors`) are preserved.
- [`src/aseprite_mcp/tools/`](src/aseprite_mcp/tools/): one module per domain (the
  `@mcp.tool()` layer).

## Adding a tool

> **Check the idea against [`docs/HEADLESS.md`](docs/HEADLESS.md) first.** Every tool is
> one `aseprite -b --script` run, and the scripting API does not advertise what that
> costs: `Dialog` is a constructor that builds `nil`, `app.transform` does not exist,
> `Rotate{target="mask"}` and the UI commands return success and do nothing, two
> `app.useTool` calls take the process down with no file written, and `app.preferences`
> writes land in the GUI configuration of the person running the server. That file has
> the full list, which workaround each constraint forced, and the code that implements it,
> so a tool that cannot work is ruled out in one pass rather than after it is written.

1. Pick (or create) the right module in `src/aseprite_mcp/tools/`.
2. Write the function, decorate with `@mcp.tool()`, and add a clear docstring (it
   becomes the tool description the model sees, so document every argument).
3. Build a Lua **body** that uses the prelude helpers (`open_sprite`, `find_layer`,
   `to_pixel`, `get_draw_image`/`commit_image`, `sprite_info`, …), set the `RESULT`
   table, and call `run_lua(body, args)`. For drawing-style edits, reuse the
   `_OPEN`/`_CLOSE` harness in `tools/drawing.py`. For exports/preview, use `run_cli`.
4. If you created a new module, import it in
   [`src/aseprite_mcp/server.py`](src/aseprite_mcp/server.py) so its tools register.
5. Add a test in `tests/`. If it needs no Aseprite, add its module name to
   `PURE_PYTHON_TESTS` in `tests/conftest.py` or it will be silently skipped
   (see [Running the tests](#running-the-tests)).
6. Regenerate the tool reference:

   ```bash
   uv run python scripts/gen_tool_docs.py
   ```

### Conventions

- Frames are **1-based**; palette indices are **0-based**.
- **Put the judgement in `core/`, keep the Lua thin.** Anything that decides something
  (geometry, ramps, timing, validation, path policy) belongs in a `core/` module that
  imports neither Aseprite nor MCP, so CI can test it on a runner with no editor
  installed. `tools/` should be the `@mcp.tool()` wrapper plus the Lua body that applies
  the decision. A rule that only exists inside a Lua string can only be tested by
  launching Aseprite, which puts it in the `--run-aseprite` tier that CI never reaches.
- **Every parameter must advertise one concrete wire type.** A bare `x: int | None = None`
  serializes as a nullable `anyOf` with pydantic `title` noise, which strict
  function-calling clients mishandle, so the registration pass collapses it to a single
  `type` and restates the default in the parameter's `description`. If a tool needs to
  accept two shapes (an object or a JSON-looking string, say), widen the *behaviour* with
  a `BeforeValidator` and keep the declared type concrete. `tests/test_schema_portability.py`
  asserts this across the whole registry, so adding a tool is what reintroduces the
  problem and what catches it.
- Accept colours as flexible strings and parse with `tools/common.parse_color`.
- Resolve user paths with `tools/common.resolve_path` (relative → workspace).
- Pass paths to Lua via `tools/common.lua_path` (forward slashes).
- Keep operations deterministic and headless: no GUI/persistent-state assumptions. What
  is actually unavailable, silently inert or outright fatal under `-b`, and what each
  constraint forced instead, is in [`docs/HEADLESS.md`](docs/HEADLESS.md).
- Raise **typed errors** from `errors.py` at boundaries: `AsepriteNotFoundError` /
  `WorkspaceError` (config & path sandbox), `LuaToolError` (a Lua body failed),
  `AsepriteCLIError` / `ExportError` (CLI/export), `AsepriteTimeoutError` (timeout).
  All subclass `AsepriteMCPError`, aliased as `AsepriteError` for backwards
  compatibility (`from aseprite_mcp.runner import AsepriteError` still works and still
  catches every aseprite-mcp error).
- **Workflow tools** (high-level scaffolding in `tools/workflow.py`) must return a
  `workflow_manifest.v1` object built with the helpers in `core/manifest.py`
  (`workflow_manifest`, `file_entry`, `export_entry`, `sprite_summary`); don't hand-roll
  a bespoke result dict. Add the `kind`/roles to `core/manifest.py` if you need new ones.

## Pull requests

- Keep changes focused and include tests where practical.
- Before submitting, run what CI runs, so a lint or docs failure costs you a minute rather
  than a round trip:

  ```bash
  uv run ruff check src tests scripts
  uv run pytest
  uv run python scripts/gen_tool_docs.py --check   # or drop --check to regenerate
  ```

- Never hand-edit `docs/TOOLS.md`; it is generated from the tool docstrings by
  `scripts/gen_tool_docs.py`, and the `--check` step above fails if it has drifted.
- Describe what you changed and why.
