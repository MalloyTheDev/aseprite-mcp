# Bug / Hardening / Security Audit: aseprite-mcp

> **Status: closed. This is a historical record, not a live list of exploitable problems.**
>
> Every finding below was raised against **v0.6.0** in June 2026. All of the actionable
> ones have since been fixed, and each finding now carries a `Resolution:` line naming the
> PR, file or test that closed it. Nothing on this page describes a weakness that is open
> today, and no finding here is waiting to be filed as an issue.
>
> Kept deliberately: it is the evidence trail for that review, and several design
> decisions (the no-clobber default, the per-call work limits, the `ARG`-table escaping)
> only make sense next to the problem they were a response to. Read it as history.
>
> **For the current security posture, read [SECURITY.md](../../SECURITY.md).** That file,
> not this one, is maintained against the shipping version. The companion
> [AUDIT_ACTION_PLAN.md](AUDIT_ACTION_PLAN.md) has the same eleven items as a one-screen
> table with the PR that closed each.
>
> *Status pass: re-verified against the code and the issue tracker at v0.8.1 (147 tools).
> The eight "confirmed safe" items were each re-checked and still hold; where the code has
> moved on, the finding says so.*

**Scope:** repository at v0.6.0 (`main`). Report-only; no behavior changes. Inspection
covered `core/` (config, runner, luagen, errors, models, manifest, validation, oplib),
`tools/*` (incl. batch), tests, docs, CI, packaging.

**Gate at audit time:** `ruff F,E9` clean · `pytest` 74 passed (pure) · `pytest --run-aseprite`
132 passed · `gen_tool_docs.py --check` in sync (108 tools).

**Headline:** the recent typed-errors / typed-models / core-split / batch work is solid;
the bug audit is mostly *confirmed-OK*. The real, actionable gaps are in **hardening**
(no release-gate script, no property tests, no size limits, no overwrite policy) and
**security posture** (overwrite/clobber, GitHub Actions permissions, missing SECURITY.md,
missing symlink regression test). No Critical/Confirmed-Critical issues found.

**Outcome:** all four hardening gaps and all four security-posture gaps named in that
headline were closed: PR #13 (released v0.6.1), PR #14 (released v0.7.0), and the one
deliberately deferred item in PR #19 (first released in v0.8.0). The per-finding
`Resolution:` lines below give the file or test for each.

---

# 1. Bug audit

## Finding: Batch rollback preserves the on-disk file
Severity: Info · Category: Bug · Area: batch · Status: Confirmed (no issue) · **Re-verified at v0.8.1**

Description: `apply_operations` runs all ops inside `app.transaction(...)` and calls
`save_sprite(spr)` only **after** the transaction returns; any op `error(...)`s out, so
`save_sprite` is never reached and the in-memory transaction rolls back.
Evidence: `core/oplib.py` `BATCH_LUA_BODY` (transaction wraps the op loop; `save_sprite`
is after it); `tests/test_batch.py::test_mid_batch_failure_rolls_back_and_saves_nothing`
asserts the on-disk pixels are unchanged after a mid-batch failure.
Impact: none; behaves as intended.
Recommended fix: none.
Suggested PR: n/a.
Resolution: nothing to fix. Still true: `core/oplib.BATCH_LUA_BODY` and the named test
both still exist and still assert it.

## Finding: dry_run never launches Aseprite
Severity: Info · Category: Bug · Area: batch · Status: Confirmed (no issue) · **Re-verified at v0.8.1**

Description: `apply_operations(..., dry_run=True)` validates via `oplib.validate_operations`
(pure Python) and `return`s the plan **before** any `run_lua`/`run_cli` call.
Evidence: `tools/batch.py` (the `if dry_run:` branch returns before `resolve_path`/`run_lua`);
`tests/test_batch.py::test_dry_run_does_not_touch_file_and_returns_plan`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.
Resolution: nothing to fix. Still true at `tools/batch.py:39` (`apply_operations`), and
the named test still exists.

## Finding: Typed errors preserve legacy catch behavior
Severity: Info · Category: Bug · Area: errors · Status: Confirmed (no issue) · **Re-verified at v0.8.1**

