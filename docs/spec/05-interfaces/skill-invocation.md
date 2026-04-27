# Skill invocation

## Role

The meta-harness is exposed as a Claude Code skill. The human invokes
this skill when they want a reflective pass over recent sessions. The
skill is the orchestrator of the run loop (see
`04-processes/run-loop.md`) and the primary interface between the
human and the meta-harness.

The skill handles all setup transparently. First-time invocation in a
repository triggers the environment setup (Phase 1) silently.
Subsequent invocations are no-ops for setup. The human does not need to
know whether setup has happened.

## Inputs

The human provides:

- A date range for the session window. Accepted formats:
  - Absolute: two ISO dates (e.g., `2026-04-01 to 2026-04-07`).
  - Relative: natural phrases (`last 7 days`, `last week`,
    `since last run`, `since yesterday`).

If the skill is invoked without a date range, it prompts for one.

## Outputs

- The run's markdown batch document (opened in the human's editor).
- Terminal-visible diffs for proposals with successful authoring.
- A run summary at the end of Phase 9.

## Invocation

The skill is invoked by Claude Code's standard skill mechanism (e.g.,
`/meta-harness review` or equivalent). The specific command name and
mechanism are implementation choices. The spec requires only:

- The skill is discoverable via Claude Code's skill list.
- The skill accepts a date range argument (or prompts for one when
  missing).
- The skill can be interrupted (though interruption mid-run results
  in pending proposals, handled per Phase 2.5 on the next run).

## Relative date resolution

`since last run` resolves by finding the most recent Phase 9
completion in the decisions log and using its timestamp as the start
date.

`last N days` resolves to `(now - N days)` as start and `now` as end.

`last week` and similar natural phrases resolve by reasonable
interpretation (last calendar week, or rolling 7 days, depending on
implementation choice).

## Behavior across runs

- **First invocation in a repository:** Phase 1 runs setup. The human
  sees a brief status message but no blocking prompts. The skill then
  proceeds as normal.
- **Subsequent invocations:** Phase 1 is a no-op.
- **Invocation while a prior run is pending:** Phase 2.5 handles
  reconciliation. The human is asked how to handle pending
  proposals.
- **Invocation while a prior run crashed:** The skill detects the
  incomplete state (e.g., proposal branches without corresponding
  decisions) and offers to clean up or continue. Recovery behavior is
  implementation (the spec requires only that the skill detect and
  surface the condition, not silently proceed).

## Invariants

- The skill never modifies the repository outside the
  meta-harness's designated scope (the knowledge base directory and
  the active configuration files).
- The skill reads no external resources (no network access).
- The skill produces no output that requires the human to use any
  tool other than their editor and terminal.

## Explicitly excluded

- No GUI. The skill's interface is markdown files and terminal
  output.
- No background invocation. The human triggers every run.
- No automatic re-invocation on schedule.
- No notification mechanisms (email, Slack, etc.).

## Cross-references

- Run loop: `04-processes/run-loop.md`.
- Human review interface: `05-interfaces/human-review.md`.
