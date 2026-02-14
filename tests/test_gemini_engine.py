"""Focused unit tests for GeminiEngine: build_cmd, parse_output, check_available."""

from __future__ import annotations

from unittest.mock import patch


from gralph.engines.gemini import GeminiEngine


class TestGeminiEngineBuildCmd:
    """Tests for GeminiEngine.build_cmd()."""

    def test_resolved_path_used_when_which_finds_binary(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value="/usr/bin/gemini"):
            engine = GeminiEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "/usr/bin/gemini"

    def test_fallback_name_when_not_in_path(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            cmd = engine.build_cmd("hello")

        assert cmd[0] == "gemini"

    def test_output_format_json_always_present(self) -> None:
        engine = GeminiEngine()
        cmd = engine.build_cmd("test prompt")

        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "json"

    def test_prompt_passed_with_p_flag_by_default(self) -> None:
        engine = GeminiEngine()
        cmd = engine.build_cmd("my prompt")

        assert "-p" in cmd
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "my prompt"

    def test_stdin_marker_replaces_prompt_arg(self) -> None:
        engine = GeminiEngine()
        cmd = engine.build_cmd("my prompt", use_stdin=True)

        assert "-" in cmd
        assert "-p" not in cmd
        assert "my prompt" not in cmd

    def test_full_command_structure_without_stdin(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            cmd = engine.build_cmd("do stuff")

        assert cmd == ["gemini", "--output-format", "json", "-p", "do stuff"]

    def test_full_command_structure_with_stdin(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            cmd = engine.build_cmd("do stuff", use_stdin=True)

        assert cmd == ["gemini", "--output-format", "json", "-"]

    def test_prompt_with_special_characters(self) -> None:
        engine = GeminiEngine()
        prompt = 'fix the "bug" in file.py && rm -rf /'
        cmd = engine.build_cmd(prompt)

        assert prompt in cmd

    def test_empty_prompt(self) -> None:
        engine = GeminiEngine()
        cmd = engine.build_cmd("")

        assert "-p" in cmd
        assert "" in cmd


class TestGeminiEngineParseOutput:
    """Tests for GeminiEngine.parse_output()."""

    def test_response_field_extracted(self) -> None:
        engine = GeminiEngine()
        raw = '{"response":"hello world"}'
        result = engine.parse_output(raw)
        assert result.text == "hello world"

    def test_result_field_extracted(self) -> None:
        engine = GeminiEngine()
        raw = '{"result":"completed task"}'
        result = engine.parse_output(raw)
        assert result.text == "completed task"

    def test_text_field_extracted(self) -> None:
        engine = GeminiEngine()
        raw = '{"text":"text field content"}'
        result = engine.parse_output(raw)
        assert result.text == "text field content"

    def test_response_takes_priority_over_result(self) -> None:
        engine = GeminiEngine()
        raw = '{"response":"from response","result":"from result"}'
        result = engine.parse_output(raw)
        assert result.text == "from response"

    def test_result_takes_priority_over_text(self) -> None:
        engine = GeminiEngine()
        raw = '{"result":"from result","text":"from text"}'
        result = engine.parse_output(raw)
        assert result.text == "from result"

    def test_usage_field_token_extraction(self) -> None:
        engine = GeminiEngine()
        raw = '{"response":"ok","usage":{"input_tokens":100,"output_tokens":50}}'
        result = engine.parse_output(raw)

        assert result.input_tokens == 100
        assert result.output_tokens == 50

    def test_usage_metadata_field_token_extraction(self) -> None:
        engine = GeminiEngine()
        raw = '{"result":"ok","usageMetadata":{"promptTokenCount":80,"candidatesTokenCount":30}}'
        result = engine.parse_output(raw)

        assert result.input_tokens == 80
        assert result.output_tokens == 30

    def test_first_text_wins_across_multiple_lines(self) -> None:
        engine = GeminiEngine()
        raw = '{"response":"first"}\n{"response":"second"}'
        result = engine.parse_output(raw)
        assert result.text == "first"

    def test_usage_from_later_line_still_captured(self) -> None:
        engine = GeminiEngine()
        raw = (
            '{"response":"answer"}\n'
            '{"usage":{"input_tokens":5,"output_tokens":3}}'
        )
        result = engine.parse_output(raw)

        assert result.text == "answer"
        assert result.input_tokens == 5
        assert result.output_tokens == 3

    def test_invalid_json_lines_skipped(self) -> None:
        engine = GeminiEngine()
        raw = 'not json\n{"response":"valid"}\nalso not json'
        result = engine.parse_output(raw)
        assert result.text == "valid"

    def test_mixed_empty_and_valid_lines(self) -> None:
        engine = GeminiEngine()
        raw = '\n\n{"response":"ok"}\n\n'
        result = engine.parse_output(raw)
        assert result.text == "ok"

    def test_falls_back_to_raw_when_no_json_fields(self) -> None:
        engine = GeminiEngine()
        raw = "plain text output\nmore text"
        result = engine.parse_output(raw)
        assert result.text == "plain text output\nmore text"

    def test_falls_back_to_raw_when_json_has_no_known_fields(self) -> None:
        engine = GeminiEngine()
        raw = '{"unknown_field":"value"}'
        result = engine.parse_output(raw)
        assert result.text == '{"unknown_field":"value"}'

    def test_empty_string_yields_task_completed(self) -> None:
        engine = GeminiEngine()
        result = engine.parse_output("")
        assert result.text == "Task completed"

    def test_none_input_yields_task_completed(self) -> None:
        engine = GeminiEngine()
        result = engine.parse_output(None)  # type: ignore[arg-type]
        assert result.text == "Task completed"

    def test_whitespace_only_yields_task_completed(self) -> None:
        engine = GeminiEngine()
        result = engine.parse_output("   \n\n  ")
        assert result.text == "Task completed"

    def test_zero_tokens_when_no_usage(self) -> None:
        engine = GeminiEngine()
        result = engine.parse_output('{"response":"ok"}')
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    def test_partial_usage_fields(self) -> None:
        engine = GeminiEngine()
        raw = '{"response":"ok","usage":{"input_tokens":10}}'
        result = engine.parse_output(raw)
        assert result.input_tokens == 10
        assert result.output_tokens == 0


class TestGeminiEngineCheckAvailable:
    """Tests for GeminiEngine.check_available()."""

    def test_returns_none_when_binary_found(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value="/usr/bin/gemini"):
            engine = GeminiEngine()
            assert engine.check_available() is None

    def test_returns_error_when_binary_missing(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            err = engine.check_available()
            assert err is not None

    def test_error_message_mentions_gemini_cli(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            err = engine.check_available()
            assert "Gemini CLI" in err

    def test_error_message_includes_install_url(self) -> None:
        with patch("gralph.engines.gemini.shutil.which", return_value=None):
            engine = GeminiEngine()
            err = engine.check_available()
            assert "https://github.com/google-gemini/gemini-cli" in err
