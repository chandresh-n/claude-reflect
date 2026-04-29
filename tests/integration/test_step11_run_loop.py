"""
Integration tests for Step 11 — Run loop orchestration (HARD plumbing gate).

Spec ref: docs/spec/04-processes/run-loop.md

All agents are mocked with canned responses. No real agent invocations.
These tests verify the plumbing — phase sequencing, pending-proposal
carry-over, resume-from-Phase-7, and v1 crash recovery — not agent quality.

Gate criteria (from docs/PLAN.md Step 11):
1. Phase sequence is correct (phases execute in order, each end state
   reached before the next phase begins).
2. Pending-proposal carry-over from a previous run is handled.
3. Resume-from-Phase-7 works after a simulated crash.
4. Partial pre-Phase-7 run is discarded on next invocation (v1 crash
   recovery).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from meta_harness.processes.run_loop import (
    RunLoop,
    RunState,
    RunLoopError,
)
from meta_harness.storage.knowledge_base import setup
from meta_harness.storage.session_logs import Session, Turn, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Create a bare-minimum git repo with an initial commit."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    (path / "README.md").write_text("init\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )


def _make_session(
    session_id: str = "sess-001",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    turns: Optional[List[Turn]] = None,
) -> Session:
    """Create a minimal Session fixture."""
    now = datetime.now(timezone.utc)
    return Session(
        session_id=session_id,
        start_time=start or now - timedelta(hours=1),
        end_time=end or now,
        file_path=Path("/fake/sessions") / f"{session_id}.jsonl",
        turns=turns or [
            Turn(
                timestamp=now,
                human_input="test prompt",
                assistant_response="test response",
                tool_calls=[],
                model="claude-sonnet-4-6",
                input_tokens=100,
                output_tokens=50,
            ),
        ],
    )


def _canned_evaluator_output(session_id: str = "sess-001") -> dict:
    """Return a minimal valid evaluator output."""
    return {
        "per_turn_observations": [
            {
                "session_id": session_id,
                "turn_index": 0,
                "assessment": "Normal operation",
                "effort_signal": {
                    "tokens_used": 150,
                    "model": "claude-sonnet-4-6",
                    "context_occupancy": 0.1,
                    "tool_calls": [],
                },
                "flags": [],
            },
        ],
        "pass_classifications": [
            {
                "session_id": session_id,
                "turn_range": {"start": 0, "end": 0},
                "pass_type": "successful_one_shot",
                "harness_gap_rationale": "No gap identified",
                "contributing_gaps": None,
            },
        ],
        "gap_observations": [],
        "session_narratives": [
            {
                "session_id": session_id,
                "outcome": "successful_and_accepted",
                "pass_counts_by_type": {"successful_one_shot": 1},
                "gaps_observed": [],
                "narrative": "Single-turn successful session.",
            },
        ],
    }


def _canned_proposal_batch(
    run_id: str = "run-test001",
    batch_id: str = "batch-test001",
    proposal_ids: Optional[List[str]] = None,
) -> dict:
    """Return a minimal valid proposal batch."""
    if proposal_ids is None:
        proposal_ids = ["prop-001"]

    proposals = []
    for pid in proposal_ids:
        proposals.append({
            "proposal_id": pid,
            "batch_id": batch_id,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": f"Test proposal {pid}",
            "why": {
                "cited_gaps": [{"gap_id": "gap-001", "addressing_note": "test"}],
                "cited_sessions": [],
                "cited_prior_decisions": [],
                "prose_summary": "Test proposal rationale",
            },
            "what": {
                "diff_reference": None,
                "files_touched": None,
                "short_description": "Add a test rule",
            },
            "how": "Add a rule to CLAUDE.md",
            "prediction": "Fewer tool-call loops",
            "structural_tags": {
                "change_type": "addition",
                "surface": "claude_md",
                "novelty_status": "normal",
            },
            "authoring_addendum": {
                "actions": [{"type": "modify", "target_path": "CLAUDE.md"}],
                "purpose": "Test purpose",
                "behavior_constraints": ["Test constraint"],
            },
        })

    return {
        "batch_id": batch_id,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": "2026-04-20", "end": "2026-04-27"},
        "proposal_ids": proposal_ids,
        "batch_narrative": f"Batch with {len(proposal_ids)} proposal(s).",
        "contains_forced_novelty": False,
        "proposals": proposals,
    }


def _canned_author_result(
    proposal_id: str, success: bool = True
) -> dict:
    """Return a canned author result."""
    if success:
        return {
            "status": "success",
            "proposal_id": proposal_id,
            "diff_reference": "abc123",
            "files_touched": ["CLAUDE.md"],
            "branch_name": f"meta-harness/proposal/{proposal_id}",
        }
    return {
        "status": "author_failed",
        "proposal_id": proposal_id,
        "author_failure_reason": "Cannot realize this intent in Claude Code.",
        "diff_reference": None,
        "files_touched": None,
        "branch_name": None,
    }


@pytest.fixture
def repo(tmp_path):
    """Create an initialized git repo with meta-harness knowledge base."""
    _init_git_repo(tmp_path)
    setup(tmp_path)
    return tmp_path


@pytest.fixture
def sessions():
    """Return a list of synthetic sessions."""
    return [_make_session("sess-001"), _make_session("sess-002")]


# ===========================================================================
# 1. Phase sequence is correct
# ===========================================================================


class TestPhaseSequence:
    """Phases execute in the order defined by the spec, and each end state
    is reached before the next phase begins."""

    def test_phases_execute_in_order(self, repo, sessions):
        """Run the loop end-to-end with mocked agents and assert phases
        executed in the correct sequential order."""
        phase_log: List[str] = []

        def mock_evaluator(*args, **kwargs):
            phase_log.append("phase_4_evaluation")
            return _canned_evaluator_output()

        def mock_proposer(*args, **kwargs):
            phase_log.append("phase_5a_proposer")
            return _canned_proposal_batch()

        def mock_author(intent, *args, **kwargs):
            phase_log.append("phase_5b_author")
            return _canned_author_result(intent["proposal_id"])

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=mock_evaluator,
            proposer_fn=mock_proposer,
            author_fn=mock_author,
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        state = loop.run()

        # Phase ordering from spec: 0 → 1 → 2 → 2.5 → 3 → 4 → 5a → 5b → 6 → 7 → 8 → 9
        assert "phase_4_evaluation" in phase_log
        assert "phase_5a_proposer" in phase_log
        assert "phase_5b_author" in phase_log

        # Evaluator runs before proposer, proposer before author
        eval_idx = phase_log.index("phase_4_evaluation")
        prop_idx = phase_log.index("phase_5a_proposer")
        auth_idx = phase_log.index("phase_5b_author")
        assert eval_idx < prop_idx < auth_idx

    def test_phase_1_setup_runs_if_not_initialized(self, tmp_path, sessions):
        """On a fresh repo with no knowledge base, Phase 1 auto-runs."""
        _init_git_repo(tmp_path)
        # Do NOT call setup() — the run loop should do it

        loop = RunLoop(
            repo=tmp_path,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        state = loop.run()

        # Knowledge base should now exist
        assert (tmp_path / ".meta-harness").is_dir()
        assert (tmp_path / ".meta-harness" / "config.yaml").is_file()

    def test_phase_1_is_noop_if_already_initialized(self, repo, sessions):
        """If the knowledge base already exists, Phase 1 is a no-op."""
        # Snapshot config before run
        config_before = (repo / ".meta-harness" / "config.yaml").read_bytes()

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        loop.run()

        # Config should be byte-identical
        config_after = (repo / ".meta-harness" / "config.yaml").read_bytes()
        assert config_before == config_after

    def test_phase_5a_completes_before_any_5b(self, repo, sessions):
        """Phase 5a (proposer) must complete entirely before any Phase 5b
        (author) invocations begin — spec invariant."""
        order_log: List[str] = []

        def mock_proposer(*args, **kwargs):
            order_log.append("5a_start")
            batch = _canned_proposal_batch(
                proposal_ids=["prop-A", "prop-B"]
            )
            order_log.append("5a_end")
            return batch

        def mock_author(intent, *args, **kwargs):
            order_log.append(f"5b_{intent['proposal_id']}")
            return _canned_author_result(intent["proposal_id"])

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=mock_proposer,
            author_fn=mock_author,
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        loop.run()

        # All 5b entries must come after 5a_end
        five_a_end_idx = order_log.index("5a_end")
        for i, entry in enumerate(order_log):
            if entry.startswith("5b_"):
                assert i > five_a_end_idx, (
                    f"Author invocation {entry} at index {i} ran before "
                    f"proposer completed at index {five_a_end_idx}"
                )

    def test_every_proposal_produces_exactly_one_decision(self, repo, sessions):
        """Spec invariant: every proposal generated in Phase 5a produces
        exactly one decision record in Phase 8."""
        batch = _canned_proposal_batch(
            proposal_ids=["prop-X", "prop-Y", "prop-Z"]
        )

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: batch,
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda b: {
                p["proposal_id"]: "accepted" for p in b["proposals"]
            },
        )
        state = loop.run()

        # state should contain decisions for all three proposals
        assert state is not None
        assert len(state.decisions) == 3
        decision_pids = {d["proposal_id"] for d in state.decisions}
        assert decision_pids == {"prop-X", "prop-Y", "prop-Z"}

    def test_run_state_is_complete_on_success(self, repo, sessions):
        """A successful run produces a RunState marked complete."""
        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        state = loop.run()
        assert state.status == "complete"


# ===========================================================================
# 2. Pending-proposal carry-over from a previous run
# ===========================================================================


class TestPendingProposalCarryOver:
    """Phase 2.5: pending proposals from prior runs are surfaced and the
    human's choice (resolve, include, defer) is honored."""

    def test_pending_proposals_detected(self, repo, sessions):
        """When pending proposals exist from a prior run, they are detected
        and surfaced at Phase 2.5."""
        # Simulate a prior run that left a proposal pending
        pending_state = RunState(
            run_id="run-prior",
            status="paused",
            current_phase=7,
            pending_proposals=["prop-pending-1"],
        )
        pending_state.save(repo)

        detected_pending: List[str] = []

        def mock_pending_handler(pending_ids):
            detected_pending.extend(pending_ids)
            return "defer"  # defer for now

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
            pending_handler_fn=mock_pending_handler,
        )
        loop.run()

        assert "prop-pending-1" in detected_pending

    def test_pending_defer_leaves_proposals_pending(self, repo, sessions):
        """Deferring pending proposals leaves them unresolved for a future run."""
        pending_state = RunState(
            run_id="run-prior",
            status="paused",
            current_phase=7,
            pending_proposals=["prop-pending-1"],
        )
        pending_state.save(repo)

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
            pending_handler_fn=lambda ids: "defer",
        )
        state = loop.run()

        # The deferred proposals should still be listed as pending
        # (either in the returned state or recoverable from storage)
        assert state.status == "complete"
        # The prior run's pending proposals remain unresolved
        prior_state = RunState.load(repo, "run-prior")
        assert "prop-pending-1" in prior_state.pending_proposals

    def test_pending_include_adds_to_current_batch(self, repo, sessions):
        """Including pending proposals adds them to the current run's batch
        at Phase 6."""
        pending_state = RunState(
            run_id="run-prior",
            status="paused",
            current_phase=7,
            pending_proposals=["prop-pending-1"],
        )
        pending_state.save(repo)

        presented_proposal_ids: List[str] = []

        def mock_review(batch):
            for p in batch["proposals"]:
                presented_proposal_ids.append(p["proposal_id"])
            return {p["proposal_id"]: "accepted" for p in batch["proposals"]}

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(
                proposal_ids=["prop-new-1"]
            ),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=mock_review,
            pending_handler_fn=lambda ids: "include",
        )
        loop.run()

        # Both the pending proposal and the new one should be presented
        assert "prop-pending-1" in presented_proposal_ids
        assert "prop-new-1" in presented_proposal_ids


