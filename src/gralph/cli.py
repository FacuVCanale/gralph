"""GRALPH CLI — drop-in replacement for the shell scripts.

Installed as ``gralph`` console_script via pipx / pip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from gralph import __version__
from gralph.config import Config


# ── Custom Click group that handles PS1 aliases ──────────────────────

class GralphGroup(click.Group):
    """Handle ``--show-help``, ``-help``, ``--show-version`` etc. PS1 aliases."""

    # Map PS1-only aliases to canonical Click names
    _ALIASES: dict[str, str] = {
        "-help": "--help",
        "--show-help": "--help",
        "-show-help": "--help",
        "-version": "--version",
        "--show-version": "--version",
        "-show-version": "--version",
        "--skip-tests": "--no-tests",
        "--skip-lint": "--no-lint",
    }

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Rewrite PS1 aliases before Click parses them."""
        rewritten = [self._ALIASES.get(a, a) for a in args]
        return super().parse_args(ctx, rewritten)


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(
    cls=GralphGroup,
    invoke_without_command=True,
    context_settings=CONTEXT_SETTINGS,
)
@click.option("--claude", "engine", flag_value="claude", help="Use Claude Code (default)")
@click.option("--opencode", "engine", flag_value="opencode", help="Use OpenCode")
@click.option("--codex", "engine", flag_value="codex", help="Use Codex CLI")
@click.option("--cursor", "engine", flag_value="cursor", help="Use Cursor agent")
@click.option("--agent", "engine", flag_value="cursor", hidden=True)
@click.option("--opencode-model", default="", help="OpenCode model override")
@click.option("--no-tests", is_flag=True, help="Skip tests")
@click.option("--no-lint", is_flag=True, help="Skip linting")
@click.option("--fast", is_flag=True, help="Skip both tests and linting")
@click.option("--sequential", is_flag=True, help="Run tasks one at a time")
@click.option("--parallel", is_flag=True, default=True, hidden=True)
@click.option("--max-parallel", type=int, default=3, help="Max concurrent tasks")
@click.option("--max-iterations", type=int, default=0, help="Stop after N iterations (0=unlimited)")
@click.option("--max-retries", type=int, default=3, help="Max retries per task")
@click.option("--retry-delay", type=int, default=5, help="Seconds between retries")
@click.option("--external-fail-timeout", type=int, default=300, help="Timeout for running tasks on external failure")
@click.option("--stalled-timeout", type=int, default=600, help="Seconds before killing stalled agent")
@click.option("--dry-run", is_flag=True, help="Show plan without executing")
@click.option("--branch-per-task", is_flag=True, help="Create a branch per task")
@click.option("--base-branch", default="", help="Base branch for task branches")
@click.option("--create-pr", is_flag=True, help="Create PR per task (requires gh)")
@click.option("--draft-pr", is_flag=True, help="Create PRs as drafts")
@click.option("--prd", "prd_file", default="PRD.md", help="PRD file path")
@click.option("--resume", "resume_prd_id", default="", help="Resume a previous run by prd-id")
@click.option("--init", "skills_init", is_flag=True, help="Install missing skills and exit")
@click.option("--skills-url", default="", help="Override skills base URL")
@click.option("--update", "do_update", is_flag=True, help="Update gralph")
@click.option("-v", "--verbose", is_flag=True, help="Show debug output")
@click.version_option(__version__, prog_name="gralph")
@click.pass_context
def main(
    ctx: click.Context,
    engine: str | None,
    opencode_model: str,
    no_tests: bool,
    no_lint: bool,
    fast: bool,
    sequential: bool,
    parallel: bool,
    max_parallel: int,
    max_iterations: int,
    max_retries: int,
    retry_delay: int,
    external_fail_timeout: int,
    stalled_timeout: int,
    dry_run: bool,
    branch_per_task: bool,
    base_branch: str,
    create_pr: bool,
    draft_pr: bool,
    prd_file: str,
    resume_prd_id: str,
    skills_init: bool,
    skills_url: str,
    do_update: bool,
    verbose: bool,
) -> None:
    """GRALPH — Autonomous AI Coding Loop.

    Reads a PRD, generates tasks.yaml, and runs AI agents in parallel
    using a DAG scheduler with mutex support.

    \b
    EXAMPLES:
      gralph --opencode                          # Run with OpenCode (parallel)
      gralph --opencode --sequential             # Run sequentially
      gralph --resume my-feature                 # Resume previous run
      gralph --init --claude                     # Install skills for Claude
      gralph prd "Add user auth with OAuth"      # Generate a PRD
      gralph --codex prd "Implement dark mode"   # Generate PRD with Codex

    \b
    WORKFLOW:
      1. Generate PRD:  gralph prd "your feature description"
      2. Run:           gralph --opencode
      3. GRALPH creates artifacts/prd/<prd-id>/ with tasks.yaml
      4. Tasks run in parallel using DAG scheduler
      5. Resume anytime with --resume <prd-id>
    """
    from gralph import log as glog

    glog.set_verbose(verbose)

    # ── Handle --update early ────────────────────────────────────
    if do_update:
        from gralph.update import self_update

        self_update()
        ctx.exit(0)

    # ── Build config ─────────────────────────────────────────────
    cfg = Config(
        ai_engine=engine or "claude",
        opencode_model=opencode_model,
        skip_tests=no_tests or fast,
        skip_lint=no_lint or fast,
        sequential=sequential,
        parallel=not sequential,
        max_parallel=max_parallel if not sequential else 1,
        max_iterations=max_iterations,
        max_retries=max_retries,
        retry_delay=retry_delay,
        external_fail_timeout=external_fail_timeout,
        stalled_timeout=stalled_timeout,
        dry_run=dry_run,
        branch_per_task=branch_per_task,
        base_branch=base_branch,
        create_pr=create_pr,
        draft_pr=draft_pr,
        prd_file=prd_file,
        resume_prd_id=resume_prd_id,
        skills_init=skills_init,
        skills_base_url=skills_url,
        verbose=verbose,
    )

    # ── Handle --init ────────────────────────────────────────────
    if cfg.skills_init:
        from gralph.skills import ensure_skills

        ensure_skills(cfg, mode="install")
        ctx.exit(0)

    # ── If a subcommand (e.g. prd) was invoked, skip the pipeline ─
    if ctx.invoked_subcommand is not None:
        return

    # ── Main pipeline ────────────────────────────────────────────
    _run_pipeline(cfg)


