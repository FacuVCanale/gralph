"""GRALPH CLI — drop-in replacement for the shell scripts.

Installed as ``gralph`` console_script via pipx / pip.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click

from gralph import __version__
from gralph.config import Config, DEFAULT_PROVIDERS
from gralph.io_utils import read_text, write_text


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


def _dedupe_keep_order(values: tuple[str, ...] | list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _parse_providers_option(raw: str) -> list[str]:
    if not raw:
        return []

    providers = [item.strip().lower() for item in raw.split(",")]
    if any(not item for item in providers):
        raise click.BadParameter(
            "Provider list cannot contain empty values (example: --providers claude,codex).",
            param_hint="--providers",
        )

    unknown = [item for item in providers if item not in DEFAULT_PROVIDERS]
    if unknown:
        allowed = ", ".join(DEFAULT_PROVIDERS)
        invalid = ", ".join(_dedupe_keep_order(unknown))
        raise click.BadParameter(
            f"Unknown provider(s): {invalid}. Valid providers: {allowed}.",
            param_hint="--providers",
        )

    duplicates: list[str] = []
    seen: set[str] = set()
    for item in providers:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
    if duplicates:
        raise click.BadParameter(
            f"Duplicate provider(s): {', '.join(duplicates)}.",
            param_hint="--providers",
        )

    return providers


def _resolve_cli_engine_and_providers(
    engine_flags: tuple[str, ...],
    providers_raw: str,
) -> tuple[str, list[str]]:
    selected_engines = _dedupe_keep_order(engine_flags)

    if len(selected_engines) > 1:
        raise click.UsageError(
            "Conflicting engine flags selected. Use only one of "
            "--claude/--opencode/--codex/--cursor/--gemini, or use --providers."
        )

    providers = _parse_providers_option(providers_raw)

    if providers and selected_engines:
        raise click.UsageError(
            "Cannot combine --providers with an engine flag. Choose one approach."
        )

    if providers:
        return providers[0], providers

    if selected_engines:
        engine = selected_engines[0]
        return engine, [engine]

    return "claude", list(DEFAULT_PROVIDERS)


@click.group(
    cls=GralphGroup,
    invoke_without_command=True,
    context_settings=CONTEXT_SETTINGS,
)
@click.option("--claude", "engine_flags", flag_value="claude", multiple=True, help="Use Claude Code (default)")
@click.option("--opencode", "engine_flags", flag_value="opencode", multiple=True, help="Use OpenCode")
@click.option("--codex", "engine_flags", flag_value="codex", multiple=True, help="Use Codex CLI")
@click.option("--cursor", "engine_flags", flag_value="cursor", multiple=True, help="Use Cursor agent")
@click.option("--gemini", "engine_flags", flag_value="gemini", multiple=True, help="Use Gemini CLI")
@click.option("--agent", "engine_flags", flag_value="cursor", multiple=True, hidden=True)
@click.option("--providers", default="", help="Comma-separated providers (e.g. claude,codex)")
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
    engine_flags: tuple[str, ...],
    providers: str,
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
    engine_name, provider_list = _resolve_cli_engine_and_providers(engine_flags, providers)

    cfg = Config(
        ai_engine=engine_name,
        providers=provider_list,
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
@click.option("--no-questions", is_flag=True, help="Skip clarifying questions; infer defaults and note in Open Questions (single run).")
@click.pass_context
def prd(ctx: click.Context, description: str, output: str, no_questions: bool) -> None:
    """Generate a PRD from a feature description.

    By default, the AI asks 3-5 clarifying questions first; you answer (e.g. 1A, 2C),
    then the PRD is generated. Use --no-questions to skip and infer defaults.

    \b
    EXAMPLES:
      gralph prd "Add user authentication with OAuth"
      gralph prd --no-questions "Implement dark mode"
      gralph --codex prd -o PRD.md "Refactor payment flow"
    """
    from gralph import log as glog

    # Inherit engine from parent context
    parent_params = ctx.parent.params if ctx.parent else {}
    parent_engine_flags = tuple(parent_params.get("engine_flags", ()))
    parent_providers = parent_params.get("providers", "")
    engine_name, _ = _resolve_cli_engine_and_providers(parent_engine_flags, parent_providers)
    verbose = parent_params.get("verbose", False)
    skills_url = parent_params.get("skills_url", "")

    glog.set_verbose(verbose)

    cfg = Config(
        ai_engine=engine_name,
        verbose=verbose,
        skills_base_url=skills_url,
    )

    _run_prd_generation(cfg, description, output, no_questions=no_questions)


def _run_prd_generation(
    cfg: Config, description: str, output_path: str, *, no_questions: bool = False
) -> None:
    """Run an AI engine to generate a PRD from a feature description."""
    from gralph import log as glog
    from gralph.engines.registry import get_engine
    from gralph.prd import extract_prd_id, slugify

    invocation_dir = Path.cwd()
    engine = get_engine(cfg.ai_engine)
    err = engine.check_available()
    if err:
        glog.error(err)
        sys.exit(1)

    skill_path = _find_prd_skill(cfg.ai_engine)
    if skill_path:
        skill_content = read_text(skill_path)
        skill_instruction = f"""Follow these instructions for creating the PRD:\n\n{skill_content}"""
        glog.debug(f"Using PRD skill: {skill_path}")
    else:
        glog.warn("PRD skill not found; using built-in prompt. Run 'gralph --init' to install skills.")
        skill_instruction = ""

    tasks_dir = invocation_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    if not output_path:
        write_path_abs = tasks_dir / "prd-temp.md"
    else:
        write_path_abs = (invocation_dir / output_path).resolve()
    save_path_str = str(write_path_abs)

    if no_questions:
        _run_prd_single(cfg, engine, invocation_dir, description, save_path_str, output_path, tasks_dir, write_path_abs)
        return

    # Interactive default: phase 1 — get clarifying questions
    glog.info(f"Asking clarifying questions with {cfg.ai_engine}…")
    questions_prompt = f"""{skill_instruction}

