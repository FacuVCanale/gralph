"""Self-update strategy for GRALPH."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gralph import log


def _find_install_dir() -> Path | None:
    """Locate the gralph clone directory (``~/.gralph``)."""
    home_clone = Path.home() / ".gralph"
    if (home_clone / ".git").is_dir():
        return home_clone

    # Also check if we're running from a git repo directly
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent  # src/gralph -> src -> repo root
    if (repo_root / ".git").is_dir():
        return repo_root

    return None


def self_update() -> None:
    """Update gralph to the latest version.

    Standard install flow (via ``install.sh`` / ``install.ps1``):
    1. ``git pull`` in the local clone (``~/.gralph``)
    2. ``pipx install --force ~/.gralph`` to rebuild the CLI
    """
    install_dir = _find_install_dir()

    if install_dir is None:
        log.info("Could not find gralph installation directory. Update manually:")
        log.console.print("  pipx upgrade gralph")
        log.console.print("  # or: pip install --upgrade gralph")
        return

    # 1. Git pull
    log.info(f"Pulling latest from {install_dir}...")
    before = subprocess.run(
        ["git", "-C", str(install_dir), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    pull_result = subprocess.run(
        ["git", "-C", str(install_dir), "pull", "--ff-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pull_result.returncode != 0:
        details = (pull_result.stderr or pull_result.stdout or "").strip()
        log.warn("Fast-forward update failed. Skipping destructive reset.")
        if details:
            log.console.print(f"[dim]{details.splitlines()[0]}[/dim]")
        log.console.print(
            "  Resolve local/diverged changes manually, then rerun `gralph --update`."
        )
        return

    after = subprocess.run(
        ["git", "-C", str(install_dir), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    if before == after:
        log.info(f"Already up to date ({after})")
    else:
        log.success(f"Updated {before} -> {after}")

    # 2. Reinstall via pipx
    if shutil.which("pipx"):
        log.info("Reinstalling via pipx...")
        reinstall_result = subprocess.run(
            ["pipx", "install", str(install_dir), "--force"],
            capture_output=True,
            text=True,
            check=False,
        )
        if reinstall_result.returncode == 0:
            log.success("Reinstalled gralph CLI")
        else:
            log.warn(f"pipx install failed: {reinstall_result.stderr.strip()}")
            log.console.print(f"  Try manually: pipx install {install_dir} --force")
    else:
        log.info("pipx not found - skipping reinstall.")
        log.console.print(f"  Run manually: pip install {install_dir}")