# ── Subcommand: prd ──────────────────────────────────────────────


@main.command()
@click.argument("description")
@click.option("--output", "-o", default="", help="Output file path (default: tasks/prd-<slug>.md)")
@click.pass_context
def prd(ctx: click.Context, description: str, output: str) -> None:
    """Generate a PRD from a feature description.

    \b
    EXAMPLES:
      gralph prd "Add user authentication with OAuth"
      gralph --codex prd "Implement dark mode toggle"
      gralph --claude prd -o PRD.md "Refactor payment flow"
    """
    from gralph import log as glog

    # Inherit engine from parent context
    parent_params = ctx.parent.params if ctx.parent else {}
    engine_name = parent_params.get("engine") or "claude"
    verbose = parent_params.get("verbose", False)
    skills_url = parent_params.get("skills_url", "")

    glog.set_verbose(verbose)

    cfg = Config(
        ai_engine=engine_name,
        verbose=verbose,
        skills_base_url=skills_url,
    )

    _run_prd_generation(cfg, description, output)


def _run_prd_generation(cfg: Config, description: str, output_path: str) -> None:
    """Run an AI engine to generate a PRD from a feature description."""
    from gralph import log as glog
    from gralph.engines.registry import get_engine
    from gralph.prd import extract_prd_id, slugify

    engine = get_engine(cfg.ai_engine)
    err = engine.check_available()
    if err:
        glog.error(err)
        sys.exit(1)

    # Load PRD skill content
    skill_path = _find_prd_skill(cfg.ai_engine)
    if skill_path:
        skill_content = skill_path.read_text(encoding="utf-8")
        skill_instruction = f"""Follow these instructions for creating the PRD:\n\n{skill_content}"""
    else:
        glog.warn("PRD skill not found; using built-in prompt. Run 'gralph --init' to install skills.")
        skill_instruction = ""

    # Determine output file
    slug = slugify(description)
    if not output_path:
        tasks_dir = Path("tasks")
        tasks_dir.mkdir(exist_ok=True)
        output_path = str(tasks_dir / f"prd-{slug}.md")

    prompt = f"""{skill_instruction}

Feature request from the user:
{description}

IMPORTANT RULES:
1. The PRD MUST start with `# PRD: <Title>` followed by `prd-id: {slug}` on the next non-blank line.
2. Do NOT ask clarifying questions interactively — infer reasonable defaults and note assumptions in the Open Questions section.
3. Save the PRD to: {output_path}
4. Do NOT implement anything — only create the PRD file."""

    glog.info(f"Generating PRD with {cfg.ai_engine}…")
    glog.info(f"Output: {output_path}")

    result = engine.run_sync(prompt)

    out = Path(output_path)
    if out.is_file():
        # Verify prd-id is present
        prd_id = extract_prd_id(out)
        if prd_id:
            glog.success(f"PRD created: {output_path} (prd-id: {prd_id})")
        else:
            glog.warn(f"PRD created at {output_path} but missing prd-id. Adding it…")
            _inject_prd_id(out, slug)
            glog.success(f"PRD fixed: {output_path} (prd-id: {slug})")
    else:
        glog.error(f"Engine failed to create {output_path}")
        if result.error:
            glog.error(f"Error: {result.error}")
        sys.exit(1)


