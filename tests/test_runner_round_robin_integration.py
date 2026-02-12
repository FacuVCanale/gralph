"""Integration tests for full Runner round-robin provider fallback behavior."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from gralph import git_ops
from gralph.config import Config
from gralph.engines.base import EngineBase, EngineResult
from gralph.engines.claude import ClaudeEngine
from gralph.io_utils import open_text, read_text
from gralph.scheduler import Scheduler
from gralph.tasks.model import Task, TaskFile

if "gralph.tasks.io" not in sys.modules:
    tasks_io_stub = types.ModuleType("gralph.tasks.io")
    tasks_io_stub.mark_task_complete_in_file = lambda *_args, **_kwargs: None
    sys.modules["gralph.tasks.io"] = tasks_io_stub

from gralph.runner import Runner


@dataclass
class _ProviderScenario:
    outcomes_by_task: dict[str, list[str]]
    attempts_by_task: dict[str, int] = field(default_factory=dict)
    launches: list[tuple[str, str, str]] = field(default_factory=list)

    def next_outcome(self, task_id: str) -> tuple[int, str]:
        attempt = self.attempts_by_task.get(task_id, 0) + 1
        self.attempts_by_task[task_id] = attempt

        outcomes = self.outcomes_by_task.get(task_id, ["success"])
        idx = min(attempt - 1, len(outcomes) - 1)
        return attempt, outcomes[idx]


class _ScenarioEngine(EngineBase):
    def __init__(self, provider: str, scenario: _ProviderScenario) -> None:
        self.provider = provider
        self.scenario = scenario

    def build_cmd(self, prompt: str) -> list[str]:
        return [sys.executable, "-c", "pass"]

    def parse_output(self, raw: str) -> EngineResult:
        return EngineResult(text=raw)

    def check_available(self) -> str | None:
        return None

    def run_async(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        stdout_file: Path | None = None,
        stderr_file: Path | None = None,
    ) -> subprocess.Popen:
        match = re.search(r"^TASK ID:\s*(\S+)", prompt, flags=re.MULTILINE)
        if not match:
            raise AssertionError("TASK ID missing from prompt")
        task_id = match.group(1)
        attempt, outcome = self.scenario.next_outcome(task_id)
        self.scenario.launches.append((task_id, self.provider, outcome))

        if outcome == "rate_limit":
            cmd = [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('Rate limit exceeded\\n'); sys.exit(1)",
            ]
        elif outcome == "success":
            commit_script = (
                "from pathlib import Path\n"
                "import subprocess\n"
                "import sys\n"
                "task_id, provider, attempt = sys.argv[1], sys.argv[2], sys.argv[3]\n"
                "out = Path(f'{task_id.lower()}-{provider}-attempt-{attempt}.txt')\n"
                "out.write_text(f'{task_id}:{provider}:{attempt}\\n', encoding='utf-8')\n"
                "subprocess.run(['git', 'add', str(out)], check=True)\n"
                "subprocess.run(\n"
                "    ['git', 'commit', '-m', f'{task_id} via {provider} attempt {attempt}'],\n"
                "    check=True,\n"
                ")\n"
            )
            cmd = [sys.executable, "-c", commit_script, task_id, self.provider, str(attempt)]
        else:
            raise AssertionError(f"Unknown test outcome: {outcome}")

        stdout_handle = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_handle = open_text(stderr_file, "w") if stderr_file else subprocess.PIPE
        return subprocess.Popen(cmd, stdout=stdout_handle, stderr=stderr_handle, cwd=cwd)


def _task_file(task_ids: list[str]) -> TaskFile:
    return TaskFile(branch_name="test", tasks=[Task(id=task_id, title=task_id) for task_id in task_ids])


def _run_scenario(
    git_repo: Path,
    outcomes_by_task: dict[str, list[str]],
) -> tuple[Runner, _ProviderScenario, bool]:
    tf = _task_file(list(outcomes_by_task))
    cfg = Config(
        ai_engine="claude",
        providers=["claude", "codex", "gemini"],
        max_parallel=3,
        max_retries=1,
        retry_delay=0,
        base_branch=git_ops.current_branch(cwd=git_repo),
        artifacts_dir="artifacts/test",
    )
    runner = Runner(cfg, tf, ClaudeEngine(), Scheduler(tf))
    scenario = _ProviderScenario(outcomes_by_task=outcomes_by_task)

    def _engine_factory(provider: str, opencode_model: str = "") -> _ScenarioEngine:
        return _ScenarioEngine(provider, scenario)

    old_cwd = os.getcwd()
    try:
        os.chdir(git_repo)
        with patch("gralph.runner.get_engine", side_effect=_engine_factory):
            ok = runner.run()
    finally:
        os.chdir(old_cwd)

    return runner, scenario, ok


def test_run_end_to_end_round_robin_with_next_provider_fallback(git_repo: Path) -> None:
    runner, scenario, ok = _run_scenario(
        git_repo,
        {
            "TASK-001": ["success"],
            "TASK-002": ["rate_limit", "success"],
            "TASK-003": ["success"],
        },
    )

    assert ok is True
    assert runner.sched.count_done() == 3
    assert runner.provider_usage == {"claude": 1, "codex": 1, "gemini": 2}

    assert [(task, provider) for task, provider, _ in scenario.launches[:3]] == [
        ("TASK-001", "claude"),
        ("TASK-002", "codex"),
        ("TASK-003", "gemini"),
    ]
    assert scenario.launches[3][:2] == ("TASK-002", "gemini")
    assert runner.task_provider_attempts["TASK-002"] == ["codex", "gemini"]

    report = json.loads(read_text(git_repo / "artifacts" / "test" / "reports" / "TASK-002.json"))
    assert report["status"] == "done"
    assert report["provider"] == "gemini"
    assert report["providerAttempts"] == ["codex", "gemini"]
    assert report["attempt"] == 2
    assert report["retries"] == 1


def test_run_end_to_end_fallback_wraps_from_last_provider_to_first(git_repo: Path) -> None:
    runner, scenario, ok = _run_scenario(
        git_repo,
        {
            "TASK-001": ["success"],
            "TASK-002": ["success"],
            "TASK-003": ["rate_limit", "success"],
        },
    )

    assert ok is True
    assert runner.sched.count_done() == 3
    assert runner.provider_usage == {"claude": 2, "codex": 1, "gemini": 1}

    assert [(task, provider) for task, provider, _ in scenario.launches[:3]] == [
        ("TASK-001", "claude"),
        ("TASK-002", "codex"),
        ("TASK-003", "gemini"),
    ]
    assert scenario.launches[3][:2] == ("TASK-003", "claude")
    assert runner.task_provider_attempts["TASK-003"] == ["gemini", "claude"]

    report = json.loads(read_text(git_repo / "artifacts" / "test" / "reports" / "TASK-003.json"))
    assert report["status"] == "done"
    assert report["provider"] == "claude"
    assert report["providerAttempts"] == ["gemini", "claude"]
    assert report["attempt"] == 2
    assert report["retries"] == 1
