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


# ===== the selection sidecar ==========================================================
# A selection is not stored in the .aseprite file, so it is kept in a `.msk` beside the
# sprite and reloaded whenever that sprite is opened. The suffix lives here, with the rest
# of the path policy, because two different tools need to agree on it: the selection tools
# that write it and the sprite tools that have to throw it away.
SELECTION_SUFFIX = ".msk"


def selection_sidecar(sprite_path: Path) -> Path:
    """Where this sprite's selection is kept.

    Beside the sprite rather than in a subdirectory, so it is discoverable: someone
    looking at the workspace can see that a sprite has a selection attached.

    The suffix is *appended* to the whole filename (`hero.aseprite` ->
    `hero.aseprite.msk`) rather than replacing the extension, and that is the whole
    point of this function rather than a `with_suffix` call at each site.
    `with_suffix(".msk")` mapped `hero.aseprite` and `hero.png` onto one `hero.msk`,
    which is two sprites sharing one selection:

      * a selection set on `hero.aseprite` then scoped every edit to `hero.png`, with a
        rectangle measured against a different sprite's dimensions, and both calls
        reported `selection_applied: true` because from the Lua side it was;
      * `save_sprite_as("hero.aseprite", "hero.png")` called
        `discard_selection_sidecar` on the destination and deleted `hero.msk`, which was
        the *source's* selection, directly against the comment at that call site saying
        the source's own sidecar is untouched;
      * and the prelude derived the sidecar a third way, by stripping the last extension
        with a Lua pattern, which disagreed with `with_suffix` for any name whose final
        component begins with a dot: `.hidden` saved to `.hidden.msk` and loaded from
        `.msk`, so a selection on such a sprite was written and then never read.

    Appending removes all three at once, because the mapping from sprite to sidecar is
    now injective and the two derivations are the same operation. The Lua half lives in
    `core.luagen`'s `open_sprite`; the two have to be changed together, and
    `test_hardening` pins that they agree.
    """
    path = Path(sprite_path)
    return path.with_name(path.name + SELECTION_SUFFIX)


def discard_selection_sidecar(sprite_path: Path) -> bool:
    """Forget the selection belonging to a sprite that is being replaced.

    A selection is part of a sprite's state, and replacing the sprite replaces its state.
    Without this, `create_sprite(overwrite=True)` wrote a brand new sprite over an old one
    and left the old one's `.msk` sitting beside it, so the new sprite silently opened with
    a selection inherited from a sprite that no longer existed. Every edit outside that
    rectangle was then dropped, and the error that eventually surfaced came from a later
    call ("Nothing to shade: no pixel matched"), several steps from the cause and clean on
    a fresh workspace, which made it look like nondeterminism rather than a leftover file.

    Only for tools that write a *sprite*. An export still must not call this, but the
    reason is now only the obvious one, that an export is not a new sprite: since
    `selection_sidecar` appends rather than replacing the extension, `hero.png` and
    `hero.aseprite` no longer name one `hero.msk`, so an export that did call this would
    forget its own target's selection and not the source sprite's.

    Returns whether there was one to forget. A sidecar that exists and cannot be removed
    raises rather than being swallowed, because that is the bug this exists to prevent: the
    caller asked for the sprite to be replaced, and handing back a new sprite still carrying
    an old one's selection is the failure, not the error about it.
    """
    try:
        selection_sidecar(sprite_path).unlink()
    except FileNotFoundError:
        return False
    return True
