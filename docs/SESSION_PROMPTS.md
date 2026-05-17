# Session prompts

Pre-written prompts for every session of the 12-step build plus the
post-0-1 architectural refactors (steps 13–15).
Each step has three sessions: A (failing gate), B (implementation), V (verification).

**How to use:**
1. Find the next unchecked box.
2. Copy the prompt block exactly.
3. Paste into a fresh Claude Code session.
4. Check the box when the session is committed and done.

**Progress tracker:**

- [x] 1A — Step 1 Session A (failing gate committed)
- [x] 1B — Step 1 Session B (implementation committed)
- [x] 1V — Step 1 Verification subagent
- [x] 2A — Step 2 Session A
- [x] 2B — Step 2 Session B
- [x] 2V — Step 2 Verification subagent
- [x] 3A — Step 3 Session A
- [x] 3B — Step 3 Session B
- [x] 3V — Step 3 Verification subagent
- [x] 4A — Step 4 Session A
- [x] 4B — Step 4 Session B
- [x] 4V — Step 4 Verification subagent
- [x] 5A — Step 5 Session A
- [x] 5B — Step 5 Session B
- [x] 5V — Step 5 Verification subagent
- [x] 6A — Step 6 Session A
- [x] 6B — Step 6 Session B
- [x] 6V — Step 6 Verification subagent
- [x] 7A — Step 7 Session A
- [x] 7B — Step 7 Session B
- [x] 7V — Step 7 Verification subagent
- [x] 8A — Step 8 Session A
- [x] 8B — Step 8 Session B
- [x] 8V — Step 8 Verification subagent
- [x] 9A — Step 9 Session A
- [x] 9B — Step 9 Session B
- [x] 9V — Step 9 Verification subagent
- [x] 10A — Step 10 Session A
- [x] 10B — Step 10 Session B
- [x] 10V — Step 10 Verification subagent
- [x] 11A — Step 11 Session A
- [x] 11B — Step 11 Session B
- [x] 11V — Step 11 Verification subagent
- [x] 12A — Step 12 Session A
- [x] 12B — Step 12 Session B
- [x] 12V — Step 12 Verification subagent
- [x] 13A — Step 13 Session A
- [x] 13B — Step 13 Session B
- [x] 13V — Step 13 Verification subagent
- [x] 14A — Step 14 Session A
- [x] 14B — Step 14 Session B
- [ ] 14V — Step 14 Verification subagent
- [ ] 15A — Step 15 Session A
- [ ] 15B — Step 15 Session B
- [ ] 15V — Step 15 Verification subagent

---

## Step 1 — Knowledge base & setup script

### 1V — Verification subagent

```
You are a verification subagent for Step 1 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/02-storage/knowledge-base.md
2. docs/spec/04-processes/run-loop.md  (Phase 1 only)
3. docs/IMPLEMENTATION.md  (§ "Storage layout", § "Configuration file",
   § "Default models", § "Git structure")
4. docs/PLAN.md  (Step 1 gate criteria only)
5. tests/unit/test_step1_kb_setup.py
6. tests/integration/test_step1_kb_setup_integration.py
7. src/meta_harness/storage/knowledge_base.py

Gate criteria (from docs/PLAN.md Step 1):
1. Directory layout under .meta-harness/ matches the spec.
2. The meta-harness/decisions git branch is created and HEAD remains
   on the original active branch after setup().
3. config.yaml contains every required field with correct defaults
   (Sonnet for evaluator/author, Opus for proposer).
4. Running setup() twice produces byte-identical state (idempotent).

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 2 — Gap record read/write

### 2A — Session A (failing gate)

```
Session A — Step 2 gap record read/write.

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 2 only)
4. docs/spec/01-data-structures/gap-record.md

Then write failing unit tests under tests/unit/test_step2_gap_record.py.
Do not create any implementation files.

Gate criteria to cover (from docs/PLAN.md Step 2):
1. Roundtrip: write a gap record to disk, read it back, assert equality.
2. Schema validation rejects malformed records (missing required fields,
   wrong field types, invalid enum values).
3. Append-only enforcement: deleting a gap record is impossible through
   the public API.
4. Immutable field enforcement: fields the spec marks immutable cannot
   be overwritten after first write.
5. Kind-vocabulary handling matches the spec.

Run: python3.11 -m pytest tests/unit/test_step2_gap_record.py -v
Confirm every new test FAILS (ImportError or assertion failure).
Commit: "tests: step 2 gap-record — failing gate"
```

### 2B — Session B (implementation)

```
Session B — Step 2 gap record read/write.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 2 only)
4. docs/spec/01-data-structures/gap-record.md
5. tests/unit/test_step2_gap_record.py

Then implement src/meta_harness/storage/gap_record.py so all tests pass.
Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 2 gap-record — implementation"
```

### 2V — Verification subagent

```
You are a verification subagent for Step 2 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/01-data-structures/gap-record.md
2. docs/PLAN.md  (Step 2 gate criteria only)
3. tests/unit/test_step2_gap_record.py
4. src/meta_harness/storage/gap_record.py

Gate criteria (from docs/PLAN.md Step 2):
1. Roundtrip tests pass (write then read produces identical record).
2. Schema validation rejects malformed records.
3. Deleting a gap record is impossible through the public API.
4. Immutable fields cannot be overwritten post-write.
5. Kind-vocabulary handling matches the spec.

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 3 — Decision record + git ops

### 3A — Session A (failing gate)

```
Session A — Step 3 decision record + git ops.

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 3 only)
4. docs/spec/01-data-structures/decision-record.md
5. docs/spec/02-storage/decisions-git.md

Then write failing tests under tests/unit/test_step3_decision_record.py
and tests/integration/test_step3_git_ops.py. Do not create any
implementation files.

Gate criteria to cover (from docs/PLAN.md Step 3):
1. Commit-message header parses correctly (proposal_id, run_id,
   status, targeted_gaps all extractable).
2. Decision JSON roundtrips through the commit body.
3. Status transitions (accepted/rejected/author_failed) are enforced.
4. Proposal-branch lifecycle exercised end-to-end:
   create → commit → merge (accepted) or delete (rejected/author_failed).

Run: python3.11 -m pytest tests/unit/test_step3_decision_record.py
     tests/integration/test_step3_git_ops.py -v
Confirm every new test FAILS.
Commit: "tests: step 3 decision-record — failing gate"
```

### 3B — Session B (implementation)

