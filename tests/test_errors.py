"""Tests for error handling: rate limit, stalled, external vs internal, deadlock, etc."""

from __future__ import annotations

from pathlib import Path

import pytest

from gralph.engines.base import EngineBase
from gralph.io_utils import write_text
from gralph.runner import _extract_error_from_logs, _is_external_failure
from gralph.scheduler import Scheduler
from gralph.tasks.model import Task, TaskFile


# ── External vs internal failure classification ────────────────────────────


class TestIsExternalFailure:
    """_is_external_failure must classify rate limit, stalled, timeout, etc. as external."""

    def test_empty_message_is_internal(self):
        assert _is_external_failure("") is False
        assert _is_external_failure("   ") is False

    def test_rate_limit_exceeded_is_external(self):
        assert _is_external_failure("Rate limit exceeded") is True
        assert _is_external_failure("rate limit hit") is True
        assert _is_external_failure("You've hit the rate limit") is True
        assert _is_external_failure("You've hit your limit · resets 3pm") is True

    def test_429_is_external(self):
        assert _is_external_failure("429 Too Many Requests") is True
        assert _is_external_failure("Error 429") is True

    def test_quota_and_too_many_requests(self):
        assert _is_external_failure("quota exceeded") is True
        assert _is_external_failure("too many requests") is True

    def test_timeout_is_external(self):
        assert _is_external_failure("timeout after 30s") is True
        assert _is_external_failure("Request timeout") is True
        assert _is_external_failure("ETIMEDOUT") is True

    def test_network_errors_are_external(self):
        assert _is_external_failure("network error") is True
        assert _is_external_failure("ECONNRESET") is True
        assert _is_external_failure("TLS handshake failed") is True
        assert _is_external_failure("certificate verify failed") is True
        assert _is_external_failure("SSL error") is True

    def test_permission_and_command_not_found(self):
        assert _is_external_failure("permission denied") is True
        assert _is_external_failure("command not found") is True
        assert _is_external_failure("CommandNotFoundException") is True
        assert _is_external_failure("ENOENT") is True
        assert _is_external_failure("EACCES") is True
        assert _is_external_failure("rejected: blocked by policy") is True

    def test_install_and_lockfile(self):
        assert _is_external_failure("BunInstallFailedError") is True
        assert _is_external_failure("lockfile is locked") is True
        assert _is_external_failure("npm install failed") is True

    def test_stalled_is_external(self):
        assert _is_external_failure("Agent 1 stalled for 600s") is True
        assert _is_external_failure("stalled") is True

    def test_merge_conflict_is_external(self):
        assert _is_external_failure(
            "Automatic merge failed; fix conflicts and then commit the result."
        ) is True
        assert _is_external_failure("CONFLICT (content): Merge conflict in src/app.ts") is True

    def test_merge_blocked_by_local_changes_is_not_external(self):
        assert _is_external_failure(
            "Your local changes to the following files would be overwritten by merge."
        ) is False

    def test_internal_errors_not_external(self):
        assert _is_external_failure("SyntaxError: invalid syntax") is False
        assert _is_external_failure("AssertionError") is False
        assert _is_external_failure("TypeError: expected str") is False
        assert _is_external_failure("logic error in code") is False


# ── Engine error detection ──────────────────────────────────────────────────


class TestEngineCheckErrors:
    """EngineBase._check_errors must detect rate limit and API errors in output."""

    def test_rate_limit_in_json(self):
        raw = '{"type":"message","text":"ok"}\n{"error":"rate_limit"}'
        assert EngineBase._check_errors(raw) == "Rate limit exceeded"

    def test_you_hit_your_limit_in_structured_error(self):
        raw = '{"error":"You\'ve hit your limit for this model."}'
        assert EngineBase._check_errors(raw) == "Rate limit exceeded"

    def test_you_hit_your_limit_plain_text_does_not_false_positive(self):
        raw = "You've hit your limit for this model."
        assert EngineBase._check_errors(raw) == ""

    def test_clean_output_empty(self):
        assert EngineBase._check_errors("") == ""
        assert EngineBase._check_errors("Some normal output") == ""

    def test_type_error_parsing(self):
        raw = '{"type":"error","error":{"message":"Something went wrong"}}'
        assert "Something went wrong" in EngineBase._check_errors(raw)

    def test_blocked_by_policy_detection(self):
        raw = '{"error":"rejected: blocked by policy"}'
        assert EngineBase._check_errors(raw) == "Blocked by policy"

    def test_does_not_false_positive_on_error_string_inside_text_payload(self):
        raw = (
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"Ejemplo: {\\\\\\"error\\\\\\":\\\\\\"rate_limit\\\\\\"}"}}'
        )
        assert EngineBase._check_errors(raw) == ""


