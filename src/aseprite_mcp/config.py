"""Backwards-compatible shim. Config now lives in `aseprite_mcp.core.config`."""

from aseprite_mcp.core.config import (  # noqa: F401
    PROJECT_ROOT,
    allow_absolute,
    find_aseprite,
    resolve,
    timeout,
    workspace,
)
