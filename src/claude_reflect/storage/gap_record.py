"""
Gap record read/write — Step 2 of the claude-reflect build.

Spec ref: docs/spec/01-data-structures/gap-record.md

Public API (three functions, no delete):
- create_gap_record(repo, data) -> dict
- read_gap_record(repo, gap_id) -> dict
- update_gap_record(repo, gap_id, updates) -> dict

Design constraints:
- Append-only: no delete or remove function is exposed.
- Immutable fields: identifier and first_observed_at cannot be overwritten.
- Schema validation on both create and update.
- No scalar grades anywhere (no score, priority, severity, etc.).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = frozenset({"open", "partially_addressed", "addressed", "stale"})

REQUIRED_FIELDS = frozenset({
    "characterization",
    "kind",
    "first_observed_at",
    "last_observed_at",
    "occurrence_count",
    "evidence",
    "status",
    "related_proposals",
})

# Fields that are immutable once written
IMMUTABLE_FIELDS = frozenset({"identifier", "first_observed_at"})

# Fields the spec explicitly forbids (no scalar grades)
FORBIDDEN_GRADE_KEYS = frozenset({
    "score", "grade", "priority", "severity", "confidence",
    "rank", "quality", "effort",
})

REQUIRED_EVIDENCE_FIELDS = frozenset({"session_id", "turn_range", "magnitude"})


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

class GapRecordError(ValueError):
    """Raised when a gap record fails schema validation or invariant checks."""


def _validate_evidence_pointer(pointer: Any) -> None:
    """Validate a single evidence pointer dict."""
    if not isinstance(pointer, dict):
        raise GapRecordError(
            f"Each evidence pointer must be a dict; got {type(pointer)!r}"
        )
    for field in REQUIRED_EVIDENCE_FIELDS:
        if field not in pointer:
            raise GapRecordError(
                f"Evidence pointer missing required field '{field}'"
            )


def _validate_record(data: dict) -> None:
    """
    Validate a gap record dict against the spec schema.
    Raises GapRecordError on any violation.
    """
    # Required fields present
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise GapRecordError(f"Missing required field '{field}'")

    # characterization: non-empty string
    char = data["characterization"]
    if not isinstance(char, str):
        raise GapRecordError(
            f"'characterization' must be a string; got {type(char)!r}"
        )
    if not char:
        raise GapRecordError("'characterization' must not be empty")

    # kind: non-empty string
    kind = data["kind"]
    if not isinstance(kind, str):
        raise GapRecordError(
            f"'kind' must be a string; got {type(kind)!r}"
        )
    if not kind:
        raise GapRecordError("'kind' must not be empty")

    # status: enum
    status = data["status"]
    if status not in VALID_STATUSES:
        raise GapRecordError(
            f"Invalid status '{status}'; must be one of {sorted(VALID_STATUSES)}"
        )

    # evidence: list of valid pointers
    evidence = data["evidence"]
    if not isinstance(evidence, list):
        raise GapRecordError(
            f"'evidence' must be a list; got {type(evidence)!r}"
        )
    for pointer in evidence:
        _validate_evidence_pointer(pointer)

    # related_proposals: list
    rp = data["related_proposals"]
    if not isinstance(rp, list):
        raise GapRecordError(
            f"'related_proposals' must be a list; got {type(rp)!r}"
        )

    # occurrence_count must equal len(evidence)
    count = data["occurrence_count"]
    if count != len(evidence):
        raise GapRecordError(
            f"'occurrence_count' ({count}) must equal len(evidence) ({len(evidence)})"
        )

    # No scalar grade fields
    for key in FORBIDDEN_GRADE_KEYS:
        if key in data:
            raise GapRecordError(
                f"Scalar grade field '{key}' is forbidden in gap records"
            )


def _gaps_dir(repo: Path) -> Path:
    return repo / ".claude-reflect" / "gaps"


def _record_path(repo: Path, gap_id: str) -> Path:
    return _gaps_dir(repo) / f"{gap_id}.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_gap_record(repo: Path, data: dict) -> dict:
    """
    Validate *data* against the spec schema, assign a unique identifier,
    persist to .claude-reflect/gaps/<gap_id>.json, and return the full record.

    Args:
        repo: Root of the target git repository.
        data: Gap record fields (without 'identifier'; it is assigned here).

    Returns:
        The persisted gap record dict, including the assigned 'identifier'.

    Raises:
        GapRecordError: If schema validation fails.
    """
    _validate_record(data)

    gap_id = str(uuid.uuid4())
    record: dict = {"identifier": gap_id, **data}

    gaps_dir = _gaps_dir(repo)
    gaps_dir.mkdir(parents=True, exist_ok=True)

    path = _record_path(repo, gap_id)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    return record


def read_gap_record(repo: Path, gap_id: str) -> dict:
    """
    Read and return the gap record identified by *gap_id*.

    Args:
        repo: Root of the target git repository.
        gap_id: The stable identifier of the gap record.

    Returns:
        The gap record dict as stored on disk.

    Raises:
        FileNotFoundError: If no record with *gap_id* exists.
    """
    path = _record_path(repo, gap_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"Gap record '{gap_id}' not found at {path}"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def update_gap_record(repo: Path, gap_id: str, updates: dict) -> dict:
    """
    Apply *updates* to the mutable fields of an existing gap record and
    persist the result.

    Immutable fields (identifier, first_observed_at) cannot be updated.
    Enum fields (status, kind) are validated on update.

    Args:
        repo: Root of the target git repository.
        gap_id: The stable identifier of the gap record to update.
        updates: Dict of field → new_value pairs to apply.

    Returns:
        The updated gap record dict.

    Raises:
        GapRecordError: If an immutable field is targeted, or if validation fails.
        FileNotFoundError: If the record does not exist.
    """
    # Check for immutable field violations before reading from disk
    for field in IMMUTABLE_FIELDS:
        if field in updates:
            raise GapRecordError(
                f"Field '{field}' is immutable and cannot be updated post-write"
            )

    record = read_gap_record(repo, gap_id)
    record.update(updates)

    # Re-validate the updated record (excluding 'identifier' from REQUIRED_FIELDS,
    # since identifier is set and not in the original required set).
    # We validate the full record after update to catch invalid enum values etc.
    _validate_updated_record(record)

    path = _record_path(repo, gap_id)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    return record


def _validate_updated_record(record: dict) -> None:
    """
    Validate a full record (with identifier already set) after an update.
    Applies the same schema rules as _validate_record but skips the
    required-fields check for fields that are always present post-create.
    """
    # status enum
    if "status" in record:
        status = record["status"]
        if status not in VALID_STATUSES:
            raise GapRecordError(
                f"Invalid status '{status}'; must be one of {sorted(VALID_STATUSES)}"
            )

    # kind: non-empty string
    if "kind" in record:
        kind = record["kind"]
        if kind is None or not isinstance(kind, str):
            raise GapRecordError(
                f"'kind' must be a non-None string; got {kind!r}"
            )
        if not kind:
            raise GapRecordError("'kind' must not be empty")

    # characterization: non-empty string
    if "characterization" in record:
        char = record["characterization"]
        if not isinstance(char, str) or not char:
            raise GapRecordError(
                "'characterization' must be a non-empty string"
            )

    # No scalar grade fields
    for key in FORBIDDEN_GRADE_KEYS:
        if key in record:
            raise GapRecordError(
                f"Scalar grade field '{key}' is forbidden in gap records"
            )
