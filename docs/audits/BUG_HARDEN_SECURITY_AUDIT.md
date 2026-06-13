# Bug / Hardening / Security Audit — aseprite-mcp

**Scope:** repository at v0.6.0 (`main`). Report-only; no behavior changes. Inspection
covered `core/` (config, runner, luagen, errors, models, manifest, validation, oplib),
`tools/*` (incl. batch), tests, docs, CI, packaging.

**Gate at audit time:** `ruff F,E9` clean · `pytest` 74 passed (pure) · `pytest --run-aseprite`
132 passed · `gen_tool_docs.py --check` in sync (108 tools).

**Headline:** the recent typed-errors / typed-models / core-split / batch work is solid —
the bug audit is mostly *confirmed-OK*. The real, actionable gaps are in **hardening**
(no release-gate script, no property tests, no size limits, no overwrite policy) and
**security posture** (overwrite/clobber, GitHub Actions permissions, missing SECURITY.md,
missing symlink regression test). No Critical/Confirmed-Critical issues found.

---

# 1. Bug audit

## Finding: Batch rollback preserves the on-disk file
Severity: Info · Category: Bug · Area: batch · Status: Confirmed (no issue)

Description: `apply_operations` runs all ops inside `app.transaction(...)` and calls
`save_sprite(spr)` only **after** the transaction returns; any op `error(...)`s out, so
`save_sprite` is never reached and the in-memory transaction rolls back.
Evidence: `core/oplib.py` `BATCH_LUA_BODY` (transaction wraps the op loop; `save_sprite`
is after it); `tests/test_batch.py::test_mid_batch_failure_rolls_back_and_saves_nothing`
asserts the on-disk pixels are unchanged after a mid-batch failure.
Impact: none — behaves as intended.
Recommended fix: none.
Suggested PR: n/a.

## Finding: dry_run never launches Aseprite
Severity: Info · Category: Bug · Area: batch · Status: Confirmed (no issue)

Description: `apply_operations(..., dry_run=True)` validates via `oplib.validate_operations`
(pure Python) and `return`s the plan **before** any `run_lua`/`run_cli` call.
Evidence: `tools/batch.py` (the `if dry_run:` branch returns before `resolve_path`/`run_lua`);
`tests/test_batch.py::test_dry_run_does_not_touch_file_and_returns_plan`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.

## Finding: Typed errors preserve legacy catch behavior
Severity: Info · Category: Bug · Area: errors · Status: Confirmed (no issue)

Description: `AsepriteError` is an alias of `AsepriteMCPError`; `AsepriteNotFoundError`
also subclasses `FileNotFoundError`, so existing `except FileNotFoundError`
(`gui.gui_available`, `health.health_check`, `conftest`) and `from aseprite_mcp.runner
import AsepriteError` keep working.
Evidence: `core/errors.py`; `tests/test_errors.py` (alias identity, `FileNotFoundError`
back-compat, runner/CLI/timeout mapping).
Impact: none.
Recommended fix: none. (Note: `AsepriteNotFoundError(FileNotFoundError)` is a deliberate
compat base — a future cleanup may switch those three catch sites to
`AsepriteNotFoundError` and drop the extra base.)
Suggested PR: n/a.

## Finding: core shims do not create import cycles / pull in the MCP app
Severity: Info · Category: Bug · Area: core/packaging · Status: Confirmed (no issue)

Description: shims (`aseprite_mcp/{config,luagen,runner,errors}.py`) import only from
`core.*`; `core.*` imports nothing from `tools/` or `app`.
Evidence: `tests/test_imports.py::test_core_does_not_import_mcp_app_or_tools` runs in a
clean interpreter and asserts `aseprite_mcp.app` / `mcp.server.fastmcp` / `aseprite_mcp.tools.*`
are absent from `sys.modules` after importing all of `core`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.

## Finding: Workspace path anchor is correct after the core split
Severity: Info · Category: Bug · Area: config · Status: Confirmed (no issue)

Description: moving `config.py` into `core/` changed its depth; `PROJECT_ROOT` was updated
`parents[2] → parents[3]`. Verified at runtime: `PROJECT_ROOT == <repo root>` and the
default workspace resolves to `<repo>/workspace` (not `src/workspace`).
Evidence: `core/config.py:PROJECT_ROOT`; runtime check during audit printed
`PROJECT_ROOT: <repo>` / `workspace: <repo>/workspace`.
Impact: none — but there is **no regression test** locking this (see H-PathAnchor).
Recommended fix: none for the bug; add a guard test (hardening).
Suggested PR: harden/release-gate-and-property-tests.

## Finding: README/CONTRIBUTING architecture links point at the back-compat shims
Severity: Low · Category: Bug (docs drift) · Area: docs · Status: Confirmed

