"""Real end-to-end DAG execution tests (opt-in via --run-e2e)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from gralph.cli import main
from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text, read_text, write_text

_TaskDef = tuple[str, str, tuple[str, ...]]


@dataclass(frozen=True)
class _GraphScenario:
    name: str
    prd_id: str
    branch_name: str
    tasks: tuple[_TaskDef, ...]
    must_start_after: tuple[tuple[str, str], ...]

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(task_id for task_id, _title, _deps in self.tasks)


@dataclass
class _RunState:
    launches: list[str] = field(default_factory=list)


def _yaml_list(values: tuple[str, ...]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def _build_tasks_yaml(branch_name: str, tasks: tuple[_TaskDef, ...]) -> str:
    lines = [f"branchName: {branch_name}", "tasks:"]
    for task_id, title, depends_on in tasks:
        lines.extend(
            [
                f"  - id: {task_id}",
                f'    title: "{title}"',
                "    completed: false",
                f"    dependsOn: {_yaml_list(depends_on)}",
                "    mutex: []",
            ]
        )
    return "\n".join(lines) + "\n"


def _scenarios() -> tuple[_GraphScenario, ...]:
    scenario_a_tasks: tuple[_TaskDef, ...] = (
        ("SETUP-001", "Create shared baseline", ()),
        ("SETUP-002", "Create optional env", ()),
        ("TASK-001", "Build independent feature", ()),
        ("TASK-002", "Build setup-dependent feature", ("SETUP-001",)),
        (
            "TASK-003",
            "Integrate all pieces",
            ("SETUP-001", "SETUP-002", "TASK-001", "TASK-002"),
        ),
    )
    scenario_b_tasks: tuple[_TaskDef, ...] = (
        ("SETUP-001", "Create base scaffold", ()),
        ("SETUP-002", "Extend scaffold", ("SETUP-001",)),
        ("TASK-001", "Build independent vertical slice", ()),
        ("TASK-002", "Build feature from setup chain", ("SETUP-002",)),
        (
            "TASK-003",
            "Final integration task",
            ("SETUP-001", "SETUP-002", "TASK-001", "TASK-002"),
        ),
    )

    return (
        _GraphScenario(
            name="parallel-setups-with-join",
            prd_id="e2e-setups-graph-a",
            branch_name="gralph/e2e-setups-graph-a",
            tasks=scenario_a_tasks,
            must_start_after=(
                ("TASK-002", "SETUP-001"),
                ("TASK-003", "SETUP-001"),
                ("TASK-003", "SETUP-002"),
                ("TASK-003", "TASK-001"),
                ("TASK-003", "TASK-002"),
            ),
        ),
        _GraphScenario(
            name="setup-chain-with-join",
            prd_id="e2e-setups-graph-b",
            branch_name="gralph/e2e-setups-graph-b",
            tasks=scenario_b_tasks,
            must_start_after=(
                ("SETUP-002", "SETUP-001"),
                ("TASK-002", "SETUP-002"),
                ("TASK-003", "SETUP-001"),
                ("TASK-003", "SETUP-002"),
                ("TASK-003", "TASK-001"),
                ("TASK-003", "TASK-002"),
            ),
        ),
    )


class _E2EPipelineEngine(EngineBase):
    """Single engine used for metadata generation + task execution."""

    def __init__(self, *, tasks_yaml: str, state: _RunState) -> None:
        self.tasks_yaml = tasks_yaml
        self.state = state

    def __deepcopy__(self, memo: dict[int, object]) -> _E2EPipelineEngine:
        # Keep one shared state object across task launches.
        return self

    def build_cmd(self, prompt: str) -> list[str]:
        return [sys.executable, "-c", "pass"]

    def parse_output(self, raw: str) -> EngineResult:
        return EngineResult(text=raw or "ok")

    def check_available(self) -> str | None:
        return None

    def run_sync(self, prompt: str, **kwargs) -> EngineResult:
        del kwargs
        match = re.search(r"Save the file as ([^\n]+)", prompt)
        if match:
            out_path = Path(match.group(1).strip().rstrip("."))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            write_text(out_path, self.tasks_yaml)
        return EngineResult(text="ok")

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
            raise AssertionError("TASK ID missing from runner prompt")
        task_id = match.group(1)
        self.state.launches.append(task_id)

        script = (
            "from pathlib import Path\n"
            "import subprocess\n"
            "import sys\n"
            "task_id = sys.argv[1]\n"
            "out = Path('generated') / f'{task_id.lower()}.txt'\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_text(f'{task_id}\\n', encoding='utf-8')\n"
            "subprocess.run(['git', 'add', str(out)], check=True)\n"
            "subprocess.run(['git', 'commit', '-m', f'e2e: {task_id}'], check=True)\n"
        )
        cmd = [sys.executable, "-c", script, task_id]

        stdout_handle = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_handle = open_text(stderr_file, "w") if stderr_file else subprocess.PIPE
        return subprocess.Popen(cmd, stdout=stdout_handle, stderr=stderr_handle, cwd=cwd)


def _git_stdout(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda scenario: scenario.name)
def test_e2e_pipeline_with_setups_and_tasks_graphs(git_repo: Path, scenario: _GraphScenario) -> None:
    prd_path = git_repo / "PRD.md"
    write_text(
        prd_path,
        (
            f"# PRD: {scenario.name}\n\n"
            f"prd-id: {scenario.prd_id}\n\n"
            "E2E test graph for setup/task orchestration.\n"
        ),
    )

    state = _RunState()
    tasks_yaml = _build_tasks_yaml(scenario.branch_name, scenario.tasks)
    engine = _E2EPipelineEngine(tasks_yaml=tasks_yaml, state=state)

    cli_runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(git_repo)
        with patch("gralph.notify.notify_done"), patch("gralph.notify.notify_error"):
            with patch("gralph.engines.registry.get_engine", return_value=engine):
                result = cli_runner.invoke(
                    main,
                    [
                        "--codex",
                        "--prd",
                        "PRD.md",
                        "--max-parallel",
                        "3",
                        "--max-retries",
                        "0",
                        "--retry-delay",
                        "0",
                    ],
                    obj={},
                    catch_exceptions=False,
                )
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, result.output

    assert len(state.launches) == len(scenario.task_ids)
    for task_id in scenario.task_ids:
        assert state.launches.count(task_id) == 1
    assert state.launches[-1] == "TASK-003"

    launch_index = {task_id: state.launches.index(task_id) for task_id in scenario.task_ids}
    for task_id, required_task in scenario.must_start_after:
        assert launch_index[task_id] > launch_index[required_task]

    run_dirs = sorted((git_repo / "artifacts").glob("run-*"))
    assert run_dirs
    reports_dir = run_dirs[-1] / "reports"
    for task_id in scenario.task_ids:
        report = json.loads(read_text(reports_dir / f"{task_id}.json"))
        assert report["status"] == "done"

    for task_id in scenario.task_ids:
        assert (git_repo / "generated" / f"{task_id.lower()}.txt").is_file()

    current = _git_stdout(git_repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert current == scenario.branch_name
    assert _git_stdout(git_repo, "branch", "--list", scenario.branch_name).strip()

    assert not _git_stdout(git_repo, "branch", "--list", "gralph/agent-*").strip()

    worktree_output = _git_stdout(git_repo, "worktree", "list", "--porcelain")
    assert "refs/heads/gralph/agent-" not in worktree_output
    worktree_count = sum(1 for line in worktree_output.splitlines() if line.startswith("worktree "))
    assert worktree_count == 1