```
Session B — Step 3 decision record + git ops.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 3 only)
4. docs/spec/01-data-structures/decision-record.md
5. docs/spec/02-storage/decisions-git.md
6. tests/unit/test_step3_decision_record.py
7. tests/integration/test_step3_git_ops.py

Then implement:
- src/meta_harness/storage/decision_record.py
- src/meta_harness/storage/decisions_git.py  (or equivalent)

Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 3 decision-record — implementation"
```

### 3V — Verification subagent

```
You are a verification subagent for Step 3 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/01-data-structures/decision-record.md
2. docs/spec/02-storage/decisions-git.md
3. docs/PLAN.md  (Step 3 gate criteria only)
4. tests/unit/test_step3_decision_record.py
5. tests/integration/test_step3_git_ops.py
6. src/meta_harness/storage/decision_record.py  (and any related files)

Gate criteria (from docs/PLAN.md Step 3):
1. Commit-message header parses correctly.
2. Decision JSON roundtrips through the commit body.
3. Status transitions are enforced.
4. Proposal-branch lifecycle exercised end-to-end.

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 4 — Archive entry read/write

### 4A — Session A (failing gate)

```
Session A — Step 4 archive entry read/write.

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 4 only)
4. docs/spec/01-data-structures/archive-entry.md

Then write failing tests under tests/unit/test_step4_archive_entry.py.
Do not create any implementation files.

Gate criteria to cover (from docs/PLAN.md Step 4):
1. Roundtrip: write an archive entry, read it back, assert equality.
2. "Exactly one active configuration" invariant holds at all times,
   including under concurrent supersession.
3. Lifecycle transitions follow the spec's allowed paths
   (active → superseded).

Run: python3.11 -m pytest tests/unit/test_step4_archive_entry.py -v
Confirm every new test FAILS.
Commit: "tests: step 4 archive-entry — failing gate"
```

### 4B — Session B (implementation)

```
Session B — Step 4 archive entry read/write.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 4 only)
4. docs/spec/01-data-structures/archive-entry.md
5. tests/unit/test_step4_archive_entry.py

Then implement src/meta_harness/storage/archive_entry.py so all tests pass.
Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 4 archive-entry — implementation"
```

### 4V — Verification subagent

```
You are a verification subagent for Step 4 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/01-data-structures/archive-entry.md
2. docs/PLAN.md  (Step 4 gate criteria only)
3. tests/unit/test_step4_archive_entry.py
4. src/meta_harness/storage/archive_entry.py

Gate criteria (from docs/PLAN.md Step 4):
1. Roundtrip tests pass.
2. "Exactly one active configuration" invariant holds under concurrent
   supersession.
3. Lifecycle transitions follow the spec's allowed paths.

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 5 — Session log reader

### 5A — Session A (failing gate)

```
Session A — Step 5 session log reader.

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 5 only)
4. docs/spec/02-storage/session-logs.md

Then write failing tests under tests/unit/test_step5_session_logs.py
using synthetic JSONL fixtures (create fixtures under tests/fixtures/).
Do not create any implementation files.

Gate criteria to cover (from docs/PLAN.md Step 5):
1. Walk Claude Code's session log directory correctly.
2. Parse JSONL; expose a session abstraction matching the spec.
3. Date-range filtering is correct on edge cases (boundary days,
   empty range, range with no matching sessions).
4. No code path under this module writes to the session-log directory
   (static check or audit).

Run: python3.11 -m pytest tests/unit/test_step5_session_logs.py -v
Confirm every new test FAILS.
Commit: "tests: step 5 session-log-reader — failing gate"
```

### 5B — Session B (implementation)

```
Session B — Step 5 session log reader.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 5 only)
4. docs/spec/02-storage/session-logs.md
5. tests/unit/test_step5_session_logs.py
6. tests/fixtures/  (inspect existing fixtures)

Then implement src/meta_harness/storage/session_logs.py so all tests pass.
Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 5 session-log-reader — implementation"
```

### 5V — Verification subagent

```
You are a verification subagent for Step 5 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/02-storage/session-logs.md
2. docs/PLAN.md  (Step 5 gate criteria only)
3. tests/unit/test_step5_session_logs.py
4. src/meta_harness/storage/session_logs.py

Gate criteria (from docs/PLAN.md Step 5):
1. Session log directory walking is correct.
2. JSONL parsing and session abstraction match the spec.
3. Date-range filtering handles edge cases correctly.
4. No code path writes to the session-log directory.

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 6 — Summary layer storage & index regeneration

### 6A — Session A (failing gate)

```
Session A — Step 6 summary layer storage & index regeneration.

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 6 only)
4. docs/spec/02-storage/summary-layer.md

Then write failing tests under tests/unit/test_step6_summary_layer.py
and tests/integration/test_step6_summary_layer_integration.py.
Do not create any implementation files.

Gate criteria to cover (from docs/PLAN.md Step 6):
1. Page kinds are enumerated correctly per the spec.
2. Regeneration is idempotent: run twice → byte-identical output.
3. Architectural test: assert no code path from the proposer module
   reaches summary files (enforces the cross-cutting caution that the
   summary layer is not authoritative).

Run: python3.11 -m pytest tests/unit/test_step6_summary_layer.py
     tests/integration/test_step6_summary_layer_integration.py -v
Confirm every new test FAILS.
Commit: "tests: step 6 summary-layer — failing gate"
```

### 6B — Session B (implementation)

```
Session B — Step 6 summary layer storage & index regeneration.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 6 only)
4. docs/spec/02-storage/summary-layer.md
5. tests/unit/test_step6_summary_layer.py
6. tests/integration/test_step6_summary_layer_integration.py

Then implement src/meta_harness/storage/summary_layer.py so all tests pass.
Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 6 summary-layer — implementation"
```

### 6V — Verification subagent

```
You are a verification subagent for Step 6 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/02-storage/summary-layer.md
2. docs/PLAN.md  (Step 6 gate criteria only)
3. tests/unit/test_step6_summary_layer.py
4. tests/integration/test_step6_summary_layer_integration.py
5. src/meta_harness/storage/summary_layer.py

Gate criteria (from docs/PLAN.md Step 6):
1. Page kinds enumerated correctly.
2. Regeneration is idempotent (byte-identical on second run).
3. No code path from the proposer module reaches summary files.

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 7 — Maintenance process

### 7A — Session A (failing gate)

