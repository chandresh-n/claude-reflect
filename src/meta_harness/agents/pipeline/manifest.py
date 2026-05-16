"""Deterministic session manifest.

Builds a compact, model-free orientation record for one session that
downstream pipeline stages reference: turn count, duration, tool-call
distribution, first/last human-input excerpts. No LLM call — purely
derived from the parsed JSONL.
"""
from __future__ import annotations

from typing import Dict, List

from meta_harness.storage.session_logs import Session

_EXCERPT_MAX_CHARS = 200
_EXCERPT_COUNT = 3


def _excerpt(text: str | None) -> str:
    if not text:
        return ""
    if len(text) <= _EXCERPT_MAX_CHARS:
        return text
    return text[:_EXCERPT_MAX_CHARS]


def build_session_manifest(session: Session) -> dict:
    """Return a deterministic, model-free orientation manifest.

    Same ``Session`` in → byte-identical dict out (JSON-canonicalised).
    """
    turns = session.turns
    turn_count = len(turns)

    if turn_count > 0:
        duration_seconds = int(
            (session.end_time - session.start_time).total_seconds()
        )
    else:
        duration_seconds = 0

    tool_call_counts: Dict[str, int] = {}
    for turn in turns:
        for tc in turn.tool_calls:
            tool_call_counts[tc.name] = tool_call_counts.get(tc.name, 0) + 1
    tool_call_counts = dict(sorted(tool_call_counts.items()))

    first_turns = turns[:_EXCERPT_COUNT]
    last_turns = turns[-_EXCERPT_COUNT:] if turn_count > 0 else []

    first_turn_excerpts: List[str] = [_excerpt(t.human_input) for t in first_turns]
    last_turn_excerpts: List[str] = [_excerpt(t.human_input) for t in last_turns]

    return {
        "session_id": session.session_id,
        "turn_count": turn_count,
        "duration_seconds": duration_seconds,
        "tool_call_counts": tool_call_counts,
        "first_turn_excerpts": first_turn_excerpts,
        "last_turn_excerpts": last_turn_excerpts,
    }
