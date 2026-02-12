"""Tests for gralph.scheduler — DAG scheduler with mutex support."""

from __future__ import annotations

import pytest

from gralph.tasks.model import Task, TaskFile
from gralph.scheduler import Scheduler, TaskState


# ── Helpers ─────────────────────────────────────────────────────────


def _t(
    id: str,
    title: str = "",
    completed: bool = False,
    depends_on: list[str] | None = None,
    mutex: list[str] | None = None,
) -> Task:
    return Task(
        id=id,
        title=title or f"Task {id}",
        completed=completed,
        depends_on=depends_on or [],
        mutex=mutex or [],
    )


def _tf(tasks: list[Task]) -> TaskFile:
    return TaskFile(branch_name="test", tasks=tasks)


# ═══════════════════════════════════════════════════════════════════
#  Basic State Management
# ═══════════════════════════════════════════════════════════════════


class TestSchedulerState:
    """Tests for scheduler state tracking."""

    def test_initial_state_pending(self):
        """Incomplete tasks start as PENDING."""
        sched = Scheduler(_tf([_t("A")]))
        assert sched.state("A") == TaskState.PENDING

    def test_initial_state_done(self):
        """Completed tasks start as DONE."""
        sched = Scheduler(_tf([_t("A", completed=True)]))
        assert sched.state("A") == TaskState.DONE

    def test_counts(self):
        """State counts are accurate."""
        sched = Scheduler(_tf([
            _t("A", completed=True),
            _t("B"),
            _t("C"),
        ]))
        assert sched.count_done() == 1
        assert sched.count_pending() == 2
        assert sched.count_running() == 0
        assert sched.count_failed() == 0

    def test_start_task(self):
        """start_task transitions to RUNNING."""
        sched = Scheduler(_tf([_t("A")]))
        sched.start_task("A")
        assert sched.state("A") == TaskState.RUNNING
        assert sched.count_running() == 1
        assert sched.count_pending() == 0

    def test_complete_task(self):
        """complete_task transitions to DONE."""
        sched = Scheduler(_tf([_t("A")]))
        sched.start_task("A")
        sched.complete_task("A")
        assert sched.state("A") == TaskState.DONE
        assert sched.count_done() == 1
        assert sched.count_running() == 0

    def test_fail_task(self):
        """fail_task transitions to FAILED."""
        sched = Scheduler(_tf([_t("A")]))
        sched.start_task("A")
        sched.fail_task("A")
        assert sched.state("A") == TaskState.FAILED
        assert sched.count_failed() == 1
        assert sched.count_running() == 0

    def test_retry_task_returns_to_pending(self):
        """retry_task transitions RUNNING back to PENDING."""
        sched = Scheduler(_tf([_t("A")]))
        sched.start_task("A")
        sched.retry_task("A")
        assert sched.state("A") == TaskState.PENDING
        assert "A" in sched.get_ready()


# ═══════════════════════════════════════════════════════════════════
#  Dependency Ordering
# ═══════════════════════════════════════════════════════════════════


class TestDependencyOrdering:
    """Tests for dependency-based task readiness."""

    def test_independent_tasks_all_ready(self):
        """Tasks with no dependencies are all ready."""
        sched = Scheduler(_tf([_t("A"), _t("B"), _t("C")]))
        ready = sched.get_ready()
        assert set(ready) == {"A", "B", "C"}

    def test_dependent_task_not_ready(self):
        """Task with unsatisfied dependency is not ready."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        ready = sched.get_ready()
        assert "A" in ready
        assert "B" not in ready

    def test_dependent_task_ready_after_dep_done(self):
        """Task becomes ready after dependency is completed."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        sched.start_task("A")
        sched.complete_task("A")
        ready = sched.get_ready()
        assert "B" in ready

    def test_chain_order(self):
        """A -> B -> C executes in correct order."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
            _t("C", depends_on=["B"]),
        ]))

        # Only A is ready first
        assert sched.get_ready() == ["A"]

        sched.start_task("A")
        sched.complete_task("A")
        # Now B is ready
        assert sched.get_ready() == ["B"]

        sched.start_task("B")
        sched.complete_task("B")
        # Now C is ready
        assert sched.get_ready() == ["C"]

    def test_diamond_order(self):
        """Diamond: A -> (B, C) -> D executes correctly."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
            _t("C", depends_on=["A"]),
            _t("D", depends_on=["B", "C"]),
        ]))

        assert sched.get_ready() == ["A"]

        sched.start_task("A")
        sched.complete_task("A")
        ready = sched.get_ready()
        assert set(ready) == {"B", "C"}
        assert "D" not in ready

        sched.start_task("B")
        sched.complete_task("B")
        # D still not ready — C is pending
        assert "D" not in sched.get_ready()

        sched.start_task("C")
        sched.complete_task("C")
        assert sched.get_ready() == ["D"]

    def test_deps_satisfied_skips_empty_strings(self):
        """Empty strings in depends_on are ignored."""
        sched = Scheduler(_tf([
            _t("A", depends_on=[""]),
        ]))
        assert sched.deps_satisfied("A") is True
        assert "A" in sched.get_ready()


