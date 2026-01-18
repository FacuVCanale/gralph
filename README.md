# gralph — Parallel AI coding runner (inspired by Ralph)

![gralph](assets/gralph.jpeg)

gralph is a fast, parallel AI coding runner. It was inspired by Ralph (credit where it's due), but Ralph felt too slow for real-world dev speed. gralph is an attempt to parallelize coding agents to satisfy one of the biggest developer needs today: writing AI slop fast, very fast.

## Overview

gralph reads tasks, schedules them with dependencies and mutexes, runs multiple agents in isolated git worktrees, and produces actionable artifacts (logs + reports). It aims to trade single-agent depth for throughput while keeping runs debuggable.

## Project status

This repo is in active development. The entrypoint script is currently `ralph.sh` while the project is being migrated/renamed to **gralph**.

## Features

- DAG scheduling with `dependsOn` and `mutex`
- Parallel agents in isolated worktrees
- Task artifacts: JSON reports + logs
- External-failure fail-fast with graceful stop + timeout
- Auto-merge (or PRs) after successful runs
- Supports Claude Code, OpenCode, Codex, or Cursor

## Install

```bash
git clone https://github.com/juanfra/central-ralph.git
cd central-ralph
chmod +x ralph.sh
```

### Requirements

Required:
- One of: [Claude Code CLI](https://github.com/anthropics/claude-code), [OpenCode CLI](https://opencode.ai/docs/), Codex CLI, or [Cursor](https://cursor.com) (`agent` in PATH)
- `jq`

Optional:
- `yq` (only if using YAML task files)
- `gh` (only if using GitHub Issues or `--create-pr`)
- `bc` (cost estimates)

## Skills

gralph uses “skills” as reusable instruction bundles per engine.

Install missing skills for your selected engine:

```bash
./ralph.sh --init
```

Skills currently used:
- `prd`
- `ralph`
- `task-metadata`
- `dag-planner`
- `parallel-safe-implementation`
- `merge-integrator`
- `semantic-reviewer`

## Quickstart

The intended workflow is:
1) Write a PRD (or provide a `tasks.yaml`), 2) run gralph, 3) inspect artifacts/branches, 4) merge/PR as needed.

```bash
./ralph.sh --yaml tasks.yaml --parallel
```

If `tasks.yaml` does not exist, gralph will try to generate it from `PRD.md` automatically.

### Recommended: tasks.yaml v1 (DAG + mutex)

Example:

```yaml
version: 1
tasks:
  - id: SETUP-001
    title: "Initialize project structure and dependencies"
    completed: false
    dependsOn: []
    mutex: ["lockfile"]
  - id: US-001
    title: "Build hero section"
    completed: false
    dependsOn: ["SETUP-001"]
    mutex: []
```

Full schema: `docs/tasks-yaml-v1.md`.

## Usage

```bash
# YAML v1 + parallel run (default max 3 agents)
./ralph.sh --yaml tasks.yaml --parallel

# Use a specific engine
./ralph.sh --opencode --parallel

# Limit parallelism
./ralph.sh --parallel --max-parallel 2

# Run sequentially
./ralph.sh --yaml tasks.yaml
```

## Configuration

Common flags (see `./ralph.sh --help` for the full list):

| Flag | Description |
| --- | --- |
| `--parallel` | Run tasks in parallel |
| `--max-parallel N` | Max concurrent agents (default: 3) |
| `--external-fail-timeout N` | Seconds to wait for running tasks after external failure (default: 300) |
| `--max-retries N` | Retries per task on failure |
| `--retry-delay N` | Delay between retries |
| `--create-pr` | Create PRs instead of auto-merge |
| `--dry-run` | Preview only |

## Artifacts

Each run creates `artifacts/run-YYYYMMDD-HHMM/`:

- `reports/<TASK_ID>.json` (task report)
- `reports/<TASK_ID>.log` (task log)
- `review-report.json` (if reviewer runs)

### Where is the code?

gralph runs tasks in **isolated git worktrees** and commits work to a **branch per task/agent**. Your current working tree will not change until merge/checkout.

To inspect the code for a completed task:
1) Open `artifacts/run-.../reports/<TASK_ID>.json` and copy the `branch`.
2) Checkout that branch:

```bash
git checkout <branch>
```

Or keep your current branch and use a worktree:

```bash
git worktree add ../wt-<task> <branch>
```

## Failure modes (quick)

- If a task fails due to an **external/toolchain** issue (example: install/tool not found/network), gralph will **stop scheduling new work**, wait for running tasks up to `--external-fail-timeout`, then terminate remaining tasks.
- If the scheduler has pending tasks but none are runnable, gralph reports a **deadlock** and prints which tasks are blocked and why.

## Contributing

PRs and issues welcome. Keep changes small, prefer clear logs and reproducible runs. If you add new failure modes or flags, update the README and tests.

## License

MIT

## Credits

gralph is inspired by Ralph, which pioneered the autonomous coding loop and PRD-driven task execution. This project builds on that idea with a focus on parallelism and throughput.
