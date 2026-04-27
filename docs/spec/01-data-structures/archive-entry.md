# Archive entry

## Role

An archive entry represents a complete configuration state the system has
inhabited at a specific moment. One entry exists per accepted proposal. The
archive collectively is the history of configurations the system has tried,
with metadata that supports forced-novelty reasoning, supersession
tracking, and human review of evolution.

The archive is not a curated collection of "interesting" configurations.
Every accepted proposal produces an entry. Curation (e.g., identifying
which entries occupy distinct frontier regions) is a synthesis task
performed by the summary layer, not encoded in the archive itself.

## Inputs

Created by the run loop at Phase 8, one per accepted proposal. Updated by
maintenance (writing `qualitative_position` when `active_at` closes,
extending `region_markers` over time as sessions run under this
configuration).

## Outputs

Archive entries are queryable by the proposer, the summary layer's
maintenance process, and the human. They are stored alongside the other
canonical layers in the knowledge base.

## Schema

- **entry_id**: stable identifier.
- **git_reference**: commit hash on the active configuration branch
  representing the complete state this entry captures. Materializable via
  `git checkout`.
- **produced_by_decision**: the decision identifier whose acceptance
  produced this entry. Links back to the proposal and its rationale.
- **produced_at**: inherited from the decision's `reviewed_at`.
- **superseded_by**: decision identifier that replaced the state this
  entry represents (if any). `null` if not superseded.
- **active_at**: `{start, end}`. `start` is `produced_at`. `end` is
  populated when a subsequent accepted decision moves state away from
  this entry. `null` while currently active.

- **region_markers**: observed behavior under this configuration:
  - `sessions_measured`: list of session identifiers that ran while this
    configuration was active. Grows as sessions accumulate.
  - `qualitative_position`: prose description of where this
    configuration sat on the conceptual effort-quality frontier, written
    by maintenance once `active_at.end` is populated. Interpretive, for
    human review and summary layer synthesis. May be `null` for entries
    whose `active_at` has closed but whose post-supersession maintenance
    pass has not yet run.
  - `observed_gap_frequencies`: for each gap record that was open during
    this configuration's active period, the frequency it was observed at
    under this configuration. Map from gap identifier to count.

- **structural_fingerprint**: structural metadata:
  - `skill_count`: number of skills defined under `.claude/skills/`.
  - `hook_count`: number of hooks defined in settings.
  - `agent_count`: number of custom agents under `.claude/agents/`.
  - `claude_md_length`: token count (or word count) of `CLAUDE.md`.

## Invariants

- Every entry's `git_reference` resolves to a real commit.
- Every entry has exactly one `produced_by_decision` matching a decision
  with `status = accepted`.
- `region_markers.sessions_measured` contains only sessions that ran
  during this entry's `active_at` window.
- `structural_fingerprint` is derivable from the `git_reference`'s content
  at any time; the field is a cache for query efficiency.
- Archive entries are never deleted. Supersession populates
  `superseded_by` and `active_at.end` but leaves the entry in place.
- The union of all `active_at` ranges across entries covers the timeline
  of the repository's configured life, with no overlaps. Exactly one
  entry is active at any moment.
- `qualitative_position` may be `null` for entries whose `active_at.end`
  has been set but whose first post-closure maintenance pass has not yet
  run. It is populated on that next maintenance pass and is immutable
  thereafter.

## Explicitly excluded

- No full file contents. Those live in git at the `git_reference`.
- No quality or effort scalars. The `qualitative_position` is prose and
  interpretive.
- No "best" flag or champion marker. The currently-active entry is
  identifiable from `active_at.end = null`; no entry is otherwise
  distinguished.
- No per-gap attribution claims ("this configuration addressed gap G").
  Such claims live in the decision record that created the state.
- No surfaces-modified-from-previous cache. Computable on demand from
  the producing decision's `structural_tags.surface` or from `git diff`.

## Cross-references

- Produced by a decision: `01-data-structures/decision-record.md`.
- The active configuration at any moment: `02-storage/knowledge-base.md`.
- `qualitative_position` written by maintenance:
  `04-processes/maintenance.md`.
- `structural_fingerprint` consulted by forced-novelty reasoning:
  `03-agents/proposer.md` and the exploration-profile page in
  `02-storage/summary-layer.md`.
- Archive creation as part of run loop Phase 8:
  `04-processes/run-loop.md`.
