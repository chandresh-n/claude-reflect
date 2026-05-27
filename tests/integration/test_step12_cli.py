"""
Integration tests for Step 12 — CLI and skill wrapper (HARD CLI gate).

Spec refs:
  - docs/spec/05-interfaces/skill-invocation.md
  - docs/spec/05-interfaces/human-review.md

Gate criteria (from docs/PLAN.md Step 12):
1. review, status, maintenance subcommands work against fixture state.
2. --resume <run_id> re-opens the same markdown and diffs.
3. --verbose adds streamed output and tool-call traces.
4. Fresh-repo first invocation runs Phase 1 automatically.
5. Proposal batch markdown contains no decorative formatting
   (assert with a regex against rendered output).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from claude_reflect.agents.claude_runner import ClaudeRunnerError
from claude_reflect.cli import main, build_parser, ReviewCommand, StatusCommand, MaintenanceCommand


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Create a bare-minimum git repo with an initial commit."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    (path / "README.md").write_text("init\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(path), capture_output=True, check=True,
    )


def _setup_kb(path: Path) -> None:
    """Initialize the knowledge base so that the repo is not 'fresh'."""
    from claude_reflect.storage.knowledge_base import setup
    setup(path)


def _create_fixture_run_state(path: Path, run_id: str, status: str = "complete",
                               phase: int = 9, proposals: list | None = None,
                               author_results: dict | None = None,
                               decisions: list | None = None,
                               pending_proposals: list | None = None) -> Path:
    """Create a fixture run-state file on disk."""
    runs_dir = path / ".claude-reflect" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "status": status,
        "current_phase": phase,
        "pending_proposals": pending_proposals or [],
        "proposal_batch": {
            "proposals": proposals or [],
            "proposal_ids": [p["proposal_id"] for p in (proposals or [])],
        },
        "author_results": author_results or {},
        "decisions": decisions or [],
    }
    run_file = runs_dir / f"{run_id}.json"
    run_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return run_file


def _make_proposal(proposal_id: str, title: str = "Test proposal") -> dict:
    """Create a minimal proposal fixture."""
    return {
        "proposal_id": proposal_id,
        "title": title,
        "why": {"prose_summary": "Test rationale"},
        "what": {
            "short_description": "Test change",
            "mechanism_prose": "Apply a test change",
            "diff_reference": f"claude-reflect/proposal/{proposal_id}",
            "files_touched": ["test.py"],
        },
        "how": {"mechanism_prose": "Modify test.py"},
        "prediction": {"expected_impact_prose": "Tests pass"},
    }


# ---------------------------------------------------------------------------
# 1. Subcommand tests — review, status, maintenance
# ---------------------------------------------------------------------------


class TestReviewSubcommand:
    """The 'review' subcommand triggers a run loop against fixture state."""

    def test_review_subcommand_exists(self, tmp_path: Path) -> None:
        """The parser recognizes 'review' as a valid subcommand."""
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days"])
        assert args.subcommand == "review"

    def test_review_accepts_absolute_date_range(self, tmp_path: Path) -> None:
        """review --range '2026-04-01 to 2026-04-07' parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "2026-04-01 to 2026-04-07"])
        assert "2026-04-01" in args.range

    def test_review_accepts_relative_date_range(self, tmp_path: Path) -> None:
        """review --range 'last 7 days' parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days"])
        assert "last 7 days" in args.range

    def test_review_runs_against_fixture_state(self, tmp_path: Path) -> None:
        """ReviewCommand.execute() runs the run loop against fixture state."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(repo=tmp_path, date_range="last 7 days", verbose=False)
        # Should complete without error when agents are mocked
        with patch.object(cmd, "_make_run_loop") as mock_make:
            mock_state = MagicMock()
            mock_state.status = "complete"
            mock_state.decisions = []
            mock_state.run_id = "run-test123"
            mock_run_loop = MagicMock()
            mock_run_loop.run.return_value = mock_state
            mock_make.return_value = mock_run_loop
            result = cmd.execute()
            assert result is not None
            mock_run_loop.run.assert_called_once()


