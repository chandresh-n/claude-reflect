---
description: Run a claude-reflect review pass over recent Claude Code sessions and present proposals.
argument-hint: "[range, e.g. 'last 7 days' or '2026-04-01 to 2026-04-07']"
---

Run a `claude-reflect` review against the current repository, then walk the user through the proposal batch.

## Steps

1. If `$ARGUMENTS` is empty, default the range to `"last 7 days"`. Otherwise pass `$ARGUMENTS` verbatim as the range.

2. Confirm the CLI is installed:
   ```bash
   command -v claude-reflect >/dev/null 2>&1 || echo NEEDS_SETUP
   ```
   If it prints `NEEDS_SETUP`, stop and tell the user to run `/claude-reflect:setup` first.

3. Run the review:
   ```bash
   claude-reflect review --range "<range>" --repo "$(pwd)" --verbose
   ```
   Stream output as it runs. Reviews can take several minutes — that's expected.

4. When the run finishes, the tool writes a proposal batch (plain markdown) to `.claude-reflect/runs/<run_id>/proposals.md`. Open it, summarize the proposals, and present them one at a time. For each, ask the user to mark **Accept**, **Reject**, or **Defer**.

5. If a run is interrupted, the user can resume with:
   ```bash
   claude-reflect review --resume <run_id> --repo "$(pwd)"
   ```
   The run_id is printed at the start of every run.

## Notes

- All state is per-repo under `.claude-reflect/`. Nothing global is touched.
- On first run in a repo, the tool initializes its knowledge base and creates a `claude-reflect/decisions` git branch. Your working branch stays active.
- The tool produces no scalar scores or rankings — only categorical observations.
