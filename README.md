# meta-harness

A reflective analysis tool for Claude Code. It reads your Claude Code session
logs, identifies recurring quality and efficiency patterns, and proposes
configuration changes — which you review and accept or reject.

Think of it as a feedback loop: Claude Code works on your repo, meta-harness
watches how those sessions go, and suggests improvements to how Claude Code
is configured.

## How it works

1. **Evaluate** — An evaluator agent reads recent session logs and identifies
   patterns (e.g., tool-call loops, repeated mistakes, missed context).
2. **Propose** — A proposer agent reads the evaluation and the knowledge base,
   then drafts concrete configuration changes with rationale.
3. **Author** — An author agent takes each proposal and produces an actual
   git diff, or honestly reports that it can't.
4. **Review** — You see a plain-markdown batch of proposals with terminal
   diffs. Mark each one Accept, Reject, or Defer.
5. **Commit** — Accepted diffs are merged; all decisions are recorded for
   future context.

No scalar grades. No rankings. Evidence-based observations only.

## Requirements

- Python 3.11+
- git
- An Anthropic API key (for the evaluator, proposer, and author agents)

## Installation

### Quick start

```bash
git clone <this-repo>
cd meta_harness
./scripts/setup.sh
```

This installs meta-harness in editable (dev) mode with test dependencies,
verifies the installation, and runs the test suite.

For production installs (no test dependencies):

```bash
./scripts/setup.sh --prod
```

### Manual installation

```bash
pip install -e ".[dev]"    # editable + tests
# or
pip install .              # production
```

### Verify

```bash
meta-harness status
# → {"initialized": false}   (expected for a fresh repo)
```

## Usage

### CLI

meta-harness has three subcommands:

```bash
# Run a reflective review pass over recent sessions
meta-harness review --range "last 7 days"
meta-harness review --range "last week"
meta-harness review --range "2026-04-01 to 2026-04-07"

# Check knowledge base state
meta-harness status

# Manually trigger a maintenance pass
meta-harness maintenance
```

#### Common options

| Option | Subcommand | Description |
|--------|-----------|-------------|
| `--range <range>` | review | Date range for session window |
| `--resume <run_id>` | review | Resume a paused or crashed run from Phase 7 |
| `--verbose` | review | Stream agent output and tool-call traces |
| `--repo <path>` | all | Target repo (defaults to current directory) |

#### First run

On first invocation in any repo, meta-harness automatically initializes:

- Creates `.meta-harness/` directory with the knowledge base layout
- Creates the `meta-harness/decisions` git branch (your working branch stays active)
- Writes `config.yaml` with sensible defaults

No manual setup needed — just run `meta-harness review`.

#### Resuming a run

If a run is interrupted (you closed the terminal, crashed, etc.):

```bash
meta-harness review --resume <run_id>
```

This re-opens the proposal batch from where you left off. Pending proposals
from interrupted runs are also surfaced automatically on the next fresh run.

### As a Claude Code skill

To register meta-harness as slash commands in a repo:

```bash
./scripts/install-skill.sh /path/to/your/repo
```

This creates three skills you can invoke from Claude Code:

```
/meta-harness-review last 7 days     — run a reflective pass
/meta-harness-status                 — check knowledge base state
/meta-harness-maintenance            — trigger maintenance
```

## Configuration

All configuration lives in `.meta-harness/config.yaml`, auto-created on
first run. Edit it to customize behavior.

### Models

```yaml
models:
  evaluator: claude-sonnet-4-6    # reads sessions, identifies patterns
  proposer: claude-opus-4-6      # plans changes (hardest reasoning task)
  author: claude-sonnet-4-6      # writes git diffs
```

The proposer defaults to Opus because it needs the deepest reasoning to
prioritize across gaps and draft non-obvious proposals. Evaluator and
author use Sonnet for cost efficiency.

### Maintenance thresholds

```yaml
maintenance:
  trigger_thresholds:
    new_sessions: 10       # sessions since last maintenance
    new_decisions: 5       # decisions committed
    new_gap_records: 3     # new gaps identified
    days_since_last: 7     # max days without maintenance
```

Maintenance runs automatically when any threshold is exceeded. It
regenerates the summary layer, transitions stale gaps, and reconciles
vocabulary. It's idempotent — safe to run manually at any time.

### Stale gap handling

