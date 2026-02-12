"""Git operations: worktrees, branches, merges."""

from __future__ import annotations

import subprocess
from pathlib import Path

from gralph import log
from gralph.io_utils import open_text
from gralph.prd import slugify


def _git(*args: str, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a git command, suppressing stderr noise."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=check,
    )


def current_branch(cwd: Path | None = None) -> str:
    r = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return r.stdout.strip() if r.returncode == 0 else "main"


def branch_exists(name: str, cwd: Path | None = None) -> bool:
    r = _git("show-ref", "--verify", "--quiet", f"refs/heads/{name}", cwd=cwd)
    return r.returncode == 0


def checkout(branch: str, cwd: Path | None = None) -> bool:
    r = _git("checkout", branch, cwd=cwd)
    return r.returncode == 0


def create_branch(name: str, base: str, cwd: Path | None = None) -> bool:
    r = _git("checkout", "-b", name, base, cwd=cwd)
    return r.returncode == 0


def pull(branch: str, cwd: Path | None = None) -> bool:
    r = _git("pull", "origin", branch, cwd=cwd)
    return r.returncode == 0


def push(branch: str, cwd: Path | None = None) -> bool:
    r = _git("push", "-u", "origin", branch, cwd=cwd)
    return r.returncode == 0


def merge_no_edit(branch: str, cwd: Path | None = None) -> bool:
    r = _git("merge", "--no-edit", branch, cwd=cwd)
    return r.returncode == 0


