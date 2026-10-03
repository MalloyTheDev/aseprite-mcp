# Security Policy

## Supported versions

Security fixes target the latest released `0.10.x` line and `main`. Older tags are not
patched; upgrade to the newest release. This line is part of the policy rather than a
changelog entry, so it moves with each minor release: it still said `0.9.x` after
v0.10.0 shipped, which left a reader unable to tell which line was actually patched.

## Threat model

`aseprite-mcp` hands an AI agent (or any MCP client) two capabilities:

1. a **file capability**: it reads and writes image/sprite files, and
2. the ability to **run a local Aseprite binary** with generated Lua scripts.

The agent's instructions are treated as **untrusted input**. The design goal is that a
misbehaving or prompt-injected agent cannot escape the workspace, clobber arbitrary files,
inject code into the Aseprite process, or exhaust the host with a single oversized call.
It explicitly does **not** sandbox the Aseprite binary itself or the contents you place in
the workspace; see *Out of scope* below.

One consequence is worth stating outright rather than leaving to be assembled from those
two exclusions: **image parsing happens in Aseprite, not here.** Opening, importing or
stamping a file hands it to Aseprite's own decoders. The size and dimension guards below
bound how much work a file can cause, not whether a decoder handles it correctly, and the
pre-stamp header check reads dimensions with Pillow only for formats Pillow recognizes, so
for Aseprite's native `.aseprite`/`.ase` it makes no claim at all. A malformed or hostile
image is therefore parsed by Aseprite with whatever robustness Aseprite has. Treat putting
a file you do not trust into the workspace as handing it to that parser.

## Protections in place

- **Workspace sandbox.** Relative paths resolve under `ASEPRITE_MCP_WORKSPACE`, and under
  it only: they are joined to the workspace on both the default and the
  `ASEPRITE_MCP_ALLOW_ABSOLUTE=1` branch, never to the process working directory. Absolute
  paths, `..` escapes, and symlinks that point outside the workspace are **rejected**
  (`config.resolve` calls `.resolve()` before checking containment, and now does so on the
  permissive branch too, so a returned path never still contains `..`). Opt out only with
  `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`.
  - **Junctions, and directory listings (v0.8.0).** An NTFS junction is not a symlink to
    Python (`Path.is_symlink()` is False), so through v0.7.0 `list_sprites` walked through
    one and reported filenames and byte sizes from outside the workspace. It now re-checks
    every directory and every file with `os.path.realpath` before including it, which also
    stops a junction aimed at a drive root from walking the drive. Opening those paths was
    always refused, so the exposure was names and sizes, not content.
  - **No directory creation on reads (v0.8.0).** `config.resolve` no longer creates the
    parent directory; only the output helpers (`core/paths.py`) do, via
    `create_parent=True`. Through v0.7.0 a read of `a/b/c/d/e/absent.png` left five
    directories behind, so a caller could build arbitrary trees inside the workspace out of
    nothing but failing calls.
  - **Windows-hostile path components (v0.8.0).** On Windows, each component of a caller
    path is rejected if it is a reserved device name (`NUL`, `CON`, `COM1`, `LPT1`, ...,
    checked on the stem so `NUL.png` is refused too), contains `:` (an NTFS alternate data
    stream, which is invisible to every listing and export tool here), or ends with a space
    or a dot (Windows strips those, so the path reported back would not be the path on
    disk). On every platform, input that names no file (empty, `.`, `a/..`) is rejected
    instead of silently resolving to the workspace directory. A write to `NUL` previously
    succeeded, wrote nothing, and reported the path as created.
  - **Null bytes (v0.8.0).** A filename containing `\x00` is rejected explicitly, on every
    platform, before anything touches it. Through Python 3.12 an embedded NUL made
    `Path.resolve()` raise and the sandbox failed closed as a side effect; 3.13 resolves
    such a path without complaint, so on the newest interpreter the project supports the
    guard had already stopped holding. It is now a check of its own rather than a
    standard-library implementation detail.
  - **What containment cannot see: hard links.** The check canonicalises with
    `.resolve()` and then tests containment, which is what catches a symlink or a
    junction aimed out of the workspace. A **hard link** is not that kind of indirection:
    it is a second name for the same file, with no link target to resolve, so a hard link
    placed inside the workspace pointing at a file elsewhere on the same volume reads and
    writes that file and no path-based check can tell. This is stated rather than fixed
    because it cannot be fixed at the path layer, and because placing one there already
    requires write access to the workspace, which *Out of scope* below treats as trusted.
    It is worth naming so that "nothing outside the workspace" is not read as a stronger
    claim than it is. Measured: `os.link` into the workspace needs no privilege on NTFS,
    and `config.resolve` accepts the resulting name as contained, which it is.
- **Workspace default (v0.8.0).** With `ASEPRITE_MCP_WORKSPACE` unset, the default is a
  sibling `workspace/` directory *only* when the package runs from a source checkout.
  Installed (`uvx aseprite-mcp`), it is a per-user data directory
  (`%LOCALAPPDATA%`, `~/Library/Application Support`, `$XDG_DATA_HOME`); through v0.7.0 the
  same path arithmetic aimed it inside the Python installation. An unusable workspace
  raises `WorkspaceError` naming `ASEPRITE_MCP_WORKSPACE`, never a raw `PermissionError`.
