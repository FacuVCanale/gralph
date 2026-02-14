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
from gralph.engines.gemini import GeminiEngine
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
            ("gemini", GeminiEngine),
        ],
    )
    def test_get_engine_returns_expected_adapter(self, name: str, expected_cls: type) -> None:
        assert isinstance(get_engine(name), expected_cls)

    def test_engine_names_include_all_supported_providers(self) -> None:
        assert set(ENGINE_NAMES) == {"claude", "opencode", "codex", "cursor", "gemini"}

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
        fake_proc = MagicMock()
        fake_proc.communicate.return_value = ("", "Permission denied\nmore details")
        fake_proc.returncode = 2

        with patch("gralph.engines.base.subprocess.Popen", return_value=fake_proc):
            result = engine.run_sync("prompt")

        assert result.return_code == 2
        assert result.error == "Permission denied"

    def test_run_sync_keyboard_interrupt_terminates_subprocess(self) -> None:
        engine = ClaudeEngine()
        fake_proc = MagicMock()
        fake_proc.communicate.side_effect = KeyboardInterrupt
        fake_proc.poll.return_value = None
        fake_proc.wait.return_value = 0

        with patch("gralph.engines.base.subprocess.Popen", return_value=fake_proc):
            with pytest.raises(KeyboardInterrupt):
                engine.run_sync("prompt")

        fake_proc.terminate.assert_called_once()

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

    def test_run_async_uses_new_process_group_on_windows(self, tmp_path: Path) -> None:
        engine = OpenCodeEngine()
        fake_proc = MagicMock()

        with patch("gralph.engines.base.sys.platform", "win32"), patch(
            "gralph.engines.opencode.subprocess.Popen", return_value=fake_proc
        ) as mock_popen:
            proc = engine.run_async(
                "prompt",
                cwd=tmp_path,
                stdout_file=tmp_path / "out.log",
                stderr_file=tmp_path / "err.log",
            )

        assert proc is fake_proc
        assert mock_popen.call_args.kwargs.get("creationflags", 0) != 0
        called_env = mock_popen.call_args.kwargs.get("env", {})
        assert called_env.get("OPENCODE_PERMISSION") == '{"*":"allow"}'

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.opencode.shutil.which", return_value=None):
            engine = OpenCodeEngine()
            assert engine.check_available() is not None


