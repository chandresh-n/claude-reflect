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
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from meta_harness.storage.knowledge_base import setup as kb_setup
from meta_harness.storage.session_logs import SessionLogReader
from meta_harness.agents.evaluator import evaluate, EvaluatorError
from meta_harness.agents.proposer import propose, ProposerError
from meta_harness.agents.author import author as author_agent, AuthorError
from meta_harness.agents.claude_runner import ClaudeRunnerError
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
        "--session_id", dest="session_ids", action="append", default=None,
        help=(
            "Pick a specific session by id (repeatable). "
            "Mutually exclusive with --range."
        ),
    )
    review_p.add_argument(
        "--pick", dest="pick", action="store_true", default=False,
        help=(
            "After resolving --range, present an interactive picker so you "
            "can select which sessions to include. Requires a TTY."
        ),
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
        session_ids: Optional[List[str]] = None,
        pick: bool = False,
    ):
        self.repo = repo
        self.date_range = date_range
        self.verbose = verbose
        self.resume_run_id = resume_run_id
        self.session_ids = session_ids
        self.pick = pick

    def execute(self) -> dict:
        """Run the review pass and return a result dict."""
        # Phase 1: auto-setup on fresh repo
        kb_dir = self.repo / ".meta-harness"
        if not kb_dir.is_dir():
            self._log("Initializing knowledge base (Phase 1)...")
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

        # Load config for model choices
        config = _load_config(self.repo)

        # Collect sessions: either by explicit --session_id list, or by --range.
        if self.session_ids:
            self._log(
                f"Starting review pass (session_ids: {', '.join(self.session_ids)})..."
            )
            sessions = _collect_sessions_by_id(
                self.repo, self.session_ids, verbose=self.verbose
            )
            date_range_dict = _date_range_from_sessions(sessions)
        else:
            self._log(f"Starting review pass (range: {self.date_range})...")
            date_range_dict = _parse_date_range(self.date_range)
            sessions = _collect_sessions(
                self.repo, date_range_dict, verbose=self.verbose
            )

            if self.pick:
                if not sessions:
                    self._log("No sessions in range to pick from.")
                else:
                    sessions = _present_session_picker(sessions)
                    # Narrow the recorded window to the chosen sessions so the
                    # proposal batch markdown reflects what was actually used.
                    narrowed = _date_range_from_sessions(sessions)
                    if narrowed["start"] != "unknown":
                        date_range_dict = narrowed

        if not sessions and not self.resume_run_id:
            if self.session_ids:
                self._log(
                    "No matching sessions found for the given --session_id value(s)."
                )
            else:
                self._log(
                    f"No sessions found in range {date_range_dict['start']} "
                    f"to {date_range_dict['end']}."
                )
            self._log("Hint: session logs are read from ~/.claude/projects/")
            # Still run the loop so state is tracked, but with empty sessions
            # the evaluator will be skipped gracefully

        self._log(f"Found {len(sessions)} session(s) selected.")

        # Build agent wrappers that use the real implementations
        evaluator_model = config.get("models", {}).get("evaluator", "claude-opus-4-6")
        proposer_model = config.get("models", {}).get("proposer", "claude-opus-4-6")
        author_model = config.get("models", {}).get("author", "claude-sonnet-4-6")
        verbose = self.verbose
        repo = self.repo

        _empty_eval = {"per_turn_observations": [], "pass_classifications": [], "gap_observations": [], "session_narratives": []}

        def real_evaluator(sessions, repo, **kwargs):
            if not sessions:
                self._log("No sessions to evaluate — skipping evaluator.")
                return _empty_eval
            self._log(
                f"Running evaluator on {len(sessions)} session(s) "
                f"(model: {evaluator_model})..."
            )
            try:
                result = evaluate(
                    sessions,
                    repo,
                    model=evaluator_model,
                )
                gaps = result.get("gap_observations", [])
                self._log(f"Evaluator found {len(gaps)} gap observation(s).")
                return result
            except EvaluatorError as e:
                self._log(f"Evaluator error: {e}")
                self._log(
                    "Partial batch results were saved under "
                    ".meta-harness/eval-cache/<hash>/; re-run the same "
                    "review command to retry only the failed batches."
                )
                return _empty_eval
            except ClaudeRunnerError as e:
                self._log(f"Evaluator failed (Claude runner): {e}")
                return _empty_eval
            except Exception as e:
                self._log(f"Evaluator failed: {e}")
                return _empty_eval

        def real_proposer(eval_output, repo, date_range, **kwargs):
            # Skip proposer if evaluator produced nothing meaningful
            obs = eval_output.get("gap_observations", [])
            narratives = eval_output.get("session_narratives", [])
            if not obs and not narratives:
                self._log("No evaluator observations — skipping proposer.")
                return {"proposals": [], "proposal_ids": []}
            fn_config = config.get("forced_novelty", {})
            self._log(f"Running proposer (model: {proposer_model})...")
            try:
                result = propose(
                    evaluator_output=eval_output,
                    repo=repo,
                    window=date_range,
                    model=proposer_model,
                    forced_novelty_probability=fn_config.get("probability", 0.20),
                    null_baseline_probability=fn_config.get("null_baseline_probability", 0.01),
                )
                count = len(result.get("proposals", []))
                self._log(f"Proposer generated {count} proposal(s).")
                return result
            except ProposerError as e:
                self._log(f"Proposer error: {e}")
                return {"proposals": [], "proposal_ids": []}

        def real_author(proposal, repo, **kwargs):
            pid = proposal.get("proposal_id", "unknown")
            self._log(f"Running author for proposal {pid} (model: {author_model})...")
            try:
                result = author_agent(proposal, repo, model=author_model)
                self._log(f"  Author result: {result.get('status')}")
                return result
            except AuthorError as e:
                self._log(f"  Author error for {pid}: {e}")
                return {"status": "author_failed", "author_failure_reason": str(e)}

        def real_human_review(batch):
            return _human_review_via_markdown(batch, repo, date_range_dict, verbose=verbose)

        self._real_evaluator = real_evaluator
        self._real_proposer = real_proposer
        self._real_author = real_author
        self._real_human_review = real_human_review
        self._collected_sessions = sessions
        self._date_range_dict = date_range_dict

        run_loop = self._make_run_loop()
        state = run_loop.run()

        self._log(f"Run {state.run_id} completed with status: {state.status}")

        return {
            "run_id": state.run_id,
            "status": state.status,
            "decisions": state.decisions,
        }

    def _make_run_loop(self) -> RunLoop:
        """Create a RunLoop instance wired to agents.

        Extracted as a method so tests can mock it to inject canned agents.
        """
        return RunLoop(
            repo=self.repo,
            date_range=self._date_range_dict,
            sessions=self._collected_sessions,
            evaluator_fn=self._real_evaluator,
            proposer_fn=self._real_proposer,
            author_fn=self._real_author,
            human_review_fn=self._real_human_review,
            resume_run_id=self.resume_run_id,
        )

    def _log(self, msg: str) -> None:
        """Print a status message to stderr (always visible, doesn't pollute JSON stdout)."""
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)
        else:
            print(msg, file=sys.stderr, flush=True)


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
        # --session_id and --range are mutually exclusive: one names specific
        # sessions, the other names a window. Mixing them is ambiguous.
        if args.session_ids and args.range:
            parser.error("--session_id and --range cannot be used together")
        if args.session_ids and args.pick:
            parser.error("--pick only applies when selecting by --range")

        cmd = ReviewCommand(
            repo=repo,
            date_range=args.range or "last 7 days",
            verbose=args.verbose,
            resume_run_id=args.resume,
            session_ids=args.session_ids,
            pick=args.pick,
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


def _load_config(repo: Path) -> dict:
    """Load the meta-harness config.yaml, returning defaults if missing."""
    config_path = repo / ".meta-harness" / "config.yaml"
    if config_path.exists():
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {}


def _find_session_log_dir(repo: Path) -> Optional[Path]:
    """Discover the Claude Code session log directory for the given repo.

    Claude Code stores sessions under ~/.claude/projects/<slug>/ where
    <slug> is the repo path with / replaced by -. Claude Code may also
    normalize directory names (e.g., underscores to hyphens).
    """
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.is_dir():
        return None

    # Build the slug Claude Code uses: absolute path with / replaced by -
    repo_abs = str(repo.resolve())
    slug = repo_abs.replace("/", "-")

    candidate = claude_dir / slug
    if candidate.is_dir():
        return candidate

    # Try with underscores replaced by hyphens (Claude Code normalization)
    slug_normalized = slug.replace("_", "-")
    candidate = claude_dir / slug_normalized
    if candidate.is_dir():
        return candidate

    # Fallback: scan for directories whose name contains the repo directory name
    # Try both the original name and hyphenated variant
    repo_name = repo.name
    repo_name_hyphenated = repo_name.replace("_", "-")
    for entry in sorted(claude_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir():
            continue
        entry_name = entry.name
        if repo_name in entry_name or repo_name_hyphenated in entry_name:
            # Check it has JSONL session files (not just subagent dirs)
            if list(entry.glob("*.jsonl")):
                return entry

    return None


def _collect_sessions(repo: Path, date_range: dict, verbose: bool = False) -> list:
    """Collect Claude Code sessions in the given date range."""
    session_dir = _find_session_log_dir(repo)
    if session_dir is None:
        if verbose:
            print(
                f"Could not find Claude Code session logs for {repo}",
                file=sys.stderr,
                flush=True,
            )
        return []

    if verbose:
        print(f"Reading sessions from: {session_dir}", file=sys.stderr, flush=True)

    reader = SessionLogReader(session_dir)

    start_str = date_range.get("start", "")
    end_str = date_range.get("end", "")
    try:
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)
    except (ValueError, TypeError):
        # If parsing fails, return all sessions
        return reader.list_all_sessions()

    sessions = reader.sessions_in_range(start_date, end_date)
    return sessions


def _collect_sessions_by_id(
    repo: Path, session_ids: List[str], verbose: bool = False
) -> list:
    """Collect Claude Code sessions whose id matches one of `session_ids`.

    Tries a direct `<session_id>.jsonl` filename match first (Claude Code's
    on-disk convention); falls back to scanning every session's parsed
    `session_id` field. Missing ids are reported to stderr but do not raise.
    """
    session_dir = _find_session_log_dir(repo)
    if session_dir is None:
        if verbose:
            print(
                f"Could not find Claude Code session logs for {repo}",
                file=sys.stderr,
                flush=True,
            )
        return []

    reader = SessionLogReader(session_dir)
    found = []
    missing: List[str] = []
    scanned_cache: Optional[list] = None

    for sid in session_ids:
        candidate = session_dir / f"{sid}.jsonl"
        if candidate.exists():
            found.append(reader.read_session(candidate))
            continue
        if scanned_cache is None:
            scanned_cache = reader.list_all_sessions()
        match = next((s for s in scanned_cache if s.session_id == sid), None)
        if match is not None:
            found.append(match)
        else:
            missing.append(sid)

    for sid in missing:
        print(f"Warning: session_id {sid} not found.", file=sys.stderr, flush=True)

    return found


def _read_session_cwd(path: Path) -> Optional[str]:
    """Peek the JSONL session log for the first `cwd` field.

    Claude Code records the working directory on each log line; the first one
    is good enough to display. Returns None if the file can't be read or no
    `cwd` is present.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = obj.get("cwd")
                if cwd:
                    return cwd
    except OSError:
        return None
    return None


def _date_range_from_sessions(sessions: list) -> dict:
    """Derive a `{start, end}` dict from a list of Session objects.

    Returns `{"start": "unknown", "end": "unknown"}` if the list is empty.
    """
    if not sessions:
        return {"start": "unknown", "end": "unknown"}
    starts = [s.start_time for s in sessions if s.start_time is not None]
    ends = [s.end_time for s in sessions if s.end_time is not None]
    if not starts or not ends:
        return {"start": "unknown", "end": "unknown"}
    return {
        "start": min(starts).date().isoformat(),
        "end": max(ends).date().isoformat(),
    }


def _format_duration(delta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    hours, mins = divmod(total // 60, 60)
    return f"{hours}h{mins:02d}m"


def _parse_picker_selection(
    raw: str, n: int
) -> List[int]:
    """Parse the picker's selection string into a sorted list of 1-based indices.

    Accepts: "all" / empty → every index; comma-separated tokens, each of
    which is either a single integer or an `a-b` range. Out-of-range and
    non-numeric tokens are silently dropped.
    """
    cleaned = raw.strip().lower()
    if cleaned == "" or cleaned == "all":
        return list(range(1, n + 1))

    selected = set()
    for token in cleaned.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                continue
            for i in range(min(lo, hi), max(lo, hi) + 1):
                if 1 <= i <= n:
                    selected.add(i)
        else:
            try:
                i = int(token)
            except ValueError:
                continue
            if 1 <= i <= n:
                selected.add(i)
    return sorted(selected)


def _present_session_picker(sessions: list) -> list:
    """Show the user a numbered list of sessions and let them choose a subset.

    Requires an interactive TTY on stdin. If stdin is not a TTY, prints a
    clear error and returns the unfiltered list (caller already validated
    --pick was passed; we don't want to silently drop sessions on misuse).
    """
    if not sys.stdin.isatty():
        print(
            "--pick requires an interactive terminal (stdin is not a TTY); "
            "proceeding with all sessions in range.",
            file=sys.stderr,
            flush=True,
        )
        return sessions

    print("", file=sys.stderr, flush=True)
    print("Sessions in range:", file=sys.stderr, flush=True)
    print("", file=sys.stderr, flush=True)

    for i, s in enumerate(sessions, 1):
        sid_short = s.session_id[:8] if s.session_id else "(no id)"
        date_str = (
            s.start_time.strftime("%Y-%m-%d %H:%M")
            if s.start_time is not None else "(no timestamp)"
        )
        duration = (
            _format_duration(s.end_time - s.start_time)
            if s.start_time and s.end_time and s.end_time >= s.start_time
            else "?"
        )
        n_turns = len(s.turns)
        n_compactions = len(s.compaction_events)
        cwd = _read_session_cwd(s.file_path) or "(unknown folder)"

        first_input = ""
        for t in s.turns:
            if t.human_input:
                first_input = " ".join(t.human_input.split())
                if len(first_input) > 70:
                    first_input = first_input[:67] + "..."
                break

        print(
            f"  [{i:>3}] {sid_short}  {date_str}  {duration:>6}  "
            f"{n_turns:>3} turns  {n_compactions} compactions",
            file=sys.stderr,
            flush=True,
        )
        print(f"        folder: {cwd}", file=sys.stderr, flush=True)
        if first_input:
            print(f'        first: "{first_input}"', file=sys.stderr, flush=True)

    print("", file=sys.stderr, flush=True)
    print(
        "Select sessions: indices (e.g. '1,3,5'), ranges (e.g. '1-3'), "
        "'all', or blank for all.",
        file=sys.stderr,
        flush=True,
    )

    try:
        raw = input("> ")
    except EOFError:
        raw = ""

    indices = _parse_picker_selection(raw, len(sessions))
    if not indices:
        print(
            "No valid selection parsed; defaulting to all sessions.",
            file=sys.stderr,
            flush=True,
        )
        return sessions

    chosen = [sessions[i - 1] for i in indices]
    print(
        f"Selected {len(chosen)} of {len(sessions)} session(s).",
        file=sys.stderr,
        flush=True,
    )
    return chosen


def _human_review_via_markdown(
    batch: dict,
    repo: Path,
    date_range: dict,
    verbose: bool = False,
) -> dict:
    """Present the proposal batch as markdown and collect human decisions.

    Writes the batch to a temp file, opens $EDITOR (or prints to stdout),
    then parses the human's checkbox markings.
    """
    proposals = batch.get("proposals", [])
    if not proposals:
        return {}

    # Build author_results from the batch for rendering
    author_results: Dict[str, dict] = {}
    for proposal in proposals:
        pid = proposal.get("proposal_id", "")
        if proposal.get("_author_failed"):
            author_results[pid] = {
                "status": "author_failed",
                "author_failure_reason": proposal.get("_author_failure_reason", ""),
            }
        else:
            author_results[pid] = {"status": "success"}

    run_id = batch.get("run_id", "unknown")
    md_content = render_proposal_batch_markdown(
        run_id=run_id,
        date_range=date_range,
        proposals=proposals,
        author_results=author_results,
    )

    # Show diffs in terminal for proposals with successful authoring
    for proposal in proposals:
        pid = proposal.get("proposal_id", "")
        what = proposal.get("what", {})
        diff_ref = what.get("diff_reference")
        if diff_ref and not proposal.get("_author_failed"):
            branch = f"meta-harness/proposal/{pid}"
            print(f"\n--- Diff for proposal {pid}: {proposal.get('title', '')} ---", file=sys.stderr, flush=True)
            try:
                result = subprocess.run(
                    ["git", "diff", f"HEAD...{branch}"],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                )
                if result.stdout:
                    print(result.stdout, file=sys.stderr, flush=True)
                else:
                    print("  (no diff available)", file=sys.stderr, flush=True)
            except Exception:
                print("  (could not show diff)", file=sys.stderr, flush=True)

    # Write markdown to a temp file and let the human edit it
    batch_dir = repo / ".meta-harness" / "runs"
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_path = batch_dir / f"{run_id}-batch.md"
    batch_path.write_text(md_content, encoding="utf-8")

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))

    if editor and sys.stdin.isatty():
        print(
            f"\nOpening proposal batch for review: {batch_path}",
            file=sys.stderr,
            flush=True,
        )
        print(
            "Mark your decisions (Accept/Reject/Defer), save, and close the editor.",
            file=sys.stderr,
            flush=True,
        )
        subprocess.run([editor, str(batch_path)])
    else:
        # No editor or non-interactive — print to stderr and ask for input
        print("\n" + md_content, file=sys.stderr, flush=True)
        print(
            f"\nBatch saved to: {batch_path}",
            file=sys.stderr,
            flush=True,
        )
        print(
            "Edit this file to mark your decisions, then re-run with --resume.",
            file=sys.stderr,
            flush=True,
        )
        # Return all proposals as pending (human hasn't decided yet)
        return {p.get("proposal_id", ""): "pending" for p in proposals}

    # Parse decisions from the edited markdown
    edited = batch_path.read_text(encoding="utf-8")
    decisions = _parse_markdown_decisions(edited, proposals)
    return decisions


def _parse_markdown_decisions(
    markdown: str, proposals: List[dict]
) -> Dict[str, str]:
    """Parse human decisions from the edited proposal batch markdown.

    Looks for checked checkboxes:
      - [x] Accept  → accepted
      - [x] Reject  → rejected
      - [x] Defer   → pending
    Unmarked proposals are treated as pending (implicitly deferred).
    """
    decisions: Dict[str, str] = {}

    # Split by proposal sections
    sections = re.split(r"^## Proposal \d+ of \d+:", markdown, flags=re.MULTILINE)

    for i, proposal in enumerate(proposals):
        pid = proposal.get("proposal_id", "")

        # Author-failed proposals always get author_failed
        if proposal.get("_author_failed"):
            decisions[pid] = "author_failed"
            continue

        # Find the matching section (sections[0] is the header, so +1)
        section_idx = i + 1
        if section_idx >= len(sections):
            decisions[pid] = "pending"
            continue

        section = sections[section_idx]

        # Look for checked checkboxes
        if re.search(r"- \[x\]\s*Accept", section, re.IGNORECASE):
            decisions[pid] = "accepted"
        elif re.search(r"- \[x\]\s*Reject", section, re.IGNORECASE):
            decisions[pid] = "rejected"
        elif re.search(r"- \[x\]\s*Defer", section, re.IGNORECASE):
            decisions[pid] = "pending"
        else:
            # No checkbox marked — implicit defer
            decisions[pid] = "pending"

    return decisions


if __name__ == "__main__":
    main()
