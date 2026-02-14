"""Tests for gralph.config.Config defaults and providers field."""

from __future__ import annotations

from gralph.config import Config, DEFAULT_PROVIDERS, DEFAULT_SKILLS_URL


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


def test_default_skills_url_points_to_gralph_repo():
    """Default skills URL should use the active gralph skills source."""
    assert DEFAULT_SKILLS_URL == "https://raw.githubusercontent.com/FacuVCanale/gralph/main/skills"


def test_config_uses_default_skills_url_when_env_not_set(monkeypatch):
    """Config should resolve to DEFAULT_SKILLS_URL when no override env vars are set."""
    monkeypatch.delenv("GRALPH_SKILLS_BASE_URL", raising=False)
    monkeypatch.delenv("RALPH_SKILLS_BASE_URL", raising=False)

    cfg = Config()
    assert cfg.skills_base_url == DEFAULT_SKILLS_URL
