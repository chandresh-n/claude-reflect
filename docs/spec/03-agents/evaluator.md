# Evaluator

## Role

The evaluator reads session logs and produces structured observations of
what happened. It does not grade, rank, or recommend. Its output is the
proposer's primary input and is the means by which the meta-harness
extracts signal from real work.

The evaluator is spawned as a separate agent with its own context. It
never shares context with the proposer. Isolation of context is
load-bearing: it prevents the self-evaluation bias that emerges when a
single agent both generates and judges its own reasoning.

## Inputs

- A session window: a list of concrete session identifiers (resolved from
  a human-supplied date range by the skill).
- Access to the knowledge base, specifically:
  - Session logs for the window (read-only).
  - Existing gap records (for matching new observations against known
    patterns).
- Access to tools:
  - File read against the repository.
  - Test runner (to verify claims about test outcomes).
  - Linter (to verify claims about code quality gates).
  - Other Claude Code tooling as needed for verification.

## Outputs

- A full evaluation report, as specified in
  `01-data-structures/evaluator-output.md`.
- As side effects: writes to gap records in the knowledge base (creating
  new ones, updating existing ones' `evidence`, `occurrence_count`,
  `last_observed_at`, and `status` when moving from `stale` back to
  `open` on fresh observation).

## Behavior

### Processing order

The evaluator processes sessions in chronological order within the
window. Within each session, it processes turns in order. This order
matters for pass classification: a pass's classification depends on how
turns relate to each other in sequence.

### Per-turn observation generation

For every turn in every session, the evaluator:

1. Reads the turn's raw content from the session log: human input,
   assistant response, tool calls, token counts, model selection,
   context occupancy, compaction events.
2. Decides whether to run tools to verify claims (e.g., re-read a file
   Claude claimed to modify, run the test suite Claude claimed passed).
3. Writes an assessment, prose description of what happened. The
   assessment must be grounded in what the evaluator directly observed
   from the log or verified via tools.
4. Records flags for specific events: hard gate failures (with the
   tool output that confirms them), pass boundaries.

### Pass classification

After observing turns, the evaluator identifies passes within each
session. A pass is a contiguous sequence of turns working on the same
sub-goal. The end of a pass is signaled by the human accepting or
redirecting.

Each pass is classified by type (`successful_one_shot`, `refinement`,
`clarification`, `correction`, `retry`) from the lens of "what could the
harness have done differently to prevent or shorten this pass." The
classification is not about the human's literal words but about what the
harness was missing. The `harness_gap_rationale` field captures this
framing for each pass.

### Gap identification and matching

As the evaluator processes sessions, it identifies patterns of
inefficiency: recurring behaviors, wasted turns, corrections of similar
kinds, hard gate failures sharing a cause. For each identified pattern,
the evaluator:

1. Checks whether the pattern matches an existing gap record in the
   knowledge base. Matching is by the evaluator's judgment, informed by
   the gap record's `characterization` and `kind`.
2. If matched: the gap record is updated (evidence appended, counters
   incremented). The evaluator's output includes a gap observation with
   `matched_gap_id` populated.
3. If unmatched: a new gap record is created. The evaluator writes the
   record's `characterization` and `kind`. The evaluator's output
   includes a gap observation with `matched_gap_id = null` and a new
   characterization.

Kind vocabulary discipline: the evaluator is prompted to reuse existing
kinds when a pattern reasonably matches. It introduces new kinds only
when no existing kind honestly applies. Near-duplicate kinds are
reconciled by maintenance on later passes; the evaluator's job is
discipline at observation time, not enforcement.

### Session narratives

For each session, the evaluator writes a session narrative summarizing
its shape. The narrative is written for searchability: another LLM
should be able to find this session by querying for its shape (e.g.,
"sessions where Claude struggled with file location"). Narratives are
not judgments; they are navigational aids.

## Behavioral directives (prompt-level, not schema)

These directives shape the evaluator's prompt. They are intentionally
general; specific guidance on what patterns to look for is left to the
prompt itself (which lives outside this spec, though the directives
constrain it).

- **Skepticism.** The evaluator looks for reasons a session went poorly,
  not reasons it went well. A session that completed successfully is
  examined for the friction along the way, not only the outcome.
- **Tool-backed verification.** When making a claim that can be
  verified (a test passed, a file was modified, an API exists), the
  evaluator uses tools to verify rather than accepting log assertions.
- **Evidence-grounded prose.** Every assessment and narrative has
  supporting evidence in the log or in tool output. No speculation
  presented as observation.
- **No grading.** The evaluator never produces a scalar quality score,
  a confidence value, or a ranking. Prose assessments are descriptive,
  not evaluative.
- **No recommendations.** The evaluator never suggests what should be
  done about what it observed. Suggestions are the proposer's job.
- **Exhaustive.** Every turn in every session has an observation. Every
  pass is classified. The evaluator does not selectively report.

## Invariants

- The evaluator never shares context with the proposer, with a different
  evaluator instance, or with any prior run.
- The evaluator is spawned fresh at each run.
- Every observation in the output is backed by evidence (log content,
  tool output) accessible to a subsequent auditor.
- Gap record writes by the evaluator respect the invariants in
  `01-data-structures/gap-record.md`: no deletions, non-overlapping
  evidence from the same session, consistent counters.

## Explicitly excluded

- Access to the proposer's prior output.
- Access to decisions the meta-harness has made (the evaluator does not
  need this context; the proposer does).
- Any ranking or scoring.
- Any proposal generation.

## Cross-references

- Output schema: `01-data-structures/evaluator-output.md`.
- Gap record writes: `01-data-structures/gap-record.md`.
- Session log reads: `02-storage/session-logs.md`.
- Run loop invocation: `04-processes/run-loop.md` (Phase 4).
