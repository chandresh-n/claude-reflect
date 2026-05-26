# claude-reflect

**Status: v0.1 alpha.** Working end-to-end, but expect rough edges. Schemas
and CLI flags may shift before v1.

A reflective analysis tool for [Claude Code](https://claude.com/claude-code).
It reads your Claude Code session logs, identifies recurring quality and
efficiency patterns, and proposes configuration changes — which you review
and accept or reject.

Think of it as a feedback loop. Claude Code works on your repo. claude-reflect
watches how those sessions go. It then suggests improvements to how Claude
Code is configured — your `CLAUDE.md`, hooks, skills, and settings.

No scalar grades. No rankings. Categorical observations only.

---

## How it works

1. **Evaluate** — reads recent session logs and identifies patterns
   (tool-call loops, repeated mistakes, missed context, etc.).
2. **Propose** — drafts concrete configuration changes with rationale.
3. **Author** — produces a git diff for each proposal, or honestly reports
   it can't.
4. **Review** — you get a plain-markdown batch of proposals with diffs. Mark
   each Accept, Reject, or Defer.
5. **Commit** — accepted diffs are merged; all decisions are recorded for
   future context.

State lives under `.claude-reflect/` at your repo root. Decisions live on a
separate git branch (`claude-reflect/decisions`) — a full audit trail
through standard git tooling.

---

## Requirements

- **Claude Code** installed and authenticated (`claude` on PATH, signed in).
- **Python 3.11+** and pip.
- **git**.

No separate Anthropic API key is needed. claude-reflect uses your existing
Claude Code OAuth session through `claude -p`.

---

## Install

There are two ways to install claude-reflect: as a Claude Code plugin
(recommended), or as a standalone CLI.

### Option A — Claude Code plugin (recommended)

```bash
git clone https://github.com/chandresh-n/claude-reflect.git
```

Then in Claude Code:

```
/plugin install /absolute/path/to/claude-reflect
/claude-reflect:setup
```

The setup command installs the Python backend that the plugin's commands
shell out to. After that you have four commands:

- `/claude-reflect:setup` — install or upgrade the Python backend
- `/claude-reflect:review` — run a reflective pass over recent sessions
- `/claude-reflect:status` — report knowledge-base state
- `/claude-reflect:maintenance` — manually trigger maintenance

### Option B — standalone CLI

```bash
git clone https://github.com/chandresh-n/claude-reflect.git
cd claude-reflect
./scripts/setup.sh
```

The setup script verifies Python and pip, installs claude-reflect in
editable mode, and runs the test suite. Use `--prod` to skip dev
dependencies and the test run.

Either install path produces the same `claude-reflect` shell command:

```bash
claude-reflect --help
claude-reflect status
claude-reflect review --range "last 7 days"
claude-reflect maintenance
```

---

## First run

In any repo where you'd like to start the feedback loop:

```bash
claude-reflect review --range "last 7 days"
```

On first invocation in a repo, claude-reflect automatically initializes:

- Creates `.claude-reflect/` with the knowledge-base layout
- Creates the `claude-reflect/decisions` git branch (your working branch
  stays active)
- Writes `config.yaml` with sensible defaults

It then collects recent session logs, runs the evaluator/proposer/author
pipeline, and presents a proposal batch you can review interactively.

See [docs/USAGE.md](docs/USAGE.md) for the full walkthrough — date ranges,
session selection, resuming interrupted runs, and reading the output.

---

## Configuration

All configuration lives in `.claude-reflect/config.yaml`, auto-created on
first run. The defaults are sensible — edit only when you want to change
behavior.

Key knobs:

- **`models.*`** — which Claude models the evaluator, proposer, and author
  agents use. Heavier reasoning (proposer) defaults to Opus; cheaper passes
  default to Sonnet.
- **`maintenance.trigger_thresholds`** — when maintenance auto-runs
  (sessions, decisions, gaps, time since last).
- **`stale_gap_threshold_sessions`** — when a gap is considered stale and
  deprioritized.
- **`forced_novelty.*`** — probability of exploratory proposals to avoid
  local optima.

Full reference in [docs/USAGE.md](docs/USAGE.md#configuration).

---

## What lives where

```
.claude-reflect/
  config.yaml         # configuration (edit this)
  gaps/               # gap records — canonical, append-only
  archive/            # configuration history — canonical, append-only
  summary/            # regenerable markdown summaries (not authoritative)
  runs/               # per-run artifacts
  maintenance.log     # maintenance pass log
```

Safe to delete: `summary/`, `runs/`. Never delete: `gaps/`, `archive/`,
`config.yaml`.

---

## Design principles

- **No scalar grades** — observations are categorical, not scored.
- **Append-only knowledge base** — records are never deleted.
- **Summary layer is not authoritative** — agents read canonical records.
- **Idempotent maintenance** — running twice produces byte-identical state.
- **Agent context isolation** — every agent invocation is a fresh session;
  state is shared through disk, never in-memory.
- **Plain markdown for human review** — no tables, no decorative formatting.

---

## Docs

- [docs/USAGE.md](docs/USAGE.md) — end-to-end usage walkthrough
- [docs/spec/](docs/spec/) — full technical spec (data structures,
  agents, processes, interfaces, invariants)

---

## Development

```bash
python3.11 -m pytest tests/ -v
```

617 tests covering unit and integration. All integration tests mock agent
invocations — no live API calls. Live-pipeline runs are not part of the
default test suite.

---

## License

MIT — see [LICENSE](LICENSE).
