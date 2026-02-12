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
- Stalled agent detection and automatic cleanup
- External failure detection (network, permissions, rate limits)
- Support for Claude Code, OpenCode, Codex, Cursor, and Gemini CLI
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

The installer clones gralph and installs it as a Python CLI via [pipx](https://pipx.pypa.io/). Restart your terminal after installing.

**Update:**

```bash
gralph --update
```

## Requirements

- **Python 3.10+**
- **git**
- One of: Claude Code CLI, OpenCode CLI, Codex CLI, Cursor (`agent` in PATH), or Gemini CLI (`gemini` in PATH)
- Optional: `gh` (for creating PRs)

### Gemini CLI Setup

- Install Gemini CLI: https://github.com/google-gemini/gemini-cli
- Ensure `gemini` is available in your `PATH`
- Complete Gemini CLI auth/config before running `gralph --gemini`

## Quick Start

```bash
# 1. Install skills in your project
cd my-project
gralph --init

# 2. Generate a PRD from a feature description
gralph prd "Add user authentication with OAuth"

# Or create PRD.md manually (must include: prd-id: my-feature)

# 3. Run gralph
gralph
```

## Usage

```bash
# Run with default configs
gralph

# Run with a specific engine
gralph --opencode
gralph --cursor
gralph --codex
gralph --gemini

# Generate a PRD
gralph prd "Add dark mode toggle"
gralph --codex prd -o PRD.md "Refactor payment flow"

# Run sequentially
gralph --sequential

# Limit parallelism
gralph --max-parallel 2

# Dry run (preview without executing)
gralph --dry-run

# Resume a previous run
gralph --resume my-feature

# Use a specific PRD file
gralph --prd features/auth.md

# Skip tests and linting
gralph --fast

# Create PRs per task instead of auto-merge
gralph --create-pr --draft-pr

# Tune timeouts
gralph --stalled-timeout 900 --external-fail-timeout 600
```

## Configuration

### Engine

| Flag | Description |
|------|-------------|
| `--claude` | Use Claude Code (default) |
| `--opencode` | Use OpenCode |
| `--cursor` | Use Cursor agent |
| `--codex` | Use Codex CLI (default uses full write access for autonomous runs) |
| `--gemini` | Use Gemini CLI |
| `--opencode-model MODEL` | Override OpenCode model (default: `opencode/minimax-m2.1-free`) |

For Codex, GRALPH defaults to `--dangerously-bypass-approvals-and-sandbox` so agents can edit files reliably in worktrees. Set `GRALPH_CODEX_SAFE=1` (or `GRALPH_CODEX_DANGEROUS=0`) to force sandboxed mode.

### Execution

| Flag | Description |
|------|-------------|
| `--sequential` | Run tasks one at a time (default: parallel) |
| `--max-parallel N` | Max concurrent agents (default: 3) |
| `--max-iterations N` | Stop after N iterations, 0 = unlimited (default: 0) |
| `--max-retries N` | Max retries per task (default: 3) |
| `--retry-delay N` | Seconds between retries (default: 5) |
| `--external-fail-timeout N` | Timeout in seconds for running tasks on external failure (default: 300) |
| `--stalled-timeout N` | Seconds of inactivity before killing a stalled agent (default: 600) |
| `--dry-run` | Preview task plan without executing |

### Git / PRs

| Flag | Description |
|------|-------------|
| `--branch-per-task` | Create a new git branch for each task |
| `--base-branch NAME` | Base branch for task branches |
| `--create-pr` | Create a PR per task (requires `gh` CLI) |
| `--draft-pr` | Create PRs as drafts |

### Quality

| Flag | Description |
|------|-------------|
| `--no-tests` | Skip tests |
| `--no-lint` | Skip linting |
| `--fast` | Skip both tests and linting |

### PRD / Resume

| Flag | Description |
|------|-------------|
| `--prd FILE` | PRD file path (default: `PRD.md`) |
| `--resume PRD-ID` | Resume a previous run by prd-id |

### Setup

| Flag | Description |
|------|-------------|
| `--init` | Install missing skills for the current engine |
| `--skills-url URL` | Override skills base URL |
| `--update` | Update gralph to the latest version |
| `--version` | Show version |
| `-v, --verbose` | Show debug output |

## PRD Generation

Generate a PRD from a feature description using the `prd` subcommand:

```bash
gralph prd "Add user authentication with OAuth"
gralph --codex prd "Implement dark mode toggle"
gralph --gemini prd "Improve test reliability and CI logs"
gralph prd -o PRD.md "Refactor payment flow"
```

| Option | Description |
|--------|-------------|
| `DESCRIPTION` | Feature description (required, positional) |
| `-o, --output FILE` | Output file path (default: `tasks/prd-<slug>.md`) |

The subcommand inherits the engine from the parent (`--claude`, `--opencode`, `--codex`, `--cursor`, `--gemini`).

## PRD Format

PRD.md must include a `prd-id` line:

```markdown
# PRD: My Feature

prd-id: my-feature

## Introduction
...
```

GRALPH generates `tasks.yaml` automatically from PRD.md.

## tasks.yaml Format

```yaml
version: 1
branchName: gralph/feature-name
tasks:
  - id: TASK-001
    title: "First task description"
    completed: false
    dependsOn: []
    mutex: []
    touches: []
    mergeNotes: ""
  - id: TASK-002
    title: "Second task"
    completed: false
    dependsOn: ["TASK-001"]
    mutex: ["db-migrations"]
    touches: ["src/db/schema.py"]
```

| Field | Description |
|-------|-------------|
| `id` | Unique task ID (e.g. `TASK-001`) |
| `title` | Short description of the task |
| `completed` | Whether the task is done |
| `dependsOn` | List of task IDs that must complete first |
| `mutex` | Shared resources to lock during execution |
| `touches` | Expected files to create or modify |
| `mergeNotes` | Hints for merge conflict resolution |

Valid mutex names: `db-migrations`, `lockfile`, `router`, `global-config`, and `contract:*` (dynamic pattern).

## Workflow

1. Install gralph (see [Install](#install))
2. `cd` into your project and run `gralph --init`
3. Generate a PRD: `gralph prd "your feature"` (or create `PRD.md` manually with `prd-id: your-feature`)
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

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/
```

## Contributing

PRs and issues welcome. Keep changes small and update tests/docs when adding features.

## License

MIT

## Credits

Inspired by Ralph, which pioneered autonomous AI coding loops.
