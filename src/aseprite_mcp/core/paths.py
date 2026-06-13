"""Output-path helpers — resolve through the workspace sandbox with no-clobber protection.

Output-writing tools are **no-clobber by default**: `ensure_output_path` refuses to write
over an existing file unless `overwrite=True`. Sandbox/escape violations still raise
`WorkspaceError`; an existing-target conflict raises the caller's chosen error type
(`WorkspaceError` for sprite saves, `ExportError` for exports).
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .errors import WorkspaceError


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
    """
    resolved = config.resolve(str(path))  # sandbox check + safe parent mkdir
    if not create_parent:  # config.resolve already created it; nothing extra to do
        pass
    if resolved.exists() and not overwrite:
        raise error_type(
            f"Output '{resolved}' already exists. Pass overwrite=True to replace it."
        )
    return resolved
