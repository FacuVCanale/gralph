"""Runner: orchestrates parallel/sequential task execution with worktrees."""

from __future__ import annotations

import signal
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
from gralph.io_utils import read_text, write_text
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


def _extract_error_from_logs(log_file: Path, stream_file: Path | None = None) -> str:
    """Get the most relevant error line from stderr or stdout logs."""
    if log_file.is_file():
        lines = read_text(log_file, errors="replace").splitlines()
        non_debug = [l for l in lines if not l.startswith("[DEBUG]") and l.strip()]
        if non_debug:
            return non_debug[-1]
        if lines:
            return lines[-1]

    if stream_file and stream_file.is_file():
        stream = read_text(stream_file, errors="replace")
        err = EngineBase._check_errors(stream)
        if err:
            return err
        for line in reversed(stream.splitlines()):
            lower = line.lower()
            if "error" in lower or "exception" in lower or "traceback" in lower:
                return line.strip()

    return ""


def _meaningful_changes(base: str, cwd: Path) -> bool:
    """Check if there are meaningful code changes (not just tasks.yaml/progress.txt)."""
    files = changed_files(base, cwd=cwd)
    for f in files:
        if f and "tasks.yaml" not in f and "progress.txt" not in f:
            return True
    return False


_FORBIDDEN_TASK_FILES = {"tasks.yaml", "progress.txt"}


