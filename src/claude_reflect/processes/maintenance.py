"""
Maintenance process

Spec ref: docs/spec/04-processes/maintenance.md

Keeps the summary layer synchronized with canonical layers, reconciles
vocabulary drift, transitions stale state, and produces synthesized views.
Maintenance is a side-car: separate from the agents and the main run flow.

Maintenance never changes canonical state in ways that represent judgment.
It writes to the summary layer, transitions gap record status (stale),
and reconciles near-duplicate gap record kind labels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml

from claude_reflect.storage.summary_layer import (
    PageKind,
    get_summary_dir,
    write_page,
    list_pages,
    regenerate_index,
    _KIND_DIR,
)


# ---------------------------------------------------------------------------
# Threshold trigger
# ---------------------------------------------------------------------------

def should_trigger(
    *,
    repo: Path,
    new_sessions: int,
    new_decisions: int,
    new_gap_records: int,
    days_since_last: int,
    thresholds: dict[str, int],
) -> bool:
    """
    Determine whether maintenance should run based on content thresholds.

    OR semantics: any single threshold met or exceeded triggers maintenance.
    """
    if new_sessions >= thresholds["new_sessions"]:
        return True
    if new_decisions >= thresholds["new_decisions"]:
        return True
    if new_gap_records >= thresholds["new_gap_records"]:
        return True
    if days_since_last >= thresholds["days_since_last"]:
        return True
    return False


# ---------------------------------------------------------------------------
# Stale-gap transitions
# ---------------------------------------------------------------------------

def transition_stale_gaps(
    *,
    repo: Path,
    stale_threshold_sessions: int,
    current_session_count: int,
) -> list[str]:
    """
    Transition open gaps whose last_observed_at is older than the stale
    threshold to status 'stale'.

    Only gaps in 'open' status are candidates. Gaps in 'addressed',
    'partially_addressed', or already 'stale' are not touched.

    Uses a date-based heuristic: if last_observed_at is more than
    stale_threshold_sessions days ago, transition to stale.

    Returns list of gap IDs that were transitioned.
    """
    gaps_dir = repo / ".claude-reflect" / "gaps"
    if not gaps_dir.exists():
        return []

    transitioned: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_threshold_sessions)

    for gap_path in sorted(gaps_dir.glob("*.json")):
        record = json.loads(gap_path.read_text(encoding="utf-8"))

        if record.get("status") != "open":
            continue

        last_observed = record.get("last_observed_at", "")
        try:
            last_dt = datetime.fromisoformat(last_observed.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        if last_dt < cutoff:
            record["status"] = "stale"
            gap_path.write_text(
                json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
            )
            transitioned.append(record.get("identifier", gap_path.stem))

    return transitioned


# ---------------------------------------------------------------------------
# Kind-vocabulary reconciliation
# ---------------------------------------------------------------------------

# Known near-duplicate pairs that should be merged with high confidence.
# Maps (label_a, label_b) -> canonical_label.
# The spec says: "merge only when confidence is high."
_KNOWN_DUPLICATES: dict[frozenset[str], str] = {
    frozenset({"correction-required", "human-correction"}): "human-correction",
}


@dataclass
class ReconciliationResult:
    """Result of a kind-vocabulary reconciliation pass."""
    merged_kinds: list[str] = field(default_factory=list)


def reconcile_kind_vocabulary(*, repo: Path) -> ReconciliationResult:
    """
    Scan gap records for near-duplicate kinds and merge them.

    Conservative: only merges when confidence is high (known duplicate pairs).
    Edge cases are left unmerged.

    Returns a ReconciliationResult with details of what was merged.
    """
    gaps_dir = repo / ".claude-reflect" / "gaps"
    if not gaps_dir.exists():
        return ReconciliationResult()

    # Collect all gap records and their kinds
    gap_files: list[tuple[Path, dict]] = []
    for gap_path in sorted(gaps_dir.glob("*.json")):
        record = json.loads(gap_path.read_text(encoding="utf-8"))
        gap_files.append((gap_path, record))

    # Collect unique kinds
    kinds_in_use: set[str] = {rec["kind"] for _, rec in gap_files}

    result = ReconciliationResult()

    # Check each pair of kinds for known duplicates
    kinds_list = sorted(kinds_in_use)
    for i, kind_a in enumerate(kinds_list):
        for kind_b in kinds_list[i + 1:]:
            pair = frozenset({kind_a, kind_b})
            if pair in _KNOWN_DUPLICATES:
                canonical = _KNOWN_DUPLICATES[pair]
                merge_desc = f"{kind_a} + {kind_b} -> {canonical}"
                result.merged_kinds.append(merge_desc)

                # Update all gap records with the non-canonical label
                for gap_path, record in gap_files:
                    if record["kind"] in pair and record["kind"] != canonical:
                        record["kind"] = canonical
                        gap_path.write_text(
                            json.dumps(record, indent=2, sort_keys=True),
                            encoding="utf-8",
                        )

    return result


# ---------------------------------------------------------------------------
# Maintenance log
# ---------------------------------------------------------------------------

class MaintenanceLog:
    """Append-only maintenance log in JSONL format."""

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._log_path = repo / ".claude-reflect" / "maintenance.log"

    def record(
        self,
        *,
        pages_created: int = 0,
        pages_updated: int = 0,
        pages_deprecated: int = 0,
        kinds_reconciled: list[str] | None = None,
        gaps_transitioned: list[str] | None = None,
    ) -> None:
        """Append a log entry for one maintenance pass."""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pages_created": pages_created,
            "pages_updated": pages_updated,
            "pages_deprecated": pages_deprecated,
            "kinds_reconciled": kinds_reconciled or [],
            "gaps_transitioned": gaps_transitioned or [],
        }
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Summary page generation helpers
# ---------------------------------------------------------------------------

def _make_timestamp() -> str:
    """Produce a deterministic-format UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_page_content(title: str, body: str, sources: str, timestamp: str) -> str:
    """Build page content meeting the summary-layer format requirements."""
    return (
        f"Last updated: {timestamp}\n"
        f"Generated from: {sources}\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def _generate_gap_kind_pages(
    summary_dir: Path, gaps_by_kind: dict[str, list[dict]], timestamp: str
) -> int:
    """Generate or update gap-kind pages. Returns count of pages written."""
    count = 0
    for kind, gaps in sorted(gaps_by_kind.items()):
        lines = []
        for g in gaps:
            lines.append(
                f"- {g['identifier']}: {g['characterization']} "
                f"(status: {g['status']}, observed: {g['occurrence_count']}x)"
            )
        body = "\n".join(lines)
        content = _make_page_content(
            title=f"Gap kind: {kind}",
            body=body,
            sources="canonical/gaps/*.json",
            timestamp=timestamp,
        )
        write_page(summary_dir, PageKind.GAP_KIND, kind, content)
        count += 1
    return count