Feature request from the user:
{description}

OUTPUT ONLY 3-5 CLARIFYING QUESTIONS (Step 1 in the skill). Use the format with numbered questions and lettered options (A, B, C, D). Do NOT write the PRD yet. Do NOT create or modify any files — output your response only in your reply. After the last question, output a blank line and then this exact line: ---END_QUESTIONS---"""

    result1 = _run_engine_with_rate_limit_retry(
        cfg,
        engine,
        questions_prompt,
        cwd=invocation_dir,
        stage="clarifying questions",
    )
    questions_text = result1.text
    if "---END_QUESTIONS---" in questions_text:
        questions_text = questions_text.split("---END_QUESTIONS---")[0].strip()
    questions_text = questions_text.strip()

    if not questions_text and result1.error:
        glog.error(f"Failed to get questions: {result1.error}")
        sys.exit(1)

    if questions_text:
        glog.console.print("[bold]Clarifying questions:[/bold]")
        glog.console.print(questions_text)
        glog.console.print()
        if sys.stdin.isatty():
            user_answers = click.prompt(
                "Enter your answers (e.g. 1A, 2C, 3B). Add notes after a comma or on next line if needed",
                default="",
                show_default=False,
            ).strip()
        else:
            glog.warn("Not a TTY; skipping input. Generating PRD with inferred defaults.")
            user_answers = ""
    else:
        glog.warn("No questions returned; generating PRD with inferred defaults.")
        user_answers = ""

    # Phase 2 — generate PRD incorporating answers
    prompt2 = _build_prd_phase2_prompt(
        skill_instruction=skill_instruction,
        description=description,
        questions_text=questions_text,
        user_answers=user_answers,
        save_path_str=save_path_str,
    )

    _run_prd_single(
        cfg, engine, invocation_dir, description, save_path_str, output_path, tasks_dir, write_path_abs, prompt=prompt2
    )


def _build_prd_phase2_prompt(
    *,
    skill_instruction: str,
    description: str,
    questions_text: str,
    user_answers: str,
    save_path_str: str,
) -> str:
    """Build phase-2 PRD prompt with full Q&A context for one-shot engines."""
    clarifications = ""
    if questions_text:
        clarifications = (
            "Clarifying questions that were asked:\n"
            f"{questions_text.strip()}\n\n"
        )

    if user_answers:
        answers_block = (
            "User's answers to clarifying questions:\n"
            f"{user_answers.strip()}\n\n"
        )
        answer_rules = (
            "Interpret answer codes by number+letter. "
            "Example: 1C means option C for question 1. "
            "Prioritize the user's explicit choices over inferred defaults.\n\n"
        )
    else:
        answers_block = "(No answers provided.)\n\n"
        answer_rules = (
            "No answers were provided. Infer reasonable defaults and note assumptions in "
            "the Open Questions section.\n\n"
        )

    return f"""{skill_instruction}

