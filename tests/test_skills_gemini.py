"""Tests for Gemini skill path behavior in strict project-only mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gralph.skills import (
    _skill_candidates,
    _skill_install_target,
    find_skill_file,
    skill_exists,
)


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    return tmp_path / "repo"


@pytest.fixture()
def fake_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _patch_roots(fake_repo: Path, fake_home: Path):
    class _Ctx:
        def __init__(self, repo: Path, home: Path):
            self._repo = repo
            self._home = home
            self._patchers: list = []

        def __enter__(self):
            p1 = patch("gralph.skills.resolve_repo_root", return_value=self._repo)
            p2 = patch("gralph.skills.Path.home", return_value=self._home)
            self._patchers = [p1, p2]
            for patcher in self._patchers:
                patcher.start()
            return self

        def __exit__(self, *args):
            for patcher in self._patchers:
                patcher.stop()

    return _Ctx(fake_repo, fake_home)


class TestGeminiSkillCandidates:
    def test_returns_single_project_candidate(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")

        assert len(candidates) == 1
        assert candidates[0] == fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"

    def test_unknown_engine_returns_empty(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            assert _skill_candidates("unknown-engine", "prd") == []


class TestGeminiSkillInstallTarget:
    def test_returns_project_path_when_writable(self, fake_repo: Path, fake_home: Path) -> None:
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            target = _skill_install_target("gemini", "prd")

        assert target == fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"

    def test_creates_parent_directories(self, fake_repo: Path, fake_home: Path) -> None:
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            target = _skill_install_target("gemini", "ralph")

        assert target is not None
        assert target.parent.is_dir()

    def test_returns_none_for_unknown_engine(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            assert _skill_install_target("unknown-engine", "prd") is None


class TestGeminiSkillExists:
    def test_false_when_no_file(self, fake_repo: Path, fake_home: Path) -> None:
        with _patch_roots(fake_repo, fake_home):
            assert skill_exists("gemini", "prd") is False

    def test_true_when_project_file_exists(self, fake_repo: Path, fake_home: Path) -> None:
        skill_path = fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("# PRD skill")

        with _patch_roots(fake_repo, fake_home):
            assert skill_exists("gemini", "prd") is True

    def test_false_when_only_user_file_exists(self, fake_repo: Path, fake_home: Path) -> None:
        user_skill = fake_home / ".gemini" / "skills" / "prd" / "SKILL.md"
        user_skill.parent.mkdir(parents=True, exist_ok=True)
        user_skill.write_text("# user skill")

        with _patch_roots(fake_repo, fake_home):
            assert skill_exists("gemini", "prd") is False


class TestFindSkillFileGemini:
    def test_finds_project_prd_skill(self, fake_repo: Path, fake_home: Path) -> None:
        project_skill = fake_repo / ".gemini" / "skills" / "prd" / "SKILL.md"
        project_skill.parent.mkdir(parents=True, exist_ok=True)
        project_skill.write_text("# project")

        with _patch_roots(fake_repo, fake_home):
            result = find_skill_file("gemini", "prd")

        assert result == project_skill

    def test_returns_none_when_missing(self, fake_repo: Path, fake_home: Path) -> None:
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            result = find_skill_file("gemini", "prd")

        assert result is None


class TestGeminiSkillPathConsistency:
    def test_install_target_matches_candidates(self, fake_repo: Path, fake_home: Path) -> None:
        fake_repo.mkdir(parents=True, exist_ok=True)
        with _patch_roots(fake_repo, fake_home):
            candidates = _skill_candidates("gemini", "prd")
            target = _skill_install_target("gemini", "prd")

        assert target in candidates
