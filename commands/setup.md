---
description: Install the claude-reflect Python backend so other commands can run.
---

Set up the `claude-reflect` Python backend.

## Steps

1. Run the install script bundled with the plugin:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh"
   ```
   This checks for Python 3.11+ and pip, then installs the `claude-reflect` package in editable mode from `${CLAUDE_PLUGIN_ROOT}`.

2. Verify the install:
   ```bash
   claude-reflect --help
   ```
   If the binary isn't on PATH, tell the user to add their pip user-scripts directory to PATH (or to use `python3.11 -m claude_reflect.cli` as a fallback).

3. Report the Python version used and the install location.

## Notes

- This is idempotent. Re-running just upgrades.
- The package needs no API key. It uses your existing Claude Code OAuth via `claude -p`.
- Do not run `/claude-reflect:review` from this command — that's a separate step.
