"""
Step 6 gate — Summary layer storage & index regeneration (HARD gate): Unit tests.

Spec ref: docs/spec/02-storage/summary-layer.md

Gate criteria (from docs/PLAN.md Step 6):
  1. Page kinds are enumerated correctly per the spec.
  2. Regeneration is idempotent: run twice -> byte-identical output.
  3. Architectural test: assert no code path from the proposer module
     reaches summary files (enforces the cross-cutting caution that the
     summary layer is not authoritative).

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_reflect.storage.summary_layer import (
    PageKind,
    regenerate_index,
    write_page,
    read_page,
    list_pages,
    get_summary_dir,
    REQUIRED_PAGE_KINDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_summary_dir(tmp_path: Path) -> Path:
    """Create the summary layer directory structure under a tmp .claude-reflect."""
    summary_dir = tmp_path / ".claude-reflect" / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    return summary_dir


def _make_gap_kind_page_content(kind_label: str) -> str:
    """Return minimal valid content for a gap-kind page."""
    return (
        f"Last updated: 2024-01-15T12:00:00Z\n\n"
        f"Generated from: gaps/{kind_label}\n\n"
        f"# Gap kind: {kind_label}\n\n"
        f"Characterization of the '{kind_label}' gap kind.\n\n"
        f"## Gap records\n\n"
        f"- gap-001 (source: session-abc, turns 3-5)\n\n"
        f"## Historical proposals\n\n"
        f"None yet.\n"
    )


def _make_archive_entry_page_content(entry_id: str) -> str:
    """Return minimal valid content for an archive-entry page."""
    return (
        f"Last updated: 2024-01-15T12:00:00Z\n\n"
        f"Generated from: archive/{entry_id}\n\n"
        f"# Archive entry: {entry_id}\n\n"
        f"Qualitative position: initial configuration.\n\n"
        f"## Gaps observed\n\n"
        f"None yet.\n"
    )


def _make_exploration_profile_content() -> str:
    """Return minimal valid content for the exploration-profile page."""
    return (
        "Last updated: 2024-01-15T12:00:00Z\n\n"
        "Generated from: gaps/, archive/, decisions/\n\n"
        "# Exploration Profile\n\n"
        "## Recently touched surfaces\n\n"
        "None yet.\n\n"
        "## Neglected regions\n\n"
        "None identified.\n"
    )


def _make_gap_dashboard_content() -> str:
    """Return minimal valid content for the gap-dashboard page."""
    return (
        "Last updated: 2024-01-15T12:00:00Z\n\n"
        "Generated from: gaps/\n\n"
        "# Gap Dashboard\n\n"
        "## Active gaps\n\n"
        "No active gaps.\n"
    )


# ---------------------------------------------------------------------------
# Gate criterion 1: Page kinds enumerated correctly per the spec
# ---------------------------------------------------------------------------

class TestPageKindsEnumeration:
    """Page kinds must match the spec's enumerated set."""

    def test_gap_kind_pages_in_enumeration(self):
        """The spec defines 'gap-kind pages' as a page kind."""
        assert PageKind.GAP_KIND in PageKind
        assert "gap_kind" in PageKind.GAP_KIND.value or "gap-kind" in PageKind.GAP_KIND.value

    def test_archive_entry_pages_in_enumeration(self):
        """The spec defines 'archive-entry pages' as a page kind."""
        assert PageKind.ARCHIVE_ENTRY in PageKind

    def test_exploration_profile_in_enumeration(self):
        """The spec defines 'exploration-profile page' as a page kind."""
        assert PageKind.EXPLORATION_PROFILE in PageKind

    def test_gap_dashboard_in_enumeration(self):
        """The spec defines 'gap-dashboard page' as a page kind."""
        assert PageKind.GAP_DASHBOARD in PageKind

    def test_session_cluster_in_enumeration(self):
        """The spec defines 'session-cluster pages' as emergent."""
        assert PageKind.SESSION_CLUSTER in PageKind

    def test_decision_lineage_in_enumeration(self):
        """The spec defines 'decision-lineage pages' as emergent."""
        assert PageKind.DECISION_LINEAGE in PageKind

    def test_all_spec_page_kinds_present(self):
        """Exactly the six page kinds from the spec exist."""
        expected = {
            "gap_kind",
            "archive_entry",
            "exploration_profile",
            "gap_dashboard",
            "session_cluster",
            "decision_lineage",
        }
        actual = {pk.value for pk in PageKind}
        assert actual == expected

    def test_required_page_kinds_includes_always_current_pages(self):
        """
        The spec says exploration-profile and gap-dashboard 'always exist
        and are current'. REQUIRED_PAGE_KINDS must include at least these.
        """
        assert PageKind.EXPLORATION_PROFILE in REQUIRED_PAGE_KINDS
        assert PageKind.GAP_DASHBOARD in REQUIRED_PAGE_KINDS


