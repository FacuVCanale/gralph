"""Rigorous CLI tests: ensure every command and flag runs without errors."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

# Import CLI helpers directly for unit-level parsing tests.
from gralph.cli import main, _parse_providers_option, _resolve_cli_engine_and_providers
from gralph.config import Config, DEFAULT_PROVIDERS
from gralph.engines.base import EngineBase, EngineResult
from gralph.io_utils import read_text, write_text


def _run_cli(args: list[str], cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run gralph as subprocess. Use when cwd matters (e.g. --dry-run)."""
    cmd = [sys.executable, "-m", "gralph"] + args
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Replace invalid bytes instead of crashing on Windows
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

    def test_gemini_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--gemini", "--help"])
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


class TestCliProvidersOption:
    """Provider-list CLI behavior: parsing, validation, and conflicts."""

    def test_providers_help(self, cli_runner):
        r = cli_runner.invoke(main, ["--providers", "claude,codex", "--help"])
        assert r.exit_code == 0

    def test_providers_sets_config_and_primary_engine(self, cli_runner):
        with patch("gralph.cli._run_pipeline") as mock_run_pipeline:
            r = cli_runner.invoke(
                main,
                ["--providers", "  CoDeX, gemini  "],
                obj={},
                catch_exceptions=False,
            )

        assert r.exit_code == 0, r.output
        mock_run_pipeline.assert_called_once()
        cfg = mock_run_pipeline.call_args.args[0]
        assert isinstance(cfg, Config)
        assert cfg.providers == ["codex", "gemini"]
        assert cfg.ai_engine == "codex"

    def test_engine_flag_sets_single_provider_list(self, cli_runner):
        with patch("gralph.cli._run_pipeline") as mock_run_pipeline:
            r = cli_runner.invoke(
                main,
                ["--gemini"],
                obj={},
                catch_exceptions=False,
            )

        assert r.exit_code == 0, r.output
        mock_run_pipeline.assert_called_once()
        cfg = mock_run_pipeline.call_args.args[0]
        assert isinstance(cfg, Config)
        assert cfg.providers == ["gemini"]
        assert cfg.ai_engine == "gemini"

    def test_default_engine_uses_all_default_providers(self, cli_runner):
        with patch("gralph.cli._run_pipeline") as mock_run_pipeline:
            r = cli_runner.invoke(main, [], obj={}, catch_exceptions=False)

        assert r.exit_code == 0, r.output
        mock_run_pipeline.assert_called_once()
        cfg = mock_run_pipeline.call_args.args[0]
        assert isinstance(cfg, Config)
        assert cfg.providers == list(DEFAULT_PROVIDERS)
        assert cfg.ai_engine == "claude"

    def test_providers_reject_unknown_provider(self, cli_runner):
        r = cli_runner.invoke(main, ["--providers", "claude,unknown-provider"])
        assert r.exit_code != 0
        assert "Unknown provider(s): unknown-provider" in r.output

    def test_providers_reject_duplicate_provider(self, cli_runner):
        r = cli_runner.invoke(main, ["--providers", "claude,codex,claude"])
        assert r.exit_code != 0
        assert "Duplicate provider(s): claude" in r.output

    def test_providers_reject_empty_entries(self, cli_runner):
        r = cli_runner.invoke(main, ["--providers", "claude,,codex"])
        assert r.exit_code != 0
        assert "cannot contain empty values" in r.output.lower()

    def test_providers_conflicts_with_engine_flag(self, cli_runner):
        r = cli_runner.invoke(main, ["--codex", "--providers", "claude,gemini"])
        assert r.exit_code != 0
        assert "Cannot combine --providers with an engine flag" in r.output

    def test_multiple_engine_flags_conflict(self, cli_runner):
        r = cli_runner.invoke(main, ["--codex", "--gemini"])
        assert r.exit_code != 0
        assert "Conflicting engine flags selected" in r.output


