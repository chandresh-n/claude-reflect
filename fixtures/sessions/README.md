# fixtures/sessions/

Synthetic Claude Code session logs used to exercise the claude-reflect
pipeline end-to-end without hitting your real session history.

Run them with:

```bash
claude-reflect review --fixtures-dir fixtures/sessions/
```

This treats every `*.jsonl` in the directory as one session window, runs
the evaluator → proposer → author → review pipeline against them, and
writes all KB state under `fixtures/sessions/.claude-reflect/` (which is
gitignored — it won't pollute your real KB).

Add `--no-cache` to force fresh agent invocations even when input hasn't
changed. Add `--verbose` to stream agent output.

## What each fixture targets

| Fixture | Pattern under test | What evaluator should notice |
|---|---|---|
| `tool_call_loop.jsonl` | Read → Edit ping-pong on the same file with no real progress | Repeated mutation of one location; final state matches an intermediate one |
| `file_location_struggle.jsonl` | Four wrong `cat` / `ls` paths before grepping | Multiple negative Bash results targeting filesystem before a successful tool switch |
| `hallucinated_symbol.jsonl` | Two imaginary function names called before checking what's actually exported | ImportError → retry-with-similar-guess pattern; only resolved after grep |
| `clean_one_shot.jsonl` | Single Read → answer; no detours | Control case — evaluator should produce **zero** gap observations |
| `test_failure_cycle.jsonl` | Fix → break → fix → break — fixes target symptoms, not the call graph | Each "fix" introduces a different test failure; pattern is whack-a-mole, not understanding |

## Adding fixtures

Each fixture is a single `*.jsonl` file at the top of this directory.
The format matches Claude Code's native session log:

- One JSON object per line
- `type`: `"user"` | `"assistant"` | `"tool_result"`
- Stable `sessionId` shared across all lines in one fixture
- Unique `uuid` per line, increasing `timestamp`
- Assistant lines carry `model` and `usage`
- Tool calls live inside `message.content` as `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}`
- Tool results carry `tool_use_id` and stringified `content`

Keep each fixture ≤20 turns so the pipeline stays fast.
