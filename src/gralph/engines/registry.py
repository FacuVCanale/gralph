"""Engine registry — get the right adapter by name."""

from __future__ import annotations

from gralph.engines.base import EngineBase
from gralph.engines.claude import ClaudeEngine
from gralph.engines.codex import CodexEngine
from gralph.engines.cursor import CursorEngine
from gralph.engines.opencode import OpenCodeEngine


def get_engine(name: str, *, opencode_model: str = "") -> EngineBase:
    """Return an engine adapter for *name*."""
    match name:
        case "claude":
            return ClaudeEngine()
        case "opencode":
            return OpenCodeEngine(model=opencode_model)
        case "codex":
            return CodexEngine()
        case "cursor":
            return CursorEngine()
        case _:
            raise ValueError(f"Unknown engine: {name}")


ENGINE_NAMES = ("claude", "opencode", "codex", "cursor")
