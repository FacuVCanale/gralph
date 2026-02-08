"""Cursor agent engine adapter."""

from __future__ import annotations

import json

from gralph.engines.base import EngineBase, EngineResult


class CursorEngine(EngineBase):
    name = "cursor"

    def build_cmd(self, prompt: str) -> list[str]:
        return [
            "agent",
            "--print",
            "--force",
            "--output-format",
            "stream-json",
            prompt,
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

    def check_available(self) -> str | None:
        import shutil

        if not shutil.which("agent"):
            return (
                "Cursor agent CLI not found. "
                "Make sure Cursor is installed and 'agent' is in your PATH."
            )
        return None