# ===========================================================================
# 3. Resume-from-Phase-7 works after a simulated crash
# ===========================================================================


class TestResumeFromPhase7:
    """The run loop can resume from Phase 7 (awaiting human review) after
    a crash or explicit pause, without re-running earlier phases."""

    def test_resume_from_phase_7_skips_earlier_phases(self, repo, sessions):
        """Resuming from Phase 7 does NOT re-invoke the evaluator, proposer,
        or author."""
        evaluator_calls = []
        proposer_calls = []
        author_calls = []

        def mock_evaluator(*a, **kw):
            evaluator_calls.append(1)
            return _canned_evaluator_output()

        def mock_proposer(*a, **kw):
            proposer_calls.append(1)
            return _canned_proposal_batch()

        def mock_author(i, *a, **kw):
            author_calls.append(1)
            return _canned_author_result(i["proposal_id"])

        # Simulate a paused run at Phase 7 with a saved batch
        batch = _canned_proposal_batch(
            run_id="run-paused",
            proposal_ids=["prop-resume-1"],
        )
        # Attach author results to the proposals
        for p in batch["proposals"]:
            p["what"]["diff_reference"] = "abc123"
            p["what"]["files_touched"] = ["CLAUDE.md"]

        paused_state = RunState(
            run_id="run-paused",
            status="paused",
            current_phase=7,
            proposal_batch=batch,
            author_results={
                "prop-resume-1": _canned_author_result("prop-resume-1"),
            },
        )
        paused_state.save(repo)

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=mock_evaluator,
            proposer_fn=mock_proposer,
            author_fn=mock_author,
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
            resume_run_id="run-paused",
        )
        state = loop.run()

        # Earlier phases should NOT have been called
        assert len(evaluator_calls) == 0, "Evaluator re-invoked on resume"
        assert len(proposer_calls) == 0, "Proposer re-invoked on resume"
        assert len(author_calls) == 0, "Author re-invoked on resume"

        # But the run should complete
        assert state.status == "complete"

    def test_resume_presents_same_batch(self, repo, sessions):
        """Resuming re-presents the same proposal batch that was shown
        before the pause."""
        batch = _canned_proposal_batch(
            run_id="run-paused2",
            proposal_ids=["prop-A", "prop-B"],
        )
        for p in batch["proposals"]:
            p["what"]["diff_reference"] = "abc123"
            p["what"]["files_touched"] = ["CLAUDE.md"]

        paused_state = RunState(
            run_id="run-paused2",
            status="paused",
            current_phase=7,
            proposal_batch=batch,
            author_results={
                "prop-A": _canned_author_result("prop-A"),
                "prop-B": _canned_author_result("prop-B"),
            },
        )
        paused_state.save(repo)

        reviewed_ids: List[str] = []

        def mock_review(b):
            for p in b["proposals"]:
                reviewed_ids.append(p["proposal_id"])
            return {p["proposal_id"]: "accepted" for p in b["proposals"]}

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=mock_review,
            resume_run_id="run-paused2",
        )
        loop.run()

        assert set(reviewed_ids) == {"prop-A", "prop-B"}

    def test_human_pause_saves_state_for_resume(self, repo, sessions):
        """When the human explicitly pauses at Phase 7 (some proposals left
        pending), the run state is saved so a future resume is possible."""
        batch = _canned_proposal_batch(proposal_ids=["prop-1", "prop-2"])

        def mock_review(b):
            # Accept one, leave the other pending (via explicit pause)
            return {
                "prop-1": "accepted",
                "prop-2": "pending",
            }

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: batch,
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=mock_review,
        )
        state = loop.run()

        # Run should be paused (not complete) because there are pending proposals
        assert state.status == "paused"
        assert "prop-2" in state.pending_proposals

        # The state should be loadable for resume
        loaded = RunState.load(repo, state.run_id)
        assert loaded.current_phase == 7
        assert "prop-2" in loaded.pending_proposals