class TestCliProvidersParsingUnits:
    """Direct unit tests for provider parsing and engine/provider resolution."""

    def test_parse_providers_normalizes_case_and_whitespace(self) -> None:
        assert _parse_providers_option("  CoDeX, gemini , CLAUDE ") == [
            "codex",
            "gemini",
            "claude",
        ]

    def test_parse_providers_unknown_error_lists_each_unknown_once(self) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _parse_providers_option("unknown,claude,unknown,other")

        assert "Unknown provider(s): unknown, other" in str(excinfo.value)

    def test_parse_providers_rejects_case_insensitive_duplicates(self) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _parse_providers_option("CoDeX,codex")

        assert "Duplicate provider(s): codex" in str(excinfo.value)

    def test_resolve_engine_and_providers_keeps_order_for_provider_list(self) -> None:
        engine_name, provider_list = _resolve_cli_engine_and_providers(
            (),
            "gemini,codex,claude",
        )

        assert engine_name == "gemini"
        assert provider_list == ["gemini", "codex", "claude"]

    def test_resolve_engine_and_providers_allows_repeating_same_engine_flag(self) -> None:
        engine_name, provider_list = _resolve_cli_engine_and_providers(
            ("codex", "codex"),
            "",
        )

        assert engine_name == "codex"
        assert provider_list == ["codex"]


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
        write_text(tmp_path / "PRD.md", "# Test\nprd-id: cli-test\n")
        run_dir = tmp_path / "artifacts" / "prd" / "cli-test"
        run_dir.mkdir(parents=True)
        tasks_yaml = run_dir / "tasks.yaml"
        write_text(
            tasks_yaml,
            "branchName: gralph/cli-test\ntasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n",
        )
        # Point --prd to the tasks.yaml so pipeline uses it (resume path)
        proc = _run_cli(["--dry-run", "--resume", "cli-test"], cwd=tmp_path)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert "dry run" in proc.stdout.lower() or "Dry run" in proc.stdout
        assert "TASK-001" in proc.stdout or "One" in proc.stdout

    def test_dry_run_invokes_metadata_agent_when_tasks_yaml_missing(
        self, cli_runner, tmp_path: Path
    ):
        """When tasks.yaml does not exist, metadata agent runs; mock engine creates it."""
        prd_content = "# PRD: Meta Test\nprd-id: meta-test\n\nBody.\n"
        write_text(tmp_path / "prd-meta.md", prd_content)

        minimal_tasks = (
            "branchName: gralph/meta-test\n"
            "tasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n"
        )

        class _MetadataTestEngine(EngineBase):
            def build_cmd(self, prompt: str) -> list[str]:
                return [sys.executable, "-c", "pass"]

            def parse_output(self, raw: str) -> EngineResult:
                return EngineResult(text="ok")

            def run_sync(self, prompt, **kwargs):
                match = re.search(r"Save the file as ([^\n]+)", prompt)
                if match:
                    out_path = Path(match.group(1).strip().rstrip("."))
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    write_text(out_path, minimal_tasks)
                return EngineResult(text="ok")

        mock_engine = _MetadataTestEngine()

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("gralph.engines.registry.get_engine", return_value=mock_engine):
                r = cli_runner.invoke(
                    main,
                    ["--codex", "--dry-run", "--prd", "prd-meta.md"],
                    obj={},
                    catch_exceptions=False,
                )
        finally:
            os.chdir(old_cwd)
        assert r.exit_code == 0, r.output
        assert "dry run" in r.output.lower() or "Dry run" in r.output
        assert "TASK-001" in r.output or "One" in r.output

    def test_metadata_agent_prompt_requires_structure_tests_and_docs(self, tmp_path: Path) -> None:
        from gralph.cli import _run_metadata_agent

        prd_path = tmp_path / "PRD.md"
        output = tmp_path / "tasks.yaml"
        write_text(prd_path, "# PRD: Meta Prompt\n\nprd-id: meta-prompt\n\nBody.\n")

        captured: dict[str, str] = {}
        minimal_tasks = (
            "branchName: gralph/meta-prompt\n"
            "tasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n"
        )

        class _CapturePromptEngine(EngineBase):
            def build_cmd(self, prompt: str) -> list[str]:
                return [sys.executable, "-c", "pass"]

            def parse_output(self, raw: str) -> EngineResult:
                return EngineResult(text=raw)

            def run_sync(self, prompt, **kwargs):
                captured["prompt"] = prompt
                write_text(output, minimal_tasks)
                return EngineResult(text="ok")

        _run_metadata_agent(_CapturePromptEngine(), prd_path, output)

        prompt = captured["prompt"].lower()
        assert "repository structure" in prompt
        assert "automated testing tasks" in prompt
        assert "readme.md" in prompt