Description: the "Project layout" / "Architecture" sections still link
`src/aseprite_mcp/{luagen,runner,config}.py` and describe them as the engine modules.
Those paths are now thin re-export **shims**; the real logic lives in `core/`.
Evidence: `README.md` project-layout list and `CONTRIBUTING.md` architecture section
reference the top-level paths; `git mv` moved the modules to `src/aseprite_mcp/core/`.
Impact: misleading for new contributors; links resolve but to shims.
Recommended fix: update the layout/architecture sections to point at `core/` and mention
the shims exist for back-compat. **Docs-only.**
Suggested PR: harden/release-gate-and-property-tests (bundle docs touch-ups).

## Finding: Only one manifest kind is covered by a JSON-serialization test
Severity: Medium · Category: Bug (latent) · Area: manifest/tests · Status: Confirmed

Description: `workflow_manifest.v1` is consumed as JSON (e.g. `export_game_asset_bundle`
writes `manifest.json`; tool results are serialized by FastMCP). Only
`test_manifest_is_json_serializable` (one synthetic manifest) guards this. A future field
holding a non-JSON value (e.g. a `Path`) would only fail at runtime for the affected kind.
Evidence: `tests/test_manifest.py`; manifests are built in `tools/workflow.py`,
`tools/batch.py`.
Impact: a serialization regression could ship undetected for some kinds.
Recommended fix: a pure test that `json.dumps` a representative manifest for **every**
`VALID_KINDS` value (with operations/validation/sprite blocks populated).
Suggested PR: harden/release-gate-and-property-tests. Coverage: pure-Python.

---

# 2. Hardening audit

## Finding: No executable release-gate script
Severity: Medium · Category: Hardening · Area: tooling/CI · Status: Confirmed

Description: the release gate (ruff → pytest → `--run-aseprite` → docs `--check` → `uv build`)
is documented in `CONTRIBUTING.md` but run by hand each release.
Evidence: `CONTRIBUTING.md` "Local release gate"; no `scripts/release_gate.py`.
Impact: human error risk at release time; no single command.
Recommended fix: add `scripts/release_gate.py` that runs each step and exits non-zero on
the first failure (with a `--run-aseprite` flag passthrough).
Suggested PR: harden/release-gate-and-property-tests. Coverage: tooling (no test needed; it
*is* the gate).

## Finding: No property/fuzz tests for serializers/parsers/path resolution
Severity: Medium · Category: Hardening · Area: luagen/models/config/tests · Status: Confirmed

Description: `to_lua`, `ColorSpec.parse`/`parse_color`, `config.resolve`, and manifest
assembly are covered only by example-based tests.
Evidence: `tests/test_unit.py`, `tests/test_models.py` (fixed examples).
Impact: edge cases (odd unicode, control chars, huge ints, exotic relative paths) are
unverified; `to_lua` correctness underpins the no-injection guarantee.
Recommended fix: add `hypothesis` (dev group) property tests:
- `to_lua(s)` for arbitrary text never emits an unescaped `"`/`\` outside an escape and the
  assembled script never contains the sentinels from user data.
- `parse_color` never raises on `#`-hex/`r,g,b[,a]` shapes and always yields 0–255.
- `config.resolve(rel)` for any relative path **without** `..` stays under the workspace.
Suggested PR: harden/release-gate-and-property-tests. Coverage: pure-Python.

## Finding: No overwrite / clobber policy
Severity: Medium · Category: Hardening (also Security S-Clobber) · Area: config/tools · Status: Confirmed

Description: `create_sprite`, `save_sprite_as`, all `export_*`, `import_image`, and the batch
save write to the resolved path unconditionally — existing files are silently overwritten.
Evidence: `core/config.resolve` only sandboxes/creates parent dirs; the 8 `.exists()` checks
in the tree are **input** existence checks (e.g. `inspect.render_preview`, `gui.open_in_editor`),
not output guards.
Impact: an agent can silently destroy an existing workspace file (e.g. overwrite a hand-made
`hero.aseprite`). Data-loss risk; worse with `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`.
Recommended fix: an opt-in no-clobber policy — e.g. `ASEPRITE_MCP_NO_CLOBBER=1` and/or an
`overwrite: bool = True` arg on creating/exporting tools that raises `WorkspaceError` when a
target exists and overwrite is disallowed.
Suggested PR: fix/audit-critical-fixes. Coverage: pure (resolve/policy) + `--run-aseprite`
(create/export refuse to clobber).

## Finding: No size limits on op lists / pixel lists
Severity: Medium · Category: Hardening (also Security S-DoS) · Area: batch/drawing · Status: Confirmed