Feature request from the user:
{description}

{clarifications}{answers_block}{answer_rules}IMPORTANT RULES:
1. Incorporate the user's answers into the PRD.
2. The PRD MUST start with `# PRD: <Title>` (you choose a short, descriptive title).
3. On the next non-blank line after the title, add `prd-id: <id>` where <id> is a short, URL-safe identifier you choose (lowercase, hyphens only, e.g. provider-fallback-rate-limit). Keep it under 50 characters.
4. Do NOT ask more questions — generate the full PRD now.
5. Save the PRD to: {save_path_str}
6. Do NOT implement anything — only create the PRD file."""


def _run_prd_single(
    cfg: Config,
    engine: "EngineBase",
    invocation_dir: Path,
    description: str,
    save_path_str: str,
    output_path: str,
    tasks_dir: Path,
    write_path_abs: Path,
    *,
    prompt: str | None = None,
) -> None:
    """Run a single PRD generation (no questions). Uses prompt if given, else builds no-questions prompt."""
    from gralph import log as glog
    from gralph.prd import extract_prd_id, slugify

    if prompt is None:
        skill_path = _find_prd_skill(cfg.ai_engine)
        if skill_path:
            skill_content = read_text(skill_path)
            skill_instruction = f"""Follow these instructions for creating the PRD:\n\n{skill_content}"""
            glog.debug(f"Using PRD skill: {skill_path}")
        else:
            skill_instruction = ""
        prompt = f"""Follow these instructions for creating the PRD:\n\n{skill_instruction}

Feature request from the user:
{description}

