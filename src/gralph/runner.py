"""Runner: orchestrates parallel/sequential task execution with worktrees."""

from __future__ import annotations

import copy
import os
import platform
import signal
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType

from gralph import log
from gralph.config import Config
from gralph.engines.base import EngineBase
from gralph.engines.registry import get_engine
from gralph.git_ops import (
    add_and_commit,
    changed_files,
    cleanup_agent_worktree,
    commit_count,
    create_agent_worktree,
    current_branch,
    dirty_worktree_entries,
    has_dirty_worktree,
    merge_no_edit_result,
    merge_abort,
    delete_branch,
)
from gralph.scheduler import Scheduler
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
    provider: str = ""
    engine: EngineBase | None = None
    started_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    last_log_mtime: float = 0.0


def _task_shell_rules() -> str:
    """Return shell usage guardrails for the current platform."""
    if platform.system().lower().startswith("windows"):
        return (
            "SHELL COMPATIBILITY (Windows PowerShell):\n"
            "- Do NOT use '&&' between commands; PowerShell 5 treats it as a syntax error.\n"
            "- Use ';' between commands, or run commands separately.\n"
            "- Prefer setting tool workingDirectory/cwd instead of chaining 'cd'.\n"
            "- Before command sequences, set $ErrorActionPreference = 'Stop'.\n"
        )
    return (
        "SHELL COMPATIBILITY:\n"
        "- Use shell syntax compatible with the current platform.\n"
        "- Prefer tool workingDirectory/cwd instead of chaining 'cd'.\n"
    )


def _build_task_prompt(
    task_id: str,
    task_title: str,
    touches: str,
    *,
    skip_tests: bool,
    skip_lint: bool,
) -> str:
    shell_rules = _task_shell_rules()
    quality_rules: list[str] = []
    if skip_tests:
        quality_rules.append("- Skip full test suite execution unless strictly needed for this task.")
    if skip_lint:
        quality_rules.append("- Skip full lint execution unless strictly needed for this task.")
    quality_block = "\n".join(quality_rules)
    return f"""You are working on a specific task. Focus ONLY on this task:

TASK ID: {task_id}
TASK: {task_title}
EXPECTED FILES TO CREATE/MODIFY: {touches}

Instructions:
1. Implement this specific task completely by creating/editing the necessary code files.
2. Write tests if appropriate.
3. Update progress.txt with what you did.
4. Commit your changes with a descriptive message.

{shell_rules}

CRITICAL RULES:
- Do NOT modify tasks.yaml.
- Do NOT mark the task as complete in tasks.yaml.
- Do NOT just update progress.txt. You MUST write the actual code.
- Do NOT commit tasks.yaml or progress.txt.
- If the file does not exist, CREATE IT.
{quality_block}

Focus only on implementing: {task_title}"""


def _is_external_failure(msg: str) -> bool:
    """Heuristic: detect external/infra/toolchain failures."""
    if not msg:
        return False
    if _is_merge_conflict_failure(msg):
        return True
    lower = msg.lower()
    patterns = [
        "buninstallfailederror", "command not found", "enoent", "eacces",
        "commandnotfoundexception", "objectnotfound:",
        "permission denied", "network", "timeout", "tls", "econnreset",
        "etimedout", "lockfile", "install", "certificate", "ssl",
        "rate limit", "quota", "429", "too many requests", "hit your limit", "stalled",
        "blocked by policy", "read-only sandbox", "approval_policy",
    ]
    return any(p in lower for p in patterns)


def _is_merge_conflict_failure(msg: str) -> bool:
    """True when a git merge failed due to textual conflicts."""
    if not msg:
        return False
    lower = msg.lower()
    markers = [
        "automatic merge failed",
        "conflict (content)",
        "conflict in ",
        "merge conflict",
    ]
    return any(marker in lower for marker in markers)


def _extract_policy_block_detail_from_stream(stream: str) -> str:
    """Extract policy/sandbox block details from structured engine stream."""
    if not stream:
        return ""

    import json

    for line in stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if "blocked by policy" in stripped.lower():
            return "Blocked by policy"

        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        if not isinstance(obj, dict):
            continue

        err = obj.get("error")
        if isinstance(err, str) and "blocked by policy" in err.lower():
            return "Blocked by policy"
        if isinstance(err, dict):
            msg = str(err.get("message", "")).strip()
            if "blocked by policy" in msg.lower():
                return "Blocked by policy"

        item = obj.get("item")
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).lower() != "command_execution":
            continue
        output = str(item.get("aggregated_output", "")).strip()
        if "blocked by policy" in output.lower():
            return "Blocked by policy"

    return ""


