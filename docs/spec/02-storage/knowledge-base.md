# Knowledge base

## Role

The knowledge base is the claude-reflect's persistent state. It lives in the
repository being optimized. Four layers, organized by authoritativeness:
session logs (immutable source), decisions (git-tracked canonical temporal
record), gap records and archive entries (structured records), and the
summary layer (regenerable synthesis). The canonical layers are the
source of truth. The summary layer is a view.

## Inputs

- Session logs arrive from Claude Code's normal operation, in Claude Code's
  session log directory.
- Decisions, gap records, and archive entries are written by the run loop,
  the evaluator, and the proposer.
- The summary layer is written exclusively by maintenance.

## Outputs

The knowledge base as a whole is queried by:

- The evaluator (reads sessions; reads and writes gap records).
- The proposer (reads all canonical layers and summary layer).
- The author (reads current configuration state from the active git branch).
- Maintenance (reads canonical layers; writes summary layer; writes gap
  record status transitions and kind reconciliations).
- The run loop (writes decisions and archive entries).
- The human (reads everything, via the markdown batch in Phase 6 and
  through direct git inspection).

## Schema (structure, not layout)

The knowledge base lives in a dedicated directory within the repository.
Conceptually organized as:

- **Session logs**, not stored by the claude-reflect; read from Claude
  Code's session log directory. See `02-storage/session-logs.md`.
- **Decisions**, a git branch with structured commits. See
  `02-storage/decisions-git.md`.
- **Gap records**, structured records, one per gap. Storage format is
  implementation; from the consumer's perspective, gap records are queryable
  and updatable entities referenced by identifier.
- **Archive entries**, structured records, one per accepted proposal.
  Same storage consideration as gap records.
- **Summary layer**, a collection of markdown pages maintained by the
  maintenance process. See `02-storage/summary-layer.md`.

The specific filesystem layout, serialization format, and indexing
mechanisms are implementation choices. The spec requires only that:

- Every record type can be read and written by its respective consumer.
- Every cross-reference (e.g., a decision record's `targeted_gaps`)
  resolves by the identifier alone.
- The entire knowledge base is rebuildable from sessions and decisions
  if any other layer is lost or corrupted (including gap records and
  archive entries, which are reconstructible from the decisions log and
  maintained evaluator output, though this rebuild is expensive and not
  a routine operation).

## Invariants

- Sessions are never modified by the claude-reflect.
- Decisions, once committed, are immutable except for specific fields
  (see `01-data-structures/decision-record.md`).
- Gap records are append-only in existence (never deleted).
- Archive entries are append-only.
- The summary layer is regenerable: dropping it entirely and rebuilding
  from the canonical layers yields an equivalent summary layer (up to
  LLM nondeterminism in prose).
- The knowledge base's state is consistent at run boundaries: no run
  begins before the previous run's Phase 8 or Phase 9 has committed.

## Canonical vs. synthesis distinction

**Canonical:** session logs, decisions, gap records, archive entries. These
are the source of truth. Any agent making a decision that depends on
precise current state reads canonical layers directly.

**Synthesis:** summary layer. A regenerable cache of markdown pages that
synthesize over canonical layers. Used for orientation, navigation,
semantic retrieval, and human review. Agents never make authoritative
judgments based solely on summary layer content; they read canonical
sources when the decision matters.

## Explicitly excluded

- No external storage. The knowledge base lives in the local repository.
- No sharing or syncing across users or repositories.
- No encryption layer (if desired, handled outside the spec).
- No schema versioning mechanism in the first version. If the spec
  evolves, regeneration from canonical sources is the migration path.

## Cross-references

- Each layer has its own file:
  - `02-storage/session-logs.md`
  - `02-storage/decisions-git.md`
  - `02-storage/summary-layer.md`
- Gap records and archive entries do not have separate storage files
  because their schemas (in `01-data-structures/`) specify everything
  needed. Their storage format is an implementation detail.
