# Contributing to Aseprite MCP

Pick the route that matches what you have. Each one ends with something you can check.

| You are | Start with | You need |
| --- | --- | --- |
| A pixel artist, or anyone who uses Aseprite | [Test a workflow and report it](#route-1-test-a-workflow-and-report-it) | Aseprite and an MCP client. No code. |
| New to the code and want a first change | [Make a first Python change](#route-2-make-a-first-python-change) | Python, Git and uv. No Aseprite. |
| Ready to work on the engine, the tooling or client integrations | [Go deeper](#route-3-go-deeper) | Aseprite for most of it. |

## Route 1: test a workflow and report it

1. Set the server up with the [README](README.md#install) and your client's
   [setup page](docs/CLIENTS.md). `health_check` should say `ok: true`.
2. Ask your agent for something you would really make, or follow the
   [walkthrough](docs/WALKTHROUGH.md) to call a tool yourself and check what it does.
3. If the result is wrong, or setup is stuck, open a
   [bug report](https://github.com/MalloyTheDev/aseprite-mcp/issues/new?template=bug_report.yml).
   The form asks for what you asked for, what you got, a preview image, and your Aseprite
   version. Read it from Help > About in Aseprite, or from `aseprite_version` in the
   `health_check` result. `aseprite --version` also prints it on macOS and Linux; on
   Windows, PowerShell shows nothing unless the output is piped:
   `& "C:/path/to/Aseprite.exe" --version | Write-Output`.
4. Missing a tool? Describe what you are trying to make in a
   [feature request](https://github.com/MalloyTheDev/aseprite-mcp/issues/new?template=feature_request.yml).

## Route 2: make a first Python change

Look for a [good first issue](https://github.com/MalloyTheDev/aseprite-mcp/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22),
or a [help wanted](https://github.com/MalloyTheDev/aseprite-mcp/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
issue for something larger. Leave a short comment so others know you are on it. Docs fixes
need no issue: edit the file on GitHub with the pencil icon and propose it from your fork.

Fork the repository, then install [Git](https://git-scm.com/downloads) and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Replace `YOUR_USERNAME`
with your GitHub name.

```bash
git clone https://github.com/YOUR_USERNAME/aseprite-mcp.git
cd aseprite-mcp
git remote add upstream https://github.com/MalloyTheDev/aseprite-mcp.git
git switch -c my-change
uv sync --locked
uv run --locked pytest tests/test_unit.py
```

The last command uses Python only. It proves your setup works. Aseprite is not needed
until you change what ends up in a sprite.

### Check your change

```bash
uv run --locked ruff check src tests scripts
uv run --locked pytest
uv run --locked python scripts/gen_tool_docs.py --check
python scripts/check_docs.py
```

That is lint, the Python-only tests, the generated tool reference, and a check of the
Markdown. Docs are tested like code: the tool counts in the README, links and anchors, no
em dash characters, and the locked `uv` form of contributor commands are all checked.

The Python-only tier passes with several hundred tests skipped. Those are the ones that
need Aseprite, and they are not a problem on a fresh clone. At the time of writing
(November 2026) it reports about 1811 passed and 846 skipped; the counts grow as tests
are added, so compare against a clean checkout of `main`, not against this page.

### Windows: a client is running the server from your checkout

If an MCP client has the server running from this same folder, `uv sync --locked`,
`uv run --locked pytest` and the release gate can fail with "os error 32" (the file is in
use) once `pyproject.toml` or `uv.lock` has changed, because Windows keeps
`.venv\Scripts\aseprite-mcp.exe` locked. Either close the client, or run commands
without a sync:

```bash
uv run --no-sync pytest
```

To stop it happening again, launch the server from your client as
`uv --directory /path/to/aseprite-mcp run python -m aseprite_mcp`; that does not lock the
`.exe`. See [Choosing a launch form](docs/CLIENTS.md#2-choosing-a-launch-form).

### Open the pull request

```bash
git add path/to/changed-file
git diff --cached --check
git commit -m "Describe the change"
git push -u origin my-change
```

Open it into `MalloyTheDev/aseprite-mcp:main`. Link the issue, say what changes for
users, and paste the checks you ran. For a docs fix, name the page or link you verified.

To pick up new work from upstream, before you start or when a pull request needs it:

```bash
git fetch upstream
git switch main
git merge --ff-only upstream/main
git switch my-change
git rebase main
```

(GitHub's "Sync fork" button on your fork's page does the `main` part.) If the rebase
stops on a conflict, fix the files it names, then `git add` them and `git rebase --continue`.

## Route 3: go deeper

[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers the architecture, adding a tool, the two
test tiers, the release gate and cutting a release. Work that changes sprite pixels,
files or exports needs the editor tier:

```bash
uv run --locked pytest --run-aseprite
```

With no Aseprite found that command stops with an error, so set `ASEPRITE_PATH`. With
Aseprite 1.3.18.6 on Windows it takes about 19 minutes, and on 2026-11-25 it ended at about
2655 passed and 2 skipped (counts grow). The 2 skips are fixture skips for an
untracked `workspace/` folder: `tests/test_figure.py:770` and `tests/test_ramp_lint.py:118`.
Any other skip means something is missing.

For the full local check, which runs lint, both tiers, the generated reference and a build,
and prints the Aseprite version it used, run the gate. Quote that line in your pull request:

```bash
uv run --locked python scripts/release_gate.py
```

It starts by printing what it is about to test, and the line that names the editor is the
one to quote:

```text
release-gate: aseprite C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe (Aseprite 1.3.18.6-x64)
```

Each step then reports its own result, for example `ok (48.4s): 1811 passed, 846 skipped`,
and the summary at the end lists every step as PASS, FAIL or SKIP. With no editor the gate
stops before any step, with a message that says to set `ASEPRITE_PATH` or pass
`--skip-aseprite`. That flag runs only what CI runs, and the summary then says plainly that
the editor tier was not run. Check the Markdown with `python scripts/check_docs.py`, which
CI runs on its own and the gate does not.

Other places to start: [client setup](docs/CLIENTS.md), [Headless Aseprite](docs/HEADLESS.md),
the [showcase generators](scripts/showcase/README.md), and the
[tool reference](docs/TOOLS.md). Report a security issue privately, as the
[security policy](SECURITY.md) describes.
