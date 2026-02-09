"""Cursor agent engine adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from gralph.engines.base import EngineBase, EngineResult


class CursorEngine(EngineBase):
    name = "cursor"

    def build_cmd(self, prompt: str) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        # Note: prompt is passed via stdin in run_sync to avoid Windows command-line length limits.
        agent = shutil.which("agent") or "agent"
        return [
            agent,
            "--print",
            "--force",
            "--output-format",
            "stream-json",
        ]

    def parse_output(self, raw: str) -> EngineResult:
        result = EngineResult()

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
        """Execute Cursor agent with prompt via stdin to avoid Windows command-line length limits."""
        cmd = self.build_cmd(prompt)
        start = time.monotonic()

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
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
            with open(log_file, "a", encoding="utf-8") as f:
                if proc.stderr:
                    f.write(proc.stderr)

        result = self.parse_output(proc.stdout)
        result.return_code = proc.returncode
        if not result.duration_ms:
            result.duration_ms = elapsed_ms

        # Check for common errors in output
        from gralph.engines.base import EngineBase

        error = EngineBase._check_errors(proc.stdout)
        if error and not result.error:
            result.error = error

        # If the subprocess failed, surface stderr to the caller
        if proc.returncode != 0 and not result.error:
            stderr = (proc.stderr or "").strip()
            if stderr:
                result.error = stderr.splitlines()[0]
            else:
                result.error = f"exit code {proc.returncode}"

        return result

    def check_available(self) -> str | None:
        if not shutil.which("agent"):
            return (
                "Cursor agent CLI not found. "
                "Make sure Cursor is installed and 'agent' is in your PATH."
            )
        return None
