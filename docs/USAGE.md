# Using claude-reflect

This is the end-to-end usage guide. For a quick orientation, read the
top-level [README](../README.md) first.

---

## Concepts in two minutes

claude-reflect runs over your **Claude Code session logs** — the JSONL
transcripts of what you and Claude did during prior sessions. It does
**not** observe live sessions and does not modify your project files
without a reviewed proposal.

A **run** has three agent phases, then a human-review phase:

1. **Evaluator** reads recent sessions and identifies recurring patterns
   (tool-call loops, misreads, repeated detours, missed conventions). It
   writes **gap records** to the knowledge base.
2. **Proposer** reads canonical gap records plus historical decisions and
   drafts **proposals** — concrete config changes with rationale.
3. **Author** turns each proposal into an actual git diff, or honestly
   reports it can't.
4. **Human review** — you see a plain-markdown batch of proposals with
   diffs and mark each one Accept / Reject / Defer.

Accepted diffs are merged into your working branch. Every decision —
accept, reject, defer — is committed to a separate `claude-reflect/decisions`
git branch as a durable audit trail.

---

## Per-repo setup

claude-reflect operates on a per-repo basis. State lives in
`.claude-reflect/` at the repo root and never escapes that directory.

The first time you run a review in a repo, claude-reflect initializes
itself automatically — you don't need a separate init step.

```bash
cd /path/to/your/repo
claude-reflect review --range "last 7 days"
```

If you'd rather check before running, `claude-reflect status` reports
whether the knowledge base is initialized and how many records exist.

---

## Running a review

The `review` subcommand has three ways to pick which sessions to analyze:

### By date range

```bash
claude-reflect review --range "last 7 days"
claude-reflect review --range "last week"
claude-reflect review --range "2026-04-01 to 2026-04-07"
```

Natural phrases (`last week`, `yesterday`, `last 30 days`) and explicit
ranges both work.

### By specific session id

```bash
claude-reflect review --session-id <session_id>
```

Useful for replaying a single notable session.

### Interactive pick

```bash
claude-reflect review --pick
```

Shows a list of recent sessions and lets you pick one or more.

### Common options

| Option            | Description                                                              |
| ----------------- | ------------------------------------------------------------------------ |
| `--range`         | Date range for the session window (default selection mode).              |
| `--session-id`    | Target a single session by id.                                           |
| `--pick`          | Interactive picker over recent sessions.                                 |
| `--resume <id>`   | Resume a paused or crashed run from Phase 7 (post-author, pre-review).   |
| `--verbose`       | Stream agent output and tool-call traces while running.                  |
| `--repo <path>`   | Target repo (defaults to current directory).                             |

### What the run produces

Each run writes two files under `.claude-reflect/runs/`:

- `<run_id>-batch.md` — the human-review batch (plain markdown, with
  inline diffs). This is the file you actually review.
- `<run_id>.json` — serialized run state (phase, pending proposals,
  decisions) used for `--resume` and crash recovery.

Author diffs live on temporary git branches (`claude-reflect/proposal/<id>`),
not as files in the run directory. The review batch shows each diff
inline by running `git diff` against the proposal branch.

If `logging.save_full_transcripts: true`, raw agent transcripts are
written under `.claude-reflect/logs/` (separate from the per-run dir).

---

## Resuming an interrupted run

If a run is interrupted between the author phase and your review (closed
terminal, crash, etc.), resume it with:

```bash
claude-reflect review --resume <run_id>
```

The `run_id` is printed at the start of every run and is also the
directory name under `.claude-reflect/runs/`. Pending proposals from
interrupted runs also surface automatically on the next fresh run.

Crash recovery is intentionally minimal in v0.1: only post-Phase-7
runs (awaiting your review) are resumable. Partial pre-Phase-7 runs are
discarded on the next invocation.

---

## Maintenance

Maintenance regenerates the summary layer, transitions stale gap records,
and reconciles the gap-kind vocabulary. It runs automatically when the
thresholds in `config.yaml` are exceeded, but you can also trigger it
manually:

```bash
claude-reflect maintenance
```

Maintenance is **idempotent** — running it twice in a row produces
byte-identical state. Safe to invoke at any time.

---

## The git branches

claude-reflect uses two git branch namespaces in your repo:

- **`claude-reflect/decisions`** — append-only history of every accept,
  reject, and defer. One commit per decision. Browse with normal git
  tooling: `git log claude-reflect/decisions`, `git show <hash>`.
- **`claude-reflect/proposal/<id>`** — temporary per-proposal branches
  holding the author's diff. Merged on accept, deleted on reject.

