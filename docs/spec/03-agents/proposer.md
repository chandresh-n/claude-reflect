# Proposer

## Role

The proposer generates proposals that target gaps identified by the
evaluator. It reasons over the full knowledge base, makes prioritization
decisions, decides whether a forced-novelty proposal is due, and
produces a batch of proposal intents. Each intent is later realized as
a concrete diff by the author agent.

The proposer is spawned fresh as a separate agent with its own context.
It never shares context with the evaluator or the author. It may be
spawned multiple times across runs; it persists no state between runs
outside what it writes to the knowledge base.

## Inputs

- The evaluator's report for the current run (read-only).
- Access to the full knowledge base:
  - Session logs (via evidence pointers).
  - Decisions branch (via git queries).
  - Gap records.
  - Archive entries.
  - Summary layer pages.
- The current run's metadata (run_id, batch_id assignment, window).

## Outputs

- A batch of proposal intents, as specified in
  `01-data-structures/proposal.md`. Each intent includes the four-part
  rationale, structural tags, and authoring addendum.
- Writes to gap records: at intent creation, the proposer appends its
  `proposal_id` to the `related_proposals` list of every gap cited.
- A run-level reasoning commit on the decisions branch: a git commit
  message summarizing which candidate gaps were considered, which were
  acted on, and which were deferred (with reasons).

The proposer does not produce diffs. Diff authoring is the author
agent's job, invoked per proposal in Phase 5b.

## Behavior

### Reading the knowledge base

On invocation, the proposer reads:

- The evaluator's report (primary input).
- The gap records themselves (authoritative source for gap state -
  not the gap-dashboard page, which is synthesis).
- The decisions branch, focusing on:
  - Recent decisions (for trajectory awareness).
  - Decisions targeting gaps of the same kinds as current candidates
    (for "what has worked or not worked before").
  - Decisions in `superseded` status (for awareness of reverted choices).
- The archive entries, focusing on:
  - The current active configuration (for understanding what's in
    place).
  - Recent non-current entries (for awareness of what alternatives the
    system has tried).
  - `structural_fingerprint` across entries (for posture reasoning).
- Summary layer pages:
  - Exploration-profile page (primary input to forced-novelty decisions).
  - Gap-kind pages matching current candidates.
  - Relevant decision-lineage pages.

Summary-layer reads inform orientation and semantic context. Decisions
on what to propose are grounded in canonical layer reads.

### Prioritization

The proposer prioritizes gaps for this run's batch. Prioritization is
multi-dimensional:

- **Frequency.** How often the gap has been observed (from
  `occurrence_count`).
- **Recency.** How recently the gap has been observed (from
  `last_observed_at`). Recent gaps outweigh old ones when frequencies
  are comparable.
- **Magnitude.** Per-occurrence cost of the gap (from the `magnitude`
  field on evidence pointers). A gap that costs many turns per
  occurrence outweighs a gap that costs one turn per occurrence at the
  same frequency.

These dimensions are considered jointly. The proposer must not collapse
them to a single scalar and sort by it. The rationale: a single-axis
sort would systematically underrepresent gaps that are important on one
axis but not the one the sort uses. A proposer that always targets the
highest-magnitude gap ignores the long tail of high-frequency,
low-magnitude gaps that together account for significant effort.

Prioritization is not expressed as a ranked list the proposer commits to.
The proposer considers candidates, chooses a subset to address in this
run, and records its reasoning in the run-level commit.

### Historical awareness

Before proposing against a gap, the proposer consults:

- The gap record's `related_proposals`. For each entry, it looks up the
  decision in the decisions log to see the outcome.
  - If a prior proposal for this gap was **rejected**, the proposer
    reads the human's `human_reasoning` and avoids proposing something
    substantially similar.
  - If a prior proposal was **accepted**, the proposer sees what was
    tried and assesses whether the gap is still recurring (which
    suggests the previous attempt was insufficient) or has moved to a
    new form (which suggests different targeting).
  - If a prior proposal was **author_failed**, the proposer avoids
    proposing the same kind of change that could not be realized.
- The gap-kind page for this gap's kind. This page synthesizes
  historical patterns across gaps of the same kind.

### Forced-novelty logic

