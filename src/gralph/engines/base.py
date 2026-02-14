"""Base class for AI engine adapters."""

from __future__ import annotations

import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from gralph.io_utils import open_text


@dataclass
class EngineResult:
    """Uniform result from any engine invocation."""

    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    actual_cost: str = "0"
    error: str = ""
    return_code: int = 0


class EngineBase(ABC):
    """Abstract engine adapter.  Subclasses implement ``build_cmd``."""

    name: str = "base"

    @abstractmethod
    def build_cmd(self, prompt: str) -> list[str]:
        """Return the CLI command list for the given prompt."""
        ...

    @abstractmethod
    def parse_output(self, raw: str) -> EngineResult:
        """Parse raw stdout into an :class:`EngineResult`."""
        ...

    def check_available(self) -> str | None:
        """Return an error message if the engine CLI is not available, else None."""
        cmd_name = self.build_cmd("test")[0]
        import shutil

        if not shutil.which(cmd_name):
            return f"{cmd_name} not found in PATH"
        return None

    def run_sync(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        log_file: Path | None = None,
        timeout: int | None = None,
    ) -> EngineResult:
        """Execute the engine synchronously and return parsed result."""
        cmd = self.build_cmd(prompt)
        start = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
            )
        except FileNotFoundError:
            return EngineResult(error=f"{cmd[0]} not found", return_code=-1)

        try:
            proc_stdout, proc_stderr = self._communicate_with_interrupts(proc, timeout=timeout)
        except subprocess.TimeoutExpired:
            self._terminate_process(proc)
            return EngineResult(error="timeout", return_code=-1)
        except KeyboardInterrupt:
            self._terminate_process(proc)
            raise

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open_text(log_file, "a") as f:
                if proc_stderr:
                    f.write(proc_stderr)

        result = self.parse_output(proc_stdout or "")
        result.return_code = proc.returncode
        if not result.duration_ms:
            result.duration_ms = elapsed_ms

        # Check for common errors in output
        error = self._check_errors(proc_stdout or "")
        if error and not result.error:
            result.error = error

        # If the subprocess failed, surface stderr to the caller. Some CLIs (notably
        # on Windows) report argument/permission issues on stderr and otherwise
        # produce empty stdout, which makes failures look like "did nothing".
        if proc.returncode != 0 and not result.error:
            stderr = (proc_stderr or "").strip()
            if stderr:
                # Keep it readable in CLI output
                result.error = stderr.splitlines()[0]
            else:
                result.error = f"exit code {proc.returncode}"

        return result

    @staticmethod
    def _communicate_with_interrupts(
        proc: subprocess.Popen[str],
        *,
        timeout: int | None,
    ) -> tuple[str, str]:
        """Read process output while remaining responsive to KeyboardInterrupt."""
        if timeout is None:
            return proc.communicate()

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)

            wait_timeout = min(0.2, remaining)
            try:
                return proc.communicate(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                continue

    @staticmethod
    def _terminate_process(proc: subprocess.Popen[str]) -> None:
        """Terminate a subprocess promptly (best effort)."""
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

        try:
            proc.wait(timeout=2)
            return
        except Exception:
            pass

        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

        try:
            proc.wait(timeout=2)
        except Exception:
            pass

    def run_async(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        stdout_file: Path | None = None,
        stderr_file: Path | None = None,
    ) -> subprocess.Popen[str]:
        """Launch the engine asynchronously, returning the Popen handle."""
        cmd = self.build_cmd(prompt)

        stdout_fh: IO[str] | int = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_fh: IO[str] | int = open_text(stderr_file, "a") if stderr_file else subprocess.PIPE
        creationflags = self._creationflags()

        if creationflags:
            return subprocess.Popen(
                cmd,
                stdout=stdout_fh,
                stderr=stderr_fh,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                creationflags=creationflags,
            )

        return subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        )

    @staticmethod
    def _creationflags() -> int:
        """Creation flags for async worker processes."""
        if sys.platform == "win32":
            return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return 0

    @staticmethod
    def _check_errors(raw: str) -> str:
        """Detect common error patterns in engine output."""
        if not raw:
            return ""

        import json

        # Prefer structured parsing to avoid false positives from plain text content.
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            if not isinstance(obj, dict):
                continue

            err = obj.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message", "")).strip()
                code = str(err.get("type", "") or err.get("code", "")).strip().lower()
                if "rate_limit" in code or "rate limit" in code or "quota" in code:
                    return msg or "Rate limit exceeded"
                if msg:
                    return msg

            if isinstance(err, str):
                err_lower = err.lower()
                if "blocked by policy" in err_lower:
                    return "Blocked by policy"
                if "rate_limit" in err_lower or "rate limit" in err_lower or "quota" in err_lower:
                    return "Rate limit exceeded"
                if "hit your limit" in err_lower:
                    return "Rate limit exceeded"
                if err.strip():
                    return err.strip()

            if str(obj.get("type", "")).lower() == "error":
                msg = ""
                if isinstance(obj.get("message"), str):
                    msg = obj["message"].strip()
                elif isinstance(obj.get("text"), str):
                    msg = obj["text"].strip()

                if msg:
                    msg_lower = msg.lower()
                    if "blocked by policy" in msg_lower:
                        return "Blocked by policy"
                    if "rate_limit" in msg_lower or "rate limit" in msg_lower or "quota" in msg_lower:
                        return "Rate limit exceeded"
                    if "hit your limit" in msg_lower:
                        return "Rate limit exceeded"
                    return msg
                return "Unknown error"

        return ""