IMPORTANT RULES:
1. The PRD MUST start with `# PRD: <Title>` (you choose a short, descriptive title).
2. On the next non-blank line after the title, add `prd-id: <id>` where <id> is a short, URL-safe identifier you choose (lowercase, hyphens only, e.g. provider-fallback-rate-limit). Keep it under 50 characters.
3. Do NOT ask clarifying questions interactively — infer reasonable defaults and note assumptions in the Open Questions section.
4. Save the PRD to: {save_path_str}
5. Do NOT implement anything — only create the PRD file."""

    glog.info(f"Generating PRD with {cfg.ai_engine}…")
    glog.info(f"Output: {write_path_abs}")

    result = _run_engine_with_rate_limit_retry(
        cfg,
        engine,
        prompt,
        cwd=invocation_dir,
        stage="PRD generation",
    )

    out = write_path_abs
    if not out.is_file():
        details = (result.text or "").strip()
        if _looks_like_prd_text(details):
            serialized = details if details.endswith("\n") else f"{details}\n"
            write_text(out, serialized)
            glog.warn("Engine returned PRD text but did not write the file. Saved output locally.")

    if out.is_file():
        prd_id = extract_prd_id(out)
        if not prd_id:
            prd_id = slugify(description)
            glog.warn(f"PRD created at {out} but missing prd-id. Adding it…")
            _inject_prd_id(out, prd_id)
        if not output_path:
            safe_id = slugify(prd_id)
            if safe_id != prd_id:
                _normalize_prd_id_in_file(out, safe_id)
            final_path = tasks_dir / f"prd-{safe_id}.md"
            if final_path.resolve() != out.resolve():
                # os.replace overwrites destination if it exists (required on Windows)
                os.replace(out, final_path)
                out = final_path
            prd_id = safe_id
        glog.success(f"PRD created: {out} (prd-id: {prd_id})")
    else:
        glog.error(f"Engine failed to create {out}")
        if result.error:
            glog.error(f"Error: {result.error}")
            if cfg.ai_engine == "cursor" and "agent" in result.error.lower() and "not found" in result.error.lower():
                glog.console.print(
                    "[dim]Tip: Run this command from Cursor's integrated terminal, or install the Cursor CLI and add it to PATH: https://cursor.com/docs/cli/installation[/dim]"
                )
        else:
            details = (result.text or "").strip()
            if details and details != "Task completed":
                single_line = " ".join(details.split())
                if len(single_line) > 500:
                    single_line = single_line[:500].rstrip() + "..."
                glog.error(f"Engine output: {single_line}")
        sys.exit(1)


def _run_engine_with_rate_limit_retry(
    cfg: Config,
    engine: "EngineBase",
    prompt: str,
    *,
    cwd: Path,
    stage: str,
    max_attempts: int = 3,
) -> "EngineResult":
    """Run an engine call, retrying short rate-limit bursts with exponential backoff."""
    from gralph import log as glog

    attempt = 1
    delay_s = 5
    try:
        result = engine.run_sync(prompt, cwd=cwd)
    except KeyboardInterrupt:
        glog.warn(f"Interrupted by user during {stage}.")
        raise click.Abort() from None

    if _looks_like_user_interrupt_result(result):
        glog.warn(f"Interrupted by user during {stage}.")
        raise click.Abort()

    while attempt < max_attempts and _looks_like_rate_limit_error(result.error):
        if result.return_code == 0 and _has_meaningful_engine_text(result.text):
            glog.warn(
                f"{cfg.ai_engine} reported a rate-limit-like message during {stage}, "
                "but returned usable output. Skipping retry."
            )
            break
        attempt += 1
        glog.warn(
            f"{cfg.ai_engine} reported rate limit during {stage}. Retrying in {delay_s}s "
            f"(attempt {attempt}/{max_attempts})..."
        )
        try:
            time.sleep(delay_s)
        except KeyboardInterrupt:
            glog.warn(f"Interrupted by user during {stage}.")
            raise click.Abort() from None
        delay_s = min(delay_s * 2, 30)
        try:
            result = engine.run_sync(prompt, cwd=cwd)
        except KeyboardInterrupt:
            glog.warn(f"Interrupted by user during {stage}.")
            raise click.Abort() from None

        if _looks_like_user_interrupt_result(result):
            glog.warn(f"Interrupted by user during {stage}.")
            raise click.Abort()

    return result


def _looks_like_rate_limit_error(msg: str) -> bool:
    if not msg:
        return False
    lower = msg.lower()
    patterns = [
        "rate limit",
        "rate_limit",
        "you've hit your limit",
        "quota",
        "429",
        "too many requests",
    ]
    return any(p in lower for p in patterns)


def _has_meaningful_engine_text(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped and stripped != "Task completed")


def _looks_like_user_interrupt_result(result: "EngineResult") -> bool:
    interrupt_codes = {130, -130, -1073741510, 3221225786}
    if result.return_code in interrupt_codes:
        return True

    msg = " ".join(
        p for p in [result.error or "", result.text or ""] if p
    ).lower()
    patterns = [
        "keyboardinterrupt",
        "interrupted by user",
        "operation canceled",
        "operation cancelled",
        "sigint",
        "ctrl-c",
    ]
    return any(p in msg for p in patterns)


def _looks_like_prd_text(text: str) -> bool:
    if not text:
        return False
    stripped = text.lstrip()
    if stripped.startswith("# PRD:"):
        return True
    head = "\n".join(stripped.splitlines()[:8]).lower()
    return "prd-id:" in head


def _find_prd_skill(engine_name: str) -> Path | None:
    """Locate the PRD skill file for the given engine."""
    from gralph.config import resolve_repo_root

    repo = resolve_repo_root()
    home = Path.home()
    bundled = repo / "skills/prd/SKILL.md"

    candidates: list[Path] = []
    match engine_name:
        case "claude":
            candidates = [
                repo / ".claude/skills/prd/SKILL.md",
                bundled,
                home / ".claude/skills/prd/SKILL.md",
            ]
        case "codex":
            candidates = [
                repo / ".codex/skills/prd/SKILL.md",
                bundled,
                home / ".codex/skills/prd/SKILL.md",
            ]
        case "opencode":
            candidates = [
                repo / ".opencode/skill/prd/SKILL.md",
                bundled,
                home / ".config/opencode/skill/prd/SKILL.md",
            ]
        case "cursor":
            candidates = [
                repo / ".cursor/rules/prd.mdc",
                repo / ".cursor/commands/prd.md",
                bundled,
            ]
        case "gemini":
            candidates = [
                repo / ".gemini/skills/prd/SKILL.md",
                bundled,
                home / ".gemini/skills/prd/SKILL.md",
            ]
        case _:
            candidates = [bundled]

    for c in candidates:
        if c.is_file():
            return c
    return None


def _inject_prd_id(prd_file: Path, slug: str) -> None:
    """Insert a prd-id line after the title if missing."""
    content = read_text(prd_file)
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

    write_text(prd_file, "".join(lines))


def _normalize_prd_id_in_file(prd_file: Path, safe_id: str) -> None:
    """Replace existing prd-id line with the normalized (URL-safe) id."""
    content = read_text(prd_file)
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("prd-id:"):
            lines[i] = f"prd-id: {safe_id}\n"
            break
    write_text(prd_file, "".join(lines))


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
        has_dirty_worktree,
        dirty_worktree_entries,
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

    if has_dirty_worktree():
        entries = [
            entry for entry in dirty_worktree_entries()
            if not entry.startswith("?? ")
        ]
        if not entries:
            entries = []
    else:
        entries = []

    if entries:
        glog.error(
            "Working tree is dirty on the run branch. Commit/stash changes before running gralph."
        )
        glog.console.print(f"[dim]Dirty entries: {', '.join(entries[:8])}[/dim]")
        sys.exit(1)
    # ── Banner ───────────────────────────────────────────────────
    _show_banner(cfg)

    # ── Init artifacts dir ───────────────────────────────────────
    init_artifacts_dir(cfg)

    # ── Create progress.txt if missing ───────────────────────────
    progress = Path(cfg.artifacts_dir or ".") / "progress.txt"
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

    show_summary(
        cfg,
        runner.iteration,
        total_input_tokens=runner.total_input_tokens,
        total_output_tokens=runner.total_output_tokens,
        branches=runner.completed_branches,
        provider_usage=runner.provider_usage,
    )
    notify_done()


def _try_extract_tasks_yaml_from_result(text: str, output: Path) -> bool:
    """If result.text contains valid tasks.yaml structure, write it. Return True if written."""
    if not text or "branchName:" not in text or "tasks:" not in text:
        return False
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "branchName:" in line:
            yaml_content = "\n".join(lines[i:]).strip()
            if "tasks:" in yaml_content:
                output.parent.mkdir(parents=True, exist_ok=True)
                write_text(output, yaml_content)
                return True
    return False


def _run_metadata_agent(engine: object, prd_path: Path, output: Path) -> None:
    """Run the metadata agent to generate tasks.yaml from a PRD."""
    from gralph import log as glog
    from gralph.engines.base import EngineBase

    assert isinstance(engine, EngineBase)

    # Inline PRD content so all engines receive it (some don't support @path)
    prd_content = read_text(prd_path)

    prompt = f"""Convert this PRD to tasks.yaml format.

PRD content:
---
{prd_content}
---

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

    cwd = Path.cwd()
    result = engine.run_sync(prompt, cwd=cwd)

    if not output.is_file():
        # Fallback: some engines output YAML in result.text instead of writing to disk
        _try_extract_tasks_yaml_from_result(result.text, output)
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
        "gemini": "[green]Gemini CLI[/green]",
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