On each run, the proposer checks whether a forced-novelty proposal is
due. The check reads the exploration-profile page and applies a
probabilistic rule:

- With some probability (a configuration parameter, e.g., 20%), one
  proposal in this run's batch must be structurally different from
  recent proposals.
- Within the forced-novelty rule, with a smaller probability (e.g., 1%),
  the proposal is a null-baseline proposal: strip the configuration to
  its minimum.
- When generating a forced-novelty proposal, the proposer writes an
  `exploration_rationale` naming what region is being probed and why
  this region was selected (drawn from the exploration-profile page:
  "surfaces untouched for N months," "posture has been skill-heavy for
  M weeks," etc.).

The forced-novelty proposal may coexist with judgment-driven proposals
in the same batch. It is not a replacement; it is an additional
proposal. The human reviews it alongside the others.

### Generating intents

For each proposal the proposer decides to generate, it produces a
proposal intent:

1. The four-part rationale:
   - **why**: cited gaps (with addressing notes), cited sessions, cited
     prior decisions (with relational notes), prose summary.
   - **what**: short description of the mechanical change (the
     `diff_reference` and `files_touched` are filled by the author in
     Phase 5b).
   - **how**: prose explaining the mechanism by which the change acts.
   - **prediction**: prose articulating expected impact.

2. The structural tags: `change_type`, `surface`, `novelty_status`,
   `exploration_rationale` (if applicable).

3. The authoring addendum (`actions`, `purpose`, `activation_conditions`,
   `behavior_constraints`, `examples`, `style_hints`,
   `reference_material`). The addendum is verbose and specific. It
   leaves as little interpretive room as possible for the author.

4. The proposer appends its `proposal_id` to the
   `related_proposals` list of every gap in `cited_gaps`.

### Run-level commit

At the end of Phase 5a, the proposer writes a commit on the decisions
branch with a message summarizing the run's candidate analysis: which
gaps were considered, which were acted on, which were deferred (and
brief reasons), whether a forced-novelty proposal was generated.

## Behavioral directives (prompt-level)

- **Evidence-grounded proposals.** Every proposal cites specific
  sessions, turns, and gaps. "The evaluator said this was a problem" is
  not a sufficient citation.
- **Reuse historical learning.** Before proposing, check what has been
  tried. Do not re-propose rejected patterns without substantial change.
- **Keep the authoring addendum specific.** Remember that the author
  agent is fresh-context and does not see the `how` prose. The addendum
  must carry everything the author needs.
- **Prefer smaller changes.** A minimal change that addresses a gap is
  preferable to an ambitious change that addresses several. The
  claude-reflect is evolutionary; future runs compound.
- **Simplicity criterion.** If a proposal could equivalently be stated
  as "remove something" or "add something," prefer remove when possible.
- **Multi-dimensional prioritization.** Do not collapse frequency ×
  recency × magnitude to a single axis.
- **Honesty about forced-novelty.** When generating a forced-novelty
  proposal, be honest in the `how` prose that the evidence for this
  particular change is thin; the exploration is justified by
  maintaining the system's map of the space, not by strong signal.

## Invariants

- The proposer never shares context with the evaluator or the author.
- The proposer is spawned fresh at each run.
- Every cited gap, session, and prior decision resolves to a real record.
- The authoring addendum is verbose enough that an author with no
  additional context can produce a valid diff.
- Gap record writes (appending to `related_proposals`) happen at intent
  creation, before the author runs.
- Run-level commit is written before Phase 5b begins.

## Explicitly excluded

- No diff production. The proposer does not write skill files, hook
  configurations, or CLAUDE.md content.
- No access to the author's output during generation.
- No human interaction during generation.
- No scoring or grading of candidate proposals.
- No batch-level priority ranking shown to the human.

## Cross-references

- Proposal schema: `01-data-structures/proposal.md`.
- Gap record writes: `01-data-structures/gap-record.md`.
- Decision reads: `01-data-structures/decision-record.md`,
  `02-storage/decisions-git.md`.
- Archive reads: `01-data-structures/archive-entry.md`.
- Summary layer reads: `02-storage/summary-layer.md`.
- Author agent: `03-agents/author.md`.
- Run loop invocation: `04-processes/run-loop.md` (Phase 5a).
