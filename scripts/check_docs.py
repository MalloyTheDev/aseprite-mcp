#!/usr/bin/env python3
"""Check the Markdown documentation for drift, locally, with no network.

Run it from anywhere:

    python scripts/check_docs.py

It exits 0 when the docs are clean and 1 when they are not, printing one line per problem
as ``path:line: what is wrong``. It needs only the standard library, so it runs on any
platform and any Python from 3.10 up, before a virtual environment exists.

What it checks, over README.md, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md, docs/*.md,
scripts/showcase/README.md and the pull request template:

* every relative link and every ``href=`` / ``src=`` in inline HTML points at a file or
  directory that exists, with the exact letter case GitHub would need;
* every ``#anchor``, in the same file or in another Markdown file, matches a heading
  (using GitHub's slug rules) or an explicit ``id=`` / ``name=``;
* reference-style links have a definition. Full (``[text][label]``) and collapsed
  (``[label][]``) references are always checked; a bare ``[label]`` is checked only in a
  heading or when it looks like a version or ``Unreleased``, because prose is full of
  square brackets that are not links. That last rule is what catches a changelog whose
  version headings have no link definitions;
* four drift checks that each correspond to a claim that went stale once:
  the documented result sentinels still match the ones ``core/luagen.py`` builds, the
  contributor commands use a locked or no-sync ``uv`` form, nothing tells a reader to run
  the bare ``uvx aseprite-mcp`` (an unrelated project on PyPI has that name), and a
  repository path named in backticks still exists.

Fenced code blocks, code spans and HTML comments are skipped, so an example that shows a
broken link on purpose is not reported. External ``http(s)`` links are never fetched;
``--external`` lists them instead, for a reviewer who wants to check them by hand.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]

# Docs that carry the instructions a contributor types. The locked-command rule applies
# to these only: the client guide shows commands that an MCP client runs, not commands a
# person runs in a checkout.
COMMAND_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/DEVELOPMENT.md",
    "docs/WALKTHROUGH.md",
)

# Files whose historical text legitimately names things that no longer exist.
HISTORY_DOCS = ("CHANGELOG.md", "docs/TOOLS.md")


class Problem(NamedTuple):
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


# --------------------------------------------------------------------------- #
# Reading Markdown                                                            #
# --------------------------------------------------------------------------- #

_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_COMMENT = re.compile(r"<!--.*?-->")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_DEFINITION = re.compile(r"^ {0,3}\[([^\]]+)\]:[ \t]*(<[^>]*>|\S+)")
_INLINE_LINK = re.compile(
    r"\]\(\s*(<[^>\n]*>|(?:[^()\s]|\([^()\s]*\))*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
_FULL_REF = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\[([^\[\]]*)\]")
_SHORT_REF = re.compile(r"(?<![\]\\!])\[([^\[\]]+)\](?![\[(:])")
_HTML_URL = re.compile(r"""\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_HTML_ID = re.compile(r"""\b(?:id|name)\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.IGNORECASE)
_VERSIONISH = re.compile(r"^(?:v?\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?|unreleased)$", re.IGNORECASE)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_LINE_ANCHOR = re.compile(r"^L\d+(?:C\d+)?(?:-L\d+(?:C\d+)?)?$")


def _prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line number, line) for every line outside fences and HTML comments."""
    fence: tuple[str, int] | None = None
    in_comment = False
    for number, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        if fence is not None:
            close = re.match(r"^\s*(`{3,}|~{3,})\s*$", line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                fence = None
            continue
        opened = _FENCE_OPEN.match(line)
        if opened and not in_comment:
            marker = opened.group(1)
            # A backtick fence's info string cannot contain a backtick; otherwise this is
            # an inline code span that happens to start the line.
            if marker[0] != "`" or "`" not in line[opened.end():]:
                fence = (marker[0], len(marker))
                continue
        if in_comment:
            end = line.find("-->")
            if end < 0:
                continue
            line = " " * (end + 3) + line[end + 3:]
            in_comment = False
        line = _COMMENT.sub(lambda m: " " * len(m.group(0)), line)
        start = line.find("<!--")
        if start >= 0:
            in_comment = True
            line = line[:start]
        yield number, line


def _blank_code_spans(line: str) -> str:
    return _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)


def _code_span_texts(line: str) -> list[str]:
    return [m.group(2).strip() for m in _CODE_SPAN.finditer(line)]


def _heading_text(raw: str) -> str:
    """The visible text of a heading, which is what GitHub slugs."""
    pieces = re.split(r"(`+[^`]+`+)", raw)
    out = []
    for piece in pieces:
        if piece.startswith("`") and piece.endswith("`") and len(piece) > 1:
            out.append(piece.strip("`"))
            continue
        piece = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", piece)
        piece = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", piece)
        piece = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", piece)
        piece = re.sub(r"<[^>]+>", "", piece)
        piece = piece.replace("*", "")
        piece = re.sub(r"(?<!\w)(_{1,2})(\S(?:.*?\S)?)\1(?!\w)", r"\2", piece)
        out.append(html.unescape(piece))
    return "".join(out)


def github_slug(heading: str) -> str:
    """GitHub's heading anchor: lower-case, drop punctuation, spaces to hyphens.

    Runs of spaces are not collapsed, so "Notes & limitations" becomes
    ``notes--limitations``. Duplicate headings are numbered by the caller.
    """
    text = _heading_text(heading).strip().lower()
    kept = "".join(
        c for c in text
        if c.isalnum() or c in "_- " or unicodedata.category(c).startswith("M")
    )
    return kept.replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    """Every anchor a reader can jump to in this Markdown file (lower-case)."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    previous = ""

    def add_heading(raw: str) -> None:
        slug = github_slug(raw)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")

    for _, line in _prose_lines(text):
        atx = _ATX.match(line)
        if atx:
            add_heading(atx.group(2))
        else:
            setext = _SETEXT.match(line)
            if (
                setext
                and previous.strip()
                and not previous.lstrip().startswith(("|", "<", ">", "#", "-", "*", "+"))
                and not re.match(r"^\s*\d+[.)]\s", previous)
            ):
                add_heading(previous.strip())
        for m in _HTML_ID.finditer(line):
            anchors.add((m.group(1) or m.group(2)).lower())
        previous = line
    return anchors


# --------------------------------------------------------------------------- #
# Link checks                                                                 #
# --------------------------------------------------------------------------- #


class Checker:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.problems: list[Problem] = []
        self.externals: list[tuple[str, int, str]] = []
        self._anchors: dict[Path, set[str]] = {}
        self._listing: dict[Path, set[str]] = {}

    # -- bookkeeping ------------------------------------------------------- #
    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def report(self, path: Path, line: int, message: str) -> None:
        self.problems.append(Problem(self.rel(path), line, message))

    def _names_in(self, directory: Path) -> set[str]:
        if directory not in self._listing:
            try:
                self._listing[directory] = set(os.listdir(directory))
            except OSError:
                self._listing[directory] = set()
        return self._listing[directory]

    def exists_exact(self, dest: Path) -> bool:
        """True if `dest` exists with the same letter case on every component.

        GitHub serves from a case-sensitive file system. Checking the existence of a
        path on Windows or macOS would pass a link that 404s once it is pushed.
        """
        try:
            parts = dest.relative_to(self.root).parts
        except ValueError:
            return False
        current = self.root
        for part in parts:
            if part not in self._names_in(current):
                return False
            current = current / part
        return True

    def anchors_in(self, dest: Path) -> set[str]:
        if dest not in self._anchors:
            self._anchors[dest] = anchors_of(dest.read_text(encoding="utf-8", errors="replace"))
        return self._anchors[dest]

    # -- one target -------------------------------------------------------- #
    def check_target(self, source: Path, line: int, target: str) -> None:
        target = target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if not target:
            return
        if target.startswith("//") or _SCHEME.match(target):
            if target.lower().startswith(("http://", "https://")):
                self.externals.append((self.rel(source), line, target))
            return
        path_part, _, fragment = target.partition("#")
        path_part = unquote(path_part.split("?", 1)[0])
        fragment = unquote(fragment)

        if not path_part:
            dest = source.resolve()
        else:
            base = self.root if path_part.startswith("/") else source.resolve().parent
            dest = Path(os.path.normpath(base / path_part.lstrip("/")))
            if self.root != dest and self.root not in dest.parents:
                self.report(source, line, f"link '{target}' leaves the repository")
                return
            if not self.exists_exact(dest):
                self.report(source, line, f"broken link: '{path_part}' does not exist")
                return

        if not fragment:
            return
        is_markdown = dest.is_file() and dest.suffix.lower() == ".md"
        if is_markdown and fragment.lower() not in self.anchors_in(dest):
            where = "this file" if dest == source.resolve() else self.rel(dest)
            self.report(source, line, f"broken anchor: '#{fragment}' is not a heading in {where}")
        # Anchors into non-Markdown files (#L10 line links, for one) cannot be checked.

    # -- one file ---------------------------------------------------------- #
    def check_file(self, source: Path) -> None:
        text = source.read_text(encoding="utf-8", errors="replace")
        lines = list(_prose_lines(text))

        definitions: dict[str, tuple[int, str]] = {}
        for number, line in lines:
            m = _DEFINITION.match(line)
            if m:
                label = _norm_label(m.group(1))
                definitions.setdefault(label, (number, m.group(2)))

        for number, target in definitions.values():
            self.check_target(source, number, target)

        for number, raw in lines:
            if _DEFINITION.match(raw):
                continue
            line = _blank_code_spans(raw)
            work = line
            for m in _INLINE_LINK.finditer(line):
                self.check_target(source, number, m.group(1))
            work = _INLINE_LINK.sub(lambda m: " " * len(m.group(0)), work)
            for m in _HTML_URL.finditer(line):
                self.check_target(source, number, m.group(1) if m.group(1) is not None else m.group(2))

            for m in _FULL_REF.finditer(work):
                label = _norm_label(m.group(2) or m.group(1))
                if label not in definitions:
                    self.report(source, number, f"reference '[{m.group(2) or m.group(1)}]' has no definition")
            work = _FULL_REF.sub(lambda m: " " * len(m.group(0)), work)

            is_heading = bool(_ATX.match(raw))
            for m in _SHORT_REF.finditer(work):
                label = m.group(1)
                if (is_heading or _VERSIONISH.match(label.strip())) and _norm_label(label) not in definitions:
                    self.report(source, number, f"reference '[{label}]' has no definition")

    # -- drift checks ------------------------------------------------------ #
    def check_sentinels(self, files: list[Path]) -> None:
        """The documented result sentinels must be the ones the runner frames with.

        The un-nonced names `@@ASEMCP@@` and `@@ASEMCP_ERR@@` are legacy constants. Docs
        that show them as the live protocol were wrong once; a line may still name them if
        it says they are legacy.
        """
        luagen = self.root / "src" / "aseprite_mcp" / "core" / "luagen.py"
        if luagen.is_file():
            code = luagen.read_text(encoding="utf-8", errors="replace")
            for needed in ("@@ASEMCP:{nonce}@@", "@@ASEMCP_ERR:{nonce}@@"):
                if needed not in code:
                    self.report(
                        luagen, 1,
                        f"docs describe the sentinel '{needed}' but core/luagen.py no longer builds it; "
                        "update docs/DEVELOPMENT.md and this check",
                    )
        for path in files:
            if self.rel(path) in HISTORY_DOCS:
                continue
            for number, line in _prose_lines(path.read_text(encoding="utf-8", errors="replace")):
                names_legacy = re.search(r"@@ASEMCP(?:_ERR)?@@", line)
                if names_legacy and not re.search(r"legacy|un-nonced|older", line, re.I):
                    self.report(
                        path, number,
                        "names the legacy sentinel (no per-run nonce) as if it were live; "
                        "the runner frames with '@@ASEMCP:<nonce>@@'",
                    )

    def check_commands(self, files: list[Path]) -> None:
        """Contributor commands must use a locked or no-sync uv form.

        An unlocked `uv run` with a stale lock rewrote uv.lock without a word, and an
        unlocked `uv sync` fails on Windows while an MCP client holds the console script.
        """
        wanted = {self.root / name for name in COMMAND_DOCS}
        pattern = re.compile(r"^\s*(?:\$ |PS> |> )?uv\s+(sync|run)\b(.*)$")
        for path in files:
            if path.resolve() not in wanted:
                continue
            fence: tuple[str, int] | None = None
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
                line = line.rstrip("\r")
                if fence is None:
                    opened = _FENCE_OPEN.match(line)
                    if opened:
                        fence = (opened.group(1)[0], len(opened.group(1)))
                    continue
                close = re.match(r"^\s*(`{3,}|~{3,})\s*$", line)
                if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                    fence = None
                    continue
                m = pattern.match(line)
                if not m:
                    continue
                rest = m.group(2)
                if re.search(r"--(locked|frozen|no-sync)\b", rest):
                    continue
                self.report(
                    path, number,
                    f"'uv {m.group(1)}' without --locked or --no-sync in a contributor command",
                )

    def check_bare_uvx(self, files: list[Path]) -> None:
        """`uvx aseprite-mcp` without `--from` runs a different project from PyPI.

        This project is installed from git. The name on PyPI belongs to someone else, so
        a command that names it bare is a supply-chain hazard, not only a stale claim. A
        line may still mention the bare form to warn against it.
        """
        bare = re.compile(r"\buvx\s+aseprite-mcp\b")
        warning = re.compile(r"\b(?:not|bare|without|unrelated|never)\b", re.IGNORECASE)
        for path in files:
            if self.rel(path) in HISTORY_DOCS:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.split("\n"), 1):
                if bare.search(line) and not warning.search(line):
                    self.report(
                        path, number,
                        "'uvx aseprite-mcp' without --from would run an unrelated PyPI project; "
                        "use 'uvx --from git+https://github.com/MalloyTheDev/aseprite-mcp aseprite-mcp'",
                    )

    def check_repo_paths(self, files: list[Path]) -> None:
        """A repository path named in backticks must exist."""
        token = re.compile(
            r"^(?:\./)?((?:scripts|tests|src|docs|\.github)/[A-Za-z0-9_./-]*[A-Za-z0-9_])/?"
            r"(?::\d+(?:-\d+)?)?(?:::\S+)?$"
        )
        for path in files:
            if self.rel(path) in HISTORY_DOCS:
                continue
            for number, line in _prose_lines(path.read_text(encoding="utf-8", errors="replace")):
                for span in _code_span_texts(line):
                    m = token.match(span)
                    if not m:
                        continue
                    dest = self.root / m.group(1)
                    if not self.exists_exact(dest):
                        self.report(path, number, f"names '{m.group(1)}', which does not exist")


def _norm_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip()).lower()


# --------------------------------------------------------------------------- #
# Driver                                                                      #
# --------------------------------------------------------------------------- #


def collect_files(root: Path) -> list[Path]:
    """The Markdown files this tool owns, in a stable order."""
    names = ["README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
             "scripts/showcase/README.md", ".github/pull_request_template.md"]
    found = [root / n for n in names if (root / n).is_file()]
    docs = root / "docs"
    if docs.is_dir():
        found += sorted(p for p in docs.glob("*.md") if p.is_file())
    return found


def check(root: Path) -> tuple[list[Problem], list[tuple[str, int, str]]]:
    checker = Checker(root)
    files = collect_files(root)
    for path in files:
        checker.check_file(path)
    checker.check_sentinels(files)
    checker.check_commands(files)
    checker.check_bare_uvx(files)
    checker.check_repo_paths(files)
    problems = sorted(set(checker.problems), key=lambda p: (p.path, p.line, p.message))
    return problems, checker.externals


def _keep_output_printable() -> None:
    """A redirected Windows stream is cp1252, and a path or heading outside it would
    raise instead of being reported. Escape what the stream cannot encode."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the Markdown docs for drift (no network).")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root to check")
    parser.add_argument("--external", action="store_true",
                        help="also list the external http(s) links, which are never fetched")
    args = parser.parse_args(argv)
    _keep_output_printable()

    problems, externals = check(args.root)
    for problem in problems:
        print(problem.render())
    if args.external:
        for path, line, url in sorted(set(externals)):
            print(f"{path}:{line}: external {url}")
    if problems:
        print(f"{len(problems)} documentation problem(s) found.", file=sys.stderr)
        return 1
    print(f"Documentation checks passed ({len(collect_files(args.root))} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