Description: `apply_operations` accepts an unbounded `operations` list; `draw_pixels`,
`draw_polyline`, `draw_brush`, `set_tiles`, `paint_tile_pixels` accept unbounded point/pixel
lists. Only `draw_text` caps output (200k px).
Evidence: `core/oplib.validate_operations` has no length cap; `tools/drawing.py` checks
non-empty but not max.
Impact: a pathological list produces a giant generated Lua script / very long run — a local
DoS / memory spike.
Recommended fix: cap op lists (e.g. 1000) and pixel/point lists (e.g. 100k) with a clear
`ValidationFailed`/`ValueError` naming the limit.
Suggested PR: harden/release-gate-and-property-tests. Coverage: pure (validation).

## Finding: CI does not validate packaging build
Severity: Low · Category: Hardening · Area: CI/packaging · Status: Confirmed

Description: CI runs install/import/pytest/docs-check but never `uv build`, so a packaging
regression (e.g. bad `pyproject`/missing module) is only caught at release time.
Evidence: `.github/workflows/ci.yml` (no build step).
Impact: late discovery of packaging breakage.
Recommended fix: add a `uv build` step (or a dedicated job) to CI.
Suggested PR: harden/release-gate-and-property-tests.

## Finding: CI Python matrix is narrow
Severity: Low · Category: Hardening · Area: CI · Status: Confirmed

Description: matrix is `3.10` + `3.12`; `requires-python = ">=3.10"` implies 3.11/3.13 should
also be sane.
Evidence: `.github/workflows/ci.yml`.
Impact: minor — version-specific issues could slip.
Recommended fix: add `3.11` and `3.13`.
Suggested PR: harden/release-gate-and-property-tests.

## Finding: Temp Lua handling is sound
Severity: Info · Category: Hardening · Area: runner · Status: Confirmed (no issue)

Description: `run_lua` writes the script via `tempfile.mkstemp` (owner-only 0600, system temp)
and unlinks it in a `finally`, including on timeout/exception.
Evidence: `core/runner.run_lua`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.

---

# 3. Security audit

## Finding: Unsafe file overwrite / clobber
Severity: High · Category: Security · Area: config/tools · Status: Confirmed
(See also Hardening "No overwrite policy".)

Description: the file capability handed to the agent can overwrite any existing file in the
workspace (or anywhere, with `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`) with no confirmation.
Impact: silent data loss of user-authored assets.
Recommended fix: no-clobber option (env + per-tool `overwrite` flag) defaulting to a safe
behavior for create/export; document it.
Suggested PR: fix/audit-critical-fixes. Coverage: pure + `--run-aseprite`.

## Finding: Workspace traversal & symlink escape are handled — but untested
Severity: Info · Category: Security · Area: config · Status: Confirmed (no issue) + test gap

Description: `config.resolve` rejects absolute paths and `..` escapes unless opted in, and
computes `(workspace()/p).resolve()` then `Path.relative_to(workspace().resolve())`.
`resolve()` canonicalizes symlinks, so a symlink **inside** the workspace pointing outside
resolves to the external real path and fails the containment check → rejected.
Evidence: `core/config.resolve`; `tests/test_unit.py` covers absolute/`..` rejection but
**no symlink-escape test** exists.
Impact: none currently; a future refactor could regress containment unnoticed.
Recommended fix: add a regression test that creates a symlink inside a temp workspace
pointing outside and asserts `WorkspaceError` (skip where the OS can't create symlinks, e.g.
unprivileged Windows).
Suggested PR: fix/audit-critical-fixes. Coverage: pure-Python (with skip guard).

## Finding: Generated-Lua injection — not exploitable
Severity: Info · Category: Security · Area: luagen · Status: Confirmed (no issue)

Description: every user value (filenames, layer/tag/slice names, colours, batch op args,
text) is serialized through `to_lua`/the `ARG` table, which escapes quotes/backslashes/
control chars; tool/op bodies are static templates. No user string is concatenated into Lua
source.
Evidence: `core/luagen.to_lua`/`assemble_script`; `core/oplib.BATCH_LUA_BODY` reads
`ARG.operations`; `tools/*` build bodies from constant templates + `args`.
Impact: none.
Recommended fix: none; lock it with the `to_lua` property test (H above).
Suggested PR: harden/release-gate-and-property-tests.

## Finding: Subprocess invocation is shell-safe
Severity: Info · Category: Security · Area: runner · Status: Confirmed (no issue)

Description: Aseprite is always invoked with list-form argv (`[exe, "-b", ...]`), never via a
shell, so filenames/args with metacharacters are not interpreted.
Evidence: `core/runner.run_lua`/`run_cli`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.

## Finding: GitHub Actions workflow is under-hardened
Severity: Medium · Category: Security (supply chain) · Area: CI · Status: Confirmed

