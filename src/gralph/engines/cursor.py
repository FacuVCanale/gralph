"""Cursor agent engine adapter."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from gralph.engine_errors import looks_like_rate_limit
from gralph.engines.base import EngineBase, EngineResult


def _is_rate_or_usage_error(error: str, stderr: str = "", stdout: str = "") -> bool:
    """True if the failure looks like a rate limit or usage limit from Cursor."""
    combined = " ".join((error, stderr, stdout)).lower()
    return looks_like_rate_limit(combined) or '"error":"rate_limit"' in stdout


class CursorEngine(EngineBase):
    name = "cursor"

    def build_cmd(self, prompt: str, *, use_auto: bool = False) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        # Cursor print mode requires the prompt as a CLI argument.
        agent = shutil.which("agent") or "agent"
        cmd = [
            agent,
            "--print",
            "--force",
            "--output-format",
            "stream-json",
        ]
        if use_auto:
            cmd.extend(["--model", "auto"])
        cmd.append(prompt)
        return cmd

    def parse_output(self, raw: str | None) -> EngineResult:
        result = EngineResult()
        raw = raw or ""

        for line in raw.splitlines():
            if '"type":"result"' in line:
                try:
                    obj = json.loads(line)
                    result.text = obj.get("result", "Task completed")
                    duration = obj.get("duration_ms", 0)
                    if isinstance(duration, (int, float)) and duration > 0:
                        result.duration_ms = int(duration)
                        result.actual_cost = f"duration:{int(duration)}"
                except (json.JSONDecodeError, ValueError, TypeError):
                    result.text = "Task completed"

        # Fallback: assistant message
        if not result.text or result.text == "Task completed":
            for line in raw.splitlines():
                if '"type":"assistant"' in line:
                    try:
                        obj = json.loads(line)
                        content = obj.get("message", {}).get("content", [])
                        if isinstance(content, list) and content:
                            result.text = content[0].get("text", "Task completed")
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass

        # Cursor doesn't provide token counts
        result.input_tokens = 0
        result.output_tokens = 0

        if not result.text:
            result.text = "Task completed"
        return result

    def run_sync(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        log_file: Path | None = None,
        timeout: int | None = None,
    ) -> EngineResult:
        """Execute Cursor agent synchronously."""
        return self._run_once(prompt, cwd=cwd, log_file=log_file, timeout=timeout)

    def _run_once(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        log_file: Path | None = None,
        timeout: int | None = None,
        use_auto: bool = False,
    ) -> EngineResult:
        """Single Cursor agent run. use_auto=True adds --model auto."""
        cmd = self.build_cmd(prompt, use_auto=use_auto)
        start = time.monotonic()

        proc_or_error = self._run_completed_subprocess(
            cmd,
            cwd=cwd,
            timeout=timeout,
        )
        if isinstance(proc_or_error, EngineResult):
            return proc_or_error

        result = self.parse_output(proc_or_error.stdout or "")
        result = self._finalize_completed_run(
            proc=proc_or_error,
            result=result,
            start_monotonic=start,
            log_file=log_file,
        )

        stderr = (proc_or_error.stderr or "").strip()
        error = EngineBase._check_errors(proc_or_error.stdout)
        if error and not result.error:
            result.error = error

        # If we still have no error text but stderr has usage/rate message, set it
        if not result.error and stderr and _is_rate_or_usage_error("", stderr, proc_or_error.stdout or ""):
            result.error = stderr.splitlines()[0]

        return result

    def check_available(self) -> str | None:
        if not shutil.which("agent"):
            return (
                "Cursor agent CLI not found. "
                "Make sure Cursor is installed and 'agent' is in your PATH."
            )
        return None
