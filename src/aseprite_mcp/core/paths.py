"""Output-path helpers: resolve through the workspace sandbox with no-clobber protection.

Output-writing tools are **no-clobber by default**: `ensure_output_path` refuses to write
over an existing file unless `overwrite=True`. Sandbox/escape violations still raise
`WorkspaceError`; an existing-target conflict raises the caller's chosen error type
(`WorkspaceError` for sprite saves, `ExportError` for exports).

Some Aseprite exports take a *pattern* rather than a filename (``frames/walk_{frame}.png``)
and Aseprite expands it into many files, so the exact names are not known up front.
`ensure_output_pattern` applies the same policy to those by refusing when anything the
pattern could expand into already exists.
"""

from __future__ import annotations

import glob as _glob
import re
from pathlib import Path

from . import config
from .errors import WorkspaceError

# Aseprite's export placeholders: {frame}, {layer}, {tag}, {title}, {slice}, ...
_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z0-9_]*\}")


def ensure_output_path(
    path: str,
    *,
    overwrite: bool = False,
    create_parent: bool = True,
    error_type: type = WorkspaceError,
) -> Path:
    """Resolve `path` through the workspace sandbox and enforce the no-clobber policy.

    - Resolves via `config.resolve` (rejects absolute/`..`-escaping paths unless
      `ASEPRITE_MCP_ALLOW_ABSOLUTE=1`, and creates the parent directory only after the
      path is confirmed safe).
    - If the target already exists and `overwrite` is False, raises `error_type`.
    - Returns the resolved absolute `Path`.

    `create_parent` defaults to True because Aseprite will not create an output folder
    itself; pass False to validate a target without touching the filesystem.
    """
    # sandbox check, then the parent mkdir only once the path is confirmed safe
    resolved = config.resolve(str(path), create_parent=create_parent)
    if resolved.exists() and not overwrite:
        raise error_type(
            f"Output '{resolved}' already exists. Pass overwrite=True to replace it."
        )
    return resolved


def _pattern_to_glob(part: str) -> str:
    """Turn one path component into a glob, with `{placeholder}` -> `*`.

    Literal text is escaped so a name containing glob metacharacters (``[``, ``?``,
    ``*``) matches itself rather than acting as a wildcard. Otherwise
    ``a[b]_{frame}.png`` would report a false conflict against an unrelated ``ab_1.png``.
    """
    out: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(part):
        out.append(_glob.escape(part[cursor:match.start()]))
        out.append("*")
        cursor = match.end()
    out.append(_glob.escape(part[cursor:]))
    return "".join(out)


def expansion_matches(resolved: Path, *, limit: int = 20) -> list[Path]:
    """Existing files that `resolved` (a placeholder pattern) could expand into.

    Returns at most `limit` matches, enough to name a few in an error message without
    walking a huge directory. A path with no placeholder yields the path itself if it
    exists, so callers can treat both shapes uniformly.
    """
    parts = resolved.parts
    first = next((i for i, part in enumerate(parts) if _PLACEHOLDER_RE.search(part)), None)
    if first is None:
        return [resolved] if resolved.exists() else []

    base = Path(*parts[:first]) if first else Path(resolved.anchor or ".")
    pattern = "/".join(_pattern_to_glob(part) for part in parts[first:])
    found: list[Path] = []
    for match in base.glob(pattern):
        found.append(match)
        if len(found) >= limit:
            break
    return found


def ensure_output_pattern(
    pattern: str,
    *,
    overwrite: bool = False,
    error_type: type = WorkspaceError,
) -> Path:
    """No-clobber policy for a placeholder export pattern (``frames/walk_{frame}.png``).

    Aseprite expands the placeholders itself, so the concrete filenames are unknown to
    us. Instead of guessing them, this refuses when *anything* the pattern could expand
    into is already on disk, the conservative reading of "don't clobber". Returns the
    resolved absolute pattern `Path` for handing to the Aseprite CLI.
    """
    # sandbox check + safe parent mkdir: Aseprite expands the placeholders but will not
    # create the directory it writes them into.
    resolved = config.resolve(str(pattern), create_parent=True)
    if overwrite:
        return resolved
    existing = expansion_matches(resolved)
    if existing:
        shown = ", ".join(sorted(p.name for p in existing[:5]))
        more = "" if len(existing) <= 5 else f" (and {len(existing) - 5} more)"
        raise error_type(
            f"Output pattern '{resolved}' would overwrite existing files: {shown}{more}. "
            "Pass overwrite=True to replace them, or export to a new directory."
        )
    return resolved
