"""Task and TaskFile data models — stub for parallel task development."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    title: str = ""
    completed: bool = False
    depends_on: list[str] = field(default_factory=list)
    mutex: list[str] = field(default_factory=list)
    touches: list[str] = field(default_factory=list)


@dataclass
class TaskFile:
    branch_name: str = ""
    tasks: list[Task] = field(default_factory=list)

    def pending_ids(self) -> list[str]:
        return [t.id for t in self.tasks if not t.completed]

    def get_task(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None
