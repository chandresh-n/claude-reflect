# `src/` — Implementation

This is the earmarked folder for the claude-reflect Python package. Claude Code
should put all implementation code under `src/claude_reflect/`.

## What lives here

The claude-reflect ships as a pip-installable Python package with a CLI
(`claude-reflect`). Per `docs/IMPLEMENTATION.md`:

- **Python** for orchestration, agent invocation, knowledge-base mutations
  with transactional semantics, and any cross-component coordination.
- **Bash** for high-volume file I/O and git operations (lives under
  `scripts/`, called from Python via `subprocess` where appropriate).
- Python 3.11+.
- Agents (evaluator, proposer, author) invoked via the Anthropic Agent SDK.

## Suggested package layout

The spec does not prescribe file-level Python layout. A reasonable starting
shape, derived from `docs/spec/` and `docs/IMPLEMENTATION.md`:

```
src/claude_reflect/
├── __init__.py
├── cli.py                       # `claude-reflect` entry point (review, status, maintenance, fixtures)
├── config.py                    # load/validate .claude-reflect/config.yaml
├── records/                     # JSON read/write for canonical records
│   ├── gap_record.py            # spec: docs/spec/01-data-structures/gap-record.md
│   ├── decision_record.py       # spec: docs/spec/01-data-structures/decision-record.md
│   ├── archive_entry.py         # spec: docs/spec/01-data-structures/archive-entry.md
│   ├── proposal.py              # spec: docs/spec/01-data-structures/proposal.md
│   └── evaluator_output.py      # spec: docs/spec/01-data-structures/evaluator-output.md
├── storage/
│   ├── knowledge_base.py        # spec: docs/spec/02-storage/knowledge-base.md
│   ├── session_logs.py          # spec: docs/spec/02-storage/session-logs.md
│   ├── decisions_git.py         # spec: docs/spec/02-storage/decisions-git.md
│   └── summary_layer.py         # spec: docs/spec/02-storage/summary-layer.md
├── agents/
│   ├── evaluator.py             # spec: docs/spec/03-agents/evaluator.md
│   ├── proposer.py              # spec: docs/spec/03-agents/proposer.md
│   └── author.py                # spec: docs/spec/03-agents/author.md
├── processes/
│   ├── run_loop.py              # spec: docs/spec/04-processes/run-loop.md
│   └── maintenance.py           # spec: docs/spec/04-processes/maintenance.md
├── interfaces/
│   ├── skill_invocation.py      # spec: docs/spec/05-interfaces/skill-invocation.md
│   └── human_review.py          # spec: docs/spec/05-interfaces/human-review.md
└── fixtures/
    └── generator.py             # `claude-reflect fixtures generate` (synthetic JSONL session logs)
```

## Implementation order

Follow the order pinned down in `docs/IMPLEMENTATION.md` (section
"Implementation order"):

1. Knowledge base directory structure and setup script
2. Gap record read/write
3. Decision record read/write and git operations
4. Archive entry read/write
5. Session log reading utilities
6. Summary layer storage and index regeneration
7. Maintenance process
8. Evaluator agent
9. Proposer agent
10. Author agent
11. Run loop orchestration
12. CLI and skill invocation

Each step is bounded enough to fit in a single Claude Code context. Each step's
spec file is named in `docs/IMPLEMENTATION.md`.

## Constraints worth restating

From `docs/IMPLEMENTATION.md` (section "Implementation cautions"):

- No scalar grades anywhere. No quality scores, effort scores, priority numbers.
- Agent context isolation. Each agent invocation = fresh SDK session.
  Communication between agents goes through disk, never shared in-memory state.
- Summary layer is not authoritative. The proposer reads gap-record JSON, not
  summary pages, when it needs current state.
- Maintenance must be idempotent. Two runs back-to-back must produce identical
  state.
- Knowledge base is append-only. Records are never deleted; only specific
  fields update (per the schemas in `docs/spec/01-data-structures/`).
- The proposal-batch markdown is plain. No fancy tables or decorative elements.
- v1 crash recovery is simple. Resume only from Phase 7 (post-author,
  awaiting human review). Discard partial pre-Phase-7 runs.

## Where supporting material lives

- `docs/PRD.pdf` — vision (the *why*)
- `docs/spec/` — contracts and invariants (the *what*)
- `docs/IMPLEMENTATION.md` — implementation context (the *how*)
- `tests/` — earmarked for unit, integration, and fixture-based tests
- `scripts/` — earmarked for bash setup and git helpers
- `file_navigation.md` (workspace root) — index across everything