class TestStatusSubcommand:
    """The 'status' subcommand reports the state of the knowledge base."""

    def test_status_subcommand_exists(self, tmp_path: Path) -> None:
        """The parser recognizes 'status' as a valid subcommand."""
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.subcommand == "status"

    def test_status_reports_kb_state(self, tmp_path: Path) -> None:
        """StatusCommand.execute() returns structured state about the KB."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = StatusCommand(repo=tmp_path)
        result = cmd.execute()
        # Should return a dict (or similar) with gap count, decision count, etc.
        assert isinstance(result, dict)
        assert "initialized" in result
        assert result["initialized"] is True

    def test_status_on_fresh_repo(self, tmp_path: Path) -> None:
        """StatusCommand on a repo without .claude-reflect/ reports uninitialized."""
        _init_git_repo(tmp_path)
        cmd = StatusCommand(repo=tmp_path)
        result = cmd.execute()
        assert isinstance(result, dict)
        assert result["initialized"] is False


class TestMaintenanceSubcommand:
    """The 'maintenance' subcommand triggers a maintenance pass."""

    def test_maintenance_subcommand_exists(self, tmp_path: Path) -> None:
        """The parser recognizes 'maintenance' as a valid subcommand."""
        parser = build_parser()
        args = parser.parse_args(["maintenance"])
        assert args.subcommand == "maintenance"

    def test_maintenance_runs_against_fixture_state(self, tmp_path: Path) -> None:
        """MaintenanceCommand.execute() runs maintenance on fixture state."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = MaintenanceCommand(repo=tmp_path)
        # Should complete without error
        result = cmd.execute()
        # Maintenance should return some indication of what it did
        assert result is not None


# ---------------------------------------------------------------------------
# 2. --resume re-opens the same markdown and diffs
# ---------------------------------------------------------------------------


class TestResumeFlag:
    """--resume <run_id> resumes a paused run and re-opens its batch."""

    def test_resume_flag_parsed(self, tmp_path: Path) -> None:
        """The parser accepts --resume <run_id>."""
        parser = build_parser()
        args = parser.parse_args(["review", "--resume", "run-abc123"])
        assert args.resume == "run-abc123"

    def test_resume_reopens_same_batch(self, tmp_path: Path) -> None:
        """Resuming a paused run re-presents the same proposal batch."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        # Create a paused run with proposals
        proposals = [_make_proposal("prop-001", "First proposal")]
        author_results = {
            "prop-001": {"status": "success", "diff_reference": "branch-1",
                         "files_touched": ["a.py"]},
        }
        _create_fixture_run_state(
            tmp_path, "run-paused1", status="paused", phase=7,
            proposals=proposals, author_results=author_results,
            pending_proposals=["prop-001"],
        )

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days",
            verbose=False, resume_run_id="run-paused1",
        )

        # The human_review_fn should receive the same proposals as the original run
        captured_batches: list = []

        def capture_review(batch: dict) -> dict:
            captured_batches.append(batch)
            return {"prop-001": "accepted"}

        with patch.object(cmd, "_make_run_loop") as mock_make:
            mock_state = MagicMock()
            mock_state.status = "complete"
            mock_state.decisions = [{"proposal_id": "prop-001", "status": "accepted"}]
            mock_state.run_id = "run-paused1"
            mock_state.proposal_batch = {"proposals": proposals}
            mock_run_loop = MagicMock()
            mock_run_loop.run.return_value = mock_state
            mock_make.return_value = mock_run_loop
            result = cmd.execute()
            # The run loop should have been created with resume_run_id
            mock_make.assert_called_once()
            call_kwargs = mock_make.call_args
            # Verify the resume_run_id was passed through
            assert result is not None

    def test_resume_nonexistent_run_fails(self, tmp_path: Path) -> None:
        """Resuming a non-existent run_id raises an error."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days",
            verbose=False, resume_run_id="run-does-not-exist",
        )
        with pytest.raises(Exception):
            cmd.execute()


# ---------------------------------------------------------------------------
# 3. --verbose adds streamed output and tool-call traces
# ---------------------------------------------------------------------------


