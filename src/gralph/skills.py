"""Skills initialization and checking for AI engines."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from gralph import log
from gralph.config import Config, resolve_repo_root

REQUIRED_SKILLS = [
    "prd",
    "ralph",
    "task-metadata",
    "dag-planner",
    "parallel-safe-implementation",
    "merge-integrator",
    "semantic-reviewer",
]


class MissingSkillsError(RuntimeError):
    """Raised when required skills are missing for the selected engine."""


def _skill_candidates(engine: str, skill: str) -> list[Path]:
    """Return candidate project paths where a skill should be installed."""
    repo_root = resolve_repo_root()

    match engine:
        case "claude":
            return [repo_root / f".claude/skills/{skill}/SKILL.md"]
        case "codex":
            return [repo_root / f".codex/skills/{skill}/SKILL.md"]
        case "opencode":
            return [repo_root / f".opencode/skill/{skill}/SKILL.md"]
        case "cursor":
            return [repo_root / f".cursor/rules/{skill}.mdc"]
        case "gemini":
            return [repo_root / f".gemini/skills/{skill}/SKILL.md"]
        case _:
            return []


def _skill_install_target(engine: str, skill: str) -> Path | None:
    """Return the single install location for the given engine and skill."""
    candidates = _skill_candidates(engine, skill)
    if not candidates:
        return None
    target = candidates[0]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return target


def skill_exists(engine: str, skill: str) -> bool:
    return any(c.is_file() for c in _skill_candidates(engine, skill))


def find_skill_file(engine: str, skill: str) -> Path | None:
    """Return the installed path for ``skill`` in ``engine`` context, if any."""
    for candidate in _skill_candidates(engine, skill):
        if candidate.is_file():
            return candidate
    return None


def _download_skill(skill: str, base_url: str) -> Path | None:
    """Download skill content to a temp file. Returns path or None."""
    url = f"{base_url.rstrip('/')}/{skill}/SKILL.md"
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as temp_file:
        tmp = Path(temp_file.name)

    try:
        with urlopen(url, timeout=15) as resp:
            tmp.write_bytes(resp.read())
        return tmp
    except (URLError, OSError):
        return None


def install_skill(engine: str, skill: str, base_url: str) -> bool:
    """Install a single skill if missing."""
    if skill_exists(engine, skill):
        log.info(f"Skill '{skill}' already installed for {engine}, skipping")
        return True

    target = _skill_install_target(engine, skill)
    if target is None:
        log.warn(f"No writable install path for {engine} skill '{skill}'")
        return False

    tmp = _download_skill(skill, base_url)
    if tmp is None:
        log.error(f"Failed to download skill '{skill}' from {base_url}")
        return False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(target))
        log.success(f"Installed '{skill}' for {engine} at {target}")
        return True
    except OSError:
        log.error(f"Failed to install '{skill}' for {engine} at {target}")
        return False


def _missing_skills(engine: str) -> list[str]:
    """Return required skills that are currently missing."""
    return [skill for skill in REQUIRED_SKILLS if not skill_exists(engine, skill)]


def ensure_skills(cfg: Config, mode: str = "require") -> None:
    """Check/install all required skills for the configured engine.

    *mode* is ``"install"`` or ``"require"``.
    """
    engine = cfg.ai_engine
    if mode not in {"install", "require"}:
        raise ValueError(f"Unsupported ensure_skills mode: {mode}")

    missing_before = _missing_skills(engine)
    if mode == "install":
        if not missing_before:
            log.success(f"All skills already present for {engine}")
            return

        install_failures: list[str] = []
        for skill in missing_before:
            if not install_skill(engine, skill, cfg.skills_base_url):
                install_failures.append(skill)

        if install_failures:
            missing_joined = ", ".join(install_failures)
            raise MissingSkillsError(
                f"Failed to install required skills for {engine}: {missing_joined}"
            )
        return

    missing_after = _missing_skills(engine)
    if missing_after:
        missing_joined = ", ".join(missing_after)
        raise MissingSkillsError(
            f"Missing required skills for {engine}: {missing_joined}. Run 'gralph --init'."
        )
