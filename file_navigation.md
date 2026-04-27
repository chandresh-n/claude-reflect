# File navigation

Index for navigating this workspace. `CLAUDE.md` at the root is the
auto-loaded entry point that every Claude Code session reads first; this
file is the deeper index it points to. Read `CLAUDE.md` first if you
opened this manually.

This workspace holds the spec and implementation guidance for the
**meta-harness for Claude Code** — a Python + bash CLI that runs reflective
passes over Claude Code session logs and proposes configuration changes.
Implementation is 0-1 from this brief.

---

## TL;DR for Claude Code

0. **`CLAUDE.md`** at the workspace root is auto-loaded. It states the
   per-step procedure (two-session TDD + verification subagent) and the
   cross-cutting cautions that must stay live every session.
1. Read `docs/PRD.pdf` once for the *why* (vision).
2. Read `docs/spec/README.md`, then `docs/spec/00-glossary.md`.
3. Walk `docs/spec/` bottom-up: `01-data-structures/` → `02-storage/` →
   `03-agents/` → `04-processes/` → `05-interfaces/` → `06-cross-cutting/`.
4. Read `docs/IMPLEMENTATION.md` end-to-end for the *how* (language, layout,
   model defaults, error handling, implementation order, cautions).
5. **Read `docs/PLAN.md`** — the frozen breakdown of the 12 implementation
   steps, each with a named verification gate (HARD, SOFT, or SPLIT) and a
   dependency DAG. **Each Claude Code session implements exactly one step,
   and each step is two implementation sessions plus one verification
   session.**
6. Implement under `src/meta_harness/` per the layout in `src/README.md`.
7. Tests under `tests/`. Bash helpers under `scripts/`.

Conflict resolution:
- Spec vs. `docs/IMPLEMENTATION.md` → spec wins; update IMPLEMENTATION.md.
- Spec vs. `docs/PLAN.md` → spec wins; update PLAN.md.
- `docs/IMPLEMENTATION.md` vs. `docs/PLAN.md` → IMPLEMENTATION.md wins on
  *implementation decisions* (language, models, layout); PLAN.md wins on
  *slicing and gating* (which step, in what order, with what gate).
- Anything vs. this navigation guide → fix this guide.

---

## Top-level layout

```
meta_harness/
├── CLAUDE.md                  ← auto-loaded by Claude Code at session start
├── file_navigation.md         ← you are here (deeper index)
├── docs/                      ← all source-of-truth documentation
│   ├── PRD.pdf                ← vision (the why)
│   ├── IMPLEMENTATION.md      ← implementation context (the how)
│   ├── PLAN.md                ← frozen 12-step breakdown with gates and DAG
│   └── spec/                  ← technical spec (the what)
├── src/                       ← EARMARKED for the Python package
│   ├── README.md              ← package layout, implementation order, cautions
│   └── meta_harness/          ← put package code here
├── tests/                     ← EARMARKED for unit, integration, fixture tests
│   ├── README.md
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/                   ← EARMARKED for bash helpers (setup, git, file walks)
│   └── README.md
└── _archive/                  ← original source zip bundles, kept for reference
    ├── files.zip
    └── meta-harness-spec.zip
```

Folders marked **EARMARKED** are empty (or contain only the README). Their
READMEs explain what Claude Code should put there and which spec files
govern each piece.

---

## `CLAUDE.md` — the auto-loaded entry point

Sits at the workspace root. Claude Code reads it automatically at the
start of every session. It encodes:

- The reading order (this file, `docs/PLAN.md`, `docs/IMPLEMENTATION.md`,
  `docs/spec/`, `docs/PRD.pdf`).
- The **per-step procedure**: Session A writes the failing gate against
  the spec only; Session B (fresh context) implements until green;
  a **verification subagent** in a third fresh context confirms the
  implementation matches the gate criteria with no implementer-context
  bleed. The subagent's sign-off is the formal completion of the step.
- The **cross-cutting cautions** (no scalar grades, agent context
  isolation, summary layer is not authoritative, idempotent maintenance,
  append-only knowledge base, plain markdown for human review, simple
  v1 crash recovery).
- The conflict-resolution order (spec wins; IMPLEMENTATION.md wins on
  implementation choices; PLAN.md wins on slicing and gating).

Update `CLAUDE.md` whenever the per-step procedure or the cross-cutting
cautions change. It is the most expensive file in the repo to keep
incorrect.

---

## `docs/` — source-of-truth documentation

### `docs/PRD.pdf`
The vision PRD. Answers *why* the meta-harness exists. Read once, up front.
Not authoritative for contracts; the spec is.

### `docs/IMPLEMENTATION.md`
Implementation guidance: language and runtime, agent invocation via the
Anthropic Agent SDK, default models, token tracking, on-disk layout for
`.meta-harness/`, git branch structure, CLI shape, configuration file,
logging, error handling, testing strategy, fixture generation,
documentation deliverables, **implementation order** (12 numbered steps),
and **implementation cautions** (constraints Claude Code may drift on).
Read alongside the spec.

### `docs/PLAN.md`
The frozen breakdown for the 0-1 build. Slices the 12 implementation steps
into spec-bounded subtasks, each scoped to a single fresh Claude Code
session, with a named verification gate and explicit dependencies. Encodes
the gate strategy (HARD for steps 1–7, SOFT for 8–10, SPLIT for 11 and 12),
the dependency DAG, and the cross-cutting cautions that must stay live
across every session. **Each Claude Code session implements exactly one
step.** Read this after `docs/IMPLEMENTATION.md`.

