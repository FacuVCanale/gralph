"""Google Gemini CLI engine adapter."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text

# Windows and long prompts: use stdin to avoid command-line length limits (~32KB)
_STDIN_THRESHOLD = 8000


class GeminiEngine(EngineBase):
    name = "gemini"

    def build_cmd(self, prompt: str, *, use_stdin: bool = False) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        gemini = shutil.which("gemini") or "gemini"
        cmd = [gemini, "--output-format", "json"]
        if use_stdin:
            cmd.append("-")  # Read prompt from stdin
        else:
            cmd.extend(["-p", prompt])
        return cmd

    def parse_output(self, raw: str) -> EngineResult:
        result = EngineResult()
        raw = raw or ""

        # Try to parse each line as JSON looking for result/response objects
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            # Extract text from response object
            text = obj.get("response", "") or obj.get("result", "") or obj.get("text", "")
            if text and not result.text:
                result.text = text

            # Extract token usage if present
            usage = obj.get("usage", {}) or obj.get("usageMetadata", {})
            if usage:
                result.input_tokens = int(
                    usage.get("input_tokens", 0)
                    or usage.get("promptTokenCount", 0)
                )
                result.output_tokens = int(
                    usage.get("output_tokens", 0)
                    or usage.get("candidatesTokenCount", 0)
                )

        # Fallback: if no JSON result found, use raw text (minus empty lines)
        if not result.text:
            stripped = raw.strip()
            if stripped:
                result.text = stripped
            else:
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
        """Execute Gemini CLI, passing long prompts via stdin on Windows."""
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
        """Launch Gemini CLI asynchronously, passing long prompts via stdin on Windows."""
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

    def check_available(self) -> str | None:
        if not shutil.which("gemini"):
            return (
                "Gemini CLI not found. "
                "Install from https://github.com/google-gemini/gemini-cli"
            )
        return None
