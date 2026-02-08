"""Skills initialization and checking for AI engines."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

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


def _skill_candidates(engine: str, skill: str) -> list[Path]:
    """Return candidate paths where a skill might be installed."""
    repo_root = resolve_repo_root()
    home = Path.home()

    match engine:
        case "claude":
            return [
                repo_root / f".claude/skills/{skill}/SKILL.md",
                home / f".claude/skills/{skill}/SKILL.md",
            ]
        case "codex":
            return [
                repo_root / f".codex/skills/{skill}/SKILL.md",
                home / f".codex/skills/{skill}/SKILL.md",
            ]
        case "opencode":
            return [
                repo_root / f".opencode/skill/{skill}/SKILL.md",
                home / f".config/opencode/skill/{skill}/SKILL.md",
            ]
        case "cursor":
            return [
                repo_root / f".cursor/rules/{skill}.mdc",
                repo_root / f".cursor/commands/{skill}.md",
            ]
        case _:
            return []


def _skill_install_target(engine: str, skill: str) -> Path | None:
    """Pick the best install location (prefer project, fallback user)."""
    repo_root = resolve_repo_root()
    home = Path.home()

    project: Path | None = None
    user: Path | None = None

    match engine:
        case "claude":
            project = repo_root / f".claude/skills/{skill}/SKILL.md"
            user = home / f".claude/skills/{skill}/SKILL.md"
        case "codex":
            project = repo_root / f".codex/skills/{skill}/SKILL.md"
            user = home / f".codex/skills/{skill}/SKILL.md"
        case "opencode":
            project = repo_root / f".opencode/skill/{skill}/SKILL.md"
            user = home / f".config/opencode/skill/{skill}/SKILL.md"
        case "cursor":
            project = repo_root / f".cursor/rules/{skill}.mdc"

    for candidate in [project, user]:
        if candidate is not None:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue

    return None


def skill_exists(engine: str, skill: str) -> bool:
    return any(c.is_file() for c in _skill_candidates(engine, skill))


def _download_skill(skill: str, base_url: str) -> Path | None:
    """Download skill content to a temp file. Returns path or None."""
    url = f"{base_url.rstrip('/')}/{skill}/SKILL.md"
    tmp = Path(tempfile.mktemp(suffix=".md"))

    try:
        with urlopen(url, timeout=15) as resp:
            tmp.write_bytes(resp.read())
        return tmp
    except (URLError, OSError):
        # Fallback to local
        local = resolve_repo_root() / f"skills/{skill}/SKILL.md"
        if local.is_file():
            shutil.copy2(local, tmp)
            log.warn(f"Falling back to local skill source for '{skill}'")
            return tmp
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


def ensure_skills(cfg: Config, mode: str = "warn") -> None:
    """Check/install all required skills for the configured engine.

    *mode* is ``"install"`` or ``"warn"``.
    """
    engine = cfg.ai_engine
    if engine == "cursor":
        log.warn("Cursor skills are not officially supported; installing as rules is best-effort.")

    missing = False
    for skill in REQUIRED_SKILLS:
        if skill_exists(engine, skill):
            log.info(f"Skill '{skill}' found for {engine}")
            continue
        missing = True
        if mode == "install":
            install_skill(engine, skill, cfg.skills_base_url)
        else:
            log.warn(f"Missing skill '{skill}' for {engine} (run --init to install)")

    if mode == "install" and not missing:
        log.success(f"All skills already present for {engine}")
