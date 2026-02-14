"""Provider matrix tests for the full CLI pipeline with mocked engines."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gralph.cli import main
from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import read_text, write_text


@pytest.fixture
def cli_runner():
    from click.testing import CliRunner

    return CliRunner()


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    write_text(repo_dir / "dummy.txt", "x")
    subprocess.run(["git", "add", "dummy.txt"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_AUTHOR_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "T",
        },
    )


class _PipelineEngine(EngineBase):
    def __init__(self, tasks_yaml: str, mode: str) -> None:
        self.tasks_yaml = tasks_yaml
        self.mode = mode

    def build_cmd(self, prompt: str) -> list[str]:
        return [sys.executable, "-c", "pass"]

    def parse_output(self, raw: str) -> EngineResult:
        return EngineResult(text=raw or "ok")

    def check_available(self) -> str | None:
        return None

    def run_sync(self, prompt: str, **kwargs) -> EngineResult:
        if self.mode == "file":
            match = re.search(r"Save the file as ([^\n]+)", prompt)
            if match:
                out_path = Path(match.group(1).strip().rstrip("."))
                out_path.parent.mkdir(parents=True, exist_ok=True)
                write_text(out_path, self.tasks_yaml)
            return EngineResult(text="ok")

        if self.mode == "stdout":
            return EngineResult(text=self.tasks_yaml)

        return EngineResult(text="ok")


@pytest.mark.parametrize(
    "provider_flag",
    ["--claude", "--opencode", "--codex", "--cursor", "--gemini"],
)
def test_pipeline_runs_end_to_end_for_each_provider(cli_runner, tmp_path: Path, provider_flag: str):
    provider = provider_flag.lstrip("-")
    from gralph.skills import REQUIRED_SKILLS

    for skill in REQUIRED_SKILLS:
        match provider:
            case "claude":
                target = tmp_path / ".claude" / "skills" / skill / "SKILL.md"
            case "codex":
                target = tmp_path / ".codex" / "skills" / skill / "SKILL.md"
            case "opencode":
                target = tmp_path / ".opencode" / "skill" / skill / "SKILL.md"
            case "cursor":
                target = tmp_path / ".cursor" / "rules" / f"{skill}.mdc"
            case "gemini":
                target = tmp_path / ".gemini" / "skills" / skill / "SKILL.md"
            case _:
                raise ValueError(provider)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text(target, f"# {skill}\n")

    prd_content = "# PRD: Provider Matrix\nprd-id: provider-matrix\n\nBody.\n"
    write_text(tmp_path / "PRD.md", prd_content)
    _init_git_repo(tmp_path)

    minimal_tasks = (
        "branchName: gralph/provider-matrix\n"
        "tasks:\n"
        "  - id: TASK-001\n"
        "    title: One\n"
        "    completed: false\n"
        "    dependsOn: []\n"
        "    mutex: []\n"
    )
    mock_engine = _PipelineEngine(tasks_yaml=minimal_tasks, mode="file")
    mock_runner = MagicMock()
    mock_runner.run.return_value = True

    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        with patch("gralph.engines.registry.get_engine", return_value=mock_engine):
            with patch("gralph.runner.Runner", return_value=mock_runner):
                result = cli_runner.invoke(
                    main,
                    [provider_flag, "--prd", "PRD.md"],
                    obj={},
                    catch_exceptions=False,
                )
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, result.output
    tasks_path = tmp_path / "artifacts" / "prd" / "provider-matrix" / "tasks.yaml"
    assert tasks_path.is_file()
    assert "TASK-001" in read_text(tasks_path)
    assert mock_runner.run.called

    progress_files = list((tmp_path / "artifacts").rglob("progress.txt"))
    assert progress_files, "expected at least one progress.txt"


@pytest.mark.parametrize(
    "provider_flag",
    ["--claude", "--opencode", "--codex", "--cursor", "--gemini"],
)
def test_pipeline_writes_tasks_yaml_from_stdout_fallback(cli_runner, tmp_path: Path, provider_flag: str):
    provider = provider_flag.lstrip("-")
    from gralph.skills import REQUIRED_SKILLS

    for skill in REQUIRED_SKILLS:
        match provider:
            case "claude":
                target = tmp_path / ".claude" / "skills" / skill / "SKILL.md"
            case "codex":
                target = tmp_path / ".codex" / "skills" / skill / "SKILL.md"
            case "opencode":
                target = tmp_path / ".opencode" / "skill" / skill / "SKILL.md"
            case "cursor":
                target = tmp_path / ".cursor" / "rules" / f"{skill}.mdc"
            case "gemini":
                target = tmp_path / ".gemini" / "skills" / skill / "SKILL.md"
            case _:
                raise ValueError(provider)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text(target, f"# {skill}\n")

    prd_content = "# PRD: Provider Matrix Fallback\nprd-id: provider-matrix-fallback\n\nBody.\n"
    write_text(tmp_path / "PRD.md", prd_content)
    _init_git_repo(tmp_path)

    minimal_tasks = (
        "branchName: gralph/provider-matrix-fallback\n"
        "tasks:\n"
        "  - id: TASK-001\n"
        "    title: One\n"
        "    completed: false\n"
        "    dependsOn: []\n"
        "    mutex: []\n"
    )
    mock_engine = _PipelineEngine(tasks_yaml=minimal_tasks, mode="stdout")
    mock_runner = MagicMock()
    mock_runner.run.return_value = True

    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        with patch("gralph.engines.registry.get_engine", return_value=mock_engine):
            with patch("gralph.runner.Runner", return_value=mock_runner):
                result = cli_runner.invoke(
                    main,
                    [provider_flag, "--prd", "PRD.md"],
                    obj={},
                    catch_exceptions=False,
                )
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, result.output
    tasks_path = tmp_path / "artifacts" / "prd" / "provider-matrix-fallback" / "tasks.yaml"
    assert tasks_path.is_file()
    assert "TASK-001" in read_text(tasks_path)
