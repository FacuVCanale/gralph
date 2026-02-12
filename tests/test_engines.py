"""Tests for engine adapters and registry."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gralph.engines.base import EngineResult
from gralph.engines.claude import ClaudeEngine
from gralph.engines.codex import CodexEngine
from gralph.engines.cursor import CursorEngine
from gralph.engines.opencode import OpenCodeEngine
from gralph.engines.registry import ENGINE_NAMES, get_engine


class TestEngineRegistry:
    @pytest.mark.parametrize(
        ("name", "expected_cls"),
        [
            ("claude", ClaudeEngine),
            ("opencode", OpenCodeEngine),
            ("codex", CodexEngine),
            ("cursor", CursorEngine),
        ],
    )
    def test_get_engine_returns_expected_adapter(self, name: str, expected_cls: type) -> None:
        assert isinstance(get_engine(name), expected_cls)

    def test_engine_names_include_all_supported_providers(self) -> None:
        assert set(ENGINE_NAMES) == {"claude", "opencode", "codex", "cursor"}

    def test_unknown_engine_raises(self) -> None:
        with pytest.raises(ValueError):
            get_engine("unknown-provider")


class TestClaudeEngine:
    def test_build_cmd_uses_resolved_path_when_available(self) -> None:
        with patch("gralph.engines.claude.shutil.which", return_value="/usr/bin/claude"):
            engine = ClaudeEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "/usr/bin/claude"
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    def test_parse_output_extracts_result_and_usage(self) -> None:
        engine = ClaudeEngine()
        raw = (
            '{"type":"result","result":"done","usage":{"input_tokens":12,"output_tokens":7}}'
        )
        result = engine.parse_output(raw)

        assert result.text == "done"
        assert result.input_tokens == 12
        assert result.output_tokens == 7

    def test_parse_output_falls_back_when_no_result_line(self) -> None:
        engine = ClaudeEngine()
        result = engine.parse_output('{"type":"assistant","text":"hi"}')
        assert result.text == "Task completed"

    def test_run_sync_surfaces_first_stderr_line_when_subprocess_fails(self) -> None:
        engine = ClaudeEngine()
        failed = subprocess.CompletedProcess(
            args=["claude"],
            returncode=2,
            stdout="",
            stderr="Permission denied\nmore details",
        )
        with patch("gralph.engines.base.subprocess.run", return_value=failed):
            result = engine.run_sync("prompt")

        assert result.return_code == 2
        assert result.error == "Permission denied"

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.claude.shutil.which", return_value=None):
            engine = ClaudeEngine()
            assert engine.check_available() is not None


class TestOpenCodeEngine:
    def test_build_cmd_includes_model_and_resolved_binary(self) -> None:
        with patch("gralph.engines.opencode.shutil.which", return_value="/usr/bin/opencode"):
            engine = OpenCodeEngine(model="opencode/my-model")
            cmd = engine.build_cmd("hello")

        assert cmd[:4] == ["/usr/bin/opencode", "run", "--format", "json"]
        assert "--model" in cmd
        assert "opencode/my-model" in cmd
        assert cmd[-1] == "hello"

    def test_parse_output_extracts_text_tokens_and_cost(self) -> None:
        engine = OpenCodeEngine()
        raw = "\n".join(
            [
                '{"type":"text","part":{"text":"hello "}}',
                '{"type":"text","part":{"text":"world"}}',
                '{"type":"step_finish","part":{"tokens":{"input":3,"output":4},"cost":"0.01"}}',
            ]
        )
        result = engine.parse_output(raw)

        assert result.text == "hello world"
        assert result.input_tokens == 3
        assert result.output_tokens == 4
        assert result.actual_cost == "0.01"

    def test_run_sync_sets_permission_env_var(self, tmp_path: Path) -> None:
        engine = OpenCodeEngine()
        done = subprocess.CompletedProcess(
            args=["opencode"],
            returncode=0,
            stdout='{"type":"text","part":{"text":"ok"}}',
            stderr="",
        )
        with patch("gralph.engines.opencode.subprocess.run", return_value=done) as mock_run:
            result = engine.run_sync("prompt", cwd=tmp_path)

        called_env = mock_run.call_args.kwargs.get("env", {})
        assert called_env.get("OPENCODE_PERMISSION") == '{"*":"allow"}'
        assert result.error == ""
        assert result.text == "ok"

    def test_run_sync_surfaces_first_stderr_line_when_subprocess_fails(self) -> None:
        engine = OpenCodeEngine()
        failed = subprocess.CompletedProcess(
            args=["opencode"],
            returncode=1,
            stdout="",
            stderr="network unavailable\nmore details",
        )
        with patch("gralph.engines.opencode.subprocess.run", return_value=failed):
            result = engine.run_sync("prompt")

        assert result.return_code == 1
        assert result.error == "network unavailable"

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.opencode.shutil.which", return_value=None):
            engine = OpenCodeEngine()
            assert engine.check_available() is not None


class TestCodexEngine:
    def test_build_cmd_uses_resolved_path(self) -> None:
        with patch("gralph.engines.codex.shutil.which", return_value="/usr/bin/codex"):
            engine = CodexEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[:4] == ["/usr/bin/codex", "exec", "--full-auto", "--json"]
        assert cmd[-1] == "hello"

    def test_build_cmd_use_stdin_appends_dash(self) -> None:
        engine = CodexEngine()
        cmd = engine.build_cmd("hello", use_stdin=True)
        assert cmd[-1] == "-"

    def test_run_sync_on_windows_uses_stdin_input(self) -> None:
        engine = CodexEngine()
        done = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout="Task completed successfully.\n",
            stderr="",
        )
        with patch("gralph.engines.codex.platform.system", return_value="Windows"), patch(
            "gralph.engines.codex.subprocess.run", return_value=done
        ) as mock_run:
            result = engine.run_sync("prompt text")

        assert result.return_code == 0
        assert result.text == "Task completed"
        assert "-" in mock_run.call_args.args[0]
        assert mock_run.call_args.kwargs.get("input") == "prompt text"

    def test_run_sync_surfaces_stderr_when_non_zero_return_code(self) -> None:
        engine = CodexEngine()
        failed = subprocess.CompletedProcess(
            args=["codex"],
            returncode=3,
            stdout="",
            stderr="command not found\nextra",
        )
        with patch("gralph.engines.codex.subprocess.run", return_value=failed):
            result = engine.run_sync("prompt")

        assert result.return_code == 3
        assert result.error == "command not found"

    def test_run_async_on_windows_writes_prompt_to_stdin(self, tmp_path: Path) -> None:
        engine = CodexEngine()
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()

        with patch("gralph.engines.codex.platform.system", return_value="Windows"), patch(
            "gralph.engines.codex.subprocess.Popen", return_value=fake_proc
        ) as mock_popen:
            proc = engine.run_async(
                "prompt text",
                cwd=tmp_path,
                stdout_file=tmp_path / "out.log",
                stderr_file=tmp_path / "err.log",
            )

        assert proc is fake_proc
        assert "-" in mock_popen.call_args.args[0]
        fake_proc.stdin.write.assert_called_once_with("prompt text")
        fake_proc.stdin.close.assert_called_once()

    def test_parse_output_removes_generic_completion_line(self) -> None:
        engine = CodexEngine()
        result = engine.parse_output("Task completed successfully.\n")
        assert result.text == "Task completed"

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.codex.shutil.which", return_value=None):
            engine = CodexEngine()
            assert engine.check_available() is not None


class TestCursorEngine:
    def test_build_cmd_uses_resolved_path_when_agent_in_path(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value="/usr/bin/agent"):
            engine = CursorEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "/usr/bin/agent"
        assert "stream-json" in cmd
        assert "--model" not in cmd

    def test_build_cmd_fallback_to_agent_when_not_in_path(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value=None):
            engine = CursorEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "agent"
        assert "stream-json" in cmd

    def test_build_cmd_use_auto_adds_model_auto(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value=None):
            engine = CursorEngine()
            cmd = engine.build_cmd("hello", use_auto=True)

        assert cmd[0] == "agent"
        assert "--model" in cmd
        assert "auto" in cmd

    def test_parse_output_falls_back_to_assistant_message(self) -> None:
        engine = CursorEngine()
        raw = '{"type":"assistant","message":{"content":[{"text":"assistant text"}]}}'
        result = engine.parse_output(raw)
        assert result.text == "assistant text"

    def test_run_sync_retries_with_auto_when_rate_limited(self) -> None:
        engine = CursorEngine()
        first = EngineResult(text="", error="Rate limit exceeded", return_code=1)
        second = EngineResult(text="ok", error="", return_code=0)

        with patch.object(engine, "_run_once", side_effect=[first, second]) as mock_once:
            result = engine.run_sync("prompt")

        assert result.text == "ok"
        assert mock_once.call_count == 2
        assert mock_once.call_args_list[1].kwargs.get("use_auto") is True

    def test_run_sync_does_not_retry_non_rate_errors(self) -> None:
        engine = CursorEngine()
        first = EngineResult(text="", error="SyntaxError", return_code=1)

        with patch.object(engine, "_run_once", return_value=first) as mock_once:
            result = engine.run_sync("prompt")

        assert result.error == "SyntaxError"
        assert mock_once.call_count == 1

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value=None):
            engine = CursorEngine()
            assert engine.check_available() is not None