Description: `AsepriteError` is an alias of `AsepriteMCPError`; `AsepriteNotFoundError`
also subclasses `FileNotFoundError`, so existing `except FileNotFoundError`
(`gui.gui_available`, `health.health_check`, `conftest`) and `from aseprite_mcp.runner
import AsepriteError` keep working.
Evidence: `core/errors.py`; `tests/test_errors.py` (alias identity, `FileNotFoundError`
back-compat, runner/CLI/timeout mapping).
Impact: none.
Recommended fix: none. (Note: `AsepriteNotFoundError(FileNotFoundError)` is a deliberate
compat base; a future cleanup may switch those three catch sites to
`AsepriteNotFoundError` and drop the extra base.)
Suggested PR: n/a.
Resolution: nothing to fix, and the deliberate compat base is still deliberate.
`core/errors.py:24` still aliases `AsepriteError = AsepriteMCPError`, and
`core/errors.py:31` still declares `class AsepriteNotFoundError(ConfigError, FileNotFoundError)`
with the comment explaining why. The suggested cleanup has not been taken up, by choice.

## Finding: core shims do not create import cycles / pull in the MCP app
Severity: Info · Category: Bug · Area: core/packaging · Status: Confirmed (no issue) · **Re-verified at v0.8.1**

Description: shims (`aseprite_mcp/{config,luagen,runner,errors}.py`) import only from
`core.*`; `core.*` imports nothing from `tools/` or `app`.
Evidence: `tests/test_imports.py::test_core_does_not_import_mcp_app_or_tools` runs in a
clean interpreter and asserts `aseprite_mcp.app` / `mcp.server.fastmcp` / `aseprite_mcp.tools.*`
are absent from `sys.modules` after importing all of `core`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.
Resolution: nothing to fix. The four shims and the named clean-interpreter test all still
exist, and the test still runs in the default (pure) suite.

## Finding: Workspace path anchor is correct after the core split
Severity: Info · Category: Bug · Area: config · Status: Confirmed (no issue) · **Test gap closed; anchor since changed on purpose**

