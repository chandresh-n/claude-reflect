"""
Step 7 gate — Maintenance process (HARD gate): Unit tests.

Spec ref: docs/spec/04-processes/maintenance.md

Gate criteria (from docs/PLAN.md Step 7):
  1. Integration test: run maintenance, snapshot state, run again,
     assert byte-identical state (idempotent). [in integration tests]
  2. Each threshold trigger tested independently: new_sessions,
     new_decisions, new_gap_records, days_since_last.
  3. Stale-gap transition logic tested with a fixture.
  4. Kind-vocabulary reconciliation tested.

All tests must FAIL before implementation exists (Session A gate criterion).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from claude_reflect.processes.maintenance import (
    should_trigger,
    transition_stale_gaps,
    reconcile_kind_vocabulary,
    MaintenanceLog,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gap_record(
    repo: Path,
    gap_id: str,
    kind: str = "tool-call-loop",
    status: str = "open",
    last_observed_at: str = "2026-04-01T00:00:00Z",
) -> dict:
    """Write a minimal gap record to disk and return it."""
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
    gaps_dir = repo / ".claude-reflect" / "gaps"
    gaps_dir.mkdir(parents=True, exist_ok=True)
    path = gaps_dir / f"{gap_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _write_maintenance_log(repo: Path, log_entry: dict) -> None:
    """Write a maintenance log entry."""
    log_path = repo / ".claude-reflect" / "maintenance.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Append JSONL format
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")


# ---------------------------------------------------------------------------
# Gate criterion 2: Threshold triggers tested independently
# ---------------------------------------------------------------------------

class TestShouldTrigger:
    """Each threshold trigger fires correctly in isolation."""

    def test_new_sessions_above_threshold_triggers(self, tmp_path: Path) -> None:
        """Maintenance triggers when new_sessions exceeds threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=11,
            new_decisions=0,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is True

    def test_new_sessions_at_threshold_triggers(self, tmp_path: Path) -> None:
        """Maintenance triggers when new_sessions equals threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=10,
            new_decisions=0,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is True

    def test_new_sessions_below_threshold_no_trigger(self, tmp_path: Path) -> None:
        """Maintenance does not trigger when new_sessions below threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=9,
            new_decisions=0,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is False

    def test_new_decisions_above_threshold_triggers(self, tmp_path: Path) -> None:
        """Maintenance triggers when new_decisions exceeds threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=6,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is True

    def test_new_decisions_below_threshold_no_trigger(self, tmp_path: Path) -> None:
        """Maintenance does not trigger when new_decisions below threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=4,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is False

    def test_new_gap_records_above_threshold_triggers(self, tmp_path: Path) -> None:
        """Maintenance triggers when new_gap_records exceeds threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=0,
            new_gap_records=4,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is True

    def test_new_gap_records_below_threshold_no_trigger(self, tmp_path: Path) -> None:
        """Maintenance does not trigger when new_gap_records below threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=0,
            new_gap_records=2,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is False

    def test_days_since_last_above_threshold_triggers(self, tmp_path: Path) -> None:
        """Maintenance triggers when days_since_last exceeds threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=0,
            new_gap_records=0,
            days_since_last=8,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is True

    def test_days_since_last_below_threshold_no_trigger(self, tmp_path: Path) -> None:
        """Maintenance does not trigger when days_since_last below threshold."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=0,
            new_gap_records=0,
            days_since_last=6,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is False

    def test_all_below_threshold_no_trigger(self, tmp_path: Path) -> None:
        """No trigger when all metrics are below their thresholds."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=0,
            new_decisions=0,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is False

    def test_multiple_above_threshold_triggers(self, tmp_path: Path) -> None:
        """Triggers when multiple thresholds exceeded (OR semantics)."""
        result = should_trigger(
            repo=tmp_path,
            new_sessions=15,
            new_decisions=10,
            new_gap_records=0,
            days_since_last=0,
            thresholds={"new_sessions": 10, "new_decisions": 5, "new_gap_records": 3, "days_since_last": 7},
        )
        assert result is True


# ---------------------------------------------------------------------------
# Gate criterion 3: Stale-gap transition logic
# ---------------------------------------------------------------------------

class TestStaleGapTransition:
    """Stale-gap transition logic with fixtures."""

    def test_open_gap_becomes_stale_after_threshold(self, tmp_path: Path) -> None:
        """An open gap whose last_observed_at is older than threshold becomes stale."""
        # Gap last observed 35 sessions ago, threshold is 30
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _make_gap_record(tmp_path, "gap-old", status="open", last_observed_at=old_date)

        transition_stale_gaps(
            repo=tmp_path,
            stale_threshold_sessions=30,
            current_session_count=65,  # 65 - 30 = session 35; gap at session ~5
        )

        # Read back the gap record
        gap_path = tmp_path / ".claude-reflect" / "gaps" / "gap-old.json"
        updated = json.loads(gap_path.read_text(encoding="utf-8"))
        assert updated["status"] == "stale"

    def test_open_gap_within_threshold_stays_open(self, tmp_path: Path) -> None:
        """An open gap whose last_observed_at is within threshold stays open."""
        recent_date = datetime.now(timezone.utc).isoformat()
        _make_gap_record(tmp_path, "gap-recent", status="open", last_observed_at=recent_date)

        transition_stale_gaps(
            repo=tmp_path,
            stale_threshold_sessions=30,
            current_session_count=10,
        )

        gap_path = tmp_path / ".claude-reflect" / "gaps" / "gap-recent.json"
        updated = json.loads(gap_path.read_text(encoding="utf-8"))
        assert updated["status"] == "open"

    def test_already_stale_gap_stays_stale(self, tmp_path: Path) -> None:
        """A gap already in 'stale' status is not changed."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _make_gap_record(tmp_path, "gap-stale", status="stale", last_observed_at=old_date)

        transition_stale_gaps(
            repo=tmp_path,
            stale_threshold_sessions=30,
            current_session_count=65,
        )

        gap_path = tmp_path / ".claude-reflect" / "gaps" / "gap-stale.json"
        updated = json.loads(gap_path.read_text(encoding="utf-8"))
        assert updated["status"] == "stale"

    def test_addressed_gap_not_transitioned(self, tmp_path: Path) -> None:
        """A gap in 'addressed' status should not be transitioned to stale."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _make_gap_record(tmp_path, "gap-addr", status="addressed", last_observed_at=old_date)

        transition_stale_gaps(
            repo=tmp_path,
            stale_threshold_sessions=30,
            current_session_count=65,
        )

        gap_path = tmp_path / ".claude-reflect" / "gaps" / "gap-addr.json"
        updated = json.loads(gap_path.read_text(encoding="utf-8"))
        assert updated["status"] == "addressed"

    def test_partially_addressed_gap_not_transitioned(self, tmp_path: Path) -> None:
        """A gap in 'partially_addressed' status should not be transitioned to stale."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        _make_gap_record(tmp_path, "gap-partial", status="partially_addressed", last_observed_at=old_date)

        transition_stale_gaps(
            repo=tmp_path,
            stale_threshold_sessions=30,
            current_session_count=65,
        )

        gap_path = tmp_path / ".claude-reflect" / "gaps" / "gap-partial.json"
        updated = json.loads(gap_path.read_text(encoding="utf-8"))
        assert updated["status"] == "partially_addressed"


