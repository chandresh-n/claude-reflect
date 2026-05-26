"""Evaluator agent — thin shim over the staged evaluator pipeline.

The implementation lives in
``claude_reflect.agents.pipeline.orchestrator``; this module preserves
the historical public surface (``evaluate``, ``EvaluatorError``,
``evaluate_from_jsonl``) so callers like the run loop and the CLI do
not have to be rewired.

Spec: docs/spec/03-agents/evaluator.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from claude_reflect.agents.pipeline.orchestrator import evaluate as _orchestrator_evaluate
from claude_reflect.storage.session_logs import Session, SessionLogReader


class EvaluatorError(Exception):
    """Raised when the evaluator pipeline fails to produce valid output."""


def evaluate(
    sessions: List[Session],
    repo: Path,
    model: str = "claude-opus-4-7",
    write_gap_records: bool = True,
    log_dir: Optional[Path] = None,
    **_unused,
) -> dict:
    """Run the staged evaluator pipeline over the given sessions.

    Returns a document with the four spec keys
    (``per_turn_observations``, ``pass_classifications``,
    ``gap_observations``, ``session_narratives``).

    Extra keyword arguments are accepted and ignored so older callers
    that passed pre-pipeline batch knobs do not break at the import
    boundary. The supported runtime knobs are ``model``,
    ``write_gap_records``, and ``log_dir``.
    """
    if not sessions:
        raise EvaluatorError("No sessions provided for evaluation")
    return _orchestrator_evaluate(
        sessions=sessions,
        repo=repo,
        model=model,
        write_gap_records=write_gap_records,
        log_dir=log_dir,
    )


def evaluate_from_jsonl(
    session_paths: List[Path],
    repo: Path,
    model: str = "claude-opus-4-7",
    write_gap_records: bool = True,
) -> dict:
    """Read JSONL session logs from disk and evaluate them."""
    sessions = [SessionLogReader.read_session(p) for p in session_paths]
    return evaluate(
        sessions, repo, model=model, write_gap_records=write_gap_records,
    )