```yaml
stale_gap_threshold_sessions: 30
```

Gap records that haven't been observed in this many sessions are transitioned
to "stale" status. They're still in the knowledge base but deprioritized.

### Forced novelty

```yaml
forced_novelty:
  probability: 0.20                # 20% chance of exploratory proposal
  null_baseline_probability: 0.01  # 1% chance of null-result proposal
```

To avoid getting stuck in local optima, the proposer occasionally generates
an exploratory proposal targeting an under-examined region, or a null
baseline (proposing no change, to calibrate expectations).

### Window warnings

```yaml
window_warnings:
  small_window_threshold_sessions: 3
  large_window_threshold_sessions: 50
```

Warns if the session window is too small (insufficient data) or too large
(overwhelming the evaluator).

### Logging

```yaml
logging:
  default_verbosity: quiet         # quiet | verbose
  save_full_transcripts: true      # save agent transcripts to .meta-harness/runs/
```

## Knowledge base layout

meta-harness stores all state in `.meta-harness/` at your repo root:

```
.meta-harness/
  config.yaml            # configuration (edit this)
  gaps/                  # gap records (one JSON per pattern)
  archive/               # configuration history (one JSON per state)
  summary/               # regenerable markdown pages (not authoritative)
    index.md
    gap-kinds/
    archive-entries/
    session-clusters/
    decision-lineages/
  runs/                  # per-run artifacts (evaluator/proposer/author output)
  maintenance.log        # append-only log of maintenance passes
```

Decisions are tracked on a separate git branch (`meta-harness/decisions`),
providing a full audit trail via standard git tooling (`git log`, `git show`).

Proposal diffs live on temporary branches (`meta-harness/proposal/<id>`)
that are merged on acceptance or deleted on rejection.

### What's safe to delete

- `summary/` — fully regenerable, run `meta-harness maintenance` to rebuild
- `runs/` — historical artifacts, safe to prune old runs
- Never delete `gaps/`, `archive/`, or `config.yaml` — these are canonical state

## Architecture

```
Session logs (read-only)
        |
        v
   [ Evaluator ]  — identifies patterns, no grades
        |
        v
   [ Proposer ]   — plans changes, reads canonical layers only
        |
        v
   [ Author ]     — writes diffs or reports honest failure
        |
        v
   Proposal batch (markdown + terminal diffs)
        |
        v
   [ Human review ]  — Accept / Reject / Defer per proposal
        |
        v
   Decision records committed to meta-harness/decisions branch
```

Key design principles:

- **No scalar grades** — observations are categorical, not scored
- **Append-only knowledge base** — records are never deleted
- **Summary layer is not authoritative** — agents read canonical gap/decision
  records, not summary pages
- **Idempotent maintenance** — running twice produces byte-identical state
- **Agent context isolation** — each agent gets a fresh API session; state
  is shared via disk (JSON, git), never in-memory
- **Plain markdown for human review** — no tables, no decorative formatting

## Development

### Running tests

```bash
python3.11 -m pytest tests/ -v
```

### Project structure

```
src/meta_harness/
  cli.py                  # CLI entry point (review, status, maintenance)
  storage/
    knowledge_base.py     # Phase 1 setup, directory layout
    gap_record.py         # Gap record CRUD, schema validation
    decision_record.py    # Decision schema, status transitions
    decisions_git.py      # Git branch/commit ops for decisions
    archive_entry.py      # Archive entry lifecycle
    session_logs.py       # Session log reader, date filtering
    summary_layer.py      # Summary page generation
  processes/
    run_loop.py           # Phases 0-9 orchestration
    maintenance.py        # Threshold triggers, reconciliation
  agents/
    evaluator.py          # Session analysis agent
    proposer.py           # Proposal generation agent
    author.py             # Diff authoring agent
```

### Spec and docs

The full technical spec lives in `docs/spec/`, organized bottom-up:

- `01-data-structures/` — schemas for gap records, proposals, decisions, etc.
- `02-storage/` — knowledge base, session logs, decisions git, summary layer
- `03-agents/` — evaluator, proposer, author behavior contracts
- `04-processes/` — run loop phases, maintenance
- `05-interfaces/` — CLI, skill invocation, human review format
- `06-cross-cutting/` — invariants, deferred features, scope boundaries

## License

See LICENSE file.
