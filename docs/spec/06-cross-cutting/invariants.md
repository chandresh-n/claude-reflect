# System-wide invariants

Invariants that apply across multiple components. Each is listed with a
brief statement and pointers to the files that enforce or rely on it.

---

## Agent context isolation

The evaluator, proposer, and author never share context. Each is
spawned fresh at each run. Inter-agent communication happens through
durable state (disk, git, the knowledge base), not through shared
in-memory context.

Enforced by:

- `03-agents/evaluator.md` (evaluator spec invariants).
- `03-agents/proposer.md` (proposer spec invariants).
- `03-agents/author.md` (author spec invariants).
- `04-processes/run-loop.md` (phase transition invariants).

Rationale: prevents self-evaluation bias and preserves the integrity
of the evaluator's observations as independent of the proposer's
generation.

---

## No scalar grades anywhere

No component produces a quality score, a confidence value, or a
ranking on a numeric axis. The graded composite is a conceptual notion
that emerges from the proposer's reasoning over evidence; it is not a
scalar any component computes.

Enforced by:

- `01-data-structures/evaluator-output.md` (output schema).
- `01-data-structures/gap-record.md` (schema excludes severity).
- `01-data-structures/archive-entry.md` (schema excludes quality
  scores).
- `03-agents/evaluator.md`, `03-agents/proposer.md`,
  `03-agents/author.md`, `04-processes/maintenance.md` (behavioral
  directives).

Rationale: scalar grades from LLM judges drift toward the mean over
long runs. The evaluator does not have the global scope needed to
grade responsibly. Grading is a proposer-level inference over
evidence, not a first-class field.

---

## Canonical vs. synthesis

Sessions, decisions, gap records, and archive entries are canonical.
The summary layer is synthesis. Agents making decisions that depend on
precise current state read canonical layers directly. The summary
layer is for orientation, navigation, and semantic retrieval, never
authoritative for judgments.

Enforced by:

- `02-storage/knowledge-base.md`.
- `02-storage/summary-layer.md`.
- `03-agents/proposer.md` (behavioral directives).

Rationale: the summary layer is a cache, regenerable and regenerated
on maintenance passes. Making authoritative decisions from it risks
staleness. The canonical layers are the source of truth.

---

## Append-only with allowed updates

The knowledge base is append-only in existence: nothing is deleted.
Specific fields on specific records are allowed to update:

- Gap records: `evidence` grows; `occurrence_count` increments;
  `last_observed_at` moves forward; `status` transitions; `kind`
  changes on reconciliation; `related_proposals` appends.
- Decision records: `status` transitions to `superseded`;
  `prediction_outcome` transitions forward.
- Archive entries: `region_markers.sessions_measured` grows during
  the entry's `active_at` window; `qualitative_position` populates
  once on first post-closure maintenance.

All other fields are immutable post-commit.

Enforced by the invariants in each data structure's spec.

Rationale: the system's memory must not rewrite history. Reversion
happens through new decisions that supersede, not through editing old
ones.

---

## Evidence-grounded claims

Every factual claim produced by any component cites the evidence
supporting it. Evaluator observations cite session+turn pointers.
Proposer rationales cite gaps, sessions, and prior decisions. Summary
layer pages cite canonical sources. Human reasoning is prose and
treated as authoritative from the human's perspective (no citations
required from them).

Enforced by:

- `01-data-structures/evaluator-output.md`.
- `01-data-structures/proposal.md`.
- `02-storage/summary-layer.md`.

Rationale: every claim should be auditable. A future reader, human
or agent, can follow the citation back to evidence.

---

## Regenerability

The summary layer is fully regenerable from the canonical layers.
Dropping the summary layer and rebuilding produces an equivalent (up
to LLM nondeterminism in prose) layer.

Gap records and archive entries are in principle reconstructible from
canonical sources (sessions plus decisions), though the rebuild is
expensive and not a routine operation.

Session logs are never rebuilt; they are Claude Code's output,
treated as external ground truth.

Enforced by:

- `02-storage/knowledge-base.md`.
- `02-storage/summary-layer.md`.
- `04-processes/maintenance.md`.

Rationale: synthesis can drift or corrupt; the ability to rebuild
prevents drift from becoming permanent.

---

## Human as reviewer, not judge

The human's judgment is required at exactly one point in the run
loop: Phase 7, reviewing proposals. All other judgments, what to
observe, what patterns matter, what to propose, happen without human
input. The human accepts or rejects; they do not produce signal the
system otherwise depends on.

Enforced by:

- `04-processes/run-loop.md` (phase structure).
- `05-interfaces/human-review.md`.

Rationale: the system's premise is that the human is one of the
components being optimized around, not the judge. If the human were
the judge, the ceiling would be their taste and throughput. Human as
reviewer keeps them load-bearing only at the decision boundary.

---

## Exhaustive over the window

The evaluator's report is exhaustive over the session window. Every
turn in every session has an observation. Every pass is classified.
No selective reporting.

Enforced by `01-data-structures/evaluator-output.md` and
`03-agents/evaluator.md`.

Rationale: the proposer's trust in the report requires that absence
of a flag means absence of the phenomenon, not that the evaluator
skipped it.

---

## One archive entry active at a time

At any moment, exactly one archive entry has `active_at.end = null`.
This is the currently-active configuration. When an accepted proposal
produces a new state, the new entry opens its `active_at` and the
prior entry's `active_at.end` closes at the same moment.

Enforced by `01-data-structures/archive-entry.md` and
`04-processes/run-loop.md` (Phase 8).

Rationale: supports clean supersession semantics and
time-range-based queries over the archive.
