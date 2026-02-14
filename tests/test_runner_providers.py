"""Runner provider selection and task-scoped engine creation tests."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

from gralph.config import Config
from gralph.engines.base import EngineBase, EngineResult
from gralph.engines.claude import ClaudeEngine
from gralph.io_utils import open_text

if "gralph.tasks.io" not in sys.modules:
    tasks_io_stub = types.ModuleType("gralph.tasks.io")
    tasks_io_stub.mark_task_complete_in_file = lambda *_args, **_kwargs: None
    sys.modules["gralph.tasks.io"] = tasks_io_stub

from gralph.runner import Runner, _build_task_prompt
from gralph.scheduler import Scheduler, TaskState
from gralph.tasks.model import Task, TaskFile


class _AsyncTestEngine(EngineBase):
    """Simple async test engine that runs a short Python command."""

    def __init__(self, label: str) -> None:
        self.label = label

    def build_cmd(self, prompt: str) -> list[str]:
        return ["python", "-c", "pass"]

    def parse_output(self, raw: str) -> EngineResult:
        return EngineResult(text=raw)

    def run_async(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        stdout_file: Path | None = None,
        stderr_file: Path | None = None,
    ) -> subprocess.Popen:
        stdout_handle = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_handle = open_text(stderr_file, "w") if stderr_file else subprocess.PIPE
        return subprocess.Popen(
            ["python", "-c", "pass"],
            stdout=stdout_handle,
            stderr=stderr_handle,
            cwd=cwd,
        )


def _make_task_file(task_ids: list[str]) -> TaskFile:
    return TaskFile(branch_name="test", tasks=[Task(id=task_id) for task_id in task_ids])


def _worktree_factory(base_dir: Path):
    counter = 0

    def _create(*_args, **_kwargs):
        nonlocal counter
        counter += 1
        wt_dir = base_dir / f"wt-{counter}"
        wt_dir.mkdir(parents=True, exist_ok=True)
        return wt_dir, f"gralph/agent-{counter}"

    return _create


def _cleanup_slots(runner: Runner) -> None:
    for slot in runner.active:
        slot.proc.wait(timeout=5)
        for f in [slot.status_file, slot.output_file, slot.log_file, slot.stream_file]:
            f.unlink(missing_ok=True)


def _cleanup_slot_files(slot) -> None:
    for f in [slot.status_file, slot.output_file, slot.log_file, slot.stream_file]:
        f.unlink(missing_ok=True)


def test_round_robin_provider_assignment(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001", "TASK-002", "TASK-003", "TASK-004"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex", "gemini"],
        max_parallel=4,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ) as mock_get_engine:
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            for task_id in ["TASK-001", "TASK-002", "TASK-003", "TASK-004"]:
                runner._launch_agent(task_id, git_repo, worktree_base)

    assert [slot.provider for slot in runner.active] == [
        "claude",
        "codex",
        "gemini",
        "claude",
    ]
    assert [call.args[0] for call in mock_get_engine.call_args_list] == [
        "claude",
        "codex",
        "gemini",
        "claude",
    ]
    assert runner.provider_usage["claude"] == 2
    assert runner.provider_usage["codex"] == 1
    assert runner.provider_usage["gemini"] == 1
    assert runner.task_provider_attempts["TASK-001"] == ["claude"]
    assert runner.task_provider_attempts["TASK-002"] == ["codex"]
    assert runner.task_provider_attempts["TASK-003"] == ["gemini"]
    assert runner.task_provider_attempts["TASK-004"] == ["claude"]
    _cleanup_slots(runner)


def test_engine_instance_created_per_task_launch(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001", "TASK-002"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude"],
        max_parallel=2,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)
    created_engines: list[_AsyncTestEngine] = []

    def _engine_factory(provider: str, opencode_model: str = "") -> _AsyncTestEngine:
        engine = _AsyncTestEngine(f"{provider}-{len(created_engines)}")
        created_engines.append(engine)
        return engine

    with patch("gralph.runner.get_engine", side_effect=_engine_factory) as mock_get_engine:
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            runner._launch_agent("TASK-001", git_repo, worktree_base)
            runner._launch_agent("TASK-002", git_repo, worktree_base)

    assert mock_get_engine.call_count == 2
    assert runner.active[0].engine is created_engines[0]
    assert runner.active[1].engine is created_engines[1]
    assert runner.active[0].engine is not runner.active[1].engine
    _cleanup_slots(runner)


def test_retry_keeps_original_assigned_provider(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex"],
        max_parallel=1,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ) as mock_get_engine:
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            runner._launch_agent("TASK-001", git_repo, worktree_base)
            runner.sched.retry_task("TASK-001")
            runner._launch_agent("TASK-001", git_repo, worktree_base)

    assert [slot.provider for slot in runner.active] == ["claude", "claude"]
    assert [call.args[0] for call in mock_get_engine.call_args_list] == ["claude", "claude"]
    _cleanup_slots(runner)


def test_external_failure_retry_falls_back_to_next_provider(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex", "gemini"],
        max_parallel=1,
        max_retries=1,
        retry_delay=0,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    first_slot = None
    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ) as mock_get_engine:
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            with patch("gralph.runner.cleanup_agent_worktree"):
                with patch.object(runner, "_save_report"):
                    runner._launch_agent("TASK-001", git_repo, worktree_base)
                    first_slot = runner.active.pop()
                    first_slot.proc.wait(timeout=5)

                    runner._handle_failure(
                        first_slot,
                        git_repo,
                        "TASK-001",
                        "Rate limit exceeded",
                    )
                    assert runner.sched.state("TASK-001") == TaskState.PENDING
                    assert runner.task_providers["TASK-001"] == "codex"

                    runner._launch_agent("TASK-001", git_repo, worktree_base)

    assert [slot.provider for slot in runner.active] == ["codex"]
    assert [call.args[0] for call in mock_get_engine.call_args_list] == ["claude", "codex"]
    assert runner.provider_usage["claude"] == 1
    assert runner.provider_usage["codex"] == 1
    assert runner.provider_usage["gemini"] == 0
    assert runner.task_provider_attempts["TASK-001"] == ["claude", "codex"]
    _cleanup_slots(runner)
    if first_slot is not None:
        _cleanup_slot_files(first_slot)


def test_external_failure_retry_keeps_provider_when_only_one(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude"],
        max_parallel=1,
        max_retries=1,
        retry_delay=0,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    first_slot = None
    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ) as mock_get_engine:
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            with patch("gralph.runner.cleanup_agent_worktree"):
                with patch.object(runner, "_save_report"):
                    runner._launch_agent("TASK-001", git_repo, worktree_base)
                    first_slot = runner.active.pop()
                    first_slot.proc.wait(timeout=5)

                    runner._handle_failure(
                        first_slot,
                        git_repo,
                        "TASK-001",
                        "Rate limit exceeded",
                    )
                    assert runner.sched.state("TASK-001") == TaskState.PENDING
                    assert runner.task_providers["TASK-001"] == "claude"

                    runner._launch_agent("TASK-001", git_repo, worktree_base)

    assert [slot.provider for slot in runner.active] == ["claude"]
    assert [call.args[0] for call in mock_get_engine.call_args_list] == ["claude", "claude"]
    _cleanup_slots(runner)
    if first_slot is not None:
        _cleanup_slot_files(first_slot)


def test_merge_conflict_retry_keeps_provider_assignment(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex"],
        max_parallel=1,
        max_retries=1,
        retry_delay=0,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    first_slot = None
    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ):
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            with patch("gralph.runner.cleanup_agent_worktree"):
                with patch.object(runner, "_save_report"):
                    runner._launch_agent("TASK-001", git_repo, worktree_base)
                    first_slot = runner.active.pop()
                    first_slot.proc.wait(timeout=5)

                    runner._handle_failure(
                        first_slot,
                        git_repo,
                        "TASK-001",
                        "Automatic merge failed; CONFLICT (content)",
                        allow_provider_switch=False,
                    )

    assert runner.sched.state("TASK-001") == TaskState.PENDING
    assert runner.task_providers["TASK-001"] == "claude"
    if first_slot is not None:
        _cleanup_slot_files(first_slot)


def test_provider_assignment_is_sticky_and_wraps_in_round_robin() -> None:
    tf = _make_task_file(["TASK-001", "TASK-002", "TASK-003", "TASK-004"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex", "gemini"],
        max_parallel=1,
        base_branch="main",
    )
    runner = Runner(cfg, tf, _AsyncTestEngine("seed"), Scheduler(tf))

    assert runner._provider_for_task("TASK-001") == "claude"
    assert runner._provider_for_task("TASK-002") == "codex"
    # Repeated lookup for the same task must keep the assigned provider.
    assert runner._provider_for_task("TASK-001") == "claude"
    assert runner._provider_for_task("TASK-003") == "gemini"
    # Next unseen task wraps to the beginning.
    assert runner._provider_for_task("TASK-004") == "claude"


def test_rotate_provider_wraps_back_to_first_provider() -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex", "gemini"],
        max_parallel=1,
        base_branch="main",
    )
    runner = Runner(cfg, tf, _AsyncTestEngine("seed"), Scheduler(tf))
    runner.task_providers["TASK-001"] = "gemini"

    switch = runner._rotate_provider_for_task("TASK-001")
    assert switch == ("gemini", "claude")
    assert runner.task_providers["TASK-001"] == "claude"


def test_external_failure_retry_wraps_to_first_provider(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex", "gemini"],
        max_parallel=1,
        max_retries=1,
        retry_delay=0,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))
    runner.task_providers["TASK-001"] = "gemini"

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    first_slot = None
    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ) as mock_get_engine:
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            with patch("gralph.runner.cleanup_agent_worktree"):
                with patch.object(runner, "_save_report"):
                    runner._launch_agent("TASK-001", git_repo, worktree_base)
                    first_slot = runner.active.pop()
                    first_slot.proc.wait(timeout=5)

                    runner._handle_failure(
                        first_slot,
                        git_repo,
                        "TASK-001",
                        "Rate limit exceeded",
                    )
                    assert runner.sched.state("TASK-001") == TaskState.PENDING
                    assert runner.task_providers["TASK-001"] == "claude"

                    runner._launch_agent("TASK-001", git_repo, worktree_base)

    assert [slot.provider for slot in runner.active] == ["claude"]
    assert [call.args[0] for call in mock_get_engine.call_args_list] == ["gemini", "claude"]
    assert runner.provider_usage["claude"] == 1
    assert runner.provider_usage["codex"] == 0
    assert runner.provider_usage["gemini"] == 1
    assert runner.task_provider_attempts["TASK-001"] == ["gemini", "claude"]
    _cleanup_slots(runner)
    if first_slot is not None:
        _cleanup_slot_files(first_slot)


def test_internal_failure_does_not_rotate_provider_on_failure(git_repo: Path) -> None:
    tf = _make_task_file(["TASK-001"])
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex"],
        max_parallel=1,
        max_retries=1,
        retry_delay=0,
        base_branch="main",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))

    worktree_base = git_repo / "worktrees"
    worktree_base.mkdir(exist_ok=True)

    first_slot = None
    with patch(
        "gralph.runner.get_engine",
        side_effect=lambda provider, opencode_model="": _AsyncTestEngine(provider),
    ):
        with patch(
            "gralph.runner.create_agent_worktree",
            side_effect=_worktree_factory(worktree_base),
        ):
            with patch("gralph.runner.cleanup_agent_worktree"):
                with patch.object(runner, "_save_report"):
                    runner._launch_agent("TASK-001", git_repo, worktree_base)
                    first_slot = runner.active.pop()
                    first_slot.proc.wait(timeout=5)

                    runner._handle_failure(
                        first_slot,
                        git_repo,
                        "TASK-001",
                        "AssertionError: deterministic test failure",
                    )

    assert runner.sched.state("TASK-001") == TaskState.FAILED
    assert runner.task_providers["TASK-001"] == "claude"
    assert runner.provider_usage["claude"] == 1
    assert runner.provider_usage["codex"] == 0
    assert runner.task_provider_attempts["TASK-001"] == ["claude"]
    if first_slot is not None:
        _cleanup_slot_files(first_slot)


def test_task_prompt_includes_windows_powershell_guardrails() -> None:
    with patch("gralph.runner.platform.system", return_value="Windows"):
        prompt = _build_task_prompt(
            "TASK-001",
            "Sample task",
            "src/app.ts",
            skip_tests=False,
            skip_lint=False,
        )

    assert "SHELL COMPATIBILITY (Windows PowerShell):" in prompt
    assert "Do NOT use '&&' between commands" in prompt
    assert "$ErrorActionPreference = 'Stop'" in prompt
