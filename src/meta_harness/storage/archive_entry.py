"""
Archive entry read/write.

Spec: docs/spec/01-data-structures/archive-entry.md

One JSON file per entry under .meta-harness/archive/<entry_id>.json.
Enforces:
  - Exactly one active configuration at all times.
  - append-only: entries are never deleted.
  - active → superseded lifecycle; no reverse.
  - qualitative_position is null until active_at.end is set, then immutable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ArchiveEntryError(Exception):
    """Raised when an archive entry operation violates a spec invariant."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("entry_id", "git_reference", "produced_by_decision", "produced_at")
_REQUIRED_FINGERPRINT_FIELDS = ("skill_count", "hook_count", "agent_count", "claude_md_length")
_FORBIDDEN_FIELDS = ("quality_score", "effort_score", "score", "priority", "best", "champion", "is_best")


def _archive_dir(base_dir: Path) -> Path:
    d = base_dir / ".meta-harness" / "archive"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entry_path(entry_id: str, base_dir: Path) -> Path:
    return _archive_dir(base_dir) / f"{entry_id}.json"


def _serialise(obj: Any) -> Any:
    """Recursively serialise datetime objects to ISO strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialise(v) for v in obj]
    return obj


def _write_entry(entry: dict, base_dir: Path) -> None:
    path = _entry_path(entry["entry_id"], base_dir)
    serialised = _serialise(entry)
    path.write_text(json.dumps(serialised, indent=2, sort_keys=True), encoding="utf-8")


def _read_raw(entry_id: str, base_dir: Path) -> dict:
    path = _entry_path(entry_id, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Archive entry not found: {entry_id}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _active_entry_ids(base_dir: Path) -> list[str]:
    """Return IDs of all entries whose active_at.end is None."""
    archive_dir = base_dir / ".meta-harness" / "archive"
    if not archive_dir.exists():
        return []
    active = []
    for p in archive_dir.glob("*.json"):
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        if data.get("active_at", {}).get("end") is None:
            active.append(data["entry_id"])
    return active


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_archive_entry(
    *,
    base_dir: Path,
    entry_id: str,
    git_reference: str,
    produced_by_decision: str,
    produced_at: datetime,
    region_markers: dict,
    structural_fingerprint: dict,
) -> None:
    """Write a new archive entry to disk.

    Raises ArchiveEntryError if:
      - A required field is missing or invalid.
      - An entry with the same ID already exists.
      - Another active entry already exists (invariant: exactly one active).
    """
    # Validate required scalar fields
    for field_name, value in [
        ("entry_id", entry_id),
        ("git_reference", git_reference),
        ("produced_by_decision", produced_by_decision),
        ("produced_at", produced_at),
        ("region_markers", region_markers),
        ("structural_fingerprint", structural_fingerprint),
    ]:
        if value is None:
            raise ArchiveEntryError(f"Required field missing: {field_name}")

    # Validate structural_fingerprint has all required sub-fields
    for sub in _REQUIRED_FINGERPRINT_FIELDS:
        if sub not in structural_fingerprint:
            raise ArchiveEntryError(
                f"structural_fingerprint missing required field: {sub}"
            )

    # Reject duplicate entry_id
    path = _entry_path(entry_id, base_dir)
    if path.exists():
        raise ArchiveEntryError(
            f"Archive entry already exists: {entry_id}"
        )

    # Enforce exactly-one-active invariant
    active = _active_entry_ids(base_dir)
    if active:
        raise ArchiveEntryError(
            f"Cannot create a new active entry while entry {active[0]!r} is already active. "
            "Supersede it first."
        )

    entry = {
        "entry_id": entry_id,
        "git_reference": git_reference,
        "produced_by_decision": produced_by_decision,
        "produced_at": produced_at,
        "superseded_by": None,
        "active_at": {
            "start": produced_at,
            "end": None,
        },
        "region_markers": {
            "sessions_measured": region_markers.get("sessions_measured", []),
            "qualitative_position": region_markers.get("qualitative_position", None),
            "observed_gap_frequencies": region_markers.get("observed_gap_frequencies", {}),
        },
        "structural_fingerprint": dict(structural_fingerprint),
    }

    _write_entry(entry, base_dir)


def read_archive_entry(entry_id: str, *, base_dir: Path) -> dict:
    """Read and return an archive entry dict from disk."""
    return _read_raw(entry_id, base_dir)


def supersede_archive_entry(
    entry_id: str,
    *,
    superseded_by_decision: str,
    end_time: datetime,
    base_dir: Path,
) -> None:
    """Mark an entry as superseded.

    Populates superseded_by and active_at.end. The file is updated in-place
    (entry is never deleted).

    Raises ArchiveEntryError if:
      - Entry does not exist.
      - Entry is already superseded.
    """
    entry = _read_raw(entry_id, base_dir)

    if entry["superseded_by"] is not None:
        raise ArchiveEntryError(
            f"Entry {entry_id!r} is already superseded by "
            f"{entry['superseded_by']!r}; cannot supersede again."
        )

    entry["superseded_by"] = superseded_by_decision
    entry["active_at"]["end"] = end_time

    _write_entry(entry, base_dir)


def set_qualitative_position(
    entry_id: str,
    position: str,
    /,
    *,
    base_dir: Path,
) -> None:
    """Write qualitative_position prose onto a superseded entry.

    Rules from the spec:
      - May only be set after active_at.end is populated.
      - Immutable once set (cannot be overwritten).

    Raises ArchiveEntryError on any violation.
    """
    entry = _read_raw(entry_id, base_dir)

    if entry["active_at"]["end"] is None:
        raise ArchiveEntryError(
            f"Cannot set qualitative_position on entry {entry_id!r} while it is still active."
        )

    existing = entry["region_markers"].get("qualitative_position")
    if existing is not None:
        raise ArchiveEntryError(
            f"qualitative_position is already set on entry {entry_id!r} and is immutable."
        )

    entry["region_markers"]["qualitative_position"] = position
    _write_entry(entry, base_dir)
