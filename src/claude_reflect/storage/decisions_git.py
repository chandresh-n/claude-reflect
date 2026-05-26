"""
Decisions git branch operations

Spec ref: docs/spec/02-storage/decisions-git.md

Public API:
- get_current_branch(repo) -> str
- create_proposal_branch(repo, proposal_id) -> None
- commit_decision(repo, decision) -> None
- read_decision_from_commit(repo, proposal_id) -> dict
- merge_proposal_branch(repo, proposal_id) -> None
- delete_proposal_branch(repo, proposal_id) -> None

All git operations that write to the decisions branch or proposal branches
leave the caller's checked-out branch unchanged (no branch switching visible
to callers). Worktrees are used to commit to the decisions branch in
isolation.

Branch naming:
- decisions branch: claude-reflect/decisions
- proposal branches: claude-reflect/proposal/<proposal_id>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from claude_reflect.storage.decision_record import (
    format_commit_message,
    parse_commit_body,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command in *cwd* and return stripped stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _proposal_branch_name(proposal_id: str) -> str:
    return f"claude-reflect/proposal/{proposal_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_current_branch(repo: Path) -> str:
    """Return the name of the currently checked-out branch in *repo*."""
    return _git(["branch", "--show-current"], repo)


def create_proposal_branch(repo: Path, proposal_id: str) -> None:
    """
    Create a local branch named claude-reflect/proposal/<proposal_id> from the
    current HEAD.

    Does not switch the checked-out branch.
    """
    _git(["branch", _proposal_branch_name(proposal_id)], repo)


def commit_decision(repo: Path, decision: dict) -> None:
    """
    Commit *decision* to the claude-reflect/decisions branch.

    Uses a git worktree so that the caller's checked-out branch is not
    changed. The decision is written as a JSON file named <proposal_id>.json
    and the commit message follows the format_commit_message convention
    (structured header + JSON body) to support git log --grep queries.

    Leaves the checked-out branch unchanged.
    """
    proposal_id = decision["proposal_id"]
    commit_msg = format_commit_message(decision)

    # Create a temporary directory that does not yet exist for the worktree.
    tmp_parent = Path(tempfile.mkdtemp())
    worktree_path = tmp_parent / "decisions_worktree"

    # Write commit message to a temp file (avoids shell quoting issues with
    # large JSON bodies embedded in the message).
    msg_fd, msg_path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(msg_fd, "w", encoding="utf-8") as f:
            f.write(commit_msg)

        _git(["worktree", "add", str(worktree_path), "claude-reflect/decisions"], repo)
        try:
            # Write the decision JSON file into the worktree.
            decision_file = worktree_path / f"{proposal_id}.json"
            decision_file.write_text(
                json.dumps(decision, indent=2), encoding="utf-8"
            )

            subprocess.run(
                ["git", "add", f"{proposal_id}.json"],
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-F", msg_path],
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
            )
        finally:
            _git(["worktree", "remove", "--force", str(worktree_path)], repo)
    finally:
        try:
            os.unlink(msg_path)
        except OSError:
            pass
        shutil.rmtree(str(tmp_parent), ignore_errors=True)


def read_decision_from_commit(repo: Path, proposal_id: str) -> dict:
    """
    Find the commit on claude-reflect/decisions whose message contains
    'proposal_id: <proposal_id>' and parse the JSON body from that commit.

    Returns the decision record dict.
    Raises ValueError if no matching commit is found.
    """
    result = subprocess.run(
        [
            "git", "log", "claude-reflect/decisions",
            f"--grep=proposal_id: {proposal_id}",
            "--format=%H",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    hashes = [h.strip() for h in result.stdout.splitlines() if h.strip()]
    if not hashes:
        raise ValueError(
            f"No commit found on claude-reflect/decisions for proposal_id: {proposal_id!r}"
        )

    # Use the most recent matching commit.
    commit_hash = hashes[0]
    msg = subprocess.run(
        ["git", "show", "--no-patch", "--format=%B", commit_hash],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    return parse_commit_body(msg)


def merge_proposal_branch(repo: Path, proposal_id: str) -> None:
    """
    Merge the claude-reflect/proposal/<proposal_id> branch into the currently
    checked-out branch (the active configuration branch), then delete the
    proposal branch.

    This is the accepted-decision path. The merge uses --ff to allow
    fast-forward when the proposal branch has diverged, and is a no-op if the
    proposal branch is already at or behind HEAD.

    Leaves the checked-out branch unchanged (merge, not checkout).
    """
    branch = _proposal_branch_name(proposal_id)
    # Merge — "Already up to date." is acceptable when no diff was authored.
    subprocess.run(
        ["git", "merge", "--ff", branch],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    # Delete the proposal branch after merge.
    _git(["branch", "-D", branch], repo)


def delete_proposal_branch(repo: Path, proposal_id: str) -> None:
    """
    Delete the claude-reflect/proposal/<proposal_id> branch without merging it.

    This is the rejected or author-failed path. Force-deletes (-D) because
    the branch may not have been merged into the active configuration branch.

    Leaves the checked-out branch unchanged.
    """
    _git(["branch", "-D", _proposal_branch_name(proposal_id)], repo)
