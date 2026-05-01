#!/usr/bin/env bash
#
# setup.sh — Install meta-harness and verify the installation.
#
# Usage:
#   ./scripts/setup.sh          # install in dev mode (editable)
#   ./scripts/setup.sh --prod   # install as a regular package
#
# Requirements:
#   - Python 3.11+
#   - pip (for Python 3.11)
#   - git
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
# Pre-flight checks
# --------------------------------------------------------------------------

info "Checking prerequisites..."

# Python 3.11+
if command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    major="${py_version%%.*}"
    minor="${py_version##*.}"
    if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
        PYTHON=python3
    else
        err "Python 3.11+ is required (found python3 $py_version)."
        exit 1
    fi
else
    err "Python 3.11+ is required but not found."
    err "Install it via: brew install python@3.11  (macOS) or your system package manager."
    exit 1
fi

ok "Python: $($PYTHON --version)"

# pip
if ! $PYTHON -m pip --version &>/dev/null; then
    err "pip for $PYTHON is not available."
    err "Install it via: $PYTHON -m ensurepip --upgrade"
    exit 1
fi

ok "pip: $($PYTHON -m pip --version | head -1)"

# git
if ! command -v git &>/dev/null; then
    err "git is required but not found."
    exit 1
fi

ok "git: $(git --version)"

# --------------------------------------------------------------------------
# Install
# --------------------------------------------------------------------------

cd "$PROJECT_ROOT"

MODE="${1:-}"

if [[ "$MODE" == "--prod" ]]; then
    info "Installing meta-harness (production mode)..."
    $PYTHON -m pip install . -q 2>&1 | grep -v '^\[notice\]' || true
else
    info "Installing meta-harness (editable/dev mode with test dependencies)..."
    $PYTHON -m pip install -e ".[dev]" -q 2>&1 | grep -v '^\[notice\]' || true
fi

ok "Package installed."

# --------------------------------------------------------------------------
# Verify installation
# --------------------------------------------------------------------------

info "Verifying CLI is available..."

if $PYTHON -m meta_harness.cli --help &>/dev/null; then
    ok "CLI module loads correctly."
else
    err "CLI module failed to load. Check the installation."
    exit 1
fi

# Check the entry point is on PATH
if command -v meta-harness &>/dev/null; then
    ok "meta-harness command is on PATH."
else
    info "meta-harness command is not on PATH (pip scripts dir may not be in \$PATH)."
    info "You can still run it via: $PYTHON -m meta_harness.cli <subcommand>"
fi

# --------------------------------------------------------------------------
# Run tests (dev mode only)
# --------------------------------------------------------------------------

if [[ "$MODE" != "--prod" ]]; then
    info "Running test suite..."
    set +e
    $PYTHON -m pytest tests/ -v --tb=short
    test_exit=$?
    set -e
    if [[ $test_exit -eq 0 ]]; then
        ok "All tests passed."
    else
        err "Some tests failed (exit code $test_exit). See output above."
        info "Setup is complete — the failures above may need investigation."
    fi
fi

# --------------------------------------------------------------------------
# Done
# --------------------------------------------------------------------------

echo ""
ok "Setup complete."
echo ""
info "Quick start:"
echo "  meta-harness status                        # check if a repo is initialized"
echo "  meta-harness review --range 'last 7 days'  # run a reflective pass"
echo "  meta-harness maintenance                   # trigger maintenance"
echo ""
info "To set up as a Claude Code skill, run:"
echo "  ./scripts/install-skill.sh /path/to/your/repo"
echo ""
