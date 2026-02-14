"""Tests for skill download URL handling."""

from __future__ import annotations

from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from gralph.config import DEFAULT_SKILLS_URL
from gralph.skills import _download_skill


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def test_download_skill_uses_default_skills_url() -> None:
    """Downloader should build the expected URL from DEFAULT_SKILLS_URL."""
    payload = b"# task metadata skill\n"
    captured: dict[str, object] = {}
    expected_url = f"{DEFAULT_SKILLS_URL.rstrip('/')}/task-metadata/SKILL.md"

    def _fake_urlopen(url: str, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return _FakeResponse(payload)

    with patch("gralph.skills.urlopen", side_effect=_fake_urlopen):
        tmp = _download_skill("task-metadata", DEFAULT_SKILLS_URL)

    assert tmp is not None
    assert tmp.read_bytes() == payload
    assert captured["url"] == expected_url
    assert captured["timeout"] == 15

    tmp.unlink(missing_ok=True)


def test_download_skill_falls_back_to_local_when_remote_unavailable(tmp_path: Path) -> None:
    """When remote fetch fails, downloader should copy bundled local skill."""
    local_skill = tmp_path / "skills" / "task-metadata" / "SKILL.md"
    local_skill.parent.mkdir(parents=True, exist_ok=True)
    local_skill.write_text("# local fallback\n", encoding="utf-8")

    with patch("gralph.skills.urlopen", side_effect=URLError("network down")):
        with patch("gralph.skills.resolve_repo_root", return_value=tmp_path):
            tmp = _download_skill("task-metadata", DEFAULT_SKILLS_URL)

    assert tmp is not None
    assert tmp.read_text(encoding="utf-8") == "# local fallback\n"

    tmp.unlink(missing_ok=True)
