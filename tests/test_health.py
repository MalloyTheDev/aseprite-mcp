"""Test the health_check self-test tool (requires Aseprite; auto-skips otherwise)."""

import asyncio

import pytest

from aseprite_mcp.core import config
from aseprite_mcp.core.errors import WorkspaceError
from aseprite_mcp.tools import health


def test_health_check_round_trip():
    out = asyncio.run(health.health_check())
    assert out["aseprite_found"] is True
    assert out["can_create_sprite"] is True
    assert out["can_export_png"] is True
    assert out["ok"] is True
    assert out["tools_registered"] >= 90
    assert out["aseprite_version"]


@pytest.mark.pure
def test_the_workspace_reported_is_the_resolved_one(tmp_path, monkeypatch):
    """#99: this tool reported the configured value while every other tool returned the
    resolved one. Behind a relocated Documents folder the two differ by drive letter,
    which is also what a sandbox escape looks like, and a caller cannot tell the two
    readings apart from the strings alone."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(ws))

    out = asyncio.run(health.health_check())

    assert out["workspace"] == str(ws.resolve())
    assert out["workspace"] == str(config.resolved_workspace())
    assert "workspace_error" not in out


def test_an_unusable_workspace_is_reported_rather_than_raised(monkeypatch):
    """The one failure this tool has to survive reporting. Reading the workspace while
    building the result dict meant an unwritable directory raised out of health_check
    itself, so the tool whose job is to say what is wrong said nothing at all and took
    every other check down with it."""
    def refuse():
        raise WorkspaceError("Cannot use 'X' as the workspace: denied.")
    monkeypatch.setattr(config, "workspace", refuse)

    out = asyncio.run(health.health_check())

    assert "denied" in out["workspace_error"]
    assert out["ok"] is False, "no filename-taking tool can work without a workspace"
    assert out["aseprite_found"] is True, "the rest of the self-test still ran"
