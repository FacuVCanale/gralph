"""Runner: orchestrates parallel/sequential task execution with worktrees."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from gralph import log
from gralph.config import Config
from gralph.engines.base import EngineBase
from gralph.git_ops import (
    add_and_commit,
    changed_files,
    cleanup_agent_worktree,
    commit_count,
    create_agent_worktree,
    current_branch,
    has_dirty_worktree,
    merge_no_edit,
    merge_abort,
    delete_branch,
)
from gralph.scheduler import Scheduler, TaskState
from gralph.tasks.model import TaskFile
from gralph.tasks.io import mark_task_complete_in_file


@dataclass
class AgentSlot:
    """Tracks a running agent subprocess."""

    task_id: str
    agent_num: int
    proc: subprocess.Popen  # type: ignore[type-arg]
    worktree_dir: Path
    branch_name: str
    status_file: Path
    output_file: Path
    log_file: Path
    stream_file: Path
    started_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)


def _build_task_prompt(task_id: str, task_title: str, touches: str) -> str:
    return f"""You are working on a specific task. Focus ONLY on this task:

TASK ID: {task_id}
TASK: {task_title}
EXPECTED FILES TO CREATE/MODIFY: {touches}

Instructions:
1. Implement this specific task completely by creating/editing the necessary code files.
2. Write tests if appropriate.
3. Update progress.txt with what you did.
4. Commit your changes with a descriptive message.

CRITICAL RULES:
- Do NOT modify tasks.yaml.
- Do NOT mark the task as complete in tasks.yaml.
- Do NOT just update progress.txt. You MUST write the actual code.
- If the file does not exist, CREATE IT.

