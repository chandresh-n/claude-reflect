# Decisions (git branch)

## Role

The decisions git branch is the canonical temporal record of every proposal
the meta-harness has ever generated and every human response. It is the
audit trail. Provenance, reversion, and inspection work through standard
git tooling.

The active configuration branch is a separate branch where accepted
proposals merge their diffs. The decisions branch tracks the records of
what was proposed and what the human decided. The active configuration
branch tracks the actual configuration content over time.

## Inputs

Written by the run loop at Phase 5a (commit proposer's intent records),
Phase 5b (commit author-failed events), and Phase 8 (commit final
decision records).

## Outputs

Read by:

- The proposer (via canonical record reads and via git log for temporal
  queries).
- Maintenance (for rebuilding summary layer pages that reference
  decisions).
- The human (via normal git tooling).

## Branch structure

Two git branches are relevant:

- **decisions branch.** A dedicated branch (e.g., named `meta-harness/decisions`)
  that holds decision records as commits. Each decision is one or more
  commits on this branch. Commits may include structured data files
  (e.g., a markdown file or a JSON file per decision record), the exact
  format is implementation. The invariant is that every decision record
  is identifiable and queryable by its proposal_id via git.

- **active configuration branch.** The main working branch of the
  repository, where actual configuration files (`CLAUDE.md`, `.claude/`
  contents, etc.) are merged. Accepted proposals merge their diffs here.
  This branch is not meta-harness-specific; it is the normal configuration
  state Claude Code reads.

- **proposal branches.** Ephemeral. Created during run loop Phase 5b when
  the author produces a diff. Named by proposal_id. Either merged into
  the active configuration branch (on acceptance) or deleted (on
  rejection or author-failure) after the decision is committed.

## Commit conventions

Decisions-branch commits follow a convention that supports git-based
queries:

- Commit message includes a structured header with `proposal_id`,
  `run_id`, `status`, and `targeted_gaps`. This supports
  `git log --grep "targeted_gap: G-73"` and similar queries.

- Commit body carries the full decision record content in a consistent
  format (the schema from `01-data-structures/decision-record.md`).

- Proposer's run-level reasoning (the "considered N candidates, acted on
  M" summary) is a separate commit on the decisions branch, committed at
  the end of Phase 5a. Its commit message names the run_id and
  enumerates candidate gaps considered vs. acted on.

- Maintenance log entries may also commit to the decisions branch (or a
  separate maintenance branch; implementation choice) for auditability.

## Invariants

- Every decision record is reachable via its `proposal_id`.
- The decisions branch is append-only in practice: decisions are not
  rewritten after commit. The only post-commit updates are the two
  allowed field transitions (`status` to `superseded`, and
  `prediction_outcome`), which are recorded as new commits amending or
  referencing the original (implementation chooses the pattern).
- Every accepted decision's `diff_reference` points to a commit that
  exists on the active configuration branch (the merge commit).
- Rejected and author-failed decisions have no corresponding merge on
  the active configuration branch.

## Explicitly excluded

- No rebasing or history rewriting on the decisions branch.
- No squashing of decision commits. Every decision is visible in git
  history.
- No tagging scheme is required by the spec (though implementations may
  choose to tag archive entries for faster reference).

## Cross-references

- Decision record schema: `01-data-structures/decision-record.md`.
- Archive entries reference commits on the active configuration branch:
  `01-data-structures/archive-entry.md`.
- The run loop's use of git operations: `04-processes/run-loop.md`.
- Maintenance log entries: `04-processes/maintenance.md`.