# ===========================================================================
# 4. Partial pre-Phase-7 run is discarded on next invocation
#    (v1 crash recovery)
# ===========================================================================


class TestV1CrashRecovery:
    """v1 crash recovery: partial runs that crashed before Phase 7 are
    discarded on next invocation. Only Phase-7 paused runs are resumable."""

    def test_partial_phase_4_run_discarded(self, repo, sessions):
        """A run that crashed during Phase 4 (evaluation) is discarded on
        next invocation — it is not resumed."""
        crashed_state = RunState(
            run_id="run-crashed-eval",
            status="crashed",
            current_phase=4,
        )
        crashed_state.save(repo)

        evaluator_calls = []

        def mock_evaluator(*a, **kw):
            evaluator_calls.append(1)
            return _canned_evaluator_output()

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=mock_evaluator,
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        state = loop.run()

        # A fresh evaluation should have been invoked (not resumed)
        assert len(evaluator_calls) == 1
        # The new run should have a different run_id
        assert state.run_id != "run-crashed-eval"
        assert state.status == "complete"

    def test_partial_phase_5_run_discarded(self, repo, sessions):
        """A run that crashed during Phase 5 (proposer or author) is
        discarded and a fresh run starts."""
        crashed_state = RunState(
            run_id="run-crashed-prop",
            status="crashed",
            current_phase=5,
        )
        crashed_state.save(repo)

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        state = loop.run()

        assert state.run_id != "run-crashed-prop"
        assert state.status == "complete"

    def test_phase_7_paused_run_is_not_discarded(self, repo, sessions):
        """A Phase-7 paused run is NOT discarded — it is resumable."""
        batch = _canned_proposal_batch(
            run_id="run-phase7",
            proposal_ids=["prop-saved"],
        )
        for p in batch["proposals"]:
            p["what"]["diff_reference"] = "abc123"
            p["what"]["files_touched"] = ["CLAUDE.md"]

        paused_state = RunState(
            run_id="run-phase7",
            status="paused",
            current_phase=7,
            proposal_batch=batch,
            author_results={
                "prop-saved": _canned_author_result("prop-saved"),
            },
        )
        paused_state.save(repo)

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
            resume_run_id="run-phase7",
        )
        state = loop.run()

        # Should have resumed (not started fresh)
        assert state.run_id == "run-phase7"
        assert state.status == "complete"

    def test_resume_non_phase7_run_raises(self, repo, sessions):
        """Attempting to resume a run that is not paused at Phase 7 raises
        an error, because v1 only supports resume from Phase 7."""
        crashed_state = RunState(
            run_id="run-crashed-3",
            status="crashed",
            current_phase=3,
        )
        crashed_state.save(repo)

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
            resume_run_id="run-crashed-3",
        )

        with pytest.raises(RunLoopError, match="[Rr]esume.*[Pp]hase 7"):
            loop.run()

    def test_crashed_state_marked_as_discarded(self, repo, sessions):
        """After a fresh run discards a crashed pre-Phase-7 state, the
        crashed state file is marked as discarded (not deleted —
        append-only principle)."""
        crashed_state = RunState(
            run_id="run-discard-me",
            status="crashed",
            current_phase=4,
        )
        crashed_state.save(repo)

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: _canned_proposal_batch(),
            author_fn=lambda i, *a, **kw: _canned_author_result(i["proposal_id"]),
            human_review_fn=lambda batch: {
                p["proposal_id"]: "accepted" for p in batch["proposals"]
            },
        )
        loop.run()

        # The crashed state should still exist on disk but be marked discarded
        old_state = RunState.load(repo, "run-discard-me")
        assert old_state.status == "discarded"


