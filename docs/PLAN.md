# Implementation plan

The frozen breakdown for the 0-1 implementation of the meta-harness. Read
this **after** the spec (`docs/spec/`) and `docs/IMPLEMENTATION.md`. This file
specifies *how the work is sliced into units that fit a single Claude Code
session, what the verification gate is for each unit, and the order they
must run in.*

If this file conflicts with the spec, the spec wins. If it conflicts with
`docs/IMPLEMENTATION.md`, IMPLEMENTATION.md wins on implementation
decisions, this file wins on slicing and gating.

---

## Why this file exists

The meta-harness cannot be one-shot. The risk profile of a 0-1 build with
an LLM coding agent is drift, hallucination, and accumulating gaps that
only surface end-to-end. The mitigation is structural:

- **Slice the work into spec-bounded subtasks.** Each subtask is one fresh
  Claude Code session, with one named spec file as primary input and one
  named verification gate as exit criterion.
- **Gate every subtask.** Drift is caught at the boundary, not at
  integration time.
- **Keep contracts on disk.** Communication between subtasks is the spec,
  the JSON record schemas, and git — not shared in-memory state, not
  conversation context.

This file is the operational instantiation of those principles.

---

## Gate strategy (frozen)

- **HARD gate** for steps 1–7 (the deterministic bottom of the stack —
  records, storage, git ops, summary layer, maintenance). The next step is
  not started until the previous step's gate passes. Drift here corrupts
  everything above; we pay the rework cost up front.
- **SOFT gate** for steps 8–10 (the three agents). Each step has a
  fixture-based behavioral gate, but forward motion is allowed on a
  known-issues list because agent quality is iterative — prompts get tuned
  long after the structural code is stable.
- **SPLIT gate** for steps 11 and 12 (run loop, CLI+skill). The
  orchestration plumbing is HARD; the LLM-touching parts inside the
  orchestration are SOFT. Details under each step.

---

## Frozen design decisions

These were debated and resolved before this plan was committed. They are
load-bearing for the breakdown and should not be re-litigated without
re-opening the plan.

1. **Step 4 (archive entry) does not depend on step 3 (decisions+git).**
   The data structure is testable in isolation with a fixture that fakes
   acceptances. The end-to-end "decision causes archive entry" wiring is
   exercised at step 11 (run loop).

2. **Step 9's forced-novelty gate is a unit test on roll logic with a
   mocked RNG, not a live statistical assertion over N agent runs.** The
   statistical version is theater and expensive; the unit test is what
   actually catches a bug.

3. **Step 5 (session log reader) floats off the critical path.** It has no
   `.meta-harness/` dependency. Run any time before step 8.

4. **Parallelism is opportunistic, not a design goal.** The natural
   sequence is mostly serial. Coordinating parallel branches costs more
   than it saves for a single-developer build.

---

## Per-step breakdown

Each step lists: spec input, contract, verification gate, gate type,
dependencies. Steps are numbered to match `docs/IMPLEMENTATION.md` §
"Implementation order".

### Step 1 — Knowledge base & setup script · HARD

- **Spec:** `docs/spec/02-storage/knowledge-base.md`,
  `docs/spec/04-processes/run-loop.md` (Phase 1 only)
- **Contract:** create the `.meta-harness/` directory layout; initialize the
  `meta-harness/decisions` git branch; write a default `config.yaml` with
  every field from `docs/IMPLEMENTATION.md` § "Configuration file"
- **Gate:** unit tests verify the directory layout matches the spec; the
  decisions branch exists and is detached from the active branch; the
  config has every required field with correct defaults; running setup
  twice produces byte-identical state (idempotent)
- **Depends on:** —

### Step 2 — Gap record read/write · HARD

- **Spec:** `docs/spec/01-data-structures/gap-record.md`
- **Contract:** one JSON file per gap under `.meta-harness/gaps/<gap_id>.json`;
  schema validation on read and write; field-level append-only enforcement
  per the spec (specific fields update, others are immutable post-write)
- **Gate:** roundtrip tests; schema validation rejects malformed records;
  append-only enforcement test (delete is impossible through the public
  API; immutable fields cannot be overwritten); kind-vocabulary handling
  matches the spec
- **Depends on:** 1

### Step 3 — Decision record + git ops · HARD

- **Spec:** `docs/spec/01-data-structures/decision-record.md`,
  `docs/spec/02-storage/decisions-git.md`