```
Session A — Step 7 maintenance process.

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 7 only)
4. docs/spec/04-processes/maintenance.md

Then write failing tests under tests/unit/test_step7_maintenance.py
and tests/integration/test_step7_maintenance_integration.py.
Do not create any implementation files.

Gate criteria to cover (from docs/PLAN.md Step 7):
1. Integration test: run maintenance, snapshot state, run again,
   assert byte-identical state (idempotent).
2. Each threshold trigger tested independently: new_sessions,
   new_decisions, new_gap_records, days_since_last.
3. Stale-gap transition logic tested with a fixture.
4. Kind-vocabulary reconciliation tested.

Run: python3.11 -m pytest tests/unit/test_step7_maintenance.py
     tests/integration/test_step7_maintenance_integration.py -v
Confirm every new test FAILS.
Commit: "tests: step 7 maintenance — failing gate"
```

### 7B — Session B (implementation)

```
Session B — Step 7 maintenance process.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 7 only)
4. docs/spec/04-processes/maintenance.md
5. tests/unit/test_step7_maintenance.py
6. tests/integration/test_step7_maintenance_integration.py

Then implement src/meta_harness/processes/maintenance.py so all tests pass.
Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 7 maintenance — implementation"
```

### 7V — Verification subagent

```
You are a verification subagent for Step 7 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/04-processes/maintenance.md
2. docs/PLAN.md  (Step 7 gate criteria only)
3. tests/unit/test_step7_maintenance.py
4. tests/integration/test_step7_maintenance_integration.py
5. src/meta_harness/processes/maintenance.py

Gate criteria (from docs/PLAN.md Step 7):
1. Maintenance is idempotent (byte-identical on second run).
2. Each threshold trigger fires correctly in isolation.
3. Stale-gap transition logic is correct.
4. Kind-vocabulary reconciliation is correct.

Your output must be one of:
- SIGN-OFF: confirm each criterion with a one-line explanation.
- DRIFT LIST: for each failing criterion, state what the spec
  requires and what the implementation does instead.

Do not run the tests. Read the code and reason against the spec.
```

---

## Step 8 — Evaluator agent (SOFT gate)

### 8A — Session A (eval set)

```
Session A — Step 8 evaluator agent (SOFT gate).

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 8 only)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md

Then write an eval set under tests/fixtures/evaluator/:
- At least one (input, expected-output-shape) pair using a synthetic
  JSONL session that contains a tool-call loop pattern.
- expected-output-shape is a schema/category assertion, not exact prose.
- Write a fixture runner (no real agent needed) that validates the
  schema of a canned evaluator output against the expected shape.

Run the fixture runner to confirm it executes without an agent.
Commit: "tests: step 8 evaluator — eval set"
```

### 8B — Session B (implementation)

```
Session B — Step 8 evaluator agent.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 8 only)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md
6. tests/fixtures/evaluator/  (inspect eval set from Session A)

Then implement src/meta_harness/agents/evaluator.py so that:
- Given a fixture session with a tool-call-loop pattern, the evaluator
  output validates against the schema.
- A gap observation of the correct category is present.
- No scalar grades, no recommendations, no rankings appear in output.

Run eval set. Log residual drift in docs/PROMPT_ITERATION.md if needed.
Commit: "feat: step 8 evaluator — implementation"
```

### 8V — Verification subagent

```
You are a verification subagent for Step 8 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/03-agents/evaluator.md
2. docs/spec/01-data-structures/evaluator-output.md
3. docs/PLAN.md  (Step 8 gate criteria only)
4. tests/fixtures/evaluator/
5. src/meta_harness/agents/evaluator.py
6. docs/PROMPT_ITERATION.md  (if it exists)

Gate criteria (from docs/PLAN.md Step 8 — SOFT):
1. Evaluator output validates against the schema for a fixture session.
2. A gap observation of the correct category is present.
3. No scalar grades, no recommendations, no rankings in output or code.

Forward motion is allowed on a known-issues list for prompt drift.
Your output must be one of:
- SIGN-OFF (possibly with noted drift items).
- DRIFT LIST with items for docs/PROMPT_ITERATION.md.

Do not invoke the agent. Read the code and fixtures against the spec.
```

---

## Step 9 — Proposer agent (SOFT gate)

### 9A — Session A (eval set)

```
Session A — Step 9 proposer agent (SOFT gate).

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 9 only)
4. docs/spec/03-agents/proposer.md
5. docs/spec/01-data-structures/proposal.md

Then write:
- An eval set under tests/fixtures/proposer/ with at least one
  (evaluator-output-fixture, expected-proposal-batch-shape) pair.
- A unit test for the forced-novelty roll logic using a mocked RNG
  (tests/unit/test_step9_forced_novelty.py). The unit test must be
  runnable without a real agent.

Run: python3.11 -m pytest tests/unit/test_step9_forced_novelty.py -v
Confirm it FAILS.
Commit: "tests: step 9 proposer — eval set and forced-novelty gate"
```

### 9B — Session B (implementation)

```
Session B — Step 9 proposer agent.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 9 only)
4. docs/spec/03-agents/proposer.md
5. docs/spec/01-data-structures/proposal.md
6. tests/fixtures/proposer/
7. tests/unit/test_step9_forced_novelty.py

Then implement src/meta_harness/agents/proposer.py so that:
- The forced-novelty unit test passes.
- A fixture-fed proposer produces a non-empty batch with valid schema.
- Each proposal has both rationale and authoring addendum.
- The proposer reads canonical layers, not the summary layer.

Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 9 proposer — implementation"
```

### 9V — Verification subagent

```
You are a verification subagent for Step 9 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/03-agents/proposer.md
2. docs/spec/01-data-structures/proposal.md
3. docs/PLAN.md  (Step 9 gate criteria only)
4. tests/fixtures/proposer/
5. tests/unit/test_step9_forced_novelty.py
6. src/meta_harness/agents/proposer.py

Gate criteria (from docs/PLAN.md Step 9 — SOFT):
1. Fixture-fed proposer produces non-empty batch with valid schema.
2. Each proposal has rationale and authoring addendum.
3. Forced-novelty unit test covers the roll logic correctly.
4. Proposer reads canonical layers, not summary layer.

Forward motion allowed on a known-issues list for prompt drift.
Your output must be SIGN-OFF (possibly with drift) or DRIFT LIST.

Do not invoke the agent. Read the code and fixtures against the spec.
```

---

## Step 10 — Author agent (SOFT gate)

### 10A — Session A (eval set)

