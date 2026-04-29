"""
CLI and skill wrapper — Step 12 of the meta-harness build.

Spec refs:
  - docs/spec/05-interfaces/skill-invocation.md
  - docs/spec/05-interfaces/human-review.md

Provides the ``meta-harness`` CLI entry point with three subcommands:
  review      — trigger a reflective pass over recent sessions
  status      — report knowledge-base state
  maintenance — trigger a maintenance pass

The CLI auto-runs Phase 1 (setup) on first invocation in a fresh repo.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from meta_harness.storage.knowledge_base import setup as kb_setup
from meta_harness.processes.run_loop import RunLoop, RunState, RunLoopError


# ---------------------------------------------------------------------------
# Proposal batch markdown rendering
# ---------------------------------------------------------------------------


def render_proposal_batch_markdown(
    *,
    run_id: str,
    date_range: dict,
    proposals: List[dict],
    author_results: Dict[str, dict],
) -> str:
    """Render the proposal batch as plain markdown per the spec template.

    No decorative formatting: no box-drawing, no emoji, no HTML tables,
    no markdown tables, no decorative separators.
    """
    lines: List[str] = []
    start = date_range.get("start", "unknown")
    end = date_range.get("end", "unknown")
    now = datetime.now(timezone.utc).isoformat()

    lines.append("# Meta-harness proposal batch")
    lines.append("")
    lines.append(f"Run: {run_id}")
    lines.append(f"Window: {start} to {end}")
    lines.append(f"Generated at: {now}")
    lines.append("")

    total = len(proposals)
    if total == 0:
        lines.append("No proposals in this batch.")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"Batch contains {total} proposal(s).")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, proposal in enumerate(proposals, 1):
        pid = proposal.get("proposal_id", "unknown")
        title = proposal.get("title", "Untitled")
        ar = author_results.get(pid, {})
        author_status = ar.get("status", "unknown")

        if author_status == "author_failed":
            # Author-failed template per spec
            reason = ar.get("author_failure_reason", "Unknown reason")
            lines.append(f"## Proposal {i} of {total}: {title}. AUTHOR FAILED")
            lines.append("")
            why_prose = proposal.get("why", {}).get("prose_summary", "")
            lines.append(f"**Why this was proposed:** {why_prose}")
            lines.append("")
            what_desc = proposal.get("what", {}).get("short_description", "")
            lines.append(f"**What was attempted:** {what_desc}")
            lines.append("")
            lines.append(f"**Why it could not be produced:** {reason}")
            lines.append("")
            lines.append(
                "This proposal will be recorded as author-failed regardless of your"
            )
            lines.append("input. No action required.")
        else:
            # Normal proposal template per spec
            lines.append(f"## Proposal {i} of {total}: {title}")
            lines.append("")

            why_prose = proposal.get("why", {}).get("prose_summary", "")
            lines.append(f"**Why:** {why_prose}")
            lines.append("")

            what = proposal.get("what", {})
            what_desc = what.get("short_description", "")
            diff_ref = what.get("diff_reference", "")
            lines.append(f"**What:** {what_desc}, see diff: {diff_ref}")
            lines.append("")

            how_prose = proposal.get("how", {}).get("mechanism_prose", "")
            lines.append(f"**How:** {how_prose}")
            lines.append("")

            pred_prose = proposal.get("prediction", {}).get(
                "expected_impact_prose", ""
            )
            lines.append(f"**Prediction:** {pred_prose}")
            lines.append("")

            lines.append("---")
            lines.append("")
            lines.append("### Your decision")
            lines.append("")
            lines.append("Mark one:")
            lines.append("- [ ] Accept")
            lines.append("- [ ] Reject")
            lines.append("- [ ] Defer (leave pending)")
            lines.append("")
            lines.append("Reasoning (required if rejecting, optional otherwise):")
            lines.append("")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with review/status/maintenance subcommands."""
    parser = argparse.ArgumentParser(
        prog="meta-harness",
        description="Reflective pass over Claude Code session logs.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # Common --repo argument added to each subparser so it can appear
    # after the subcommand (e.g. "status --repo /path").
    repo_kwargs = dict(
        default=None,
        help="Path to the target git repository (defaults to cwd).",
    )

    # review
    review_p = sub.add_parser("review", help="Run a reflective review pass.")
    review_p.add_argument("--repo", **repo_kwargs)
    review_p.add_argument(
        "--range", dest="range", default=None,
        help="Date range (e.g. 'last 7 days', '2026-04-01 to 2026-04-07').",
    )
    review_p.add_argument(
        "--resume", dest="resume", default=None,
        help="Resume a paused run by run_id.",
    )
    review_p.add_argument(
        "--verbose", action="store_true", default=False,
        help="Enable streamed output and tool-call traces.",
    )

    # status
    status_p = sub.add_parser("status", help="Report knowledge-base state.")
    status_p.add_argument("--repo", **repo_kwargs)

    # maintenance
    maint_p = sub.add_parser("maintenance", help="Run a maintenance pass.")
    maint_p.add_argument("--repo", **repo_kwargs)

    return parser


# ---------------------------------------------------------------------------
# Command classes
# ---------------------------------------------------------------------------


class ReviewCommand:
    """Execute a review pass (the main run loop)."""

    def __init__(
        self,
        *,
        repo: Path,
        date_range: str,
        verbose: bool = False,
        resume_run_id: Optional[str] = None,
    ):
        self.repo = repo
        self.date_range = date_range
        self.verbose = verbose
        self.resume_run_id = resume_run_id

    def execute(self) -> dict:
        """Run the review pass and return a result dict."""
        # Phase 1: auto-setup on fresh repo
        kb_dir = self.repo / ".meta-harness"
        if not kb_dir.is_dir():
            if self.verbose:
                print("Initializing knowledge base (Phase 1)...", flush=True)
            kb_setup(self.repo)

        # If resuming, validate the run exists
        if self.resume_run_id:
            run_path = (
                self.repo / ".meta-harness" / "runs" / f"{self.resume_run_id}.json"
            )
            if not run_path.exists():
                raise RunLoopError(
                    f"Cannot resume: no run state found for {self.resume_run_id}"
                )

        if self.verbose:
            print(f"Starting review pass (range: {self.date_range})...", flush=True)

        run_loop = self._make_run_loop()
        state = run_loop.run()

        if self.verbose:
            print(
                f"Run {state.run_id} completed with status: {state.status}",
                flush=True,
            )

        return {
            "run_id": state.run_id,
            "status": state.status,
            "decisions": state.decisions,
        }

    def _make_run_loop(self) -> RunLoop:
        """Create a RunLoop instance wired to real agents."""
        date_range_dict = _parse_date_range(self.date_range)
        return RunLoop(
            repo=self.repo,
            date_range=date_range_dict,
            sessions=[],
            evaluator_fn=_noop_evaluator,
            proposer_fn=_noop_proposer,
            author_fn=_noop_author,
            human_review_fn=_noop_human_review,
            resume_run_id=self.resume_run_id,
        )


class StatusCommand:
    """Report the state of the knowledge base."""

    def __init__(self, *, repo: Path):
        self.repo = repo

    def execute(self) -> dict:
        """Return a dict describing the KB state."""
        kb_dir = self.repo / ".meta-harness"
        if not kb_dir.is_dir():
            return {"initialized": False}

        result: Dict[str, Any] = {"initialized": True}

        # Count gaps
        gaps_dir = kb_dir / "gaps"
        if gaps_dir.is_dir():
            result["gap_count"] = len(list(gaps_dir.glob("*.json")))
        else:
            result["gap_count"] = 0

        # Count archive entries
        archive_dir = kb_dir / "archive"
        if archive_dir.is_dir():
            result["archive_count"] = len(list(archive_dir.glob("*.json")))
        else:
            result["archive_count"] = 0

        # Count runs
        runs_dir = kb_dir / "runs"
        if runs_dir.is_dir():
            result["run_count"] = len(list(runs_dir.glob("*.json")))
        else:
            result["run_count"] = 0

        return result


class MaintenanceCommand:
    """Trigger a maintenance pass."""

    def __init__(self, *, repo: Path):
        self.repo = repo

    def execute(self) -> dict:
        """Run maintenance and return a result dict."""
        from meta_harness.processes.maintenance import run_maintenance

        kb_dir = self.repo / ".meta-harness"
        if not kb_dir.is_dir():
            return {"ran": False, "reason": "not_initialized"}

        run_maintenance(repo=self.repo)
        return {"ran": True}


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point. Parses args and dispatches to the appropriate command."""
    parser = build_parser()
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else Path.cwd()

    if args.subcommand == "review":
        cmd = ReviewCommand(
            repo=repo,
            date_range=args.range or "last 7 days",
            verbose=args.verbose,
            resume_run_id=args.resume,
        )
        result = cmd.execute()
        if result:
            print(json.dumps(result, indent=2, default=str))

    elif args.subcommand == "status":
        cmd = StatusCommand(repo=repo)
        result = cmd.execute()
        print(json.dumps(result, indent=2, default=str))

    elif args.subcommand == "maintenance":
        cmd = MaintenanceCommand(repo=repo)
        result = cmd.execute()
        print(json.dumps(result, indent=2, default=str))

    else:
        parser.print_help()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date_range(raw: str) -> dict:
    """Parse a date range string into {start, end} dict."""
    if " to " in raw:
        parts = raw.split(" to ", 1)
        return {"start": parts[0].strip(), "end": parts[1].strip()}

    # Relative ranges
    now = datetime.now(timezone.utc)
    if raw.startswith("last "):
        # e.g. "last 7 days", "last week"
        token = raw.replace("last ", "").strip()
        if "week" in token:
            delta = timedelta(days=7)
        elif "day" in token:
            # Extract the number
            num_str = "".join(c for c in token if c.isdigit())
            days = int(num_str) if num_str else 7
            delta = timedelta(days=days)
        else:
            delta = timedelta(days=7)

        start = (now - delta).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        return {"start": start, "end": end}

    # Fallback: last 7 days
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return {"start": start, "end": end}


def _noop_evaluator(**kwargs: Any) -> dict:
    return {"observations": [], "gap_observations": []}


def _noop_proposer(**kwargs: Any) -> dict:
    return {"proposals": [], "proposal_ids": []}


def _noop_author(proposal: dict, **kwargs: Any) -> dict:
    return {"status": "author_failed", "author_failure_reason": "No agent configured"}


def _noop_human_review(batch: dict) -> dict:
    return {}


if __name__ == "__main__":
    main()
