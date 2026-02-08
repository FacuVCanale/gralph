"""Codex CLI engine adapter."""

from __future__ import annotations

from gralph.engines.base import EngineBase, EngineResult


class CodexEngine(EngineBase):
    name = "codex"

    def build_cmd(self, prompt: str) -> list[str]:
        return ["codex", "exec", "--full-auto", "--json", prompt]

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
        import shutil

        if not shutil.which("codex"):
            return "Codex CLI not found. Make sure 'codex' is in your PATH."
        return None