```
Session A — Step 10 author agent (SOFT gate).

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 10 only)
4. docs/spec/03-agents/author.md

Then write an eval set under tests/fixtures/author/:
- A "valid intent" fixture: a proposer intent that should produce a
  clean git diff.
- An "impossible intent" fixture: a proposer intent for which the
  author must return author_failed rather than fabricating a diff.
- A fixture runner that validates the output shape (diff vs. failure)
  without invoking a real agent.

Run the fixture runner to confirm it executes without an agent.
Commit: "tests: step 10 author — eval set"
```

### 10B — Session B (implementation)

```
Session B — Step 10 author agent.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 10 only)
4. docs/spec/03-agents/author.md
5. tests/fixtures/author/

Then implement src/meta_harness/agents/author.py so that:
- A valid intent fixture produces a diff that applies cleanly.
- An impossible intent fixture produces author_failed (not a
  fabricated diff).

Run eval set. Log residual drift in docs/PROMPT_ITERATION.md if needed.
Commit: "feat: step 10 author — implementation"
```

### 10V — Verification subagent

```
You are a verification subagent for Step 10 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/03-agents/author.md
2. docs/PLAN.md  (Step 10 gate criteria only)
3. tests/fixtures/author/
4. src/meta_harness/agents/author.py

Gate criteria (from docs/PLAN.md Step 10 — SOFT):
1. Valid intent fixture → diff applies cleanly.
2. Impossible intent fixture → author_failed (not fabricated diff).

Forward motion allowed on a known-issues list for prompt drift.
Your output must be SIGN-OFF (possibly with drift) or DRIFT LIST.

Do not invoke the agent. Read the code and fixtures against the spec.
```

---

## Step 11 — Run loop orchestration (SPLIT gate)

### 11A — Session A (failing gate — HARD plumbing only)

```
Session A — Step 11 run loop orchestration (HARD plumbing gate).

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 11 only)
4. docs/spec/04-processes/run-loop.md  (full)

Then write failing tests under tests/integration/test_step11_run_loop.py.
Agents must be mocked with canned responses; do not invoke real agents.

Gate criteria to cover (HARD plumbing — from docs/PLAN.md Step 11):
1. Phase sequence is correct (phases execute in order, each end state
   reached before the next phase begins).
2. Pending-proposal carry-over from a previous run is handled.
3. Resume-from-Phase-7 works after a simulated crash.
4. Partial pre-Phase-7 run is discarded on next invocation (v1 crash
   recovery).

Run: python3.11 -m pytest tests/integration/test_step11_run_loop.py -v
Confirm every new test FAILS.
Commit: "tests: step 11 run-loop — failing gate"
```

### 11B — Session B (implementation)

```
Session B — Step 11 run loop orchestration.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 11 only)
4. docs/spec/04-processes/run-loop.md  (full)
5. tests/integration/test_step11_run_loop.py

Then implement src/meta_harness/processes/run_loop.py so all tests pass.
Agents must remain mocked in tests; the implementation wires real agents
behind the same interface.

Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 11 run-loop — implementation"
```

### 11V — Verification subagent

```
You are a verification subagent for Step 11 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/04-processes/run-loop.md
2. docs/PLAN.md  (Step 11 gate criteria only)
3. tests/integration/test_step11_run_loop.py
4. src/meta_harness/processes/run_loop.py

Gate criteria (HARD plumbing — from docs/PLAN.md Step 11):
1. Phase sequence is enforced correctly.
2. Pending-proposal carry-over works.
3. Resume-from-Phase-7 works after a simulated crash.
4. Partial pre-Phase-7 run is discarded (v1 crash recovery).

Note: agents must be mocked in the tests — the gate explicitly
requires this. Flag it as drift if real agents are invoked in the
plumbing tests.

Your output must be SIGN-OFF or DRIFT LIST.
Do not run the tests. Read the code and reason against the spec.
```

---

## Step 12 — CLI and skill wrapper (SPLIT gate)

### 12A — Session A (failing gate — HARD CLI only)

```
Session A — Step 12 CLI and skill wrapper (HARD CLI gate).

Read in this order (do NOT read any prior implementation work):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 12 only)
4. docs/spec/05-interfaces/skill-invocation.md
5. docs/spec/05-interfaces/human-review.md

Then write failing tests under tests/integration/test_step12_cli.py.
Do not create any implementation files.

Gate criteria to cover (HARD CLI — from docs/PLAN.md Step 12):
1. review, status, maintenance subcommands work against fixture state.
2. --resume <run_id> re-opens the same markdown and diffs.
3. --verbose adds streamed output and tool-call traces.
4. Fresh-repo first invocation runs Phase 1 automatically.
5. Proposal batch markdown contains no decorative formatting
   (assert with a regex against rendered output).

Run: python3.11 -m pytest tests/integration/test_step12_cli.py -v
Confirm every new test FAILS.
Commit: "tests: step 12 cli — failing gate"
```

### 12B — Session B (implementation)

```
Session B — Step 12 CLI and skill wrapper.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 12 only)
4. docs/spec/05-interfaces/skill-invocation.md
5. docs/spec/05-interfaces/human-review.md
6. tests/integration/test_step12_cli.py

Then implement:
- src/meta_harness/cli.py  (the meta-harness entry point)
- The Claude Code skill wrapper (thin layer over the CLI)

Run: python3.11 -m pytest tests/ -v
Iterate until green. Commit: "feat: step 12 cli — implementation"
```

### 12V — Verification subagent

```
You are a verification subagent for Step 12 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/05-interfaces/skill-invocation.md
2. docs/spec/05-interfaces/human-review.md
3. docs/PLAN.md  (Step 12 gate criteria only)
4. tests/integration/test_step12_cli.py
5. src/meta_harness/cli.py

Gate criteria (HARD CLI — from docs/PLAN.md Step 12):
1. All three subcommands work against fixture state.
2. --resume re-opens the correct markdown and diffs.
3. --verbose produces streamed output and tool-call traces.
4. Fresh-repo first invocation auto-runs Phase 1.
5. Proposal batch markdown has no decorative formatting.

Your output must be SIGN-OFF or DRIFT LIST.
Do not run the tests. Read the code and reason against the spec.
```

---

## Step 13 — Evaluator pipeline: infrastructure + stage 1a (HARD gate)

### 13A — Session A (failing gate)

