"""Configuration defaults, env vars, and runtime options for GRALPH."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


VERSION = "4.0.0"

DEFAULT_SKILLS_URL = "https://raw.githubusercontent.com/frizynn/central-ralph/main/skills"


@dataclass
class Config:
    """Runtime configuration — mirrors the flags of the shell scripts."""

    # AI engine
    ai_engine: str = "claude"
    opencode_model: str = "opencode/minimax-m2.1-free"

    # Workflow
    skip_tests: bool = False
    skip_lint: bool = False

    # Execution
    parallel: bool = True
    sequential: bool = False
    max_parallel: int = 3
    max_iterations: int = 0
    max_retries: int = 3
    retry_delay: int = 5
    external_fail_timeout: int = 300
    stalled_timeout: int = 600
    dry_run: bool = False

    # Git
    branch_per_task: bool = False
    base_branch: str = ""
    create_pr: bool = False
    draft_pr: bool = False
    run_branch: str = ""

    # PRD
    prd_file: str = "PRD.md"
    prd_id: str = ""
    prd_run_dir: str = ""
    resume_prd_id: str = ""

    # Skills
    skills_init: bool = False
    skills_base_url: str = ""

    # Misc
    verbose: bool = False

    # Derived / runtime state (not user-set)
    artifacts_dir: str = ""
    original_dir: str = ""
    worktree_base: str = ""

    def __post_init__(self) -> None:
        if not self.skills_base_url:
            self.skills_base_url = (
                os.environ.get("GRALPH_SKILLS_BASE_URL")
                or os.environ.get("RALPH_SKILLS_BASE_URL")
                or DEFAULT_SKILLS_URL
            )
        if self.sequential:
            self.parallel = False
            self.max_parallel = 1


def resolve_repo_root() -> Path:
    """Return the git repository root, falling back to cwd."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")
