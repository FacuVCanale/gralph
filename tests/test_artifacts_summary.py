"""Tests for run summary banner and cost display in artifacts.py."""

from __future__ import annotations

import pytest

from gralph.artifacts import _estimate_cost, _ENGINE_PRICING, show_summary
from gralph.config import Config


class TestEstimateCost:
    """Tests for _estimate_cost helper."""

    def test_claude_pricing(self):
        cost = _estimate_cost("claude", 1_000_000, 1_000_000)
        inp_price, out_price = _ENGINE_PRICING["claude"]
        expected = (1_000_000 * inp_price) + (1_000_000 * out_price)
        assert cost == pytest.approx(expected)

    def test_gemini_pricing(self):
        cost = _estimate_cost("gemini", 1_000_000, 1_000_000)
        inp_price, out_price = _ENGINE_PRICING["gemini"]
        expected = (1_000_000 * inp_price) + (1_000_000 * out_price)
        assert cost == pytest.approx(expected)

    def test_gemini_cheaper_than_claude(self):
        """Gemini pricing should be significantly lower than Claude."""
        gemini_cost = _estimate_cost("gemini", 100_000, 100_000)
        claude_cost = _estimate_cost("claude", 100_000, 100_000)
        assert gemini_cost < claude_cost

    def test_codex_pricing(self):
        cost = _estimate_cost("codex", 500_000, 500_000)
        inp_price, out_price = _ENGINE_PRICING["codex"]
        expected = (500_000 * inp_price) + (500_000 * out_price)
        assert cost == pytest.approx(expected)

    def test_unknown_engine_uses_default(self):
        """Unknown engines should fall back to Claude pricing."""
        unknown = _estimate_cost("unknown_engine", 1000, 1000)
        claude = _estimate_cost("claude", 1000, 1000)
        assert unknown == pytest.approx(claude)

    def test_zero_tokens(self):
        assert _estimate_cost("gemini", 0, 0) == 0.0

    def test_only_input_tokens(self):
        cost = _estimate_cost("gemini", 1000, 0)
        inp_price, _ = _ENGINE_PRICING["gemini"]
        assert cost == pytest.approx(1000 * inp_price)

    def test_only_output_tokens(self):
        cost = _estimate_cost("gemini", 0, 1000)
        _, out_price = _ENGINE_PRICING["gemini"]
        assert cost == pytest.approx(1000 * out_price)


class TestShowSummaryGemini:
    """Tests for Gemini in show_summary display."""

    def test_gemini_shows_token_counts(self, capsys):
        cfg = Config(ai_engine="gemini")
        show_summary(cfg, 3, total_input_tokens=5000, total_output_tokens=2000)
        out = capsys.readouterr().out
        assert "5000" in out
        assert "2000" in out
        assert "7000" in out

    def test_gemini_shows_estimated_cost(self, capsys):
        cfg = Config(ai_engine="gemini")
        show_summary(cfg, 1, total_input_tokens=1_000_000, total_output_tokens=500_000)
        out = capsys.readouterr().out
        assert "Est. cost:" in out
        # Should show Gemini pricing, not Claude pricing
        expected = _estimate_cost("gemini", 1_000_000, 500_000)
        assert f"${expected:.4f}" in out

    def test_gemini_not_cursor_message(self, capsys):
        """Gemini should NOT show the Cursor 'token usage not available' message."""
        cfg = Config(ai_engine="gemini")
        show_summary(cfg, 1, total_input_tokens=100, total_output_tokens=100)
        out = capsys.readouterr().out
        assert "not available" not in out

    def test_cursor_still_shows_not_available(self, capsys):
        cfg = Config(ai_engine="cursor")
        show_summary(cfg, 1)
        out = capsys.readouterr().out
        assert "not available" in out

    def test_claude_uses_claude_pricing(self, capsys):
        cfg = Config(ai_engine="claude")
        show_summary(cfg, 1, total_input_tokens=1_000_000, total_output_tokens=500_000)
        out = capsys.readouterr().out
        expected = _estimate_cost("claude", 1_000_000, 500_000)
        assert f"${expected:.4f}" in out

    def test_summary_shows_task_count(self, capsys):
        cfg = Config(ai_engine="gemini")
        show_summary(cfg, 5)
        out = capsys.readouterr().out
        assert "5 task(s)" in out

    def test_summary_shows_branches(self, capsys):
        cfg = Config(ai_engine="gemini")
        show_summary(cfg, 1, branches=["gralph/task-001", "gralph/task-002"])
        out = capsys.readouterr().out
        assert "gralph/task-001" in out
        assert "gralph/task-002" in out

    def test_summary_shows_provider_usage(self, capsys):
        cfg = Config(ai_engine="gemini")
        show_summary(cfg, 1, provider_usage={"claude": 2, "codex": 1, "gemini": 0})
        out = capsys.readouterr().out
        assert "Provider Usage" in out
        assert "claude: 2 task attempt(s)" in out
        assert "codex: 1 task attempt(s)" in out
        assert "gemini: 0" not in out


class TestEnginePricingTable:
    """Verify pricing table has expected entries."""

    def test_gemini_in_pricing(self):
        assert "gemini" in _ENGINE_PRICING

    def test_claude_in_pricing(self):
        assert "claude" in _ENGINE_PRICING

    def test_codex_in_pricing(self):
        assert "codex" in _ENGINE_PRICING

    def test_pricing_values_positive(self):
        for engine, (inp, out) in _ENGINE_PRICING.items():
            assert inp > 0, f"{engine} input price should be positive"
            assert out > 0, f"{engine} output price should be positive"