```
Session A — Step 13 evaluator pipeline: infrastructure + stage 1a (HARD gate).

Read in this order (do NOT read any prior implementation work,
and in particular do NOT read src/meta_harness/agents/evaluator.py —
that is the old single-call evaluator, replaced in step 15, and is
not authoritative for what step 13 builds):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 13 only; glance at 14 and 15 to understand
   what stage 1a hands off to)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md

Then write failing tests under:
- tests/unit/test_pipeline_runner.py
- tests/unit/test_pipeline_cache.py
- tests/unit/test_pipeline_manifest.py
- tests/unit/test_pipeline_stage_1a.py

Do not create any implementation files. The pipeline package
src/meta_harness/agents/pipeline/ does not exist yet — tests must
fail on import. That is the gate.

Gate criteria to cover (HARD — from docs/PLAN.md Step 13):
1. cache_key includes prompt_version; hit/miss/invalidate flow works;
   bumping prompt_version invalidates the stage's cache without
   touching other stages.
2. The Runner abstraction supports the claude-cli implementation and
   is swappable. Architecturally enforced: no claude_runner import
   inside pipeline modules outside the runner module (AST scan).
3. Session manifest builder is deterministic (run twice → byte-
   identical) and makes ZERO model calls.
4. Stage 1a output carries every required schema field for fixture
   turns covering: plain text exchange, a Read tool call, a Bash
   tool call, an MCP tool call with outcome="denied", and a turn
   with 12 similar Reads that should cluster (count + targets[]).
5. Stage 1a cache hit on a re-run for the same turn results in zero
   additional runner invocations.
6. Failure of one turn's 1a call does not poison the description of
   any other turn (per-turn failure isolation; failed turns surface
   as {"_failed": True, ...} sentinels in turn order).

Cross-cutting cautions (from CLAUDE.md) to keep live:
- No scalar grades anywhere — not as quality scores, not as
  confidences.
- Agent context isolation — each Runner.invoke is a fresh
  subprocess.
- Append-only — caches are written, never destructively rewritten.

Run: PYTHONPATH=src python3.11 -m pytest tests/unit/test_pipeline_runner.py
     tests/unit/test_pipeline_cache.py tests/unit/test_pipeline_manifest.py
     tests/unit/test_pipeline_stage_1a.py -v
Confirm every new test FAILS.
Commit: "tests: step 13 evaluator pipeline infra + stage 1a — failing gate"
```

### 13B — Session B (implementation)

```
Session B — Step 13 evaluator pipeline: infrastructure + stage 1a.

Read in this order (do NOT read prior session transcripts, and in
particular do NOT read src/meta_harness/agents/evaluator.py — that
is the old single-call evaluator, replaced in step 15, and is not
authoritative for what step 13 builds):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 13 only; glance at 14 and 15 for handoff
   context — they are NOT in your scope)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md
6. tests/unit/test_pipeline_runner.py
7. tests/unit/test_pipeline_cache.py
8. tests/unit/test_pipeline_manifest.py
9. tests/unit/test_pipeline_stage_1a.py

Do not re-read or re-derive the gate. The tests are the contract.
If you think a test is wrong, surface it instead of softening the
implementation to match.

Then implement a new package src/meta_harness/agents/pipeline/
containing at least:
- __init__.py
- runner.py — Runner abstraction + ClaudeCLIRunner wrapping
  claude_runner.invoke_claude. Only this file may import
  claude_runner.
- cache.py — cache_key(stage_id, model, prompt_version, content)
  and StageCache(repo, stage_id) with .get(key) / .set(key, value)
  persisting under
  .meta-harness/eval-cache/stage-<id>/<key>.json.
- manifest.py — build_session_manifest(session) returning a dict
  (or dataclass) with at minimum session_id, turn_count,
  duration_seconds, tool_call_counts, first_turn_excerpts (≤3),
  last_turn_excerpts (≤3). No model calls. Deterministic.
- stage_1a.py — describe_turn(session_id, turn_index, turn,
  runner, repo, model) per the schema pinned by the tests, plus
  describe_session_turns(session, runner, repo, model) with per-
  turn failure isolation. The 1a prompt template lives in this
  file as a constant; expose a STAGE_1A_PROMPT_VERSION constant
  that gets included in cache keys.

Cross-cutting cautions (from CLAUDE.md) to keep live:
- No scalar grades anywhere — not as quality scores, not as
  confidences.
- Agent context isolation — each Runner.invoke is a fresh
  subprocess.
- Append-only — caches are written, never destructively rewritten
  in place.
- Plain markdown / JSON — no decorative formatting.

Iterate until
  PYTHONPATH=src python3.11 -m pytest tests/unit/test_pipeline_runner.py
    tests/unit/test_pipeline_cache.py tests/unit/test_pipeline_manifest.py
    tests/unit/test_pipeline_stage_1a.py -v
is 29/29 green AND the rest of the suite stays green.
Use /usr/bin/python3 if python3.11 resolves to a Python without
pytest installed.

Commit: "feat: step 13 evaluator pipeline infra + stage 1a — implementation"
Do not amend any existing commits. Do not run any git reset or git
push.
```

### 13V — Verification subagent

```
You are a verification subagent for Step 13 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/03-agents/evaluator.md
2. docs/spec/01-data-structures/evaluator-output.md
3. docs/PLAN.md  (Step 13 gate criteria only)
4. tests/unit/test_pipeline_runner.py
5. tests/unit/test_pipeline_cache.py
6. tests/unit/test_pipeline_manifest.py
7. tests/unit/test_pipeline_stage_1a.py
8. src/meta_harness/agents/pipeline/__init__.py
9. src/meta_harness/agents/pipeline/runner.py
10. src/meta_harness/agents/pipeline/cache.py
11. src/meta_harness/agents/pipeline/manifest.py
12. src/meta_harness/agents/pipeline/stage_1a.py

Do NOT read src/meta_harness/agents/evaluator.py — that is the old
single-call evaluator, replaced in step 15, and is not
authoritative for what step 13 builds.

Gate criteria (HARD — from docs/PLAN.md Step 13):
1. Cache keys include prompt_version; the hit/miss/invalidate flow
   works correctly across stage namespaces.
2. The Runner abstraction supports the claude-cli implementation
   and is swappable; only pipeline/runner.py imports claude_runner.
3. Manifest builder is deterministic and makes zero model calls.
4. Stage 1a output carries every required schema field across the
   five fixture turn shapes (plain, Read, Bash, denied MCP,
   clustered Reads).
5. Stage 1a cache hit on a re-run yields zero additional runner
   invocations.
6. Per-turn failure isolation: one turn's failure does not poison
   the description of any other turn.

Cross-cutting cautions to flag if violated:
- Any scalar grade (quality score, confidence value, priority
  number) anywhere in the pipeline schema or code.
- A pipeline module other than runner.py importing claude_runner.
- Cache writes that destructively rewrite or delete prior entries
  (caches must be append-only).
- The internal stage 1a schema being confused with the external
  evaluator-output schema in the spec — they are distinct.

Your output must be SIGN-OFF or DRIFT LIST.
Do not run the tests. Read the code and reason against the spec.
```