class TestCodexEngine:
    def test_build_cmd_uses_resolved_path(self) -> None:
        with patch("gralph.engines.codex.shutil.which", return_value="/usr/bin/codex"):
            engine = CodexEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[:3] == [
            "/usr/bin/codex",
            "--dangerously-bypass-approvals-and-sandbox",
            "exec",
        ]
        assert "--json" in cmd
        assert cmd[-1] == "hello"

    def test_build_cmd_use_stdin_appends_dash(self) -> None:
        engine = CodexEngine()
        cmd = engine.build_cmd("hello", use_stdin=True)
        assert cmd[-1] == "-"

    def test_build_cmd_uses_safe_mode_when_enabled_via_env(self) -> None:
        with patch("gralph.engines.codex.shutil.which", return_value="/usr/bin/codex"), patch.dict(
            "os.environ",
            {"GRALPH_CODEX_SAFE": "1"},
            clear=False,
        ):
            engine = CodexEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[:5] == ["/usr/bin/codex", "-a", "on-failure", "-s", "workspace-write"]
        assert cmd[5] == "exec"
        assert "--json" in cmd
        assert cmd[-1] == "hello"

    def test_build_cmd_respects_explicit_dangerous_false_env(self) -> None:
        with patch("gralph.engines.codex.shutil.which", return_value="/usr/bin/codex"), patch.dict(
            "os.environ",
            {"GRALPH_CODEX_DANGEROUS": "0"},
            clear=False,
        ):
            engine = CodexEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[:5] == ["/usr/bin/codex", "-a", "on-failure", "-s", "workspace-write"]
        assert cmd[5] == "exec"
        assert "--json" in cmd
        assert cmd[-1] == "hello"

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

        with patch("gralph.engines.base.sys.platform", "win32"), patch(
            "gralph.engines.codex.platform.system", return_value="Windows"
        ), patch("gralph.engines.codex.subprocess.Popen", return_value=fake_proc) as mock_popen:
            proc = engine.run_async(
                "prompt text",
                cwd=tmp_path,
                stdout_file=tmp_path / "out.log",
                stderr_file=tmp_path / "err.log",
            )

        assert proc is fake_proc
        assert "-" in mock_popen.call_args.args[0]
        assert mock_popen.call_args.kwargs.get("creationflags", 0) != 0
        fake_proc.stdin.write.assert_called_once_with("prompt text")
        fake_proc.stdin.close.assert_called_once()

    def test_parse_output_removes_generic_completion_line(self) -> None:
        engine = CodexEngine()
        result = engine.parse_output("Task completed successfully.\n")
        assert result.text == "Task completed"

    def test_parse_output_extracts_agent_message_from_json_events(self) -> None:
        engine = CodexEngine()
        raw = "\n".join(
            [
                '{"type":"thread.started","thread_id":"abc"}',
                '{"type":"item.completed","item":{"type":"reasoning","text":"internal"}}',
                '{"type":"item.completed","item":{"type":"agent_message","text":"1. Question A\\n2. Question B"}}',
            ]
        )
        result = engine.parse_output(raw)

        assert result.text == "1. Question A\n2. Question B"

    def test_parse_output_extracts_agent_message_from_content_array(self) -> None:
        engine = CodexEngine()
        raw = (
            '{"type":"item.completed","item":{"type":"agent_message","content":'
            '[{"type":"output_text","text":"Hello "},{"type":"output_text","text":"world"}]}}'
        )
        result = engine.parse_output(raw)

        assert result.text == "Hello world"

    def test_run_sync_does_not_false_positive_rate_limit_from_payload_text(self) -> None:
        engine = CodexEngine()
        done = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"Ejemplo: {\\\\\\"error\\\\\\":\\\\\\"rate_limit\\\\\\"}"}}'
            ),
            stderr="",
        )
        with patch("gralph.engines.codex.subprocess.run", return_value=done):
            result = engine.run_sync("prompt")

        assert result.error == ""
        assert "Ejemplo:" in result.text

    def test_run_sync_does_not_use_base_error_scanner_for_codex(self) -> None:
        engine = CodexEngine()
        done = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}',
            stderr="",
        )
        with patch("gralph.engines.codex.subprocess.run", return_value=done), patch.object(
            CodexEngine, "_check_errors", return_value="Rate limit exceeded"
        ):
            result = engine.run_sync("prompt")

        assert result.error == ""
        assert result.text == "ok"

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
        assert cmd[-1] == "hello"
        assert "--model" not in cmd

    def test_build_cmd_fallback_to_agent_when_not_in_path(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value=None):
            engine = CursorEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "agent"
        assert "stream-json" in cmd
        assert cmd[-1] == "hello"

    def test_build_cmd_use_auto_adds_model_auto(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value=None):
            engine = CursorEngine()
            cmd = engine.build_cmd("hello", use_auto=True)

        assert cmd[0] == "agent"
        assert "--model" in cmd
        assert "auto" in cmd
        assert cmd[-1] == "hello"

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

    def test_run_async_passes_prompt_argument_required_by_print_mode(self, tmp_path: Path) -> None:
        engine = CursorEngine()
        fake_proc = MagicMock()

        with patch("gralph.engines.cursor.shutil.which", return_value=None), patch(
            "gralph.engines.base.subprocess.Popen", return_value=fake_proc
        ) as mock_popen:
            proc = engine.run_async("prompt text", cwd=tmp_path)

        assert proc is fake_proc
        cmd = mock_popen.call_args.args[0]
        assert cmd[0] == "agent"
        assert "--print" in cmd
        assert cmd[-1] == "prompt text"

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.cursor.shutil.which", return_value=None):
            engine = CursorEngine()
            assert engine.check_available() is not None


