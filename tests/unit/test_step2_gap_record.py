"""
Step 2 gate — Gap record read/write (HARD gate): Unit tests.

Spec ref: docs/spec/01-data-structures/gap-record.md

Gate criteria (from docs/PLAN.md Step 2):
  1. Roundtrip: write a gap record to disk, read it back, assert equality.
  2. Schema validation rejects malformed records (missing required fields,
     wrong field types, invalid enum values).
  3. Append-only enforcement: deleting a gap record is impossible through
     the public API.
  4. Immutable field enforcement: fields the spec marks immutable cannot
     be overwritten after first write.
  5. Kind-vocabulary handling matches the spec.

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import json
from pathlib import Path

import pytest

from meta_harness.storage.gap_record import (
    create_gap_record,
    read_gap_record,
    update_gap_record,
)
from meta_harness.storage.knowledge_base import setup


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_EVIDENCE_POINTER = {
    "session_id": "sess-abc-001",
    "turn_range": {"start": 0, "end": 3},
    "magnitude": {
        "additional_turns": 2,
        "additional_tokens": 150,
        "human_correction_required": True,
    },
}

VALID_GAP_RECORD = {
    "characterization": "The model repeatedly enters tool-call loops without recovery.",
    "kind": "tool-call-loop",
    "first_observed_at": "2024-01-15T10:00:00+00:00",
    "last_observed_at": "2024-01-15T10:00:00+00:00",
    "occurrence_count": 1,
    "evidence": [VALID_EVIDENCE_POINTER],
    "status": "open",
    "related_proposals": [],
}


@pytest.fixture
def kb_repo(tmp_git_repo: Path) -> Path:
    """Temporary git repo with the knowledge base already initialized."""
    setup(tmp_git_repo)
    return tmp_git_repo


# ---------------------------------------------------------------------------
# Criterion 1: Roundtrip — write then read produces identical record
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_create_and_read_back_equals_original(self, kb_repo):
        """Write a valid gap record, read it back, assert field equality."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        read_back = read_gap_record(kb_repo, gap_id)
        for key in VALID_GAP_RECORD:
            assert read_back[key] == created[key], (
                f"Field '{key}' did not survive roundtrip"
            )

    def test_gap_record_file_exists_on_disk(self, kb_repo):
        """Backing JSON file must be at .meta-harness/gaps/<gap_id>.json."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        expected_path = kb_repo / ".meta-harness" / "gaps" / f"{gap_id}.json"
        assert expected_path.is_file(), (
            f"Gap record file not found at {expected_path}"
        )

    def test_gap_record_on_disk_is_valid_json(self, kb_repo):
        """The backing file must be valid JSON."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        path = kb_repo / ".meta-harness" / "gaps" / f"{gap_id}.json"
        with open(path) as f:
            on_disk = json.load(f)
        assert isinstance(on_disk, dict)

    def test_identifier_is_assigned_on_create(self, kb_repo):
        """create_gap_record must assign a stable, non-empty identifier."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        assert "identifier" in created
        assert isinstance(created["identifier"], str)
        assert created["identifier"]

    def test_two_records_get_distinct_identifiers(self, kb_repo):
        """Two separate gap records must have distinct identifiers."""
        r1 = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        r2_data = VALID_GAP_RECORD.copy()
        r2_data["characterization"] = "A different inefficiency pattern."
        r2 = create_gap_record(kb_repo, r2_data)
        assert r1["identifier"] != r2["identifier"]

    def test_occurrence_count_equals_evidence_length(self, kb_repo):
        """Invariant: occurrence_count == len(evidence)."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        assert created["occurrence_count"] == len(created["evidence"])

    def test_identifier_in_record_matches_filename(self, kb_repo):
        """The identifier in the returned record must match the on-disk filename."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        path = kb_repo / ".meta-harness" / "gaps" / f"{gap_id}.json"
        with open(path) as f:
            on_disk = json.load(f)
        assert on_disk["identifier"] == gap_id

    def test_evidence_pointer_fields_survive_roundtrip(self, kb_repo):
        """Evidence pointer sub-fields (session_id, turn_range, magnitude) survive roundtrip."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        read_back = read_gap_record(kb_repo, gap_id)
        ev = read_back["evidence"][0]
        assert ev["session_id"] == VALID_EVIDENCE_POINTER["session_id"]
        assert ev["turn_range"] == VALID_EVIDENCE_POINTER["turn_range"]
        assert ev["magnitude"] == VALID_EVIDENCE_POINTER["magnitude"]


