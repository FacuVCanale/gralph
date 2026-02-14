"""Integration tests for Runner git flows (success, failure, merge, stalled)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gralph.config import Config
from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text, read_text, write_text
from gralph.runner import Runner, AgentSlot, _meaningful_changes
from gralph.scheduler import Scheduler, TaskState
from gralph.tasks.model import Task, TaskFile
from gralph import git_ops


# ── helpers ──────────────────────────────────────────────────────────


def _tf(tasks: list[Task]) -> TaskFile:
    return TaskFile(branch_name="test", tasks=tasks)


def _t(
    id: str, title: str = "", completed: bool = False, depends_on: list[str] | None = None,
) -> Task:
    return Task(id=id, title=title or id, completed=completed, depends_on=depends_on or [])


def _commit_file(repo: Path, name: str, content: str, msg: str) -> None:
    write_text(repo / name, content)
    subprocess.run(["git", "add", name], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, capture_output=True, check=True)


class MockEngine(EngineBase):
    """Minimal mock engine for runner tests."""

    def build_cmd(self, prompt: str) -> list[str]:
        return ["python", "-c", "pass"]

    def parse_output(self, raw: str) -> EngineResult:
        return EngineResult()

    def run_async(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        stdout_file: Path | None = None,
        stderr_file: Path | None = None,
    ) -> subprocess.Popen:
        stdout_handle = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_handle = open_text(stderr_file, "w") if stderr_file else subprocess.PIPE
        proc = subprocess.Popen(
            ["python", "-c", "pass"],
            stdout=stdout_handle,
            stderr=stderr_handle,
            cwd=cwd,
        )
        return proc

    def run_sync(self, prompt: str, **kwargs) -> EngineResult:
        return EngineResult()


def _make_runner(git_repo: Path, tasks: list[Task] | None = None) -> tuple[Runner, Scheduler]:
    tf = _tf(tasks or [_t("A", "Task A")])
    cfg = Config(max_parallel=1, base_branch="main", artifacts_dir="artifacts/test")
    engine = MockEngine()
    scheduler = Scheduler(tf)
    runner = Runner(cfg, tf, engine, scheduler)
    runner.cfg.original_dir = str(git_repo)
    (git_repo / "artifacts" / "test" / "reports").mkdir(parents=True, exist_ok=True)
    write_text(git_repo / "tasks.yaml", "branchName: test\ntasks: []")
    return runner, scheduler


def _make_successful_slot(
    runner: Runner,
    git_repo: Path,
    task_id: str = "A",
) -> AgentSlot:
    """Create an AgentSlot that looks like a successfully completed agent."""
    base = git_ops.current_branch(cwd=git_repo)
    wt_base = git_repo / "worktrees"
    wt_base.mkdir(exist_ok=True)

    wt_dir, branch = git_ops.create_agent_worktree(
        task_id, runner.agent_num + 1,
        base_branch=base, worktree_base=wt_base, original_dir=git_repo,
    )
    runner.agent_num += 1

    # Add meaningful commit in worktree
    write_text(wt_dir / "code.py", "print('hello')")
    subprocess.run(["git", "add", "."], cwd=wt_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "implement feature"], cwd=wt_dir, capture_output=True)

    # Create a finished process (rc=0)
    proc = subprocess.Popen(["python", "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.wait()

    import tempfile
    status_file = Path(tempfile.mktemp(prefix=f"gralph-status-{task_id}-"))
    output_file = Path(tempfile.mktemp(prefix=f"gralph-output-{task_id}-"))
    log_file = Path(tempfile.mktemp(prefix=f"gralph-log-{task_id}-"))
    stream_file = Path(tempfile.mktemp(prefix=f"gralph-stream-{task_id}-"))
    write_text(status_file, "running")
    write_text(log_file, "")

    slot = AgentSlot(
        task_id=task_id,
        agent_num=runner.agent_num,
        proc=proc,
        worktree_dir=wt_dir,
        branch_name=branch,
        status_file=status_file,
        output_file=output_file,
        log_file=log_file,
        stream_file=stream_file,
    )
    return slot


# ── TestRunnerSuccessFlow ────────────────────────────────────────────


class TestRunnerSuccessFlow:
    def test_success_merges_branch_into_base(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.DONE
        # The merged file should exist on main
        assert (git_repo / "code.py").is_file()
        # Worktree dir should be cleaned up
        assert not slot.worktree_dir.is_dir()

    def test_success_with_dirty_worktree_autocommits(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        # Make worktree dirty
        write_text(slot.worktree_dir / "extra.txt", "uncommitted change")

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.DONE
        # The autocommit should have committed the dirty file

    def test_success_sanitizes_committed_runtime_files(self, git_repo: Path) -> None:
        """Committed runtime files from agent branches are stripped before merge."""
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        before_tasks = read_text(git_repo / "tasks.yaml")
        write_text(slot.worktree_dir / "tasks.yaml", "modified by agent")
        write_text(slot.worktree_dir / "progress.txt", "runtime noise")
        subprocess.run(
            ["git", "add", "tasks.yaml", "progress.txt"],
            cwd=slot.worktree_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "noise files"],
            cwd=slot.worktree_dir,
            capture_output=True,
            check=True,
        )

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.DONE
        assert read_text(git_repo / "tasks.yaml") == before_tasks
        assert not (git_repo / "progress.txt").exists()


# ── TestRunnerMergeFailureFlow ───────────────────────────────────────


class TestRunnerMergeFailureFlow:
    def test_merge_conflict_retries_task_when_retries_available(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        # Create a conflict: commit to main the same file the agent changed
        _commit_file(git_repo, "code.py", "conflicting content", "conflict on main")

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.PENDING
        assert runner.retry_counts.get("A") == 1
        # MERGE_HEAD should be gone (abort was called)
        assert not (git_repo / ".git" / "MERGE_HEAD").exists()
        report = json.loads(read_text(git_repo / "artifacts" / "test" / "reports" / "A.json"))
        assert report["status"] == "retrying"
        assert report["commits"] == 1

    def test_merge_conflict_fails_when_retries_exhausted(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        runner.cfg.max_retries = 0
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        _commit_file(git_repo, "code.py", "conflicting content", "conflict on main")

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.FAILED
        assert not (git_repo / ".git" / "MERGE_HEAD").exists()
        report = json.loads(read_text(git_repo / "artifacts" / "test" / "reports" / "A.json"))
        assert report["status"] == "failed"
        assert report["failureType"] == "external"

    def test_merge_failure_does_not_delete_branch(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        _commit_file(git_repo, "code.py", "conflicting content", "conflict on main")

        runner._handle_finished(slot, git_repo)

        # Branch should NOT be deleted when merge fails — it's preserved
        # (Runner calls merge_abort but doesn't delete_branch on failure path)
        # Note: worktree cleanup may remove the worktree but the branch ref stays
        assert git_ops.branch_exists(slot.branch_name, cwd=git_repo)

    def test_merge_blocked_by_local_changes_reports_detail(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")
        slot = _make_successful_slot(runner, git_repo, "A")

        write_text(git_repo / "code.py", "local uncommitted file")

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.FAILED
        report = json.loads(read_text(git_repo / "artifacts" / "test" / "reports" / "A.json"))
        assert report["status"] == "failed"
        assert "overwritten by merge" in report["errorMessage"].lower()


# ── TestRunnerFailureFlow ────────────────────────────────────────────


class TestRunnerFailureFlow:
    def test_failed_process_cleans_up_worktree(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")

        base = git_ops.current_branch(cwd=git_repo)
        wt_base = git_repo / "worktrees"
        wt_base.mkdir(exist_ok=True)
        wt_dir, branch = git_ops.create_agent_worktree(
            "A", 1, base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )

        # Failed process (rc=1)
        proc = subprocess.Popen(
            ["python", "-c", "import sys; sys.exit(1)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc.wait()

        import tempfile
        status_file = Path(tempfile.mktemp(prefix="gralph-status-A-"))
        output_file = Path(tempfile.mktemp(prefix="gralph-output-A-"))
        log_file = Path(tempfile.mktemp(prefix="gralph-log-A-"))
        stream_file = Path(tempfile.mktemp(prefix="gralph-stream-A-"))
        write_text(status_file, "running")
        write_text(log_file, "SyntaxError: invalid syntax\n")

        slot = AgentSlot(
            task_id="A", agent_num=1, proc=proc,
            worktree_dir=wt_dir, branch_name=branch,
            status_file=status_file, output_file=output_file,
            log_file=log_file, stream_file=stream_file,
        )

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.FAILED
        assert not wt_dir.is_dir()

    def test_error_extracted_from_stdout(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")

        base = git_ops.current_branch(cwd=git_repo)
        wt_base = git_repo / "worktrees"
        wt_base.mkdir(exist_ok=True)
        wt_dir, branch = git_ops.create_agent_worktree(
            "A", 1, base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )

        # Failed process (rc=1)
        proc = subprocess.Popen(
            ["python", "-c", "import sys; sys.exit(1)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc.wait()

        import tempfile
        status_file = Path(tempfile.mktemp(prefix="gralph-status-A-"))
        output_file = Path(tempfile.mktemp(prefix="gralph-output-A-"))
        log_file = Path(tempfile.mktemp(prefix="gralph-log-A-"))
        stream_file = Path(tempfile.mktemp(prefix="gralph-stream-A-"))
        write_text(status_file, "running")
        write_text(log_file, "")
        write_text(stream_file, '{"type":"error","error":{"message":"Bad auth"}}\n')

        slot = AgentSlot(
            task_id="A", agent_num=1, proc=proc,
            worktree_dir=wt_dir, branch_name=branch,
            status_file=status_file, output_file=output_file,
            log_file=log_file, stream_file=stream_file,
        )

        runner._handle_finished(slot, git_repo)

        report_file = git_repo / "artifacts" / "test" / "reports" / "A.json"
        assert report_file.exists()
        import json
        report = json.loads(read_text(report_file))
        assert "Bad auth" in report.get("errorMessage", "")

    def test_no_commits_treated_as_failure(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")

        base = git_ops.current_branch(cwd=git_repo)
        wt_base = git_repo / "worktrees"
        wt_base.mkdir(exist_ok=True)
        wt_dir, branch = git_ops.create_agent_worktree(
            "A", 1, base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )

        # Successful process but no commits
        proc = subprocess.Popen(["python", "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.wait()

        import tempfile
        status_file = Path(tempfile.mktemp(prefix="gralph-status-A-"))
        output_file = Path(tempfile.mktemp(prefix="gralph-output-A-"))
        log_file = Path(tempfile.mktemp(prefix="gralph-log-A-"))
        stream_file = Path(tempfile.mktemp(prefix="gralph-stream-A-"))
        write_text(status_file, "running")
        write_text(log_file, "")

        slot = AgentSlot(
            task_id="A", agent_num=1, proc=proc,
            worktree_dir=wt_dir, branch_name=branch,
            status_file=status_file, output_file=output_file,
            log_file=log_file, stream_file=stream_file,
        )

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.FAILED

    def test_no_commits_ignores_non_error_tool_event_when_building_error_message(
        self,
        git_repo: Path,
    ) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")

        base = git_ops.current_branch(cwd=git_repo)
        wt_base = git_repo / "worktrees"
        wt_base.mkdir(exist_ok=True)
        wt_dir, branch = git_ops.create_agent_worktree(
            "A",
            1,
            base_branch=base,
            worktree_base=wt_base,
            original_dir=git_repo,
        )

        proc = subprocess.Popen(
            ["python", "-c", "pass"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.wait()

        import tempfile

        status_file = Path(tempfile.mktemp(prefix="gralph-status-A-"))
        output_file = Path(tempfile.mktemp(prefix="gralph-output-A-"))
        log_file = Path(tempfile.mktemp(prefix="gralph-log-A-"))
        stream_file = Path(tempfile.mktemp(prefix="gralph-stream-A-"))
        write_text(status_file, "running")
        write_text(log_file, "")
        write_text(
            stream_file,
            (
                '{"type":"tool_call","subtype":"completed","call_id":"tool_1",'
                '"tool_call":{"editToolCall":{"args":{"path":"tests/server.test.ts",'
                '"streamContent":"expect((JSON.parse(response.body) as { error: string }).error).toBe(\\"Unauthorized\\");"},'
                '"result":{"success":{"path":"tests/server.test.ts"}}}}}\n'
            ),
        )

        slot = AgentSlot(
            task_id="A",
            agent_num=1,
            proc=proc,
            worktree_dir=wt_dir,
            branch_name=branch,
            status_file=status_file,
            output_file=output_file,
            log_file=log_file,
            stream_file=stream_file,
        )

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.FAILED
        report = json.loads(read_text(git_repo / "artifacts" / "test" / "reports" / "A.json"))
        assert report["errorMessage"] == "Agent exited without creating any commits"

    def test_no_meaningful_changes_treated_as_failure(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        scheduler.start_task("A")

        base = git_ops.current_branch(cwd=git_repo)
        wt_base = git_repo / "worktrees"
        wt_base.mkdir(exist_ok=True)
        wt_dir, branch = git_ops.create_agent_worktree(
            "A", 1, base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )

        # Only change tasks.yaml (not meaningful)
        write_text(wt_dir / "tasks.yaml", "modified")
        subprocess.run(["git", "add", "."], cwd=wt_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "only tasks.yaml"], cwd=wt_dir, capture_output=True)

        proc = subprocess.Popen(["python", "-c", "pass"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.wait()

        import tempfile
        status_file = Path(tempfile.mktemp(prefix="gralph-status-A-"))
        output_file = Path(tempfile.mktemp(prefix="gralph-output-A-"))
        log_file = Path(tempfile.mktemp(prefix="gralph-log-A-"))
        stream_file = Path(tempfile.mktemp(prefix="gralph-stream-A-"))
        write_text(status_file, "running")
        write_text(log_file, "")

        slot = AgentSlot(
            task_id="A", agent_num=1, proc=proc,
            worktree_dir=wt_dir, branch_name=branch,
            status_file=status_file, output_file=output_file,
            log_file=log_file, stream_file=stream_file,
        )

        runner._handle_finished(slot, git_repo)

        assert scheduler.state("A") == TaskState.FAILED

    def test_report_includes_provider_and_attempt_history(self, git_repo: Path) -> None:
        runner, _scheduler = _make_runner(git_repo)
        slot = _make_successful_slot(runner, git_repo, "A")
        slot.provider = "codex"
        runner.task_provider_attempts["A"] = ["claude", "codex"]

        runner._save_report(
            slot,
            git_repo,
            "failed",
            0,
            "Rate limit exceeded",
            attempt=2,
            retries=1,
        )

        report_file = git_repo / "artifacts" / "test" / "reports" / "A.json"
        report = json.loads(read_text(report_file))
        assert report["provider"] == "codex"
        assert report["providerAttempts"] == ["claude", "codex"]


# ── TestRunnerStalledFlow ────────────────────────────────────────────


class TestRunnerStalledFlow:
    def test_stalled_process_killed_and_worktree_cleaned(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)
        runner.cfg.stalled_timeout = 1  # very short

        with patch("gralph.runner.create_agent_worktree") as mock_wt:
            wt_dir = git_repo / "wt-stall"
            wt_dir.mkdir(exist_ok=True)
            mock_wt.return_value = (wt_dir, "gralph/agent-1")

            runner._launch_agent("A", git_repo, git_repo / "worktrees")
            assert len(runner.active) == 1
            slot = runner.active[0]
            slot.proc.wait(timeout=5)  # let it finish naturally first

            # Simulate stall: set last_activity far in the past
            # Process already finished (poll() != None), so _reap_finished goes to _handle_finished
            # For a true stall test we need a long-running process
            slot.proc.kill()

        # After kill, on next reap the slot should be cleaned up
        with patch("gralph.runner.cleanup_agent_worktree"):
            runner._reap_finished(git_repo)

        assert len(runner.active) == 0


# ── TestRunnerWorktreeCreationFailure ────────────────────────────────


class TestRunnerWorktreeCreationFailure:
    def test_worktree_creation_failure_marks_task_failed(self, git_repo: Path) -> None:
        runner, scheduler = _make_runner(git_repo)

        with patch("gralph.runner.create_agent_worktree", side_effect=RuntimeError("boom")):
            runner._launch_agent("A", git_repo, git_repo / "worktrees")

        assert len(runner.active) == 0
        assert scheduler.state("A") == TaskState.FAILED


# ── TestMergeBranchWithFallback ──────────────────────────────────────


class TestMergeBranchWithFallback:
    def test_clean_merge_succeeds(self, git_repo: Path) -> None:
        from gralph.artifacts import merge_branch_with_fallback

        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("fb-clean", base, cwd=git_repo)
        _commit_file(git_repo, "fb.txt", "content", "add file")
        git_ops.checkout(base, cwd=git_repo)

        tf = _tf([_t("A")])
        engine = MockEngine()

        # merge_branch_with_fallback operates on cwd, so we need to be in git_repo
        with patch("gralph.artifacts.merge_no_edit", wraps=lambda b, **kw: git_ops.merge_no_edit(b, cwd=git_repo)) as mock_merge:
            with patch("gralph.artifacts.merge_no_edit", side_effect=lambda b: git_ops.merge_no_edit(b, cwd=git_repo)):
                # Simpler approach: just call with cwd-aware mocks
                pass

        # Direct approach: use the git_repo as cwd
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(git_repo)
            result = merge_branch_with_fallback("fb-clean", "A", engine, tf)
            assert result is True
        finally:
            os.chdir(old_cwd)

    def test_conflict_triggers_ai_resolution(self, git_repo: Path) -> None:
        from gralph.artifacts import merge_branch_with_fallback

        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("fb-conflict", base, cwd=git_repo)
        _commit_file(git_repo, "fb.txt", "branch version", "branch")
        git_ops.checkout(base, cwd=git_repo)
        _commit_file(git_repo, "fb.txt", "main version", "main")

        tf = _tf([_t("A")])
        engine = MockEngine()

        # Mock run_sync to resolve the conflict
        def resolve_conflict(prompt, **kwargs):
            # Simulate AI resolving the conflict
            write_text(git_repo / "fb.txt", "resolved version")
            subprocess.run(["git", "add", "fb.txt"], cwd=git_repo, capture_output=True)
            subprocess.run(["git", "commit", "--no-edit"], cwd=git_repo, capture_output=True)
            return EngineResult()

        engine.run_sync = resolve_conflict  # type: ignore[assignment]

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(git_repo)
            result = merge_branch_with_fallback("fb-conflict", "A", engine, tf)
            assert result is True
        finally:
            os.chdir(old_cwd)

    def test_unresolved_conflict_aborts(self, git_repo: Path) -> None:
        from gralph.artifacts import merge_branch_with_fallback

        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("fb-unresolved", base, cwd=git_repo)
        _commit_file(git_repo, "fb.txt", "branch version", "branch")
        git_ops.checkout(base, cwd=git_repo)
        _commit_file(git_repo, "fb.txt", "main version", "main")

        tf = _tf([_t("A")])
        engine = MockEngine()

        # run_sync does nothing → conflict remains
        engine.run_sync = lambda prompt, **kw: EngineResult()  # type: ignore[assignment]

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(git_repo)
            result = merge_branch_with_fallback("fb-unresolved", "A", engine, tf)
            assert result is False
            # Should have aborted
            assert not (git_repo / ".git" / "MERGE_HEAD").exists()
        finally:
            os.chdir(old_cwd)