---

## Step 14 — Evaluator pipeline: stages 1b, 2, 3 (HARD gate)

### 14A — Session A (failing gate)

```
Session A — Step 14 evaluator pipeline: stages 1b, 2, 3 (HARD gate).

Read in this order (do NOT read any prior implementation work, and
in particular do NOT read src/meta_harness/agents/evaluator.py —
that is the old single-call evaluator, replaced in step 15, and
its prompt shape is the wrong reference for the new stages):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 14 only; glance at 15 for handoff context)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md
6. src/meta_harness/agents/pipeline/stage_1a.py  (to understand the
   stage 1a output that stage 1b consumes; do NOT change it)
7. src/meta_harness/agents/pipeline/cache.py  (you will key new
   caches the same way)
8. src/meta_harness/agents/pipeline/runner.py  (you will accept a
   Runner argument the same way stage 1a does)

Then write failing tests under:
- tests/unit/test_pipeline_stage_1b.py
- tests/unit/test_pipeline_stage_2.py
- tests/unit/test_pipeline_stage_3.py

Do not create any implementation files. Stages 1b/2/3 do not exist
yet — tests must fail on import. That is the gate.

Gate criteria to cover (HARD — from docs/PLAN.md Step 14):
1. Stage 1b output schema matches the spec's per_turn_observation
   and pass_classification shapes from
   docs/spec/01-data-structures/evaluator-output.md.
2. Overlap dedup: a fixture with 25-turn windows and 5-turn overlap
   produces exactly one per_turn_observation per turn across the
   boundary — no duplicates, no gaps.
3. Stage 2 produces non-overlapping pass_classifications covering
   every turn of a session (no gaps, no overlaps; every turn
   belongs to exactly one pass).
4. Stage 3 produces exactly one session_narrative per session.
5. Cache invalidation cascades: if the upstream digest for a
   session changes, the downstream stage's cache for that session
   misses and re-runs. New caches MUST live under
   .meta-harness/eval-cache/stage-1b/, .../stage-2/, .../stage-3/
   keyed on (upstream digests + model + prompt_version).
6. Partial-with-flag policy: one window failing in stage 1b for a
   session yields a partial_completion flag on that session's
   stage 3 narrative, NOT a session drop. Other sessions are
   unaffected.

Cross-cutting cautions (from CLAUDE.md) to keep live:
- No scalar grades anywhere — not as quality scores, not as
  confidences, not as priority numbers.
- Agent context isolation — each Runner.invoke is a fresh
  subprocess.
- Append-only — caches are written, never destructively rewritten
  in place.
- Plain markdown / JSON — no decorative formatting.

Run: PYTHONPATH=src python3.11 -m pytest
       tests/unit/test_pipeline_stage_1b.py
       tests/unit/test_pipeline_stage_2.py
       tests/unit/test_pipeline_stage_3.py -v
Confirm every new test FAILS.
Commit: "tests: step 14 evaluator pipeline stages 1b/2/3 — failing gate"
```

### 14B — Session B (implementation)

```
Session B — Step 14 evaluator pipeline: stages 1b, 2, 3.

Read in this order (do NOT read prior session transcripts, and in
particular do NOT read src/meta_harness/agents/evaluator.py — that
is the old single-call evaluator, replaced in step 15, and its
prompt shape is the wrong reference for the new stages):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 14 only; glance at 15 for handoff context —
   step 15 is NOT in your scope)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md
6. src/meta_harness/agents/pipeline/stage_1a.py  (you consume this
   output; do NOT change it)
7. src/meta_harness/agents/pipeline/cache.py
8. src/meta_harness/agents/pipeline/runner.py
9. tests/unit/test_pipeline_stage_1b.py
10. tests/unit/test_pipeline_stage_2.py
11. tests/unit/test_pipeline_stage_3.py

Do not re-read or re-derive the gate. The tests are the contract.
If you think a test is wrong, surface it instead of softening the
implementation to match.

Then implement under src/meta_harness/agents/pipeline/ at least:
- stage_1b.py — windowed per-turn observations + draft pass
  classifications. Window size and overlap are config knobs;
  defaults TBD in implementation (document the chosen defaults at
  the top of the module). Cache namespace: stage-1b. Expose
  STAGE_1B_PROMPT_VERSION.
- stage_2.py — per-session refinement of pass classifications
  across windows; emits the final non-overlapping
  pass_classifications per the spec. Cache namespace: stage-2.
  Expose STAGE_2_PROMPT_VERSION.
- stage_3.py — per-session session_narrative per the spec, with a
  partial_completion flag set when upstream stages dropped data
  for that session. Cache namespace: stage-3. Expose
  STAGE_3_PROMPT_VERSION.

Architectural constraint: do NOT import claude_runner from any of
these modules. Talk to the Runner abstraction. This is enforced by
the same AST scan that pinned step 13 — don't regress it.

Cross-cutting cautions (from CLAUDE.md) to keep live:
- No scalar grades anywhere.
- Agent context isolation — each Runner.invoke is a fresh
  subprocess.
- Append-only — caches are written, never destructively rewritten.
- Plain markdown / JSON — no decorative formatting in any prompt
  template.

Iterate until
  PYTHONPATH=src python3.11 -m pytest
    tests/unit/test_pipeline_stage_1b.py
    tests/unit/test_pipeline_stage_2.py
    tests/unit/test_pipeline_stage_3.py -v
is green AND the rest of the suite stays green. Use /usr/bin/python3
if python3.11 resolves to a Python without pytest installed.

Commit: "feat: step 14 evaluator pipeline stages 1b/2/3 — implementation"
Do not amend any existing commits. Do not run any git reset or git
push.
```

### 14V — Verification subagent

