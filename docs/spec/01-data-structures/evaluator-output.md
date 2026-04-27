# Evaluator output

## Role

The evaluator produces a structured report of a session window. The report is
the proposer's primary input. It contains per-turn observations, pass
classifications, gap observations, and session-level navigation aids. It
contains no scalar grades and no recommendations.

## Inputs

- A session window: list of session identifiers to process.
- Access to the knowledge base for matching gap observations against
  existing gap records.
- Access to tools (tests, file reads, linters) to verify claims about
  session outputs.

## Outputs

The evaluator produces one report per run, covering the full window.
Components of the report:

- Per-turn observations, exhaustive over the window.
- Pass classifications, non-overlapping, covering every turn.
- Gap observations, one per pattern identified in the window.
- Session narratives, one per session, for navigation.

As a side effect of producing the report, the evaluator writes to gap
records (creating new ones, updating existing ones) in the knowledge base.

## Schema

### Per-turn observation

Exhaustive: every turn in every session in the window has an observation.

- **session_id**
- **turn_index**: zero-indexed position in the session.
- **assessment**: prose description of what happened at this turn: what
  Claude did, what it read or modified, what the human said, what the
  result was. Descriptive, not judgmental.
- **effort_signal**: observed directly from the session log:
  - `tokens_used`: total tokens consumed on this turn.
  - `model`: which model handled this turn.
  - `context_occupancy`: approximate context window usage at this turn.
  - `tool_calls`: list of tool names called and counts.
- **flags**: list of zero or more of:
  - `hard_gate_failure`: with a description (which gate, tool-verified).
  - `pass_start`: this turn begins a new pass.
  - `pass_end`: this turn ends a pass.
  - Any other flag the evaluator's behavioral spec instructs it to surface.
- **tool_verifications**: if the evaluator ran tools while examining
  this turn, the tool name and its output. Supports assertions in
  `assessment`.

### Pass classification

Non-overlapping, covering every turn in every session.

- **session_id**
- **turn_range**: start and end turn indices (inclusive).
- **pass_type**: one of:
  - `successful_one_shot`: length 1, produced acceptable output.
  - `refinement`: human accepted the first output and extended the task.
    Normal workflow, not a gap signal.
  - `clarification`: the human provided more information the harness
    could have asked for. Indicates the harness failed to disambiguate.
  - `correction`: the human redirected to a different approach. Indicates
    the harness's understanding of the task was wrong.
  - `retry`: the human asked for another attempt without specifying
    direction. Indicates the output was too unacceptable to even correct.
- **harness_gap_rationale**: prose framed as "what could the harness have
  done differently to prevent or shorten this pass." This is the lens from
  which pass type is assigned; it is not a judgment of human or Claude but
  of harness gaps.
- **contributing_gaps**: list of gap record identifiers this pass
  contributes evidence to, or `null` if this pass is `successful_one_shot`
  or `refinement`.

### Gap observation

One per pattern identified in the window.

- **matched_gap_id**: if this observation matches an existing gap record,
  its identifier; `null` if this is a new pattern.
- **characterization**: if new, the prose characterization that will
  become the new record's `characterization` field; if matched, may be
  `null` or contain a short refinement note.
- **kind**: label for this pattern. Matched to an existing kind when
  reasonable; new label only when no existing kind applies.
- **evidence_additions**: list of evidence pointers to append:
  - `session_id`
  - `turn_range`
  - `magnitude`: per-occurrence cost (turns, tokens, correction required).

### Session narrative

One per session in the window. For navigation, not for inference.

- **session_id**
- **outcome**: one of: `successful_and_accepted`, `successful_with_friction`,
  `abandoned`, `ongoing`.
- **pass_counts_by_type**: counts of each pass type in this session.
- **gaps_observed**: list of gap record identifiers touched by this
  session (new or updated).
- **narrative**: short prose describing the session's shape, written to
  be searchable. Not a conclusion; a navigational cue.

## Invariants

- The report is exhaustive over the window. Every turn has an observation.
  Every pass has a classification. Every session has a narrative.
- Every claim with `assessment` or `narrative` prose has supporting evidence
  present in `effort_signal`, `flags`, `tool_verifications`, or other
  observations.
- Pass classifications within a single session are non-overlapping and
  cover every turn. Every turn belongs to exactly one pass.
- No scalar grades anywhere in the output.
- No recommendations or proposals anywhere in the output.
- No aggregate quality scores at the session level.
- `contributing_gaps` is `null` only for `successful_one_shot` and
  `refinement` passes.
- Every `session_id` in the report belongs to the window.
- Every `matched_gap_id` in a gap observation resolves to a real gap
  record that existed before this run.
- Gap records created or updated by this report are reachable in the
  knowledge base after the evaluator completes.

## Explicitly excluded

- No quality scalars at any level.
- No confidence values.
- No recommendations or proposals.
- No aggregate scoring of sessions or configurations.
- No cross-session synthesis. Cross-session patterns that do not accumulate
  into gap records are left for the summary layer to surface.
- No scoring of the current configuration. Configurations are not directly
  scored; they are measured by the downstream behavior of their decisions.

## Cross-references

- Evidence pointer shape is shared with gap records:
  `01-data-structures/gap-record.md`.
- Session source format: `02-storage/session-logs.md`.
- Gap record updates as side effect: `01-data-structures/gap-record.md`
  and `03-agents/evaluator.md`.
- The proposer consuming this report: `03-agents/proposer.md`.
- The evaluator's behavioral spec (how it decides what to observe, what
  patterns to look for, what verifications to run): `03-agents/evaluator.md`.
