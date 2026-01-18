# GRALPH

![gralph](assets/gralph.png)

GRALPH is a parallel AI coding runner that executes tasks across multiple agents in isolated git worktrees.

## Overview

GRALPH reads task definitions, schedules them with dependencies and mutexes, and runs multiple agents in parallel. Each task produces artifacts (logs and reports) and commits work to isolated branches.

## Features

- DAG-based task scheduling with dependencies and mutexes
- Parallel execution in isolated git worktrees
- Per-task artifacts (JSON reports and logs)
- Integration branch merging with conflict resolution
- Support for Claude Code, OpenCode, Codex, and Cursor

## Requirements

- One of: Claude Code CLI, OpenCode CLI, Codex CLI, or Cursor (`agent` in PATH)
- `jq`
- Optional: `yq` (YAML task files), `gh` (GitHub Issues/PRs), `bc` (cost estimates)

## Setup

### Option 1: Copy to your project

```bash
# From your project root
mkdir -p scripts/gralph
cp /path/to/gralph/gralph.sh scripts/gralph/
cp /path/to/gralph/prompt.md scripts/gralph/
cp /path/to/gralph/prd.json.example scripts/gralph/
chmod +x scripts/gralph/gralph.sh
```

### Option 2: Install skills globally

```bash
cp -r skills/prd ~/.config/amp/skills/
cp -r skills/ralph ~/.config/amp/skills/
```

## Usage

```bash
# Run with YAML task file (recommended)
./scripts/gralph/gralph.sh --yaml examples/personal-landing/tasks.yaml --parallel

# Run with specific engine
./scripts/gralph/gralph.sh --opencode --parallel

# Limit parallelism
./scripts/gralph/gralph.sh --parallel --max-parallel 2

# Run sequentially
./scripts/gralph/gralph.sh --yaml examples/personal-landing/tasks.yaml
```

## Configuration

| Flag | Description |
|------|-------------|
| `--parallel` | Run tasks in parallel |
| `--max-parallel N` | Max concurrent agents (default: 3) |
| `--external-fail-timeout N` | Seconds to wait after external failure (default: 300) |
| `--create-pr` | Create PRs instead of auto-merge |
| `--dry-run` | Preview only |

## Task Files

GRALPH supports `tasks.yaml` v1 format with dependencies and mutexes:

```yaml
version: 1
tasks:
  - id: SETUP-001
    title: "Initialize project structure"
    completed: false
    dependsOn: []
    mutex: ["lockfile"]
  - id: US-001
    title: "Build hero section"
    completed: false
    dependsOn: ["SETUP-001"]
    mutex: []
```

## Artifacts

Each run creates `artifacts/run-YYYYMMDD-HHMM/`:
- `reports/<TASK_ID>.json` - Task report
- `reports/<TASK_ID>.log` - Task log
- `review-report.json` - Integration review (if enabled)

## Code Location

Tasks run in isolated git worktrees and commit to feature branches. To inspect completed task code:

```bash
# Find branch in task report
cat artifacts/run-*/reports/TASK-ID.json | jq '.branch'

# Checkout the branch
git checkout <branch>
```

## Skills

GRALPH uses skills for reusable instruction bundles. Install missing skills:

```bash
./scripts/gralph/gralph.sh --init
```

Available skills:
- `prd` - Generate PRDs
- `ralph` - Convert PRDs to JSON
- `task-metadata` - Task metadata validation
- `dag-planner` - DAG planning and validation
- `parallel-safe-implementation` - Parallel execution guidelines
- `merge-integrator` - Branch merging
- `semantic-reviewer` - Code review

## Contributing

PRs and issues welcome. Keep changes small and update tests/docs when adding features.

## License

MIT

## Credits

Inspired by Ralph, which pioneered autonomous AI coding loops.