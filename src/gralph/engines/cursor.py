"""Cursor agent engine adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text


def _is_rate_or_usage_error(error: str, stderr: str = "", stdout: str = "") -> bool:
    """True if the failure looks like a rate limit or usage limit from Cursor."""
    combined = " ".join((error, stderr, stdout)).lower()
    return (
        "rate limit" in combined
        or "usage limit" in combined
        or "you've hit your limit" in combined
        or '"error":"rate_limit"' in stdout
    )


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
        result = self._run_once(prompt, cwd=cwd, log_file=log_file, timeout=timeout)

        # On rate/usage limit, retry once with --model auto (higher limit), then fail if still error
        if result.error and _is_rate_or_usage_error(result.error, "", ""):
            # Re-detect from full stderr/stdout; we only have result.error here, so check that
            try:
                from gralph import log as glog

                glog.warn(
                    "Cursor hit rate/usage limit. Retrying with --model auto (higher usage allowance)…"
                )
            except Exception:
                pass
            retry = self._run_once(
                prompt,
                cwd=cwd,
                log_file=log_file,
                timeout=timeout,
                use_auto=True,
            )
            if not retry.error and retry.text:
                return retry
            # Retry also failed; return retry result so user sees the error
            return retry

        return result

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

        try:
            proc = subprocess.run(
                cmd,
                input=None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return EngineResult(error="timeout", return_code=-1)
        except FileNotFoundError:
            return EngineResult(error=f"{cmd[0]} not found", return_code=-1)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open_text(log_file, "a") as f:
                if proc.stderr:
                    f.write(proc.stderr)

        result = self.parse_output(proc.stdout or "")
        result.return_code = proc.returncode
        if not result.duration_ms:
            result.duration_ms = elapsed_ms

        stderr = (proc.stderr or "").strip()
        error = EngineBase._check_errors(proc.stdout)
        if error and not result.error:
            result.error = error

        if proc.returncode != 0 and not result.error:
            if stderr:
                result.error = stderr.splitlines()[0]
            else:
                result.error = f"exit code {proc.returncode}"

        # If we still have no error text but stderr has usage/rate message, set it
        if not result.error and stderr and _is_rate_or_usage_error("", stderr, proc.stdout or ""):
            result.error = stderr.splitlines()[0]

        return result

    def check_available(self) -> str | None:
        if not shutil.which("agent"):
            return (
                "Cursor agent CLI not found. "
                "Make sure Cursor is installed and 'agent' is in your PATH."
            )
        return None
