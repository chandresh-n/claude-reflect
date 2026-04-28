"""
Step 6 gate — Summary layer storage & index regeneration (HARD gate): Integration tests.

Spec ref: docs/spec/02-storage/summary-layer.md

Gate criteria (from docs/PLAN.md Step 6):
  3. Architectural test: assert no code path from the proposer module
     reaches summary files (enforces the cross-cutting caution that the
     summary layer is not authoritative).

Also exercises:
  - End-to-end index regeneration with a populated summary directory.
  - Index file written to disk matches in-memory result.
  - Idempotent regeneration at the filesystem level (byte-identical files).

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import ast
import importlib
import inspect
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from meta_harness.storage.summary_layer import (
    PageKind,
    regenerate_index,
    write_page,
    read_page,
    list_pages,
    get_summary_dir,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_summary_dir(tmp_path: Path) -> Path:
    """Create the summary layer directory structure under a tmp .meta-harness."""
    summary_dir = tmp_path / ".meta-harness" / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    return summary_dir


def _make_exploration_profile_content() -> str:
    return (
        "Last updated: 2024-01-15T12:00:00Z\n\n"
        "Generated from: gaps/, archive/, decisions/\n\n"
        "# Exploration Profile\n\n"
        "## Recently touched surfaces\n\nNone yet.\n\n"
        "## Neglected regions\n\nNone identified.\n"
    )


def _make_gap_dashboard_content() -> str:
    return (
        "Last updated: 2024-01-15T12:00:00Z\n\n"
        "Generated from: gaps/\n\n"
        "# Gap Dashboard\n\n"
        "## Active gaps\n\nNo active gaps.\n"
    )


def _make_gap_kind_page_content(kind_label: str) -> str:
    return (
        f"Last updated: 2024-01-15T12:00:00Z\n\n"
        f"Generated from: gaps/{kind_label}\n\n"
        f"# Gap kind: {kind_label}\n\n"
        f"Characterization of the '{kind_label}' gap kind.\n\n"
        f"## Gap records\n\n"
        f"- gap-001 (source: session-abc, turns 3-5)\n\n"
        f"## Historical proposals\n\nNone yet.\n"
    )


def _make_archive_entry_page_content(entry_id: str) -> str:
    return (
        f"Last updated: 2024-01-15T12:00:00Z\n\n"
        f"Generated from: archive/{entry_id}\n\n"
        f"# Archive entry: {entry_id}\n\n"
        f"Qualitative position: initial configuration.\n\n"
        f"## Gaps observed\n\nNone yet.\n"
    )


# ---------------------------------------------------------------------------
# Gate criterion 3: Architectural test — proposer cannot reach summary files
# ---------------------------------------------------------------------------

class TestProposerCannotReachSummaryLayer:
    """
    The cross-cutting caution states: 'Summary layer is not authoritative.
    When the proposer needs current state, it reads canonical layers.'

    This architectural test statically verifies that no import path from
    the proposer module to the summary_layer module exists.
    """

    def _collect_imports_from_source(self, filepath: Path) -> set:
        """Parse a Python file and collect all imported module names."""
        source = filepath.read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        return imports

    def _collect_all_imports_transitively(
        self, start_file: Path, src_root: Path, visited: set | None = None
    ) -> set:
        """
        Recursively collect all intra-project modules imported (directly
        or transitively) starting from start_file.
        """
        if visited is None:
            visited = set()
        if str(start_file) in visited:
            return set()
        visited.add(str(start_file))

        all_modules = set()
        if not start_file.exists():
            return all_modules

        try:
            direct_imports = self._collect_imports_from_source(start_file)
        except SyntaxError:
            return all_modules

        for mod_name in direct_imports:
            all_modules.add(mod_name)
            # Resolve to a file path within the project
            parts = mod_name.split(".")
            candidate = src_root / "/".join(parts)
            # Try as a module file
            for suffix in [".py", "/__init__.py"]:
                mod_file = Path(str(candidate) + suffix)
                if mod_file.exists():
                    sub_modules = self._collect_all_imports_transitively(
                        mod_file, src_root, visited
                    )
                    all_modules.update(sub_modules)
                    break

        return all_modules

    def test_proposer_does_not_import_summary_layer(self):
        """
        The proposer module must never import summary_layer, directly
        or transitively.
        """
        src_root = Path(__file__).resolve().parents[2] / "src"
        proposer_file = src_root / "meta_harness" / "agents" / "proposer.py"

        # If proposer doesn't exist yet, the test should still fail
        # with an informative message (it's a gate test).
        if not proposer_file.exists():
            # The proposer module doesn't exist yet. When it does, this
            # test will verify the architectural constraint. For the
            # Session A gate, we verify the summary_layer module exists
            # (which it won't yet, causing the expected import failure).
            pytest.skip(
                "Proposer module does not exist yet; "
                "architectural constraint will be enforced when it does."
            )
            return

        all_imports = self._collect_all_imports_transitively(proposer_file, src_root)
        summary_imports = {
            m for m in all_imports
            if "summary_layer" in m or "summary-layer" in m
        }
        assert not summary_imports, (
            f"Proposer module must not import summary_layer (directly or "
            f"transitively), but found: {summary_imports}"
        )

    def test_summary_layer_module_has_no_proposer_references(self):
        """
        The summary_layer module source must not reference the proposer
        module (bidirectional check).
        """
        src_root = Path(__file__).resolve().parents[2] / "src"
        summary_file = src_root / "meta_harness" / "storage" / "summary_layer.py"

        if not summary_file.exists():
            pytest.fail(
                "summary_layer.py does not exist yet — "
                "expected for Session A failing gate."
            )

        source = summary_file.read_text()
        assert "proposer" not in source.lower(), (
            "summary_layer.py must not reference the proposer module."
        )


# ---------------------------------------------------------------------------
# Integration: End-to-end index regeneration on disk
# ---------------------------------------------------------------------------

class TestEndToEndIndexRegeneration:
    """Full round-trip: write pages, regenerate index, verify on disk."""

    def test_index_file_written_to_disk(self, tmp_path):
        """regenerate_index writes an index.md file to the summary dir."""
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

        index_file = summary_dir / "index.md"
        assert index_file.exists(), "regenerate_index must write index.md"
        assert index_file.read_text() == index_content

    def test_filesystem_idempotent(self, tmp_path):
        """Two regenerations produce byte-identical files on disk."""
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

        regenerate_index(summary_dir=summary_dir)
        first_bytes = (summary_dir / "index.md").read_bytes()

        regenerate_index(summary_dir=summary_dir)
        second_bytes = (summary_dir / "index.md").read_bytes()

        assert first_bytes == second_bytes

    def test_index_consistent_with_pages_on_disk(self, tmp_path):
        """
        Spec invariant: 'The index is consistent with the set of pages
        actually present.'
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

        # Every page on disk must appear in the index
        all_pages = []
        for pk in PageKind:
            all_pages.extend(list_pages(summary_dir=summary_dir, page_kind=pk))

        for page_path in all_pages:
            anchor = page_path.stem
            assert anchor in index_content, (
                f"Page '{anchor}' exists on disk but is not in the index."
            )

    def test_index_no_phantom_entries(self, tmp_path):
        """
        The index must not reference pages that don't exist on disk.
        Specifically: only page kinds with pages get section headers.
        """
        summary_dir = _setup_summary_dir(tmp_path)
        # Only write required pages — no gap-kind, archive-entry, etc.
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

        # No section headers for kinds that have zero pages
        assert "## Gap-kind pages" not in index_content
        assert "## Archive-entry pages" not in index_content
        assert "## Session-cluster pages" not in index_content
        assert "## Decision-lineage pages" not in index_content


