# Human review

## Role

Phase 6 and Phase 7 of the run loop present the proposal batch to the
human and capture their decisions. The interface is deliberately
low-tech: a markdown document the human opens in their editor, and
terminal-visible diffs alongside. Decisions are marked inline in the
markdown.

The human's role is strictly judgment. They read rationale and diff,
decide per proposal, provide reasoning for rejections, and save. The
skill reads their markings after they save and closes out Phase 7.

## Inputs

- A proposal batch from Phase 5 (proposals with diffs, plus any
  author-failed proposals carrying their failure reasons).
- The human's time and attention.

## Outputs

- Per-proposal decisions (accept, reject, or pending) with the human's
  reasoning where provided.
- These decisions are processed in Phase 8 to commit decision records
  and merge accepted diffs.

## The markdown document

Structure:

```
# Meta-harness proposal batch

Run: <run_id>
Window: <start> to <end>
Generated at: <timestamp>

Batch narrative: <prose summary of what this batch contains>

---

## Proposal 1 of N: <title>

**Why:** <prose summary from the rationale>

**What:** <short description>, see diff: <branch name>

**How:** <mechanism prose>

**Prediction:** <expected impact prose>

<if forced_novelty or null_baseline>
**Exploration rationale:** <prose explaining the region being probed>
</if>

---

### Your decision

Mark one:
- [ ] Accept
- [ ] Reject
- [ ] Defer (leave pending)

Reasoning (required if rejecting, optional otherwise):

```

Every proposal in the batch gets its own section following this
template.

Author-failed proposals appear with a different template:

```
## Proposal <n> of N: <title>. AUTHOR FAILED

**Why this was proposed:** <prose summary>

**What was attempted:** <short description>

**Why it could not be produced:** <author_failure_reason>

This proposal will be recorded as author-failed regardless of your
input. No action required.
```

The human cannot accept an author-failed proposal (there is no diff to
merge). The decision record will be committed with
`status = author_failed`.

## The terminal-visible diffs

For each proposal with a successful diff:

- The skill prints the diff to the terminal when the batch is
  generated, labeled by proposal number and title.
- The diff is viewable alongside the markdown (in a split terminal, or
  scrolled through).

Format is standard `git diff` or equivalent. The diff is authoritative
for what will be merged; the markdown's prose is explanation.

## The human's workflow

Expected workflow:

1. The skill announces the batch is ready; the markdown file has
   opened in the human's editor; diffs are in the terminal.
2. The human reads the batch narrative.
3. For each proposal:
   - Read rationale sections in the markdown.
   - Inspect the diff in the terminal.
   - Mark the decision checkbox.
   - Provide reasoning if rejecting.
4. The human saves and closes the markdown.
5. The skill reads the saved file, extracts decisions, and proceeds
   to Phase 8.

## Pause semantics

If the human does not mark all proposals before closing the markdown:

- Marked proposals are processed in Phase 8 as usual (accepted or
  rejected with their recorded reasoning).
- Unmarked proposals remain `pending`. They will be surfaced at Phase
  2.5 of the next run.

The human can explicitly mark "Defer" to leave a proposal pending
without abandoning the run. Unmarked proposals are treated as
implicitly deferred.

## Invariants

- The human sees the batch in exactly one markdown file per run.
- Every proposal with a successful diff has its diff viewable in
  terminal.
- The markdown structure is consistent across runs. Proposals are
  ordered by generation order within the batch (or by another
  convention; ordering is not load-bearing).
- Rejecting a proposal requires a reason. If the human marks "Reject"
  but leaves the reasoning blank, the skill prompts for one before
  completing Phase 7.
- The skill does not modify the human's markings after they save.
  Whatever the human wrote is what gets committed.

## Explicitly excluded

- No GUI form. Plain markdown, plain terminal.
- No programmatic validation of the human's reasoning. If the human
  writes "rejected because I don't like it," that is a valid reason.
- No intermediate confirmation dialogs ("are you sure?").
- No undo mechanism within Phase 7. Once the human saves and Phase 8
  runs, decisions are committed. Subsequent runs can propose
  supersession of an earlier decision if the human changes their
  mind.
- No notifications when the batch is ready. The human sees the
  terminal output of the invocation directly.

## Cross-references

- Batch construction: `04-processes/run-loop.md` (Phase 5-6).
- Decision commit: `04-processes/run-loop.md` (Phase 8).
- Decision record schema: `01-data-structures/decision-record.md`.
- Proposal schema: `01-data-structures/proposal.md`.
- Author failure: `03-agents/author.md`.
