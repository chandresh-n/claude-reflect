# `scripts/` — Bash helpers

Earmarked for the bash side of the hybrid Python + bash implementation
described in `docs/IMPLEMENTATION.md`.

## Split principle

> If the operation is "do this thing across many files quickly" or "run a git
> command," bash. If the operation is "coordinate this multi-step workflow
> with structured records," Python.

## Likely contents

- `setup.sh` — initialize `.meta-harness/` in a target repo, create the
  decisions branch, write default `config.yaml`. Called by Phase 1 of the
  run loop. Spec: `docs/spec/04-processes/run-loop.md` and
  `docs/spec/02-storage/knowledge-base.md`.
- `walk_session_logs.sh` — fast traversal of Claude Code's session log
  directory, filter by date range. Spec: `docs/spec/02-storage/session-logs.md`.
- `git_decisions.sh` — branch and commit helpers for the
  `meta-harness/decisions` branch and `meta-harness/proposal/<id>` branches.
  Spec: `docs/spec/02-storage/decisions-git.md`.
- `jq` snippets and other JSON-mangling utilities used by the above.

## Call convention

These scripts are invoked from Python via `subprocess`. Stdout is the result;
stderr is for human-readable progress; non-zero exit is a hard failure.
Scripts should not pretty-print or color their output by default — Python
parses them.
