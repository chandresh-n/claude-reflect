"""
Knowledge base setup — Phase 1 of the run loop.

Creates the .meta-harness/ directory layout in the target repository,
initializes the meta-harness/decisions git branch, and writes a default
config.yaml with every required field.

Idempotent: calling setup() on an already-initialized repository is a no-op.
The second call produces byte-identical on-disk state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

# Expressed as a Python dict so that field order and types are explicit and
# not subject to YAML-round-trip drift on subsequent calls.
_DEFAULT_CONFIG: dict = {
    "models": {
        "evaluator": "claude-opus-4-6",
        "proposer": "claude-opus-4-6",
        "author": "claude-sonnet-4-6",
    },
    "maintenance": {
        "trigger_thresholds": {
            "new_sessions": 10,
            "new_decisions": 5,
            "new_gap_records": 3,
            "days_since_last": 7,
        },
    },
    "stale_gap_threshold_sessions": 30,
    "forced_novelty": {
        "probability": 0.20,
        "null_baseline_probability": 0.01,
    },
    "window_warnings": {
        "small_window_threshold_sessions": 3,
        "large_window_threshold_sessions": 50,
    },
    "logging": {
        "default_verbosity": "quiet",
        "save_full_transcripts": True,
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command in *cwd* and return stdout, stripped."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _decisions_branch_exists(repo: Path) -> bool:
    """Return True if the meta-harness/decisions branch exists in *repo*."""
    result = subprocess.run(
        ["git", "branch", "--list", "meta-harness/decisions"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return "meta-harness/decisions" in result.stdout


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup(repo: Path) -> None:
    """
    Initialize the meta-harness knowledge base in the target git repository.

    Phase 1 of the run loop:
    - Create the .meta-harness/ directory layout.
    - Initialize the meta-harness/decisions git branch.
    - Initialize the summary layer directory with an empty index.
    - Write a default config.yaml with every required field.

    Idempotent: safe to call on an already-initialized repository. The second
    call produces byte-identical file state and does not add commits to the
    decisions branch.

    Args:
        repo: Absolute path to the root of the target git repository.
    """
    kb = repo / ".meta-harness"

    # -----------------------------------------------------------------------
    # Directory layout
    # All directories use exist_ok=True so repeated calls are a no-op.
    # -----------------------------------------------------------------------
    dirs = [
        kb,
        kb / "gaps",
        kb / "archive",
        kb / "summary",
        kb / "summary" / "gap-kinds",
        kb / "summary" / "archive-entries",
        kb / "summary" / "session-clusters",
        kb / "summary" / "decision-lineages",
        kb / "runs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # summary/index.md — written once; never overwritten (idempotency)
    # Phase 1: "Initialize the summary layer directory with an empty index."
    # -----------------------------------------------------------------------
    index_md = kb / "summary" / "index.md"
    if not index_md.exists():
        index_md.write_text("# Summary index\n", encoding="utf-8")

    # -----------------------------------------------------------------------
    # config.yaml — written once; never overwritten (idempotency)
    # Fields: every key from IMPLEMENTATION.md § "Configuration file".
    # -----------------------------------------------------------------------
    config_path = kb / "config.yaml"
    if not config_path.exists():
        config_path.write_text(
            yaml.dump(_DEFAULT_CONFIG, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    # -----------------------------------------------------------------------
    # meta-harness/decisions git branch
    # Created from the current HEAD. HEAD is not switched; the user's working
    # branch is unchanged after setup() returns.
    # -----------------------------------------------------------------------
    if not _decisions_branch_exists(repo):
        _git(["branch", "meta-harness/decisions"], repo)