Your working branch is never touched without an explicit acceptance.

---

## Configuration

All configuration is in `.claude-reflect/config.yaml`, auto-created on
first run. The file is your only edit surface — the tool reads from there
and never overwrites it.

### Models

```yaml
models:
  evaluator: claude-sonnet-4-6    # reads sessions, identifies patterns
  proposer:  claude-opus-4-6      # plans changes (hardest reasoning)
  author:    claude-sonnet-4-6    # writes git diffs
```

The proposer defaults to Opus because it does the deepest reasoning. The
evaluator and author default to Sonnet for cost efficiency. Override per
agent if your priorities differ.

> Note for v0.1: model selection is a static default per agent. A
> per-run model selector is on the roadmap.

### Maintenance thresholds

```yaml
maintenance:
  trigger_thresholds:
    new_sessions: 10       # sessions since last maintenance
    new_decisions: 5       # decisions committed since last maintenance
    new_gap_records: 3     # new gaps identified
    days_since_last: 7     # max days without maintenance
```

Maintenance runs when **any** threshold is exceeded.

### Stale gap handling

```yaml
stale_gap_threshold_sessions: 30
```

Gap records not observed for this many sessions are transitioned to
`stale` status. They remain in the knowledge base but are deprioritized
by the proposer.

### Forced novelty

```yaml
forced_novelty:
  probability: 0.20                # 20% chance of an exploratory proposal
  null_baseline_probability: 0.01  # 1% chance of a null-result proposal
```

To avoid getting stuck in local optima, the proposer occasionally
generates an exploratory proposal aimed at an under-examined area, or a
null baseline (proposing no change, to calibrate expectations).

### Window warnings

```yaml
window_warnings:
  small_window_threshold_sessions: 3
  large_window_threshold_sessions: 50
```

Warns if the session window selected is too small (insufficient signal)
or too large (overwhelms the evaluator).

### Logging

```yaml
logging:
  default_verbosity: quiet         # quiet | verbose
  save_full_transcripts: true      # save agent transcripts to runs/
```

---

## Knowledge base layout

```
.claude-reflect/
  config.yaml            # configuration (edit this)
  gaps/                  # gap records (one JSON per pattern)
  archive/               # configuration history (one JSON per state)
  summary/               # regenerable markdown pages (not authoritative)
    index.md
    gap-kinds/
    archive-entries/
    session-clusters/
    decision-lineages/
  runs/                  # per-run artifacts
  maintenance.log        # append-only maintenance log
```

### Safe to delete

- `summary/` — regenerable; rebuild via `claude-reflect maintenance`.
- `runs/` — historical artifacts, safe to prune old runs.

### Never delete

- `gaps/`, `archive/`, `config.yaml` — canonical state.

---

## Architecture summary

```
Session logs (read-only)
        |
        v
   [ Evaluator ]   — identifies patterns, writes gap records
        |
        v
   [ Proposer  ]   — drafts proposals from canonical layers
        |
        v
   [ Author    ]   — writes diffs or reports honest failure
        |
        v
   Proposal batch (plain markdown + diffs)
        |
        v
   [ Human review ]   — Accept / Reject / Defer per proposal
        |
        v
   Decision records committed to claude-reflect/decisions branch
```

Key invariants enforced by the implementation:

- **No scalar grades** — schemas reject score-like fields anywhere.
- **Append-only knowledge base** — gap and archive records mutate only the
  specific fields the spec permits; never deleted.
- **Summary layer is not authoritative** — the proposer always reads
  canonical gap/decision JSON, never summary pages.
- **Idempotent maintenance** — enforced by run-twice tests.
- **Agent context isolation** — each agent invocation is a fresh Claude
  session; communication is through disk only.

Full spec: [docs/spec/](spec/).

---

## Troubleshooting

**`claude-reflect: command not found`**
The pip user-scripts directory may not be on PATH. Fall back to
`python3.11 -m claude_reflect.cli <subcommand>`, or add the directory
output by `python3.11 -m site --user-base`/`bin` to your PATH.

**`claude` not on PATH**
claude-reflect shells out to `claude -p` to drive its agents. Install
[Claude Code](https://claude.com/claude-code) and authenticate it by
running `claude` interactively once (it'll walk you through `/login`).

**A run hangs at the evaluator phase**
Re-run with `--verbose` to see agent output and tool-call traces. If
the underlying Claude session is the issue, kill the run and let
`--resume` skip ahead (only works post-Phase-7; otherwise restart).

**Tests fail with import errors**
Reinstall the package: `python3.11 -m pip install -e ".[dev]"` from
the repo root.