Focus only on implementing: {task_title}"""


def _is_external_failure(msg: str) -> bool:
    """Heuristic: detect external/infra/toolchain failures."""
    if not msg:
        return False
    lower = msg.lower()
    patterns = [
        "buninstallfailederror", "command not found", "enoent", "eacces",
        "permission denied", "network", "timeout", "tls", "econnreset",
        "etimedout", "lockfile", "install", "certificate", "ssl",
        "rate limit", "quota", "429", "too many requests", "stalled",
    ]
    return any(p in lower for p in patterns)


def _extract_error_from_log(log_file: Path) -> str:
    """Get the last non-debug line from a log file."""
    if not log_file.is_file():
        return ""
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    non_debug = [l for l in lines if not l.startswith("[DEBUG]") and l.strip()]
    return non_debug[-1] if non_debug else (lines[-1] if lines else "")


def _meaningful_changes(base: str, cwd: Path) -> bool:
    """Check if there are meaningful code changes (not just tasks.yaml/progress.txt)."""
    files = changed_files(base, cwd=cwd)
    for f in files:
        if f and "tasks.yaml" not in f and "progress.txt" not in f:
            return True
    return False


class Runner:
    """Orchestrates DAG-aware parallel/sequential task execution."""

    def __init__(
        self,
        cfg: Config,
        tf: TaskFile,
        engine: EngineBase,
        scheduler: Scheduler,
    ) -> None:
        self.cfg = cfg
        self.tf = tf
        self.engine = engine
        self.sched = scheduler
        self.iteration = 0
        self.agent_num = 0
        self.active: list[AgentSlot] = []
        self.completed_branches: list[str] = []
        self.completed_task_ids: list[str] = []

    def run(self) -> bool:
        """Execute all tasks. Returns ``True`` on success."""
        self.cfg.original_dir = str(Path.cwd())
        self.cfg.worktree_base = tempfile.mkdtemp(prefix="gralph-")
        original_dir = Path(self.cfg.original_dir)
        worktree_base = Path(self.cfg.worktree_base)

        if not self.cfg.base_branch:
            self.cfg.base_branch = current_branch()

        log.info(f"Running DAG-aware parallel execution (max {self.cfg.max_parallel} agents)…")
        log.info(f"Tasks: {self.sched.count_pending()} pending")

        try:
            return self._main_loop(original_dir, worktree_base)
        finally:
            # Cleanup
            if worktree_base.exists():
                shutil.rmtree(worktree_base, ignore_errors=True)

    def _main_loop(self, original_dir: Path, worktree_base: Path) -> bool:
        external_fail = False

        while True:
            # 1. Check finished agents
            self._reap_finished(original_dir)

            # 2. Check completion / deadlock
            pending = self.sched.count_pending()
            running = self.sched.count_running()

            if pending == 0 and running == 0:
                break

            if self.sched.check_deadlock():
                self._report_deadlock()
                return False

            # 3. Launch new tasks
            slots = self.cfg.max_parallel - running
            if slots > 0:
                ready = self.sched.get_ready()
                to_start = ready[:slots]
                for task_id in to_start:
                    self._launch_agent(task_id, original_dir, worktree_base)

            # 4. Check max iterations
            if self.cfg.max_iterations > 0 and self.iteration >= self.cfg.max_iterations:
                log.warn(f"Reached max iterations ({self.cfg.max_iterations})")
                break

            time.sleep(0.5)

        return True

    def _launch_agent(self, task_id: str, original_dir: Path, worktree_base: Path) -> None:
        self.agent_num += 1
        self.iteration += 1
        self.sched.start_task(task_id)

        task = self.tf.get_task(task_id)
        title = task.title if task else task_id
        touches = ", ".join(task.touches) if task else ""

        log.console.print(
            f"  [cyan]●[/cyan] Agent {self.agent_num}: "
            f"{title[:40]} ({task_id})"
        )

        # Create temp files for IPC
        status_file = Path(tempfile.mktemp(prefix=f"gralph-status-{task_id}-"))
        output_file = Path(tempfile.mktemp(prefix=f"gralph-output-{task_id}-"))
        log_file = Path(tempfile.mktemp(prefix=f"gralph-log-{task_id}-"))
        stream_file = Path(tempfile.mktemp(prefix=f"gralph-stream-{task_id}-"))

        status_file.write_text("setting up")

        try:
            wt_dir, branch_name = create_agent_worktree(
                task_id,
                self.agent_num,
                base_branch=self.cfg.base_branch,
                worktree_base=worktree_base,
                original_dir=original_dir,
            )
        except RuntimeError as e:
            log.error(f"Failed to create worktree for {task_id}: {e}")
            status_file.write_text("failed")
            output_file.write_text("0 0")
            self.sched.fail_task(task_id)
            return

        # Copy PRD/tasks to worktree
        prd_src = original_dir / self.cfg.prd_file
        if prd_src.is_file():
            shutil.copy2(prd_src, wt_dir)

        # Create progress.txt in worktree root
        (wt_dir / "progress.txt").touch()

        prompt = _build_task_prompt(task_id, title, touches)
        status_file.write_text("running")

        # Launch engine async
        proc = self.engine.run_async(
            prompt,
            cwd=wt_dir,
            stdout_file=stream_file,
            stderr_file=log_file,
        )

        self.active.append(
            AgentSlot(
                task_id=task_id,
                agent_num=self.agent_num,
                proc=proc,
                worktree_dir=wt_dir,
                branch_name=branch_name,
                status_file=status_file,
                output_file=output_file,
                log_file=log_file,
                stream_file=stream_file,
            )
        )

    def _reap_finished(self, original_dir: Path) -> None:
        """Check active agents; process any that have finished."""
        still_active: list[AgentSlot] = []

        for slot in self.active:
            poll = slot.proc.poll()
            if poll is None:
                # Still running — check for stall
                if slot.log_file.is_file():
                    mtime = slot.log_file.stat().st_mtime
                    if mtime > slot.last_activity:
                        slot.last_activity = mtime

                idle = time.monotonic() - slot.last_activity
                if idle > self.cfg.stalled_timeout:
                    log.warn(
                        f"Agent {slot.agent_num} stalled for {int(idle)}s. Killing…"
                    )
                    slot.proc.kill()
                    slot.status_file.write_text("failed")
                else:
                    still_active.append(slot)
                    continue
            # Process finished
            self._handle_finished(slot, original_dir)

        self.active = still_active

    def _handle_finished(self, slot: AgentSlot, original_dir: Path) -> None:
        """Process a finished agent slot."""
        task = self.tf.get_task(slot.task_id)
        title = task.title if task else slot.task_id

        # Persist log
        self._persist_log(slot.task_id, slot.log_file, original_dir)

        # Check success
        rc = slot.proc.returncode
        commits = commit_count(self.cfg.base_branch, cwd=slot.worktree_dir)
        meaningful = _meaningful_changes(self.cfg.base_branch, cwd=slot.worktree_dir)

        if rc == 0 and commits > 0 and meaningful:
            # Success
            self._handle_success(slot, original_dir, title, commits)
        else:
            # Failure
            self._handle_failure(slot, original_dir, title)

        # Cleanup temp files
        for f in [slot.status_file, slot.output_file, slot.log_file, slot.stream_file]:
            f.unlink(missing_ok=True)

    def _handle_success(
        self, slot: AgentSlot, original_dir: Path, title: str, commits: int
    ) -> None:
        # If worktree has uncommitted changes, auto-commit
        if has_dirty_worktree(cwd=slot.worktree_dir):
            add_and_commit("Auto-commit remaining changes", cwd=slot.worktree_dir)

        # Revert tasks.yaml if modified
        tasks_yaml = slot.worktree_dir / "tasks.yaml"
        if tasks_yaml.is_file():
            subprocess.run(
                ["git", "reset", "HEAD", "tasks.yaml"],
                cwd=slot.worktree_dir, capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", "--", "tasks.yaml"],
                cwd=slot.worktree_dir, capture_output=True,
            )

        # Merge or create PR
        merge_ok = True
        if not self.cfg.create_pr:
            log.info(f"Merging {slot.branch_name} into {self.cfg.base_branch}…")
            if merge_no_edit(slot.branch_name, cwd=original_dir):
                delete_branch(slot.branch_name, cwd=original_dir)
                self.completed_branches.append(slot.branch_name)
            else:
                merge_ok = False
                merge_abort(cwd=original_dir)
                log.error(f"Merge failed for {slot.branch_name}")
        else:
            from gralph.git_ops import create_pull_request

            create_pull_request(
                slot.branch_name,
                self.cfg.base_branch,
                title,
                f"Automated: {slot.task_id}",
                draft=self.cfg.draft_pr,
            )

        if merge_ok:
            self.sched.complete_task(slot.task_id)
            # Mark in YAML file
            prd_path = Path(original_dir) / self.cfg.prd_file
            if prd_path.is_file():
                mark_task_complete_in_file(prd_path, slot.task_id)
            self.completed_task_ids.append(slot.task_id)
            log.console.print(
                f"  [green]✓[/green] {title[:45]} ({slot.task_id})"
            )
        else:
            self.sched.fail_task(slot.task_id)
            log.console.print(
                f"  [red]✗[/red] {title[:45]} ({slot.task_id}) [Merge Failed]"
            )

        # Save report
        self._save_report(slot, original_dir, "done", commits)

        # Cleanup worktree
        cleanup_agent_worktree(
            slot.worktree_dir,
            slot.branch_name,
            original_dir=original_dir,
            log_file=slot.log_file,
        )

    def _handle_failure(self, slot: AgentSlot, original_dir: Path, title: str) -> None:
        self.sched.fail_task(slot.task_id)
        log.console.print(f"  [red]✗[/red] {title[:45]} ({slot.task_id})")

        err_msg = _extract_error_from_log(slot.log_file)
        if err_msg:
            log.console.print(f"[dim]    Error: {err_msg}[/dim]")

        self._save_report(slot, original_dir, "failed", 0, err_msg)

        cleanup_agent_worktree(
            slot.worktree_dir,
            slot.branch_name,
            original_dir=original_dir,
            log_file=slot.log_file,
        )

    def _persist_log(self, task_id: str, log_file: Path, original_dir: Path) -> None:
        if not self.cfg.artifacts_dir:
            return
        reports_dir = original_dir / self.cfg.artifacts_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        if log_file.is_file():
            shutil.copy2(log_file, reports_dir / f"{task_id}.log")

    def _save_report(
        self,
        slot: AgentSlot,
        original_dir: Path,
        status: str,
        commits: int,
        error_msg: str = "",
    ) -> None:
        if not self.cfg.artifacts_dir:
            return
        import json
        from datetime import datetime, timezone

        reports_dir = original_dir / self.cfg.artifacts_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        task = self.tf.get_task(slot.task_id)
        title = task.title if task else slot.task_id
        files = changed_files(self.cfg.base_branch, cwd=slot.worktree_dir)

        report = {
            "taskId": slot.task_id,
            "title": title,
            "branch": slot.branch_name,
            "status": status,
            "commits": commits,
            "changedFiles": ",".join(files),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if error_msg:
            report["errorMessage"] = error_msg
            report["failureType"] = "external" if _is_external_failure(error_msg) else "internal"

        (reports_dir / f"{slot.task_id}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

    def _report_deadlock(self) -> None:
        # Check if it's a failed-deps situation or a real deadlock
        has_failed = False
        for tid in self.sched._state:
            if self.sched.state(tid) == TaskState.PENDING:
                if self.sched.has_failed_deps(tid):
                    has_failed = True
                    break

        if has_failed:
            log.error("Workflow halted: Dependencies failed, preventing further progress.")
        else:
            log.error("DEADLOCK: No progress possible (cycle or mutex contention)")

        log.console.print("")
        log.console.print("[red]Blocked tasks:[/red]")
        for tid in self.sched._state:
            if self.sched.state(tid) == TaskState.PENDING:
                reason = self.sched.explain_block(tid)
                log.console.print(f"  {tid}: {reason}")
