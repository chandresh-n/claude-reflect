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
    stage_1a_model: Optional[str] = None,
    max_concurrent_turn_descriptions: int = 1,
    max_concurrent_sessions: int = 1,
    **_unused,
) -> dict:
    """Run the staged evaluator pipeline over the given sessions.

    Returns a document with the four spec keys
    (``per_turn_observations``, ``pass_classifications``,
    ``gap_observations``, ``session_narratives``).

    Args:
        model: Model used for stages 1b/2/3/4. Treated as the default
            for stage 1a too when ``stage_1a_model`` is not supplied.
        stage_1a_model: Optional override for stage 1a (per-turn
            description). Stage 1a runs once per turn so it benefits
            from a smaller, cheaper model when corpus volume is high.

    Extra keyword arguments are accepted and ignored so older callers
    that passed pre-pipeline batch knobs do not break at the import
    boundary.
    """
    if not sessions:
        raise EvaluatorError("No sessions provided for evaluation")
    return _orchestrator_evaluate(
        sessions=sessions,
        repo=repo,
        model=model,
        stage_1a_model=stage_1a_model,
        max_concurrent_turn_descriptions=max_concurrent_turn_descriptions,
        max_concurrent_sessions=max_concurrent_sessions,
        write_gap_records=write_gap_records,
        log_dir=log_dir,
    )


def evaluate_from_jsonl(
    session_paths: List[Path],
    repo: Path,
    model: str = "claude-opus-4-7",
    write_gap_records: bool = True,
    stage_1a_model: Optional[str] = None,
) -> dict:
    """Read JSONL session logs from disk and evaluate them."""
    sessions = [SessionLogReader.read_session(p) for p in session_paths]
    return evaluate(
        sessions, repo, model=model,
        write_gap_records=write_gap_records,
        stage_1a_model=stage_1a_model,
    )