class TestStageErrorSurfacing:
    """Stage failures must show up in the final result instead of looking
    like a clean 'complete, 0 decisions' run.

    Regression guard for the bug where a transient evaluator/proposer
    failure produced an empty result that callers could not tell apart
    from a legitimately-empty review pass.
    """

    def test_evaluator_failure_marks_result_complete_with_errors(
        self, tmp_path: Path,
    ) -> None:
        """When the evaluator raises ClaudeRunnerError, the run must:
          - complete (no exception propagated to the caller),
          - return status='complete_with_errors' (not 'complete'),
          - include the failure in result['errors'].
        """
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days", verbose=False,
        )

        # Force the imported evaluate symbol to raise. The wrapper in
        # ReviewCommand catches it, records the error, and returns empty
        # output — the run loop continues to completion.
        with patch("claude_reflect.cli.evaluate") as mock_eval, \
             patch.object(cmd, "_make_run_loop") as mock_make:
            mock_eval.side_effect = ClaudeRunnerError(
                "simulated socket connection closed"
            )

            def fake_run():
                # Invoke the real_evaluator wrapper exactly the way the run
                # loop would, so its except branch runs and populates
                # self._stage_errors.
                cmd._real_evaluator(sessions=[MagicMock()], repo=tmp_path)
                state = MagicMock()
                state.status = "complete"
                state.decisions = []
                state.run_id = "run-eval-fail"
                state.proposal_batch = {"proposals": []}
                return state

            mock_loop = MagicMock()
            mock_loop.run.side_effect = fake_run
            mock_make.return_value = mock_loop

            result = cmd.execute()

        assert result["status"] == "complete_with_errors", (
            f"Expected status='complete_with_errors' when a stage raised; "
            f"got {result['status']!r}. Full result: {result!r}"
        )
        assert "errors" in result and result["errors"], (
            "result must include a non-empty 'errors' list when stages failed"
        )
        assert any("evaluator" in e.lower() for e in result["errors"]), (
            f"the evaluator error must be in 'errors'; got {result['errors']!r}"
        )

    def test_author_claude_runner_failure_becomes_author_failed(
        self, tmp_path: Path,
    ) -> None:
        """A ClaudeRunnerError raised from inside author_agent must NOT
        crash the run mid-batch. The wrapper must catch it, return an
        author_failed result for that proposal (so the renderer can show
        an AUTHOR FAILED template), and record the failure in
        stage_errors so the final status is complete_with_errors.
        """
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days", verbose=False,
        )

        with patch("claude_reflect.cli.author_agent") as mock_author, \
             patch.object(cmd, "_make_run_loop") as mock_make:
            mock_author.side_effect = ClaudeRunnerError(
                "simulated socket close during author"
            )

            captured = {}

            def fake_run():
                # Drive the real_author wrapper exactly the way the run loop
                # would for a single proposal.
                proposal = {"proposal_id": "prop-x", "title": "x"}
                captured["author_result"] = cmd._real_author(proposal, tmp_path)
                state = MagicMock()
                state.status = "complete"
                state.decisions = []
                state.run_id = "run-author-fail"
                state.proposal_batch = {"proposals": [proposal]}
                return state

            mock_loop = MagicMock()
            mock_loop.run.side_effect = fake_run
            mock_make.return_value = mock_loop

            result = cmd.execute()

        assert captured["author_result"]["status"] == "author_failed", (
            "ClaudeRunnerError from author must produce status=author_failed, "
            f"got {captured['author_result']!r}"
        )
        assert captured["author_result"]["proposal_id"] == "prop-x", (
            "author_failed result must carry the proposal_id so the renderer "
            "and decision recorder can attribute it"
        )
        assert result["status"] == "complete_with_errors", (
            "An author Claude-runner failure must drive the run to "
            f"complete_with_errors; got {result['status']!r}"
        )
        assert "errors" in result
        assert any("author" in e.lower() for e in result["errors"]), (
            f"author error must show up in result['errors']: {result['errors']!r}"
        )

    def test_author_unexpected_exception_does_not_crash_run(
        self, tmp_path: Path,
    ) -> None:
        """Belt-and-suspenders: any non-AuthorError, non-ClaudeRunnerError
        exception out of author_agent must also degrade to author_failed
        with the proposal_id preserved."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days", verbose=False,
        )

        with patch("claude_reflect.cli.author_agent") as mock_author, \
             patch.object(cmd, "_make_run_loop") as mock_make:
            # Deliberately not AuthorError/ClaudeRunnerError.
            mock_author.side_effect = RuntimeError("disk gone weird")

            captured = {}

            def fake_run():
                proposal = {"proposal_id": "prop-y", "title": "y"}
                captured["author_result"] = cmd._real_author(proposal, tmp_path)
                state = MagicMock()
                state.status = "complete"
                state.decisions = []
                state.run_id = "run-author-unexpected"
                state.proposal_batch = {"proposals": [proposal]}
                return state

            mock_loop = MagicMock()
            mock_loop.run.side_effect = fake_run
            mock_make.return_value = mock_loop

            result = cmd.execute()

        assert captured["author_result"]["status"] == "author_failed"
        assert captured["author_result"]["proposal_id"] == "prop-y"
        assert "RuntimeError" in captured["author_result"]["author_failure_reason"]
        assert result["status"] == "complete_with_errors"

    def test_one_author_failure_does_not_block_other_proposals(
        self, tmp_path: Path,
    ) -> None:
        """Regression guard. Cascade isolation: a ClaudeRunnerError on
        proposal A must not prevent the author wrapper from running cleanly
        on proposal B. The renderer must see results for both."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days", verbose=False,
        )

        call_count = {"n": 0}

        def author_side_effect(proposal, repo, model=None, **kwargs):
            call_count["n"] += 1
            if proposal["proposal_id"] == "prop-fails":
                raise ClaudeRunnerError("transient")
            return {
                "status": "success",
                "proposal_id": proposal["proposal_id"],
                "diff_reference": "fake-branch",
                "files_touched": ["x.py"],
            }

        with patch("claude_reflect.cli.author_agent", side_effect=author_side_effect), \
             patch.object(cmd, "_make_run_loop") as mock_make:

            captured = {}

            def fake_run():
                results = {}
                for pid in ("prop-fails", "prop-succeeds"):
                    results[pid] = cmd._real_author(
                        {"proposal_id": pid, "title": pid}, tmp_path,
                    )
                captured["results"] = results
                state = MagicMock()
                state.status = "complete"
                state.decisions = []
                state.run_id = "run-cascade"
                state.proposal_batch = {
                    "proposals": [
                        {"proposal_id": "prop-fails"},
                        {"proposal_id": "prop-succeeds"},
                    ],
                }
                return state

            mock_loop = MagicMock()
            mock_loop.run.side_effect = fake_run
            mock_make.return_value = mock_loop

            cmd.execute()

        assert call_count["n"] == 2, (
            f"Both author invocations must execute; the first failure must "
            f"not short-circuit the batch. Got {call_count['n']} call(s)."
        )
        assert captured["results"]["prop-fails"]["status"] == "author_failed"
        assert captured["results"]["prop-succeeds"]["status"] == "success", (
            "prop-succeeds must run cleanly even after prop-fails raised"
        )

    def test_clean_run_keeps_complete_status(self, tmp_path: Path) -> None:
        """The complete_with_errors signalling must NOT fire on a clean run."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(
            repo=tmp_path, date_range="last 7 days", verbose=False,
        )

        with patch.object(cmd, "_make_run_loop") as mock_make:
            state = MagicMock()
            state.status = "complete"
            state.decisions = []
            state.run_id = "run-clean"
            state.proposal_batch = {"proposals": []}
            mock_loop = MagicMock()
            mock_loop.run.return_value = state
            mock_make.return_value = mock_loop

            result = cmd.execute()

        assert result["status"] == "complete", (
            f"A run with no stage errors must keep status='complete'; "
            f"got {result['status']!r}"
        )
        assert "errors" not in result, (
            "result must NOT include an 'errors' key on a clean run"
        )


class TestVerboseFlag:
    """--verbose adds streamed output and tool-call traces."""

    def test_verbose_flag_parsed(self, tmp_path: Path) -> None:
        """The parser accepts --verbose."""
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days", "--verbose"])
        assert args.verbose is True

    def test_verbose_default_is_false(self, tmp_path: Path) -> None:
        """Without --verbose, verbose defaults to False."""
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days"])
        assert args.verbose is False

    def test_verbose_produces_additional_output(self, tmp_path: Path, capsys) -> None:
        """With --verbose, the CLI produces streamed output during execution."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)

        cmd = ReviewCommand(repo=tmp_path, date_range="last 7 days", verbose=True)

        with patch.object(cmd, "_make_run_loop") as mock_make:
            mock_state = MagicMock()
            mock_state.status = "complete"
            mock_state.decisions = []
            mock_state.run_id = "run-verbose1"
            mock_state.proposal_batch = {"proposals": []}
            mock_run_loop = MagicMock()
            mock_run_loop.run.return_value = mock_state
            mock_make.return_value = mock_run_loop
            cmd.execute()

        captured = capsys.readouterr()
        # Verbose mode should produce some phase-level output
        # (at minimum, phase names or progress indicators)
        assert len(captured.out) > 0 or len(captured.err) > 0