# ---------------------------------------------------------------------------
# Criterion 2: Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """create_gap_record rejects malformed records at write time."""

    @pytest.mark.parametrize("missing_field", [
        "characterization",
        "kind",
        "first_observed_at",
        "last_observed_at",
        "occurrence_count",
        "evidence",
        "status",
        "related_proposals",
    ])
    def test_create_rejects_missing_required_field(self, kb_repo, missing_field):
        """Schema validation must raise when a required field is missing."""
        bad = VALID_GAP_RECORD.copy()
        del bad[missing_field]
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_invalid_status_value(self, kb_repo):
        """Status must be one of the spec-defined enum values."""
        bad = VALID_GAP_RECORD.copy()
        bad["status"] = "invalid_status_not_in_spec"
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    @pytest.mark.parametrize("valid_status", [
        "open", "partially_addressed", "addressed", "stale"
    ])
    def test_create_accepts_all_valid_status_values(self, kb_repo, valid_status):
        """Every status value in the spec's enum must be accepted."""
        record = VALID_GAP_RECORD.copy()
        record["status"] = valid_status
        created = create_gap_record(kb_repo, record)
        assert created["status"] == valid_status

    def test_create_rejects_empty_kind(self, kb_repo):
        """kind must be a non-empty string; empty string is rejected."""
        bad = VALID_GAP_RECORD.copy()
        bad["kind"] = ""
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_kind_as_non_string(self, kb_repo):
        """kind must be a string type."""
        bad = VALID_GAP_RECORD.copy()
        bad["kind"] = 42
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_occurrence_count_mismatch(self, kb_repo):
        """occurrence_count must equal len(evidence); mismatch is rejected."""
        bad = VALID_GAP_RECORD.copy()
        bad["occurrence_count"] = 99  # evidence has length 1
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_evidence_as_non_list(self, kb_repo):
        """evidence must be a list."""
        bad = VALID_GAP_RECORD.copy()
        bad["evidence"] = "not-a-list"
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_related_proposals_as_non_list(self, kb_repo):
        """related_proposals must be a list."""
        bad = VALID_GAP_RECORD.copy()
        bad["related_proposals"] = "not-a-list"
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_empty_characterization(self, kb_repo):
        """characterization must be a non-empty string."""
        bad = VALID_GAP_RECORD.copy()
        bad["characterization"] = ""
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_characterization_as_non_string(self, kb_repo):
        """characterization must be a string."""
        bad = VALID_GAP_RECORD.copy()
        bad["characterization"] = 123
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_read_nonexistent_gap_id_raises(self, kb_repo):
        """Reading a gap_id that does not exist must raise."""
        with pytest.raises(Exception):
            read_gap_record(kb_repo, "gap-id-that-does-not-exist")

    def test_create_rejects_evidence_pointer_missing_session_id(self, kb_repo):
        """Each evidence pointer must have session_id."""
        bad_ev = {
            "turn_range": {"start": 0, "end": 1},
            "magnitude": {"additional_turns": 1, "additional_tokens": 10,
                          "human_correction_required": False},
        }
        bad = VALID_GAP_RECORD.copy()
        bad["evidence"] = [bad_ev]
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_evidence_pointer_missing_turn_range(self, kb_repo):
        """Each evidence pointer must have turn_range."""
        bad_ev = {
            "session_id": "sess-001",
            "magnitude": {"additional_turns": 1, "additional_tokens": 10,
                          "human_correction_required": False},
        }
        bad = VALID_GAP_RECORD.copy()
        bad["evidence"] = [bad_ev]
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)

    def test_create_rejects_evidence_pointer_missing_magnitude(self, kb_repo):
        """Each evidence pointer must have magnitude."""
        bad_ev = {
            "session_id": "sess-001",
            "turn_range": {"start": 0, "end": 1},
        }
        bad = VALID_GAP_RECORD.copy()
        bad["evidence"] = [bad_ev]
        with pytest.raises(Exception):
            create_gap_record(kb_repo, bad)


# ---------------------------------------------------------------------------
# Criterion 3: Append-only enforcement — delete is impossible
# ---------------------------------------------------------------------------

