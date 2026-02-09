"""Unit tests for gralph.git_ops against real temporary git repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gralph import git_ops


# ── helpers ──────────────────────────────────────────────────────────


def _commit_file(repo: Path, name: str, content: str, msg: str) -> None:
    (repo / name).write_text(content)
    subprocess.run(["git", "add", name], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, capture_output=True, check=True)


# ── TestBasicBranchOps ───────────────────────────────────────────────


class TestBasicBranchOps:
    def test_current_branch(self, git_repo: Path) -> None:
        # Default branch from `git init` may be "main" or "master" depending on config.
        # Our fixture doesn't force a name, but we can just check it returns something.
        branch = git_ops.current_branch(cwd=git_repo)
        assert branch  # non-empty string

    def test_create_branch_and_exists(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        assert git_ops.create_branch("feature-x", base, cwd=git_repo)
        assert git_ops.branch_exists("feature-x", cwd=git_repo)

    def test_branch_exists_false(self, git_repo: Path) -> None:
        assert not git_ops.branch_exists("nonexistent-branch", cwd=git_repo)

    def test_checkout_switches(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("switch-test", base, cwd=git_repo)
        # create_branch does checkout -b, so we're already on switch-test
        git_ops.checkout(base, cwd=git_repo)
        assert git_ops.current_branch(cwd=git_repo) == base

        assert git_ops.checkout("switch-test", cwd=git_repo)
        assert git_ops.current_branch(cwd=git_repo) == "switch-test"

    def test_delete_branch(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("to-delete", base, cwd=git_repo)
        git_ops.checkout(base, cwd=git_repo)
        git_ops.delete_branch("to-delete", cwd=git_repo)
        assert not git_ops.branch_exists("to-delete", cwd=git_repo)

    def test_delete_branch_force(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("force-del", base, cwd=git_repo)
        _commit_file(git_repo, "unmerged.txt", "data", "unmerged commit")
        git_ops.checkout(base, cwd=git_repo)
        # -d would fail because commits are not merged; -D (force) works
        git_ops.delete_branch("force-del", force=True, cwd=git_repo)
        assert not git_ops.branch_exists("force-del", cwd=git_repo)


# ── TestEnsureRunBranch ──────────────────────────────────────────────


class TestEnsureRunBranch:
    def test_creates_new_branch(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        result = git_ops.ensure_run_branch("run-new", base, cwd=git_repo)
        assert result == "run-new"
        assert git_ops.current_branch(cwd=git_repo) == "run-new"

    def test_switches_to_existing(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("run-existing", base, cwd=git_repo)
        git_ops.checkout(base, cwd=git_repo)

        result = git_ops.ensure_run_branch("run-existing", base, cwd=git_repo)
        assert result == "run-existing"
        assert git_ops.current_branch(cwd=git_repo) == "run-existing"

    def test_empty_name_returns_base(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        result = git_ops.ensure_run_branch("", base, cwd=git_repo)
        assert result == base

    def test_raises_on_checkout_failure(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        # Create the branch so ensure_run_branch takes the "exists" path
        subprocess.run(
            ["git", "branch", "bad-branch", base], cwd=git_repo, capture_output=True,
        )
        from unittest.mock import patch

        with patch.object(git_ops, "checkout", return_value=False):
            with pytest.raises(RuntimeError, match="Failed to checkout"):
                git_ops.ensure_run_branch("bad-branch", base, cwd=git_repo)


# ── TestWorktreeOperations ───────────────────────────────────────────


class TestWorktreeOperations:
    def test_create_agent_worktree_creates_dir_and_branch(self, git_repo: Path) -> None:
        wt_base = git_repo / "worktrees"
        wt_base.mkdir()
        base = git_ops.current_branch(cwd=git_repo)

        wt_dir, branch = git_ops.create_agent_worktree(
            "TASK-1", 1,
            base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )
        assert wt_dir.is_dir()
        assert git_ops.branch_exists(branch, cwd=git_repo)

    def test_create_agent_worktree_naming_convention(self, git_repo: Path) -> None:
        wt_base = git_repo / "worktrees"
        wt_base.mkdir()
        base = git_ops.current_branch(cwd=git_repo)

        _, branch = git_ops.create_agent_worktree(
            "TASK-1", 3,
            base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )
        assert branch.startswith("gralph/agent-3-")

    def test_create_agent_worktree_replaces_existing(self, git_repo: Path) -> None:
        wt_base = git_repo / "worktrees"
        wt_base.mkdir()
        base = git_ops.current_branch(cwd=git_repo)

        wt1, branch1 = git_ops.create_agent_worktree(
            "TASK-1", 1,
            base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )
        # Create again with same agent_num but different task — should replace
        wt2, branch2 = git_ops.create_agent_worktree(
            "TASK-2", 1,
            base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )
        assert wt2.is_dir()
        # worktree dir is the same (agent-1) but branch differs
        assert wt1 == wt2
        assert branch1 != branch2

    def test_create_agent_worktree_bad_base_raises(self, git_repo: Path) -> None:
        wt_base = git_repo / "worktrees"
        wt_base.mkdir()

        with pytest.raises(RuntimeError, match="Failed to create branch"):
            git_ops.create_agent_worktree(
                "TASK-1", 1,
                base_branch="nonexistent-base", worktree_base=wt_base,
                original_dir=git_repo,
            )

    def test_worktree_add_remove(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        branch = "wt-test-branch"
        git_ops.create_branch(branch, base, cwd=git_repo)
        git_ops.checkout(base, cwd=git_repo)

        wt_dir = git_repo / "wt-test"
        assert git_ops.worktree_add(wt_dir, branch, cwd=git_repo)
        assert wt_dir.is_dir()

        assert git_ops.worktree_remove(wt_dir, cwd=git_repo)


# ── TestWorktreeCleanup ──────────────────────────────────────────────


class TestWorktreeCleanup:
    def test_cleanup_removes_dir(self, git_repo: Path) -> None:
        wt_base = git_repo / "worktrees"
        wt_base.mkdir()
        base = git_ops.current_branch(cwd=git_repo)

        wt_dir, branch = git_ops.create_agent_worktree(
            "cleanup-task", 1,
            base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )
        assert wt_dir.is_dir()

        git_ops.cleanup_agent_worktree(
            wt_dir, branch, original_dir=git_repo,
        )
        assert not wt_dir.is_dir()

    def test_cleanup_dirty_worktree_logs(self, git_repo: Path, tmp_path: Path) -> None:
        wt_base = git_repo / "worktrees"
        wt_base.mkdir()
        base = git_ops.current_branch(cwd=git_repo)

        wt_dir, branch = git_ops.create_agent_worktree(
            "dirty-task", 1,
            base_branch=base, worktree_base=wt_base, original_dir=git_repo,
        )
        # Make worktree dirty
        (wt_dir / "dirty.txt").write_text("uncommitted")

        log_file = tmp_path / "cleanup.log"
        git_ops.cleanup_agent_worktree(
            wt_dir, branch, original_dir=git_repo, log_file=log_file,
        )
        assert not wt_dir.is_dir()
        assert "WARN" in log_file.read_text()

    def test_cleanup_nonexistent_dir(self, git_repo: Path) -> None:
        # Should not raise even if directory doesn't exist
        git_ops.cleanup_agent_worktree(
            git_repo / "does-not-exist",
            "fake-branch",
            original_dir=git_repo,
        )


# ── TestMergeOperations ──────────────────────────────────────────────


class TestMergeOperations:
    def test_merge_clean(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("merge-src", base, cwd=git_repo)
        _commit_file(git_repo, "new.txt", "content", "add new file")
        git_ops.checkout(base, cwd=git_repo)

        assert git_ops.merge_no_edit("merge-src", cwd=git_repo)

    def test_merge_conflict_returns_false(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)

        # Create conflicting changes on two branches
        git_ops.create_branch("conflict-src", base, cwd=git_repo)
        _commit_file(git_repo, "conflict.txt", "branch version", "branch change")
        git_ops.checkout(base, cwd=git_repo)
        _commit_file(git_repo, "conflict.txt", "main version", "main change")

        assert not git_ops.merge_no_edit("conflict-src", cwd=git_repo)

    def test_merge_abort_cleans_state(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)

        git_ops.create_branch("abort-src", base, cwd=git_repo)
        _commit_file(git_repo, "conflict.txt", "branch version", "branch change")
        git_ops.checkout(base, cwd=git_repo)
        _commit_file(git_repo, "conflict.txt", "main version", "main change")

        git_ops.merge_no_edit("abort-src", cwd=git_repo)
        git_ops.merge_abort(cwd=git_repo)
        # After abort, MERGE_HEAD should be gone
        git_dir = git_repo / ".git"
        assert not (git_dir / "MERGE_HEAD").exists()

    def test_conflicted_files_during_conflict(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)

        git_ops.create_branch("cf-src", base, cwd=git_repo)
        _commit_file(git_repo, "a.txt", "branch-a", "branch a")
        git_ops.checkout(base, cwd=git_repo)
        _commit_file(git_repo, "a.txt", "main-a", "main a")

        git_ops.merge_no_edit("cf-src", cwd=git_repo)
        files = git_ops.conflicted_files(cwd=git_repo)
        assert "a.txt" in files

        git_ops.merge_abort(cwd=git_repo)

    def test_conflicted_files_when_clean(self, git_repo: Path) -> None:
        assert git_ops.conflicted_files(cwd=git_repo) == []


# ── TestCleanGitState ────────────────────────────────────────────────


class TestCleanGitState:
    def test_aborts_interrupted_merge(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)

        git_ops.create_branch("int-merge", base, cwd=git_repo)
        _commit_file(git_repo, "x.txt", "branch", "branch commit")
        git_ops.checkout(base, cwd=git_repo)
        _commit_file(git_repo, "x.txt", "main", "main commit")

        git_ops.merge_no_edit("int-merge", cwd=git_repo)
        git_dir = git_repo / ".git"
        assert (git_dir / "MERGE_HEAD").exists()

        git_ops.ensure_clean_git_state(cwd=git_repo)
        assert not (git_dir / "MERGE_HEAD").exists()

    def test_noop_on_clean_repo(self, git_repo: Path) -> None:
        # Should not raise
        git_ops.ensure_clean_git_state(cwd=git_repo)


# ── TestStaleAgentBranchCleanup ──────────────────────────────────────


class TestStaleAgentBranchCleanup:
    def test_removes_orphan_branches(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        # Create agent-style branches (no associated worktree)
        subprocess.run(
            ["git", "branch", "gralph/agent-1-task-a", base],
            cwd=git_repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "branch", "gralph/agent-2-task-b", base],
            cwd=git_repo, capture_output=True, check=True,
        )
        assert git_ops.branch_exists("gralph/agent-1-task-a", cwd=git_repo)

        git_ops.cleanup_stale_agent_branches(cwd=git_repo)

        assert not git_ops.branch_exists("gralph/agent-1-task-a", cwd=git_repo)
        assert not git_ops.branch_exists("gralph/agent-2-task-b", cwd=git_repo)

    def test_no_error_without_agent_branches(self, git_repo: Path) -> None:
        git_ops.cleanup_stale_agent_branches(cwd=git_repo)


# ── TestGitUtilities ─────────────────────────────────────────────────


class TestGitUtilities:
    def test_has_dirty_worktree(self, git_repo: Path) -> None:
        assert not git_ops.has_dirty_worktree(cwd=git_repo)
        (git_repo / "dirty.txt").write_text("dirty")
        assert git_ops.has_dirty_worktree(cwd=git_repo)

    def test_add_and_commit(self, git_repo: Path) -> None:
        (git_repo / "new.txt").write_text("hello")
        assert git_ops.add_and_commit("add new file", cwd=git_repo)
        assert not git_ops.has_dirty_worktree(cwd=git_repo)

    def test_commit_count(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("count-branch", base, cwd=git_repo)
        _commit_file(git_repo, "c1.txt", "1", "first")
        _commit_file(git_repo, "c2.txt", "2", "second")
        assert git_ops.commit_count(base, cwd=git_repo) == 2

    def test_changed_files(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("changes-branch", base, cwd=git_repo)
        _commit_file(git_repo, "changed.txt", "data", "change")
        files = git_ops.changed_files(base, cwd=git_repo)
        assert "changed.txt" in files

    def test_diff_stat(self, git_repo: Path) -> None:
        base = git_ops.current_branch(cwd=git_repo)
        git_ops.create_branch("stat-branch", base, cwd=git_repo)
        _commit_file(git_repo, "stat.txt", "data", "stat commit")
        git_ops.checkout(base, cwd=git_repo)

        stat = git_ops.diff_stat(base, "stat-branch", cwd=git_repo)
        assert "stat.txt" in stat

    def test_stash_push_pop(self, git_repo: Path) -> None:
        (git_repo / "stash.txt").write_text("stash me")
        subprocess.run(["git", "add", "stash.txt"], cwd=git_repo, capture_output=True)
        assert git_ops.has_dirty_worktree(cwd=git_repo)

        assert git_ops.stash_push(cwd=git_repo)
        assert not git_ops.has_dirty_worktree(cwd=git_repo)

        assert git_ops.stash_pop(cwd=git_repo)
        assert git_ops.has_dirty_worktree(cwd=git_repo)
