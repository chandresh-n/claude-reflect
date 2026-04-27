# CLAUDE.md

You are working on the **meta-harness for Claude Code** — a Python + bash CLI
tool that runs reflective passes over Claude Code session logs and proposes
configuration changes. This is a 0-1 build. Claude Code reads this file
automatically at the start of every session.

---

## Read these first, in this order

1. `file_navigation.md` — workspace index. What every file is, where it lives.
2. `docs/PLAN.md` — the **frozen 12-step breakdown**. Each session implements
   exactly one step. Look up which step you are on and read the named spec
   files.
3. `docs/IMPLEMENTATION.md` — implementation context (language, models, layout,
   error handling, cautions).
4. `docs/spec/` — technical spec. Authoritative for contracts and invariants.
5. `docs/PRD.pdf` — vision (the *why*). Read once.

If anything in this file conflicts with the spec, the spec wins. Update this
file to remove the conflict.

---

## Per-step procedure

Each step in `docs/PLAN.md` corresponds to **two implementation sessions plus
one verification session**, not one session. The two-session pattern addresses
an LLM-specific TDD failure mode: when the same model writes the tests *and*
the implementation in one context, the tests end up validating what the
implementation does rather than what the spec requires. The verification
session catches drift the implementer cannot see.

### Session A — write the gate first (separate context)

1. Open a fresh Claude Code session.
2. Read: this `CLAUDE.md`, `file_navigation.md`, `docs/PLAN.md`, and the spec
   files named under your step (and any specs they cross-reference). Do
   **not** read prior implementation work for this step.
3. Write the verification gate as code:
   - **HARD steps (1–7):** unit and integration tests under `tests/`. Tests
     must fail (no implementation exists yet).
   - **SOFT steps (8–10):** an eval set under `tests/fixtures/` — `(input,
     expected-output-shape)` pairs. Schemas and categories, not exact prose.
   - **SPLIT steps (11, 12):** unit/integration tests for the HARD portion;
     observational notes for the SOFT portion in `docs/PROMPT_ITERATION.md`.
4. Run the gate; confirm it fails (HARD) or that the eval harness runs
   without an agent (SOFT).
5. Commit. Suggested message: `tests: step N <name> — failing gate`.

### Session B — implement until green (fresh context)

1. Open a new fresh Claude Code session.
2. Read: this `CLAUDE.md`, `file_navigation.md`, `docs/PLAN.md`, the spec for
   this step, **and the failing tests from session A**. Do not re-derive the
   gate.
3. Implement under `src/meta_harness/` per `src/README.md` and the
   cross-cutting cautions below.
4. Run the gate. Iterate until green for HARD; iterate until acceptable for
   SOFT, logging residual drift in `docs/PROMPT_ITERATION.md`.
5. Commit. Suggested message: `feat: step N <name> — implementation`.

### Verification subagent — closing ritual (fresh context, no shared state)

1. Launch a verification subagent — either a fresh Claude Code session or a
   subagent invocation via the Task tool.
2. Brief it with: the spec files for this step, the gate criteria from
   `docs/PLAN.md`, and the paths of the implemented files. Do **not** include
   the implementer's reasoning or prior session transcripts.
3. The subagent reads the implementation and confirms it satisfies the gate
   criteria. It returns a written sign-off or a drift list.
4. The subagent's output is the formal sign-off for the step.

If the subagent finds drift:
- **HARD steps:** open a fresh implementation session to fix the drift, then
  re-run the verification subagent. Do not proceed to step N+1.
- **SOFT steps:** append the drift to `docs/PROMPT_ITERATION.md` and decide
  whether to proceed. The plan allows forward motion on a known-issues list.

### Promotion rule

Do not start step N+1 until step N has a verification subagent sign-off. The
gate is not "the tests pass" — it is "an independent reader confirms the
tests *and* the implementation match the spec."

---

## Cross-cutting cautions (must stay live every session)

These are constraints from `docs/IMPLEMENTATION.md` § "Implementation
cautions" that Claude Code is most likely to drift on. Re-read at the start
of every session.

- **No scalar grades anywhere.** No quality scores, effort scores, priority
  numbers. If a function signature includes a numeric score, that's a bug.
- **Agent context isolation.** Each agent invocation is a fresh Anthropic SDK
  session. Communication between agents goes through disk (JSON, git, the
  knowledge base), never shared in-memory state.
- **Summary layer is not authoritative.** When the proposer needs current
  state, it reads canonical layers (gap records, decisions, archive entries)
  — not summary pages.
- **Maintenance is idempotent.** Running it twice in succession produces
  byte-identical state. Run-twice tests required.
- **Knowledge base is append-only.** Records are never deleted; only specific
  fields update per the spec. Tests must enforce this.
- **Plain markdown for human review.** No fancy tables, no decorative
  elements in the proposal batch markdown.
- **v1 crash recovery is simple.** Resume from Phase 7 only. Discard partial
  pre-Phase-7 runs on next invocation.

---

## Conflict resolution

- **Spec vs. anything** → spec wins; update the conflicting file.
- **`docs/IMPLEMENTATION.md` vs. `docs/PLAN.md`** → IMPLEMENTATION.md wins on
  *implementation decisions* (language, models, layout); PLAN.md wins on
  *slicing and gating* (which step, in what order, with what gate).
- **This file vs. anything** → fix this file.

---

## What you do **not** do in this repo

- Do not implement multiple steps in one session.
- Do not write tests and implementation in the same session for HARD-gated
  steps.
- Do not skip the verification subagent.
- Do not parallelize work across the 12 steps unless the dependency DAG in
  `docs/PLAN.md` already marks the step as floating (only step 5 floats).
- Do not introduce scalar grades anywhere — schemas, function signatures, or
  config — even as "convenience."
- Do not let the proposer read the summary layer for authoritative state.
- Do not re-read implementation guidance during Session A of a HARD step.
  Session A reads spec only; that is the discipline that makes the test gate
  honest.
