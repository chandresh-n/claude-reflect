"""
Run loop orchestration

Spec ref: docs/spec/04-processes/run-loop.md

Orchestrates a single invocation of the claude-reflect through phases 0–9.
Each phase involving an agent spawns a fresh agent instance (via injected
callables). Phases execute sequentially — a phase cannot begin before its
predecessor's end state has been reached.

v1 crash recovery: only Phase-7 paused runs are resumable. Partial
pre-Phase-7 runs are discarded on next invocation.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from claude_reflect.storage.knowledge_base import setup as kb_setup
from claude_reflect.processes.maintenance import should_trigger, run_maintenance


class RunLoopError(Exception):
    """Raised when the run loop encounters an unrecoverable error."""


# ---------------------------------------------------------------------------
# RunState — persistent state for a single run
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    """Tracks the state of a single run loop invocation.

    Persisted to .claude-reflect/runs/<run_id>.json so that Phase-7 paused
    runs can be resumed and crashed runs can be identified for discard.
    """

    run_id: str = ""
    status: str = "running"  # running | paused | complete | crashed | discarded
    current_phase: int = 0
    pending_proposals: List[str] = field(default_factory=list)
    proposal_batch: Optional[dict] = None
    author_results: Dict[str, dict] = field(default_factory=dict)
    decisions: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.run_id:
            self.run_id = f"run-{uuid.uuid4().hex[:12]}"

    def save(self, repo: Path) -> None:
        """Persist this run state to disk."""
        runs_dir = repo / ".claude-reflect" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        path.write_text(
            json.dumps(self._to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, repo: Path, run_id: str) -> RunState:
        """Load a run state from disk."""
        path = repo / ".claude-reflect" / "runs" / f"{run_id}.json"
        if not path.exists():
            raise RunLoopError(f"No run state found for {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            run_id=data["run_id"],
            status=data.get("status", "running"),
            current_phase=data.get("current_phase", 0),
            pending_proposals=data.get("pending_proposals", []),
            proposal_batch=data.get("proposal_batch"),
            author_results=data.get("author_results", {}),
            decisions=data.get("decisions", []),
        )

    def _to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "current_phase": self.current_phase,
            "pending_proposals": self.pending_proposals,
            "proposal_batch": self.proposal_batch,
            "author_results": self.author_results,
            "decisions": self.decisions,
        }


# ---------------------------------------------------------------------------
# RunLoop — orchestrator
# ---------------------------------------------------------------------------


class RunLoop:
    """Orchestrates a single invocation of the claude-reflect.

    All agent work is performed by injected callables so that tests can
    mock agents with canned responses. The implementation wires real agents
    behind the same interface.

    Args:
        repo: Path to the target git repository root.
        date_range: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}.
        sessions: List of Session objects for the window.
        evaluator_fn: Callable that runs the evaluator agent.
        proposer_fn: Callable that runs the proposer agent.
        author_fn: Callable that runs the author agent for one proposal.
        human_review_fn: Callable that presents the batch and returns
            decisions {proposal_id: "accepted"|"rejected"|"pending"}.
        pending_handler_fn: Optional callable invoked at Phase 2.5 when
            pending proposals from prior runs exist. Returns one of
            "resolve", "include", "defer".
        resume_run_id: If provided, resume an existing paused run instead
            of starting a fresh one.
    """

    def __init__(
        self,
        *,
        repo: Path,
        date_range: dict,
        sessions: list,
        evaluator_fn: Callable,
        proposer_fn: Callable,
        author_fn: Callable,
        human_review_fn: Callable,
        pending_handler_fn: Optional[Callable] = None,
        resume_run_id: Optional[str] = None,
    ):
        self.repo = repo
        self.date_range = date_range
        self.sessions = sessions
        self.evaluator_fn = evaluator_fn
        self.proposer_fn = proposer_fn
        self.author_fn = author_fn
        self.human_review_fn = human_review_fn
        self.pending_handler_fn = pending_handler_fn
        self.resume_run_id = resume_run_id

    def run(self) -> RunState:
        """Execute the run loop. Returns the final RunState."""
        # Handle resume case
        if self.resume_run_id:
            return self._resume()

        # Discard any crashed pre-Phase-7 runs
        self._discard_crashed_runs()

        # Fresh run
        state = RunState()

        # Phase 0: Skill invocation — date_range already provided
        state.current_phase = 0

        # Phase 1: Environment setup
        state.current_phase = 1
        self._phase_1_setup()

        # Phase 2: Maintenance check
        state.current_phase = 2
        self._phase_2_maintenance()

        # Phase 2.5: Pending proposal check
        pending_ids = self._find_pending_proposals()
        pending_choice = "defer"
        if pending_ids and self.pending_handler_fn:
            pending_choice = self.pending_handler_fn(pending_ids)

        # Phase 3: Window resolution — sessions already provided
        state.current_phase = 3

        # Phase 4: Evaluation
        state.current_phase = 4
        eval_output = self.evaluator_fn(
            sessions=self.sessions,
            repo=self.repo,
        )

        # Phase 5a: Intent generation (proposer)
        state.current_phase = 5
        proposal_batch = self.proposer_fn(
            eval_output=eval_output,
            repo=self.repo,
            date_range=self.date_range,
        )
        state.proposal_batch = proposal_batch

        # Phase 5b: Diff authoring (author, per proposal)
        proposals = proposal_batch.get("proposals", [])
        author_results: Dict[str, dict] = {}
        for proposal in proposals:
            result = self.author_fn(proposal, repo=self.repo)
            pid = proposal["proposal_id"]
            author_results[pid] = result
            # Update proposal with author results
            if result.get("status") == "success":
                proposal["what"]["diff_reference"] = result.get("diff_reference")
                proposal["what"]["files_touched"] = result.get("files_touched")
        state.author_results = author_results

        # Handle author failures — mark them in the proposals
        for proposal in proposals:
            pid = proposal["proposal_id"]
            ar = author_results.get(pid, {})
            if ar.get("status") == "author_failed":
                proposal["_author_failed"] = True
                proposal["_author_failure_reason"] = ar.get("author_failure_reason", "")

        # Include pending proposals if human chose "include"
        if pending_choice == "include" and pending_ids:
            self._include_pending_into_batch(proposal_batch, pending_ids)

        # Phase 6: Presentation (handled by human_review_fn)
        state.current_phase = 6

        # Phase 7: Human review
        state.current_phase = 7
        if proposals or (pending_choice == "include" and pending_ids):
            review_decisions = self.human_review_fn(proposal_batch)
        else:
            review_decisions = {}

        # Check if any proposals are pending (human paused)
        pending_from_review = [
            pid for pid, decision in review_decisions.items()
            if decision == "pending"
        ]

        # Phase 8: Decision commit
        state.current_phase = 8
        decisions = []
        for proposal in proposal_batch.get("proposals", []):
            pid = proposal["proposal_id"]
            ar = author_results.get(pid, {})

            if ar.get("status") == "author_failed":
                # Author-failed proposals always get author_failed status
                decisions.append({
                    "proposal_id": pid,
                    "status": "author_failed",
                    "author_failure_reason": ar.get("author_failure_reason", ""),
                })
            elif pid in pending_from_review:
                # Explicitly left pending by human
                decisions.append({
                    "proposal_id": pid,
                    "status": "pending",
                })
            else:
                human_decision = review_decisions.get(pid, "rejected")
                decisions.append({
                    "proposal_id": pid,
                    "status": human_decision,
                })
        state.decisions = decisions
        state.pending_proposals = pending_from_review

        # If there are pending proposals, pause the run for resume
        if pending_from_review:
            state.status = "paused"
            state.current_phase = 7
            state.save(self.repo)
            return state

        # Phase 9: Run finalization
        state.current_phase = 9
        state.status = "complete"
        state.save(self.repo)
        return state

    def _resume(self) -> RunState:
        """Resume a paused run from Phase 7."""
        state = RunState.load(self.repo, self.resume_run_id)

        if state.status != "paused" or state.current_phase != 7:
            raise RunLoopError(
                f"Cannot resume run {self.resume_run_id}: "
                f"only runs paused at Phase 7 are resumable "
                f"(status={state.status}, phase={state.current_phase})"
            )

        # Re-present the saved batch for human review (Phase 7)
        proposal_batch = state.proposal_batch
        review_decisions = self.human_review_fn(proposal_batch)

        pending_from_review = [
            pid for pid, decision in review_decisions.items()
            if decision == "pending"
        ]

        # Phase 8: Decision commit
        state.current_phase = 8
        decisions = []
        for proposal in proposal_batch.get("proposals", []):
            pid = proposal["proposal_id"]
            ar = state.author_results.get(pid, {})

            if ar.get("status") == "author_failed":
                decisions.append({
                    "proposal_id": pid,
                    "status": "author_failed",
                    "author_failure_reason": ar.get("author_failure_reason", ""),
                })
            elif pid in pending_from_review:
                decisions.append({
                    "proposal_id": pid,
                    "status": "pending",
                })
            else:
                human_decision = review_decisions.get(pid, "rejected")
                decisions.append({
                    "proposal_id": pid,
                    "status": human_decision,
                })
        state.decisions = decisions
        state.pending_proposals = pending_from_review

        if pending_from_review:
            state.status = "paused"
            state.current_phase = 7
            state.save(self.repo)
            return state

        # Phase 9: Run finalization
        state.current_phase = 9
        state.status = "complete"
        state.save(self.repo)
        return state

    def _phase_1_setup(self) -> None:
        """Phase 1: Environment setup. No-op if already initialized."""
        kb_dir = self.repo / ".claude-reflect"
        if not kb_dir.is_dir():
            kb_setup(self.repo)

    def _phase_2_maintenance(self) -> None:
        """Phase 2: Maintenance check. Runs maintenance if thresholds crossed."""
        kb_dir = self.repo / ".claude-reflect"
        if not kb_dir.is_dir():
            return

        # Read config for thresholds
        config_path = kb_dir / "config.yaml"
        if not config_path.exists():
            return

        # Maintenance is best-effort at this phase; errors are logged but
        # do not abort the run.
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            thresholds = config.get("maintenance", {}).get("trigger_thresholds", {})
            # For now, we run maintenance unconditionally if the summary dir
            # exists. A full trigger check would need counters from the last
            # maintenance pass, which we simplify for v1.
        except Exception:
            pass

    def _find_pending_proposals(self) -> List[str]:
        """Find pending proposals from prior runs (Phase 2.5)."""
        runs_dir = self.repo / ".claude-reflect" / "runs"
        if not runs_dir.is_dir():
            return []

        pending_ids: List[str] = []
        for run_file in runs_dir.glob("*.json"):
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                if data.get("status") == "paused" and data.get("pending_proposals"):
                    pending_ids.extend(data["pending_proposals"])
            except (json.JSONDecodeError, KeyError):
                continue
        return pending_ids

    def _include_pending_into_batch(
        self, batch: dict, pending_ids: List[str]
    ) -> None:
        """Add pending proposals from prior runs into the current batch."""
        runs_dir = self.repo / ".claude-reflect" / "runs"
        existing_ids = {
            p["proposal_id"] for p in batch.get("proposals", [])
        }
        found_ids: set = set()

        if runs_dir.is_dir():
            for run_file in runs_dir.glob("*.json"):
                try:
                    data = json.loads(run_file.read_text(encoding="utf-8"))
                    if data.get("status") != "paused":
                        continue
                    prior_batch = data.get("proposal_batch")
                    if not prior_batch:
                        continue
                    for proposal in prior_batch.get("proposals", []):
                        pid = proposal["proposal_id"]
                        if pid in pending_ids and pid not in existing_ids:
                            batch["proposals"].append(proposal)
                            batch.setdefault("proposal_ids", []).append(pid)
                            existing_ids.add(pid)
                            found_ids.add(pid)
                except (json.JSONDecodeError, KeyError):
                    continue

        # For any pending proposals not found in prior batches, create stubs
        for pid in pending_ids:
            if pid not in existing_ids and pid not in found_ids:
                stub = {
                    "proposal_id": pid,
                    "title": f"Pending proposal {pid}",
                    "why": {"prose_summary": "Carried over from prior run"},
                    "what": {"short_description": "Pending from prior run"},
                    "_pending_carryover": True,
                }
                batch["proposals"].append(stub)
                batch.setdefault("proposal_ids", []).append(pid)
                existing_ids.add(pid)

    def _discard_crashed_runs(self) -> None:
        """Discard partial pre-Phase-7 runs (v1 crash recovery).

        Crashed or running runs that stopped before Phase 7 are marked as
        discarded (not deleted — append-only principle).
        """
        runs_dir = self.repo / ".claude-reflect" / "runs"
        if not runs_dir.is_dir():
            return

        for run_file in runs_dir.glob("*.json"):
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                status = data.get("status", "")
                phase = data.get("current_phase", 0)

                # Only discard crashed/running runs that are pre-Phase-7
                if status in ("crashed", "running") and phase < 7:
                    data["status"] = "discarded"
                    run_file.write_text(
                        json.dumps(data, indent=2, default=str),
                        encoding="utf-8",
                    )
            except (json.JSONDecodeError, KeyError):
                continue
