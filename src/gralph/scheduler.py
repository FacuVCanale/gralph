"""DAG scheduler with mutex support for parallel task execution."""

from __future__ import annotations

from enum import Enum

from gralph import log
from gralph.tasks.model import TaskFile


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Scheduler:
    """Stateful DAG scheduler that tracks task readiness and mutex locks.

    Usage::

        sched = Scheduler(task_file)
        ready = sched.get_ready()      # tasks whose deps are done and mutex free
        sched.start_task(tid)           # pending -> running, lock mutexes
        sched.complete_task(tid)        # running -> done,  unlock mutexes
        sched.fail_task(tid)            # running -> failed, unlock mutexes
    """

    def __init__(self, tf: TaskFile) -> None:
        self._tf = tf
        self._state: dict[str, TaskState] = {}
        self._locked: dict[str, str] = {}  # mutex -> task_id

        # Build dep and mutex lookup
        self._deps: dict[str, list[str]] = {}
        self._mutex: dict[str, list[str]] = {}

        for task in tf.tasks:
            if task.completed:
                self._state[task.id] = TaskState.DONE
            else:
                self._state[task.id] = TaskState.PENDING
            self._deps[task.id] = task.depends_on
            self._mutex[task.id] = task.mutex

    # ── state queries ────────────────────────────────────────────

    def state(self, task_id: str) -> TaskState:
        return self._state.get(task_id, TaskState.PENDING)

    def count_pending(self) -> int:
        return sum(1 for s in self._state.values() if s == TaskState.PENDING)

    def count_running(self) -> int:
        return sum(1 for s in self._state.values() if s == TaskState.RUNNING)

    def count_done(self) -> int:
        return sum(1 for s in self._state.values() if s == TaskState.DONE)

    def count_failed(self) -> int:
        return sum(1 for s in self._state.values() if s == TaskState.FAILED)

    # ── dependency / mutex checks ────────────────────────────────

    def deps_satisfied(self, task_id: str) -> bool:
        for dep in self._deps.get(task_id, []):
            if not dep:
                continue
            if self._state.get(dep) != TaskState.DONE:
                return False
        return True

    def mutex_available(self, task_id: str) -> bool:
        for mx in self._mutex.get(task_id, []):
            if not mx:
                continue
            if mx in self._locked:
                return False
        return True

    def _lock_mutex(self, task_id: str) -> None:
        for mx in self._mutex.get(task_id, []):
            if mx:
                self._locked[mx] = task_id

    def _unlock_mutex(self, task_id: str) -> None:
        for mx in self._mutex.get(task_id, []):
            self._locked.pop(mx, None)

    # ── ready tasks ──────────────────────────────────────────────

    def get_ready(self) -> list[str]:
        """Return task IDs that are pending with deps satisfied and mutex free."""
        ready: list[str] = []
        for tid, st in self._state.items():
            if st == TaskState.PENDING:
                if self.deps_satisfied(tid) and self.mutex_available(tid):
                    ready.append(tid)
        return ready

    # ── transitions ──────────────────────────────────────────────

    def start_task(self, task_id: str) -> None:
        self._state[task_id] = TaskState.RUNNING
        self._lock_mutex(task_id)
        log.debug(f"Task {task_id}: pending -> running (mutex locked)")

    def complete_task(self, task_id: str) -> None:
        self._state[task_id] = TaskState.DONE
        self._unlock_mutex(task_id)
        log.debug(f"Task {task_id}: running -> done (mutex released)")

    def fail_task(self, task_id: str) -> None:
        self._state[task_id] = TaskState.FAILED
        self._unlock_mutex(task_id)
        log.debug(f"Task {task_id}: running -> failed (mutex released)")

    def retry_task(self, task_id: str) -> None:
        """Return a running task to pending for retry."""
        self._state[task_id] = TaskState.PENDING
        self._unlock_mutex(task_id)
        log.debug(f"Task {task_id}: running -> pending (retry)")

    # ── diagnostics ──────────────────────────────────────────────

    def check_deadlock(self) -> bool:
        """Return ``True`` if no progress is possible (deadlock)."""
        return (
            self.count_pending() > 0
            and self.count_running() == 0
            and len(self.get_ready()) == 0
        )

    def explain_block(self, task_id: str) -> str:
        """Human-readable explanation of why *task_id* is blocked."""
        reasons: list[str] = []

        blocked_deps = []
        for dep in self._deps.get(task_id, []):
            if not dep:
                continue
            st = self._state.get(dep, TaskState.PENDING)
            if st != TaskState.DONE:
                blocked_deps.append(f"{dep} ({st.value})")
        if blocked_deps:
            reasons.append(f"dependsOn: {' '.join(blocked_deps)}")

        blocked_mx = []
        for mx in self._mutex.get(task_id, []):
            if not mx:
                continue
            holder = self._locked.get(mx)
            if holder:
                blocked_mx.append(f"{mx} (held by {holder})")
        if blocked_mx:
            reasons.append(f"mutex: {' '.join(blocked_mx)}")

        return " ".join(reasons)

    def has_failed_deps(self, task_id: str) -> bool:
        """Check if any dependency of *task_id* has failed."""
        for dep in self._deps.get(task_id, []):
            if self._state.get(dep) == TaskState.FAILED:
                return True
        return False