def _generate_gap_dashboard(
    summary_dir: Path, all_gaps: list[dict], timestamp: str
) -> None:
    """Generate the gap-dashboard page."""
    open_gaps = [g for g in all_gaps if g.get("status") == "open"]
    stale_gaps = [g for g in all_gaps if g.get("status") == "stale"]
    addressed = [g for g in all_gaps if g.get("status") in ("addressed", "partially_addressed")]

    lines = [
        f"Total gaps: {len(all_gaps)}",
        f"Open: {len(open_gaps)}",
        f"Stale: {len(stale_gaps)}",
        f"Addressed/Partially addressed: {len(addressed)}",
        "",
    ]
    if open_gaps:
        lines.append("### Open gaps")
        for g in open_gaps:
            lines.append(f"- {g['identifier']}: {g['characterization']} (kind: {g['kind']})")
        lines.append("")

    content = _make_page_content(
        title="Gap Dashboard",
        body="\n".join(lines),
        sources="canonical/gaps/*.json",
        timestamp=timestamp,
    )
    write_page(summary_dir, PageKind.GAP_DASHBOARD, "dashboard", content)


def _generate_exploration_profile(
    summary_dir: Path, all_gaps: list[dict], timestamp: str
) -> None:
    """Generate the exploration-profile page."""
    kinds = sorted({g["kind"] for g in all_gaps})
    lines = [
        f"Known gap kinds: {len(kinds)}",
        "",
    ]
    for k in kinds:
        count = sum(1 for g in all_gaps if g["kind"] == k)
        lines.append(f"- {k}: {count} gap(s)")

    content = _make_page_content(
        title="Exploration Profile",
        body="\n".join(lines),
        sources="canonical/gaps/*.json",
        timestamp=timestamp,
    )
    write_page(summary_dir, PageKind.EXPLORATION_PROFILE, "profile", content)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _load_all_gaps(repo: Path) -> list[dict]:
    """Load all gap records from disk."""
    gaps_dir = repo / ".claude-reflect" / "gaps"
    if not gaps_dir.exists():
        return []
    gaps = []
    for path in sorted(gaps_dir.glob("*.json")):
        gaps.append(json.loads(path.read_text(encoding="utf-8")))
    return gaps