- **No-clobber output (v0.6.1+, completed in v0.8.0).** Every output-writing tool refuses
  to overwrite an existing file unless `overwrite=True`; multi-file exports validate every
  target before writing any of them. Pattern exports (`frames/walk_{frame}.png`) are
  expanded by Aseprite itself, so they are checked against everything the pattern could
  match. `export_minecraft_texture` was the last exception to the "validate every target
  first" half: it wrote the PNG and only then checked the `.png.mcmeta` sidecar, leaving
  half a texture behind when the sidecar was the conflict. (Through v0.7.0, six tools
  bypassed this and wrote silently: `export_layer`,
  `export_layers`, `export_tags`, `export_frames`, `export_onion_skin`, `import_image`.)
- **No shell, no Lua injection.** Aseprite is invoked with list-form arguments (never a
  shell string). Every user value is passed into generated Lua through an **escaped `ARG`
  table**: user input is never concatenated into Lua source. The `to_lua` escaping is
  covered by Hypothesis property tests asserting strings can't break out of their literal.
- **Size limits (DoS guard, v0.7.0+).** Batch op-lists and pixel/tile/colour lists are
  capped (`core/limits.py`); exceeding a cap raises `ValidationFailed` before any work
  begins, with a message explaining how to split the request. Since v0.8.0 the same module
  also bounds **canvas geometry** (16384px per axis *and* 16,777,216 pixels of area, so a
  pair of individually-legal axes can't add up to gigabytes), **inline base64 images**
  (32 MB **and** their declared raster dimensions, so a compressed decompression bomb
  cannot slip past a byte cap), **text rasterization** (budgeted while rendering, not
  after), **aggregate cel area** when scaling a sprite, and Aseprite's output, which is
  drained into a bounded buffer as it is read rather than captured whole and trimmed
  afterwards.
  - **Drawing extents.** A shape's cost is the extent it was given, not the canvas it
    lands on: the prelude's `img_set` discards an off-canvas write, but only after the
    loop has already run, so the canvas caps above do not bound it. The shared drawing
    primitives in `core/luagen.py` (`draw_rect_img`, `ellipse_offsets`,
    `bresenham_points`, `draw_line_img`, and both anti-aliased variants) therefore refuse
    an extent past `MAX_DRAW_EXTENT_PIXELS` before the first pixel. The bound lives in
    the primitives rather than at each tool's entry so that a tool reaching one of them
    inherits it. Before this, `draw_rectangle(width=1000000, height=1000000,
    filled=True)` was accepted and asked Lua for 1e12 writes, which spent the whole
    invocation timeout, and `draw_ellipse(radius_x=1000000, radius_y=1000000,
    filled=True)` asked for ~3.1e12 point tables, which is an out-of-memory rather than
    a slow call.
- **Timeouts.** Every Aseprite invocation runs under `ASEPRITE_MCP_TIMEOUT` (default 90s,
  clamped to 1-3600s so a hostile or fat-fingered value can't disable the guard). On
  expiry the child is killed, not abandoned, and the generated script is removed.
- **Error-message hygiene.** The generated Lua lives in a temp file, so an error the
  interpreter prefixes with its own location names an absolute host path, with the
  account name in it. `core/errors.strip_script_location` removes those, and it is
  applied on **every** path that carries interpreter output to the caller: the caught-Lua
  branch, the no-sentinel branch a Lua *compile* error takes, and both CLI failure
  branches. The compile-error branch was the gap: it handed back
  `C:\Users\<user>\AppData\Local\Temp\asemcp_<rand>.lua:12: ...` verbatim.
- **Generated scripts are removed on every path.** The temp script is unlinked in a
  `finally`, including on timeout and on an unexpected error. A removal that *fails*
  (on Windows, unlinking a file a process still holds raises) is now retried by the next
  run instead of being suppressed and forgotten; a hard kill of the server is the one
  case nothing in-process can collect.
- **Bring your own Aseprite.** The server only executes the Aseprite binary you point it
  at via `ASEPRITE_PATH` / PATH.
- **Least-privilege CI.** Both GitHub Actions workflows declare `permissions: contents: read`
  at the top level and pin every action to a commit SHA. CodeQL (`security-extended`) scans
  `main`, every PR, and weekly on a schedule; its analysis job is the only thing granted a
  write scope, `security-events: write`, which is what uploading the SARIF results needs.
  Neither workflow pushes, so both check out with `persist-credentials: false`: otherwise
  the job's token sits in `.git/config` for every later step to read, and the steps after
  checkout run third-party code (`uv sync` executes the build backends the lock resolves
  to). Dependencies are installed with `uv sync --locked`, so the committed `uv.lock` is
  what gets tested and a stale lock fails CI rather than being silently re-resolved.

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