class TestGeminiEngine:
    def test_build_cmd_uses_resolved_path_when_available(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value="/usr/bin/gemini"):
            engine = GeminiEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "/usr/bin/gemini"
        assert "-p" in cmd
        assert "hello" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd

    def test_build_cmd_fallback_to_gemini_when_not_in_path(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "gemini"

    def test_build_cmd_uses_stdin_marker_when_requested(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value="/usr/bin/gemini"):
            engine = GeminiEngine()
            cmd = engine.build_cmd("hello", use_stdin=True)

        assert "-" in cmd
        assert "-p" not in cmd
        assert "hello" not in cmd

    def test_parse_output_extracts_response_and_usage(self) -> None:
        engine = GeminiEngine()
        raw = '{"response":"done","usage":{"input_tokens":10,"output_tokens":5}}'
        result = engine.parse_output(raw)

        assert result.text == "done"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    def test_parse_output_extracts_usage_metadata_format(self) -> None:
        engine = GeminiEngine()
        raw = '{"result":"ok","usageMetadata":{"promptTokenCount":8,"candidatesTokenCount":3}}'
        result = engine.parse_output(raw)

        assert result.text == "ok"
        assert result.input_tokens == 8
        assert result.output_tokens == 3

    def test_parse_output_falls_back_to_raw_text(self) -> None:
        engine = GeminiEngine()
        result = engine.parse_output("plain text output\nmore text")
        assert result.text == "plain text output\nmore text"

    def test_parse_output_falls_back_when_empty(self) -> None:
        engine = GeminiEngine()
        result = engine.parse_output("")
        assert result.text == "Task completed"

    def test_run_sync_passes_short_prompt_via_cli_arg(self) -> None:
        engine = GeminiEngine()
        done = subprocess.CompletedProcess(
            args=["gemini"],
            returncode=0,
            stdout='{"response":"ok"}',
            stderr="",
        )
        with (
            patch("gralph.engines.gemini.subprocess.run", return_value=done) as mock_run,
            patch("gralph.engines.gemini.platform.system", return_value="Linux"),
        ):
            result = engine.run_sync("short prompt")

        assert result.text == "ok"
        assert mock_run.call_args.kwargs.get("input") is None

    def test_run_sync_passes_long_prompt_via_stdin(self) -> None:
        engine = GeminiEngine()
        long_prompt = "x" * 9000
        done = subprocess.CompletedProcess(
            args=["gemini"],
            returncode=0,
            stdout='{"response":"ok"}',
            stderr="",
        )
        with patch("gralph.engines.gemini.subprocess.run", return_value=done) as mock_run:
            result = engine.run_sync(long_prompt)

        assert result.text == "ok"
        assert mock_run.call_args.kwargs.get("input") == long_prompt

    def test_run_sync_uses_stdin_on_windows(self) -> None:
        engine = GeminiEngine()
        done = subprocess.CompletedProcess(
            args=["gemini"],
            returncode=0,
            stdout='{"response":"ok"}',
            stderr="",
        )
        with (
            patch("gralph.engines.gemini.subprocess.run", return_value=done) as mock_run,
            patch("gralph.engines.gemini.platform.system", return_value="Windows"),
        ):
            result = engine.run_sync("short prompt")

        assert result.text == "ok"
        assert mock_run.call_args.kwargs.get("input") == "short prompt"

    def test_run_sync_surfaces_stderr_on_failure(self) -> None:
        engine = GeminiEngine()
        failed = subprocess.CompletedProcess(
            args=["gemini"],
            returncode=1,
            stdout="",
            stderr="API key invalid\nmore details",
        )
        with patch("gralph.engines.gemini.subprocess.run", return_value=failed):
            result = engine.run_sync("prompt")

        assert result.return_code == 1
        assert result.error == "API key invalid"

    def test_run_async_writes_long_prompt_to_stdin(self, tmp_path: Path) -> None:
        engine = GeminiEngine()
        long_prompt = "x" * 9000
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()

        with patch("gralph.engines.gemini.subprocess.Popen", return_value=fake_proc):
            proc = engine.run_async(
                long_prompt,
                cwd=tmp_path,
                stdout_file=tmp_path / "out.log",
                stderr_file=tmp_path / "err.log",
            )

        assert proc is fake_proc
        fake_proc.stdin.write.assert_called_once_with(long_prompt)
        fake_proc.stdin.close.assert_called_once()

    def test_run_async_short_prompt_no_stdin(self, tmp_path: Path) -> None:
        engine = GeminiEngine()
        fake_proc = MagicMock()

        with (
            patch("gralph.engines.gemini.subprocess.Popen", return_value=fake_proc),
            patch("gralph.engines.gemini.platform.system", return_value="Linux"),
        ):
            proc = engine.run_async(
                "short",
                cwd=tmp_path,
                stdout_file=tmp_path / "out.log",
                stderr_file=tmp_path / "err.log",
            )

        assert proc is fake_proc
        fake_proc.stdin.write.assert_not_called()

    def test_check_available_reports_missing_binary(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            assert engine.check_available() is not None
