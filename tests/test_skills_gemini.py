"""Tests for Gemini integration into the skills system and PRD skill lookup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gralph.skills import _skill_candidates, _skill_install_target, skill_exists


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Create a fake repo root for testing."""
    return tmp_path / "repo"


@pytest.fixture()
def fake_home(tmp_path: Path) -> Path:
    """Create a fake home directory for testing."""
    return tmp_path / "home"


def _patch_roots(fake_repo: Path, fake_home: Path):
    """Return a combined patcher for resolve_repo_root and Path.home."""

    class _Ctx:
        def __init__(self, repo: Path, home: Path):
            self._repo = repo
            self._home = home
            self._patchers: list = []

        def __enter__(self):
            p1 = patch("gralph.skills.resolve_repo_root", return_value=self._repo)
            p2 = patch("gralph.skills.Path.home", return_value=self._home)
            self._patchers = [p1, p2]
            for p in self._patchers:
                p.start()
            return self

        def __exit__(self, *args):
            for p in self._patchers:
                p.stop()

    return _Ctx(fake_repo, fake_home)


# ── _skill_candidates tests ──────────────────────────────────────


class TestGeminiSkillCandidates:
    """Tests for _skill_candidates() with engine='gemini'."""

    def test_returns_two_candidates(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")
        assert len(candidates) == 2

    def test_project_path_first(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")
        assert candidates[0] == fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"

    def test_user_path_second(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")
        assert candidates[1] == fake_home / ".gemini" / "skills" / "prd" / "SKILL.md"

    def test_skill_name_in_path(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "dag-planner")
        # Use Path parts to check for skill name (cross-platform)
        assert "dag-planner" in candidates[0].parts
        assert "dag-planner" in candidates[1].parts

    def test_unknown_engine_returns_empty(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("unknown-engine", "prd")
        assert candidates == []


# ── _skill_install_target tests ──────────────────────────────────


class TestGeminiSkillInstallTarget:
    """Tests for _skill_install_target() with engine='gemini'."""

    def test_returns_project_path_when_writable(self, fake_repo: Path, fake_home: Path) -> None:
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            target = _skill_install_target("gemini", "prd")
        assert target is not None
        expected = fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"
        assert target == expected

    def test_creates_parent_directories(self, fake_repo: Path, fake_home: Path) -> None:
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            target = _skill_install_target("gemini", "ralph")
        assert target is not None
        assert target.parent.is_dir()

    def test_returns_none_for_unknown_engine(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            target = _skill_install_target("unknown-engine", "prd")
        assert target is None


# ── skill_exists tests ───────────────────────────────────────────


class TestGeminiSkillExists:
    """Tests for skill_exists() with engine='gemini'."""

    def test_false_when_no_file(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            assert skill_exists("gemini", "prd") is False

    def test_true_when_project_file_exists(self, fake_repo: Path, fake_home: Path) -> None:
        skill_path = fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("# PRD skill")
        with _patch_roots(fake_repo, fake_home):
            assert skill_exists("gemini", "prd") is True

    def test_true_when_user_file_exists(self, fake_repo: Path, fake_home: Path) -> None:
        skill_path = fake_home / ".gemini" / "skills" / "prd" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("# PRD skill")
        with _patch_roots(fake_repo, fake_home):
            assert skill_exists("gemini", "prd") is True


# ── _find_prd_skill tests ───────────────────────────────────────


class TestFindPrdSkillGemini:
    """Tests for _find_prd_skill() with engine='gemini' in cli.py."""

    def _patch_cli_roots(self, fake_repo: Path, fake_home: Path):
        """Patch resolve_repo_root and Path.home for cli module."""

        class _Ctx:
            def __init__(self, repo: Path, home: Path):
                self._repo = repo
                self._home = home
                self._patchers: list = []

            def __enter__(self):
                # _find_prd_skill does: from gralph.config import resolve_repo_root
                # so we patch it at the source (gralph.config) where it's imported from
                p1 = patch("gralph.config.resolve_repo_root", return_value=self._repo)
                p2 = patch("pathlib.Path.home", return_value=self._home)
                self._patchers = [p1, p2]
                for p in self._patchers:
                    p.start()
                return self

            def __exit__(self, *args):
                for p in self._patchers:
                    p.stop()

        return _Ctx(fake_repo, fake_home)

    def test_finds_project_prd_skill(self, fake_repo: Path, fake_home: Path) -> None:
        from gralph.cli import _find_prd_skill

        skill_path = fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("# PRD skill for gemini")

        with self._patch_cli_roots(fake_repo, fake_home):
            result = _find_prd_skill("gemini")

        assert result == skill_path

    def test_finds_user_prd_skill(self, fake_repo: Path, fake_home: Path) -> None:
        from gralph.cli import _find_prd_skill

        skill_path = fake_home / ".gemini" / "skills" / "prd" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("# PRD skill for gemini")

        with self._patch_cli_roots(fake_repo, fake_home):
            result = _find_prd_skill("gemini")

        assert result == skill_path

    def test_prefers_bundled_over_user_skill(self, fake_repo: Path, fake_home: Path) -> None:
        from gralph.cli import _find_prd_skill

        user_skill = fake_home / ".gemini" / "skills" / "prd" / "SKILL.md"
        user_skill.parent.mkdir(parents=True, exist_ok=True)
        user_skill.write_text("# user skill")

        bundled = fake_repo / "skills" / "prd" / "SKILL.md"
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text("# bundled skill")

        with self._patch_cli_roots(fake_repo, fake_home):
            result = _find_prd_skill("gemini")

        assert result == bundled

    def test_prefers_project_over_bundled_and_user(self, fake_repo: Path, fake_home: Path) -> None:
        from gralph.cli import _find_prd_skill

        project_skill = fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"
        project_skill.parent.mkdir(parents=True, exist_ok=True)
        project_skill.write_text("# project skill")

        user_skill = fake_home / ".gemini" / "skills" / "prd" / "SKILL.md"
        user_skill.parent.mkdir(parents=True, exist_ok=True)
        user_skill.write_text("# user skill")

        bundled = fake_repo / "skills" / "prd" / "SKILL.md"
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text("# bundled skill")

        with self._patch_cli_roots(fake_repo, fake_home):
            result = _find_prd_skill("gemini")

        assert result == project_skill

    def test_falls_back_to_bundled_skill(self, fake_repo: Path, fake_home: Path) -> None:
        from gralph.cli import _find_prd_skill

        bundled = fake_repo / "skills" / "prd" / "SKILL.md"
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text("# Bundled PRD skill")

        with self._patch_cli_roots(fake_repo, fake_home):
            result = _find_prd_skill("gemini")

        assert result == bundled

    def test_returns_none_when_no_skill(self, fake_repo: Path, fake_home: Path) -> None:
        from gralph.cli import _find_prd_skill

        fake_repo.mkdir(parents=True, exist_ok=True)
        with self._patch_cli_roots(fake_repo, fake_home):
            result = _find_prd_skill("gemini")

        assert result is None


# ── Consistency tests ────────────────────────────────────────────


class TestGeminiSkillPathConsistency:
    """Ensure _skill_candidates and _find_prd_skill use matching paths for Gemini."""

    def test_candidates_use_gemini_skills_dir(self, fake_repo: Path, fake_home: Path) -> None:
        """The Gemini paths in _skill_candidates should use .gemini/skills/ pattern."""
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")

        # Both should use .gemini/skills/prd/SKILL.md pattern
        assert any(".gemini" in c.parts and "skills" in c.parts for c in candidates)

    def test_install_target_matches_candidates(self, fake_repo: Path, fake_home: Path) -> None:
        """The install target should be one of the candidate paths."""
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")
            target = _skill_install_target("gemini", "prd")

        assert target in candidates