# ---------------------------------------------------------------------------
# Gate criterion 1 (continued): Page content requirements
# ---------------------------------------------------------------------------

class TestPageContentRequirements:
    """Every page must meet the spec's content requirements."""

    def test_page_has_last_updated_line(self, tmp_path):
        """Every page must begin with a 'Last updated' line."""
        summary_dir = _setup_summary_dir(tmp_path)
        content = _make_gap_kind_page_content("tool_call_loop")
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=content,
        )
        retrieved = read_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
        )
        assert retrieved.startswith("Last updated:")

    def test_page_has_generated_from_line(self, tmp_path):
        """Every page must include a 'Generated from' line."""
        summary_dir = _setup_summary_dir(tmp_path)
        content = _make_gap_kind_page_content("tool_call_loop")
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=content,
        )
        retrieved = read_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
        )
        assert "Generated from:" in retrieved

    def test_write_rejects_page_without_last_updated(self, tmp_path):
        """write_page must reject content missing 'Last updated' line."""
        summary_dir = _setup_summary_dir(tmp_path)
        bad_content = "# Some page\n\nNo metadata header.\n"
        with pytest.raises(ValueError, match="[Ll]ast updated"):
            write_page(
                summary_dir=summary_dir,
                page_kind=PageKind.GAP_KIND,
                anchor="bad_page",
                content=bad_content,
            )

    def test_write_rejects_page_without_generated_from(self, tmp_path):
        """write_page must reject content missing 'Generated from' line."""
        summary_dir = _setup_summary_dir(tmp_path)
        bad_content = "Last updated: 2024-01-15T12:00:00Z\n\n# No sources\n"
        with pytest.raises(ValueError, match="[Gg]enerated from"):
            write_page(
                summary_dir=summary_dir,
                page_kind=PageKind.GAP_KIND,
                anchor="bad_page",
                content=bad_content,
            )


# ---------------------------------------------------------------------------
# Gate criterion 1 (continued): Index structure matches the spec
# ---------------------------------------------------------------------------

class TestIndexStructure:
    """The index must follow the spec's structure."""

    def test_index_has_summary_layer_index_heading(self, tmp_path):
        """Index starts with '# Summary Layer Index'."""
        summary_dir = _setup_summary_dir(tmp_path)
        # Write required pages so index can be generated
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )
        index_content = regenerate_index(summary_dir=summary_dir)
        assert index_content.startswith("# Summary Layer Index")

    def test_index_has_last_updated(self, tmp_path):
        """Index contains a 'Last updated:' line."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )
        index_content = regenerate_index(summary_dir=summary_dir)
        assert "Last updated:" in index_content

    def test_index_has_section_per_present_page_kind(self, tmp_path):
        """
        The spec says: 'organized into sections, one per page-kind' and
        'every page-kind section header corresponds to a page-kind that has
        at least one page.'
        """
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=_make_gap_kind_page_content("tool_call_loop"),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )
        index_content = regenerate_index(summary_dir=summary_dir)
        # Sections for the three page kinds that have pages
        assert "## Gap-kind pages" in index_content
        assert "## Exploration-profile" in index_content
        assert "## Gap-dashboard" in index_content
        # No section for page kinds with no pages
        assert "## Archive-entry pages" not in index_content
        assert "## Session-cluster pages" not in index_content
        assert "## Decision-lineage pages" not in index_content

    def test_index_lists_each_page_exactly_once(self, tmp_path):
        """Every page appears under exactly one section."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=_make_gap_kind_page_content("tool_call_loop"),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="permission_escalation",
            content=_make_gap_kind_page_content("permission_escalation"),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )
        index_content = regenerate_index(summary_dir=summary_dir)
        # Each anchor appears exactly once
        assert index_content.count("tool_call_loop") == 1
        assert index_content.count("permission_escalation") == 1
        assert index_content.count("exploration-profile") == 1
        assert index_content.count("gap-dashboard") == 1


