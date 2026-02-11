"""Codex CLI engine adapter."""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path

from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text

# Windows and long prompts: use stdin to avoid command-line length limits (~32KB)
_STDIN_THRESHOLD = 8000


class CodexEngine(EngineBase):
    name = "codex"

    def build_cmd(self, prompt: str, *, use_stdin: bool = False) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        codex = shutil.which("codex") or "codex"
        cmd = [codex, "exec", "--full-auto", "--json"]
        if use_stdin:
            cmd.append("-")  # Read prompt from stdin
        else:
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
        """Override to pass long prompts via stdin (Codex supports '-' for stdin)."""
        use_stdin = len(prompt) > _STDIN_THRESHOLD or platform.system() == "Windows"
        cmd = self.build_cmd(prompt, use_stdin=use_stdin)
        start = time.monotonic()

        try:
            proc = subprocess.run(
                cmd,
                input=prompt if use_stdin else None,
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
    ) -> subprocess.Popen:  # type: ignore[type-arg]
        """Launch Codex asynchronously, passing long prompts via stdin on Windows."""
        use_stdin = len(prompt) > _STDIN_THRESHOLD or platform.system() == "Windows"
        cmd = self.build_cmd(prompt, use_stdin=use_stdin)

        stdout_fh = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_fh = open_text(stderr_file, "a") if stderr_file else subprocess.PIPE

        if use_stdin:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=stdout_fh,
                stderr=stderr_fh,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
            )
            if proc.stdin:
                try:
                    proc.stdin.write(prompt)
                    proc.stdin.close()
                except Exception:
                    pass
            return proc

        return subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        )

    def parse_output(self, raw: str) -> EngineResult:
        # Codex output is simpler — we rely on commit detection
        result = EngineResult()
        if raw:
            # Remove generic completion line
            lines = raw.strip().splitlines()
            cleaned = [
                l for l in lines if l.strip() != "Task completed successfully."
            ]
            result.text = "\n".join(cleaned) if cleaned else "Task completed"
        else:
            result.text = "Task completed"
        return result

    def check_available(self) -> str | None:
        if not shutil.which("codex"):
            return "Codex CLI not found. Make sure 'codex' is in your PATH."
        return None
