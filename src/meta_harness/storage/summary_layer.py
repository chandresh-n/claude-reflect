"""
Summary layer storage & index regeneration.

Spec ref: docs/spec/02-storage/summary-layer.md

The summary layer is a collection of LLM-maintained markdown pages that
synthesize views over the canonical layers. It is regenerable and is not
a source of truth.
"""
from __future__ import annotations

import enum
import re
from datetime import datetime, timezone
from pathlib import Path


class PageKind(enum.Enum):
    """Page kinds defined by the spec."""

    GAP_KIND = "gap_kind"
    ARCHIVE_ENTRY = "archive_entry"
    EXPLORATION_PROFILE = "exploration_profile"
    GAP_DASHBOARD = "gap_dashboard"
    SESSION_CLUSTER = "session_cluster"
    DECISION_LINEAGE = "decision_lineage"


# The spec says exploration-profile and gap-dashboard "always exist and are
# current within one maintenance cycle".
REQUIRED_PAGE_KINDS: frozenset[PageKind] = frozenset(
    {PageKind.EXPLORATION_PROFILE, PageKind.GAP_DASHBOARD}
)

# Mapping from PageKind to the subdirectory name used on disk.
_KIND_DIR: dict[PageKind, str] = {
    PageKind.GAP_KIND: "gap-kind",
    PageKind.ARCHIVE_ENTRY: "archive-entry",
    PageKind.EXPLORATION_PROFILE: "exploration-profile",
    PageKind.GAP_DASHBOARD: "gap-dashboard",
    PageKind.SESSION_CLUSTER: "session-cluster",
    PageKind.DECISION_LINEAGE: "decision-lineage",
}

# Mapping from PageKind to the section header used in the index.
_KIND_SECTION_HEADER: dict[PageKind, str] = {
    PageKind.GAP_KIND: "## Gap-kind pages",
    PageKind.ARCHIVE_ENTRY: "## Archive-entry pages",
    PageKind.EXPLORATION_PROFILE: "## Exploration-profile",
    PageKind.GAP_DASHBOARD: "## Gap-dashboard",
    PageKind.SESSION_CLUSTER: "## Session-cluster pages",
    PageKind.DECISION_LINEAGE: "## Decision-lineage pages",
}

# Stable ordering for index sections (matches spec).
_KIND_ORDER: list[PageKind] = [
    PageKind.GAP_KIND,
    PageKind.ARCHIVE_ENTRY,
    PageKind.EXPLORATION_PROFILE,
    PageKind.GAP_DASHBOARD,
    PageKind.SESSION_CLUSTER,
    PageKind.DECISION_LINEAGE,
]


def get_summary_dir(kb_root: Path) -> Path:
    """Return the summary layer directory path under a knowledge-base root."""
    return kb_root / "summary"


def _kind_dir(summary_dir: Path, page_kind: PageKind) -> Path:
    """Return the subdirectory for a given page kind, creating if needed."""
    d = summary_dir / _KIND_DIR[page_kind]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_content(content: str) -> None:
    """Validate that page content meets spec requirements."""
    if not content.startswith("Last updated:"):
        raise ValueError(
            "Page content must begin with a 'Last updated:' line."
        )
    if "Generated from:" not in content:
        raise ValueError(
            "Page content must include a 'Generated from:' line."
        )


def write_page(
    summary_dir: Path,
    page_kind: PageKind,
    anchor: str,
    content: str,
) -> Path:
    """Write a summary page to disk. Returns the file path."""
    _validate_content(content)
    dest = _kind_dir(summary_dir, page_kind) / f"{anchor}.md"
    dest.write_text(content, encoding="utf-8")
    return dest


def read_page(
    summary_dir: Path,
    page_kind: PageKind,
    anchor: str,
) -> str:
    """Read a summary page from disk."""
    path = _kind_dir(summary_dir, page_kind) / f"{anchor}.md"
    return path.read_text(encoding="utf-8")


def list_pages(
    summary_dir: Path,
    page_kind: PageKind,
) -> list[Path]:
    """List all pages of a given kind. Returns sorted list of paths."""
    d = summary_dir / _KIND_DIR[page_kind]
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.suffix == ".md")


def _extract_last_updated(content: str) -> str:
    """Extract the timestamp from the 'Last updated:' line."""
    for line in content.splitlines():
        if line.startswith("Last updated:"):
            return line.split(":", 1)[1].strip()
    return ""


def regenerate_index(summary_dir: Path) -> str:
    """
    Regenerate the summary layer index from the pages on disk.

    Writes index.md to summary_dir and returns the content string.
    Deterministic: same disk state always produces identical output.
    """
    lines: list[str] = []
    lines.append("# Summary Layer Index")
    lines.append("")
    lines.append(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")

    for kind in _KIND_ORDER:
        pages = list_pages(summary_dir=summary_dir, page_kind=kind)
        if not pages:
            continue
        lines.append(_KIND_SECTION_HEADER[kind])
        for page_path in pages:
            anchor = page_path.stem
            content = page_path.read_text(encoding="utf-8")
            last_updated = _extract_last_updated(content)
            lines.append(f"  - {anchor}, {last_updated}")
        lines.append("")

    result = "\n".join(lines)
    index_path = summary_dir / "index.md"
    index_path.write_text(result, encoding="utf-8")
    return result
