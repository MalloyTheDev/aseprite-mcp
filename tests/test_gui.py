"""Tests for the GUI companion tools.

These intentionally do NOT launch the Aseprite GUI (that would pop a window). They
only check capability detection and the missing-file guard.
"""

import pytest

from aseprite_mcp.runner import AsepriteError
from aseprite_mcp.tools import gui


def test_gui_available():
    out = gui.gui_available()
    assert out["available"] is True
    assert out["executable"]


def test_open_in_editor_missing_file_errors():
    with pytest.raises(AsepriteError, match="No such sprite"):
        gui.open_in_editor("gui/does_not_exist.aseprite")
