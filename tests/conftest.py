"""Shared fixtures for gralph tests.

File handling in tests:
- Use tmp_path for any directory or file creation so tests are isolated and cleaned up.
- Use gralph.io_utils read_text/write_text for consistent UTF-8 I/O.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gralph.io_utils import write_text
from gralph.skills import REQUIRED_SKILLS
from gralph.tasks.model import Task, TaskFile


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register opt-in switch for expensive end-to-end tests."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests marked with 'e2e'.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip e2e tests unless explicitly enabled."""
    if config.getoption("--run-e2e"):
        return

    skip_e2e = pytest.mark.skip(
        reason="E2E tests are skipped by default. Use --run-e2e to include them.",
    )
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test"], cwd=tmp_path, capture_output=True
    )
    write_text(tmp_path / "README.md", "# Test")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True
    )
    return tmp_path


def _make_task(
    id: str,
    title: str = "",
    completed: bool = False,
    depends_on: list[str] | None = None,
    mutex: list[str] | None = None,
    touches: list[str] | None = None,
) -> Task:
    return Task(
        id=id,
        title=title or f"Task {id}",
        completed=completed,
        depends_on=depends_on or [],
        mutex=mutex or [],
        touches=touches or [],
    )


def _make_task_file(tasks: list[Task], branch_name: str = "test") -> TaskFile:
    return TaskFile(branch_name=branch_name, tasks=tasks)


@pytest.fixture
def make_task():
    """Factory fixture that creates Task instances."""
    return _make_task


@pytest.fixture
def make_task_file():
    """Factory fixture that creates TaskFile instances."""
    return _make_task_file


def _skill_target(repo: Path, engine: str, skill: str) -> Path:
    match engine:
        case "claude":
            return repo / ".claude" / "skills" / skill / "SKILL.md"
        case "codex":
            return repo / ".codex" / "skills" / skill / "SKILL.md"
        case "opencode":
            return repo / ".opencode" / "skill" / skill / "SKILL.md"
        case "cursor":
            return repo / ".cursor" / "rules" / f"{skill}.mdc"
        case "gemini":
            return repo / ".gemini" / "skills" / skill / "SKILL.md"
        case _:
            raise ValueError(f"Unsupported engine for skills fixture: {engine}")


@pytest.fixture
def install_fake_skills():
    """Create minimal required skill files for one engine under a repo root."""

    def _install(repo: Path, engine: str) -> None:
        for skill in REQUIRED_SKILLS:
            target = _skill_target(repo, engine, skill)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text(target, f"# {skill}\n")

    return _install
