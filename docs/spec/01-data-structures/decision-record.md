# Decision record

## Role

A decision record is the committed record of a proposal plus the human's
response. Every proposal becomes exactly one decision record, regardless of
whether it was accepted, rejected, or failed at authoring. Decision records
are tracked in git on a dedicated branch and are the canonical temporal
history of the claude-reflect's choices.

## Inputs

Created by the run loop at Phase 8 (decision commit) or at Phase 5b (if the
author fails). Written by the skill, not by any agent.

## Outputs

Committed to git on the decisions branch. Queryable via standard git tooling:
`git log`, `git show`, `git blame`, `git log --grep`.

## Schema

- **proposal_id**: stable identifier assigned at proposal creation. Does
  not change across the proposal's lifecycle.
- **run_id**: the run that generated this proposal.
- **batch_id**: the batch this proposal belonged to.
- **created_at**: when the proposer generated the proposal.
- **reviewed_at**: when the human acted on the proposal. `null` if status
  is `pending`. Matches the author-failed timestamp if status is
  `author_failed`.

- **status**: one of:
  - `accepted`: human accepted; diff was merged into the active
    configuration.
  - `rejected`: human rejected; diff was not merged.
  - `pending`: presented to the human but not yet acted on.
  - `superseded`: a later decision has replaced the state produced by
    this one.
  - `author_failed`: the author agent could not produce a valid diff;
    proposal never reached human review.

- **human_reasoning**: prose from the human captured during review.
  Required when `status` is `rejected`. Optional when `status` is
  `accepted`. Absent when `status` is `pending` or `author_failed`.

- **author_failure_reason**: prose from the author agent explaining why
  it could not produce a valid diff. Present only when `status` is
  `author_failed`.

- **why**: the evidence section from the proposal:
  - `cited_gaps`: list of gap record identifiers targeted, each with a
    note on how the proposal addresses that gap.
  - `cited_sessions`: list of session identifiers and turn ranges the
    proposer drew on.
  - `cited_prior_decisions`: list of decision identifiers the proposer
    considered, with notes on the relationship (builds on, differs from,
    supersedes).
  - `prose_summary`: short paragraph pulling the above together for the
    human.

- **what**: the change itself:
  - `diff_reference`: git commit or branch containing the proposed diff.
    Populated by the author agent; `null` if `status` is `author_failed`.
  - `files_touched`: list of file paths affected by the diff.
  - `short_description`: one-line summary of the mechanical change.

- **how**: prose explaining the mechanism by which the change acts on
  future sessions.

- **prediction**: prose articulating the expected impact. What should
  change if this is accepted, over what window. Not required to be
  structured or machine-verifiable.

- **prediction_outcome**: reserved for a future validation loop:
  - `status`: one of `not_yet_due`, `overdue`, `held`, `not_held`,
    `inconclusive`. Starts at `not_yet_due`; transitions to `overdue`
    when the measurement window specified in the prediction has passed
    without a verification run; transitions to `held` / `not_held` /
    `inconclusive` when verification runs. Verification loop is deferred;
    until it is built, the status will not move past `not_yet_due` or
    `overdue`.
  - `evidence`: pointers to sessions in the measurement window used for
    verification. `null` until verification runs.
  - `commentary`: prose from the verifying run. `null` until verification
    runs.

- **targeted_gaps**: list of gap record identifiers the proposal cited.
  Redundant with `why.cited_gaps` but kept as a first-class field for
  cheap queries (`git log --grep "targeted_gap: G-73"`).

- **authoring_addendum**: the structured specification the proposer
  produced for the author. Not human-facing. Kept for audit and future
  learning. Shape specified in `01-data-structures/proposal.md`.

- **structural_tags**: classifiers for searchability:
  - `change_type`: one of `addition`, `modification`, `removal`,
    `restructuring`. Bookkeeping only; not load-bearing for forced-novelty.
  - `surface`: one of `claude_md`, `skill`, `agent`, `hook`, `settings`,
    `mcp`.
  - `novelty_status`: one of `normal`, `forced_novelty`, `null_baseline`.
  - `exploration_rationale`: prose, present only when `novelty_status` is
    `forced_novelty` or `null_baseline`. Describes what region is being
    probed and why.

- **superseded_by**: decision identifier of the decision that superseded
  this one. Populated only when `status` is `superseded`. `null`
  otherwise.

## Invariants

- Every decision has a `proposal_id` matching exactly one proposal.
- Decisions with `status = accepted` have non-null `diff_reference` and
  `reviewed_at`.
- Decisions with `status = rejected` have non-null `human_reasoning` and
  `reviewed_at`.
- Decisions with `status = author_failed` have non-null
  `author_failure_reason`, `reviewed_at`, and `diff_reference = null`.
- Decisions with `status = superseded` have non-null `superseded_by`.
- Decisions with `status = pending` have `reviewed_at = null` and
  `human_reasoning = null`.
- Every `targeted_gaps` entry resolves to a real gap record.
- Every `cited_sessions` entry resolves to a real session.
- Every `cited_prior_decisions` entry resolves to a real earlier decision.
- Once committed, only `status` (when transitioning to `superseded`) and
  `prediction_outcome` fields can be updated. All other fields are
  immutable post-commit.
- `prediction_outcome.status` transitions follow the state diagram:
  - `not_yet_due` → `overdue` (time passes without verification)
  - `not_yet_due` → `held` / `not_held` / `inconclusive` (verification)
  - `overdue` → `held` / `not_held` / `inconclusive` (verification)
  - No backwards transitions.

## Explicitly excluded

- No internal proposer deliberation traces. Only the finalized proposal is
  committed. Alternatives considered at proposal time are not preserved in
  the decision record (they may live in the proposer's run-level commit
  message separately).
- No evaluator view of the proposal. The evaluator does not evaluate
  proposals.
- No formal dependency graph between decisions. Dependencies are implicit.
- No separate effort-vs-quality prediction fields. Prediction is prose.
- No machine-verifiable prediction requirement today. The schema preserves
  the verification slot for future use.

## Cross-references

- Committed to the decisions branch in git: `02-storage/decisions-git.md`.
- Originates from a proposal: `01-data-structures/proposal.md`.
- References gap records via `targeted_gaps` and `why.cited_gaps`:
  `01-data-structures/gap-record.md`.
- The `authoring_addendum` is consumed by the author:
  `03-agents/author.md`.
- Decision committed by run loop Phase 8: `04-processes/run-loop.md`.