```
You are a verification subagent for Step 14 of the meta-harness build.
Your only job is to read the spec, the gate criteria, and the
implementation, then return a written sign-off or a drift list.
You have no implementer context. Do not read any prior session
transcripts.

Read these files, in this order:
1. docs/spec/03-agents/evaluator.md
2. docs/spec/01-data-structures/evaluator-output.md
3. docs/PLAN.md  (Step 14 gate criteria only)
4. tests/unit/test_pipeline_stage_1b.py
5. tests/unit/test_pipeline_stage_2.py
6. tests/unit/test_pipeline_stage_3.py
7. src/meta_harness/agents/pipeline/stage_1b.py
8. src/meta_harness/agents/pipeline/stage_2.py
9. src/meta_harness/agents/pipeline/stage_3.py
10. src/meta_harness/agents/pipeline/cache.py  (to confirm cache
    namespaces and key composition match the gate's expectations)

Do NOT read src/meta_harness/agents/evaluator.py — that is the old
single-call evaluator, replaced in step 15, and is not
authoritative for what step 14 builds.

Gate criteria (HARD — from docs/PLAN.md Step 14):
1. Stage 1b output schema matches the spec's per_turn_observation
   and pass_classification shapes.
2. Overlap dedup is correct across window boundaries.
3. Stage 2 emits non-overlapping pass_classifications covering
   every turn (no gaps, no overlaps).
4. Stage 3 emits exactly one narrative per session.
5. Cache invalidation cascades when an upstream digest changes;
   each stage's cache lives under its own
   .meta-harness/eval-cache/stage-<id>/ namespace.
6. One window failing in stage 1b for a session yields a partial-
   completion flag on stage 3's narrative for that session, not a
   session drop.

Cross-cutting cautions to flag if violated:
- Any scalar grade (quality score, confidence, priority) anywhere
  in the new pipeline schemas or code.
- A pipeline module other than runner.py importing claude_runner.
- Cache writes that destructively rewrite or delete prior entries.
- Stage 1b/2/3 output drifting from the spec's evaluator-output
  schema (these stages produce the SPEC schema; only stage 1a is
  internal).
- The Human:/Assistant: conversational prompt shape from the old
  evaluator showing up in any new stage's prompt.

Your output must be SIGN-OFF or DRIFT LIST.
Do not run the tests. Read the code and reason against the spec.
```

---

## Step 15 — Evaluator pipeline: stage 4 + orchestrator + cutover (HARD gate)

### 15A — Session A (failing gate)

```
Session A — Step 15 evaluator pipeline: stage 4 + orchestrator +
cutover (HARD gate).

Read in this order (do NOT read any prior implementation work for
this step):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 15 only)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md
6. docs/spec/01-data-structures/gap-record.md
7. src/meta_harness/agents/pipeline/stage_1a.py
8. src/meta_harness/agents/pipeline/stage_1b.py
9. src/meta_harness/agents/pipeline/stage_2.py
10. src/meta_harness/agents/pipeline/stage_3.py
11. src/meta_harness/agents/pipeline/cache.py
12. src/meta_harness/agents/pipeline/runner.py
13. src/meta_harness/agents/evaluator.py  (the old single-call
    evaluator — read it ONLY to enumerate what the cutover deletes:
    _split_into_batches, _chunk_large_sessions, _evaluate_batch,
    _format_sessions_for_prompt, _build_batch_prompt, and the
    single-call evaluate() public surface. Do NOT mirror its
    prompt shape into the new orchestrator.)
14. src/meta_harness/processes/run_loop.py  (Phase 4 — to see who
    calls evaluate() today so the cutover does not strand callers)

Then write failing tests under:
- tests/unit/test_pipeline_stage_4.py
- tests/unit/test_pipeline_orchestrator.py
- tests/integration/test_pipeline_e2e.py
- tests/unit/test_pipeline_cutover.py  (the static-scan regression)

Do not create or modify any implementation files. The orchestrator,
stage_4, and the cutover do not exist yet — tests must fail. That
is the gate.

Gate criteria to cover (HARD — from docs/PLAN.md Step 15):
1. Orchestrator sequences stages correctly with mocked stages —
   1a → 1b → 2 → 3 → 4, with each stage's output threaded into
   the next, and per-stage progress logged under
   .meta-harness/logs/eval/<timestamp>/stages/.
2. Partial-failure propagation: a partial failure in any stage
   sets the partial_completion flag on the affected session's
   session_narrative in the final output, without aborting the
   run or dropping unaffected sessions.
3. Cache-resume: re-running with identical inputs makes ZERO
   model calls. Re-running with one new session only re-runs that
   session's 1a/1b/2/3 plus the corpus-level 4 — the other
   sessions hit cache.
4. End-to-end integration test: with all five stages mocked to
   canned outputs, the orchestrator produces a final document
   containing exactly the four top-level keys required by
   docs/spec/01-data-structures/evaluator-output.md
   (per_turn_observations, pass_classifications, gap_observations,
   session_narratives).
5. Cutover regression (static scan over src/): the symbol names
   _split_into_batches, _chunk_large_sessions, _evaluate_batch,
   _format_sessions_for_prompt, _build_batch_prompt are absent
   from src/. The string "Human:" followed by a newline and
   "Assistant:" (the old conversational prompt shape) is absent
   from every file under src/meta_harness/agents/pipeline/. Gap
   record writes still satisfy the invariants in
   docs/spec/01-data-structures/gap-record.md (append-only, no
   deletions, matched_gap_id merge rule).

Cross-cutting cautions (from CLAUDE.md) to keep live:
- No scalar grades anywhere — not as quality scores, not as
  confidences.
- Agent context isolation — each Runner.invoke is a fresh
  subprocess.
- Append-only — caches AND gap records. Stage 4 must never delete
  gap records or rewrite their evidence destructively; it can only
  append evidence and increment counters per the gap-record spec.
- Plain markdown / JSON — no decorative formatting.

Run: PYTHONPATH=src python3.11 -m pytest
       tests/unit/test_pipeline_stage_4.py
       tests/unit/test_pipeline_orchestrator.py
       tests/unit/test_pipeline_cutover.py
       tests/integration/test_pipeline_e2e.py -v
Confirm every new test FAILS.
Commit: "tests: step 15 evaluator pipeline stage 4 + orchestrator
+ cutover — failing gate"
```

### 15B — Session B (implementation)

