"""Shared fixtures for gralph tests."""

from __future__ import annotations

import pytest

from gralph.tasks.model import Task, TaskFile


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