# ---------------------------------------------------------------------------
# Gate criterion 4: Kind-vocabulary reconciliation
# ---------------------------------------------------------------------------

class TestKindVocabularyReconciliation:
    """Kind-vocabulary reconciliation logic."""

    def test_exact_duplicates_merged(self, tmp_path: Path) -> None:
        """Two gaps with the same kind are not merged (not duplicates in label)."""
        _make_gap_record(tmp_path, "gap-1", kind="tool-call-loop")
        _make_gap_record(tmp_path, "gap-2", kind="tool-call-loop")

        reconcile_kind_vocabulary(repo=tmp_path)

        # Both should remain unchanged — same kind is not a problem
        g1 = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-1.json").read_text())
        g2 = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-2.json").read_text())
        assert g1["kind"] == "tool-call-loop"
        assert g2["kind"] == "tool-call-loop"

    def test_near_duplicate_kinds_merged(self, tmp_path: Path) -> None:
        """Near-duplicate kinds (e.g. 'correction-required' and 'human-correction')
        are merged to a canonical label when confidence is high."""
        _make_gap_record(tmp_path, "gap-a", kind="correction-required")
        _make_gap_record(tmp_path, "gap-b", kind="human-correction")

        result = reconcile_kind_vocabulary(repo=tmp_path)

        # After reconciliation, both should have the same canonical label
        g_a = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-a.json").read_text())
        g_b = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-b.json").read_text())
        assert g_a["kind"] == g_b["kind"]
        # The result should indicate what was reconciled
        assert len(result.merged_kinds) > 0

    def test_dissimilar_kinds_not_merged(self, tmp_path: Path) -> None:
        """Kinds that are clearly different are left separate."""
        _make_gap_record(tmp_path, "gap-x", kind="tool-call-loop")
        _make_gap_record(tmp_path, "gap-y", kind="context-window-overflow")

        result = reconcile_kind_vocabulary(repo=tmp_path)

        g_x = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-x.json").read_text())
        g_y = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-y.json").read_text())
        assert g_x["kind"] == "tool-call-loop"
        assert g_y["kind"] == "context-window-overflow"
        assert len(result.merged_kinds) == 0

    def test_reconciliation_is_conservative(self, tmp_path: Path) -> None:
        """Edge cases are left unmerged — reconciliation requires high confidence."""
        # These kinds are somewhat similar but not clearly duplicates
        _make_gap_record(tmp_path, "gap-m", kind="file-read-retry")
        _make_gap_record(tmp_path, "gap-n", kind="tool-retry-pattern")

        result = reconcile_kind_vocabulary(repo=tmp_path)

        # Conservative: should NOT merge ambiguous cases
        g_m = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-m.json").read_text())
        g_n = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-n.json").read_text())
        assert g_m["kind"] == "file-read-retry"
        assert g_n["kind"] == "tool-retry-pattern"

    def test_reconciliation_updates_kind_field_only(self, tmp_path: Path) -> None:
        """Reconciliation only changes the 'kind' field; other fields are untouched."""
        original = _make_gap_record(tmp_path, "gap-r", kind="correction-required")

        reconcile_kind_vocabulary(repo=tmp_path)

        updated = json.loads((tmp_path / ".claude-reflect" / "gaps" / "gap-r.json").read_text())
        # All fields except 'kind' should be identical
        for key in original:
            if key == "kind":
                continue
            assert updated[key] == original[key], f"Field '{key}' was modified"


# ---------------------------------------------------------------------------
# MaintenanceLog
# ---------------------------------------------------------------------------

class TestMaintenanceLog:
    """Maintenance log is produced each pass."""

    def test_log_entry_written(self, tmp_path: Path) -> None:
        """A maintenance pass produces a log entry."""
        log = MaintenanceLog(repo=tmp_path)
        log.record(
            pages_created=2,
            pages_updated=1,
            pages_deprecated=0,
            kinds_reconciled=["correction-required -> human-correction"],
            gaps_transitioned=["gap-old"],
        )
        log_path = tmp_path / ".claude-reflect" / "maintenance.log"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "pages_created" in content

    def test_log_is_append_only(self, tmp_path: Path) -> None:
        """Multiple log entries accumulate; earlier entries are never removed."""
        log = MaintenanceLog(repo=tmp_path)
        log.record(pages_created=1, pages_updated=0, pages_deprecated=0,
                   kinds_reconciled=[], gaps_transitioned=[])
        log.record(pages_created=2, pages_updated=1, pages_deprecated=0,
                   kinds_reconciled=[], gaps_transitioned=[])

        log_path = tmp_path / ".claude-reflect" / "maintenance.log"
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
