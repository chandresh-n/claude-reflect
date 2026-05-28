# claude-reflect

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

```bash
git clone https://github.com/chandresh-n/claude-reflect.git
cd claude-reflect
./scripts/setup.sh
```

The setup script checks Python 3.11+ / pip / git, then:

1. **Tries a direct install first** (`pip install -e .` against your
   system Python). If your Python allows it, that's the end of the story
   and `claude-reflect` is on your PATH.
2. **Falls back to a venv if the direct install fails** — most commonly
   because modern Python distributions (Homebrew, Debian/Ubuntu)
   externally-manage the system site-packages (PEP 668). The fallback
   creates a venv at `.venv/` inside the clone, installs into it, and
   adds a `claude-reflect` alias to `~/.bashrc` and `~/.zshrc` so the
   command is available globally in any new shell.

Pass `--prod` to skip dev dependencies and the test run.

After install, open a new shell (or `source ~/.zshrc` / `~/.bashrc`) and:

```bash
claude-reflect --help
claude-reflect status
claude-reflect maintenance
```

`claude-reflect review` has three ways to pick which sessions to analyze:

```bash
# By date range — natural phrases or explicit ranges
claude-reflect review --range "yesterday"
claude-reflect review --range "2026-04-01 to 2026-04-07"

# By specific session id (repeatable)
claude-reflect review --session-id <session_id>

# Interactive picker over recent sessions
claude-reflect review --pick
```

---

## First run

### Try it safely first (no real sessions, no setup)

The repo ships synthetic session logs under `fixtures/sessions/`. Point a
review at them to exercise the full evaluator → proposer → author pipeline
without touching your real Claude Code history:

```bash
claude-reflect review --fixtures-dir fixtures/sessions/
```

This is the recommended way to see what claude-reflect does before running
it against your own work. All knowledge-base state is written under
`fixtures/sessions/.claude-reflect/` (gitignored), isolated from your real
KB. Add `--no-cache` to force fresh agent calls; add `--verbose` to stream
agent output.

> Heads up: a review makes paid Claude calls (via your Claude Code session)
> for the evaluator, proposer, and author agents. The fixtures run above is
> the cheapest way to try the tool — each fixture is kept small on purpose.

### Run it against your own repo

In any repo where you'd like to start the feedback loop, run a review. The
session-selection modes are the same as shown under [Install](#install)
above (`--range`, `--session-id`, `--pick`). For example:

```bash
claude-reflect review --range "last 7 days"
```

On first invocation in a repo, claude-reflect automatically initializes:

- Creates `.claude-reflect/` with the knowledge-base layout
- Creates the `claude-reflect/decisions` git branch (your working branch
  stays active)
- Writes `config.yaml` with sensible defaults
- Prompts an **interactive model picker** (one question per agent) — press
  Enter to accept each default. In a non-interactive shell the picker is
  skipped and defaults are used. See
  [docs/USAGE.md](docs/USAGE.md#models) for details and `--pick-models`.

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

- **`models.*`** — which Claude models each agent uses. The evaluator and
  proposer default to Opus for the deepest reasoning; the high-volume
  per-turn pass (`stage_1a`) and the author default to Sonnet for cost
  efficiency. Set on first run via the interactive picker (or
  `--pick-models`).
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