def _find_prd_skill(engine_name: str) -> Path | None:
    """Locate the PRD skill file for the given engine."""
    from gralph.config import resolve_repo_root

    repo = resolve_repo_root()
    home = Path.home()

    candidates: list[Path] = []
    match engine_name:
        case "claude":
            candidates = [
                repo / ".claude/skills/prd/SKILL.md",
                home / ".claude/skills/prd/SKILL.md",
            ]
        case "codex":
            candidates = [
                repo / ".codex/skills/prd/SKILL.md",
                home / ".codex/skills/prd/SKILL.md",
            ]
        case "opencode":
            candidates = [
                repo / ".opencode/skill/prd/SKILL.md",
                home / ".config/opencode/skill/prd/SKILL.md",
            ]
        case "cursor":
            candidates = [
                repo / ".cursor/rules/prd.mdc",
                repo / ".cursor/commands/prd.md",
            ]

    # Also check the bundled skills dir
    candidates.append(repo / "skills/prd/SKILL.md")

    for c in candidates:
        if c.is_file():
            return c
    return None


def _inject_prd_id(prd_file: Path, slug: str) -> None:
    """Insert a prd-id line after the title if missing."""
    content = prd_file.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    for i, line in enumerate(lines):
        if line.startswith("# "):
            # Insert prd-id after the title line
            prd_id_line = f"\nprd-id: {slug}\n"
            lines.insert(i + 1, prd_id_line)
            break
    else:
        # No title found — prepend
        lines.insert(0, f"prd-id: {slug}\n\n")

    prd_file.write_text("".join(lines), encoding="utf-8")


