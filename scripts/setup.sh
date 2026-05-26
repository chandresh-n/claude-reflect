#!/usr/bin/env bash
#
# setup.sh — Install claude-reflect and verify the installation.
#
# Usage:
#   ./scripts/setup.sh          # install in dev mode (editable, run tests)
#   ./scripts/setup.sh --prod   # install as a regular package, skip tests
#
# Install strategy:
#   1. Try a direct system pip install first.
#   2. If that fails (commonly PEP 668 externally-managed Python on
#      Homebrew / Debian / Ubuntu), fall back to a venv at <repo>/.venv,
#      install into it, and wire a `claude-reflect` alias into
#      ~/.bashrc and ~/.zshrc so the command works in any new shell.
#
# Requirements:
#   - Python 3.11+
#   - pip
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
warn()  { printf '\033[1;33m[warn]\033[0m  %s\n' "$*" >&2; }
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
    PIP_ARGS=("install" ".")
else
    PIP_ARGS=("install" "-e" ".[dev]")
fi

INSTALL_MODE="system"   # set to "venv" if we fall back
CLAUDE_REFLECT_BIN=""   # set when INSTALL_MODE=venv
PIP_LOG="$(mktemp -t claude-reflect-setup.XXXXXX)"
trap 'rm -f "$PIP_LOG"' EXIT

info "Attempting direct install ($PYTHON -m pip ${PIP_ARGS[*]})..."
if "$PYTHON" -m pip "${PIP_ARGS[@]}" -q >"$PIP_LOG" 2>&1; then
    ok "Installed against system Python."
else
    pip_exit=$?
    if grep -q "externally-managed-environment" "$PIP_LOG"; then
        warn "System Python is externally managed (PEP 668). Falling back to venv install."
    else
        warn "Direct pip install failed (exit $pip_exit). Falling back to venv install."
        warn "  (pip output above this line — re-run with --verbose-pip for full log)"
        tail -20 "$PIP_LOG" >&2 || true
    fi

    VENV_DIR="$PROJECT_ROOT/.venv"
    if [[ -d "$VENV_DIR" ]]; then
        info "Reusing existing venv at $VENV_DIR"
    else
        info "Creating venv at $VENV_DIR..."
        "$PYTHON" -m venv "$VENV_DIR"
    fi

    info "Installing claude-reflect into venv..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip -q >>"$PIP_LOG" 2>&1
    if ! "$VENV_DIR/bin/python" -m pip "${PIP_ARGS[@]}" -q >>"$PIP_LOG" 2>&1; then
        err "Venv install also failed. Full pip log:"
        cat "$PIP_LOG" >&2
        exit 1
    fi

    INSTALL_MODE="venv"
    CLAUDE_REFLECT_BIN="$VENV_DIR/bin/claude-reflect"
    ok "Installed into venv at $VENV_DIR"

    # ----------------------------------------------------------------------
    # Wire alias into shell rc files (idempotent)
    # ----------------------------------------------------------------------
    MARKER_BEGIN="# >>> claude-reflect alias (managed by scripts/setup.sh) >>>"
    MARKER_END="# <<< claude-reflect alias <<<"

    add_or_update_alias() {
        local rc="$1"
        local block
        block=$(printf '%s\nalias claude-reflect=%q\n%s\n' \
            "$MARKER_BEGIN" "$CLAUDE_REFLECT_BIN" "$MARKER_END")

        # Create the rc file if it doesn't exist so we don't silently skip.
        [[ -e "$rc" ]] || touch "$rc"

        if grep -qF "$MARKER_BEGIN" "$rc"; then
            # Replace existing managed block.
            "$PYTHON" - "$rc" "$MARKER_BEGIN" "$MARKER_END" "$block" <<'PYEOF'
import sys, pathlib
rc = pathlib.Path(sys.argv[1])
begin, end, block = sys.argv[2], sys.argv[3], sys.argv[4]
text = rc.read_text()
i = text.find(begin)
j = text.find(end, i)
if i == -1 or j == -1:
    sys.exit(0)
j_end = text.find('\n', j) + 1 or len(text)
rc.write_text(text[:i] + block + '\n' + text[j_end:])
PYEOF
            ok "Updated claude-reflect alias in $rc"
        else
            # Append a fresh block, preceded by a blank line for readability.
            {
                printf '\n%s\n' "$block"
            } >> "$rc"
            ok "Added claude-reflect alias to $rc"
        fi
    }

    add_or_update_alias "$HOME/.bashrc"
    add_or_update_alias "$HOME/.zshrc"
fi

# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------

info "Verifying CLI is callable..."

if [[ "$INSTALL_MODE" == "venv" ]]; then
    if "$CLAUDE_REFLECT_BIN" --help &>/dev/null; then
        ok "claude-reflect works at $CLAUDE_REFLECT_BIN"
    else
        err "Venv binary failed to load: $CLAUDE_REFLECT_BIN"
        exit 1
    fi
else
    if "$PYTHON" -m claude_reflect.cli --help &>/dev/null; then
        ok "CLI module loads correctly."
    else
        err "CLI module failed to load."
        exit 1
    fi
    if command -v claude-reflect &>/dev/null; then
        ok "claude-reflect is on PATH ($(command -v claude-reflect))."
    else
        warn "claude-reflect is not on PATH (pip scripts dir may not be in \$PATH)."
        warn "You can still run it via: $PYTHON -m claude_reflect.cli <subcommand>"
    fi
fi

# --------------------------------------------------------------------------
# Run tests (dev mode only)
# --------------------------------------------------------------------------

if [[ "$MODE" != "--prod" ]]; then
    info "Running test suite..."
    if [[ "$INSTALL_MODE" == "venv" ]]; then
        PYTEST_PY="$PROJECT_ROOT/.venv/bin/python"
    else
        PYTEST_PY="$PYTHON"
    fi
    set +e
    "$PYTEST_PY" -m pytest tests/ --tb=short
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

if [[ "$INSTALL_MODE" == "venv" ]]; then
    info "Open a new terminal (or 'source ~/.zshrc' / 'source ~/.bashrc') before using:"
fi

echo "  claude-reflect status                       # check if a repo is initialized"
echo "  claude-reflect review --pick                # interactively pick recent sessions"
echo "  claude-reflect review --range 'yesterday'   # run a pass over a date range"
echo "  claude-reflect maintenance                  # trigger maintenance"
echo ""