def merge_no_edit_result(branch: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run merge and return the raw completed-process for error inspection."""
    return _git("merge", "--no-edit", branch, cwd=cwd)


def merge_abort(cwd: Path | None = None) -> None:
    _git("merge", "--abort", cwd=cwd)


def conflicted_files(cwd: Path | None = None) -> list[str]:
    r = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [f.strip() for f in r.stdout.strip().splitlines() if f.strip()]


def commit_count(base: str, cwd: Path | None = None) -> int:
    r = _git("rev-list", "--count", f"{base}..HEAD", cwd=cwd)
    if r.returncode != 0:
        return 0
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def changed_files(base: str, cwd: Path | None = None) -> list[str]:
    r = _git("diff", "--name-only", f"{base}..HEAD", cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [f.strip() for f in r.stdout.strip().splitlines() if f.strip()]


def diff_stat(base: str, head: str, cwd: Path | None = None) -> str:
    r = _git("diff", "--stat", f"{base}..{head}", cwd=cwd)
    return r.stdout.strip() if r.returncode == 0 else ""


def has_dirty_worktree(cwd: Path | None = None) -> bool:
    r = _git("status", "--porcelain", cwd=cwd)
    return bool(r.stdout.strip())


def dirty_worktree_entries(cwd: Path | None = None) -> list[str]:
    """Return concise dirty entries from `git status --porcelain`."""
    r = _git("status", "--porcelain", cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    entries: list[str] = []
    for line in r.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            entries.append(stripped)
    return entries


def stash_push(cwd: Path | None = None) -> bool:
    r = _git("stash", "push", "-m", "gralph-autostash", cwd=cwd)
    return r.returncode == 0


def stash_pop(cwd: Path | None = None) -> bool:
    r = _git("stash", "pop", cwd=cwd)
    return r.returncode == 0


def add_and_commit(message: str, cwd: Path | None = None) -> bool:
    _git("add", ".", cwd=cwd)
    r = _git("commit", "-m", message, cwd=cwd)
    return r.returncode == 0


def delete_branch(name: str, force: bool = False, cwd: Path | None = None) -> None:
    flag = "-D" if force else "-d"
    _git("branch", flag, name, cwd=cwd)


# ── Worktree management ─────────────────────────────────────────────

def worktree_prune(cwd: Path | None = None) -> None:
    _git("worktree", "prune", cwd=cwd)


def worktree_add(worktree_dir: Path, branch: str, cwd: Path | None = None) -> bool:
    r = _git("worktree", "add", "--force", str(worktree_dir), branch, cwd=cwd)
    return r.returncode == 0


def worktree_remove(worktree_dir: Path, cwd: Path | None = None) -> bool:
    r = _git("worktree", "remove", "--force", str(worktree_dir), cwd=cwd)
    return r.returncode == 0


def create_agent_worktree(
    task_id: str,
    agent_num: int,
    *,
    base_branch: str,
    worktree_base: Path,
    original_dir: Path,
) -> tuple[Path, str]:
    """Create an isolated worktree for a parallel agent.

    Returns ``(worktree_dir, branch_name)``.
    Raises ``RuntimeError`` on failure.
    """
    branch_name = f"gralph/agent-{agent_num}-{slugify(task_id)}"
    worktree_dir = worktree_base / f"agent-{agent_num}"

    # Prune stale worktrees
    worktree_prune(cwd=original_dir)

    # Delete branch if it exists
    delete_branch(branch_name, force=True, cwd=original_dir)

    # Create branch from base
    r = _git("branch", branch_name, base_branch, cwd=original_dir)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create branch {branch_name} from {base_branch}: {r.stderr}")

    # Remove existing worktree dir
    import shutil

    if worktree_dir.exists():
        shutil.rmtree(worktree_dir, ignore_errors=True)

    # Create worktree
    if not worktree_add(worktree_dir, branch_name, cwd=original_dir):
        raise RuntimeError(f"Failed to create worktree at {worktree_dir}")

    return worktree_dir, branch_name


def cleanup_agent_worktree(
    worktree_dir: Path,
    branch_name: str,
    *,
    original_dir: Path,
    log_file: Path | None = None,
) -> None:
    """Remove a worktree (preserving dirty ones)."""
    import shutil

    if worktree_dir.exists():
        if has_dirty_worktree(cwd=worktree_dir):
            if log_file:
                with open_text(log_file, "a") as f:
                    f.write(f"[WARN] Worktree dirty, forcing cleanup: {worktree_dir}\n")

    # Try to remove
    shutil.rmtree(worktree_dir, ignore_errors=True)
    worktree_remove(worktree_dir, cwd=original_dir)


# ── Clean git state ──────────────────────────────────────────────────

def ensure_clean_git_state(cwd: Path | None = None) -> None:
    """Abort any interrupted merge/rebase/cherry-pick."""
    git_dir_r = _git("rev-parse", "--git-dir", cwd=cwd)
    if git_dir_r.returncode != 0:
        return
    git_dir = Path(git_dir_r.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (cwd or Path.cwd()) / git_dir

    if (git_dir / "MERGE_HEAD").exists():
        log.warn("Detected interrupted git merge. Aborting…")
        merge_abort(cwd=cwd)
    if (git_dir / "REBASE_HEAD").exists():
        log.warn("Detected interrupted git rebase. Aborting…")
        _git("rebase", "--abort", cwd=cwd)
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        log.warn("Detected interrupted git cherry-pick. Aborting…")
        _git("cherry-pick", "--abort", cwd=cwd)


def cleanup_stale_agent_branches(cwd: Path | None = None) -> None:
    """Prune stale worktrees and delete orphan ``gralph/agent-*`` branches."""
    worktree_prune(cwd=cwd)

    r = _git("branch", "--list", "gralph/agent-*", cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return

    for line in r.stdout.strip().splitlines():
        branch = line.lstrip("*+ ").strip()
        if not branch:
            continue
        # Check if checked out in a worktree
        wt = _git("worktree", "list", cwd=cwd)
        if f"[{branch}]" in wt.stdout:
            for wt_line in wt.stdout.splitlines():
                if f"[{branch}]" in wt_line:
                    wt_path = wt_line.split()[0]
                    log.debug(f"Removing stale worktree for {branch} at {wt_path}")
                    worktree_remove(Path(wt_path), cwd=cwd)
                    break
        log.debug(f"Cleaning up stale branch: {branch}")
        delete_branch(branch, force=True, cwd=cwd)


# ── Run branch ───────────────────────────────────────────────────────

def ensure_run_branch(branch_name: str, base_branch: str, cwd: Path | None = None) -> str:
    """Switch to (or create) *branch_name*. Returns the effective base branch."""
    if not branch_name:
        return base_branch

    base = base_branch or current_branch(cwd=cwd)

    if branch_exists(branch_name, cwd=cwd):
        log.info(f"Switching to run branch: {branch_name}")
        if not checkout(branch_name, cwd=cwd):
            raise RuntimeError(f"Failed to checkout run branch: {branch_name}")
    else:
        log.info(f"Creating run branch: {branch_name} from {base}")
        checkout(base, cwd=cwd)
        pull(base, cwd=cwd)
        if not create_branch(branch_name, base, cwd=cwd):
            raise RuntimeError(f"Failed to create run branch: {branch_name}")

    return branch_name


# ── PR creation ──────────────────────────────────────────────────────

def create_pull_request(
    branch: str,
    base: str,
    title: str,
    body: str = "Automated PR created by GRALPH",
    draft: bool = False,
) -> str | None:
    """Create a GitHub PR using ``gh`` CLI. Returns PR URL or None."""
    import shutil

    if not shutil.which("gh"):
        log.warn("gh CLI not found — cannot create PR")
        return None

    push(branch)

    cmd = ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body]
    if draft:
        cmd.append("--draft")

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.warn(f"Failed to create PR for {branch}: {r.stderr.strip()}")
        return None

    url = r.stdout.strip()
    log.success(f"PR created: {url}")
    return url