class TestAppendOnly:
    """Gap records are never deleted through the public API."""

    def test_no_delete_function_in_public_api(self):
        """The gap_record module must not export any delete or remove function."""
        import meta_harness.storage.gap_record as module
        api_names = [name for name in dir(module) if not name.startswith("_")]
        forbidden = [
            name for name in api_names
            if "delete" in name.lower() or "remove" in name.lower()
        ]
        assert not forbidden, (
            f"Delete/remove function(s) found in public API: {forbidden}. "
            "Gap records are append-only; no delete may be exposed."
        )

    def test_gap_record_file_persists_after_update(self, kb_repo):
        """Updating a record must not remove or replace the backing file."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        original_path = kb_repo / ".meta-harness" / "gaps" / f"{gap_id}.json"
        update_gap_record(kb_repo, gap_id, {"characterization": "Refined description."})
        assert original_path.is_file()

    def test_all_earlier_records_remain_after_multiple_creates(self, kb_repo):
        """Creating new records must not overwrite or remove older ones."""
        ids = []
        for i in range(3):
            data = VALID_GAP_RECORD.copy()
            data["characterization"] = f"Pattern {i} — distinct inefficiency."
            created = create_gap_record(kb_repo, data)
            ids.append(created["identifier"])

        for gap_id in ids:
            record = read_gap_record(kb_repo, gap_id)
            assert record["identifier"] == gap_id

    def test_gap_record_count_grows_monotonically(self, kb_repo):
        """Each create adds exactly one new file under .meta-harness/gaps/."""
        gaps_dir = kb_repo / ".meta-harness" / "gaps"

        before = len(list(gaps_dir.glob("*.json")))
        data = VALID_GAP_RECORD.copy()
        data["characterization"] = "An additional pattern."
        create_gap_record(kb_repo, data)
        after = len(list(gaps_dir.glob("*.json")))

        assert after == before + 1


# ---------------------------------------------------------------------------
# Criterion 4: Immutable field enforcement
# ---------------------------------------------------------------------------

class TestImmutableFields:
    """
    Immutable fields per spec: identifier, first_observed_at.
    Attempting to overwrite them via update_gap_record must raise.
    """

    def test_cannot_overwrite_identifier(self, kb_repo):
        """identifier is immutable post-write; update attempt must raise."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        with pytest.raises(Exception):
            update_gap_record(kb_repo, gap_id, {"identifier": "new-id-attempt"})

    def test_cannot_overwrite_first_observed_at(self, kb_repo):
        """first_observed_at is immutable post-write; update attempt must raise."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        with pytest.raises(Exception):
            update_gap_record(kb_repo, gap_id, {
                "first_observed_at": "2030-01-01T00:00:00+00:00"
            })

    def test_can_update_characterization(self, kb_repo):
        """characterization is mutable (may be refined on subsequent observations)."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        new_char = "Refined: model enters loops especially in file-edit tasks."
        updated = update_gap_record(kb_repo, gap_id, {"characterization": new_char})
        assert updated["characterization"] == new_char

    def test_can_update_kind(self, kb_repo):
        """kind is mutable (maintenance may reconcile near-duplicate labels)."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        updated = update_gap_record(kb_repo, gap_id, {"kind": "tool-call-loop-reconciled"})
        assert updated["kind"] == "tool-call-loop-reconciled"

    def test_can_update_status(self, kb_repo):
        """status is mutable (transitions per the spec's state diagram)."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        updated = update_gap_record(kb_repo, gap_id, {"status": "stale"})
        assert updated["status"] == "stale"

    def test_update_preserves_immutable_fields(self, kb_repo):
        """After a mutable-field update, identifier and first_observed_at stay unchanged."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        original_first_observed = created["first_observed_at"]

        update_gap_record(kb_repo, gap_id, {"characterization": "Updated description."})

        read_back = read_gap_record(kb_repo, gap_id)
        assert read_back["identifier"] == gap_id
        assert read_back["first_observed_at"] == original_first_observed

    def test_update_to_invalid_status_raises(self, kb_repo):
        """update_gap_record must also validate enum fields on update."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        with pytest.raises(Exception):
            update_gap_record(kb_repo, gap_id, {"status": "not-a-valid-status"})

    def test_updated_record_persists_to_disk(self, kb_repo):
        """update_gap_record must write the change back to disk."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        new_char = "Persisted update."
        update_gap_record(kb_repo, gap_id, {"characterization": new_char})
        read_back = read_gap_record(kb_repo, gap_id)
        assert read_back["characterization"] == new_char


# ---------------------------------------------------------------------------
# Criterion 5: Kind-vocabulary handling
# ---------------------------------------------------------------------------

class TestKindVocabulary:
    """
    Spec: kind is a free-form, non-empty string assigned by the evaluator.
    Maintenance may reconcile near-duplicate kinds.
    kind must always be populated.
    """

    def test_kind_is_preserved_on_roundtrip(self, kb_repo):
        """The kind label must survive a write-read roundtrip exactly."""
        record = VALID_GAP_RECORD.copy()
        record["kind"] = "wasted-model-effort"
        created = create_gap_record(kb_repo, record)
        read_back = read_gap_record(kb_repo, created["identifier"])
        assert read_back["kind"] == "wasted-model-effort"

    def test_kind_accepts_hyphenated_labels(self, kb_repo):
        """kind accepts multi-word hyphenated labels (common evaluator pattern)."""
        record = VALID_GAP_RECORD.copy()
        record["kind"] = "correction-required"
        created = create_gap_record(kb_repo, record)
        assert created["kind"] == "correction-required"

    def test_kind_accepts_arbitrary_non_empty_string(self, kb_repo):
        """kind is free-form; any non-empty string must be accepted."""
        record = VALID_GAP_RECORD.copy()
        record["kind"] = "novel-kind-not-previously-seen-in-vocabulary"
        created = create_gap_record(kb_repo, record)
        assert created["kind"] == "novel-kind-not-previously-seen-in-vocabulary"

    def test_update_changes_kind_successfully(self, kb_repo):
        """Maintenance may change kind to a reconciled label via update_gap_record."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        update_gap_record(kb_repo, gap_id, {"kind": "tool-call-loop"})
        read_back = read_gap_record(kb_repo, gap_id)
        assert read_back["kind"] == "tool-call-loop"

    def test_update_rejects_empty_kind(self, kb_repo):
        """Updating kind to empty string is invalid (kind must always be populated)."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        with pytest.raises(Exception):
            update_gap_record(kb_repo, gap_id, {"kind": ""})

    def test_update_rejects_none_kind(self, kb_repo):
        """Updating kind to None is invalid."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        gap_id = created["identifier"]
        with pytest.raises(Exception):
            update_gap_record(kb_repo, gap_id, {"kind": None})

    def test_gap_records_with_different_kinds_coexist(self, kb_repo):
        """Multiple gap records with different kind labels can coexist in the KB."""
        kinds = ["tool-call-loop", "wasted-model-effort", "correction-required"]
        ids = []
        for kind in kinds:
            data = VALID_GAP_RECORD.copy()
            data["kind"] = kind
            data["characterization"] = f"Pattern of kind: {kind}"
            created = create_gap_record(kb_repo, data)
            ids.append((created["identifier"], kind))

        for gap_id, expected_kind in ids:
            read_back = read_gap_record(kb_repo, gap_id)
            assert read_back["kind"] == expected_kind


# ---------------------------------------------------------------------------
# Cross-cutting caution: no scalar grades in gap records
# ---------------------------------------------------------------------------

class TestNoScalarGrades:
    """
    Cross-cutting caution: no scalar grades anywhere.
    Spec (gap-record.md § 'Explicitly excluded'):
      No severity score, no confidence value.
    Spec (IMPLEMENTATION.md § 'Implementation cautions'):
      No quality scores, effort scores, priority numbers.
    """

    FORBIDDEN_GRADE_KEYS = frozenset({
        "score", "grade", "priority", "severity", "confidence",
        "rank", "quality", "effort",
    })

    def test_gap_record_has_no_scalar_grade_fields(self, kb_repo):
        """The record returned by create must contain no scalar grade keys."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        for key in self.FORBIDDEN_GRADE_KEYS:
            assert key not in created, (
                f"Scalar grade field '{key}' found in gap record. "
                "Spec explicitly excludes severity/confidence/priority scores."
            )

    def test_read_back_has_no_scalar_grade_fields(self, kb_repo):
        """The record returned by read must also contain no scalar grade keys."""
        created = create_gap_record(kb_repo, VALID_GAP_RECORD.copy())
        read_back = read_gap_record(kb_repo, created["identifier"])
        for key in self.FORBIDDEN_GRADE_KEYS:
            assert key not in read_back, (
                f"Scalar grade field '{key}' found in read-back gap record."
            )