```
Session B — Step 15 evaluator pipeline: stage 4 + orchestrator +
cutover.

Read in this order (do NOT read prior session transcripts):
1. CLAUDE.md
2. file_navigation.md
3. docs/PLAN.md  (Step 15 only)
4. docs/spec/03-agents/evaluator.md
5. docs/spec/01-data-structures/evaluator-output.md
6. docs/spec/01-data-structures/gap-record.md
7. src/meta_harness/agents/pipeline/stage_1a.py
8. src/meta_harness/agents/pipeline/stage_1b.py
9. src/meta_harness/agents/pipeline/stage_2.py
10. src/meta_harness/agents/pipeline/stage_3.py
11. src/meta_harness/agents/pipeline/cache.py
12. src/meta_harness/agents/pipeline/runner.py
13. src/meta_harness/agents/evaluator.py  (read it to know what to
    DELETE in the cutover; do NOT mirror its prompt shape into the
    new orchestrator)
14. src/meta_harness/processes/run_loop.py  (rewire its evaluator
    call site to the new orchestrator-backed evaluate())
15. tests/unit/test_pipeline_stage_4.py
16. tests/unit/test_pipeline_orchestrator.py
17. tests/unit/test_pipeline_cutover.py
18. tests/integration/test_pipeline_e2e.py

Do not re-read or re-derive the gate. The tests are the contract.
If you think a test is wrong, surface it instead of softening the
implementation to match.

Then implement under src/meta_harness/agents/pipeline/:
- stage_4.py — cross-session gap observation production from the
  merged stage 1a + stage 3 outputs across the corpus. Writes gap
  records via the existing side-effect path; honours append-only
  and the matched-gap-id merge rule from gap-record.md. Cache
  namespace: stage-4. Expose STAGE_4_PROMPT_VERSION.
- orchestrator.py — new evaluate(sessions, repo, model, ...) that
  runs 1a → 1b → 2 → 3 → 4, surfaces per-stage progress to
  .meta-harness/logs/eval/<timestamp>/stages/, applies partial-
  with-flag failure propagation, and persists per-stage
  checkpoints for cheap resume.

Then perform the cutover:
- Replace src/meta_harness/agents/evaluator.py's evaluate() with a
  thin shim that delegates to orchestrator.evaluate(), OR remove
  evaluator.py entirely and update callers to import the new
  evaluate() directly. Either is fine; pick the one that minimises
  churn at the call sites.
- Delete the pre-pipeline batching helpers: _split_into_batches,
  _chunk_large_sessions, _evaluate_batch,
  _format_sessions_for_prompt, _build_batch_prompt. They MUST NOT
  appear under src/ after this session.
- Delete the old Human:/Assistant: conversational prompt shape
  from anywhere under src/meta_harness/agents/pipeline/.
- Update src/meta_harness/processes/run_loop.py if its call to
  evaluate() needs new argument plumbing.

Architectural constraint: do NOT import claude_runner from any
pipeline module except runner.py. The AST scan from step 13 still
enforces this.

Cross-cutting cautions (from CLAUDE.md) to keep live:
- No scalar grades anywhere.
- Agent context isolation — each Runner.invoke is a fresh
  subprocess.
- Append-only — caches AND gap records. Stage 4 must never delete
  gap records or destructively rewrite evidence.
- Plain markdown / JSON — no decorative formatting.

Iterate until
  PYTHONPATH=src python3.11 -m pytest tests/ -v
is fully green (the full suite, not just the new tests — the
cutover touches existing call sites). Use /usr/bin/python3 if
python3.11 resolves to a Python without pytest installed.

Commit: "feat: step 15 evaluator pipeline stage 4 + orchestrator
+ cutover — implementation"
Do not amend any existing commits. Do not run any git reset or git
push.
```

### 15V — Verification subagent

```
You are a verification subagent for Step 15 of the meta-harness build.
This is the final step of the post-0-1 pipeline refactor and the
cutover from the old single-call evaluator. Your only job is to
read the spec, the gate criteria, and the implementation, then
return a written sign-off or a drift list. You have no implementer
context. Do not read any prior session transcripts.

Read these files, in this order:
1. docs/spec/03-agents/evaluator.md
2. docs/spec/01-data-structures/evaluator-output.md
3. docs/spec/01-data-structures/gap-record.md
4. docs/PLAN.md  (Step 15 gate criteria only)
5. tests/unit/test_pipeline_stage_4.py
6. tests/unit/test_pipeline_orchestrator.py
7. tests/unit/test_pipeline_cutover.py
8. tests/integration/test_pipeline_e2e.py
9. src/meta_harness/agents/pipeline/stage_4.py
10. src/meta_harness/agents/pipeline/orchestrator.py
11. src/meta_harness/agents/pipeline/cache.py  (to confirm stage 4
    cache namespacing and resume behaviour)
12. src/meta_harness/processes/run_loop.py  (Phase 4 call site)
13. src/meta_harness/agents/evaluator.py if it still exists (only
    to confirm the old batching code paths are gone)

Gate criteria (HARD — from docs/PLAN.md Step 15):
1. Orchestrator sequences 1a → 1b → 2 → 3 → 4 correctly with
   mocked stages.
2. Partial failure in any stage propagates a partial_completion
   flag to the affected session's narrative without aborting the
   run.
3. Cache-resume: identical inputs → zero model calls; one new
   session → only that session's 1a/1b/2/3 re-run plus corpus-
   level 4.
4. End-to-end test with mocked stages produces a 4-key document
   matching the spec schema (per_turn_observations,
   pass_classifications, gap_observations, session_narratives).
5. Cutover regression: _split_into_batches,
   _chunk_large_sessions, _evaluate_batch,
   _format_sessions_for_prompt, _build_batch_prompt are absent
   from src/. The old Human:/Assistant: conversational prompt
   shape is absent from src/meta_harness/agents/pipeline/.
6. Gap record writes by stage 4 satisfy
   docs/spec/01-data-structures/gap-record.md (append-only, no
   deletions, matched_gap_id merge rule, consistent counters).

Cross-cutting cautions to flag if violated:
- Any scalar grade (quality score, confidence, priority) anywhere
  in the orchestrator, stage 4, or the final output.
- A pipeline module other than runner.py importing claude_runner.
- Destructive cache or gap-record writes.
- The old Human:/Assistant: prompt shape sneaking into the new
  orchestrator or stage 4 prompts.
- A caller of the old evaluate() that was not rewired to the new
  orchestrator-backed evaluate() and is now broken.

Your output must be SIGN-OFF or DRIFT LIST.
Do not run the tests. Read the code and reason against the spec.
```
