"""
Step 3 gate — Decision record + git ops (HARD gate): Integration tests.

Spec refs:
  docs/spec/01-data-structures/decision-record.md
  docs/spec/02-storage/decisions-git.md

Gate criteria (from docs/PLAN.md Step 3):
  4. Proposal-branch lifecycle exercised end-to-end:
     create → commit → merge (accepted) or delete (rejected/author_failed).
  1. Commit-message header parses correctly (verified against real git log).
  2. Decision JSON roundtrips through the commit body (verified via git show).

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import json
import subprocess
from pathlib import Path

import pytest

from claude_reflect.storage.decision_record import (
    create_decision_record,
    format_commit_message,
    parse_commit_header,
    parse_commit_body,
)
from claude_reflect.storage.decisions_git import (
    commit_decision,
    read_decision_from_commit,
    create_proposal_branch,
    merge_proposal_branch,
    delete_proposal_branch,
    get_current_branch,
)
from claude_reflect.storage.knowledge_base import setup


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_WHY = {
    "cited_gaps": [{"gap_id": "G-001", "note": "Addresses the tool-call-loop gap."}],
    "cited_sessions": [{"session_id": "sess-001", "turn_range": {"start": 0, "end": 3}}],
    "cited_prior_decisions": [],
    "prose_summary": "This proposal addresses the tool-call loop gap.",
}

VALID_WHAT_ACCEPTED = {
    "diff_reference": "to-be-filled-by-git",  # placeholder; real tests set after commit
    "files_touched": ["CLAUDE.md"],
    "short_description": "Add tool-call loop recovery instruction to CLAUDE.md.",
}

VALID_PREDICTION_OUTCOME = {
    "status": "not_yet_due",
    "evidence": None,
    "commentary": None,
}

VALID_STRUCTURAL_TAGS = {
    "change_type": "addition",
    "surface": "claude_md",
    "novelty_status": "normal",
    "exploration_rationale": None,
}

VALID_ACCEPTED_DECISION = {
    "proposal_id": "P-001",
    "run_id": "R-001",
    "batch_id": "B-001",
    "created_at": "2024-01-15T10:00:00+00:00",
    "reviewed_at": "2024-01-15T11:00:00+00:00",
    "status": "accepted",
    "human_reasoning": None,
    "author_failure_reason": None,
    "why": VALID_WHY,
    "what": VALID_WHAT_ACCEPTED,
    "how": "The instruction guides the model to detect and break tool-call loops.",
    "prediction": "Tool-call loop frequency drops over the next 5 sessions.",
    "prediction_outcome": VALID_PREDICTION_OUTCOME,
    "targeted_gaps": ["G-001"],
    "authoring_addendum": {"spec": "Add a recovery note after the tool-call section."},
    "structural_tags": VALID_STRUCTURAL_TAGS,
    "superseded_by": None,
}

VALID_REJECTED_DECISION = {
    **VALID_ACCEPTED_DECISION,
    "proposal_id": "P-002",
    "status": "rejected",
    "human_reasoning": "The change is too broad; prefer a more focused approach.",
    "what": {
        "diff_reference": None,
        "files_touched": [],
        "short_description": "Add tool-call loop recovery instruction.",
    },
    "author_failure_reason": None,
}

VALID_AUTHOR_FAILED_DECISION = {
    **VALID_ACCEPTED_DECISION,
    "proposal_id": "P-003",
    "status": "author_failed",
    "reviewed_at": "2024-01-15T10:30:00+00:00",
    "human_reasoning": None,
    "author_failure_reason": "Could not locate the target section in CLAUDE.md.",
    "what": {
        "diff_reference": None,
        "files_touched": [],
        "short_description": "Add tool-call loop recovery instruction.",
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kb_repo(tmp_git_repo: Path) -> Path:
    """Temporary git repo with the knowledge base (including decisions branch) initialized."""
    setup(tmp_git_repo)
    return tmp_git_repo


def _get_all_branches(repo: Path) -> list[str]:
    """Return all local branch names in the repo."""
    result = subprocess.run(
        ["git", "branch", "--list", "--format=%(refname:short)"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return [b.strip() for b in result.stdout.splitlines() if b.strip()]


def _get_all_commits_on_branch(repo: Path, branch: str) -> list[str]:
    """Return the list of commit hashes on a branch."""
    result = subprocess.run(
        ["git", "log", branch, "--format=%H"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return [h.strip() for h in result.stdout.splitlines() if h.strip()]


def _get_commit_message(repo: Path, commit_hash: str) -> str:
    """Return the full commit message for a given hash."""
    result = subprocess.run(
        ["git", "show", "--no-patch", "--format=%B", commit_hash],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _branch_exists(repo: Path, branch_name: str) -> bool:
    """Return True if the named branch exists in the repo."""
    return branch_name in _get_all_branches(repo)


# ---------------------------------------------------------------------------
# Criterion 4a: Proposal-branch lifecycle — accepted (create → commit → merge)
# ---------------------------------------------------------------------------

class TestProposalBranchLifecycleAccepted:
    """
    Accepted lifecycle:
      1. create_proposal_branch creates a branch named after the proposal_id.
      2. commit_decision commits the decision record to claude-reflect/decisions.
      3. merge_proposal_branch merges the proposal branch into the active
         configuration branch and removes the proposal branch.
    """

    def test_create_proposal_branch_creates_the_branch(self, kb_repo):
        """create_proposal_branch must create a local branch claude-reflect/proposal/<id>."""
        create_proposal_branch(kb_repo, "P-001")
        assert _branch_exists(kb_repo, "claude-reflect/proposal/P-001")

    def test_create_proposal_branch_does_not_switch_active_branch(self, kb_repo):
        """create_proposal_branch must not change the currently checked-out branch."""
        original_branch = get_current_branch(kb_repo)
        create_proposal_branch(kb_repo, "P-001")
        assert get_current_branch(kb_repo) == original_branch

    def test_commit_decision_adds_commit_to_decisions_branch(self, kb_repo):
        """commit_decision must add at least one new commit to claude-reflect/decisions."""
        before = _get_all_commits_on_branch(kb_repo, "claude-reflect/decisions")
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)
        after = _get_all_commits_on_branch(kb_repo, "claude-reflect/decisions")
        assert len(after) > len(before)

    def test_commit_decision_does_not_switch_active_branch(self, kb_repo):
        """commit_decision must not change the currently checked-out branch."""
        original_branch = get_current_branch(kb_repo)
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)
        assert get_current_branch(kb_repo) == original_branch

    def test_commit_decision_header_is_searchable_via_grep(self, kb_repo):
        """
        The committed message must contain 'targeted_gap: G-001' so that
        git log --grep 'targeted_gap: G-001' finds this commit.
        """
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)

        result = subprocess.run(
            ["git", "log", "claude-reflect/decisions",
             "--grep=targeted_gap: G-001", "--format=%H"],
            cwd=str(kb_repo),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip(), (
            "git log --grep 'targeted_gap: G-001' returned no commits. "
            "Commit header must use 'targeted_gap: <id>' format per the spec."
        )

    def test_commit_decision_header_searchable_by_proposal_id(self, kb_repo):
        """git log --grep 'proposal_id: P-001' must find the committed decision."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)

        result = subprocess.run(
            ["git", "log", "claude-reflect/decisions",
             "--grep=proposal_id: P-001", "--format=%H"],
            cwd=str(kb_repo),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip()

    def test_read_decision_from_commit_roundtrips_proposal_id(self, kb_repo):
        """read_decision_from_commit must recover the proposal_id from git."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)
        recovered = read_decision_from_commit(kb_repo, "P-001")
        assert recovered["proposal_id"] == "P-001"

    def test_read_decision_from_commit_roundtrips_status(self, kb_repo):
        """read_decision_from_commit must recover the status from git."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)
        recovered = read_decision_from_commit(kb_repo, "P-001")
        assert recovered["status"] == "accepted"

    def test_read_decision_from_commit_roundtrips_targeted_gaps(self, kb_repo):
        """read_decision_from_commit must recover targeted_gaps from git."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)
        recovered = read_decision_from_commit(kb_repo, "P-001")
        assert "G-001" in recovered["targeted_gaps"]

    def test_merge_proposal_branch_removes_the_proposal_branch(self, kb_repo):
        """After merge_proposal_branch, the proposal branch must no longer exist."""
        create_proposal_branch(kb_repo, "P-001")
        assert _branch_exists(kb_repo, "claude-reflect/proposal/P-001")
        merge_proposal_branch(kb_repo, "P-001")
        assert not _branch_exists(kb_repo, "claude-reflect/proposal/P-001")

    def test_merge_proposal_branch_does_not_switch_active_branch(self, kb_repo):
        """merge_proposal_branch must leave the checked-out branch unchanged."""
        original_branch = get_current_branch(kb_repo)
        create_proposal_branch(kb_repo, "P-001")
        merge_proposal_branch(kb_repo, "P-001")
        assert get_current_branch(kb_repo) == original_branch

    def test_full_accepted_lifecycle(self, kb_repo):
        """
        End-to-end accepted lifecycle:
          create_proposal_branch → commit_decision → merge_proposal_branch.
        Final state: proposal branch gone, decision readable from git.
        """
        original_branch = get_current_branch(kb_repo)

        # Phase 1: proposal branch exists
        create_proposal_branch(kb_repo, "P-001")
        assert _branch_exists(kb_repo, "claude-reflect/proposal/P-001")

        # Phase 2: decision committed to decisions branch
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)

        # Phase 3: merge (accepted) → proposal branch gone
        merge_proposal_branch(kb_repo, "P-001")
        assert not _branch_exists(kb_repo, "claude-reflect/proposal/P-001")

        # Active branch unchanged
        assert get_current_branch(kb_repo) == original_branch

        # Decision still readable
        recovered = read_decision_from_commit(kb_repo, "P-001")
        assert recovered["status"] == "accepted"


# ---------------------------------------------------------------------------
# Criterion 4b: Proposal-branch lifecycle — rejected (create → commit → delete)
# ---------------------------------------------------------------------------

class TestProposalBranchLifecycleRejected:
    """
    Rejected lifecycle:
      1. create_proposal_branch (branch exists for the review period).
      2. commit_decision (rejected record committed to decisions branch).
      3. delete_proposal_branch (branch deleted, no merge to active config).
    """

    def test_delete_proposal_branch_removes_the_branch(self, kb_repo):
        """delete_proposal_branch must remove the proposal branch."""
        create_proposal_branch(kb_repo, "P-002")
        assert _branch_exists(kb_repo, "claude-reflect/proposal/P-002")
        delete_proposal_branch(kb_repo, "P-002")
        assert not _branch_exists(kb_repo, "claude-reflect/proposal/P-002")

    def test_delete_proposal_branch_does_not_switch_active_branch(self, kb_repo):
        """delete_proposal_branch must leave the checked-out branch unchanged."""
        original_branch = get_current_branch(kb_repo)
        create_proposal_branch(kb_repo, "P-002")
        delete_proposal_branch(kb_repo, "P-002")
        assert get_current_branch(kb_repo) == original_branch

    def test_full_rejected_lifecycle(self, kb_repo):
        """
        End-to-end rejected lifecycle:
          create_proposal_branch → commit_decision → delete_proposal_branch.
        Final state: proposal branch gone, rejected decision readable from git.
        """
        original_branch = get_current_branch(kb_repo)

        create_proposal_branch(kb_repo, "P-002")
        assert _branch_exists(kb_repo, "claude-reflect/proposal/P-002")

        decision = create_decision_record(VALID_REJECTED_DECISION.copy())
        commit_decision(kb_repo, decision)

        delete_proposal_branch(kb_repo, "P-002")
        assert not _branch_exists(kb_repo, "claude-reflect/proposal/P-002")

        assert get_current_branch(kb_repo) == original_branch

        recovered = read_decision_from_commit(kb_repo, "P-002")
        assert recovered["status"] == "rejected"

    def test_rejected_decision_not_merged_to_active_config_branch(self, kb_repo):
        """
        A rejected proposal branch must be deleted, not merged.
        We verify this by confirming that the active-config-branch commit
        log does not grow after delete_proposal_branch.
        """
        original_branch = get_current_branch(kb_repo)
        before_commits = _get_all_commits_on_branch(kb_repo, original_branch)

        create_proposal_branch(kb_repo, "P-002")
        decision = create_decision_record(VALID_REJECTED_DECISION.copy())
        commit_decision(kb_repo, decision)
        delete_proposal_branch(kb_repo, "P-002")

        after_commits = _get_all_commits_on_branch(kb_repo, original_branch)
        assert len(after_commits) == len(before_commits), (
            "Rejected proposal branch must be deleted, not merged into the "
            "active configuration branch."
        )


# ---------------------------------------------------------------------------
# Criterion 4c: Proposal-branch lifecycle — author_failed (create → commit → delete)
# ---------------------------------------------------------------------------

class TestProposalBranchLifecycleAuthorFailed:
    """
    Author-failed lifecycle:
      1. commit_decision (author-failed record committed to decisions branch;
         no proposal branch may be created if the author never produced a diff,
         but the implementation may create a branch and immediately delete it).
      2. No merge to the active configuration branch.
    """

    def test_full_author_failed_lifecycle(self, kb_repo):
        """
        End-to-end author_failed lifecycle:
          (optional create_proposal_branch) → commit_decision →
          delete_proposal_branch (if created).
        Final state: no proposal branch, author_failed decision readable from git.
        """
        original_branch = get_current_branch(kb_repo)

        # Author-failed proposals may or may not have a proposal branch
        # depending on when the failure occurred. If created, it must be deleted.
        if _branch_exists(kb_repo, "claude-reflect/proposal/P-003"):
            delete_proposal_branch(kb_repo, "P-003")

        decision = create_decision_record(VALID_AUTHOR_FAILED_DECISION.copy())
        commit_decision(kb_repo, decision)

        # Confirm the branch is not present after the failure
        assert not _branch_exists(kb_repo, "claude-reflect/proposal/P-003")

        # Active branch unchanged
        assert get_current_branch(kb_repo) == original_branch

        # Decision readable
        recovered = read_decision_from_commit(kb_repo, "P-003")
        assert recovered["status"] == "author_failed"

    def test_author_failed_decision_not_merged_to_active_config_branch(self, kb_repo):
        """
        An author-failed decision must never produce a merge on the active
        configuration branch.
        """
        original_branch = get_current_branch(kb_repo)
        before_commits = _get_all_commits_on_branch(kb_repo, original_branch)

        decision = create_decision_record(VALID_AUTHOR_FAILED_DECISION.copy())
        commit_decision(kb_repo, decision)

        after_commits = _get_all_commits_on_branch(kb_repo, original_branch)
        assert len(after_commits) == len(before_commits), (
            "Author-failed decision must not produce a merge on the active "
            "configuration branch."
        )


# ---------------------------------------------------------------------------
# Decisions branch: append-only invariant
# ---------------------------------------------------------------------------

class TestDecisionsBranchAppendOnly:
    """
    Spec (decisions-git.md § Invariants):
      The decisions branch is append-only in practice. Decisions are not
      rewritten after commit.
    """

    def test_multiple_decisions_accumulate_on_decisions_branch(self, kb_repo):
        """
        Committing two separate decisions must produce two separate commits on
        the decisions branch (not one overwriting the other).
        """
        d1 = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, d1)

        d2_data = {**VALID_REJECTED_DECISION}
        d2 = create_decision_record(d2_data)
        commit_decision(kb_repo, d2)

        commits = _get_all_commits_on_branch(kb_repo, "claude-reflect/decisions")
        # Both decisions should be visible as distinct commits
        messages = [_get_commit_message(kb_repo, h) for h in commits]
        has_p001 = any("proposal_id: P-001" in m for m in messages)
        has_p002 = any("proposal_id: P-002" in m for m in messages)
        assert has_p001, "Commit for P-001 not found on decisions branch."
        assert has_p002, "Commit for P-002 not found on decisions branch."

    def test_read_decision_from_commit_raises_for_unknown_proposal_id(self, kb_repo):
        """read_decision_from_commit must raise if the proposal_id has no commit."""
        with pytest.raises(Exception):
            read_decision_from_commit(kb_repo, "P-nonexistent")

    def test_commit_decision_stays_on_decisions_branch_not_active(self, kb_repo):
        """
        Decision commits must go to claude-reflect/decisions, not the active
        configuration branch.
        """
        original_branch = get_current_branch(kb_repo)
        before_active = _get_all_commits_on_branch(kb_repo, original_branch)
        before_decisions = _get_all_commits_on_branch(kb_repo, "claude-reflect/decisions")

        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        commit_decision(kb_repo, decision)

        after_active = _get_all_commits_on_branch(kb_repo, original_branch)
        after_decisions = _get_all_commits_on_branch(kb_repo, "claude-reflect/decisions")

        assert len(after_active) == len(before_active), (
            "commit_decision must not add commits to the active config branch."
        )
        assert len(after_decisions) > len(before_decisions), (
            "commit_decision must add commits to claude-reflect/decisions."
        )