# ===========================================================================
# Additional plumbing tests
# ===========================================================================


class TestAuthorFailedHandling:
    """Author-failed proposals are handled correctly in the plumbing."""

    def test_author_failed_produces_decision_not_merge(self, repo, sessions):
        """A proposal where the author fails still produces a decision
        record (with status author_failed) but does not merge any branch."""
        batch = _canned_proposal_batch(proposal_ids=["prop-fail"])

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: batch,
            author_fn=lambda i, *a, **kw: _canned_author_result(
                i["proposal_id"], success=False
            ),
            human_review_fn=lambda b: {
                p["proposal_id"]: "accepted" for p in b["proposals"]
            },
        )
        state = loop.run()

        # The decision should exist and have status author_failed
        assert len(state.decisions) == 1
        assert state.decisions[0]["status"] == "author_failed"


class TestEmptyBatch:
    """Proposer producing an empty batch."""

    def test_empty_batch_skips_authoring_and_review(self, repo, sessions):
        """If the proposer produces zero proposals, Phase 5b and 7 are
        effectively no-ops and the run completes with an empty batch."""
        empty_batch = {
            "batch_id": "batch-empty",
            "run_id": "run-empty",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "window": {"start": "2026-04-20", "end": "2026-04-27"},
            "proposal_ids": [],
            "batch_narrative": "No proposals this run.",
            "contains_forced_novelty": False,
            "proposals": [],
        }

        author_calls = []
        review_calls = []

        loop = RunLoop(
            repo=repo,
            date_range={"start": "2026-04-20", "end": "2026-04-27"},
            sessions=sessions,
            evaluator_fn=lambda *a, **kw: _canned_evaluator_output(),
            proposer_fn=lambda *a, **kw: empty_batch,
            author_fn=lambda i, *a, **kw: author_calls.append(1),
            human_review_fn=lambda b: review_calls.append(1) or {},
        )
        state = loop.run()

        assert len(author_calls) == 0
        assert state.status == "complete"