Description: moving `config.py` into `core/` changed its depth; `PROJECT_ROOT` was updated
`parents[2] → parents[3]`. Verified at runtime: `PROJECT_ROOT == <repo root>` and the
default workspace resolves to `<repo>/workspace` (not `src/workspace`).
Evidence: `core/config.py:PROJECT_ROOT`; runtime check during audit printed
`PROJECT_ROOT: <repo>` / `workspace: <repo>/workspace`.
Impact: none, but there is **no regression test** locking this. (The audit gave this gap
no finding of its own; the hardening section's property-test item is the nearest relative.)
Recommended fix: none for the bug; add a guard test (hardening).
Suggested PR: harden/release-gate-and-property-tests.
Resolution: the test gap is closed, and the behaviour it would have locked has since been
changed deliberately, so read the original claim as true of v0.6.0 only.

* Guard test: `tests/test_path_sandbox.py::test_this_checkout_is_detected_as_a_source_layout`
  asserts the source-checkout default is still `<repo>/workspace`.
* Changed on purpose (issue #54, closed in PR #67): `PROJECT_ROOT` is no longer trusted to
  pick the default workspace. On an installed package `parents[3]` points *inside* the
  Python installation, so `core/config._source_checkout_root` now requires both a `src`
  parent and a real `pyproject.toml`, and `core/config._per_user_workspace` supplies a
  per-user directory otherwise. `PROJECT_ROOT` itself is still `parents[3]`
  (`core/config.py:32`), and its docstring now says where that arithmetic is and is not
  meaningful.

## Finding: README/CONTRIBUTING architecture links point at the back-compat shims
Severity: Low · Category: Bug (docs drift) · Area: docs · Status: **Fixed in PR #14**

Description: the "Project layout" / "Architecture" sections still link
`src/aseprite_mcp/{luagen,runner,config}.py` and describe them as the engine modules.
Those paths are now thin re-export **shims**; the real logic lives in `core/`.
Evidence: `README.md` project-layout list and `CONTRIBUTING.md` architecture section
reference the top-level paths; `git mv` moved the modules to `src/aseprite_mcp/core/`.
Impact: misleading for new contributors; links resolve but to shims.
Recommended fix: update the layout/architecture sections to point at `core/` and mention
the shims exist for back-compat. **Docs-only.**
Suggested PR: harden/release-gate-and-property-tests (bundle docs touch-ups).
Resolution: done as recommended. `CONTRIBUTING.md` now links
`src/aseprite_mcp/core/{luagen,runner,config}.py` and says in the same list that the
top-level `luagen`/`runner`/`config`/`errors` modules are back-compat shims; `README.md`'s
project-layout block now describes `core/` as the engine. No link in either file points at
a shim as if it were the implementation.

## Finding: Only one manifest kind is covered by a JSON-serialization test
Severity: Medium · Category: Bug (latent) · Area: manifest/tests · Status: **Fixed in PR #14**

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
Resolution: done as recommended.
`tests/test_manifest.py::test_every_manifest_kind_serializes` loops over
`manifest.VALID_KINDS` and `json.dumps` each one, so a new kind cannot be added without
being covered.

---

# 2. Hardening audit

## Finding: No executable release-gate script
Severity: Medium · Category: Hardening · Area: tooling/CI · Status: **Fixed in PR #14**

Description: the release gate (ruff → pytest → `--run-aseprite` → docs `--check` → `uv build`)
is documented in `CONTRIBUTING.md` but run by hand each release.
Evidence: `CONTRIBUTING.md` "Local release gate"; no `scripts/release_gate.py`.
Impact: human error risk at release time; no single command.
Recommended fix: add `scripts/release_gate.py` that runs each step and exits non-zero on
the first failure (with a `--run-aseprite` flag passthrough).
Suggested PR: harden/release-gate-and-property-tests. Coverage: tooling (no test needed; it
*is* the gate).
Resolution: done as recommended. `scripts/release_gate.py` runs ruff, `pytest`,
`pytest --run-aseprite`, `gen_tool_docs.py --check` and `uv build` in that order and stops
at the first failure; the flag is a `--skip-aseprite` opt-out rather than an opt-in.
`CONTRIBUTING.md` now opens its "Local release gate" section with that one command.

## Finding: No property/fuzz tests for serializers/parsers/path resolution
Severity: Medium · Category: Hardening · Area: luagen/models/config/tests · Status: **Fixed in PR #14**

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
Resolution: done as recommended, with `hypothesis>=6` added to the dev group.
`tests/test_properties.py` covers all three boundaries, and goes further than the
recommendation on the first one: rather than pattern-matching the output it decodes each
generated literal with an independent scanner, so a string that round-trips has *provably*
stayed inside its quotes. `parse_color`/`ColorSpec.parse` are fuzzed for "never raises
anything but `ValueError`, channels always 0 to 255", and `config.resolve` /
`ensure_output_path` for "resolves inside the workspace or is rejected, never escapes".

## Finding: No overwrite / clobber policy
Severity: Medium · Category: Hardening (also Security S-Clobber) · Area: config/tools · Status: **Fixed in PR #13, extended in PR #47**

Description: `create_sprite`, `save_sprite_as`, all `export_*`, `import_image`, and the batch
save write to the resolved path unconditionally; existing files are silently overwritten.
Evidence: `core/config.resolve` only sandboxes/creates parent dirs; the 8 `.exists()` checks
in the tree are **input** existence checks (e.g. `inspect.render_preview`, `gui.open_in_editor`),
not output guards.
Impact: an agent can silently destroy an existing workspace file (e.g. overwrite a hand-made
`hero.aseprite`). Data-loss risk; worse with `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`.
Recommended fix: an opt-in no-clobber policy, e.g. `ASEPRITE_MCP_NO_CLOBBER=1` and/or an
`overwrite: bool = True` arg on creating/exporting tools that raises `WorkspaceError` when a
target exists and overwrite is disallowed.
Suggested PR: fix/audit-critical-fixes. Coverage: pure (resolve/policy) + `--run-aseprite`
(create/export refuse to clobber).
Resolution: fixed, and settled **safer than this recommendation asked for**. The policy is
not opt-in and there is no `ASEPRITE_MCP_NO_CLOBBER` env var: no-clobber is the default and
`overwrite` defaults to `False` on every output-writing tool, so the opt-in is to *allow*
the overwrite rather than to prevent it.

* `core/paths.ensure_output_path(path, *, overwrite=False, create_parent=True,
  error_type=WorkspaceError)` is the single chokepoint: it resolves through
  `config.resolve` and raises if the target exists and `overwrite` is False.
* Coverage is as suggested: `tests/test_output_paths.py` (pure) and
  `tests/test_overwrite.py` (`--run-aseprite`, including that a multi-file bundle export
  fails before writing anything).
* PR #13 covered create/save/export; PR #47 brought the remaining output paths onto
  `ensure_output_path`, which is why `SECURITY.md` dates the policy to two releases.

## Finding: No size limits on op lists / pixel lists
Severity: Medium · Category: Hardening (also Security S-DoS) · Area: batch/drawing · Status: **Fixed in PR #14, extended in PRs #47 and #49**

Description: `apply_operations` accepts an unbounded `operations` list; `draw_pixels`,
`draw_polyline`, `draw_brush`, `set_tiles`, `paint_tile_pixels` accept unbounded point/pixel
lists. Only `draw_text` caps output (200k px).
Evidence: `core/oplib.validate_operations` has no length cap; `tools/drawing.py` checks
non-empty but not max.
Impact: a pathological list produces a giant generated Lua script / very long run, a local
DoS / memory spike.
Recommended fix: cap op lists (e.g. 1000) and pixel/point lists (e.g. 100k) with a clear
`ValidationFailed`/`ValueError` naming the limit.
Suggested PR: harden/release-gate-and-property-tests. Coverage: pure (validation).
Resolution: fixed, and the idea grew into its own module. `core/limits.py` holds the caps
and the `check_list_length` helper; `core/oplib.validate_operations` applies
`MAX_BATCH_OPERATIONS` (500) to the op list and `MAX_PIXEL_LIST_LENGTH` (65,536) to
pixel/point args, both tighter than the round numbers suggested here.
Coverage is `tests/test_limits.py` (pure), which checks each cap *at* its ceiling with the
Lua runner stubbed, so an at-the-cap call genuinely succeeds instead of merely failing for
another reason.

Later work widened the same idea past collection lengths, to the class of bug where one
small integer buys unbounded work: scalar loop bounds and repetition counts (issues #57,
#58, #59), process-output capture, image rasters and text budgets (PRs #47 and #49).

## Finding: CI does not validate packaging build
Severity: Low · Category: Hardening · Area: CI/packaging · Status: **Fixed in PR #14**

Description: CI runs install/import/pytest/docs-check but never `uv build`, so a packaging
regression (e.g. bad `pyproject`/missing module) is only caught at release time.
Evidence: `.github/workflows/ci.yml` (no build step).
Impact: late discovery of packaging breakage.
Recommended fix: add a `uv build` step (or a dedicated job) to CI.
Suggested PR: harden/release-gate-and-property-tests.
Resolution: done as recommended. `.github/workflows/ci.yml` ends with a
`Build wheel + sdist` step running `uv build`, and `scripts/release_gate.py` runs the same
step locally.

## Finding: CI Python matrix is narrow
Severity: Low · Category: Hardening · Area: CI · Status: **Fixed in PR #14**

Description: matrix is `3.10` + `3.12`; `requires-python = ">=3.10"` implies 3.11/3.13 should
also be sane.
Evidence: `.github/workflows/ci.yml`.
Impact: minor; version-specific issues could slip.
Recommended fix: add `3.11` and `3.13`.
Suggested PR: harden/release-gate-and-property-tests.
Resolution: done as recommended. The matrix in `.github/workflows/ci.yml` is now
`["3.10", "3.11", "3.12", "3.13"]`, covering all of `requires-python = ">=3.10"`.

## Finding: Temp Lua handling is sound
Severity: Info · Category: Hardening · Area: runner · Status: Confirmed (no issue) · **Re-verified at v0.8.1**

Description: `run_lua` writes the script via `tempfile.mkstemp` (owner-only 0600, system temp)
and unlinks it in a `finally`, including on timeout/exception.
Evidence: `core/runner.run_lua`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.
Resolution: nothing to fix. Still true at `core/runner.py:175`
(`tempfile.mkstemp(suffix=".lua", prefix="asemcp_")`) with the `os.unlink` in a `finally`
at `core/runner.py:185`.

---

# 3. Security audit

## Finding: Unsafe file overwrite / clobber
Severity: High · Category: Security · Area: config/tools · Status: **Fixed in PR #13, extended in PR #47**
(See also Hardening "No overwrite policy".)

Description: the file capability handed to the agent can overwrite any existing file in the
workspace (or anywhere, with `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`) with no confirmation.
Impact: silent data loss of user-authored assets.
Recommended fix: no-clobber option (env + per-tool `overwrite` flag) defaulting to a safe
behavior for create/export; document it.
Suggested PR: fix/audit-critical-fixes. Coverage: pure + `--run-aseprite`.
Resolution: fixed. See the Hardening entry above for the mechanism
(`core/paths.ensure_output_path`, no-clobber by default). It is documented in
[SECURITY.md](../../SECURITY.md) under *Protections in place* ("No-clobber output") and on
the README feature list, and the residual risk is stated plainly under *Out of scope*: the
agent may still overwrite a workspace file when the caller passes `overwrite=True`.

## Finding: Workspace traversal & symlink escape are handled, but untested
Severity: Info · Category: Security · Area: config · Status: Confirmed (no issue) · **Test gap fixed in PR #13; widened later**

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
Resolution: the test was added as recommended, and writing it was worth more than the one
test, because the containment guarantee this finding rated "handled" turned out to be
**incomplete in three ways the audit missed**. All three are now closed; recorded here so
the Info rating is not read as a clean bill of health for v0.6.0.

* As recommended: `tests/test_output_paths.py::test_symlink_escape_rejected`, with
  `test_symlink_within_workspace_allowed` beside it so the guard is not just "reject
  everything". `_make_symlink` skips where the OS refuses. CI follow-up in PR #18.
* **Junctions were not symlinks.** `Path.is_symlink()` is False for an NTFS junction, so
  directory walks went straight through one: `list_sprites` could list files outside the
  workspace. Fixed and covered by
  `tests/test_path_sandbox.py::test_list_sprites_does_not_follow_a_junction_out_of_the_workspace`,
  with the POSIX mirror at `test_list_sprites_does_not_follow_a_symlink_out_of_the_workspace`.
* **A read created directories.** `config.resolve` created parent directories
  unconditionally, so resolving a path that turned out not to exist left the folders
  behind. `create_parent` now defaults to False and only the output helper passes True.
* **The permissive branch skipped canonicalisation.** Under
  `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`, `resolve` returned a path still containing `..`
  segments, which then reached manifests and `mkdir` verbatim. Both branches now call
  `.resolve()`; covered by `tests/test_path_sandbox.py::test_permissive_branch_canonicalises`
  and `test_permissive_relative_paths_still_anchor_on_the_workspace`.

Those three came out of issues #55 and #56, closed in PR #67, and are described in
[SECURITY.md](../../SECURITY.md) under *Protections in place*. Windows-hostile components
(reserved device names, alternate data streams, trailing dots) were closed in the same
pass; `core/config._check_component` is the guard.

## Finding: Generated-Lua injection, not exploitable
Severity: Info · Category: Security · Area: luagen · Status: Confirmed (no issue) · **Re-verified at v0.8.1; since strengthened**

Description: every user value (filenames, layer/tag/slice names, colours, batch op args,
text) is serialized through `to_lua`/the `ARG` table, which escapes quotes/backslashes/
control chars; tool/op bodies are static templates. No user string is concatenated into Lua
source.
Evidence: `core/luagen.to_lua`/`assemble_script`; `core/oplib.BATCH_LUA_BODY` reads
`ARG.operations`; `tools/*` build bodies from constant templates + `args`.
Impact: none.
Recommended fix: none; lock it with the `to_lua` property test (H above).
Suggested PR: harden/release-gate-and-property-tests.
Resolution: still holds, and it is now locked as recommended. The property test in
`tests/test_properties.py` decodes each generated literal with an independent scanner, so a
value that round-trips provably never left its quotes.

A second, adjacent channel the audit did not consider has also been closed. Results were
framed on stdout by a **fixed** sentinel (`@@ASEMCP@@`), and the runner recognised any line
starting with it as protocol, so a caller-supplied string that reached stdout (a layer name,
a tag, a filename) could claim to *be* a result. `core/luagen.new_nonce` now generates a
per-run token and the sentinels are `@@ASEMCP:<nonce>@@` / `@@ASEMCP_ERR:<nonce>@@`. The
payload is serialized before the nonce exists and never contains it, so it cannot name the
token it would have to forge. Escaping the line terminators is still done, as defence in
depth rather than as the only guard.

## Finding: Subprocess invocation is shell-safe
Severity: Info · Category: Security · Area: runner · Status: Confirmed (no issue) · **Re-verified at v0.8.1; since strengthened**

Description: Aseprite is always invoked with list-form argv (`[exe, "-b", ...]`), never via a
shell, so filenames/args with metacharacters are not interpreted.
Evidence: `core/runner.run_lua`/`run_cli`.
Impact: none.
Recommended fix: none.
Suggested PR: n/a.
Resolution: still holds. No `shell=True` and no `os.system` anywhere in `src/`; the two
launch sites are `core/runner.py:119` (`subprocess.Popen(argv, ...)`, argv built as
`[exe, "-b", "--script", path]` or `[exe, "-b", *cli_args]`) and `tools/gui.py:67`
(`[exe, str(path)]`).

Two things were added here afterwards, neither correcting this finding. The child now gets
`stdin=subprocess.DEVNULL`, because under the stdio transport it would otherwise inherit
the client's JSON-RPC stream. And output capture is bounded
(`core/limits.MAX_PROCESS_OUTPUT_CHARS`, read on two threads to avoid a pipe deadlock)
rather than accumulated whole, which is the subprocess half of the size-limits finding.

## Finding: GitHub Actions workflow is under-hardened
Severity: Medium · Category: Security (supply chain) · Area: CI · Status: **Fixed in PRs #13 and #19**

Description: `ci.yml` has no top-level `permissions:` block (the `GITHUB_TOKEN` defaults to
the repository's setting, which may be read/write) and pins actions to mutable tags
(`actions/checkout@v4`, `astral-sh/setup-uv@v5`) rather than commit SHAs.
Evidence: `.github/workflows/ci.yml`.
Impact: broader-than-needed token scope; a compromised tag could run untrusted action code.
Recommended fix: add `permissions: contents: read` (top-level); optionally pin actions to
SHAs and add Dependabot for actions.
Suggested PR: fix/audit-critical-fixes (permissions) + defer SHA-pinning.
Resolution: fixed, including the part that was deferred.
`.github/workflows/ci.yml` has a top-level `permissions: contents: read` (PR #13), and both
actions are pinned to commit SHAs with the version in a trailing comment, with
`.github/dependabot.yml` keeping them current (PR #19). A `.github/workflows/codeql.yml`
workflow arrived later still, in PR #47, beyond what this finding asked for.

## Finding: No SECURITY.md / documented threat model
Severity: Medium · Category: Security · Area: docs · Status: **Fixed in PR #14**

Description: the project gives an AI agent a sandboxed file+process capability, but the trust
model and reporting process are undocumented.
Evidence: no `SECURITY.md` in the tree.
Impact: users can't reason about the boundary (local, semi-trusted client, workspace
sandbox, BYO-Aseprite, untrusted-file caveat) or report issues.
Recommended fix: add `SECURITY.md` covering: local-only/trusted-host assumption; workspace
sandbox + `ALLOW_ABSOLUTE` opt-in; no shell / no Lua injection; BYO licensed Aseprite;
the caveat that opening untrusted images makes Aseprite parse them; and a reporting contact.
Suggested PR: harden/release-gate-and-property-tests (docs-only). Coverage: none.
Resolution: fixed. [SECURITY.md](../../SECURITY.md) exists with *Supported versions*,
*Threat model*, *Protections in place*, *Out of scope (your responsibility)* and *Reporting
a vulnerability* (private GitHub advisory). It covers every item on the list above: the
local/semi-trusted-client assumption, the workspace sandbox and the `ALLOW_ABSOLUTE`
opt-out, no shell and no Lua injection, bring-your-own Aseprite, and the reporting route.
It is maintained against the shipping release, which is why it, not this file, is the place
to look for current posture.

## Finding: Opening untrusted source files delegates parsing to Aseprite
Severity: Low · Category: Security · Area: tools (stamp/import/palette/reference) · Status: Info · **Accepted; documented as out of scope**

Description: `stamp_file`, `import_image`, `load_palette`, and the reference tools `app.open`
a user-supplied path, so Aseprite parses a potentially untrusted file. Any parser
vulnerability is in Aseprite, outside this project's control.
Evidence: `tools/image.py`, `tools/export.import_image`, `tools/palette.load_palette`,
`tools/reference.py`.
Impact: low/out-of-scope; worth a documented caveat.
Recommended fix: note it in SECURITY.md.
Suggested PR: harden/release-gate-and-property-tests.
Resolution: accepted rather than fixed, which is the right outcome: the risk is in
Aseprite's own file parsers and cannot be fixed here. All four call sites still open a
user-supplied path (`tools/image.stamp_file`, `tools/export.import_image`,
`tools/palette.load_palette`, `tools/reference.py`).

Documented in [SECURITY.md](../../SECURITY.md) by scope rather than by caveat: the threat
model states the server "does not sandbox the Aseprite binary itself or the contents you
place in the workspace", and *Out of scope* assigns both the workspace contents ("use as an
import source") and the Aseprite binary to the operator.

## Finding: Dependency / supply-chain posture
Severity: Low · Category: Security · Area: packaging · Status: Info · **Dependabot added in PR #19**

Description: dependencies are minimal (`mcp[cli]`, `pillow`, dev `pytest`) and `uv.lock` is
committed (pinned, reproducible). No Dependabot/renovate configured.
Evidence: `pyproject.toml`, `uv.lock`.
Impact: low.
Recommended fix: optionally add Dependabot for pip + actions.
Suggested PR: defer.
Resolution: the optional part was taken up: `.github/dependabot.yml` was added in PR #19.
`uv.lock` is still committed. The runtime dependency list has grown by one since this
finding: `pydantic>=2` is declared explicitly because the tool layer imports
`BeforeValidator` directly, though it was already arriving via `mcp`. The dev group is now
`pytest`, `hypothesis` and `ruff`.

---

# Prioritized fix plan

**Every item in this plan is done.** It is kept as written, with the landing noted on each
line, so the order the work was actually taken in stays legible.

### 1. Must fix before next feature
- **Overwrite / clobber policy** (S-High / H-Med): prevents silent data loss. *Done: PR #13, completed PR #47.*
- **GitHub Actions `permissions: contents: read`** (S-Med): one-line, high value. *Done: PR #13.*
- **Symlink-escape regression test** (S, test gap): locks the sandbox guarantee. *Done: PR #13; widened in PR #67.*

### 2. Should fix soon
- `scripts/release_gate.py` (H-Med). *Done: PR #14.*
- Property/fuzz tests for `to_lua`, `parse_color`/`ColorSpec`, `resolve` (H-Med; also locks
  the no-injection guarantee). *Done: PR #14.*
- Op-list / pixel-list size limits (H-Med / S-DoS). *Done: PR #14; extended in PRs #47, #49.*
- Manifest "serialize every kind" test (B-Med). *Done: PR #14.*
- `SECURITY.md` threat model (S-Med, docs). *Done: PR #14.*

### 3. Can defer
- README/CONTRIBUTING architecture path drift (B-Low, docs). *Done: PR #14.*
- CI `uv build` step + Python 3.11/3.13 matrix (H-Low). *Done: PR #14.*
- Action SHA-pinning + Dependabot (S-Low). *Done: PR #19.*
- Untrusted-file caveat note (S-Low, folds into SECURITY.md). *Done: PR #14, by scope.*

### 4. Explicitly safe: no issue found
Batch rollback · dry_run no-launch · typed-error catch compat · core shims/no-cycles ·
workspace path anchor · generated-Lua injection · subprocess shell safety · temp Lua
placement/cleanup.

All eight were re-checked against the code at v0.8.1 and all eight still hold. Three have
footnotes worth reading above rather than taking from this list: the **workspace path
anchor** no longer picks the default workspace on an installed layout (issue #54, by
design), **generated-Lua injection** also had a sentinel-forgery channel that this audit
did not consider (now closed by a per-run nonce), and the **symlink** guarantee was
incomplete for NTFS junctions (now closed). Nothing in that list is a current weakness.

---

# Recommended branches & test coverage

Both branches were taken as planned and are merged: `fix/audit-critical-fixes` as PR #13
(released v0.6.1) and `harden/release-gate-and-property-tests` as PR #14 (released v0.7.0).
The deferred SHA-pinning followed on `harden/action-sha-pins-dependabot` as PR #19.

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

One part of that held and one did not. No new MCP tools were added, and the tool count was
unchanged across both branches. But the no-clobber policy *is* a public-behavior change:
output-writing tools that used to replace a file now refuse unless the caller passes
`overwrite=True`. It shipped as v0.6.1 rather than as a patch to v0.6.0 for that reason.
`feature/godot-export-presets` was resumed afterwards and landed as PR #15.
