"""Claude Code engine adapter."""

from __future__ import annotations

import json
import shutil

from gralph.engines.base import EngineBase, EngineResult


class ClaudeEngine(EngineBase):
    name = "claude"

    def build_cmd(self, prompt: str) -> list[str]:
        # Use resolved path so subprocess gets an absolute path; on some platforms
        # (e.g. Windows with pipx) the child process resolves PATH differently.
        claude = shutil.which("claude") or "claude"
        return [
            claude,
            "--dangerously-skip-permissions",
            "--verbose",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
        ]

    def parse_output(self, raw: str) -> EngineResult:
        result = EngineResult()
        for line in raw.splitlines():
            if '"type":"result"' in line:
                try:
                    obj = json.loads(line)
                    result.text = obj.get("result", "")
                    usage = obj.get("usage", {})
                    result.input_tokens = int(usage.get("input_tokens", 0))
                    result.output_tokens = int(usage.get("output_tokens", 0))
                except (json.JSONDecodeError, ValueError, TypeError):
                    result.text = "Could not parse result"
        if not result.text:
            result.text = "Task completed"
        return result

    def check_available(self) -> str | None:
        if not shutil.which("claude"):
            return "Claude Code CLI not found. Install from https://github.com/anthropics/claude-code"
        return None
