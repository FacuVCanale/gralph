"""Self-update strategy for GRALPH."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gralph import log


def self_update() -> None:
    """Update gralph to the latest version.

    Detects the installation method and updates accordingly:
    - pipx: ``pipx upgrade gralph``
    - git clone: ``git pull``
    - pip: prints instructions
    """
    # 1. Try pipx
    if shutil.which("pipx"):
        log.info("Detected pipx — running pipx upgrade gralph…")
        r = subprocess.run(
            ["pipx", "upgrade", "gralph"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            log.success(f"Updated via pipx: {r.stdout.strip()}")
            return
        # pipx might fail if not installed via pipx — fall through
        log.debug(f"pipx upgrade failed: {r.stderr.strip()}")

    # 2. Try git (legacy install)
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent  # src/gralph -> src -> repo root
    git_dir = repo_root / ".git"

    if git_dir.is_dir():
        log.info("Detected git installation — pulling latest…")
        before = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        r = subprocess.run(
            ["git", "-C", str(repo_root), "pull", "--ff-only"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            log.warn("Fast-forward failed, resetting to origin/main…")
            subprocess.run(
                ["git", "-C", str(repo_root), "fetch", "origin"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_root), "reset", "--hard", "origin/main"],
                capture_output=True,
            )

        after = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        if before == after:
            log.success(f"Already up to date ({after})")
        else:
            log.success(f"Updated {before} → {after}")
        return

    # 3. Fallback: print instructions
    log.info("Could not detect installation method. Update manually:")
    log.console.print("  pipx upgrade gralph")
    log.console.print("  # or: pip install --upgrade gralph")
