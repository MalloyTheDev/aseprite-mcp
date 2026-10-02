# Audit Action Plan (at a glance)

> **Status: closed. Historical record, not a live queue.**
> This was the ranked work list coming out of the v0.6.0 audit (June 2026). All eleven
> items have since landed; the "Landed in" column cites the PR for each one. Nothing on
> this page is an open action, and nothing on it describes a current weakness. It is kept
> as the audit trail for that review. For the project's present security posture, read
> [SECURITY.md](../../SECURITY.md) instead.

Companion to [BUG_HARDEN_SECURITY_AUDIT.md](BUG_HARDEN_SECURITY_AUDIT.md). Report-only
when it was written: none of it was implemented at the time the queue was drawn up.

## TL;DR
The v0.6.0 code is clean: **no Critical/High *bugs***, and all "did the recent refactors
break anything?" checks come back confirmed-OK. The actionable work is **safety posture +
hardening**, not bug-fixing.

## Ranked queue

All eleven are **done**. "Landed in" is the PR that closed the item.

| # | Item | Sev | Branch | Coverage | Landed in |
|---|------|-----|--------|----------|-----------|
| 1 | Overwrite/clobber policy (no-clobber opt-in + `overwrite` flag) | High (sec) | `fix/audit-critical-fixes` | pure + `--run-aseprite` | PR #13 (`core/paths.py`, `tests/test_overwrite.py`); extended in PR #47 |
| 2 | GitHub Actions `permissions: contents: read` | Med (sec) | `fix/audit-critical-fixes` | CI config | PR #13 (`.github/workflows/ci.yml`) |
| 3 | Symlink-escape regression test | Info+gap (sec) | `fix/audit-critical-fixes` | pure (skip if no symlink) | PR #13 (`tests/test_output_paths.py::test_symlink_escape_rejected`); CI follow-up PR #18 |
| 4 | `scripts/release_gate.py` | Med (harden) | `harden/release-gate-and-property-tests` | tooling | PR #14 (`scripts/release_gate.py`) |
| 5 | Property tests: `to_lua` / `parse_color` / `resolve` | Med (harden+sec) | `harden/…` | pure | PR #14 (`tests/test_properties.py`, `hypothesis` dev dep) |
| 6 | Op-list / pixel-list size limits | Med (harden/DoS) | `harden/…` | pure | PR #14 (`core/limits.py`, `tests/test_limits.py`) |
| 7 | "serialize every manifest kind" test | Med (bug latent) | `harden/…` | pure | PR #14 (`tests/test_manifest.py::test_every_manifest_kind_serializes`) |
| 8 | `SECURITY.md` threat model | Med (sec) | `harden/…` | docs | PR #14 ([SECURITY.md](../../SECURITY.md)) |
| 9 | README/CONTRIBUTING path drift (core split) | Low (docs) | `harden/…` | docs | PR #14 (both now link `src/aseprite_mcp/core/`) |
| 10 | CI: `uv build` step + 3.11/3.13 matrix | Low (harden) | `harden/…` | CI | PR #14 (matrix is now 3.10 to 3.14, plus a `uv build` step) |
| 11 | Action SHA-pinning + Dependabot | Low (sec) | defer | CI | PR #19 (deferred, then done: `.github/dependabot.yml`) |

## Suggested sequence
This is what was planned, and it is what happened.

1. `fix/audit-critical-fixes` → items 1–3 → small PR → (optional) **v0.6.1**.
   *Done:* PR #13, released as v0.6.1.
2. `harden/release-gate-and-property-tests` → items 4–10 → PR.
   *Done:* PR #14, released as v0.7.0. Item 11 followed in PR #19 (first released v0.8.0).
3. Resume `feature/godot-export-presets`. *Done:* PR #15.

## No-issue / confirmed safe (do not "fix")
batch rollback · dry_run no-launch · typed-error catch compat · core shims & no import
cycles · workspace path anchor (`PROJECT_ROOT` parents[3]) · generated-Lua injection ·
subprocess shell safety · temp Lua placement/cleanup.

Each of these was re-checked against the code during the status pass that added this
banner, and each still holds. Two have since been strengthened beyond what the audit
described, and one changed on purpose; see the matching findings in
[BUG_HARDEN_SECURITY_AUDIT.md](BUG_HARDEN_SECURITY_AUDIT.md) for which and why.