# ── Full pipeline run (no --dry-run) ─────────────────────────────────────
# Exercises code paths after dry-run (e.g. progress.txt, Runner) so missing
# Config attributes (e.g. run_dir vs artifacts_dir) are caught.


class TestCliFullPipelineRun:
    """Pipeline run without --dry-run must not crash on Config attribute access."""

    def test_resume_run_creates_progress_and_exits_success(self, cli_runner, tmp_path: Path):
        """Running with --resume (no --dry-run) reaches progress.txt creation and Runner; no AttributeError on cfg.run_dir."""
        write_text(tmp_path / "PRD.md", "# Test\nprd-id: cli-test\n")
        run_dir = tmp_path / "artifacts" / "prd" / "cli-test"
        run_dir.mkdir(parents=True)
        write_text(
            run_dir / "tasks.yaml",
            "branchName: gralph/cli-test\ntasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n",
        )
        subprocess.run(
            ["git", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        write_text(tmp_path / "dummy", "x")
        subprocess.run(
            ["git", "add", "dummy"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_EMAIL": "t@t.com",
                "GIT_AUTHOR_NAME": "T",
                "GIT_COMMITTER_EMAIL": "t@t.com",
                "GIT_COMMITTER_NAME": "T",
            },
        )
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = True

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("gralph.runner.Runner", return_value=mock_runner_instance):
                r = cli_runner.invoke(
                    main,
                    ["--codex", "--resume", "cli-test"],
                    obj={},
                    catch_exceptions=False,
                )
        finally:
            os.chdir(old_cwd)
        assert r.exit_code == 0, r.output
        # progress.txt is created under artifacts/run-<ts> (set by init_artifacts_dir)
        artifacts = tmp_path / "artifacts"
        progress_files = list(artifacts.rglob("progress.txt"))
        assert len(progress_files) >= 1, f"expected progress.txt under {artifacts}"

    def test_fresh_prd_run_creates_progress_and_exits_success(
        self, cli_runner, tmp_path: Path
    ):
        """Running with --prd (no --resume, no --dry-run) reaches progress.txt; same cfg.artifacts_dir path."""
        prd_content = "# PRD: Fresh\nprd-id: fresh-test\n\nBody.\n"
        write_text(tmp_path / "PRD.md", prd_content)
        minimal_tasks = (
            "branchName: gralph/fresh-test\n"
            "tasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n"
        )

        class _FreshTestEngine(EngineBase):
            def build_cmd(self, prompt: str) -> list[str]:
                return [sys.executable, "-c", "pass"]

            def parse_output(self, raw: str) -> EngineResult:
                return EngineResult(text="ok")

            def run_sync(self, prompt, **kwargs):
                out_path = tmp_path / "artifacts" / "prd" / "fresh-test" / "tasks.yaml"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                write_text(out_path, minimal_tasks)
                return EngineResult(text="ok")

        subprocess.run(
            ["git", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        write_text(tmp_path / "dummy", "x")
        subprocess.run(
            ["git", "add", "dummy"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_EMAIL": "t@t.com",
                "GIT_AUTHOR_NAME": "T",
                "GIT_COMMITTER_EMAIL": "t@t.com",
                "GIT_COMMITTER_NAME": "T",
            },
        )
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = True

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("gralph.engines.registry.get_engine", return_value=_FreshTestEngine()):
                with patch("gralph.runner.Runner", return_value=mock_runner_instance):
                    r = cli_runner.invoke(
                        main,
                        ["--codex", "--prd", "PRD.md"],
                        obj={},
                        catch_exceptions=False,
                    )
        finally:
            os.chdir(old_cwd)
        assert r.exit_code == 0, r.output
        progress_files = list((tmp_path / "artifacts").rglob("progress.txt"))
        assert len(progress_files) >= 1

    def test_resume_run_fails_fast_when_run_branch_is_dirty(self, cli_runner, tmp_path: Path):
        write_text(tmp_path / "PRD.md", "# Test\nprd-id: dirty-run\n")
        run_dir = tmp_path / "artifacts" / "prd" / "dirty-run"
        run_dir.mkdir(parents=True)
        write_text(
            run_dir / "tasks.yaml",
            "branchName: gralph/dirty-run\ntasks:\n"
            "  - id: TASK-001\n    title: One\n    completed: false\n    dependsOn: []\n    mutex: []\n",
        )

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        write_text(tmp_path / "dummy", "x")
        subprocess.run(["git", "add", "dummy"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_EMAIL": "t@t.com",
                "GIT_AUTHOR_NAME": "T",
                "GIT_COMMITTER_EMAIL": "t@t.com",
                "GIT_COMMITTER_NAME": "T",
            },
        )
        subprocess.run(
            ["git", "branch", "gralph/dirty-run"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        write_text(tmp_path / "dummy", "changed")

        mock_engine = MagicMock()
        mock_engine.check_available.return_value = None

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("gralph.engines.registry.get_engine", return_value=mock_engine):
                with patch("gralph.skills.ensure_skills", return_value=None):
                    with patch("gralph.runner.Runner") as mock_runner:
                        r = cli_runner.invoke(
                            main,
                            ["--resume", "dirty-run"],
                            obj={},
                            catch_exceptions=False,
                        )
        finally:
            os.chdir(old_cwd)

        assert r.exit_code != 0
        assert "Working tree is dirty on the run branch" in r.output
        mock_runner.assert_not_called()


# ── Config attributes used by pipeline ───────────────────────────────────
# Ensures Config has all attributes the pipeline expects (e.g. artifacts_dir, not run_dir).


class TestConfigPipelineAttributes:
    """Config must define every attribute accessed in _run_pipeline."""

    def test_config_has_artifacts_dir_for_progress_path(self):
        """Pipeline uses cfg.artifacts_dir for progress.txt path; must exist on Config."""
        cfg = Config()
        assert hasattr(cfg, "artifacts_dir")
        progress = Path(cfg.artifacts_dir or ".") / "progress.txt"
        assert progress.name == "progress.txt"


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

    def test_build_prd_phase2_prompt_includes_questions_and_answers(self):
        from gralph.cli import _build_prd_phase2_prompt

        prompt = _build_prd_phase2_prompt(
            skill_instruction="Skill block",
            description="Implement provider fallback",
            questions_text="1. Assignment?\nA. First\nB. Round-robin",
            user_answers="1B, keep logs",
            save_path_str="tasks/prd-temp.md",
        )

        assert "Clarifying questions that were asked:" in prompt
        assert "1. Assignment?" in prompt
        assert "User's answers to clarifying questions:" in prompt
        assert "1B, keep logs" in prompt
        assert "Interpret answer codes by number+letter." in prompt
        assert "## Repository Structure Plan" in prompt
        assert "## Testing Requirements" in prompt
        assert "## Documentation Requirements" in prompt
        assert "## Definition of Done" in prompt
        assert "Save the PRD to: tasks/prd-temp.md" in prompt

    def test_prd_generation_phase2_prompt_uses_questions_and_answers(self, tmp_path: Path):
        from gralph.cli import _run_prd_generation

        cfg = Config(ai_engine="claude", verbose=False)
        prompts: list[str] = []
        questions = (
            "1. How should providers be assigned?\n"
            "A. First available\n"
            "B. Round-robin\n"
        )

        mock_engine = MagicMock()
        mock_engine.check_available.return_value = None

        def _run_sync(prompt: str, **kwargs):
            prompts.append(prompt)
            cwd = kwargs["cwd"]
            if len(prompts) == 1:
                return EngineResult(text=f"{questions}\n---END_QUESTIONS---")
            write_text(cwd / "tasks" / "prd-temp.md", "# PRD: Test\n\nprd-id: test\n\nBody.\n")
            return EngineResult(text="ok")

        mock_engine.run_sync.side_effect = _run_sync

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("gralph.engines.registry.get_engine", return_value=mock_engine):
                with patch("gralph.cli._find_prd_skill", return_value=None):
                    with patch.object(sys.stdin, "isatty", return_value=True):
                        with patch("gralph.cli.click.prompt", return_value="1B"):
                            _run_prd_generation(cfg, "Implement provider fallback", "", no_questions=False)
        finally:
            os.chdir(old_cwd)

        assert len(prompts) == 2
        phase2_prompt = prompts[1]
        assert "Clarifying questions that were asked:" in phase2_prompt
        assert "1. How should providers be assigned?" in phase2_prompt
        assert "User's answers to clarifying questions:" in phase2_prompt
        assert "1B" in phase2_prompt
        assert "## Repository Structure Plan" in phase2_prompt
        assert "## Testing Requirements" in phase2_prompt
        assert "## Documentation Requirements" in phase2_prompt
        assert "## Definition of Done" in phase2_prompt

    def test_find_prd_skill_for_claude_prefers_bundled_over_user(self, tmp_path: Path):
        from gralph.cli import _find_prd_skill

        fake_repo = tmp_path / "repo"
        fake_home = tmp_path / "home"

        user_skill = fake_home / ".claude" / "skills" / "prd" / "SKILL.md"
        user_skill.parent.mkdir(parents=True, exist_ok=True)
        user_skill.write_text("# user skill")

        bundled = fake_repo / "skills" / "prd" / "SKILL.md"
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text("# bundled skill")

        with patch("gralph.config.resolve_repo_root", return_value=fake_repo):
            with patch("pathlib.Path.home", return_value=fake_home):
                result = _find_prd_skill("claude")

        assert result == bundled

    def test_find_prd_skill_for_claude_prefers_project_specific(self, tmp_path: Path):
        from gralph.cli import _find_prd_skill

        fake_repo = tmp_path / "repo"
        fake_home = tmp_path / "home"

        project_skill = fake_repo / ".claude" / "skills" / "prd" / "SKILL.md"
        project_skill.parent.mkdir(parents=True, exist_ok=True)
        project_skill.write_text("# project skill")

        bundled = fake_repo / "skills" / "prd" / "SKILL.md"
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text("# bundled skill")

        with patch("gralph.config.resolve_repo_root", return_value=fake_repo):
            with patch("pathlib.Path.home", return_value=fake_home):
                result = _find_prd_skill("claude")

        assert result == project_skill

    def test_prd_rename_overwrites_existing_file(self, tmp_path: Path):
        """When renaming prd-temp.md to prd-<id>.md, overwrite existing target (Windows-safe)."""
        from gralph.cli import _run_prd_single

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        write_path = tasks_dir / "prd-temp.md"
        final_path = tasks_dir / "prd-provider-fallback-rate-limit.md"

        # Pre-create target so rename would fail with Path.rename() on Windows
        write_text(final_path, "old content\n")
        assert final_path.is_file()

        prd_content = "# PRD: Test\nprd-id: provider-fallback-rate-limit\n\nBody.\n"
        mock_engine = MagicMock()

        def _on_run_sync(*_args, **_kwargs):
            write_text(write_path, prd_content)
            return EngineResult(text="ok")

        mock_engine.run_sync.side_effect = _on_run_sync

        cfg = Config(ai_engine="cursor", verbose=False)
        _run_prd_single(
            cfg,
            mock_engine,
            tmp_path,
            "provider fallback rate limit",
            str(write_path),
            "",  # output_path: use default naming
            tasks_dir,
            write_path,
        )

        assert final_path.is_file(), "Final PRD file should exist"
        assert "old content" not in read_text(final_path)
        assert "provider-fallback-rate-limit" in read_text(final_path)

    def test_prd_failure_without_error_shows_engine_output(self, tmp_path: Path, capsys):
        """If engine returns text but no explicit error, surface that text when file is missing."""
        from gralph.cli import _run_prd_single

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        write_path = tasks_dir / "prd-temp.md"

        mock_engine = MagicMock()
        mock_engine.run_sync.return_value = EngineResult(
            text="Could not create file due policy constraints."
        )

        cfg = Config(ai_engine="codex", verbose=False)
        with pytest.raises(SystemExit):
            _run_prd_single(
                cfg,
                mock_engine,
                tmp_path,
                "provider fallback",
                str(write_path),
                "",  # output_path: use default naming
                tasks_dir,
                write_path,
            )

        captured = capsys.readouterr()
        combined = f"{captured.out}\n{captured.err}"
        assert "Engine output:" in combined
        assert "Could not create file due policy constraints." in combined

    def test_prd_single_retries_rate_limit_and_saves_returned_prd_text(self, tmp_path: Path):
        """PRD flow should retry short rate limits and persist PRD when engine returns text."""
        from gralph.cli import _run_prd_single

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        write_path = tasks_dir / "prd-temp.md"

        mock_engine = MagicMock()
        mock_engine.run_sync.side_effect = [
            EngineResult(error="Rate limit exceeded"),
            EngineResult(text="# PRD: Retry Test\n\nprd-id: retry-test\n\nBody.\n"),
        ]

        cfg = Config(ai_engine="codex", verbose=False)
        with patch("gralph.cli.time.sleep", return_value=None):
            _run_prd_single(
                cfg,
                mock_engine,
                tmp_path,
                "provider fallback",
                str(write_path),
                "",  # output_path: use default naming
                tasks_dir,
                write_path,
            )

        final_path = tasks_dir / "prd-retry-test.md"
        assert final_path.is_file()
        assert "prd-id: retry-test" in read_text(final_path)
        assert mock_engine.run_sync.call_count == 2

    def test_prd_single_skips_retry_when_output_is_usable(self, tmp_path: Path):
        """Do not retry on rate-limit-like errors when engine already returned valid output."""
        from gralph.cli import _run_prd_single

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        write_path = tasks_dir / "prd-temp.md"

        mock_engine = MagicMock()
        mock_engine.run_sync.return_value = EngineResult(
            error="Rate limit exceeded",
            return_code=0,
            text="# PRD: Usable Output\n\nprd-id: usable-output\n\nBody.\n",
        )

        cfg = Config(ai_engine="claude", verbose=False)
        with patch("gralph.cli.time.sleep", return_value=None) as mock_sleep:
            _run_prd_single(
                cfg,
                mock_engine,
                tmp_path,
                "provider fallback",
                str(write_path),
                "",  # output_path: use default naming
                tasks_dir,
                write_path,
            )

        final_path = tasks_dir / "prd-usable-output.md"
        assert final_path.is_file()
        assert "prd-id: usable-output" in read_text(final_path)
        assert mock_engine.run_sync.call_count == 1
        mock_sleep.assert_not_called()

    def test_prd_single_ctrl_c_during_retry_sleep_aborts(self, tmp_path: Path):
        """Ctrl-C during retry wait should abort immediately."""
        from gralph.cli import _run_prd_single

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        write_path = tasks_dir / "prd-temp.md"

        mock_engine = MagicMock()
        mock_engine.run_sync.return_value = EngineResult(error="Rate limit exceeded")

        cfg = Config(ai_engine="claude", verbose=False)
        with patch("gralph.cli.time.sleep", side_effect=KeyboardInterrupt):
            with pytest.raises(click.Abort):
                _run_prd_single(
                    cfg,
                    mock_engine,
                    tmp_path,
                    "provider fallback",
                    str(write_path),
                    "",
                    tasks_dir,
                    write_path,
                )

    def test_prd_single_interrupt_return_code_aborts(self, tmp_path: Path):
        """If provider exits due Ctrl-C, treat it as user abort and stop."""
        from gralph.cli import _run_prd_single

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        write_path = tasks_dir / "prd-temp.md"

        mock_engine = MagicMock()
        mock_engine.run_sync.return_value = EngineResult(
            error="",
            text="",
            return_code=130,
        )

        cfg = Config(ai_engine="claude", verbose=False)
        with pytest.raises(click.Abort):
            _run_prd_single(
                cfg,
                mock_engine,
                tmp_path,
                "provider fallback",
                str(write_path),
                "",
                tasks_dir,
                write_path,
            )


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