def _run_pipeline(cfg: Config) -> None:
    """Full GRALPH pipeline: PRD → tasks → schedule → execute → report."""
    from gralph import log as glog
    from gralph.artifacts import init_artifacts_dir, show_summary
    from gralph.config import resolve_repo_root
    from gralph.engines.registry import get_engine
    from gralph.git_ops import (
        current_branch,
        ensure_clean_git_state,
        cleanup_stale_agent_branches,
        ensure_run_branch,
    )
    from gralph.notify import notify_done, notify_error
    from gralph.prd import extract_prd_id, setup_run_dir, find_prd_file, copy_prd_to_run_dir
    from gralph.runner import Runner
    from gralph.scheduler import Scheduler
    from gralph.skills import ensure_skills
    from gralph.tasks.io import load_task_file
    from gralph.tasks.validate import validate_and_report

    # ── Pre-flight: engine check ─────────────────────────────────
    engine = get_engine(cfg.ai_engine, opencode_model=cfg.opencode_model)
    err = engine.check_available()
    if err:
        glog.error(err)
        sys.exit(1)

    # ── gh check if --create-pr ──────────────────────────────────
    if cfg.create_pr:
        import shutil

        if not shutil.which("gh"):
            glog.error("GitHub CLI (gh) is required for --create-pr. Install from https://cli.github.com/")
            sys.exit(1)

    # ── PRD / resume handling ────────────────────────────────────
    if cfg.resume_prd_id:
        cfg.prd_id = cfg.resume_prd_id
        cfg.prd_run_dir = f"artifacts/prd/{cfg.prd_id}"
        run_dir = Path(cfg.prd_run_dir)
        if not run_dir.is_dir():
            glog.error(f"No run found for prd-id: {cfg.prd_id}")
            sys.exit(1)
        tasks_path = run_dir / "tasks.yaml"
        if not tasks_path.is_file():
            glog.error(f"No tasks.yaml found in {cfg.prd_run_dir}")
            sys.exit(1)
        cfg.prd_file = str(tasks_path)
        cfg.artifacts_dir = cfg.prd_run_dir
        glog.info(f"Resuming PRD: {cfg.prd_id}")
    else:
        prd_path = Path(cfg.prd_file)
        if not prd_path.is_file():
            found = find_prd_file()
            if found:
                prd_path = found
            else:
                glog.error("PRD.md not found")
                sys.exit(1)
            cfg.prd_file = str(prd_path)

        cfg.prd_id = extract_prd_id(prd_path)
        if not cfg.prd_id:
            glog.error("PRD missing prd-id. Add 'prd-id: your-id' to the PRD file.")
            sys.exit(1)

        run_dir = setup_run_dir(cfg.prd_id)
        cfg.prd_run_dir = str(run_dir)
        copy_prd_to_run_dir(prd_path, run_dir)

        tasks_path = run_dir / "tasks.yaml"
        if tasks_path.is_file():
            glog.info(f"Resuming existing run for {cfg.prd_id}")
        else:
            glog.info(f"Generating tasks.yaml for {cfg.prd_id}…")
            _run_metadata_agent(engine, prd_path, tasks_path)

        cfg.prd_file = str(tasks_path)

    # ── Load and validate tasks.yaml ─────────────────────────────
    tf = load_task_file(Path(cfg.prd_file))
    if not validate_and_report(tf, base_dir=Path.cwd()):
        sys.exit(1)

    # ── Skills check ─────────────────────────────────────────────
    ensure_skills(cfg, mode="warn")

    # ── Git state cleanup ────────────────────────────────────────
    ensure_clean_git_state()
    cleanup_stale_agent_branches()

    # ── Dry run ──────────────────────────────────────────────────
    if cfg.dry_run:
        _show_dry_run(cfg, tf)
        sys.exit(0)

    # ── Ensure run branch ────────────────────────────────────────
    if tf.branch_name:
        base = cfg.base_branch or current_branch()
        cfg.base_branch = ensure_run_branch(tf.branch_name, base)

    if cfg.branch_per_task and not cfg.base_branch:
        cfg.base_branch = current_branch()

    # ── Banner ───────────────────────────────────────────────────
    _show_banner(cfg)

    # ── Init artifacts dir ───────────────────────────────────────
    init_artifacts_dir(cfg)

    # ── Create progress.txt if missing ───────────────────────────
    progress = Path(cfg.run_dir or ".") / "progress.txt"
    if not progress.is_file():
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.touch()

    # ── Run ──────────────────────────────────────────────────────
    scheduler = Scheduler(tf)
    runner = Runner(cfg, tf, engine, scheduler)

    try:
        success = runner.run()
    except KeyboardInterrupt:
        glog.warn("Interrupted!")
        success = False

    if not success:
        notify_error("GRALPH stopped due to external failure or deadlock")
        sys.exit(1)

    show_summary(cfg, runner.iteration, branches=runner.completed_branches)
    notify_done()


