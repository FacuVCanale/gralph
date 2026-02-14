"""OpenCode engine adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import IO

from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text


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

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                timeout=timeout,
                env=env,
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

        error = self._check_errors(proc.stdout)
        if error and not result.error:
            result.error = error

        if proc.returncode != 0 and not result.error:
            stderr = (proc.stderr or "").strip()
            if stderr:
                result.error = stderr.splitlines()[0]
            else:
                result.error = f"exit code {proc.returncode}"

        return result

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
                env=env,
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
