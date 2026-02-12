"""Artifacts, reports, integration, and semantic reviewer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from gralph import log
from gralph.config import Config
from gralph.io_utils import read_text
from gralph.engines.base import EngineBase
from gralph.git_ops import (
    checkout,
    create_branch,
    diff_stat,
    merge_no_edit,
    merge_abort,
    delete_branch,
    conflicted_files,
)
from gralph.tasks.model import TaskFile


def init_artifacts_dir(cfg: Config) -> str:
    """Create a timestamped artifacts directory and set it on *cfg*."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifacts = f"artifacts/run-{ts}"
    Path(artifacts, "reports").mkdir(parents=True, exist_ok=True)
    cfg.artifacts_dir = artifacts
    log.info(f"Artifacts: {artifacts}")
    return artifacts


# ── Integration ──────────────────────────────────────────────────────

def create_integration_branch(base_branch: str) -> str:
    """Create an integration branch from *base_branch*. Returns branch name."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"gralph/integration-{ts}"
    if create_branch(name, base_branch):
        log.info(f"Created integration branch: {name}")
    else:
        checkout(name)
    return name


def merge_branch_with_fallback(
    branch: str,
    task_id: str,
    engine: EngineBase,
    tf: TaskFile,
) -> bool:
    """Merge *branch*, using AI to resolve conflicts if needed."""
    if merge_no_edit(branch):
        return True

    log.warn(f"Conflict merging {branch}, attempting AI resolution…")
    files = conflicted_files()

    task = tf.get_task(task_id)
    merge_notes = task.merge_notes if task else ""

    prompt = f"""Resolve git merge conflicts in these files:

{chr(10).join(files)}

Merge notes from task: {merge_notes}

For each file:
1. Read the conflict markers (<<<<<<< HEAD, =======, >>>>>>>)
2. Combine BOTH changes intelligently
3. Remove all conflict markers
4. Ensure valid syntax

Then run:
git add <files>
git commit --no-edit"""

    result = engine.run_sync(prompt)

    remaining = conflicted_files()
    if remaining:
        log.error(f"AI failed to resolve conflicts in {branch}")
        merge_abort()
        return False

    log.success(f"AI resolved conflicts in {branch}")
    return True


# ── Reviewer ─────────────────────────────────────────────────────────

def run_reviewer_agent(
    cfg: Config,
    engine: EngineBase,
    base_branch: str,
    integration_branch: str,
) -> bool:
    """Run semantic reviewer. Returns ``True`` if no blockers."""
    if not cfg.artifacts_dir or not integration_branch:
        return True

    log.info("Running semantic reviewer…")

    summary = diff_stat(base_branch, integration_branch)

    reports_dir = Path(cfg.artifacts_dir) / "reports"
    reports_text = ""
    if reports_dir.is_dir():
        for rp in reports_dir.glob("*.json"):
            reports_text += f"\n{read_text(rp)}"

    prompt = f"""Review the integrated code changes for issues.

Diff summary:
{summary}

Task reports:
{reports_text}

Check for:
1. Type mismatches between modules
2. Broken imports or references
3. Inconsistent patterns (error handling, naming)
4. Missing exports

Create a file review-report.json with this format:
{{
  "issues": [
    {{"severity": "blocker|critical|warning", "file": "path", "description": "...", "suggestedFix": "..."}}
  ],
  "summary": "Brief overall assessment"
}}

If no issues found, create an empty issues array.
Save to {cfg.artifacts_dir}/review-report.json"""

    engine.run_sync(prompt)

    report_path = Path(cfg.artifacts_dir) / "review-report.json"
    if report_path.is_file():
        try:
            data = json.loads(read_text(report_path))
            blockers = [i for i in data.get("issues", []) if i.get("severity") == "blocker"]
            if blockers:
                log.warn(f"Reviewer found {len(blockers)} blocker(s)")
                return False
            log.success("Review passed (no blockers)")
        except json.JSONDecodeError:
            log.warn("Could not parse review report")

    return True


def generate_fix_tasks(cfg: Config, tf: TaskFile) -> None:
    """Generate FIX-* tasks from blocker issues in the review report."""
    report_path = Path(cfg.artifacts_dir) / "review-report.json"
    if not report_path.is_file():
        return

    try:
        data = json.loads(read_text(report_path))
    except json.JSONDecodeError:
        return

    blockers = [i for i in data.get("issues", []) if i.get("severity") == "blocker"]
    if not blockers:
        return

    log.info("Generating fix tasks from blockers…")
    from gralph.tasks.model import Task

    for i, issue in enumerate(blockers, 1):
        fix_id = f"FIX-{i:03d}"
        desc = issue.get("description", "Fix issue")
        tf.tasks.append(
            Task(
                id=fix_id,
                title=f"Fix: {desc}",
                completed=False,
            )
        )

    log.success("Added fix tasks")


# ── Cost estimation ───────────────────────────────────────────────────

# Per-token pricing (USD) by engine.  Values are rough estimates.
_ENGINE_PRICING: dict[str, tuple[float, float]] = {
    "claude":  (0.000003, 0.000015),   # Claude Sonnet ballpark
    "codex":   (0.000003, 0.000015),   # Codex CLI (OpenAI pricing approx.)
    "gemini":  (0.0000001, 0.0000004), # Gemini 2.5 Flash pricing
}


def _estimate_cost(engine: str, input_tokens: int, output_tokens: int) -> float:
    """Return a rough USD cost estimate for the given engine and token counts."""
    inp_price, out_price = _ENGINE_PRICING.get(engine, (0.000003, 0.000015))
    return (input_tokens * inp_price) + (output_tokens * out_price)


def _coerce_non_negative_int(value: object) -> int:
    """Best-effort conversion for token counters coming from external objects/mocks."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# ── Summary ──────────────────────────────────────────────────────────

def show_summary(
    cfg: Config,
    iteration: int,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    total_actual_cost: str = "0",
    branches: list[str] | None = None,
) -> None:
    """Print the final run summary."""
    total_input_tokens = _coerce_non_negative_int(total_input_tokens)
    total_output_tokens = _coerce_non_negative_int(total_output_tokens)

    log.console.print("")
    log.console.print("[bold]============================================[/bold]")
    log.console.print(f"[green]PRD complete![/green] Finished {iteration} task(s).")
    log.console.print("[bold]============================================[/bold]")
    log.console.print("")
    log.console.print("[bold]>>> Cost Summary[/bold]")

    if cfg.ai_engine == "cursor":
        log.console.print("[dim]Token usage not available (Cursor CLI doesn't expose this data)[/dim]")
    else:
        log.console.print(f"Input tokens:  {total_input_tokens}")
        log.console.print(f"Output tokens: {total_output_tokens}")
        log.console.print(f"Total tokens:  {total_input_tokens + total_output_tokens}")

        if cfg.ai_engine == "opencode" and total_actual_cost != "0":
            log.console.print(f"Actual cost:   ${total_actual_cost}")
        else:
            cost = _estimate_cost(cfg.ai_engine, total_input_tokens, total_output_tokens)
            log.console.print(f"Est. cost:     ${cost:.4f}")

    if branches:
        log.console.print("")
        log.console.print("[bold]>>> Branches Created[/bold]")
        for b in branches:
            log.console.print(f"  - {b}")

    log.console.print("[bold]============================================[/bold]")
