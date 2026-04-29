# Session prompts

Pre-written prompts for every session of the 12-step build.
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
- [ ] 11A — Step 11 Session A
- [ ] 11B — Step 11 Session B
- [ ] 11V — Step 11 Verification subagent
- [ ] 12A — Step 12 Session A
- [ ] 12B — Step 12 Session B
- [ ] 12V — Step 12 Verification subagent

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
