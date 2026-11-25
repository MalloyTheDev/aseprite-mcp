# Contributing to Aseprite MCP

## Find something to work on

- Pick a small task from the [good first issues](https://github.com/MalloyTheDev/aseprite-mcp/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22). For larger tasks, browse [help wanted issues](https://github.com/MalloyTheDev/aseprite-mcp/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22).
- Try the server on a sprite from your own workflow. Include the exact tool call, what you expected, and a small sprite you can share in a [bug report](https://github.com/MalloyTheDev/aseprite-mcp/issues/new?template=bug_report.yml).
- Have a workflow that needs a new tool or a change to the MCP interface? Describe what you are trying to make and where you get stuck in a [feature request](https://github.com/MalloyTheDev/aseprite-mcp/issues/new?template=feature_request.yml).

If you pick up an issue, leave a short comment so others know someone is working on it.
Small fixes to the docs are welcome as pull requests.

## Make a documentation fix

For a small Markdown change, open the file on GitHub and use the pencil icon. Preview
the edit, then propose it from your fork. Check the changed links and try any commands
you edited. In the pull request, mention what you checked. This path works entirely in
the browser. [GitHub's file editing guide](https://docs.github.com/en/repositories/working-with-files/managing-files/editing-files#editing-files-in-another-users-repository)

For a tool description or argument, edit the Python docstring where the tool is defined
and regenerate the reference locally. [Tool authoring guide](docs/DEVELOPMENT.md#adding-or-changing-a-tool)

## Local setup

Fork the repository. Install [Git](https://git-scm.com/downloads) and [uv](https://docs.astral.sh/uv/getting-started/installation/)
if needed. Replace `YOUR_USERNAME` with the owner of your fork.

```bash
git clone https://github.com/YOUR_USERNAME/aseprite-mcp.git
cd aseprite-mcp
git switch -c my-change
uv sync --locked
uv run --locked pytest tests/test_unit.py
```

The last command checks your setup using Python only. The project supports Python 3.10
and up. For tests that open or export sprites, use Aseprite 1.3+ and point
`ASEPRITE_PATH` at your executable if needed. [Editor setup](docs/DEVELOPMENT.md#local-editor-setup)

## Running the tests

For code changes, start with the tests for the module you changed. Run these checks
before opening the pull request.

```bash
uv run --locked ruff check src tests scripts
uv run --locked pytest
uv run --locked python scripts/gen_tool_docs.py --check
```

These commands cover lint, the Python-only test tier, and the generated reference check.
CI runs its Python jobs on pull requests into `main` and on pushes to `main`. For a change
to sprite pixels, files, or exports, run the relevant editor-backed tests with
`--run-aseprite -rs` and report the Aseprite version. See how to target a single test,
read the skip summary, or register a new Python-only test. [Test guide](docs/DEVELOPMENT.md#running-the-tests)

## Pull requests

For a local change, stage the files you edited, check the staged diff, and push your
branch to your fork. Replace the example file path and use the branch name you created.

```bash
git add path/to/changed-file
git diff --cached --check
git commit -m "Describe the change"
git push -u origin my-change
```

Open the pull request into `MalloyTheDev/aseprite-mcp:main`. Link the issue if there is
one, explain what changes for users, and include the checks you ran. For a tool fix, a
failing case and a focused test make the expected behaviour clear. For a docs fix, name
the page, link, or example you verified.

## Find the right guide

| If you want to | Start here |
| --- | --- |
| Find the module for a tool or add a test | [Development guide](docs/DEVELOPMENT.md) |
| Check what Aseprite supports in batch mode | [Headless Aseprite](docs/HEADLESS.md) |
| Find tool arguments and results | [Tool reference](docs/TOOLS.md) |
| Set up an MCP client or check a connection | [Client setup](docs/CLIENTS.md) |
| Reproduce the art shown in the README | [Showcase generators](scripts/showcase/README.md) |
| Report a security issue privately | [Security policy](SECURITY.md) |
