# GRALPH

![gralph](assets/gralph.png)

GRALPH is a parallel AI coding runner that executes tasks across multiple agents in isolated git worktrees.

## Overview

GRALPH reads a PRD, generates tasks with dependencies, and runs multiple agents in parallel using a DAG scheduler. Each task produces artifacts and commits work to isolated branches.

## Features

- DAG-based task scheduling with dependencies and mutexes
- Parallel execution by default (isolated git worktrees)
- Per-PRD run directories with all artifacts
- Automatic resume on re-run
- Support for Claude Code, OpenCode, Codex, and Cursor
- Cross-platform: macOS, Linux, and Windows

## Install

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/frizynn/gralph/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/frizynn/gralph/main/install.ps1 | iex
```

Restart your terminal after installing. Then `gralph` is available globally.

**Update:**

```bash
gralph --update
```

## Requirements

- One of: Claude Code CLI, OpenCode CLI, Codex CLI, or Cursor (`agent` in PATH)
- `yq` (YAML parsing)
- `jq`
- `git`
- Optional: `gh` (PRs), `bc` (cost estimates)

## Quick Start

```bash
# 1. Install skills in your project
cd my-project
gralph --init

# 2. Create a PRD with prd-id (use /prd skill or write one manually)
# PRD.md must include: prd-id: my-feature

# 3. Run gralph (parallel by default)
gralph

# Or with a specific engine
gralph --opencode
```

## Usage

```bash
# Run with default engine (Claude Code)
gralph

# Run with a specific engine
gralph --opencode
gralph --cursor
gralph --codex

# Run sequentially
gralph --sequential

# Limit parallelism
gralph --max-parallel 2

# Dry run (preview without executing)
gralph --dry-run

# Resume a previous run
gralph --resume my-feature

# Skip tests and linting
gralph --fast

# Create PRs per task instead of auto-merge
gralph --create-pr --draft-pr
```

## Configuration

| Flag | Description |
|------|-------------|
| `--claude` | Use Claude Code (default) |
| `--opencode` | Use OpenCode |
| `--cursor` | Use Cursor agent |
| `--codex` | Use Codex CLI |
| `--sequential` | Run tasks one at a time (default: parallel) |
| `--max-parallel N` | Max concurrent agents (default: 3) |
| `--resume PRD-ID` | Resume a previous run |
| `--create-pr` | Create PRs instead of auto-merge |
| `--draft-pr` | Create PRs as drafts |
| `--branch-per-task` | Create a new git branch for each task |
| `--no-tests` | Skip tests |
| `--no-lint` | Skip linting |
| `--fast` | Skip both tests and linting |
| `--dry-run` | Preview only |
| `--init` | Install missing skills for the current engine |
| `--update` | Update gralph to the latest version |
| `-v, --verbose` | Show debug output |

## PRD Format

PRD.md must include a `prd-id` line:

```markdown
# PRD: My Feature

prd-id: my-feature

## Introduction
...
```

GRALPH generates `tasks.yaml` automatically from PRD.md.

## Workflow

1. Install gralph (see [Install](#install))
2. `cd` into your project and run `gralph --init`
3. Create `PRD.md` with `prd-id: your-feature` (use `/prd` skill)
4. Run `gralph` (or `gralph --opencode`, etc.)
5. GRALPH creates `artifacts/prd/<prd-id>/` with tasks.yaml
6. Tasks run in parallel using the DAG scheduler
7. Re-run anytime to resume (auto-detects existing run)
8. Use `--resume <prd-id>` to resume a different PRD

## Artifacts

Each PRD run creates `artifacts/prd/<prd-id>/`:
- `PRD.md` - Copy of the PRD
- `tasks.yaml` - Generated task list
- `progress.txt` - Progress notes
- `reports/<TASK_ID>.json` - Task reports
- `reports/<TASK_ID>.log` - Task logs

## Skills

GRALPH uses these skills (installed with `--init`):
- `prd` - Generate PRDs with prd-id
- `ralph` - Convert PRDs to tasks
- `task-metadata` - Validate tasks.yaml
- `dag-planner` - Plan task execution
- `parallel-safe-implementation` - Safe parallel coding
- `merge-integrator` - Merge branches
- `semantic-reviewer` - Review integrated code

## Contributing

PRs and issues welcome. Keep changes small and update tests/docs when adding features.

## License

MIT

## Credits

Inspired by Ralph, which pioneered autonomous AI coding loops.