# ── Log extraction ──────────────────────────────────────────────────────────


class TestExtractErrorFromLog:
    """_extract_error_from_logs must return last non-debug line."""

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert _extract_error_from_logs(tmp_path / "nonexistent.log") == ""

    def test_empty_file_returns_empty(self, tmp_path: Path):
        log = tmp_path / "out.log"
        write_text(log, "")
        assert _extract_error_from_logs(log) == ""

    def test_only_debug_lines_returns_last_line(self, tmp_path: Path):
        log = tmp_path / "out.log"
        write_text(log, "[DEBUG] a\n[DEBUG] b\n[DEBUG] c\n")
        assert _extract_error_from_logs(log) == "[DEBUG] c"

    def test_last_non_debug_line_returned(self, tmp_path: Path):
        log = tmp_path / "out.log"
        write_text(log, "[DEBUG] x\nError: rate limit exceeded\n[DEBUG] y\n")
        assert _extract_error_from_logs(log) == "Error: rate limit exceeded"

    def test_single_error_line(self, tmp_path: Path):
        log = tmp_path / "out.log"
        write_text(log, "Permission denied\n")
        assert _extract_error_from_logs(log) == "Permission denied"

    def test_fallback_to_stream_file(self, tmp_path: Path):
        stream = tmp_path / "out.stream"
        write_text(stream, '{"type":"error","error":{"message":"rate_limit hit"}}\n')
        assert _extract_error_from_logs(tmp_path / "missing.log", stream) == "rate_limit hit"

    def test_rate_limit_from_stream_includes_detail_message(self, tmp_path: Path):
        stream = tmp_path / "out.stream"
        write_text(
            stream,
            "\n".join(
                [
                    "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"You've hit your limit resets 3pm\"}]},\"error\":\"rate_limit\"}",
                    "{\"type\":\"result\",\"result\":\"You've hit your limit resets 3pm\",\"is_error\":true}",
                ]
            )
            + "\n",
        )
        msg = _extract_error_from_logs(tmp_path / "missing.log", stream)
        assert msg.startswith("Rate limit exceeded:")
        assert "resets 3pm" in msg

    def test_stream_blocked_by_policy_has_priority(self, tmp_path: Path):
        stream = tmp_path / "out.stream"
        write_text(
            stream,
            "\n".join(
                [
                    "{\"type\":\"item.completed\",\"item\":{\"type\":\"command_execution\",\"status\":\"failed\",\"aggregated_output\":\"command rejected: blocked by policy\"}}",
                    "{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"You've hit your limit for this model.\"}}",
                ]
            )
            + "\n",
        )
        assert _extract_error_from_logs(tmp_path / "missing.log", stream) == "Blocked by policy"

    def test_stream_success_result_with_is_error_false_is_ignored(self, tmp_path: Path):
        stream = tmp_path / "out.stream"
        write_text(
            stream,
            (
                '{"type":"result","subtype":"success","is_error":false,'
                '"result":"Installing dependencies and running checks"}\n'
            ),
        )
        assert _extract_error_from_logs(tmp_path / "missing.log", stream) == ""

    def test_stream_tool_call_completed_with_embedded_error_text_is_ignored(self, tmp_path: Path):
        stream = tmp_path / "out.stream"
        write_text(
            stream,
            (
                '{"type":"tool_call","subtype":"completed","call_id":"tool_1",'
                '"tool_call":{"editToolCall":{"args":{"path":"tests/server.test.ts",'
                '"streamContent":"expect((JSON.parse(response.body) as { error: string }).error).toBe(\\"Unauthorized\\");"},'
                '"result":{"success":{"path":"tests/server.test.ts"}}}}}\n'
            ),
        )
        assert _extract_error_from_logs(tmp_path / "missing.log", stream) == ""

    def test_stream_skips_tool_call_noise_and_recovers_prior_structured_error(
        self,
        tmp_path: Path,
    ):
        stream = tmp_path / "out.stream"
        write_text(
            stream,
            "\n".join(
                [
                    '{"type":"error","error":{"message":"rate_limit hit"}}',
                    '{"type":"tool_call","subtype":"completed","call_id":"tool_1",'
                    '"tool_call":{"editToolCall":{"args":{"path":"tests/server.test.ts",'
                    '"streamContent":"expect((JSON.parse(response.body) as { error: string }).error).toBe(\\"Unauthorized\\");"},'
                    '"result":{"success":{"path":"tests/server.test.ts"}}}}}',
                ]
            )
            + "\n",
        )
        assert _extract_error_from_logs(tmp_path / "missing.log", stream) == "rate_limit hit"

    def test_stream_result_with_is_error_true_uses_result_text(self, tmp_path: Path):
        stream = tmp_path / "out.stream"
        write_text(
            stream,
            (
                '{"type":"result","subtype":"error","is_error":true,'
                '"result":"Tool execution failed due to timeout"}\n'
            ),
        )
        assert _extract_error_from_logs(
            tmp_path / "missing.log",
            stream,
        ) == "Tool execution failed due to timeout"


