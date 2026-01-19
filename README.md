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

## Requirements

- One of: Claude Code CLI, OpenCode CLI, Codex CLI, or Cursor (`agent` in PATH)
- `yq` (YAML parsing)
- `jq`
- Optional: `gh` (PRs), `bc` (cost estimates)

## Setup

```bash
# From your project root
mkdir -p scripts/gralph
cp /path/to/gralph/gralph.sh scripts/gralph/
chmod +x scripts/gralph/gralph.sh

# Install required skills for the selected engine
./scripts/gralph/gralph.sh --init
```

## Usage

```bash
# 1. Create PRD with prd-id (use /prd skill)
# 2. Run gralph (parallel by default)
./scripts/gralph/gralph.sh --opencode

# Run sequentially instead (ralph-based)
./scripts/gralph/gralph.sh --opencode --sequential

# Limit parallelism
./scripts/gralph/gralph.sh --opencode --max-parallel 2

# Resume a previous run
./scripts/gralph/gralph.sh --opencode --resume my-feature
```

## Configuration

| Flag | Description |
|------|-------------|
| `--sequential` | Run tasks one at a time (default: parallel) |
| `--max-parallel N` | Max concurrent agents (default: 3) |
| `--resume PRD-ID` | Resume a previous run |
| `--create-pr` | Create PRs instead of auto-merge |
| `--dry-run` | Preview only |

## PRD Format

PRD.md must include a `prd-id` line:

```markdown
# PRD: My Feature

prd-id: my-feature

## Introduction
...
```

GRALPH generates `tasks.yaml` automatically from PRD.md.

## Artifacts

Each PRD run creates `artifacts/prd/<prd-id>/`:
- `PRD.md` - Copy of the PRD
- `tasks.yaml` - Generated task list
- `progress.txt` - Progress notes
- `reports/<TASK_ID>.json` - Task reports
- `reports/<TASK_ID>.log` - Task logs

## Workflow

1. Create PRD.md with `prd-id: your-feature` (use /prd skill)
2. Run `./scripts/gralph/gralph.sh --opencode`
3. GRALPH creates `artifacts/prd/<prd-id>/` with tasks.yaml
4. Tasks run in parallel using DAG scheduler
5. Re-run anytime to resume (auto-detects existing run)
6. Use `--resume <prd-id>` to resume a different PRD

## Engines

- `--opencode`
- `--claude`
- `--cursor`
- `--codex`

## Skills

GRALPH uses these skills:
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