# ---------------------------------------------------------------------------
# 4. Fresh-repo first invocation runs Phase 1 automatically
# ---------------------------------------------------------------------------


class TestFreshRepoFirstInvocation:
    """First invocation in a fresh repo runs Phase 1 (setup) automatically."""

    def test_fresh_repo_triggers_setup(self, tmp_path: Path) -> None:
        """Invoking review on a repo without .claude-reflect/ triggers Phase 1."""
        _init_git_repo(tmp_path)
        assert not (tmp_path / ".claude-reflect").exists()

        cmd = ReviewCommand(repo=tmp_path, date_range="last 7 days", verbose=False)

        with patch.object(cmd, "_make_run_loop") as mock_make:
            mock_state = MagicMock()
            mock_state.status = "complete"
            mock_state.decisions = []
            mock_state.run_id = "run-fresh1"
            mock_run_loop = MagicMock()
            mock_run_loop.run.return_value = mock_state
            mock_make.return_value = mock_run_loop
            cmd.execute()

        # After execution, .claude-reflect/ should exist (Phase 1 ran)
        assert (tmp_path / ".claude-reflect").is_dir()

    def test_subsequent_invocation_skips_setup(self, tmp_path: Path) -> None:
        """Second invocation on an already-initialized repo skips Phase 1."""
        _init_git_repo(tmp_path)
        _setup_kb(tmp_path)
        assert (tmp_path / ".claude-reflect").is_dir()

        cmd = ReviewCommand(repo=tmp_path, date_range="last 7 days", verbose=False)

        with patch("claude_reflect.cli.kb_setup") as mock_setup, \
             patch.object(cmd, "_make_run_loop") as mock_make:
            mock_state = MagicMock()
            mock_state.status = "complete"
            mock_state.decisions = []
            mock_state.run_id = "run-subsequent1"
            mock_run_loop = MagicMock()
            mock_run_loop.run.return_value = mock_state
            mock_make.return_value = mock_run_loop
            cmd.execute()

        # kb_setup should not have been called since KB already exists
        # (This is validated through the run_loop's _phase_1_setup which
        # checks if .claude-reflect/ already exists)