# ═══════════════════════════════════════════════════════════════════
#  Mutex Exclusion
# ═══════════════════════════════════════════════════════════════════


class TestMutexExclusion:
    """Tests for mutex-based exclusion."""

    def test_mutex_blocks_concurrent(self):
        """Two tasks with the same mutex cannot run concurrently."""
        sched = Scheduler(_tf([
            _t("A", mutex=["db"]),
            _t("B", mutex=["db"]),
        ]))

        # Both are ready initially
        ready = sched.get_ready()
        assert set(ready) == {"A", "B"}

        # Start A — B should now be blocked
        sched.start_task("A")
        ready = sched.get_ready()
        assert "B" not in ready

    def test_mutex_released_on_complete(self):
        """Mutex is released when task completes, unblocking the next task."""
        sched = Scheduler(_tf([
            _t("A", mutex=["db"]),
            _t("B", mutex=["db"]),
        ]))

        sched.start_task("A")
        sched.complete_task("A")
        ready = sched.get_ready()
        assert "B" in ready

    def test_mutex_released_on_fail(self):
        """Mutex is released when task fails, unblocking the next task."""
        sched = Scheduler(_tf([
            _t("A", mutex=["db"]),
            _t("B", mutex=["db"]),
        ]))

        sched.start_task("A")
        sched.fail_task("A")
        ready = sched.get_ready()
        assert "B" in ready

    def test_different_mutexes_no_conflict(self):
        """Tasks with different mutexes can run concurrently."""
        sched = Scheduler(_tf([
            _t("A", mutex=["db"]),
            _t("B", mutex=["cache"]),
        ]))

        sched.start_task("A")
        ready = sched.get_ready()
        assert "B" in ready

    def test_mutex_and_dependency_combined(self):
        """Both dependency and mutex must be satisfied for readiness."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"], mutex=["db"]),
            _t("C", mutex=["db"]),
        ]))

        # A and C are ready, B is not (dep on A)
        ready = sched.get_ready()
        assert "A" in ready
        assert "C" in ready
        assert "B" not in ready

        # Start C (takes mutex), complete A
        sched.start_task("C")
        sched.start_task("A")
        sched.complete_task("A")

        # B still blocked by mutex (C is running with "db")
        ready = sched.get_ready()
        assert "B" not in ready

        # Complete C — now B is ready (dep done + mutex free)
        sched.complete_task("C")
        ready = sched.get_ready()
        assert "B" in ready


# ═══════════════════════════════════════════════════════════════════
#  Deadlock Detection
# ═══════════════════════════════════════════════════════════════════


class TestDeadlockDetection:
    """Tests for deadlock detection."""

    def test_no_deadlock_normal(self):
        """Normal task flow has no deadlock."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        assert sched.check_deadlock() is False

    def test_deadlock_all_deps_failed(self):
        """Deadlock when all dependencies have failed."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        sched.start_task("A")
        sched.fail_task("A")
        # B depends on A which failed — B will never be ready
        assert sched.check_deadlock() is True

    def test_no_deadlock_when_tasks_running(self):
        """Not a deadlock if tasks are still running."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        sched.start_task("A")
        assert sched.check_deadlock() is False

    def test_no_deadlock_all_done(self):
        """Not a deadlock when all tasks are done."""
        sched = Scheduler(_tf([
            _t("A", completed=True),
            _t("B", completed=True),
        ]))
        assert sched.check_deadlock() is False


# ═══════════════════════════════════════════════════════════════════
#  Diagnostics
# ═══════════════════════════════════════════════════════════════════


class TestDiagnostics:
    """Tests for explain_block and has_failed_deps."""

    def test_explain_block_dependency(self):
        """explain_block shows pending dependency."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        explanation = sched.explain_block("B")
        assert "A" in explanation
        assert "pending" in explanation

    def test_explain_block_mutex(self):
        """explain_block shows mutex holder."""
        sched = Scheduler(_tf([
            _t("A", mutex=["db"]),
            _t("B", mutex=["db"]),
        ]))
        sched.start_task("A")
        explanation = sched.explain_block("B")
        assert "db" in explanation
        assert "A" in explanation

    def test_has_failed_deps(self):
        """has_failed_deps detects failed dependencies."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        sched.start_task("A")
        sched.fail_task("A")
        assert sched.has_failed_deps("B") is True

    def test_has_failed_deps_false(self):
        """has_failed_deps returns False when deps are OK."""
        sched = Scheduler(_tf([
            _t("A"),
            _t("B", depends_on=["A"]),
        ]))
        assert sched.has_failed_deps("B") is False
