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

### Priority A — baseline pipeline coverage

| Fixture | Pattern under test | What evaluator should notice |
|---|---|---|
| `tool_call_loop.jsonl` | Read → Edit ping-pong on the same file with no real progress | Repeated mutation of one location; final state matches an intermediate one |
| `file_location_struggle.jsonl` | Four wrong `cat` / `ls` paths before grepping | Multiple negative Bash results targeting filesystem before a successful tool switch |
| `hallucinated_symbol.jsonl` | Two imaginary function names called before checking what's actually exported | ImportError → retry-with-similar-guess pattern; only resolved after grep |
| `clean_one_shot.jsonl` | Single Read → answer; no detours | Control case — evaluator should produce **zero** gap observations |
| `test_failure_cycle.jsonl` | Fix → break → fix → break — fixes target symptoms, not the call graph | Each "fix" introduces a different test failure; pattern is whack-a-mole, not understanding |

### Priority B — variance + targeted regression

| Fixture | Pattern under test | What evaluator should notice |
|---|---|---|
| `missed_claude_md.jsonl` | Pushed directly to main even though CLAUDE.md forbids it; only read CLAUDE.md after the user flagged the violation | CLAUDE.md was not consulted before an irreversible operation; agent self-corrected only post-error |
| `refactor_scope_creep.jsonl` | Asked for a one-character typo fix; agent added type hints, new modules, new TypedDicts, three new tests | Scope of change vastly exceeded the request; user explicitly asks for a revert |
| `convention_drift.jsonl` | Added a camelCase function to a file whose every other symbol is snake_case | Local convention not inferred from surrounding code; correction only after user pushes back |
| `multi_window_{a,b,c}_*.jsonl` | Three separate sessions in the same window, each making the same "look in wrong dir before grepping" mistake | First multi-session set — exercises cross-session gap aggregation in stage 4 (one shared gap kind across three session ids) |
| `malformed_proposer_output_repro.jsonl` | Five-iteration "match the expected literal" anti-pattern (return-the-test-string) | Pinned to make stage 4 surface a `pattern_match_without_understanding` gap; primary purpose is to feed the proposer enough corpus to potentially exercise the string-typed-section bug the renderer was hardened against |

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