- **Contract:** commit decisions to `meta-harness/decisions` with structured
  metadata in the commit message header (`proposal_id`, `run_id`, `status`,
  `targeted_gaps`) and the decision JSON in the commit body; create,
  merge, and delete `meta-harness/proposal/<proposal_id>` branches
- **Gate:** commit-message header parses correctly; decision JSON
  roundtrips through the commit body; status transitions
  (`accepted`/`rejected`/`author_failed`) enforced; proposal-branch
  lifecycle exercised end-to-end (create → commit → merge or delete)
- **Depends on:** 1

### Step 4 — Archive entry read/write · HARD

- **Spec:** `docs/spec/01-data-structures/archive-entry.md`
- **Contract:** one JSON file per archive entry under
  `.meta-harness/archive/<entry_id>.json`; active vs. superseded lifecycle
  per the spec; the "exactly one active configuration" invariant holds at
  all times
- **Gate:** roundtrip tests; "exactly one active configuration" invariant
  asserted under concurrent supersession; lifecycle transitions follow
  the spec's allowed paths
- **Depends on:** 1

### Step 5 — Session log reader · HARD

- **Spec:** `docs/spec/02-storage/session-logs.md`
- **Contract:** walk Claude Code's session log directory; parse JSONL;
  filter by date range; expose a session abstraction matching the spec.
  **Read-only** — never modifies session logs.
- **Gate:** tests against synthetic JSONL fixtures (the fixture generator
  from `docs/IMPLEMENTATION.md` § "Fixture generation" feeds these);
  date-range filtering correct on edge cases; static check or audit that
  no code path under this module writes to the session-log directory
- **Depends on:** — *(reads external state, no `.meta-harness/` dependency)*

### Step 6 — Summary layer storage & index regeneration · HARD

- **Spec:** `docs/spec/02-storage/summary-layer.md`
- **Contract:** page kinds, filesystem layout, and index regeneration
  logic per the spec; **not authoritative** — the proposer never reads
  summary pages for state it can read from canonical layers
- **Gate:** regeneration is idempotent (run twice → byte-identical); page
  kinds enumerated correctly; **architectural test asserts no code path
  from the proposer module to summary files** (this is the cross-cutting
  invariant from `docs/IMPLEMENTATION.md` § "Implementation cautions")
- **Depends on:** 2, 3, 4

### Step 7 — Maintenance process · HARD

- **Spec:** `docs/spec/04-processes/maintenance.md`
- **Contract:** threshold-triggered, regenerates the summary layer,
  transitions stale gaps, reconciles kind vocabulary, appends to
  `.meta-harness/maintenance.log`. Idempotent.
- **Gate:** integration test runs maintenance, snapshots state, runs
  maintenance again, asserts byte-identical state; threshold triggers
  tested independently (each of `new_sessions`, `new_decisions`,
  `new_gap_records`, `days_since_last`); stale-gap transition logic
  tested with a fixture; kind-vocabulary reconciliation tested
- **Depends on:** 2, 3, 4, 6

### Step 8 — Evaluator agent · SOFT

- **Spec:** `docs/spec/03-agents/evaluator.md`,
  `docs/spec/01-data-structures/evaluator-output.md`
- **Contract:** reads sessions; produces an evaluator output document
  matching the schema; updates gap records as a side effect; **no scalar
  grades, no recommendations, no rankings**
- **Gate (SOFT):** fixture with a known tool-call-loop session →
  evaluator output validates against schema, contains a gap observation
  of category `tool_call_loop` (or whatever vocabulary the spec defines).
  Forward motion allowed on a known-issues list for prompt drift; track
  drift items in `docs/PROMPT_ITERATION.md` (created when first needed).
- **Depends on:** 2, 5; uses 1, 6 for context (read-only on 6)

### Step 9 — Proposer agent · SOFT

- **Spec:** `docs/spec/03-agents/proposer.md`,
  `docs/spec/01-data-structures/proposal.md`
- **Contract:** reads evaluator output and the full canonical knowledge
  base (not the summary layer for authoritative state); produces a batch
  of proposal intents, each with rationale and authoring addendum;
  honors the forced-novelty probability from `config.yaml`
- **Gate (SOFT):** fixture-fed proposer produces non-empty batch with
  valid schema; each proposal has both rationale and addendum; **unit
  test on the forced-novelty roll logic with a mocked RNG** (asserts the
  roll fires at the right rate without N expensive agent runs)
- **Depends on:** 2, 3, 4, 8

### Step 10 — Author agent · SOFT

