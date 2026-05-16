"""Stage 1a — per-turn description.

One model call per turn produces a compact structured description used
by stages 1b/2/3 instead of the raw turn text. Output schema (per the
plan, internal to the pipeline, not the spec's evaluator-output):

    session_id, turn_index,
    goal_signal, action_signal, outcome_signal, friction_signal,
    effort_signal (input_tokens, output_tokens, model),
    tool_actions[],
    evidence_anchors[]

``tool_actions`` may be flat (one entry per tool call with target +
outcome) or clustered (one entry per group of similar calls, with
``count`` and ``targets[]``). Clustering is a hint to the model only;
both shapes round-trip through the cache.

Per-turn failure isolation: ``describe_session_turns`` traps exceptions
from one turn's runner invocation and emits a ``{"_failed": True, ...}``
sentinel for that turn while preserving the descriptions of the others.

Spec: docs/spec/03-agents/evaluator.md (the evaluator's behavioural
spec). This stage is an internal pipeline step; its output is not the
external evaluator output.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from meta_harness.agents._json_parsing import extract_json
from meta_harness.agents.pipeline.cache import StageCache, cache_key
from meta_harness.storage.session_logs import Session, Turn

# Bump this string whenever the stage-1a prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1b/2/3/4.
STAGE_1A_PROMPT_VERSION = "v1"

_STAGE_ID = "1a"

STAGE_1A_SYSTEM_PROMPT = """\
You are the per-turn describer in an evaluator pipeline reading a Claude
Code session log. You will be shown ONE turn at a time. Produce a
compact structured description of that turn as a JSON object.

You do not grade, rank, or recommend. You describe what happened.

Required fields (every one must be present):

- session_id (string, echo from input)
- turn_index (integer, echo from input)
- goal_signal (string): what the human appears to want at this turn.
- action_signal (string): what the assistant did this turn.
- outcome_signal (string, one of:
    "completed", "partial", "blocked", "tool_failure",
    "clarification_needed", "agent_continued_without_outcome").
- friction_signal (string, may be empty): any friction observed in
  reaching the outcome (retried tool calls, denials, error messages,
  the human re-asking, etc.).
- effort_signal (object): {input_tokens, output_tokens, model} —
  copied straight from the turn's metadata.
- tool_actions (array): one entry per tool call OR per cluster of
  similar tool calls. Per-call entries: {tool, target, outcome}
  where outcome is "ok" | "error" | "denied". Clustered entries:
  {tool, count, targets, outcome, notes} for groups of similar calls.
- evidence_anchors (array of strings): short anchor snippets quoted from
  the turn's text supporting the description.

Output JSON only. No markdown fences, no preamble prose.
"""

_USER_PROMPT_TEMPLATE = """\
<turn>
session_id: {session_id}
turn_index: {turn_index}
{turn_json}
</turn>

Produce the JSON description as instructed in the system prompt.
"""


def _serialize_turn(turn: Turn) -> dict:
    """Deterministic, JSON-safe view of a Turn for prompts and cache keys."""
    return {
        "timestamp": turn.timestamp.isoformat() if turn.timestamp else None,
        "human_input": turn.human_input,
        "assistant_response": turn.assistant_response,
        "tool_calls": [
            {"name": tc.name, "input": tc.input} for tc in turn.tool_calls
        ],
        "model": turn.model,
        "input_tokens": turn.input_tokens,
        "output_tokens": turn.output_tokens,
    }


def _build_user_prompt(session_id: str, turn_index: int, turn: Turn) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        session_id=session_id,
        turn_index=turn_index,
        turn_json=json.dumps(_serialize_turn(turn), indent=2, default=str),
    )


def _cache_content(session_id: str, turn_index: int, turn: Turn) -> dict:
    return {
        "session_id": session_id,
        "turn_index": turn_index,
        "turn": _serialize_turn(turn),
    }


def describe_turn(
    session_id: str,
    turn_index: int,
    turn: Turn,
    runner,
    repo: Path,
    model: str,
) -> dict:
    """Describe a single turn. Returns the parsed description dict.

    Reads the stage-1a cache first. On hit, returns the cached value
    without invoking the runner. On miss, invokes the runner exactly
    once, parses the JSON response, normalises echoed identifiers, and
    writes the result to the cache before returning it.
    """
    content = _cache_content(session_id, turn_index, turn)
    key = cache_key(
        stage_id=_STAGE_ID,
        model=model,
        prompt_version=STAGE_1A_PROMPT_VERSION,
        content=content,
    )
    cache = StageCache(repo=repo, stage_id=_STAGE_ID)

    cached = cache.get(key)
    if cached is not None:
        return cached

    user_prompt = _build_user_prompt(session_id, turn_index, turn)
    raw = runner.invoke(
        system_prompt=STAGE_1A_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )
    parsed: Any = extract_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError(
            f"stage 1a expected a JSON object, got {type(parsed).__name__}"
        )

    # Force-echo identifiers so callers can trust them even if the model
    # paraphrased or dropped them.
    parsed["session_id"] = session_id
    parsed["turn_index"] = turn_index

    cache.set(key, parsed)
    return parsed


def describe_session_turns(
    session: Session,
    runner,
    repo: Path,
    model: str,
) -> List[dict]:
    """Describe every turn in a session with per-turn failure isolation.

    Returns a list aligned with ``session.turns``. Each entry is either
    a full description dict or a ``{"_failed": True, ...}`` sentinel.
    A failure on one turn does not affect any other turn's description.
    """
    results: List[dict] = []
    for turn_index, turn in enumerate(session.turns):
        try:
            description = describe_turn(
                session_id=session.session_id,
                turn_index=turn_index,
                turn=turn,
                runner=runner,
                repo=repo,
                model=model,
            )
            results.append(description)
        except Exception as exc:
            results.append({
                "_failed": True,
                "session_id": session.session_id,
                "turn_index": turn_index,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return results
