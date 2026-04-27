# Session logs

## Role

Session logs are Claude Code's native record of each session: every tool
call, every turn, every token count, every compaction event. The
meta-harness reads them as ground truth. It never modifies them.

## Inputs

Produced by Claude Code during normal work. Located in Claude Code's
session log directory (platform-specific path; the skill discovers the
location at runtime).

## Outputs

Read by:

- The evaluator, as primary input for its report.
- The proposer, via evidence pointers in evaluator output and gap records.
- The human, indirectly through the proposer's citations and through
  direct inspection if they choose.

## Content

Each session is a JSONL file. The format is defined by Claude Code, not by
this spec. Relevant fields the meta-harness consumes:

- Session identifier.
- Timestamps (session start, session end, per-turn timestamps).
- Per-turn records including:
  - Human input.
  - Assistant response.
  - Tool calls with inputs and outputs.
  - Model selection.
  - Token counts.
  - Compaction events.
- Any context injection events.

The meta-harness does not depend on an exhaustive field list; consumers
(especially the evaluator) read the JSONL and extract what they need.
Format drift in Claude Code's logs may require the evaluator's behavioral
spec to be updated, but the schema of what the meta-harness produces does
not change.

## Session resolution

The skill resolves a human-supplied date range to session identifiers by
scanning the session log directory for files whose timestamps fall in the
range. All sessions in the range are included. No filtering is applied:
short sessions, aborted sessions, and otherwise-unusual sessions are data
and are passed to the evaluator.

## Invariants

- The meta-harness never writes to or deletes session logs.
- Every session identifier referenced in gap records, decision records,
  or evaluator output resolves to an existing session log file.
- If a session log file is deleted out-of-band (e.g., Claude Code's
  cleanup), references to it become dangling. This is a degraded state
  and the spec does not require the meta-harness to recover from it; the
  human can rebuild affected summary layer pages if needed.

## Explicitly excluded

- No filtering of sessions by quality, length, or other criteria before
  evaluation. Everything in the date range is processed.
- No modification or enrichment of session logs.
- No copying of session logs into the knowledge base. Session logs remain
  in Claude Code's directory; references are identifier-based.

## Cross-references

- Evidence pointer shape: `01-data-structures/gap-record.md` and
  `01-data-structures/evaluator-output.md`.
- The evaluator consuming session logs: `03-agents/evaluator.md`.
- Date range resolution as part of Phase 3 of the run loop:
  `04-processes/run-loop.md`.
