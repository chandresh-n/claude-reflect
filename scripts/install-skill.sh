#!/usr/bin/env bash
#
# install-skill.sh — Register claude-reflect as a Claude Code skill in a repo.
#
# Usage:
#   ./scripts/install-skill.sh /path/to/your/repo
#   ./scripts/install-skill.sh                     # defaults to current directory
#
# What this does:
#   1. Creates .claude/commands/claude-reflect-review.md  (the skill prompt)
#   2. Creates .claude/commands/claude-reflect-status.md
#   3. Creates .claude/commands/claude-reflect-maintenance.md
#
# After installation, invoke from Claude Code with:
#   /claude-reflect-review last 7 days
#   /claude-reflect-status
#   /claude-reflect-maintenance
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

info()  { printf '\033[1;34m[info]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[ok]\033[0m    %s\n' "$*"; }
err()   { printf '\033[1;31m[err]\033[0m   %s\n' "$*" >&2; }

# --------------------------------------------------------------------------
# Target repo
# --------------------------------------------------------------------------

TARGET_REPO="${1:-.}"
TARGET_REPO="$(cd "$TARGET_REPO" && pwd)"

if [[ ! -d "$TARGET_REPO/.git" ]]; then
    err "$TARGET_REPO is not a git repository."
    exit 1
fi

info "Installing claude-reflect skills into: $TARGET_REPO"

# --------------------------------------------------------------------------
# Verify claude-reflect is installed
# --------------------------------------------------------------------------

if ! command -v claude-reflect &>/dev/null; then
    # Try python module fallback
    if python3.11 -m claude_reflect.cli --help &>/dev/null 2>&1; then
        META_CMD="python3.11 -m claude_reflect.cli"
    elif python3 -m claude_reflect.cli --help &>/dev/null 2>&1; then
        META_CMD="python3 -m claude_reflect.cli"
    else
        err "claude-reflect is not installed. Run scripts/setup.sh first."
        exit 1
    fi
else
    META_CMD="claude-reflect"
fi

ok "claude-reflect CLI found: $META_CMD"

# --------------------------------------------------------------------------
# Create skill files
# --------------------------------------------------------------------------

COMMANDS_DIR="$TARGET_REPO/.claude/commands"
mkdir -p "$COMMANDS_DIR"

# --- /claude-reflect-review ---
cat > "$COMMANDS_DIR/claude-reflect-review.md" << 'SKILL_EOF'
Run a claude-reflect reflective review pass over recent Claude Code sessions.

This analyzes session logs for patterns, gaps, and inefficiencies, then
proposes configuration changes to improve Claude Code's performance.

Usage: /claude-reflect-review <date-range>
  Examples:
    /claude-reflect-review last 7 days
    /claude-reflect-review last week
    /claude-reflect-review 2026-04-01 to 2026-04-07

Steps:
1. Run: claude-reflect review --range "$ARGUMENTS" --repo "$(pwd)" --verbose
2. The tool will:
   - Initialize the knowledge base on first run (automatic)
   - Collect session logs in the date range
   - Evaluate sessions for quality patterns and gaps
   - Generate proposals for configuration changes
   - Present proposals as a markdown batch for your review
3. Review each proposal and mark Accept / Reject / Defer
4. Accepted changes are committed to the repo automatically

If no date range is provided, default to "last 7 days".

To resume a paused run: claude-reflect review --resume <run_id> --repo "$(pwd)"
SKILL_EOF

ok "Created /claude-reflect-review skill"

# --- /claude-reflect-status ---
cat > "$COMMANDS_DIR/claude-reflect-status.md" << 'SKILL_EOF'
Check the status of the claude-reflect knowledge base in this repository.

Run: claude-reflect status --repo "$(pwd)"

This reports:
- Whether the knowledge base is initialized
- Number of gap records tracked
- Number of archive entries (configuration history)
- Number of completed runs

If not yet initialized, suggest running /claude-reflect-review to start.
SKILL_EOF

ok "Created /claude-reflect-status skill"

# --- /claude-reflect-maintenance ---
cat > "$COMMANDS_DIR/claude-reflect-maintenance.md" << 'SKILL_EOF'
Trigger a claude-reflect maintenance pass on this repository.

Run: claude-reflect maintenance --repo "$(pwd)"

Maintenance:
- Regenerates the summary layer (idempotent)
- Transitions stale gap records
- Reconciles the gap kind vocabulary
- Runs automatically when thresholds are met, but can be triggered manually

This is safe to run at any time — maintenance is idempotent (running it
twice produces identical state).
SKILL_EOF

ok "Created /claude-reflect-maintenance skill"

# --------------------------------------------------------------------------
# Done
# --------------------------------------------------------------------------

echo ""
ok "Skills installed in $COMMANDS_DIR/"
echo ""
info "Available commands in Claude Code:"
echo "  /claude-reflect-review last 7 days    # run a reflective pass"
echo "  /claude-reflect-status                # check knowledge base state"
echo "  /claude-reflect-maintenance           # trigger maintenance"
echo ""