### `docs/spec/` — technical spec

Bottom-up: data structures → storage → agents → processes → interfaces →
cross-cutting concerns. Each file follows the same internal structure:
Role · Inputs · Outputs · Schema/Behavior · Invariants · Explicitly
excluded · Cross-references.

#### `docs/spec/README.md`
Spec overview and reading guide. The directory layout it describes is
preserved verbatim under `docs/spec/`.

#### `docs/spec/00-glossary.md`
Definitions used throughout. Terms are bolded on first use in each spec
file; definitions live here.

#### `docs/spec/01-data-structures/` — schemas for records and outputs
- `gap-record.md` — recurring quality-or-effort inefficiency pattern
  across sessions; primary unit the proposer prioritizes on.
- `evaluator-output.md` — structured report of a session window;
  per-turn observations, pass classifications, gap observations.
  Contains no scalar grades and no recommendations.
- `decision-record.md` — committed record of a proposal plus the human's
  response; canonical temporal record on the decisions git branch.
- `proposal.md` — single candidate change to the configuration; atomic
  unit of meta-harness output.
- `archive-entry.md` — one configuration state the system has inhabited;
  one entry per accepted proposal.

#### `docs/spec/02-storage/` — how data is held
- `knowledge-base.md` — overall persistent state in the target repo;
  four layers organized by authoritativeness.
- `session-logs.md` — Claude Code's native session record, read as
  ground truth, never modified.
- `decisions-git.md` — the `meta-harness/decisions` git branch; audit
  trail; provenance via standard git tooling.
- `summary-layer.md` — LLM-maintained markdown pages synthesizing views
  over canonical layers. Regenerable. **Not authoritative** for
  proposer judgments.

#### `docs/spec/03-agents/` — entities that read and write
- `evaluator.md` — reads sessions, produces structured observations;
  no grading, no ranking, no recommendations.
- `proposer.md` — reads evaluator output and the knowledge base;
  produces proposal intents (rationale + authoring addendum).
- `author.md` — takes one proposer intent, produces a concrete git diff
  on a proposal branch, or reports honest failure.

#### `docs/spec/04-processes/` — orchestration and maintenance
- `run-loop.md` — orchestrates a single invocation; phases 0–9.
- `maintenance.md` — keeps the summary layer in sync, reconciles
  vocabulary, transitions stale state. Idempotent.

#### `docs/spec/05-interfaces/` — exposed to the human
- `skill-invocation.md` — the meta-harness as a Claude Code skill
  wrapping the CLI.
- `human-review.md` — Phase 6/7 of the run loop; markdown batch
  document opened in the human's editor with terminal-visible diffs.
  **Boring formatting on purpose.**

#### `docs/spec/06-cross-cutting/` — system-wide concerns
- `invariants.md` — invariants spanning multiple components.
- `deferred.md` — features the spec acknowledges but defers.
- `scope-boundaries.md` — what is in scope, out of scope, and where the
  line is. Architectural commitments unlikely to change.

---

## `src/` — earmarked for the implementation

The meta-harness Python package goes under `src/meta_harness/`. See
`src/README.md` for:

- The split between Python (orchestration, structured records) and bash
  (high-volume file I/O, git ops).
- A suggested package layout mapped one-to-one against spec files.
- The 12-step implementation order from `docs/IMPLEMENTATION.md`.
- The "Implementation cautions" — constraints worth re-reading every
  context: no scalar grades, agent context isolation, summary layer is
  not authoritative, idempotent maintenance, append-only knowledge
  base, plain markdown for human review, simple v1 crash recovery.

---

## `tests/` — earmarked for tests

Layered strategy from `docs/IMPLEMENTATION.md`: unit, integration with
fixtures, integration with real session logs, behavioral, manual
evaluation. See `tests/README.md` for fixture pattern types and an
explicit reminder to assert maintenance idempotency.

---

## `scripts/` — earmarked for bash helpers

Setup, git operations, and file walking. Called from Python via
`subprocess`. See `scripts/README.md` for the split principle and a
list of likely scripts mapped to the spec files that govern them.

---

## `_archive/`

Original source zip bundles (`files.zip` and `meta-harness-spec.zip`),
kept for traceability. Not needed for implementation; safe to ignore.

---

## What is **not** in this workspace yet

These are produced by Claude Code during implementation, not provided up
front:

- `pyproject.toml` / `setup.py` / `setup.cfg` — the package will need
  packaging metadata for `pip install meta-harness`.
- `README.md` at the package root (per `docs/IMPLEMENTATION.md` §
  "Documentation deliverables").
- `docs/quickstart.md`, `docs/configuration.md`, `docs/architecture.md`
  (per the same section).
- The Claude Code skill wrapper around the CLI.

When Claude Code creates these, update this navigation guide so it stays
accurate.

---

## Conflict resolution

- Spec vs. `docs/IMPLEMENTATION.md` → spec wins; update IMPLEMENTATION.md.
- Spec vs. PRD → spec wins for *what* and *how*; PRD covers *why* only.
- Anything vs. this navigation guide → fix this guide.
