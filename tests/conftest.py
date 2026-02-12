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