def _extract_rate_limit_detail_from_stream(stream: str) -> str:
    """Extract human-readable rate-limit text from structured engine stream."""
    if not stream:
        return ""

    import json

    for line in stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        if not isinstance(obj, dict):
            continue

        # Common path in Claude stream-json: assistant message carries detail text.
        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and "hit your limit" in text.lower():
                        return text.strip()

        # Result events may also carry a plain string with reset info.
        result_text = obj.get("result")
        if isinstance(result_text, str) and "hit your limit" in result_text.lower():
            return result_text.strip()

    return ""


def _extract_structured_error_line(stripped: str) -> tuple[str, bool]:
    """Extract an error message from one stream line.

    Returns ``(error_message, is_structured_json)``.
    """
    if not stripped:
        return "", False

    import json

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return "", False

    if not isinstance(obj, dict):
        return "", True

    event_type = str(obj.get("type", "")).lower()
    if event_type == "result":
        is_error = obj.get("is_error")
        if is_error is False:
            return "", True
        if is_error is True:
            result_text = obj.get("result")
            if isinstance(result_text, str) and result_text.strip():
                return result_text.strip(), True

    err = obj.get("error")
    if isinstance(err, dict):
        msg = str(err.get("message", "")).strip()
        if msg:
            return msg, True
    elif isinstance(err, str) and err.strip():
        return err.strip(), True

    item = obj.get("item")
    if isinstance(item, dict) and str(item.get("type", "")).lower() == "error":
        text = str(item.get("text", "")).strip()
        if text:
            return text, True
        msg = str(item.get("message", "")).strip()
        if msg:
            return msg, True

    if event_type == "error":
        msg = str(obj.get("message", "")).strip()
        if msg:
            return msg, True
        text = str(obj.get("text", "")).strip()
        if text:
            return text, True
        return "Unknown error", True

    return "", True


