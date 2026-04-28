"""
Step 7 gate — Maintenance process (HARD gate): Integration tests.

Spec ref: docs/spec/04-processes/maintenance.md

Gate criteria (from docs/PLAN.md Step 7):
  1. Integration test: run maintenance, snapshot state, run again,
     assert byte-identical state (idempotent).
  2. Each threshold trigger tested independently (covered in unit tests).
  3. Stale-gap transition logic tested with a fixture (covered in unit tests).
  4. Kind-vocabulary reconciliation tested (covered in unit tests).

This file focuses on criterion 1 (idempotence) and end-to-end integration.

All tests must FAIL before implementation exists (Session A gate criterion).
"""
from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml

from meta_harness.processes.maintenance import (
    run_maintenance,
    should_trigger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_kb(repo: Path) -> None:
    """Create a minimal .meta-harness structure for testing."""
    mh = repo / ".meta-harness"
    mh.mkdir(parents=True, exist_ok=True)
    (mh / "gaps").mkdir(exist_ok=True)
    (mh / "archive").mkdir(exist_ok=True)
    (mh / "summary").mkdir(exist_ok=True)
    # Write a minimal config
    config = {
        "models": {
            "evaluator": "claude-sonnet-4-6",
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
    (mh / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")


def _make_gap_record(repo: Path, gap_id: str, kind: str = "tool-call-loop",
                     status: str = "open",
                     last_observed_at: str = "2026-04-01T00:00:00Z") -> dict:
    """Write a minimal gap record fixture."""
    record = {
        "identifier": gap_id,
        "characterization": f"Test gap {gap_id}",
        "kind": kind,
        "first_observed_at": "2026-01-01T00:00:00Z",
        "last_observed_at": last_observed_at,
        "occurrence_count": 1,
        "evidence": [{"session_id": "s1", "turn_range": [1, 5], "magnitude": "medium"}],
        "status": status,
        "related_proposals": [],
    }
    gap_path = repo / ".meta-harness" / "gaps" / f"{gap_id}.json"
    gap_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    """Capture every file under root as path -> content bytes."""
    snapshot: dict[str, bytes] = {}
    for dirpath, _, filenames in os.walk(root):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            rel = str(fpath.relative_to(root))
            snapshot[rel] = fpath.read_bytes()
    return snapshot


def _hash_snapshot(snapshot: dict[str, bytes]) -> str:
    """Produce a deterministic hash of a file tree snapshot."""
    h = hashlib.sha256()
    for key in sorted(snapshot.keys()):
        h.update(key.encode())
        h.update(snapshot[key])
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Gate criterion 1: Idempotence
# ---------------------------------------------------------------------------

class TestMaintenanceIdempotence:
    """Run maintenance, snapshot state, run again, assert byte-identical."""

    def test_run_twice_produces_identical_state(self, tmp_path: Path) -> None:
        """Maintenance is idempotent: second run on same inputs is a no-op."""
        _init_kb(tmp_path)
        _make_gap_record(tmp_path, "gap-1", kind="tool-call-loop")
        _make_gap_record(tmp_path, "gap-2", kind="context-overflow")

        # First run
        run_maintenance(repo=tmp_path)
        snapshot_1 = _snapshot_tree(tmp_path / ".meta-harness")

        # Second run (no new content)
        run_maintenance(repo=tmp_path)
        snapshot_2 = _snapshot_tree(tmp_path / ".meta-harness")

        assert _hash_snapshot(snapshot_1) == _hash_snapshot(snapshot_2), (
            "Second maintenance run altered state — not idempotent"
        )

    def test_no_new_content_is_noop(self, tmp_path: Path) -> None:
        """When no new content has arrived, maintenance is a no-op
        (except potentially the maintenance log entry itself)."""
        _init_kb(tmp_path)

        # Run maintenance with nothing new
        run_maintenance(repo=tmp_path)
        snap_1 = _snapshot_tree(tmp_path / ".meta-harness")

        run_maintenance(repo=tmp_path)
        snap_2 = _snapshot_tree(tmp_path / ".meta-harness")

        assert _hash_snapshot(snap_1) == _hash_snapshot(snap_2)


# ---------------------------------------------------------------------------
# End-to-end: maintenance pass with content
# ---------------------------------------------------------------------------

class TestMaintenanceEndToEnd:
    """End-to-end maintenance pass exercises the full pipeline."""

    def test_maintenance_produces_log_entry(self, tmp_path: Path) -> None:
        """Every maintenance pass produces a log entry."""
        _init_kb(tmp_path)
        _make_gap_record(tmp_path, "gap-e2e")

        run_maintenance(repo=tmp_path)

        log_path = tmp_path / ".meta-harness" / "maintenance.log"
        assert log_path.exists(), "Maintenance log not created"
        content = log_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 0, "Maintenance log is empty"

    def test_maintenance_regenerates_index(self, tmp_path: Path) -> None:
        """Maintenance regenerates the summary layer index."""
        _init_kb(tmp_path)
        _make_gap_record(tmp_path, "gap-idx")

        run_maintenance(repo=tmp_path)

        index_path = tmp_path / ".meta-harness" / "summary" / "index.md"
        assert index_path.exists(), "Summary index not regenerated"

    def test_stale_gaps_transitioned_during_pass(self, tmp_path: Path) -> None:
        """During a full maintenance pass, stale gaps are transitioned."""
        _init_kb(tmp_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        _make_gap_record(tmp_path, "gap-stale-e2e", status="open",
                         last_observed_at=old_date)

        run_maintenance(repo=tmp_path)

        gap = json.loads(
            (tmp_path / ".meta-harness" / "gaps" / "gap-stale-e2e.json").read_text()
        )
        assert gap["status"] == "stale"

    def test_maintenance_writes_only_allowed_state(self, tmp_path: Path) -> None:
        """Maintenance writes only to summary layer, gap status, and gap kind.
        It does not modify other canonical state (per spec invariants)."""
        _init_kb(tmp_path)
        _make_gap_record(tmp_path, "gap-inv", kind="tool-call-loop")

        # Snapshot non-maintenance state before
        gap_before = json.loads(
            (tmp_path / ".meta-harness" / "gaps" / "gap-inv.json").read_text()
        )

        run_maintenance(repo=tmp_path)

        gap_after = json.loads(
            (tmp_path / ".meta-harness" / "gaps" / "gap-inv.json").read_text()
        )
        # characterization, first_observed_at, evidence etc. must be unchanged
        for field in ("identifier", "characterization", "first_observed_at",
                      "evidence", "related_proposals"):
            assert gap_after[field] == gap_before[field], (
                f"Maintenance modified '{field}' which it should not touch"
            )

    def test_maintenance_does_not_delete_files(self, tmp_path: Path) -> None:
        """Maintenance is non-destructive: deprecated pages are flagged, not deleted."""
        _init_kb(tmp_path)
        _make_gap_record(tmp_path, "gap-nd")

        # First run to create pages
        run_maintenance(repo=tmp_path)
        files_before = set()
        mh = tmp_path / ".meta-harness"
        for p in mh.rglob("*"):
            if p.is_file():
                files_before.add(str(p.relative_to(mh)))

        # Second run should not delete any files
        run_maintenance(repo=tmp_path)
        files_after = set()
        for p in mh.rglob("*"):
            if p.is_file():
                files_after.add(str(p.relative_to(mh)))

        deleted = files_before - files_after
        assert not deleted, f"Maintenance deleted files: {deleted}"