# ---------------------------------------------------------------------------
# Gate criterion 1 (continued): Page filesystem layout
# ---------------------------------------------------------------------------

class TestPageFilesystemLayout:
    """Pages are organized by page kind in the summary directory."""

    def test_write_creates_file_with_anchor_in_name(self, tmp_path):
        """The filename identifies the anchor unambiguously."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=_make_gap_kind_page_content("tool_call_loop"),
        )
        pages = list_pages(summary_dir=summary_dir, page_kind=PageKind.GAP_KIND)
        assert len(pages) == 1
        assert "tool_call_loop" in pages[0].name

    def test_list_pages_filters_by_kind(self, tmp_path):
        """list_pages returns only pages of the requested kind."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=_make_gap_kind_page_content("tool_call_loop"),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        gap_pages = list_pages(summary_dir=summary_dir, page_kind=PageKind.GAP_KIND)
        assert len(gap_pages) == 1
        profile_pages = list_pages(
            summary_dir=summary_dir, page_kind=PageKind.EXPLORATION_PROFILE
        )
        assert len(profile_pages) == 1

    def test_summary_dir_path(self, tmp_path):
        """get_summary_dir returns the expected path."""
        kb_root = tmp_path / ".claude-reflect"
        kb_root.mkdir(parents=True, exist_ok=True)
        result = get_summary_dir(kb_root=kb_root)
        assert result == kb_root / "summary"


# ---------------------------------------------------------------------------
# Gate criterion 2: Regeneration is idempotent (byte-identical)
# ---------------------------------------------------------------------------

class TestRegenerationIdempotent:
    """Running regenerate_index twice produces byte-identical output."""

    def test_index_regeneration_idempotent(self, tmp_path):
        """regenerate_index called twice with the same state -> same output."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=_make_gap_kind_page_content("tool_call_loop"),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.ARCHIVE_ENTRY,
            anchor="entry-001",
            content=_make_archive_entry_page_content("entry-001"),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )

        first_run = regenerate_index(summary_dir=summary_dir)
        second_run = regenerate_index(summary_dir=summary_dir)
        assert first_run == second_run

    def test_index_regeneration_idempotent_empty(self, tmp_path):
        """Idempotent even when summary dir has only required pages."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )

        first_run = regenerate_index(summary_dir=summary_dir)
        second_run = regenerate_index(summary_dir=summary_dir)
        assert first_run == second_run

    def test_index_regeneration_idempotent_many_pages(self, tmp_path):
        """Idempotent with multiple pages across multiple kinds."""
        summary_dir = _setup_summary_dir(tmp_path)
        # Multiple gap-kind pages
        for kind in ["tool_call_loop", "permission_escalation", "stale_context"]:
            write_page(
                summary_dir=summary_dir,
                page_kind=PageKind.GAP_KIND,
                anchor=kind,
                content=_make_gap_kind_page_content(kind),
            )
        # Multiple archive-entry pages
        for entry in ["entry-001", "entry-002"]:
            write_page(
                summary_dir=summary_dir,
                page_kind=PageKind.ARCHIVE_ENTRY,
                anchor=entry,
                content=_make_archive_entry_page_content(entry),
            )
        # Required pages
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )

        first_run = regenerate_index(summary_dir=summary_dir)
        second_run = regenerate_index(summary_dir=summary_dir)
        assert first_run == second_run


# ---------------------------------------------------------------------------
# Gate criterion 2 (continued): No scalar grades in output
# ---------------------------------------------------------------------------

class TestNoScalarGrades:
    """The summary layer must not produce scalar grades (cross-cutting)."""

    def test_index_contains_no_numeric_scores(self, tmp_path):
        """Index output must not contain score-like patterns."""
        summary_dir = _setup_summary_dir(tmp_path)
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=_make_exploration_profile_content(),
        )
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_DASHBOARD,
            anchor="gap-dashboard",
            content=_make_gap_dashboard_content(),
        )
        index_content = regenerate_index(summary_dir=summary_dir)
        # No "score:", "priority:", "grade:", "rating:" patterns
        import re
        assert not re.search(r'\b(score|priority|grade|rating)\s*:', index_content, re.IGNORECASE)
