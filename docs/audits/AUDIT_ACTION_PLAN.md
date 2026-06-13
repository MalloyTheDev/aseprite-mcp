# Audit Action Plan (at a glance)

Companion to [BUG_HARDEN_SECURITY_AUDIT.md](BUG_HARDEN_SECURITY_AUDIT.md). Report-only —
nothing here is implemented yet.

## TL;DR
The v0.6.0 code is clean: **no Critical/High *bugs***, and all "did the recent refactors
break anything?" checks come back confirmed-OK. The actionable work is **safety posture +
hardening**, not bug-fixing.

## Ranked queue

| # | Item | Sev | Branch | Coverage |
|---|------|-----|--------|----------|
| 1 | Overwrite/clobber policy (no-clobber opt-in + `overwrite` flag) | High (sec) | `fix/audit-critical-fixes` | pure + `--run-aseprite` |
| 2 | GitHub Actions `permissions: contents: read` | Med (sec) | `fix/audit-critical-fixes` | CI config |
| 3 | Symlink-escape regression test | Info+gap (sec) | `fix/audit-critical-fixes` | pure (skip if no symlink) |
| 4 | `scripts/release_gate.py` | Med (harden) | `harden/release-gate-and-property-tests` | tooling |
| 5 | Property tests: `to_lua` / `parse_color` / `resolve` | Med (harden+sec) | `harden/…` | pure |
| 6 | Op-list / pixel-list size limits | Med (harden/DoS) | `harden/…` | pure |
| 7 | "serialize every manifest kind" test | Med (bug latent) | `harden/…` | pure |
| 8 | `SECURITY.md` threat model | Med (sec) | `harden/…` | docs |
| 9 | README/CONTRIBUTING path drift (core split) | Low (docs) | `harden/…` | docs |
| 10 | CI: `uv build` step + 3.11/3.13 matrix | Low (harden) | `harden/…` | CI |
| 11 | Action SHA-pinning + Dependabot | Low (sec) | defer | CI |

## Suggested sequence
1. `fix/audit-critical-fixes` → items 1–3 → small PR → (optional) **v0.6.1**.
2. `harden/release-gate-and-property-tests` → items 4–10 → PR.
3. Resume `feature/godot-export-presets`.

## No-issue / confirmed safe (do not "fix")
batch rollback · dry_run no-launch · typed-error catch compat · core shims & no import
cycles · workspace path anchor (`PROJECT_ROOT` parents[3]) · generated-Lua injection ·
subprocess shell safety · temp Lua placement/cleanup.
