# Security Policy

## Supported versions

Security fixes target the latest released `0.6.x` line and `main`. Older tags are not
patched — upgrade to the newest release.

## Threat model

`aseprite-mcp` hands an AI agent (or any MCP client) two capabilities:

1. a **file capability** — it reads and writes image/sprite files, and
2. the ability to **run a local Aseprite binary** with generated Lua scripts.

The agent's instructions are treated as **untrusted input**. The design goal is that a
misbehaving or prompt-injected agent cannot escape the workspace, clobber arbitrary files,
inject code into the Aseprite process, or exhaust the host with a single oversized call.
It explicitly does **not** sandbox the Aseprite binary itself or the contents you place in
the workspace — see *Out of scope* below.

## Protections in place

- **Workspace sandbox.** Relative paths resolve under `ASEPRITE_MCP_WORKSPACE`. Absolute
  paths, `..` escapes, and symlinks that point outside the workspace are **rejected**
  (`config.resolve` calls `.resolve()` before checking containment). Opt out only with
  `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`.
- **No-clobber output (v0.6.1+).** Output-writing tools refuse to overwrite an existing
  file unless `overwrite=True`; multi-file exports validate every target before writing
  any of them.
- **No shell, no Lua injection.** Aseprite is invoked with list-form arguments (never a
  shell string). Every user value is passed into generated Lua through an **escaped `ARG`
  table** — user input is never concatenated into Lua source. The `to_lua` escaping is
  covered by Hypothesis property tests asserting strings can't break out of their literal.
- **Size limits (DoS guard, v0.6.x+).** Batch op-lists and pixel/tile/colour lists are
  capped (`core/limits.py`); exceeding a cap raises `ValidationFailed` before any work
  begins, with a message explaining how to split the request.
- **Timeouts.** Every Aseprite invocation runs under `ASEPRITE_MCP_TIMEOUT` (default 90s).
- **Bring your own Aseprite.** The server only executes the Aseprite binary you point it
  at via `ASEPRITE_PATH` / PATH.
- **Least-privilege CI.** The GitHub Actions workflow runs with `permissions: contents: read`.

## Out of scope (your responsibility)

- **Contents of the workspace.** Anything already in `ASEPRITE_MCP_WORKSPACE` is fair game
  for the agent to read, modify (with `overwrite=True`), or use as an import source.
- **`ASEPRITE_MCP_ALLOW_ABSOLUTE=1`.** Setting this **disables the path sandbox** by design.
  Only enable it when you trust the caller.
- **The Aseprite binary and any custom Lua/extensions** you install into it.
- **Transport/host security** of however you run the MCP server (stdio/socket, the machine,
  and the client connecting to it).

## Reporting a vulnerability

Please report security issues **privately**, not via a public issue:

- Use GitHub's **“Report a vulnerability”** button on the repository’s **Security** tab
  (Security → Advisories → Report a vulnerability), which opens a private advisory.

Include a description, affected version/commit, and a minimal reproduction if possible.
We aim to acknowledge within a few days and will coordinate a fix and disclosure timeline
with you.
