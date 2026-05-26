# Run loop

## Role

The run loop orchestrates a single invocation of the claude-reflect. It
sequences the phases that read sessions, run the evaluator, generate
proposals, realize them as diffs, present them to the human, capture
decisions, and commit outcomes. The skill is the orchestrator. Each
phase involving an agent spawns a fresh agent instance with its own
context.

The run loop is sequential. Phases execute in order. A phase cannot
begin before its predecessor's end state has been reached.

## Inputs

Triggered by human invocation of the claude-reflect skill. The human
provides a date range.

## Outputs

Per run:

- One evaluation report (on disk).
- One proposal batch (possibly empty, possibly containing
  author-failed proposals alongside successful ones).
- One set of decision records (one per proposal, on the decisions
  branch).
- One set of archive entries (one per accepted proposal).
- One run summary (the human's receipt).
- Possibly one or two maintenance log entries (from Phase 2 and/or
  Phase 9).

## Phases

### Phase 0: Skill invocation

The human invokes the claude-reflect skill (e.g.,
`/claude-reflect review`). The skill prompts for or receives a date
range. Date ranges may be absolute (`2026-04-01` to `2026-04-07`) or
relative (`last 7 days`, `since last run`).

*End state:* skill holds a valid date range.

### Phase 1: Environment setup

The skill checks whether the knowledge base is initialized in the
current repository. If not, a shell script runs to set up:

- Create the knowledge base directory structure.
- Initialize the decisions git branch.
- Initialize the summary layer directory with an empty index.
- Write any bootstrap configuration.

If the knowledge base exists, this phase is a no-op.

*End state:* knowledge base exists and is queryable.

### Phase 2: Maintenance check

The skill checks whether maintenance should run (content thresholds
crossed since last pass). If yes, maintenance runs
(`04-processes/maintenance.md`). The human is not interrupted; the
maintenance log is available for later inspection.

*End state:* summary layer is current within one maintenance cycle.

### Phase 2.5: Pending proposal check

The skill queries the decisions log for proposals with status
`pending` from prior runs. If any exist, the skill asks the human:

> "There are N pending proposals from prior runs. Resolve them first,
> include them in this run's batch, or defer?"

- **Resolve first:** the skill re-presents the pending proposals as
  their own batch, advances through Phase 6 and Phase 7 with them,
  commits decisions at Phase 8. Then proceeds to Phase 3 for the
  current run's new window.
- **Include:** the pending proposals are added to this run's batch at
  Phase 6.
- **Defer:** pending proposals remain pending; this run proceeds
  without them.

*End state:* pending proposals handled per the human's choice.

### Phase 3: Window resolution

The skill resolves the date range to concrete session identifiers by
scanning Claude Code's session log directory. All sessions in the
range are included. No filtering.

Validation:

- At least one session found. If zero, the skill reports this and
  offers to expand the range or abort.
- Sessions are readable.
- If the window is very large (above a soft threshold), the skill
  warns and asks for confirmation.
- If the window is very small (below a soft threshold), the skill
  warns that signal may be weak.

*End state:* concrete list of session identifiers, confirmed.

### Phase 4: Evaluation

The evaluator is spawned as a fresh agent
(`03-agents/evaluator.md`). It receives:

- The list of session identifiers.
- Access to the knowledge base (read existing gap records for
  matching).
- Access to verification tools.

It produces the evaluation report and writes to gap records as side
effect. The report is persisted to disk for the proposer to read.

*End state:* evaluation report on disk; gap records updated.

### Phase 5a: Intent generation (proposer)

The proposer is spawned as a fresh agent (`03-agents/proposer.md`). It
receives:

- The evaluation report for this run (read-only).
- Access to the full knowledge base.
- The run metadata (run_id, batch_id).

It produces a batch of proposal intents: rationale, structural tags,
authoring addendum for each. It writes:

- `proposal_id` to the `related_proposals` list of each cited gap
  record (before Phase 5b begins).
- A run-level commit on the decisions branch summarizing the
  candidate analysis.

If the batch is empty (no gaps worth addressing, no forced-novelty
due), Phase 5b is a no-op and Phase 6 presents an empty batch.

*End state:* proposal intents produced. No diffs yet.

### Phase 5b: Diff authoring (author, per proposal)

For each proposal in the batch:

1. An author is spawned fresh (`03-agents/author.md`).
2. The author receives the single proposal's intent and access to the
   current configuration state.
3. The author produces a git diff on a branch named by `proposal_id`,
   or reports an `author_failure_reason`.

Author invocations are independent and may run in parallel if
orchestration supports it.

For each proposal:

- On success: `what.diff_reference` and `what.files_touched` are
  populated.
- On failure: the proposal is marked for `author_failed` status at
  Phase 8; `author_failure_reason` is captured.

*End state:* every proposal either has a diff reference or has a
failure reason.

### Phase 6: Presentation

The skill renders the proposal batch for the human. Two artifacts are
produced:

- A markdown document with per-proposal sections: title, rationale
  (why / what / how / prediction), and an acceptance mechanism
  (interface concern, see `05-interfaces/human-review.md`).
- Terminal-visible diffs for proposals with successful authoring.
  Author-failed proposals appear in the markdown with their failure
  reason and no diff; the human cannot accept them (they will be
  recorded as `author_failed` regardless of any human input, since
  there is no diff to merge).

If Phase 2.5 resulted in "include" pending proposals, they appear in
this batch's markdown alongside the new ones.

*End state:* markdown and diffs visible to the human.

### Phase 7: Human review

The human reviews each proposal. For each, the human records a
decision: accept, reject, or defer (leaving the proposal pending).
Rejections require a reason. Acceptances may optionally include a
note.

The human may pause: save their progress (partial decisions) and
resume in a later run via Phase 2.5.

*End state:* every proposal has a recorded decision or is explicitly
left pending.

### Phase 8: Decision commit

For each proposal in the batch:

- **Accepted proposals:**
  - The proposal's diff (from its proposal branch) is merged into the
    active configuration branch.
  - A decision record with status `accepted` is committed to the
    decisions branch. All proposal fields propagate to the decision
    record.
  - A new archive entry is created:
    - `git_reference` = the merge commit on the active configuration
      branch.
    - `produced_by_decision` = the new decision's identifier.
    - `active_at.start` = now.
    - The prior active archive entry's `active_at.end` = now.
    - `region_markers.sessions_measured` begins empty; it will
      accumulate as new sessions run.
  - The prior archive entry's `qualitative_position` is marked for
    generation on the next maintenance pass (remains `null` until
    then).

- **Rejected proposals:**
  - No merge.
  - Decision record with status `rejected`, including human_reasoning.
  - The proposal branch is deleted or marked for cleanup.

- **Author-failed proposals:**
  - Decision record with status `author_failed`, including
    `author_failure_reason`.
  - No merge, no archive entry, no proposal branch to clean up.

- **Pending proposals (from explicit human pause):**
  - Decision record with status `pending`. No reviewed_at, no
    human_reasoning.
  - The proposal branch is preserved until the proposal is resolved.

*End state:* decisions committed. Active configuration reflects
accepted changes. Archive updated.

### Phase 9: Run finalization

The skill writes a run summary:

- Window processed.
- Count of proposals generated, by status.
- Links to decision commits.
- Links to the evaluation report.

The skill rechecks the maintenance trigger. If Phase 4, 5a, or 8
produced enough new content to cross the threshold, a second
maintenance pass runs. Otherwise, maintenance is deferred to the next
run's Phase 2.

The run summary is presented to the human.

*End state:* run complete.

## Invariants

- Phases execute in order. A phase cannot begin before its
  predecessor's end state has been reached.
- Phase 4 (evaluator) and Phase 5a (proposer) never share context.
  The evaluator's output is written to disk and read by the proposer
  from disk; no in-memory handoff.
- Phase 5a completes before any Phase 5b invocation begins.
- Phase 5b invocations are independent (no shared context between
  author instances, no cross-proposal coordination).
- Every proposal generated in Phase 5a produces exactly one decision
  record in Phase 8 (or in Phase 5b for author-failed proposals).
- Accepted proposals produce exactly one archive entry each.
- At any moment, exactly one archive entry has `active_at.end = null`
  (the currently-active configuration).
- The run is atomic at the skill-invocation level: it either completes
  all phases, is explicitly paused at Phase 7, or crashes (in which
  case recovery is manual).

## Explicitly excluded

- No automatic re-running if a batch is rejected. The human invokes
  the skill again.
- No partial-phase recovery beyond explicit human pause at Phase 7.
- No background processing. All work happens while the human is
  waiting (with maintenance as synchronous side-effect at Phase 2
  and 9).
- No network access during the run. All reads and writes are local.
- No changes to session logs at any phase.

## Cross-references

- Skill invocation: `05-interfaces/skill-invocation.md`.
- Evaluator: `03-agents/evaluator.md`.
- Proposer: `03-agents/proposer.md`.
- Author: `03-agents/author.md`.
- Maintenance: `04-processes/maintenance.md`.
- Human review: `05-interfaces/human-review.md`.
- All data structures referenced in the phases: see
  `01-data-structures/`.
