"""Tests for gralph.config.Config — providers field."""

from __future__ import annotations

from gralph.config import Config, DEFAULT_PROVIDERS


def test_default_providers_populated():
    """Config().providers contains all default providers."""
    cfg = Config()
    assert cfg.providers == list(DEFAULT_PROVIDERS)


def test_default_providers_is_mutable_copy():
    """Each Config instance gets its own list (not a shared reference)."""
    a = Config()
    b = Config()
    a.providers.append("custom")
    assert "custom" not in b.providers


def test_custom_providers():
    """Providers can be overridden at construction time."""
    cfg = Config(providers=["claude", "gemini"])
    assert cfg.providers == ["claude", "gemini"]


def test_empty_providers():
    """An empty providers list is allowed."""
    cfg = Config(providers=[])
    assert cfg.providers == []