- **Spec:** `docs/spec/03-agents/author.md`
- **Contract:** takes one proposer intent → produces a git diff on the
  `meta-harness/proposal/<id>` branch, or returns `author_failed`
  honestly. Never fabricates a diff.
- **Gate (SOFT):** fixture intent → diff that applies cleanly to the
  active configuration branch; "impossible intent" fixture →
  `author_failed` (the test fails if the author fabricates a diff
  instead of failing honestly)
- **Depends on:** 3, 9

### Step 11 — Run loop orchestration · SPLIT (HARD plumbing, SOFT agents-in-loop)

- **Spec:** `docs/spec/04-processes/run-loop.md`
- **Contract:** phases 0–9 sequenced correctly; pending-proposal carry-over
  from previous runs; resume from Phase 7 (post-author, awaiting human
  review); v1 crash recovery — discard partial pre-Phase-7 runs on next
  invocation
- **Gate (SPLIT):**
  - **HARD plumbing gate:** end-to-end integration test against synthetic
    JSONL with **mocked agents producing canned responses**. Asserts
    phase sequence, pending-proposal handling, resume-from-7 works after
    a simulated crash, partial-run discard works.
  - **SOFT agents-in-loop:** running with real agents on real sessions
    produces a coherent batch markdown. This is observed during use, not
    auto-tested.
  - **The HARD gate must explicitly mock agents.** Do not "just run the
    real agents and see" — that re-tests prompts at the worst possible
    time and lets phase-sequencing bugs hide behind agent noise.
- **Depends on:** 1, 2, 3, 4, 5, 6, 7, 8, 9, 10

### Step 12 — CLI and skill wrapper · SPLIT (HARD CLI, SOFT skill polish)

- **Spec:** `docs/spec/05-interfaces/skill-invocation.md`,
  `docs/spec/05-interfaces/human-review.md`
- **Contract:** `meta-harness {review, status, maintenance}` subcommands;
  first invocation in a fresh repo auto-runs Phase 1 silently;
  `--resume <run_id>`; `--verbose`; the proposal batch markdown is plain
  formatting (no fancy tables, no decorative elements); a thin Claude
  Code skill wrapper around the CLI
- **Gate (SPLIT):**
  - **HARD CLI gate:** integration tests per subcommand against fixture
    state; `--resume` re-opens the same markdown and diffs; `--verbose`
    adds streamed output and tool-call traces; fresh-repo first
    invocation runs Phase 1; the proposal batch markdown renders without
    decorative formatting (regex assertion against the rendered output)
  - **SOFT skill polish:** does invocation from inside Claude Code feel
    right? Revisit after we've used it ourselves a few times.
- **Depends on:** 11

---

## Dependency DAG

```
                    ┌──────────────────────────┐
                    │  1. KB setup (HARD)      │
                    └──────────┬───────────────┘
                               │
              ┌────────┬───────┼───────┐
              ▼        ▼       ▼       ▼
            ┌────┐  ┌────┐  ┌────┐  ┌──────────────┐
            │ 2  │  │ 3  │  │ 4  │  │ 5. session   │   (5 has no .meta-harness/
            │gap │  │dec │  │arc │  │   log reader │    dependency. Floats off
            └─┬──┘  └─┬──┘  └─┬──┘  └──────┬───────┘    critical path.)
              │       │       │            │
              └───────┼───────┘            │
                      ▼                    │
              ┌──────────────┐             │
              │ 6. summary   │             │
              │    layer     │             │
              └──────┬───────┘             │
                     ▼                     │
              ┌──────────────┐             │
              │ 7. mainten-  │             │
              │    ance      │             │
              └──────┬───────┘             │
                     │                     │
                     └────────┬────────────┘
                              ▼
                     ┌────────────────┐
                     │ 8. evaluator   │   (SOFT gate begins)
                     └────────┬───────┘
                              ▼
                     ┌────────────────┐
                     │ 9. proposer    │
                     └────────┬───────┘
                              ▼
                     ┌────────────────┐
                     │ 10. author     │
                     └────────┬───────┘
                              ▼
                     ┌────────────────┐
                     │ 11. run loop   │   (HARD plumbing, mocked agents;
                     └────────┬───────┘    SOFT real-agent observation)
                              ▼
                     ┌────────────────┐
                     │ 12. CLI+skill  │   (HARD CLI, SOFT skill polish)
                     └────────────────┘
```

**Critical path:** 1 → {2, 3, 4} → 6 → 7 → 8 → 9 → 10 → 11 → 12.
**Floating:** 5 (any time before 8).

---

## Cross-cutting cautions (must stay live across every step)

