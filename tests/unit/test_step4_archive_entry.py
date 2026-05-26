"""
Step 4 gate — Archive entry read/write (HARD gate): Unit tests.

Spec ref: docs/spec/01-data-structures/archive-entry.md

Gate criteria (from docs/PLAN.md Step 4):
  1. Roundtrip: write an archive entry, read it back, assert equality.
  2. "Exactly one active configuration" invariant holds at all times,
     including under concurrent supersession.
  3. Lifecycle transitions follow the spec's allowed paths
     (active → superseded).

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_reflect.storage.archive_entry import (
    ArchiveEntryError,
    create_archive_entry,
    read_archive_entry,
    supersede_archive_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry_kwargs(**overrides):
    """Return a minimal valid set of kwargs for create_archive_entry."""
    base = dict(
        entry_id="entry-001",
        git_reference="abc123def456",
        produced_by_decision="decision-001",
        produced_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        region_markers={
            "sessions_measured": [],
            "qualitative_position": None,
            "observed_gap_frequencies": {},
        },
        structural_fingerprint={
            "skill_count": 0,
            "hook_count": 0,
            "agent_count": 0,
            "claude_md_length": 100,
        },
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Gate criterion 1 — Roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip:
    """Write an archive entry, read it back, assert equality."""

    def test_roundtrip_basic(self, tmp_path):
        kwargs = _make_entry_kwargs()
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)

        assert entry["entry_id"] == "entry-001"
        assert entry["git_reference"] == "abc123def456"
        assert entry["produced_by_decision"] == "decision-001"
        assert entry["superseded_by"] is None
        assert entry["active_at"]["end"] is None

    def test_roundtrip_preserves_region_markers(self, tmp_path):
        kwargs = _make_entry_kwargs(
            region_markers={
                "sessions_measured": ["session-aaa", "session-bbb"],
                "qualitative_position": None,
                "observed_gap_frequencies": {"gap-1": 3, "gap-2": 1},
            }
        )
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)

        rm = entry["region_markers"]
        assert rm["sessions_measured"] == ["session-aaa", "session-bbb"]
        assert rm["observed_gap_frequencies"] == {"gap-1": 3, "gap-2": 1}

    def test_roundtrip_preserves_structural_fingerprint(self, tmp_path):
        fp = {"skill_count": 3, "hook_count": 1, "agent_count": 2, "claude_md_length": 500}
        kwargs = _make_entry_kwargs(structural_fingerprint=fp)
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)

        assert entry["structural_fingerprint"] == fp

    def test_roundtrip_produced_at_preserved(self, tmp_path):
        ts = datetime(2024, 6, 15, 9, 30, 0, tzinfo=timezone.utc)
        kwargs = _make_entry_kwargs(produced_at=ts)
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)

        # produced_at must survive the round trip (string or datetime, but same value)
        stored = entry["produced_at"]
        if isinstance(stored, str):
            stored = datetime.fromisoformat(stored)
        assert stored == ts

    def test_roundtrip_active_at_start_equals_produced_at(self, tmp_path):
        ts = datetime(2024, 6, 15, 9, 30, 0, tzinfo=timezone.utc)
        kwargs = _make_entry_kwargs(produced_at=ts)
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)

        start = entry["active_at"]["start"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        assert start == ts

    def test_file_written_as_json(self, tmp_path):
        kwargs = _make_entry_kwargs()
        create_archive_entry(base_dir=tmp_path, **kwargs)
        archive_dir = tmp_path / ".claude-reflect" / "archive"
        json_path = archive_dir / "entry-001.json"
        assert json_path.exists()
        # Must be valid JSON
        with json_path.open() as f:
            data = json.load(f)
        assert data["entry_id"] == "entry-001"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """Malformed entries are rejected at create time."""

    def test_missing_entry_id_rejected(self, tmp_path):
        kwargs = _make_entry_kwargs()
        del kwargs["entry_id"]
        with pytest.raises((ArchiveEntryError, TypeError, KeyError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)

    def test_missing_git_reference_rejected(self, tmp_path):
        kwargs = _make_entry_kwargs()
        del kwargs["git_reference"]
        with pytest.raises((ArchiveEntryError, TypeError, KeyError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)

    def test_missing_produced_by_decision_rejected(self, tmp_path):
        kwargs = _make_entry_kwargs()
        del kwargs["produced_by_decision"]
        with pytest.raises((ArchiveEntryError, TypeError, KeyError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)

    def test_missing_produced_at_rejected(self, tmp_path):
        kwargs = _make_entry_kwargs()
        del kwargs["produced_at"]
        with pytest.raises((ArchiveEntryError, TypeError, KeyError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)

    def test_missing_structural_fingerprint_rejected(self, tmp_path):
        kwargs = _make_entry_kwargs()
        del kwargs["structural_fingerprint"]
        with pytest.raises((ArchiveEntryError, TypeError, KeyError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)

    def test_structural_fingerprint_missing_skill_count_rejected(self, tmp_path):
        fp = {"hook_count": 0, "agent_count": 0, "claude_md_length": 100}
        kwargs = _make_entry_kwargs(structural_fingerprint=fp)
        with pytest.raises((ArchiveEntryError, KeyError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)

    def test_no_scalar_quality_score_field(self, tmp_path):
        """No quality_score or effort_score field must appear in stored entry."""
        kwargs = _make_entry_kwargs()
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        for forbidden in ("quality_score", "effort_score", "score", "priority"):
            assert forbidden not in entry, f"Forbidden scalar field found: {forbidden}"

    def test_no_best_flag(self, tmp_path):
        """No 'best' or 'champion' flag must appear in stored entry."""
        kwargs = _make_entry_kwargs()
        create_archive_entry(base_dir=tmp_path, **kwargs)
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        for forbidden in ("best", "champion", "is_best"):
            assert forbidden not in entry, f"Forbidden flag found: {forbidden}"

    def test_duplicate_entry_id_rejected(self, tmp_path):
        """Writing a second entry with the same ID must fail."""
        kwargs = _make_entry_kwargs()
        create_archive_entry(base_dir=tmp_path, **kwargs)
        with pytest.raises((ArchiveEntryError, FileExistsError, ValueError)):
            create_archive_entry(base_dir=tmp_path, **kwargs)


# ---------------------------------------------------------------------------
# Gate criterion 2 — Exactly one active configuration
# ---------------------------------------------------------------------------

class TestExactlyOneActive:
    """The 'exactly one active configuration' invariant holds at all times."""

    def test_first_entry_is_active(self, tmp_path):
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        assert entry["superseded_by"] is None
        assert entry["active_at"]["end"] is None

    def test_superseded_entry_is_no_longer_active(self, tmp_path):
        # Create first entry
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        # Supersede the first before creating the second (invariant: exactly one active)
        ts2 = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        supersede_archive_entry(
            entry_id="entry-001",
            superseded_by_decision="decision-002",
            end_time=ts2,
            base_dir=tmp_path,
        )
        # Now create second entry
        create_archive_entry(
            base_dir=tmp_path,
            **_make_entry_kwargs(
                entry_id="entry-002",
                produced_by_decision="decision-002",
                produced_at=ts2,
            ),
        )
        old = read_archive_entry("entry-001", base_dir=tmp_path)
        assert old["superseded_by"] == "decision-002"
        assert old["active_at"]["end"] is not None

        new = read_archive_entry("entry-002", base_dir=tmp_path)
        assert new["superseded_by"] is None
        assert new["active_at"]["end"] is None

    def test_cannot_have_two_active_entries_simultaneously(self, tmp_path):
        """Creating a second active entry without superseding the first must fail."""
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        ts2 = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Second create without superseding first should raise — invariant violation
        with pytest.raises((ArchiveEntryError, ValueError)):
            create_archive_entry(
                base_dir=tmp_path,
                **_make_entry_kwargs(
                    entry_id="entry-002",
                    produced_by_decision="decision-002",
                    produced_at=ts2,
                ),
            )

    def test_supersede_then_create_maintains_invariant(self, tmp_path):
        """After supersession, exactly one entry remains active."""
        ts1 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        create_archive_entry(
            base_dir=tmp_path,
            **_make_entry_kwargs(entry_id="entry-001", produced_at=ts1),
        )
        supersede_archive_entry(
            entry_id="entry-001",
            superseded_by_decision="decision-002",
            end_time=ts2,
            base_dir=tmp_path,
        )
        create_archive_entry(
            base_dir=tmp_path,
            **_make_entry_kwargs(
                entry_id="entry-002",
                produced_by_decision="decision-002",
                produced_at=ts2,
            ),
        )
        e1 = read_archive_entry("entry-001", base_dir=tmp_path)
        e2 = read_archive_entry("entry-002", base_dir=tmp_path)
        # Exactly one is active
        active_entries = [
            e for e in [e1, e2] if e["active_at"]["end"] is None
        ]
        assert len(active_entries) == 1
        assert active_entries[0]["entry_id"] == "entry-002"

    def test_chain_of_supersessions(self, tmp_path):
        """A chain of three entries leaves exactly one active at the end."""
        ts1 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts3 = datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

        create_archive_entry(
            base_dir=tmp_path,
            **_make_entry_kwargs(entry_id="entry-001", produced_at=ts1),
        )
        supersede_archive_entry(
            "entry-001", superseded_by_decision="decision-002", end_time=ts2, base_dir=tmp_path
        )
        create_archive_entry(
            base_dir=tmp_path,
            **_make_entry_kwargs(
                entry_id="entry-002",
                produced_by_decision="decision-002",
                produced_at=ts2,
            ),
        )
        supersede_archive_entry(
            "entry-002", superseded_by_decision="decision-003", end_time=ts3, base_dir=tmp_path
        )
        create_archive_entry(
            base_dir=tmp_path,
            **_make_entry_kwargs(
                entry_id="entry-003",
                produced_by_decision="decision-003",
                produced_at=ts3,
            ),
        )

        entries = [
            read_archive_entry(eid, base_dir=tmp_path)
            for eid in ["entry-001", "entry-002", "entry-003"]
        ]
        active = [e for e in entries if e["active_at"]["end"] is None]
        assert len(active) == 1
        assert active[0]["entry_id"] == "entry-003"


# ---------------------------------------------------------------------------
# Gate criterion 3 — Lifecycle transitions (active → superseded only)
# ---------------------------------------------------------------------------

class TestLifecycleTransitions:
    """Lifecycle transitions follow the spec's allowed paths (active → superseded)."""

    def test_new_entry_starts_active(self, tmp_path):
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        assert entry["superseded_by"] is None
        assert entry["active_at"]["end"] is None

    def test_supersede_populates_superseded_by(self, tmp_path):
        ts = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        supersede_archive_entry(
            "entry-001",
            superseded_by_decision="decision-002",
            end_time=ts,
            base_dir=tmp_path,
        )
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        assert entry["superseded_by"] == "decision-002"

    def test_supersede_populates_active_at_end(self, tmp_path):
        ts = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        supersede_archive_entry(
            "entry-001",
            superseded_by_decision="decision-002",
            end_time=ts,
            base_dir=tmp_path,
        )
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        end = entry["active_at"]["end"]
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        assert end == ts

    def test_cannot_supersede_already_superseded_entry(self, tmp_path):
        ts = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        supersede_archive_entry(
            "entry-001",
            superseded_by_decision="decision-002",
            end_time=ts,
            base_dir=tmp_path,
        )
        with pytest.raises((ArchiveEntryError, ValueError)):
            supersede_archive_entry(
                "entry-001",
                superseded_by_decision="decision-003",
                end_time=ts,
                base_dir=tmp_path,
            )

    def test_supersede_nonexistent_entry_raises(self, tmp_path):
        ts = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        with pytest.raises((ArchiveEntryError, FileNotFoundError, KeyError)):
            supersede_archive_entry(
                "does-not-exist",
                superseded_by_decision="decision-002",
                end_time=ts,
                base_dir=tmp_path,
            )

    def test_entries_are_never_deleted(self, tmp_path):
        """After supersession the file still exists on disk."""
        ts = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        supersede_archive_entry(
            "entry-001",
            superseded_by_decision="decision-002",
            end_time=ts,
            base_dir=tmp_path,
        )
        archive_dir = tmp_path / ".claude-reflect" / "archive"
        assert (archive_dir / "entry-001.json").exists()

    def test_qualitative_position_null_by_default(self, tmp_path):
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        entry = read_archive_entry("entry-001", base_dir=tmp_path)
        assert entry["region_markers"]["qualitative_position"] is None

    def test_qualitative_position_immutable_once_set(self, tmp_path):
        """
        Once qualitative_position is written (non-null), it cannot be
        changed by a subsequent update.
        """
        from claude_reflect.storage.archive_entry import set_qualitative_position

        ts = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        supersede_archive_entry(
            "entry-001",
            superseded_by_decision="decision-002",
            end_time=ts,
            base_dir=tmp_path,
        )
        set_qualitative_position("entry-001", "First description.", base_dir=tmp_path)
        # Attempting to set it again must raise
        with pytest.raises((ArchiveEntryError, ValueError)):
            set_qualitative_position("entry-001", "Second description.", base_dir=tmp_path)

    def test_qualitative_position_only_settable_after_active_at_end(self, tmp_path):
        """Cannot write qualitative_position while entry is still active."""
        from claude_reflect.storage.archive_entry import set_qualitative_position

        create_archive_entry(base_dir=tmp_path, **_make_entry_kwargs())
        with pytest.raises((ArchiveEntryError, ValueError)):
            set_qualitative_position("entry-001", "Some prose.", base_dir=tmp_path)
