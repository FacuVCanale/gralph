"""Codex CLI engine adapter."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import IO

from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import open_text

# Windows and long prompts: use stdin to avoid command-line length limits (~32KB)
_STDIN_THRESHOLD = 8000
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return None


class CodexEngine(EngineBase):
    name = "codex"

    def build_cmd(self, prompt: str, *, use_stdin: bool = False) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        codex = shutil.which("codex") or "codex"
        safe_mode = _env_bool("GRALPH_CODEX_SAFE")
        dangerous_mode = _env_bool("GRALPH_CODEX_DANGEROUS")
        use_dangerous = True
        if safe_mode is True:
            use_dangerous = False
        if dangerous_mode is not None:
            use_dangerous = dangerous_mode

        if use_dangerous:
            cmd = [
                codex,
                "--dangerously-bypass-approvals-and-sandbox",
                "exec",
                "--json",
            ]
        else:
            cmd = [
                codex,
                "-a",
                "on-failure",
                "-s",
                "workspace-write",
                "exec",
                "--json",
            ]
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
        """Launch Codex asynchronously, passing long prompts via stdin on Windows."""
        use_stdin = len(prompt) > _STDIN_THRESHOLD or platform.system() == "Windows"
        cmd = self.build_cmd(prompt, use_stdin=use_stdin)

        stdout_fh: IO[str] | int = open_text(stdout_file, "w") if stdout_file else subprocess.PIPE
        stderr_fh: IO[str] | int = open_text(stderr_file, "a") if stderr_file else subprocess.PIPE
        creationflags = self._creationflags()

        if use_stdin:
            if creationflags:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=stdout_fh,
                    stderr=stderr_fh,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=cwd,
                    creationflags=creationflags,
                )
            else:
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

    def parse_output(self, raw: str) -> EngineResult:
        result = EngineResult()
        if not raw:
            result.text = "Task completed"
            return result

        assistant_parts: list[str] = []
        fallback_lines: list[str] = []
        saw_json_event = False

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            try:
                obj = json.loads(stripped)
                saw_json_event = True
            except (json.JSONDecodeError, ValueError):
                fallback_lines.append(stripped)
                continue

            if not isinstance(obj, dict):
                continue

            event_type = obj.get("type")
            top_level_text = self._extract_text(obj)
            if event_type == "agent_message" and top_level_text:
                assistant_parts.append(top_level_text)

            if not result.error:
                err = obj.get("error")
                if isinstance(err, dict):
                    msg = str(err.get("message", "")).strip()
                    code = str(err.get("type", "") or err.get("code", "")).strip().lower()
                    if "rate_limit" in code or "rate limit" in code or "quota" in code:
                        result.error = msg or "Rate limit exceeded"
                    elif msg:
                        result.error = msg
                elif isinstance(err, str) and err.strip():
                    lower_err = err.lower()
                    if "rate_limit" in lower_err or "rate limit" in lower_err or "quota" in lower_err:
                        result.error = "Rate limit exceeded"
                    else:
                        result.error = err.strip()

            item = obj.get("item")
            if isinstance(item, dict):
                item_type = item.get("type")
                item_text = self._extract_text(item)
                if item_type == "agent_message" and item_text:
                    assistant_parts.append(item_text)
                elif item_type == "error" and item_text and not result.error:
                    result.error = item_text

            if event_type == "error" and not result.error:
                err = obj.get("error", "")
                if isinstance(err, dict):
                    result.error = str(err.get("message", "")).strip()
                else:
                    result.error = str(err).strip()

        if assistant_parts:
            result.text = "\n\n".join(assistant_parts).strip()
            return result

        cleaned = [line for line in fallback_lines if line != "Task completed successfully."]
        if cleaned:
            result.text = "\n".join(cleaned)
            return result

        if saw_json_event:
            result.text = "Task completed"
            return result

        result.text = "Task completed"
        return result

    @staticmethod
    def _extract_text(payload: dict[str, object]) -> str:
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_text = part.get("text")
                if isinstance(part_text, str) and part_text:
                    parts.append(part_text)
            merged = "".join(parts).strip()
            if merged:
                return merged

        return ""

    def check_available(self) -> str | None:
        if not shutil.which("codex"):
            return "Codex CLI not found. Make sure 'codex' is in your PATH."
        return None