Description: `ci.yml` has no top-level `permissions:` block (the `GITHUB_TOKEN` defaults to
the repository's setting, which may be read/write) and pins actions to mutable tags
(`actions/checkout@v4`, `astral-sh/setup-uv@v5`) rather than commit SHAs.
Evidence: `.github/workflows/ci.yml`.
Impact: broader-than-needed token scope; a compromised tag could run untrusted action code.
Recommended fix: add `permissions: contents: read` (top-level); optionally pin actions to
SHAs and add Dependabot for actions.
Suggested PR: fix/audit-critical-fixes (permissions) + defer SHA-pinning.

## Finding: No SECURITY.md / documented threat model
Severity: Medium · Category: Security · Area: docs · Status: Confirmed

Description: the project gives an AI agent a sandboxed file+process capability, but the trust
model and reporting process are undocumented.
Evidence: no `SECURITY.md` in the tree.
Impact: users can't reason about the boundary (local, semi-trusted client, workspace
sandbox, BYO-Aseprite, untrusted-file caveat) or report issues.
Recommended fix: add `SECURITY.md` covering: local-only/trusted-host assumption; workspace
sandbox + `ALLOW_ABSOLUTE` opt-in; no shell / no Lua injection; BYO licensed Aseprite;
the caveat that opening untrusted images makes Aseprite parse them; and a reporting contact.
Suggested PR: harden/release-gate-and-property-tests (docs-only). Coverage: none.

## Finding: Opening untrusted source files delegates parsing to Aseprite
Severity: Low · Category: Security · Area: tools (stamp/import/palette/reference) · Status: Info

Description: `stamp_file`, `import_image`, `load_palette`, and the reference tools `app.open`
a user-supplied path, so Aseprite parses a potentially untrusted file. Any parser
vulnerability is in Aseprite, outside this project's control.
Evidence: `tools/image.py`, `tools/export.import_image`, `tools/palette.load_palette`,
`tools/reference.py`.
Impact: low/out-of-scope; worth a documented caveat.
Recommended fix: note it in SECURITY.md.
Suggested PR: harden/release-gate-and-property-tests.

## Finding: Dependency / supply-chain posture
Severity: Low · Category: Security · Area: packaging · Status: Info

Description: dependencies are minimal (`mcp[cli]`, `pillow`, dev `pytest`) and `uv.lock` is
committed (pinned, reproducible). No Dependabot/renovate configured.
Evidence: `pyproject.toml`, `uv.lock`.
Impact: low.
Recommended fix: optionally add Dependabot for pip + actions.
Suggested PR: defer.

---

# Prioritized fix plan

### 1. Must fix before next feature
- **Overwrite / clobber policy** (S-High / H-Med) — prevents silent data loss.
- **GitHub Actions `permissions: contents: read`** (S-Med) — one-line, high value.
- **Symlink-escape regression test** (S, test gap) — locks the sandbox guarantee.

### 2. Should fix soon
- `scripts/release_gate.py` (H-Med).
- Property/fuzz tests for `to_lua`, `parse_color`/`ColorSpec`, `resolve` (H-Med; also locks
  the no-injection guarantee).
- Op-list / pixel-list size limits (H-Med / S-DoS).
- Manifest "serialize every kind" test (B-Med).
- `SECURITY.md` threat model (S-Med, docs).

### 3. Can defer
- README/CONTRIBUTING architecture path drift (B-Low, docs).
- CI `uv build` step + Python 3.11/3.13 matrix (H-Low).
- Action SHA-pinning + Dependabot (S-Low).
- Untrusted-file caveat note (S-Low, folds into SECURITY.md).

### 4. Explicitly safe — no issue found
Batch rollback · dry_run no-launch · typed-error catch compat · core shims/no-cycles ·
workspace path anchor · generated-Lua injection · subprocess shell safety · temp Lua
placement/cleanup.

---

# Recommended branches & test coverage

**`fix/audit-critical-fixes`** (small, confirmed issues + regression tests):
- overwrite/clobber policy → tests: pure (resolve/policy) **+ `--run-aseprite`** (create/export refuse clobber).
- Actions `permissions: contents: read` → no test (CI config).
- symlink-escape guard → test: **pure-Python** (skip if OS can't symlink).

**`harden/release-gate-and-property-tests`** (tooling/tests/docs; no feature behavior change):
- `scripts/release_gate.py` → no test (it is the gate).
- property tests (`hypothesis`, dev dep) for `to_lua` / `parse_color` / `resolve` → **pure**.
- op-list / pixel-list caps → **pure** validation tests.
- "serialize every manifest kind" → **pure**.
- `SECURITY.md` + README/CONTRIBUTING path-drift fix → docs.
- CI `uv build` step + 3.11/3.13 matrix → CI.

Both branches: **no new MCP tools, no public-behavior change, no version bump.** A release
(e.g. v0.6.1) can bundle them once merged, before resuming `feature/godot-export-presets`.
