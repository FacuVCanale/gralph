"""Contract tests for task data models used across loader/validator/runner."""

from __future__ import annotations

from dataclasses import fields

from gralph.tasks.model import Task, TaskFile


def test_task_has_merge_notes_field() -> None:
    names = {f.name for f in fields(Task)}
    assert "merge_notes" in names


def test_taskfile_has_version_field_with_default() -> None:
    names = {f.name for f in fields(TaskFile)}
    assert "version" in names
    assert TaskFile().version == 1
