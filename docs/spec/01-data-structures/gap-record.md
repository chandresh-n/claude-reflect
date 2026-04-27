# Gap record

## Role

A gap record tracks a recurring pattern of observable quality-or-effort
inefficiency across sessions. Gap records are the primary unit on which the
proposer prioritizes proposals. They accumulate over time: new occurrences
increment existing records, new patterns create new records. Records are
append-only in existence (never deleted) and mostly append-only in content
(evidence grows; status transitions; characterization refines).

## Inputs

- The evaluator identifies gap patterns in session logs and writes to gap
  records (creating new ones, updating existing ones).
- Maintenance reads gap records to reconcile near-duplicate `kind` labels
  and to transition stale records.
- The proposer reads gap records for prioritization and writes to
  `related_proposals` when it creates proposals citing them.

## Outputs

Gap records are stored as records in the knowledge base. Their shape is
specified below. Consumers read them directly; gap records are not
synthesized into markdown (unlike the summary layer).

## Schema

Every gap record has these fields:

- **identifier**: stable, unique reference used across runs. Treat as
  opaque; consumers do not parse it.

- **characterization**: natural-language description of this inefficiency
  pattern. Written by the evaluator when the record is first created; may be
  refined on subsequent observations if the pattern has evolved. Prose,
  one to three sentences.

- **kind**: free-form label assigned by the evaluator (e.g.,
  `correction-required`, `wasted-model-effort`). Vocabulary is not fixed;
  the evaluator is prompted to reuse existing kinds when reasonable and
  introduce new ones only when no existing kind honestly applies.
  Maintenance reconciles near-duplicates on its passes.

- **first_observed_at**: timestamp of the first observation contributing
  to this record.

- **last_observed_at**: timestamp of the most recent observation. Always
  equals the maximum timestamp across all evidence pointers.

- **occurrence_count**: total number of observations. Equals the length
  of `evidence`.

- **evidence**: list of evidence pointers. Each element:
  - `session_id`: the session in which this occurrence was observed.
  - `turn_range`: start and end turn indices (inclusive) within that
    session.
  - `magnitude`: structured summary of the cost of this occurrence:
    additional turns, additional tokens, whether human correction was
    required, any other per-occurrence observations the evaluator recorded.

- **status**: one of:
  - `open`: currently being observed, not addressed.
  - `partially_addressed`: at least one proposal targeting this gap has
    been accepted, but its prediction has not yet been verified.
  - `addressed`: a proposal targeting this gap has been accepted and its
    prediction has been verified as holding. (Deferred: prediction
    verification is not yet implemented; this status is reachable only
    once the verification loop is built.)
  - `stale`: the gap has not been observed in the last N sessions (N is a
    maintenance configuration parameter) and nothing explicitly fixed it.
    Set by maintenance.

- **related_proposals**: list of proposal identifiers that have cited
  this gap. Appended at proposal creation time (not at decision commit).
  Proposals that are later rejected remain in this list; the proposer
  looks up each identifier in the decisions log to see the outcome.

## Invariants

- Append-only: gap records are never deleted.
- `occurrence_count` equals the length of `evidence`.
- Every evidence pointer's `session_id` resolves to a real session in the
  knowledge base.
- Every evidence pointer's `turn_range` is valid within its session.
- `last_observed_at` always equals the maximum timestamp across `evidence`.
- Evidence pointers from the same session do not overlap in `turn_range`.
  The evaluator merges contiguous observations within a session.
- `kind` is populated; may be changed by maintenance during reconciliation.
- `related_proposals` entries are appended at proposal creation and are
  never removed. Whether each proposal was accepted, rejected, or
  author-failed is determined by looking it up in the decisions log.
- Status transitions follow the state diagram:
  - `open` → `partially_addressed` (on accepted proposal targeting this gap)
  - `open` → `stale` (by maintenance, if not observed for N sessions)
  - `partially_addressed` → `addressed` (on prediction verification; deferred)
  - `partially_addressed` → `open` (on reversion of addressing decision)
  - Any status → `open` (if a new observation matches a `stale` record)

## Explicitly excluded

- No severity score or confidence value. Frequency, recency, and magnitude
  are tracked separately and weighed by the proposer; a single composite
  score would flatten them.
- No task-type classifier. Task-type variation flows through evidence
  naturally and may be surfaced by the summary layer; it is not a schema
  field.
- No proposed fix. Gap records describe problems, not solutions. Solutions
  live in proposals.
- No evaluator recommendation. The evaluator identifies and characterizes;
  it does not suggest how to fix.

## Cross-references

- Evidence pointers reference session logs: `02-storage/session-logs.md`.
- `related_proposals` entries resolve in the decisions log:
  `02-storage/decisions-git.md` and `01-data-structures/decision-record.md`.
- The evaluator's writes to gap records: `03-agents/evaluator.md`.
- The proposer's reads: `03-agents/proposer.md`.
- Status transitions by maintenance: `04-processes/maintenance.md`.