def _sanitize_forbidden_task_files(base: str, cwd: Path) -> list[str]:
    """Revert forbidden runtime files in a task branch before merge.

    Agents sometimes commit local runtime bookkeeping files (``tasks.yaml``,
    ``progress.txt``). These must not be merged into the run branch.
    Returns the list of sanitized paths.
    """
    changed = changed_files(base, cwd=cwd)
    offenders = [f for f in changed if Path(f).as_posix() in _FORBIDDEN_TASK_FILES]
    if not offenders:
        return []

    for rel in offenders:
        abs_path = cwd / rel
        # If the file exists on base, restore that exact version.
        show = subprocess.run(
            ["git", "show", f"{base}:{rel}"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if show.returncode == 0:
            subprocess.run(["git", "checkout", base, "--", rel], cwd=cwd, capture_output=True)
            continue

        # Otherwise it was introduced by the task branch; remove it.
        if abs_path.exists():
            abs_path.unlink(missing_ok=True)
        subprocess.run(["git", "rm", "-f", "--ignore-unmatch", rel], cwd=cwd, capture_output=True)

    if has_dirty_worktree(cwd=cwd):
        add_and_commit("chore(gralph): sanitize forbidden task files", cwd=cwd)

    return offenders


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
        self.retry_counts: dict[str, int] = {}
        self.retry_after: dict[str, float] = {}
        self._stop_requested = False
        self._interrupt_count = 0
        self._orig_signal_handlers: dict[int, object] = {}
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

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

        self._install_signal_handlers()
        try:
            try:
                return self._main_loop(original_dir, worktree_base)
            except KeyboardInterrupt:
                self._stop_requested = True
                self._abort_all_active(original_dir)
                return False
        finally:
            self._restore_signal_handlers()
            # Cleanup
            if worktree_base.exists():
                shutil.rmtree(worktree_base, ignore_errors=True)

    def _main_loop(self, original_dir: Path, worktree_base: Path) -> bool:
        external_fail = False

        while True:
            if self._stop_requested:
                self._abort_all_active(original_dir)
                return False

            # 1. Check finished agents
            self._reap_finished(original_dir)

            if self._stop_requested:
                self._abort_all_active(original_dir)
                return False

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
                ready = self._get_ready_tasks()
                to_start = ready[:slots]
                for task_id in to_start:
                    self._launch_agent(task_id, original_dir, worktree_base)

            # 4. Check max iterations
            if self.cfg.max_iterations > 0 and self.iteration >= self.cfg.max_iterations:
                log.warn(f"Reached max iterations ({self.cfg.max_iterations})")
                break

            time.sleep(0.5)

        return True

    def _install_signal_handlers(self) -> None:
        """Install handlers so Ctrl-C can stop long-running parallel work."""
        self._orig_signal_handlers = {}
        signals_to_handle = [signal.SIGINT]
        if hasattr(signal, "SIGBREAK"):
            signals_to_handle.append(signal.SIGBREAK)
        if hasattr(signal, "SIGTERM"):
            signals_to_handle.append(signal.SIGTERM)

        for sig in signals_to_handle:
            try:
                self._orig_signal_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._on_signal)
            except (OSError, RuntimeError, ValueError):
                continue

    def _restore_signal_handlers(self) -> None:
        for sig, handler in self._orig_signal_handlers.items():
            try:
                signal.signal(sig, handler)
            except (OSError, RuntimeError, ValueError):
                continue
        self._orig_signal_handlers = {}

    def _on_signal(self, signum: int, _frame: object) -> None:
        self._interrupt_count += 1
        self._stop_requested = True
        if self._interrupt_count == 1:
            log.warn(f"Interrupt received (signal {signum}). Stopping agents...")
        else:
            log.warn(f"Interrupt received again (signal {signum}). Forcing stop...")

    def _abort_all_active(self, original_dir: Path) -> None:
        """Kill active agents, write failure reports, and clean up worktrees."""
        if not self.active:
            return

        log.warn(f"Stopping {len(self.active)} active agent(s)...")
        slots = list(self.active)
        self.active = []

        for slot in slots:
            if slot.proc.poll() is None:
                try:
                    slot.proc.terminate()
                except OSError:
                    pass
                try:
                    slot.proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if slot.proc.poll() is None:
                try:
                    slot.proc.kill()
                except OSError:
                    pass

            self.sched.fail_task(slot.task_id)
            self._persist_log(slot.task_id, slot.log_file, slot.stream_file, original_dir)
            retries_used = self.retry_counts.get(slot.task_id, 0)
            self._save_report(
                slot,
                original_dir,
                "failed",
                0,
                "Interrupted by user (Ctrl-C)",
                attempt=retries_used + 1,
                retries=retries_used,
            )
            cleanup_agent_worktree(
                slot.worktree_dir,
                slot.branch_name,
                original_dir=original_dir,
                log_file=slot.log_file,
            )
            for f in [slot.status_file, slot.output_file, slot.log_file, slot.stream_file]:
                f.unlink(missing_ok=True)

    def _get_ready_tasks(self) -> list[str]:
        """Return ready tasks, honoring retry delays."""
        ready: list[str] = []
        now = time.monotonic()
        for tid in self.sched.get_ready():
            retry_at = self.retry_after.get(tid)
            if retry_at and retry_at > now:
                continue
            if retry_at and retry_at <= now:
                self.retry_after.pop(tid, None)
            ready.append(tid)
        return ready

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

        write_text(status_file, "setting up")

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
            write_text(status_file, "failed")
            write_text(output_file, "0 0")
            self.sched.fail_task(task_id)
            return

        # Copy PRD/tasks to worktree
        prd_src = original_dir / self.cfg.prd_file
        if prd_src.is_file():
            shutil.copy2(prd_src, wt_dir)

        # Create progress.txt in worktree root
        (wt_dir / "progress.txt").touch()

        prompt = _build_task_prompt(task_id, title, touches)
        write_text(status_file, "running")

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
                    write_text(slot.status_file, "failed")
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

        # Accumulate token usage from engine output
        self._accumulate_tokens(slot.stream_file)

        # Persist log
        self._persist_log(slot.task_id, slot.log_file, slot.stream_file, original_dir)

        # Check success
        rc = slot.proc.returncode
        commits = commit_count(self.cfg.base_branch, cwd=slot.worktree_dir)
        meaningful = _meaningful_changes(self.cfg.base_branch, cwd=slot.worktree_dir)

        if rc == 0 and commits > 0 and meaningful:
            # Success
            self._handle_success(slot, original_dir, title, commits)
        else:
            # Failure
            err_msg = _extract_error_from_logs(slot.log_file, slot.stream_file)
            if not err_msg:
                if rc != 0:
                    err_msg = f"exit code {rc}"
                elif commits == 0:
                    err_msg = "Agent exited without creating any commits"
                elif not meaningful:
                    err_msg = "No meaningful changes (only tasks.yaml/progress.txt)"
            self._handle_failure(slot, original_dir, title, err_msg)

        # Cleanup temp files
        for f in [slot.status_file, slot.output_file, slot.log_file, slot.stream_file]:
            f.unlink(missing_ok=True)

    def _handle_success(
        self, slot: AgentSlot, original_dir: Path, title: str, commits: int
    ) -> None:
        # If worktree has uncommitted changes, auto-commit
        if has_dirty_worktree(cwd=slot.worktree_dir):
            add_and_commit("Auto-commit remaining changes", cwd=slot.worktree_dir)

        sanitized = _sanitize_forbidden_task_files(self.cfg.base_branch, slot.worktree_dir)
        if sanitized:
            log.warn(f"Sanitized forbidden files from task branch: {', '.join(sanitized)}")

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
        retries_used = self.retry_counts.get(slot.task_id, 0)
        self._save_report(
            slot,
            original_dir,
            "done",
            commits,
            attempt=retries_used + 1,
            retries=retries_used,
        )

        # Cleanup worktree
        cleanup_agent_worktree(
            slot.worktree_dir,
            slot.branch_name,
            original_dir=original_dir,
            log_file=slot.log_file,
        )


    def _handle_failure(
        self,
        slot: AgentSlot,
        original_dir: Path,
        title: str,
        err_msg: str,
    ) -> None:
        retries_used = self.retry_counts.get(slot.task_id, 0)
        attempt = retries_used + 1
        max_attempts = self.cfg.max_retries + 1
        should_retry = self._should_retry(err_msg, retries_used)

        if should_retry:
            self.retry_counts[slot.task_id] = retries_used + 1
            delay = max(self.cfg.retry_delay, 0)
            if delay:
                self.retry_after[slot.task_id] = time.monotonic() + delay
            self.sched.retry_task(slot.task_id)
            log.console.print(
                f"  [yellow]RETRY[/yellow] {title[:45]} ({slot.task_id}) "
                f"in {delay}s (attempt {attempt + 1}/{max_attempts})"
            )
        else:
            self.sched.fail_task(slot.task_id)
            log.console.print(f"  [red]x[/red] {title[:45]} ({slot.task_id})")

        if err_msg:
            log.console.print(f"[dim]    Error: {err_msg}[/dim]")

        status = "retrying" if should_retry else "failed"
        self._save_report(
            slot,
            original_dir,
            status,
            0,
            err_msg,
            attempt=attempt,
            retries=retries_used,
        )

        cleanup_agent_worktree(
            slot.worktree_dir,
            slot.branch_name,
            original_dir=original_dir,
            log_file=slot.log_file,
        )

    def _persist_log(
        self,
        task_id: str,
        log_file: Path,
        stream_file: Path,
        original_dir: Path,
    ) -> None:
        if not self.cfg.artifacts_dir:
            return
        reports_dir = original_dir / self.cfg.artifacts_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        if log_file.is_file():
            shutil.copy2(log_file, reports_dir / f"{task_id}.log")
        if stream_file.is_file():
            shutil.copy2(stream_file, reports_dir / f"{task_id}.out")

    def _save_report(
        self,
        slot: AgentSlot,
        original_dir: Path,
        status: str,
        commits: int,
        error_msg: str = "",
        *,
        attempt: int | None = None,
        retries: int | None = None,
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
        if attempt is not None:
            report["attempt"] = attempt
        if retries is not None:
            report["retries"] = retries
        report["maxRetries"] = self.cfg.max_retries
        if error_msg:
            report["errorMessage"] = error_msg
            report["failureType"] = "external" if _is_external_failure(error_msg) else "internal"

        write_text(
            reports_dir / f"{slot.task_id}.json",
            json.dumps(report, indent=2),
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

    def _should_retry(self, err_msg: str, retries_used: int) -> bool:
        """Return True if this error should be retried."""
        if self.cfg.max_retries <= 0:
            return False
        if retries_used >= self.cfg.max_retries:
            return False
        return _is_external_failure(err_msg)

    def _accumulate_tokens(self, stream_file: Path) -> None:
        """Parse engine output from *stream_file* and accumulate token counts."""
        if not stream_file.is_file():
            return
        raw = read_text(stream_file, errors="replace")
        if not raw:
            return
        result = self.engine.parse_output(raw)
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens
