"""
Step 1 gate — Knowledge base & setup script (HARD gate): Integration tests.

Spec refs:
  docs/spec/02-storage/decisions-git.md
  docs/spec/04-processes/run-loop.md  (Phase 1)
  docs/IMPLEMENTATION.md § "Git structure"

Gate criteria verified here (from docs/PLAN.md, Step 1):
  2. The decisions branch exists and is detached from the active branch.
  4. Running setup twice produces byte-identical state (idempotent).

These tests require a real git repository (provided by the tmp_git_repo fixture
in tests/conftest.py) because they inspect git branch state directly.

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import hashlib
import subprocess
from pathlib import Path

import pytest

from claude_reflect.storage.knowledge_base import setup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout, stripped."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _hash_directory(root: Path) -> dict[str, str]:
    """
    Return {relative_path_str: sha256_hex} for every regular file under root.
    Sorted by path for deterministic comparison output.
    """
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root))
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _diff_snapshots(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Return human-readable lines describing differences between two snapshots."""
    all_keys = sorted(set(before) | set(after))
    lines = []
    for k in all_keys:
        b, a = before.get(k), after.get(k)
        if b != a:
            lines.append(f"  {k}: {b or '(missing)'!r} → {a or '(missing)'!r}")
    return lines


# ---------------------------------------------------------------------------
# Test class: decisions git branch
# ---------------------------------------------------------------------------

class TestDecisionsBranch:
    """
    setup() must create the claude-reflect/decisions git branch.
    After setup(), HEAD must remain on the original active branch.

    Spec: docs/IMPLEMENTATION.md § "Git structure"
      'Decisions branch. Named claude-reflect/decisions.'
    Spec: docs/spec/04-processes/run-loop.md Phase 1
      'Initialize the decisions git branch.'
    Gate: docs/PLAN.md Step 1
      'the decisions branch exists and is detached from the active branch'
    """

    def test_decisions_branch_exists_after_setup(self, tmp_git_repo):
        setup(tmp_git_repo)
        branches = _git(["branch", "--list", "claude-reflect/decisions"], tmp_git_repo)
        assert "claude-reflect/decisions" in branches, (
            "Expected branch 'claude-reflect/decisions' to exist after setup(). "
            f"git branch --list output: {branches!r}"
        )

    def test_head_is_not_on_decisions_branch_after_setup(self, tmp_git_repo):
        """
        setup() must leave HEAD on the original working branch, not switch
        to claude-reflect/decisions.
        """
        setup(tmp_git_repo)
        current = _git(["rev-parse", "--abbrev-ref", "HEAD"], tmp_git_repo)
        assert current != "claude-reflect/decisions", (
            "setup() must not leave HEAD on 'claude-reflect/decisions'. "
            f"Current HEAD: {current!r}"
        )

    def test_active_branch_unchanged_after_setup(self, tmp_git_repo):
        """
        The branch that was active before setup() is still active afterward.
        setup() must not silently switch branches.
        """
        branch_before = _git(["rev-parse", "--abbrev-ref", "HEAD"], tmp_git_repo)
        setup(tmp_git_repo)
        branch_after = _git(["rev-parse", "--abbrev-ref", "HEAD"], tmp_git_repo)
        assert branch_before == branch_after, (
            f"Active branch changed from {branch_before!r} to {branch_after!r} during setup(). "
            "setup() must not switch the user's working branch."
        )


# ---------------------------------------------------------------------------
# Test class: idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """
    Running setup() twice in succession must produce byte-identical state.

    Gate: docs/PLAN.md Step 1 — 'running setup twice produces byte-identical state (idempotent)'
    Spec: docs/spec/04-processes/run-loop.md Phase 1 — 'If the knowledge base exists, this phase is a no-op.'
    Cross-cutting caution: docs/IMPLEMENTATION.md § 'Idempotent maintenance'
    """

    def test_file_state_is_byte_identical_after_second_setup(self, tmp_git_repo):
        """
        All files under .claude-reflect/ must have the same content after the
        second call to setup() as after the first call.
        """
        setup(tmp_git_repo)
        snapshot_1 = _hash_directory(tmp_git_repo / ".claude-reflect")

        setup(tmp_git_repo)
        snapshot_2 = _hash_directory(tmp_git_repo / ".claude-reflect")

        diffs = _diff_snapshots(snapshot_1, snapshot_2)
        assert not diffs, (
            "setup() is not idempotent. File state changed between first and second call:\n"
            + "\n".join(diffs)
        )

    def test_no_new_files_after_second_setup(self, tmp_git_repo):
        """
        The second call to setup() must not create any files that the first
        call did not create.
        """
        setup(tmp_git_repo)
        files_1 = {
            str(p.relative_to(tmp_git_repo / ".claude-reflect"))
            for p in (tmp_git_repo / ".claude-reflect").rglob("*")
            if p.is_file()
        }

        setup(tmp_git_repo)
        files_2 = {
            str(p.relative_to(tmp_git_repo / ".claude-reflect"))
            for p in (tmp_git_repo / ".claude-reflect").rglob("*")
            if p.is_file()
        }

        new_files = files_2 - files_1
        assert not new_files, (
            f"Second call to setup() created unexpected new files: {new_files}"
        )

    def test_decisions_branch_tip_unchanged_after_second_setup(self, tmp_git_repo):
        """
        The commit SHA at claude-reflect/decisions must be the same after
        the first and second calls to setup(). No extra commits on second run.
        """
        setup(tmp_git_repo)
        sha_1 = _git(["rev-parse", "claude-reflect/decisions"], tmp_git_repo)

        setup(tmp_git_repo)
        sha_2 = _git(["rev-parse", "claude-reflect/decisions"], tmp_git_repo)

        assert sha_1 == sha_2, (
            "setup() committed extra commits to 'claude-reflect/decisions' on the second call. "
            f"SHA before: {sha_1}, SHA after: {sha_2}. "
            "setup() must be a no-op when the knowledge base already exists."
        )

    def test_second_setup_does_not_raise(self, tmp_git_repo):
        """setup() called on an already-initialized KB must not raise any exception."""
        setup(tmp_git_repo)
        # Should not raise:
        setup(tmp_git_repo)