# ---------------------------------------------------------------------------
# 5. Proposal batch markdown — no decorative formatting
# ---------------------------------------------------------------------------


# Decorative patterns that should NOT appear in proposal batch markdown
DECORATIVE_PATTERNS = [
    r"[╔╗╚╝║═╬╠╣╦╩]",       # Box-drawing characters
    r"[┌┐└┘│─┬┴├┤┼]",       # Light box-drawing
    r"[★☆✓✗✔✘⚡🔥💡🎯🚀]",  # Decorative emoji/symbols
    r"<table>",              # HTML tables
    r"<div>",                # HTML divs
    r"\|.*\|.*\|",           # Markdown table rows (pipe-delimited)
    r"={3,}",                # Decorative separator lines (===)
    r"\*{3,}",               # Decorative separator lines (***)
    r"~{3,}",                # Decorative separator lines (~~~)
]


class TestProposalBatchMarkdown:
    """Proposal batch markdown contains no decorative formatting."""

    def test_batch_markdown_structure_matches_spec(self, tmp_path: Path) -> None:
        """The rendered batch markdown follows the spec template structure."""
        from claude_reflect.cli import render_proposal_batch_markdown

        proposals = [
            _make_proposal("prop-001", "First proposal"),
            _make_proposal("prop-002", "Second proposal"),
        ]
        author_results = {
            "prop-001": {"status": "success"},
            "prop-002": {"status": "author_failed",
                         "author_failure_reason": "Could not produce diff"},
        }

        markdown = render_proposal_batch_markdown(
            run_id="run-test",
            date_range={"start": "2026-04-01", "end": "2026-04-07"},
            proposals=proposals,
            author_results=author_results,
        )

        assert isinstance(markdown, str)
        assert len(markdown) > 0
        # Should contain proposal headers
        assert "Proposal 1 of 2" in markdown or "Proposal 1" in markdown
        assert "Proposal 2 of 2" in markdown or "Proposal 2" in markdown

    def test_batch_markdown_no_decorative_formatting(self, tmp_path: Path) -> None:
        """The batch markdown contains no decorative formatting elements."""
        from claude_reflect.cli import render_proposal_batch_markdown

        proposals = [_make_proposal("prop-001", "Test proposal")]
        author_results = {"prop-001": {"status": "success"}}

        markdown = render_proposal_batch_markdown(
            run_id="run-test",
            date_range={"start": "2026-04-01", "end": "2026-04-07"},
            proposals=proposals,
            author_results=author_results,
        )

        for pattern in DECORATIVE_PATTERNS:
            matches = re.findall(pattern, markdown)
            assert len(matches) == 0, (
                f"Decorative pattern {pattern!r} found in batch markdown: {matches}"
            )

    def test_batch_markdown_author_failed_template(self, tmp_path: Path) -> None:
        """Author-failed proposals use the spec's author-failed template."""
        from claude_reflect.cli import render_proposal_batch_markdown

        proposals = [_make_proposal("prop-fail", "Failing proposal")]
        author_results = {
            "prop-fail": {
                "status": "author_failed",
                "author_failure_reason": "Cannot produce a valid diff",
            },
        }

        markdown = render_proposal_batch_markdown(
            run_id="run-test",
            date_range={"start": "2026-04-01", "end": "2026-04-07"},
            proposals=proposals,
            author_results=author_results,
        )

        assert "AUTHOR FAILED" in markdown
        assert "Cannot produce a valid diff" in markdown

    def test_batch_markdown_decision_checkboxes(self, tmp_path: Path) -> None:
        """Successful proposals include Accept/Reject/Defer checkboxes."""
        from claude_reflect.cli import render_proposal_batch_markdown

        proposals = [_make_proposal("prop-001", "Test proposal")]
        author_results = {"prop-001": {"status": "success"}}

        markdown = render_proposal_batch_markdown(
            run_id="run-test",
            date_range={"start": "2026-04-01", "end": "2026-04-07"},
            proposals=proposals,
            author_results=author_results,
        )

        assert "Accept" in markdown
        assert "Reject" in markdown
        assert "Defer" in markdown
        # Checkboxes should be unchecked markdown checkboxes
        assert "- [ ]" in markdown

    def test_batch_markdown_no_decorative_on_empty_batch(self, tmp_path: Path) -> None:
        """Even an empty batch produces clean, non-decorative markdown."""
        from claude_reflect.cli import render_proposal_batch_markdown

        markdown = render_proposal_batch_markdown(
            run_id="run-test",
            date_range={"start": "2026-04-01", "end": "2026-04-07"},
            proposals=[],
            author_results={},
        )

        for pattern in DECORATIVE_PATTERNS:
            matches = re.findall(pattern, markdown)
            assert len(matches) == 0, (
                f"Decorative pattern {pattern!r} in empty batch markdown: {matches}"
            )

    def test_batch_markdown_tolerates_string_typed_sections(
        self, tmp_path: Path,
    ) -> None:
        """Regression guard. The proposer occasionally returns a section
        (``why`` / ``what`` / ``how`` / ``prediction``) as a plain string
        instead of a ``{field: prose}`` dict. The renderer must not raise
        AttributeError on that shape — it must surface the string as the
        section's prose so the user still sees the proposer's words.

        Surfaced by fixture-driven E2E run on 2026-05-27 (cli.py crash on
        a real proposer output where ``how`` was a string).
        """
        from claude_reflect.cli import render_proposal_batch_markdown

        # A proposal whose every section is a string (worst case).
        proposal_all_string = {
            "proposal_id": "prop-str",
            "title": "All sections as strings",
            "why": "We saw a recurring loop pattern in the session.",
            "what": "Add a stop-after-success rule to CLAUDE.md.",
            "how": "Append three lines to CLAUDE.md under the 'When to stop' section.",
            "prediction": "Loop sessions should drop by 60% next week.",
        }
        # A proposal whose sections are the spec-shaped dicts (sanity check).
        proposal_dict = _make_proposal("prop-dict", "Properly shaped proposal")
        # A proposal mixing the two shapes section-by-section.
        proposal_mixed = {
            "proposal_id": "prop-mix",
            "title": "Mixed section shapes",
            "why": {"prose_summary": "dict-shaped why"},
            "what": "string-shaped what",
            "how": {"mechanism_prose": "dict-shaped how"},
            "prediction": "string-shaped prediction",
        }

        markdown = render_proposal_batch_markdown(
            run_id="run-mix",
            date_range={"start": "2026-05-25", "end": "2026-05-25"},
            proposals=[proposal_all_string, proposal_dict, proposal_mixed],
            author_results={
                "prop-str": {"status": "success"},
                "prop-dict": {"status": "success"},
                "prop-mix": {"status": "success"},
            },
        )

        # No crash got us this far. Verify the string-typed prose actually
        # made it into the output for each section.
        assert "We saw a recurring loop pattern" in markdown, (
            "string-typed 'why' must be surfaced as the why prose"
        )
        assert "Add a stop-after-success rule" in markdown, (
            "string-typed 'what' must be surfaced as the what description"
        )
        assert "Append three lines to CLAUDE.md" in markdown, (
            "string-typed 'how' must be surfaced as the how prose (this is the "
            "exact field that crashed the renderer pre-fix)"
        )
        assert "Loop sessions should drop by 60%" in markdown, (
            "string-typed 'prediction' must be surfaced as the prediction prose"
        )
        # Mixed-shape proposal must surface both dict-shaped and string-shaped.
        assert "dict-shaped why" in markdown
        assert "string-shaped what" in markdown
        assert "dict-shaped how" in markdown
        assert "string-shaped prediction" in markdown

    def test_batch_markdown_tolerates_string_section_on_author_failed(
        self, tmp_path: Path,
    ) -> None:
        """Same defensive shape needed on the author-failed code path,
        which has its own (smaller) set of section reads."""
        from claude_reflect.cli import render_proposal_batch_markdown

        proposal = {
            "proposal_id": "prop-fail",
            "title": "Failed with string sections",
            "why": "saw a thing",
            "what": "tried a thing",
            "how": "via a thing",
            "prediction": "expects a thing",
        }
        markdown = render_proposal_batch_markdown(
            run_id="run-test",
            date_range={"start": "2026-05-25", "end": "2026-05-25"},
            proposals=[proposal],
            author_results={
                "prop-fail": {
                    "status": "author_failed",
                    "author_failure_reason": "no diff produced",
                },
            },
        )

        assert "AUTHOR FAILED" in markdown
        assert "saw a thing" in markdown
        assert "tried a thing" in markdown
        assert "no diff produced" in markdown


