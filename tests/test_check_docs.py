"""The documentation checker reports what is wrong and nothing else (pure Python).

`scripts/check_docs.py` is only worth running if two things hold: it finds the defects it
exists for, and it stays quiet about text that merely looks like one, since a checker that
cries wolf gets switched off. The fixture trees below plant each defect once and surround
it with the lookalikes that must be left alone: a broken link inside a code fence, inside
a code span and inside an HTML comment, an anchor that only resolves under GitHub's slug
rules, and a reference whose definition sits at the bottom of the file.

The last test runs the checker on this repository, which is the check that matters.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.pure

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("check_docs", REPO / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_docs"] = module
    spec.loader.exec_module(module)
    return module


check_docs = _load()


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _line(path: Path, marker: str) -> int:
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if marker in line:
            return number
    raise AssertionError(f"{marker!r} not in {path}")


def _found(root: Path) -> list[tuple[str, int, str]]:
    problems, _ = check_docs.check(root)
    return [(p.path, p.line, p.message) for p in problems]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _write(tmp_path, "docs/a.md", "# A\n\n## Second part\n\ntext\n")
    _write(tmp_path, "docs/pic.png", "x")
    _write(
        tmp_path,
        "README.md",
        "\n".join(
            [
                "# Title",
                "",
                "OK file [a](docs/a.md) and OK cross anchor [b](docs/a.md#second-part).",
                "BROKEN-FILE [c](docs/missing.md).",
                "OK slug [d](#notes--limitations) and OK dup [e](#dup-1).",
                "BROKEN-ANCHOR [f](#nowhere) and BROKEN-CROSS [g](docs/a.md#absent).",
                'OK html <img src="docs/pic.png"> BROKEN-HTML <a href="docs/gone.png">x</a>',
                "OK ref [h][known] and OK collapsed [known][] and BROKEN-REF [i][unknown].",
                "OK external [j](https://example.invalid/never-fetched) and OK mail [k](mailto:a@b.c).",
                "",
                "```bash",
                "[ignored](fenced-missing.md)",
                "```",
                "",
                "A code span `[ignored](span-missing.md)` and <!-- [ignored](comment-missing.md) --> done.",
                "",
                "## Notes & limitations",
                "",
                "## Dup",
                "",
                "## Dup",
                "",
                "[known]: docs/a.md",
                "",
            ]
        ),
    )
    _write(
        tmp_path,
        "CHANGELOG.md",
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n[1.0.0]: https://example.invalid/1.0.0\n",
    )
    return tmp_path


def test_exactly_the_planted_defects_are_reported(tree: Path):
    readme = tree / "README.md"
    expected = {
        ("README.md", _line(readme, "BROKEN-FILE"), "broken link: 'docs/missing.md' does not exist"),
        ("README.md", _line(readme, "BROKEN-ANCHOR"),
         "broken anchor: '#nowhere' is not a heading in this file"),
        ("README.md", _line(readme, "BROKEN-CROSS"),
         "broken anchor: '#absent' is not a heading in docs/a.md"),
        ("README.md", _line(readme, "BROKEN-HTML"), "broken link: 'docs/gone.png' does not exist"),
        ("README.md", _line(readme, "BROKEN-REF"), "reference '[unknown]' has no definition"),
        ("CHANGELOG.md", 3, "reference '[Unreleased]' has no definition"),
    }
    assert set(_found(tree)) == expected


def test_a_comment_hides_its_links_however_many_lines_it_spans(tmp_path: Path):
    """One comment closed on a later line, two on one line, and text between them that
    is not commented out and so is still checked."""
    _write(tmp_path, "README.md", "\n".join([
        "# T",
        "",
        "<!-- [a](gone-1.md)",
        "[b](gone-2.md)",
        "[c](gone-3.md) --> [seen](really-gone.md) <!-- [d](gone-4.md) --> <!-- [e](gone-5.md)",
        "[f](gone-6.md) -->",
        "",
    ]))
    problems = [str(p) for p in check_docs.check(tmp_path)[0]]
    assert len(problems) == 1 and "really-gone.md" in problems[0], problems


def test_a_clean_tree_passes(tmp_path: Path):
    _write(tmp_path, "README.md", "# Title\n\n[self](#title) [other](docs/a.md#a)\n")
    _write(tmp_path, "docs/a.md", "# A\n")
    assert _found(tmp_path) == []
    assert check_docs.main(["--root", str(tmp_path)]) == 0


def test_the_exit_status_and_output_format(tree: Path, capsys: pytest.CaptureFixture[str]):
    assert check_docs.main(["--root", str(tree)]) == 1
    out = capsys.readouterr().out
    assert f"README.md:{_line(tree / 'README.md', 'BROKEN-FILE')}: broken link" in out


def test_external_links_are_listed_on_request_and_never_fetched(
    tree: Path, capsys: pytest.CaptureFixture[str]
):
    check_docs.main(["--root", str(tree), "--external"])
    out = capsys.readouterr().out
    assert "external https://example.invalid/never-fetched" in out
    assert "mailto" not in out


def test_a_link_into_a_directory_that_exists_passes(tmp_path: Path):
    _write(tmp_path, "README.md", "[d](docs/) [e](docs)\n")
    (tmp_path / "docs").mkdir()
    assert _found(tmp_path) == []


def test_letter_case_must_match_because_github_is_case_sensitive(tmp_path: Path):
    _write(tmp_path, "README.md", "[a](docs/Guide.md)\n")
    _write(tmp_path, "docs/guide.md", "# G\n")
    assert [m for _, _, m in _found(tmp_path)] == ["broken link: 'docs/Guide.md' does not exist"]


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        ("Notes & limitations", "notes--limitations"),
        ("`gen_tool_docs.py` and friends", "gen_tool_docspy-and-friends"),
        ("Run [the gate](x.md) now", "run-the-gate-now"),
        ("5. Troubleshooting", "5-troubleshooting"),
        ("What _is_ it?", "what-is-it"),
        ("snake_case stays", "snake_case-stays"),
    ],
)
def test_heading_slugs_follow_github(heading: str, slug: str):
    assert check_docs.github_slug(heading) == slug


# ---------------------------------------------------------------------------
# The drift checks
# ---------------------------------------------------------------------------


def _luagen(root: Path, *, nonced: bool = True) -> None:
    body = (
        'return f"@@ASEMCP:{nonce}@@"\nreturn f"@@ASEMCP_ERR:{nonce}@@"\n'
        if nonced
        else 'RESULT_PREFIX = "@@ASEMCP@@"\n'
    )
    _write(root, "src/aseprite_mcp/core/luagen.py", body)


def test_a_legacy_sentinel_shown_as_live_is_reported(tmp_path: Path):
    _luagen(tmp_path)
    _write(
        tmp_path,
        "docs/DEVELOPMENT.md",
        "# Dev\n\nThe script prints @@ASEMCP@@<json> when it works.\n"
        "The un-nonced @@ASEMCP_ERR@@ is a legacy name kept for imports.\n",
    )
    found = _found(tmp_path)
    assert [(p, n) for p, n, _ in found] == [("docs/DEVELOPMENT.md", 3)]
    assert "legacy sentinel" in found[0][2]


def test_docs_that_name_a_sentinel_the_code_no_longer_builds_are_reported(tmp_path: Path):
    _luagen(tmp_path, nonced=False)
    _write(tmp_path, "README.md", "# R\n")
    messages = [m for _, _, m in _found(tmp_path)]
    assert len(messages) == 2
    assert all("no longer builds it" in m for m in messages)


def test_unlocked_uv_commands_are_reported_only_where_contributors_type_them(tmp_path: Path):
    _write(
        tmp_path,
        "CONTRIBUTING.md",
        "# C\n\n```bash\nuv sync --locked\nuv run --locked pytest\nuv run --no-sync pytest\n"
        "uv sync\n$ uv run pytest\nuvx --from x y\n```\n\nProse: run uv sync later.\n",
    )
    _write(tmp_path, "docs/CLIENTS.md", "# K\n\n```bash\nuv run aseprite-mcp\n```\n")
    found = _found(tmp_path)
    assert [(p, n) for p, n, _ in found] == [("CONTRIBUTING.md", 7), ("CONTRIBUTING.md", 8)]


def test_the_bare_uvx_form_is_reported_unless_the_line_warns_against_it(tmp_path: Path):
    _write(
        tmp_path,
        "docs/CLIENTS.md",
        "# K\n\n```bash\nuvx aseprite-mcp\nuvx --from git+https://example.invalid/x aseprite-mcp\n```\n\n"
        "Do not run uvx aseprite-mcp without --from.\n",
    )
    assert [(p, n) for p, n, _ in _found(tmp_path)] == [("docs/CLIENTS.md", 4)]


def test_a_repository_path_that_no_longer_exists_is_reported(tmp_path: Path):
    _write(tmp_path, "scripts/real.py", "x = 1\n")
    _write(
        tmp_path,
        "README.md",
        "# R\n\nSee `scripts/real.py`, `scripts/real.py:1` and `tests/gone.py::test_x`.\n"
        "Also `scripts/*.py` and `not/a/repo/path.py` are left alone.\n",
    )
    assert [m for _, _, m in _found(tmp_path)] == ["names 'tests/gone.py', which does not exist"]


# ---------------------------------------------------------------------------
# The real documentation
# ---------------------------------------------------------------------------


def test_the_repository_documentation_is_clean():
    problems, _ = check_docs.check(REPO)
    assert [p.render() for p in problems] == []
