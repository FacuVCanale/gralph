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
        assert "stream-json" in cmd
        assert "--model" not in cmd

    def test_build_cmd_fallback_to_agent_when_not_in_path(self):
        with patch("gralph.engines.cursor.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            engine = CursorEngine()
            cmd = engine.build_cmd("hello")
        assert cmd[0] == "agent"
        assert "stream-json" in cmd

    def test_build_cmd_use_auto_adds_model_auto(self):
        with patch("gralph.engines.cursor.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            engine = CursorEngine()
            cmd = engine.build_cmd("hello", use_auto=True)
        assert cmd[0] == "agent"
        assert "--model" in cmd
        assert "auto" in cmd
