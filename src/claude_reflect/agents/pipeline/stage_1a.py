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

from claude_reflect.agents._json_parsing import extract_json
from claude_reflect.agents.pipeline.cache import StageCache, cache_key
from claude_reflect.storage.session_logs import Session, Turn

# Bump this string whenever the stage-1a prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1b/2/3/4.
# Bump this string whenever the stage-1a prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching the other stages.
STAGE_1A_PROMPT_VERSION = "v2"

_STAGE_ID = "1a"

STAGE_1A_SYSTEM_PROMPT = """\
<role>
You are the per-turn describer, the first stage of an evaluator pipeline that
reads Claude Code session logs to find recurring inefficiencies in how an AI
coding agent does its work. You are shown exactly ONE turn of one session at a
time. Later stages aggregate many of your descriptions; they never see the raw
turn, only what you write here. The pipeline's signal is therefore only as
faithful as your description of the turn in front of you.
</role>

<task>
Describe what happened in this turn as a single JSON object: what the human
wanted, what the assistant did, how it turned out, and any friction along the
way. Describe what the turn shows — do not judge it, score it, or suggest what
should have been done instead.
</task>

<output_format>
Return one JSON object with every field below present:

- session_id (string): echo the value from the input unchanged.
- turn_index (integer): echo the value from the input unchanged.
- goal_signal (string): what the human appears to want at this turn.
- action_signal (string): what the assistant did this turn.
- outcome_signal (string): exactly one of "completed", "partial", "blocked",
  "tool_failure", "clarification_needed", "agent_continued_without_outcome".
- friction_signal (string, "" when there is none): friction in reaching the
  outcome — retried tool calls, denials, error messages, the human re-asking.
- effort_signal (object): {"input_tokens", "output_tokens", "model"}, copied
  verbatim from the turn's metadata.
- tool_actions (array): one entry per tool call, or one per cluster of similar
  calls. Per call: {"tool", "target", "outcome"} where outcome is
  "ok" | "error" | "denied". Per cluster: {"tool", "count", "targets",
  "outcome", "notes"}.
- evidence_anchors (array of strings): short snippets quoted from the turn's
  text that support your description.
</output_format>

<rules>
- Ground every field in what the turn actually shows. If a detail is not in the
  input, leave the field empty rather than inferring it.
- Produce no scores, grades, confidence values, or rankings. This pipeline has
  no scalar quality axis by design: a score assigned by a model reading a single
  turn drifts toward the mean and misleads the stages that consume it. Use prose.
- Echo session_id and turn_index exactly so later stages can join your output
  back to this turn.
</rules>

<example>
<input>
session_id: sess-3f2a
turn_index: 4
{"human_input": "run the tests", "assistant_response": "Tests pass.",
 "tool_calls": [{"name": "Bash", "input": {"command": "pytest -q"}}],
 "model": "claude-sonnet-4-6", "input_tokens": 1820, "output_tokens": 240}
</input>
<output>
{"session_id": "sess-3f2a", "turn_index": 4,
 "goal_signal": "Run the test suite and report the result.",
 "action_signal": "Ran the suite via Bash and reported it passing.",
 "outcome_signal": "completed", "friction_signal": "",
 "effort_signal": {"input_tokens": 1820, "output_tokens": 240, "model": "claude-sonnet-4-6"},
 "tool_actions": [{"tool": "Bash", "target": "pytest -q", "outcome": "ok"}],
 "evidence_anchors": ["run the tests", "Tests pass."]}
</output>
</example>

Return only the JSON object — no markdown fences, no text before or after it.
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


def _describe_one_safely(
    session_id: str, turn_index: int, turn: Turn,
    runner, repo: Path, model: str,
) -> dict:
    """Per-turn worker. Always returns a dict (never raises) so the
    pool's ``.result()`` calls never throw and per-turn failures are
    isolated. Each call writes to its own cache key on disk; the cache
    is per-content-hash so different turns never collide."""
    try:
        return describe_turn(
            session_id=session_id, turn_index=turn_index,
            turn=turn, runner=runner, repo=repo, model=model,
        )
    except Exception as exc:
        return {
            "_failed": True,
            "session_id": session_id,
            "turn_index": turn_index,
            "error": f"{type(exc).__name__}: {exc}",
        }


def describe_session_turns(
    session: Session,
    runner,
    repo: Path,
    model: str,
    max_concurrent: int = 1,
) -> List[dict]:
    """Describe every turn in a session with per-turn failure isolation.

    Returns a list aligned with ``session.turns``. Each entry is either
    a full description dict or a ``{"_failed": True, ...}`` sentinel.

    Concurrency:
      - ``max_concurrent=1`` (default) preserves the original sequential
        behavior so callers that do not opt into parallelism see no
        behavior change.
      - ``max_concurrent>1`` fans the per-turn calls out to a bounded
        thread pool. The runner is stateless, the cache is keyed per
        turn-content (no write contention), and the return list is
        re-ordered by ``turn_index`` before being returned so the
        downstream pipeline always sees descriptions in temporal
        sequence regardless of completion order.

    A failure on one turn never affects another turn's description.
    """
    turns = list(enumerate(session.turns))
    n = len(turns)
    if n == 0:
        return []

    if max_concurrent <= 1:
        return [
            _describe_one_safely(
                session.session_id, ti, t, runner, repo, model,
            )
            for ti, t in turns
        ]

    # Parallel path. Bound max_workers to the actual workload so we don't
    # spin up idle threads on small sessions.
    from concurrent.futures import ThreadPoolExecutor

    results: List[dict | None] = [None] * n
    workers = min(max_concurrent, n)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                _describe_one_safely,
                session.session_id, ti, t, runner, repo, model,
            ): ti
            for ti, t in turns
        }
        for fut in futures:
            ti = futures[fut]
            # _describe_one_safely never raises; .result() returns a dict.
            results[ti] = fut.result()
    # Drop the None placeholders by reassembling in index order. Order
    # is preserved structurally because we wrote to results[ti].
    return [r for r in results if r is not None]
