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

from gralph.runner import Runner
from gralph.scheduler import Scheduler
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