def _run_metadata_agent(engine: object, prd_path: Path, output: Path) -> None:
    """Run the metadata agent to generate tasks.yaml from a PRD."""
    from gralph import log as glog
    from gralph.engines.base import EngineBase

    assert isinstance(engine, EngineBase)

    prompt = f"""Read the PRD file and convert it to tasks.yaml format.

@{prd_path}

Create a tasks.yaml file with this EXACT format:

branchName: gralph/your-feature-name
tasks:
  - id: TASK-001
    title: "First task description"
    completed: false
    dependsOn: []
    mutex: []
  - id: TASK-002
    title: "Second task description"
    completed: false
    dependsOn: ["TASK-001"]
    mutex: []

Rules:
1. Each task gets a unique ID (TASK-001, TASK-002, etc.)
2. Order tasks by dependency (database first, then backend, then frontend)
3. Use dependsOn to link tasks that must run after others
4. Use mutex for shared resources: db-migrations, lockfile, router, global-config
5. Set branchName to a short kebab-case feature name prefixed with "gralph/" (based on the PRD)
6. Keep tasks small and focused (completable in one session)

Save the file as {output}.
Do NOT implement anything - only create the tasks.yaml file."""

    result = engine.run_sync(prompt)

    if not output.is_file():
        glog.error(f"Metadata agent failed to create {output}")
        if result.error:
            glog.error(f"Agent error: {result.error}")
        sys.exit(1)

    glog.success(f"Generated {output}")


def _show_dry_run(cfg: Config, tf: object) -> None:
    from gralph import log as glog
    from gralph.tasks.model import TaskFile

    assert isinstance(tf, TaskFile)

    glog.console.print("")
    glog.console.print("[bold]============================================[/bold]")
    glog.console.print("[bold]GRALPH[/bold] — Dry run (no execution)")

    if tf.branch_name:
        glog.console.print(f"Run branch: [cyan]{tf.branch_name}[/cyan]")

    pending = tf.pending_ids()
    if not pending:
        glog.success("No pending tasks.")
        glog.console.print("[bold]============================================[/bold]")
        return

    glog.info(f"Pending tasks: {len(pending)}")
    for tid in pending:
        task = tf.get_task(tid)
        title = task.title if task else ""
        if title:
            glog.console.print(f"  - [{tid}] {title}")
        else:
            glog.console.print(f"  - [{tid}]")

    glog.console.print("[bold]============================================[/bold]")


def _show_banner(cfg: Config) -> None:
    from gralph import log as glog

    engine_display = {
        "opencode": "[cyan]OpenCode[/cyan]",
        "cursor": "[yellow]Cursor Agent[/yellow]",
        "codex": "[blue]Codex[/blue]",
        "claude": "[magenta]Claude Code[/magenta]",
    }.get(cfg.ai_engine, cfg.ai_engine)

    glog.console.print("[bold]============================================[/bold]")
    glog.console.print("[bold]GRALPH[/bold] — Running until PRD is complete")
    glog.console.print(f"Engine: {engine_display}")
    glog.console.print(
        f"PRD: [cyan]{cfg.prd_id}[/cyan] ({cfg.prd_run_dir})"
    )

    parts: list[str] = []
    if cfg.skip_tests:
        parts.append("no-tests")
    if cfg.skip_lint:
        parts.append("no-lint")
    if cfg.dry_run:
        parts.append("dry-run")
    if cfg.sequential:
        parts.append("sequential")
    else:
        parts.append(f"parallel:{cfg.max_parallel}")
    if cfg.branch_per_task:
        parts.append("branch-per-task")
    if cfg.run_branch:
        parts.append(f"run-branch:{cfg.run_branch}")
    if cfg.create_pr:
        parts.append("create-pr")
    if cfg.max_iterations > 0:
        parts.append(f"max:{cfg.max_iterations}")

    if parts:
        glog.console.print(f"Mode: [yellow]{' '.join(parts)}[/yellow]")

    glog.console.print("[bold]============================================[/bold]")