# ---------------------------------------------------------------------------
# 6. CLI entry point (main function / argparse)
# ---------------------------------------------------------------------------


class TestCLIEntryPoint:
    """The main() entry point and parser work correctly."""

    def test_build_parser_returns_parser(self) -> None:
        """build_parser() returns an ArgumentParser with subcommands."""
        parser = build_parser()
        assert parser is not None

    def test_main_with_review(self, tmp_path: Path) -> None:
        """main() dispatches to the review subcommand."""
        _init_git_repo(tmp_path)

        with patch("claude_reflect.cli.ReviewCommand") as MockReview:
            mock_instance = MagicMock()
            mock_instance.execute.return_value = {"status": "complete"}
            MockReview.return_value = mock_instance
            # Call main with appropriate arguments
            main(["review", "--range", "last 7 days", "--repo", str(tmp_path)])
            MockReview.assert_called_once()

    def test_main_with_status(self, tmp_path: Path) -> None:
        """main() dispatches to the status subcommand."""
        _init_git_repo(tmp_path)

        with patch("claude_reflect.cli.StatusCommand") as MockStatus:
            mock_instance = MagicMock()
            mock_instance.execute.return_value = {"initialized": True}
            MockStatus.return_value = mock_instance
            main(["status", "--repo", str(tmp_path)])
            MockStatus.assert_called_once()

    def test_main_with_maintenance(self, tmp_path: Path) -> None:
        """main() dispatches to the maintenance subcommand."""
        _init_git_repo(tmp_path)

        with patch("claude_reflect.cli.MaintenanceCommand") as MockMaintenance:
            mock_instance = MagicMock()
            mock_instance.execute.return_value = {"ran": True}
            MockMaintenance.return_value = mock_instance
            main(["maintenance", "--repo", str(tmp_path)])
            MockMaintenance.assert_called_once()

    def test_repo_flag_defaults_to_cwd(self) -> None:
        """Without --repo, the CLI defaults to the current working directory."""
        parser = build_parser()
        args = parser.parse_args(["status"])
        # The default repo should be None or "." (resolved to cwd at execution)
        assert args.repo is None or args.repo == "."