These are restated from `docs/IMPLEMENTATION.md` § "Implementation
cautions" because each session must keep them in scope:

- **No scalar grades anywhere.** No quality scores, effort scores,
  priority numbers. If a function signature includes a numeric score,
  that's a bug.
- **Agent context isolation.** Each agent invocation is a fresh SDK
  session. Communication is through disk (JSON, git, the knowledge
  base), never shared in-memory state.
- **Summary layer is not authoritative.** When the proposer needs
  current state, it reads canonical layers. The architectural test in
  step 6 enforces this.
- **Maintenance is idempotent.** Run-twice tests in step 7.
- **Knowledge base is append-only.** Records are never deleted. Step 2
  enforces this for gap records; analogous tests for steps 3 and 4.
- **Plain markdown for human review.** Step 12's CLI gate asserts no
  decorative formatting in the proposal batch markdown.
- **v1 crash recovery is simple.** Resume only from Phase 7. Step 11's
  plumbing gate covers discard-on-crash for earlier phases.

---

## How to use this plan in a Claude Code session

Each step in this plan corresponds to **two implementation sessions plus
one verification session**, not a single session. The two-session pattern
addresses an LLM-specific TDD failure mode: when the same model writes
the tests *and* the implementation in one context, the tests end up
validating what the implementation does rather than what the spec
requires. The verification session catches drift the implementer cannot
see. The full procedure is mandatory; the gate is not "the tests pass"
but "an independent reader confirms the tests *and* the implementation
match the spec."

### Session A — write the gate first (separate context)

1. Open a fresh Claude Code session.
2. Read: `CLAUDE.md`, `file_navigation.md`, this `PLAN.md`, and the spec
   files named under the step (and any specs they cross-reference). Do
   **not** read prior implementation work for this step.
3. Write the verification gate as code:
   - **HARD steps (1–7):** unit and integration tests under `tests/`.
     Tests must fail (no implementation exists yet).
   - **SOFT steps (8–10):** an eval set under `tests/fixtures/` —
     `(input, expected-output-shape)` pairs. Schemas and categories,
     not exact prose.
   - **SPLIT steps (11, 12):** unit/integration tests for the HARD
     portion; observational notes for the SOFT portion in
     `docs/PROMPT_ITERATION.md`.
4. Run the gate; confirm it fails (HARD) or that the eval harness runs
   without an agent (SOFT).
5. Commit. Suggested message: `tests: step N <name> — failing gate`.

### Session B — implement until green (fresh context)

1. Open a new fresh Claude Code session.
2. Read: `CLAUDE.md`, `file_navigation.md`, this `PLAN.md`, the spec for
   this step, **and the failing tests from session A**. Do not re-derive
   the gate.
3. Implement under `src/meta_harness/` per `src/README.md` and the
   cross-cutting cautions above.
4. Run the gate. Iterate until green for HARD; iterate until acceptable
   for SOFT, logging residual drift in `docs/PROMPT_ITERATION.md`.
5. Commit. Suggested message: `feat: step N <name> — implementation`.

### Verification subagent — closing ritual (fresh context, no shared state)

1. Launch a verification subagent — a fresh Claude Code session or a
   subagent invocation via the Task tool.
2. Brief it with: the spec files for this step, the gate criteria from
   this `PLAN.md`, and the paths of the implemented files. Do **not**
   include the implementer's reasoning or prior session transcripts.
3. The subagent reads the implementation and confirms it satisfies the
   gate criteria. It returns a written sign-off or a drift list.
4. The subagent's output is the formal sign-off for the step.

If the subagent finds drift:
- **HARD steps:** open a fresh implementation session to fix the drift,
  then re-run the verification subagent. Do not proceed.
- **SOFT steps:** append the drift to `docs/PROMPT_ITERATION.md` and
  decide whether to proceed. The plan allows forward motion on a
  known-issues list for soft-gated steps only.

### Promotion rule

Do not start step N+1 until step N has a verification subagent sign-off.
Update this plan if anything was learned during the step that changes
downstream gates or dependencies.

---

## Open items

To be filled in as the build progresses:

- `docs/PROMPT_ITERATION.md` — created when step 8 produces the first
  drift item that needs tracking. Holds the soft-gate known-issues lists
  for steps 8, 9, 10.
- Per-step verification fixtures — assemble alongside the test files
  under `tests/fixtures/`. Step 5's fixture generator (which is part of
  the package, not the test suite) produces synthetic JSONL session logs
  for downstream steps.