def _extract_error_from_logs(log_file: Path, stream_file: Path | None = None) -> str:
    """Get the most relevant error line from stderr or stdout logs."""
    if log_file.is_file():
        lines = read_text(log_file, errors="replace").splitlines()
        non_debug = [line_text for line_text in lines if not line_text.startswith("[DEBUG]") and line_text.strip()]
        if non_debug:
            return non_debug[-1]
        if lines:
            return lines[-1]

    if stream_file and stream_file.is_file():
        stream = read_text(stream_file, errors="replace")
        policy_detail = _extract_policy_block_detail_from_stream(stream)
        if policy_detail:
            return policy_detail
        rate_limit_detail = _extract_rate_limit_detail_from_stream(stream)
        err = EngineBase._check_errors(stream)
        if err:
            if err.lower() == "rate limit exceeded" and rate_limit_detail:
                return f"Rate limit exceeded: {rate_limit_detail}"
            return err
        if rate_limit_detail:
            return rate_limit_detail
        for line in reversed(stream.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if "blocked by policy" in lower:
                return "Blocked by policy"

            structured_error, is_structured_json = _extract_structured_error_line(stripped)
            if structured_error:
                return structured_error

            if "exception" in lower or "traceback" in lower:
                return stripped

            # Avoid false positives on non-error JSON events that merely include
            # snippets like {"error": "..."} in tool payload text.
            if is_structured_json:
                continue

            if lower.startswith("error") or " error:" in lower or '"error"' in lower:
                return stripped

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
        self.providers: list[str] = self._normalize_providers(cfg.providers, cfg.ai_engine)
        self.task_providers: dict[str, str] = {}
        self.task_provider_attempts: dict[str, list[str]] = {}
        self.provider_usage: dict[str, int] = {provider: 0 for provider in self.providers}
        self._provider_index = 0
        self._engine_factory = self._make_engine_factory(engine)
        self.iteration = 0
        self.agent_num = 0
        self.active: list[AgentSlot] = []
        self.completed_branches: list[str] = []
        self.completed_task_ids: list[str] = []
        self.retry_counts: dict[str, int] = {}
        self.retry_after: dict[str, float] = {}
        self._external_failure_since: dict[str, float] = {}
        self._stop_requested = False
        self._interrupt_count = 0
        self._orig_signal_handlers: dict[
            signal.Signals,
            int | Callable[[int, FrameType | None], object] | None,
        ] = {}
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    @staticmethod
    def _normalize_providers(providers: list[str], fallback_provider: str) -> list[str]:
        """Return a non-empty provider list, preserving order."""
        normalized = [p.strip().lower() for p in providers if p and p.strip()]
        if normalized:
            return normalized
        return [fallback_provider.strip().lower()]

    def _make_engine_factory(self, seed_engine: EngineBase) -> Callable[[str], EngineBase]:
        """Create task-scoped engines while keeping test doubles easy to inject."""
        if seed_engine.__class__.__module__.startswith("gralph.engines."):
            return lambda provider: get_engine(provider, opencode_model=self.cfg.opencode_model)

        def _clone_engine(_provider: str) -> EngineBase:
            try:
                return copy.deepcopy(seed_engine)
            except Exception:
                return seed_engine

        return _clone_engine

    def _provider_for_task(self, task_id: str) -> str:
        """Assign a provider once per task using round-robin order."""
        assigned = self.task_providers.get(task_id)
        if assigned:
            return assigned

        provider = self.providers[self._provider_index % len(self.providers)]
        self._provider_index += 1
        self.task_providers[task_id] = provider
        return provider

    def _rotate_provider_for_task(self, task_id: str) -> tuple[str, str] | None:
        """Switch *task_id* to the next distinct provider in configured order."""
        if len(self.providers) <= 1:
            return None

        current = self.task_providers.get(task_id)
        if not current:
            current = self._provider_for_task(task_id)

        try:
            start_idx = self.providers.index(current)
        except ValueError:
            start_idx = -1

        for offset in range(1, len(self.providers) + 1):
            candidate = self.providers[(start_idx + offset) % len(self.providers)]
            if candidate != current:
                self.task_providers[task_id] = candidate
                return current, candidate

        return None

    def _task_engine_for_provider(self, provider: str) -> EngineBase:
        """Build a fresh engine instance for a task launch."""
        return self._engine_factory(provider)

    def _record_provider_attempt(self, task_id: str, provider: str) -> None:
        """Track provider attempt counts for run summary and task reports."""
        self.provider_usage[provider] = self.provider_usage.get(provider, 0) + 1
        attempts = self.task_provider_attempts.setdefault(task_id, [])
        attempts.append(provider)

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
                failed = self.sched.count_failed()
                if failed > 0:
                    log.error(
                        "Workflow finished with failed tasks. "
                        f"{failed} task(s) failed."
                    )
                    return False
                break

            if self.sched.check_deadlock():
                self._report_deadlock()
                return False

            max_reached = self.cfg.max_iterations > 0 and self.iteration >= self.cfg.max_iterations
            if max_reached and pending > 0 and running == 0:
                log.warn(
                    "Reached max iterations "
                    f"({self.cfg.max_iterations}) with {pending} pending task(s). Stopping run."
                )
                return False

            # 3. Launch new tasks
            slots = self.cfg.max_parallel - running
            if slots > 0 and not max_reached:
                ready = self._get_ready_tasks()
                to_start = ready[:slots]
                for task_id in to_start:
                    self._launch_agent(task_id, original_dir, worktree_base)

            time.sleep(0.5)

        return True

    def _install_signal_handlers(self) -> None:
        """Install handlers so Ctrl-C can stop long-running parallel work."""
        self._orig_signal_handlers = {}
        signals_to_handle: list[signal.Signals] = [signal.SIGINT]
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

    def _on_signal(self, signum: int, _frame: FrameType | None) -> None:
        self._interrupt_count += 1
        self._stop_requested = True
        if self._interrupt_count == 1:
            log.warn(f"Interrupt received (signal {signum}). Stopping agents...")
        else:
            log.warn(f"Interrupt received again (signal {signum}). Forcing stop...")

    @staticmethod
    def _new_temp_file(prefix: str) -> Path:
        """Create a temporary file path safely and close the open descriptor."""
        fd, raw_path = tempfile.mkstemp(prefix=prefix)
        os.close(fd)
        return Path(raw_path)

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
        provider = self._provider_for_task(task_id)

        try:
            task_engine = self._task_engine_for_provider(provider)
        except Exception as e:
            log.error(f"Failed to create engine '{provider}' for {task_id}: {e}")
            self.sched.fail_task(task_id)
            return

        availability_error = task_engine.check_available()
        if availability_error:
            log.error(f"Provider '{provider}' unavailable for {task_id}: {availability_error}")
            self.sched.fail_task(task_id)
            return

        log.console.print(
            f"  [cyan]*[/cyan] Agent {self.agent_num}: "
            f"{title[:40]} ({task_id}) [{provider}]"
        )

        # Create temp files for IPC
        status_file = self._new_temp_file(prefix=f"gralph-status-{task_id}-")
        output_file = self._new_temp_file(prefix=f"gralph-output-{task_id}-")
        log_file = self._new_temp_file(prefix=f"gralph-log-{task_id}-")
        stream_file = self._new_temp_file(prefix=f"gralph-stream-{task_id}-")

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

        prompt = _build_task_prompt(
            task_id,
            title,
            touches,
            skip_tests=self.cfg.skip_tests,
            skip_lint=self.cfg.skip_lint,
        )
        write_text(status_file, "running")

        # Launch engine async
        try:
            proc = task_engine.run_async(
                prompt,
                cwd=wt_dir,
                stdout_file=stream_file,
                stderr_file=log_file,
            )
        except OSError as e:
            log.error(f"Failed to start provider '{provider}' for {task_id}: {e}")
            write_text(status_file, "failed")
            write_text(output_file, "0 0")
            self.sched.fail_task(task_id)
            cleanup_agent_worktree(
                wt_dir,
                branch_name,
                original_dir=original_dir,
                log_file=log_file,
            )
            for f in [status_file, output_file, log_file, stream_file]:
                f.unlink(missing_ok=True)
            return

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
                provider=provider,
                engine=task_engine,
            )
        )
        self._record_provider_attempt(task_id, provider)

    def _reap_finished(self, original_dir: Path) -> None:
        """Check active agents; process any that have finished."""
        still_active: list[AgentSlot] = []

        for slot in self.active:
            poll = slot.proc.poll()
            if poll is None:
                # Still running — check for stall
                if slot.log_file.is_file():
                    mtime = slot.log_file.stat().st_mtime
                    if mtime > slot.last_log_mtime:
                        slot.last_log_mtime = mtime
                        slot.last_activity = time.monotonic()

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
        self._accumulate_tokens(slot.stream_file, slot.engine or self.engine)

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
        self._external_failure_since.pop(slot.task_id, None)

        # If worktree has uncommitted changes, auto-commit
        if has_dirty_worktree(cwd=slot.worktree_dir):
            add_and_commit("Auto-commit remaining changes", cwd=slot.worktree_dir)

        sanitized = _sanitize_forbidden_task_files(self.cfg.base_branch, slot.worktree_dir)
        if sanitized:
            log.warn(f"Sanitized forbidden files from task branch: {', '.join(sanitized)}")

        # Merge or create PR
        merge_ok = True
        merge_error = ""
        delete_merged_branch = False
        if not self.cfg.create_pr:
            log.info(f"Merging {slot.branch_name} into {self.cfg.base_branch}…")
            merge_result = merge_no_edit_result(slot.branch_name, cwd=original_dir)
            if merge_result.returncode == 0:
                delete_merged_branch = True
            else:
                merge_ok = False
                merge_abort(cwd=original_dir)
                merged_output = (merge_result.stderr or merge_result.stdout or "").strip()
                if merged_output:
                    merged_output = " ".join(merged_output.split())

                # If no message is surfaced, report dirty entries to help diagnose
                # local-uncommitted-change failures.
                if not merged_output:
                    dirty_entries = dirty_worktree_entries(cwd=original_dir)
                    if dirty_entries:
                        merged_output = (
                            "Run branch has local uncommitted changes that block merge: "
                            + ", ".join(dirty_entries[:8])
                        )

                merge_error = merged_output or "git merge failed"
                log.error(f"Merge failed for {slot.branch_name}: {merge_error}")
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
                f"  [green]OK[/green] {title[:45]} ({slot.task_id})"
            )
            # Save report
            retries_used = self.retry_counts.get(slot.task_id, 0)
            self._save_report(
                slot,
                original_dir,
                "done",
                commits,
                merge_error,
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
            if delete_merged_branch:
                if not self.cfg.branch_per_task:
                    delete_branch(slot.branch_name, cwd=original_dir)
                self.completed_branches.append(slot.branch_name)
            return

        # Merge conflicts can happen when parallel tasks touch overlapping files.
        # Retry the task from a fresh worktree, but keep its current provider.
        self._handle_failure(
            slot,
            original_dir,
            title,
            merge_error or "git merge failed",
            commits=commits,
            allow_provider_switch=False,
        )


    def _handle_failure(
        self,
        slot: AgentSlot,
        original_dir: Path,
        title: str,
        err_msg: str,
        *,
        commits: int = 0,
        allow_provider_switch: bool = True,
    ) -> None:
        retries_used = self.retry_counts.get(slot.task_id, 0)
        attempt = retries_used + 1
        max_attempts = self.cfg.max_retries + 1
        is_external_failure = _is_external_failure(err_msg)
        should_retry = self._should_retry(err_msg, retries_used)
        provider_switch: tuple[str, str] | None = None

        if should_retry and is_external_failure and self.cfg.external_fail_timeout > 0:
            first_seen = self._external_failure_since.setdefault(slot.task_id, time.monotonic())
            elapsed = time.monotonic() - first_seen
            if elapsed >= self.cfg.external_fail_timeout:
                should_retry = False
                err_msg = f"{err_msg} (external failure timeout after {int(elapsed)}s)"
        elif not should_retry or not is_external_failure:
            self._external_failure_since.pop(slot.task_id, None)

        if should_retry:
            if allow_provider_switch and is_external_failure:
                provider_switch = self._rotate_provider_for_task(slot.task_id)
            self.retry_counts[slot.task_id] = retries_used + 1
            delay = max(self.cfg.retry_delay, 0)
            if delay:
                self.retry_after[slot.task_id] = time.monotonic() + delay
            self.sched.retry_task(slot.task_id)
            switch_note = ""
            if provider_switch:
                switch_note = (
                    f" provider {provider_switch[0]} -> {provider_switch[1]}"
                )
            log.console.print(
                f"  [yellow]RETRY[/yellow] {title[:45]} ({slot.task_id}) "
                f"in {delay}s (attempt {attempt + 1}/{max_attempts}){switch_note}"
            )
        else:
            self.sched.fail_task(slot.task_id)
            self._external_failure_since.pop(slot.task_id, None)
            log.console.print(f"  [red]x[/red] {title[:45]} ({slot.task_id})")

        if err_msg:
            log.console.print(f"[dim]    Error: {err_msg}[/dim]")

        status = "retrying" if should_retry else "failed"
        self._save_report(
            slot,
            original_dir,
            status,
            commits,
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
        provider_attempts = self.task_provider_attempts.get(slot.task_id, [])
        if not provider_attempts and slot.provider:
            provider_attempts = [slot.provider]

        report = {
            "taskId": slot.task_id,
            "title": title,
            "branch": slot.branch_name,
            "provider": slot.provider,
            "providerAttempts": provider_attempts,
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
        for tid in self.sched.pending_task_ids():
            if self.sched.has_failed_deps(tid):
                has_failed = True
                break

        if has_failed:
            log.error("Workflow halted: Dependencies failed, preventing further progress.")
        else:
            log.error("DEADLOCK: No progress possible (cycle or mutex contention)")

        log.console.print("")
        log.console.print("[red]Blocked tasks:[/red]")
        for tid in self.sched.pending_task_ids():
            reason = self.sched.explain_block(tid)
            log.console.print(f"  {tid}: {reason}")

    def _should_retry(self, err_msg: str, retries_used: int) -> bool:
        """Return True if this error should be retried."""
        if self.cfg.max_retries <= 0:
            return False
        if retries_used >= self.cfg.max_retries:
            return False
        lower = err_msg.lower()
        if "blocked by policy" in lower or "read-only sandbox" in lower:
            return False
        return _is_external_failure(err_msg)

    def _accumulate_tokens(self, stream_file: Path, engine: EngineBase) -> None:
        """Parse engine output from *stream_file* and accumulate token counts."""
        if not stream_file.is_file():
            return
        raw = read_text(stream_file, errors="replace")
        if not raw:
            return
        result = engine.parse_output(raw)
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens
