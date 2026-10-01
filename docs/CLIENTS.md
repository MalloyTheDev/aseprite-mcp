# Client setup

This server speaks plain MCP over stdio, so any MCP client can run it. What differs
between clients is only *where* the config lives and *what shape* it takes. This page
gives one copy-paste block per format, with the file path for each client that uses it.

Every config format below was checked against that client's own current documentation;
the links are in [Where these formats came from](#where-these-formats-came-from). A client
whose format could not be confirmed is listed under
[Clients not covered here](#clients-not-covered-here) rather than guessed at.

- [1. Prerequisites](#1-prerequisites)
- [2. Choosing a launch form](#2-choosing-a-launch-form)
- [3. Per-client configuration](#3-per-client-configuration)
- [4. Verify it works](#4-verify-it-works)
- [5. Troubleshooting](#5-troubleshooting)

---

## 1. Prerequisites

- **Aseprite 1.3+**, and a licensed copy. The Steam and standalone builds both work.
- **Python 3.10+** and **[uv](https://docs.astral.sh/uv/)**.
- A clone of this repository (see [Install](../README.md#install)).

Two environment variables matter for every client:

| Variable | Why you want it set |
| --- | --- |
| `ASEPRITE_PATH` | Full path to `Aseprite.exe` / `aseprite`. Auto-detection covers the usual Steam and standalone locations, but naming it explicitly is the only way to be sure which install the server drives. |
| `ASEPRITE_MCP_WORKSPACE` | The folder relative sprite filenames resolve inside. **Always set this explicitly.** |

`ASEPRITE_MCP_WORKSPACE` deserves the emphasis. Relative paths are the normal way to
address a sprite, and absolute paths are refused by default, so this variable decides
where everything you make ends up. Unset, the server picks a default for you: a sibling
`workspace/` directory when it is running from a source checkout, and a per-user data
directory under `aseprite-mcp/workspace` otherwise, rooted at `%LOCALAPPDATA%` on Windows,
`~/Library/Application Support` on macOS, and `$XDG_DATA_HOME` (or `~/.local/share`)
elsewhere. Either default is writable, and neither is inside the Python installation now
([issue #54](https://github.com/MalloyTheDev/aseprite-mcp/issues/54), fixed in v0.8.0).
A default is still somewhere you did not choose, though; point it at a real project folder
and the question never arises.

The full list of variables, including `ASEPRITE_MCP_TIMEOUT` and
`ASEPRITE_MCP_ALLOW_ABSOLUTE`, is in the README's
[Configuration](../README.md#configuration) table.

---

## 2. Choosing a launch form

Three commands start the same server. Pick one and use it in whichever config format your
client wants.

| Launch form | Use it when |
| --- | --- |
| `uv --directory /path/to/aseprite-mcp run aseprite-mcp` | You have a source checkout. This is the form the README and the example config use. |
| `uv --directory /path/to/aseprite-mcp run python -m aseprite_mcp` | Same, but it does not hold the console script open. See the note below. |
| `uvx --from git+https://github.com/MalloyTheDev/aseprite-mcp aseprite-mcp` | You would rather not clone. uv fetches and caches the repo itself. |

**The console-script lock (Windows).** `uv run aseprite-mcp` executes
`.venv\Scripts\aseprite-mcp.exe`, and Windows keeps that file locked for as long as the
server process lives. `uv sync` has to replace it, so it fails while a client is holding
the server open, and the fix is to shut the client down first. Launching with
`python -m aseprite_mcp` runs the same entry point through the interpreter instead, leaves
the `.exe` untouched, and lets you re-sync the environment without stopping your client.
That is the only difference between the two; pick the second if you develop against the
server while using it.

`uvx aseprite-mcp` without `--from` is not available: the package is not published to
PyPI at the time of writing, so there is nothing for `uvx` to resolve by name.

---

## 3. Per-client configuration

Throughout, replace `/ABSOLUTE/PATH/TO/aseprite-mcp` with your clone's path, and the
`ASEPRITE_PATH` value with your Aseprite executable. On Windows, prefer forward slashes
(`C:/path/to/aseprite-mcp`): they work in all three formats below and sidestep the fact
that JSON, TOML and YAML each treat a backslash differently. If you do use backslashes,
double them in JSON and in TOML double-quoted strings.

### The `mcpServers` JSON family

Claude Desktop, Cursor, Cline, Roo Code, Windsurf and LM Studio all read the same shape.
[`mcp-config.example.json`](../mcp-config.example.json) is this block as a file, ready to
copy; it is not duplicated per client here because the only thing that changes is the
path you put it at.

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/TO/aseprite-mcp", "run", "aseprite-mcp"],
      "env": {
        "ASEPRITE_PATH": "/path/to/Aseprite.exe",
        "ASEPRITE_MCP_WORKSPACE": "/path/to/your/art-project"
      }
    }
  }
}
```

Where that file lives:

| Client | Config file |
| --- | --- |
| Claude Desktop | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows: `%APPDATA%\Claude\claude_desktop_config.json`. Reachable from Settings > Developer > Edit Config. |
| Cursor | `~/.cursor/mcp.json` for every project, or `.cursor/mcp.json` in one project's root. |
| Cline | CLI: `~/.cline/mcp.json`. In the editor extension: the MCP Servers panel, Configure tab, "Configure MCP Servers". |
| Roo Code | Global: `mcp_settings.json`, opened from the MCP settings panel. Per project: `.roo/mcp.json`. |
| Windsurf | `~/.config/devin/mcp_config.json` (macOS and Linux) or `%APPDATA%\devin\mcp_config.json` (Windows), per the current docs. Older Windsurf builds used `~/.codeium/windsurf/mcp_config.json`; if the path above does not exist, use whichever one your install already has. |
| LM Studio | Edited in the app: Program tab, Install, "Edit mcp.json". LM Studio follows Cursor's `mcp.json` notation. |

Cline and Roo Code both keep a per-server allowlist of tools they will call without
asking (`autoApprove` in Cline, `alwaysAllow` in Roo Code). Every tool on this server
carries annotations, and the ones marked `readOnlyHint` are the safe candidates to put
there: nothing that writes a file the caller owns is marked read-only.

Key that list on the annotation rather than on the tool's name. The hint comes from a
hand-curated `READ_ONLY_TOOLS` set in `src/aseprite_mcp/app.py`, not from a name pattern,
and it is narrower than the naming suggests: `get_selection`, `assess_sprite` and
`diff_sprites` only measure, but none of the three carries the hint. A client keyed on
`get_*` would therefore auto-approve one tool the server does not vouch for, and still
prompt on the other two.

### Claude Code (CLI)

```bash
claude mcp add aseprite \
  --env ASEPRITE_PATH="/path/to/Aseprite.exe" \
  --env ASEPRITE_MCP_WORKSPACE="/path/to/your/art-project" \
  -- uv --directory /ABSOLUTE/PATH/TO/aseprite-mcp run aseprite-mcp
```

### Codex CLI (TOML)

`~/.codex/config.toml`, or a project-scoped `.codex/config.toml`:

```toml
[mcp_servers.aseprite]
command = "uv"
args = ["--directory", "/ABSOLUTE/PATH/TO/aseprite-mcp", "run", "aseprite-mcp"]
env = { ASEPRITE_PATH = "/path/to/Aseprite.exe", ASEPRITE_MCP_WORKSPACE = "/path/to/your/art-project" }
startup_timeout_sec = 30
```

Note the underscore: the table is `mcp_servers`, not `mcpServers`. The equivalent without
editing the file by hand is:

```bash
codex mcp add aseprite \
  --env ASEPRITE_PATH=/path/to/Aseprite.exe \
  --env ASEPRITE_MCP_WORKSPACE=/path/to/your/art-project \
  -- uv --directory /ABSOLUTE/PATH/TO/aseprite-mcp run aseprite-mcp
```

`startup_timeout_sec` defaults to 10. Raising it is worth doing here, because the first
launch may have to create the virtual environment before the server answers.

### Continue (`config.yaml`)

`mcpServers` is a **list** here, not an object, and each entry names itself:

```yaml
mcpServers:
  - name: aseprite
    type: stdio
    command: uv
    args:
      - "--directory"
      - "/ABSOLUTE/PATH/TO/aseprite-mcp"
      - "run"
      - "aseprite-mcp"
    env:
      ASEPRITE_PATH: /path/to/Aseprite.exe
      ASEPRITE_MCP_WORKSPACE: /path/to/your/art-project
```

This goes in your Continue config, or in its own file under `.continue/mcpServers/`.

### Zed (`settings.json`)

Zed calls them context servers:

```json
{
  "context_servers": {
    "aseprite": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/TO/aseprite-mcp", "run", "aseprite-mcp"],
      "env": {
        "ASEPRITE_PATH": "/path/to/Aseprite.exe",
        "ASEPRITE_MCP_WORKSPACE": "/path/to/your/art-project"
      }
    }
  }
}
```

### Goose (`~/.config/goose/config.yaml`)

On Windows the same file is `%APPDATA%\Block\goose\config\config.yaml`. Goose calls them
extensions, and uses `cmd` rather than `command` and `envs` rather than `env`:

```yaml
extensions:
  aseprite:
    type: stdio
    name: aseprite
    enabled: true
    cmd: uv
    args: ["--directory", "/ABSOLUTE/PATH/TO/aseprite-mcp", "run", "aseprite-mcp"]
    envs:
      ASEPRITE_PATH: /path/to/Aseprite.exe
      ASEPRITE_MCP_WORKSPACE: /path/to/your/art-project
    timeout: 300
```

### Hosts that can only reach an HTTP endpoint

Some hosted runners and remote agents cannot spawn a local process. Set
`ASEPRITE_MCP_TRANSPORT=streamable-http` (or `sse`) and the server listens over HTTP
instead of stdio. It still needs Aseprite on the same machine.

**Read this before you do.** `stdio` is the default because it keeps the server reachable
only by the process that started it. This server's file access is scoped by a workspace
directory, not by an identity, so binding it to a reachable port gives every caller that
can reach that port the same filesystem access the local user has. There is no
authentication in front of it. Bind it to loopback, or put an authenticating proxy in
front of it, and treat turning it on as a deliberate exposure decision rather than a
configuration convenience.

### OpenAI and Grok style function-calling bridges

If you are not using an MCP client at all but converting `tools/list` into function
definitions, the schemas here are already shaped for it: no pydantic `title` keys, every
parameter carries a concrete `type` rather than a nullable `anyOf`, and each default is
stated in the parameter's `description` as well as in `default`.

Two things your bridge still has to do for OpenAI **strict** mode, because they are
properties of the call rather than of the schema:

1. Set `additionalProperties: false` on every object.
2. List every property in `required`, and express an optional parameter by adding `null`
   to its type (`"type": ["integer", "null"]`) instead of leaving it out.

Strict mode also accepts only a subset of JSON Schema, so a bridge that strips keywords
outside that subset will drop `default`. Nothing is lost when it does: the default is in
the description text as well, which is why it is written there.

Non-strict function calling needs none of this and can pass the schemas through as they
are. Either way, `openWorldHint` is false on every tool and `readOnlyHint` marks the tools
that only read, which is the metadata to key an auto-approve policy on.

---

## 4. Verify it works

Restart the client, then ask the agent to call `health_check`. It returns a JSON object,
and the fields to look at are:

```json
{
  "ok": true,
  "aseprite_found": true,
  "aseprite_path": "...",
  "aseprite_version": "1.3.x",
  "workspace": "/path/to/your/art-project",
  "can_run_lua": true,
  "can_create_sprite": true,
  "can_export_png": true
}
```

`ok` is true only when a real create-sprite plus export-PNG round trip succeeded, so it is
the single field worth checking. A workspace that cannot be created does not take the rest
of the self-test down with it: it is reported as `workspace_error`, with `ok` false.

`workspace` is the **resolved** path, which is where files actually land and what every
other tool hands back, because paths are canonicalised before the containment check. If
your configured value reaches the same directory by a different spelling, through a symlink
or an NTFS junction, the two differ and the configured one appears beside it as
`workspace_configured` with a `workspace_note` saying they are one place. Expect that
rather than reading a different drive letter as an escape; otherwise `workspace` should be
the folder you configured.

The response also carries `tools_registered`, the number of tools the server registered on
startup. It should match the count stated at the top of [`docs/TOOLS.md`](TOOLS.md), which
is generated from the same registry; a lower number means a tool module failed to import.
The count is not repeated here because it changes every time a tool is added.

If `aseprite_found` is false, the `reason` field says where it looked.

---

## 5. Troubleshooting

**Sprites turn up somewhere you did not choose.** `ASEPRITE_MCP_WORKSPACE` did not reach
the server, so relative filenames resolved against the default: `<repo>/workspace` from a
source checkout, or the per-user data directory described in
[Prerequisites](#1-prerequisites). Set it in your client's `env` block and restart the
client. `health_check` reports the resolved workspace, which is the quickest way to
confirm the variable actually arrived: a variable set in your own shell does not reach a
server the client spawns. (Before v0.8.0 the non-checkout default landed inside the Python
installation instead, which is
[issue #54](https://github.com/MalloyTheDev/aseprite-mcp/issues/54).)

**A tool refuses an absolute path.** That is deliberate. Relative filenames resolve inside
the workspace, and paths that are absolute or climb out with `..` are rejected so a tool
call cannot reach the rest of the disk. Put the file under your workspace and use a
relative name. `ASEPRITE_MCP_ALLOW_ABSOLUTE=1` opts out, and gives away the sandbox.

**The model cannot see the preview.** `render_preview` returns a PNG as image content. A
text-only model gets nothing usable from it. Use `get_sprite_info` for structured state
(size, colour mode, frames, layer tree, tags, palette size) and `get_pixels` to read an
actual region as hex strings; both are text. The `validate_*` tools also answer
"is this right" without needing an image, and for animation `validate_loop` measures a
cycle frame by frame and names its faults, which is the one thing a still preview cannot
show however many times it is rendered.

**A structured argument seems to arrive empty.** Clients disagree about JSON-looking
values: some send an object, some send a string, and some parse a JSON-looking string into
an object before the call is made. Where an argument is genuinely structured, such as a
slice's `data`, the server accepts both forms and stores the same thing either way, so
`data={"type": "hitbox"}` and `data='{"type":"hitbox"}'` are equivalent. The exact text may
come back re-spaced by that round trip; the data does not change. Elsewhere, an argument
declared as a string wants a string: every parameter advertises one concrete type, which
is what makes the schemas usable by strict function-calling clients.

**`uv sync` fails with a permission or "file in use" error on Windows.** A client is
holding `.venv\Scripts\aseprite-mcp.exe` open. Close the client (or stop the server it
started), then re-run `uv sync`. To avoid hitting it again, switch that client's launch
form to `uv --directory ... run python -m aseprite_mcp`, which never touches the
console script (see [Choosing a launch form](#2-choosing-a-launch-form)).

**The server does not appear at all.** Check the client's own MCP log first: a stdio server
that fails to start usually reports a plain Python traceback there. Then run the launch
command yourself in a terminal; it should start and wait silently for JSON-RPC on stdin.
Anything printed to stdout that is not JSON-RPC will break the transport, which is why the
command has to be exactly the server and nothing that wraps it in extra output.

**Timeouts on large operations.** Raise `ASEPRITE_MCP_TIMEOUT` (seconds). Some clients also
impose their own startup timeout, which is what `startup_timeout_sec` covers for Codex CLI.

---

## Clients not covered here

Nothing was left out for lack of a confirmed format at the time of writing. If a client
you use is missing, its format is most likely the `mcpServers` JSON family above; check
its own documentation for the file path rather than assuming one from this list.

## Where these formats came from

Each block above was checked against the client's current documentation:

- Claude Desktop: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- Cursor: [Model Context Protocol](https://cursor.com/docs/context/mcp)
- Cline: [Configuring MCP Servers](https://docs.cline.bot/mcp/configuring-mcp-servers)
- Roo Code: [Using MCP in Roo Code](https://roocodeinc.github.io/Roo-Code/features/mcp/using-mcp-in-roo)
- Windsurf: [Cascade MCP](https://docs.windsurf.com/windsurf/cascade/mcp)
- LM Studio: [Use MCP Servers](https://lmstudio.ai/docs/app/plugins/mcp)
- Codex CLI: [Extend with MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- Continue: [MCP](https://docs.continue.dev/customize/deep-dives/mcp)
- Zed: [Model Context Protocol](https://zed.dev/docs/ai/mcp)
- Goose: [Configuration files](https://goose-docs.ai/docs/guides/config-files/)
- uv launch forms: [Using tools](https://docs.astral.sh/uv/guides/tools/)
- OpenAI strict mode: [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