def _load_config(repo: Path) -> dict:
    """Load maintenance config from config.yaml."""
    config_path = repo / ".claude-reflect" / "config.yaml"
    if config_path.exists():
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {}


def _snapshot_summary_and_gaps(repo: Path) -> dict[str, bytes]:
    """Capture summary dir and gaps dir content for idempotence check."""
    snapshot: dict[str, bytes] = {}
    for subdir in ("summary", "gaps"):
        d = repo / ".claude-reflect" / subdir
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(repo / ".claude-reflect"))
                snapshot[rel] = p.read_bytes()
    return snapshot


def run_maintenance(*, repo: Path) -> None:
    """
    Execute a full maintenance pass.

    Spec ref: docs/spec/04-processes/maintenance.md

    Operations in order:
    1. Ingest new content (identify gaps, etc.)
    2. Update gap-kind pages
    3. Update archive-entry pages (stub)
    4. Update exploration-profile page
    5. Update gap-dashboard page
    6. Reconcile kind vocabulary
    7. Transition stale gaps
    8. Detect session clusters (stub)
    9. Detect decision lineages (stub)
    10. Consolidate (stub)
    11. Regenerate index
    12. Write maintenance log

    Idempotent: running twice on the same inputs produces byte-identical
    state. Achieves this by snapshotting before/after and skipping the
    log entry when nothing changed.
    """
    mh = repo / ".claude-reflect"
    if not mh.exists():
        return

    config = _load_config(repo)
    stale_threshold = config.get("stale_gap_threshold_sessions", 30)

    summary_dir = get_summary_dir(mh)
    summary_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot state before this pass (for idempotence detection).
    pre_snapshot = _snapshot_summary_and_gaps(repo)

    # 6. Reconcile kind vocabulary (before generating pages so pages reflect merged kinds)
    recon_result = reconcile_kind_vocabulary(repo=repo)

    # 7. Transition stale gaps (before generating pages so pages reflect new statuses)
    transitioned = transition_stale_gaps(
        repo=repo,
        stale_threshold_sessions=stale_threshold,
        current_session_count=0,  # not used; we use date-based logic
    )

    # Use a fixed timestamp for all pages in this pass to ensure
    # idempotence (same input -> same output).
    # Derive timestamp from the state of gap records on disk.
    all_gaps = _load_all_gaps(repo)
    timestamp = _derive_pass_timestamp(all_gaps)

    pages_created = 0

    # 2. Update gap-kind pages
    gaps_by_kind: dict[str, list[dict]] = {}
    for g in all_gaps:
        gaps_by_kind.setdefault(g["kind"], []).append(g)
    pages_created += _generate_gap_kind_pages(summary_dir, gaps_by_kind, timestamp)

    # 4. Update exploration-profile page
    _generate_exploration_profile(summary_dir, all_gaps, timestamp)
    pages_created += 1

    # 5. Update gap-dashboard page
    _generate_gap_dashboard(summary_dir, all_gaps, timestamp)
    pages_created += 1

    # 11. Regenerate index
    regenerate_index(summary_dir)

    # Check if anything actually changed
    post_snapshot = _snapshot_summary_and_gaps(repo)
    if pre_snapshot == post_snapshot:
        # Nothing changed — idempotent no-op, skip the log entry.
        return

    # 12. Write maintenance log (only when work was actually done)
    log = MaintenanceLog(repo=repo)
    log.record(
        pages_created=pages_created,
        pages_updated=0,
        pages_deprecated=0,
        kinds_reconciled=recon_result.merged_kinds,
        gaps_transitioned=transitioned,
    )


def _derive_pass_timestamp(gaps: list[dict]) -> str:
    """
    Derive a deterministic timestamp from the gap records on disk.

    Uses the maximum last_observed_at from all gaps, ensuring that
    identical disk state always produces an identical timestamp.
    Falls back to a fixed epoch if no gaps exist.
    """
    max_ts = ""
    for g in gaps:
        ts = g.get("last_observed_at", "")
        if ts > max_ts:
            max_ts = ts
    if not max_ts:
        return "1970-01-01T00:00:00Z"
    return max_ts
