"""Tests for engine adapters."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gralph.engines.cursor import CursorEngine


class TestCursorEngine:
    """Cursor engine uses resolved path in build_cmd so subprocess finds agent."""

    def test_build_cmd_uses_resolved_path_when_agent_in_path(self):
        with patch("gralph.engines.cursor.shutil") as mock_shutil:
            mock_shutil.which.return_value = "/usr/bin/agent"
            engine = CursorEngine()
            cmd = engine.build_cmd("hello")
        assert cmd[0] == "/usr/bin/agent"
        assert cmd[-1] == "hello"

    def test_build_cmd_fallback_to_agent_when_not_in_path(self):
        with patch("gralph.engines.cursor.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            engine = CursorEngine()
            cmd = engine.build_cmd("hello")
        assert cmd[0] == "agent"
        assert cmd[-1] == "hello"