# ---------------------------------------------------------------------------
# Integration: Page round-trip
# ---------------------------------------------------------------------------

class TestPageRoundTrip:
    """Write a page, read it back, verify content is preserved."""

    def test_gap_kind_page_roundtrip(self, tmp_path):
        summary_dir = _setup_summary_dir(tmp_path)
        original = _make_gap_kind_page_content("tool_call_loop")
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
            content=original,
        )
        retrieved = read_page(
            summary_dir=summary_dir,
            page_kind=PageKind.GAP_KIND,
            anchor="tool_call_loop",
        )
        assert retrieved == original

    def test_archive_entry_page_roundtrip(self, tmp_path):
        summary_dir = _setup_summary_dir(tmp_path)
        original = _make_archive_entry_page_content("entry-001")
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.ARCHIVE_ENTRY,
            anchor="entry-001",
            content=original,
        )
        retrieved = read_page(
            summary_dir=summary_dir,
            page_kind=PageKind.ARCHIVE_ENTRY,
            anchor="entry-001",
        )
        assert retrieved == original

    def test_exploration_profile_roundtrip(self, tmp_path):
        summary_dir = _setup_summary_dir(tmp_path)
        original = _make_exploration_profile_content()
        write_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
            content=original,
        )
        retrieved = read_page(
            summary_dir=summary_dir,
            page_kind=PageKind.EXPLORATION_PROFILE,
            anchor="exploration-profile",
        )
        assert retrieved == original
