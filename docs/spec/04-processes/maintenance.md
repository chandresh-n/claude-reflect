# Maintenance

## Role

Maintenance is a process that keeps the summary layer synchronized with
the canonical layers, reconciles vocabulary drift, transitions stale
state, and produces the synthesized views the proposer reads for
orientation. It is a side-car: philosophically and operationally
separate from the agents and the main run flow.

Maintenance never changes canonical state in ways that represent
judgment. It writes to the summary layer, transitions gap record status
(`stale`), and reconciles near-duplicate gap record `kind` labels.
These are alignment operations, not decisions.

## Inputs

- All canonical layers (read-only except for the specific writes listed
  below):
  - Session logs.
  - Decisions branch.
  - Gap records.
  - Archive entries.
- The current state of the summary layer (to know what to update vs.
  regenerate).
- A maintenance log (for idempotence: what was done in prior passes).

## Outputs

- Writes to the summary layer (new pages, updated pages, regenerated
  index).
- Writes to gap records (limited): status transitions to `stale`, and
  `kind` reconciliations on merge of near-duplicates.
- A maintenance log entry recording what this pass did.

## Behavior

### Trigger

Maintenance runs when content thresholds have been crossed since the
last maintenance pass. Thresholds are implementation configuration
(e.g., N new sessions, M new decisions, K new gap records, or T days
elapsed). The skill checks the trigger at Phase 2 of the run loop and
again at Phase 9.

Maintenance is not triggered by consumer requests. The proposer and
evaluator read the summary layer in whatever state it is; they do not
request updates. If the summary layer is stale by up to one maintenance
cycle, that is acceptable (consumers fall back to canonical layers for
decisions that matter).

### The maintenance pass

One pass executes the following operations in order:

1. **Ingest new content.** Identify sessions, decisions, gap records,
   and archive entries added since the last maintenance pass (using
   timestamps or cursors).

2. **Update gap-kind pages.** For each `kind` touched by new gap
   records or by decisions referencing gaps of that kind, regenerate
   the gap-kind page. If the kind is new, create the page. If the
   kind has no remaining gap records (all reconciled away or all gone
   stale), deprecate the page.

3. **Update archive-entry pages.** For archive entries whose
   `active_at.end` has been populated since the last pass, write the
   `qualitative_position` prose to the archive entry and regenerate
   the archive-entry page. The `qualitative_position` synthesizes the
   entry's `region_markers.sessions_measured` and
   `observed_gap_frequencies` into a prose description.

4. **Update exploration-profile page.** Always regenerate. This page
   must reflect recent activity for forced-novelty reasoning.

5. **Update gap-dashboard page.** Always regenerate. This page must
   reflect current open gap state.

6. **Reconcile `kind` vocabulary.** Scan gap records for near-duplicate
   kinds (e.g., `correction-required` and `human-correction` being
   used for substantively similar patterns). When duplicates are
   identified, merge them: pick a canonical label, update the `kind`
   field on affected gap records, update gap-kind pages accordingly.
   Reconciliation is conservative: merge only when confidence is high.
   Edge cases are left unmerged.

7. **Transition `stale` gaps.** For each gap record in status `open`
   whose `last_observed_at` is older than the stale threshold (e.g.,
   N sessions ago, configurable), transition status to `stale`. A
   future observation will transition it back to `open`.

8. **Detect session clusters.** Scan sessions processed since the last
   pass for recurring patterns not already captured by gap records.
   When a pattern across sessions is worth anchoring, create a
   session-cluster page.

9. **Detect decision lineages.** Scan decisions for chains of related
   proposals (same gap targeted across multiple decisions, related
   surfaces evolving together). Create or update decision-lineage
   pages as warranted.

10. **Consolidate.** Check whether any existing summary layer pages
    have become redundant, sparse, or stale. Merge redundant pages
    (preserving citations). Deprecate (do not delete) pages whose
    source no longer exists.

11. **Regenerate the index.** Produce a fresh index listing all pages
    by page-kind, with updated timestamps.

12. **Write maintenance log.** Produce a log entry summarizing what
    was done: pages created, pages updated, pages deprecated, kinds
    reconciled, gaps transitioned.

### Idempotence

Maintenance is idempotent. Running it twice on the same inputs
produces the same result (up to LLM nondeterminism in prose
generation). Specifically:

- If no new content has arrived, maintenance is a no-op.
- If the same content is processed twice, the second pass detects that
  everything is current and exits.

### Non-destructiveness

Maintenance does not delete. Deprecated pages are flagged
(`deprecated: true` in the page's header, or moved to an archive
section of the index) but remain in the filesystem. Git history of
the summary layer branch preserves all versions.

## Behavioral directives (prompt-level)

Maintenance is an LLM-maintained process; its prompt encodes:

- **Preserve citations.** Every synthesized claim must cite its
  canonical source.
- **Prefer linking over duplication.** If a piece of synthesis lives
  on another page, link to it; do not restate.
- **Be conservative on reconciliation.** When merging kinds, require
  strong evidence that two labels refer to the same pattern. When in
  doubt, leave them separate.
- **Write for proposer consumption.** Pages are read by the proposer
  for orientation. Use clear headings, consistent conventions, and
  make information easy to locate.
- **Do not judge.** Summaries describe patterns and outcomes. They do
  not grade. They do not recommend.

## Invariants

- Maintenance writes only to the summary layer, to gap record status
  fields, and to gap record kind fields (for reconciliation). It does
  not write to sessions, decisions, archive entries' content fields,
  or any other canonical state.
- Maintenance is idempotent.
- Every maintenance pass produces a log entry.
- The summary layer after maintenance is consistent with the canonical
  layers at the time the pass started.
- Consumer reads during a maintenance pass see either the pre-pass or
  post-pass state, never a partial state (implementation ensures
  atomic or consistent reads; simplest approach is that maintenance
  and consumer runs do not overlap).

## Explicitly excluded

- No judgment calls. Maintenance does not decide whether a pattern is
  important, whether a gap should be addressed, or whether a
  configuration is good. Those are the proposer's and evaluator's
  jobs.
- No writes to the active configuration. Maintenance never modifies
  the files Claude Code reads for its own behavior.
- No interaction with the human. Maintenance is silent.
- No execution of tests, linters, or other verification tools. Those
  are the evaluator's tools.

## Cross-references

- Summary layer structure: `02-storage/summary-layer.md`.
- Gap record status transitions: `01-data-structures/gap-record.md`.
- Archive entry `qualitative_position` writes:
  `01-data-structures/archive-entry.md`.
- Triggered by the run loop at Phase 2 and Phase 9:
  `04-processes/run-loop.md`.
- Log entries committed to the decisions branch (or a maintenance
  branch): `02-storage/decisions-git.md`.
