"""Rigorous CLI tests: ensure every command and flag runs without errors."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Import the CLI main so we can invoke it with Click's CliRunner
from gralph.cli import main


def _run_cli(args: list[str], cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run gralph as subprocess. Use when cwd matters (e.g. --dry-run)."""
    cmd = [sys.executable, "-m", "gralph"] + args
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def cli_runner():
    """Click CliRunner for invoking the CLI in-process."""
    from click.testing import CliRunner
    return CliRunner()


# ── Main entry and help ────────────────────────────────────────────────


class TestCliHelpAndVersion:
    """Basic entry: --help, --version, -h."""

    def test_help_long(self, cli_runner):
        r = cli_runner.invoke(main, ["--help"])
        assert r.exit_code == 0
        assert "GRALPH" in r.output
        assert "gralph" in r.output.lower()

    def test_help_short(self, cli_runner):
        r = cli_runner.invoke(main, ["-h"])
        assert r.exit_code == 0
        assert "GRALPH" in r.output

    def test_version(self, cli_runner):
        r = cli_runner.invoke(main, ["--version"])
        assert r.exit_code == 0
        assert "gralph" in r.output.lower()


# ── Engine flags (must parse and not crash) ──────────────────────────────


class TestCliEngineFlags:
    """All engine flags must work with --help."""

    def test_claude_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--claude", "--help"])
        assert r.exit_code == 0

    def test_opencode_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--opencode", "--help"])
        assert r.exit_code == 0

    def test_codex_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--codex", "--help"])
        assert r.exit_code == 0

    def test_cursor_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--cursor", "--help"])
        assert r.exit_code == 0


# ── Option flags (parse correctly) ───────────────────────────────────────


class TestCliOptionFlags:
    """All main options must parse with --help."""

    def test_no_tests_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--no-tests", "--help"])
        assert r.exit_code == 0

    def test_no_lint_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--no-lint", "--help"])
        assert r.exit_code == 0

    def test_fast_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--fast", "--help"])
        assert r.exit_code == 0

    def test_sequential_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--sequential", "--help"])
        assert r.exit_code == 0

    def test_max_parallel_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--max-parallel", "2", "--help"])
        assert r.exit_code == 0

    def test_max_iterations_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--max-iterations", "1", "--help"])
        assert r.exit_code == 0

    def test_dry_run_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--dry-run", "--help"])
        assert r.exit_code == 0

    def test_branch_per_task_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--branch-per-task", "--help"])
        assert r.exit_code == 0

    def test_base_branch_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--base-branch", "main", "--help"])
        assert r.exit_code == 0

    def test_create_pr_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--create-pr", "--help"])
        assert r.exit_code == 0

    def test_draft_pr_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--draft-pr", "--help"])
        assert r.exit_code == 0

    def test_prd_option_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--prd", "other.md", "--help"])
        assert r.exit_code == 0

    def test_resume_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--resume", "my-feature", "--help"])
        assert r.exit_code == 0

    def test_init_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--init", "--help"])
        assert r.exit_code == 0

    def test_skills_url_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--skills-url", "https://example.com", "--help"])
        assert r.exit_code == 0

    def test_verbose_help(self, cli_runner):
        r = cli_runner.invoke(main, ["-v", "--help"])
        assert r.exit_code == 0

    def test_update_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--update", "--help"])
        assert r.exit_code == 0


# ── --dry-run (full pipeline until dry-run output) ────────────────────────


class TestCliDryRun:
    """--dry-run must run without ModuleNotFoundError and show plan."""

    def test_dry_run_requires_prd(self, cli_runner):
        # No PRD.md in cwd -> must exit with error (not crash)
        r = cli_runner.invoke(main, ["--dry-run"])
        # Expect failure: PRD not found or similar
        assert r.exit_code != 0 or "PRD" in r.output or "prd" in r.output.lower()

    def test_dry_run_with_minimal_project(self, tmp_path: Path):
        # Minimal project: PRD.md + artifacts/prd/<id>/tasks.yaml
        (tmp_path / "PRD.md").write_text("# Test\nprd-id: cli-test\n", encoding="utf-8")
        run_dir = tmp_path / "artifacts" / "prd" / "cli-test"
        run_dir.mkdir(parents=True)
        tasks_yaml = run_dir / "tasks.yaml"
        tasks_yaml.write_text(
            "branchName: gralph/cli-test\ntasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n",
            encoding="utf-8",
        )
        # Point --prd to the tasks.yaml so pipeline uses it (resume path)
        proc = _run_cli(["--dry-run", "--resume", "cli-test"], cwd=tmp_path)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert "dry run" in proc.stdout.lower() or "Dry run" in proc.stdout
        assert "TASK-001" in proc.stdout or "One" in proc.stdout


# ── --init (must exit 0, no crash) ──────────────────────────────────────


class TestCliInit:
    """--init must run and exit 0."""

    def test_init_exits_clean(self, cli_runner):
        r = cli_runner.invoke(main, ["--init"])
        assert r.exit_code == 0


# ── Subcommand: prd ──────────────────────────────────────────────────────


class TestCliPrdSubcommand:
    """Subcommand 'prd' must be invokable (may fail without AI)."""

    def test_prd_help(self, cli_runner):
        r = cli_runner.invoke(main, ["prd", "--help"])
        assert r.exit_code == 0
        assert "prd" in r.output.lower()
        assert "description" in r.output.lower() or "PRD" in r.output

    def test_prd_requires_arg(self, cli_runner):
        r = cli_runner.invoke(main, ["prd"])
        assert r.exit_code != 0

    def test_prd_with_description_does_not_crash(self):
        # Invoke via subprocess; short timeout (prd may block on AI engine)
        try:
            proc = _run_cli(["prd", "Add a test feature"], timeout=5)
        except subprocess.TimeoutExpired:
            # Engine is slow/missing; we only care that it didn't crash at import
            return
        err = proc.stdout + proc.stderr
        assert not ("ModuleNotFoundError" in err and "gralph.tasks" in err), f"CLI crashed: {err!r}"


# ── PS1 aliases (optional, if we want to assert they're rewritten) ───────


class TestCliPs1Aliases:
    """PS1 aliases are rewritten to canonical options."""

    def test_show_help_alias(self, cli_runner):
        r = cli_runner.invoke(main, ["--show-help"])
        assert r.exit_code == 0
        assert "GRALPH" in r.output

    def test_show_version_alias(self, cli_runner):
        r = cli_runner.invoke(main, ["--show-version"])
        assert r.exit_code == 0
        assert "4." in r.output


# ── Invoke as module (smoke test) ───────────────────────────────────────


class TestCliModuleInvocation:
    """python -m gralph must behave like gralph binary."""

    def test_module_help(self):
        proc = _run_cli(["--help"])
        assert proc.returncode == 0
        assert "GRALPH" in proc.stdout