# ── Failure type in report (classification consistency) ──────────────────────


class TestFailureTypeClassification:
    """Report failureType must be 'external' for infra errors, 'internal' otherwise."""

    def test_external_gets_external_type(self):
        msg = "Rate limit exceeded"
        failure_type = "external" if _is_external_failure(msg) else "internal"
        assert failure_type == "external"

    def test_internal_gets_internal_type(self):
        msg = "SyntaxError in file.py"
        failure_type = "external" if _is_external_failure(msg) else "internal"
        assert failure_type == "internal"

    def test_stalled_gets_external_type(self):
        msg = "Agent stalled for 600s. Killing…"
        failure_type = "external" if _is_external_failure(msg) else "internal"
        assert failure_type == "external"


# ── Deadlock and blocked tasks ──────────────────────────────────────────────


def _tf(tasks: list[Task]) -> TaskFile:
    return TaskFile(branch_name="test", tasks=tasks)


def _t(
    id: str,
    title: str = "",
    completed: bool = False,
    depends_on: list[str] | None = None,
    mutex: list[str] | None = None,
) -> Task:
    return Task(
        id=id,
        title=title or id,
        completed=completed,
        depends_on=depends_on or [],
        mutex=mutex or [],
    )


class TestDeadlockAndBlocked:
    """Deadlock detection and explain_block messages."""

    def test_deadlock_when_all_deps_failed(self):
        tf = _tf([
            _t("A", completed=False),
            _t("B", depends_on=["A"]),
        ])
        sched = Scheduler(tf)
        sched.start_task("A")
        sched.fail_task("A")
        assert sched.check_deadlock() is True
        assert sched.has_failed_deps("B") is True
        reason = sched.explain_block("B")
        assert "A" in reason
        assert "failed" in reason.lower()

    def test_no_deadlock_when_ready_available(self):
        tf = _tf([_t("A"), _t("B")])
        sched = Scheduler(tf)
        assert sched.check_deadlock() is False
        assert set(sched.get_ready()) == {"A", "B"}

    def test_explain_block_mutex_held(self):
        tf = _tf([
            _t("A", mutex=["db"]),
            _t("B", mutex=["db"]),
        ])
        sched = Scheduler(tf)
        sched.start_task("A")
        reason = sched.explain_block("B")
        assert "mutex" in reason.lower()
        assert "db" in reason
        assert "A" in reason


# ── Validation errors (ensure they are reported) ────────────────────────────


class TestValidationErrorsReported:
    """Validation must surface errors (validate_and_report returns False)."""

    def test_cycle_reported(self):
        from gralph.tasks.validate import validate_and_report

        tf = TaskFile(
            branch_name="test",
            tasks=[
                Task(id="A", title="A", depends_on=["B"]),
                Task(id="B", title="B", depends_on=["A"]),
            ],
        )
        result = validate_and_report(tf)
        assert result is False

    def test_duplicate_id_reported(self):
        from gralph.tasks.validate import validate_and_report

        tf = TaskFile(
            branch_name="test",
            tasks=[
                Task(id="X", title="First"),
                Task(id="X", title="Duplicate"),
            ],
        )
        result = validate_and_report(tf)
        assert result is False

    def test_missing_dep_reported(self):
        from gralph.tasks.validate import validate_and_report

        tf = TaskFile(
            branch_name="test",
            tasks=[
                Task(id="A", title="A", depends_on=["MISSING"]),
            ],
        )
        result = validate_and_report(tf)
        assert result is False


# ── Tasks I/O errors ────────────────────────────────────────────────────────


class TestTasksIoErrors:
    """load_task_file and invalid YAML."""

    def test_load_missing_file_raises(self):
        from gralph.tasks.io import load_task_file

        with pytest.raises((FileNotFoundError, OSError)):
            load_task_file(Path("/nonexistent/tasks.yaml"))

    def test_load_invalid_yaml_raises(self, tmp_path: Path):
        from gralph.tasks.io import load_task_file

        bad = tmp_path / "tasks.yaml"
        write_text(bad, "tasks:\n  - id: A\n    title: [unclosed\n")
        with pytest.raises(Exception):  # ruamel or yaml error
            load_task_file(bad)
