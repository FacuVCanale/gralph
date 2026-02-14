"""OpenCode engine adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from gralph.engines.base import EngineBase, EngineResult


class OpenCodeEngine(EngineBase):
    name = "opencode"

    def __init__(self, model: str = "opencode/minimax-m2.1-free") -> None:
        self.model = model

    def build_cmd(self, prompt: str) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        opencode = shutil.which("opencode") or "opencode"
        cmd = [opencode, "run", "--format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(prompt)
        return cmd

    def run_sync(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        log_file: Path | None = None,
        timeout: int | None = None,
    ) -> EngineResult:
        """Override to inject OPENCODE_PERMISSION env var."""
        env = os.environ.copy()
        env["OPENCODE_PERMISSION"] = '{"*":"allow"}'

        cmd = self.build_cmd(prompt)
        start = time.monotonic()

        proc_or_error = self._run_completed_subprocess(
            cmd,
            cwd=cwd,
            timeout=timeout,
            env=env,
        )
        if isinstance(proc_or_error, EngineResult):
            return proc_or_error

        result = self.parse_output(proc_or_error.stdout or "")
        return self._finalize_completed_run(
            proc=proc_or_error,
            result=result,
            start_monotonic=start,
            log_file=log_file,
        )

    def run_async(
        self,
        prompt: str,
        *,
        cwd: Path | None = None,
        stdout_file: Path | None = None,
        stderr_file: Path | None = None,
    ) -> subprocess.Popen[str]:
        """Override to inject OPENCODE_PERMISSION env var."""
        cmd = self.build_cmd(prompt)
        env = os.environ.copy()
        env["OPENCODE_PERMISSION"] = '{"*":"allow"}'
        return self._launch_async_cmd(
            cmd,
            cwd=cwd,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            env=env,
        )

    def parse_output(self, raw: str) -> EngineResult:
        result = EngineResult()
        for line in raw.splitlines():
            if '"type":"step_finish"' in line:
                try:
                    obj = json.loads(line)
                    part = obj.get("part", {})
                    tokens = part.get("tokens", {})
                    result.input_tokens = int(tokens.get("input", 0))
                    result.output_tokens = int(tokens.get("output", 0))
                    result.actual_cost = str(part.get("cost", "0"))
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

        # Collect text from text events
        parts: list[str] = []
        for line in raw.splitlines():
            if '"type":"text"' in line:
                try:
                    obj = json.loads(line)
                    text = obj.get("part", {}).get("text", "")
                    if text:
                        parts.append(text)
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

        result.text = "".join(parts) if parts else "Task completed"
        return result

    def check_available(self) -> str | None:
        if not shutil.which("opencode"):
            return "OpenCode CLI not found. Install from https://opencode.ai/docs/"
        return None
