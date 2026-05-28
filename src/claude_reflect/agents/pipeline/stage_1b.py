"""Stage 1b — windowed per-turn observations + draft pass classifications.

Stage 1b consumes the stage 1a descriptions for a single session,
slices them into windows with a configurable overlap, and asks the
model to produce, per window:

  - per_turn_observations (spec schema from
    docs/spec/01-data-structures/evaluator-output.md)
  - draft pass_classifications (spec schema)

Window defaults: ``window_size=25`` turns, ``overlap=5`` turns. These
match the fixture shape pinned by the step-14 gate; tune them in
``observe_session_windows`` call sites if needed.

Per-window failure isolation: one window's runner exception does not
prevent other windows in the same session from being observed. When
any window fails, the per-session output carries
``partial_completion=True`` for stage 3 to propagate onto the
session_narrative.

Spec: docs/spec/03-agents/evaluator.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from claude_reflect.agents._json_parsing import extract_json
from claude_reflect.agents.pipeline.cache import StageCache, cache_key

# Bump this string whenever the stage-1b prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/2/3/4.
STAGE_1B_PROMPT_VERSION = "v2"

_STAGE_ID = "1b"

DEFAULT_WINDOW_SIZE = 25
DEFAULT_OVERLAP = 5

STAGE_1B_SYSTEM_PROMPT = """\
<role>
You are the windowed observer, the second stage of an evaluator pipeline that
reads Claude Code session logs to surface recurring inefficiencies in how an AI
coding agent works. You receive a WINDOW of consecutive per-turn descriptions
(produced by stage 1a) from ONE session, in turn order. You turn them into
structured per-turn observations and a first draft of how the window's turns
group into passes. A pass is a contiguous run of turns working toward the same
sub-goal.
</role>

<task>
For the window you are given: (1) write one observation per turn, grounded in
that turn's stage-1a description, and (2) draft the pass classifications that
cover the window. Describe what happened; when classifying a pass, reason about
what the harness was missing — not about whether the human or the assistant
performed well.
</task>

<output_format>
Return one JSON object with exactly two fields.

1. per_turn_observations: an array, one object per turn in the window:
   - session_id (string): echo from input.
   - turn_index (integer): echo from input.
   - assessment (string): prose describing what happened at this turn,
     grounded in the stage-1a description. Descriptive, not judgmental.
   - effort_signal (object): {"tokens_used" (int), "model" (string),
     "context_occupancy" (int or null), "tool_calls" (array)}. Compute
     tokens_used as input_tokens + output_tokens from the stage-1a
     effort_signal. tool_calls summarises tools as {"name", "count"} entries
     (empty array when there were no tools).
   - flags (array of strings): zero or more of "hard_gate_failure",
     "pass_start", "pass_end", or another event flag the description warrants
     (empty array is fine).
   - tool_verifications (array): always an empty array here — this stage has
     no tools to independently re-run the turn's claims.

2. draft_pass_classifications: an array of pass objects covering the window:
   - session_id (string): echo from input.
   - turn_range (array of two integers [start, end], inclusive).
   - pass_type: one of "successful_one_shot", "refinement", "clarification",
     "correction", "retry".
   - harness_gap_rationale (string): what the harness could have done
     differently to prevent or shorten this pass.
   - contributing_gaps (array of gap-identifier strings, or null). Use null
     only for pass_type "successful_one_shot" or "refinement".
</output_format>

<rules>
- Ground each assessment in the stage-1a description for that turn; do not
  invent activity the descriptions do not show.
- Classify each pass through one lens — "what was the harness missing?":
  "clarification" means the harness could have disambiguated the request;
  "correction" means its understanding of the task was wrong; "retry" means the
  output was too poor to even correct.
- Produce no scores, grades, confidence values, or priority ratings. The
  pipeline has no scalar quality axis on purpose: such scores drift over long
  runs, so the downstream proposer reasons over concrete evidence instead.
- Echo session_id and turn_index exactly so later stages can join back to the
  turns. Adjacent windows overlap by design, so your drafts may overlap or
  disagree at the seams with neighbouring windows — that is expected; stage 2
  reconciles them. Classify this window on its own; do not try to be globally
  consistent.
</rules>

<example>
<input>
session_id: sess-9c1
window_index: 0
descriptions: [
  {"turn_index": 0, "goal_signal": "Find where retries are configured",
   "action_signal": "Grepped for 'retry' and opened config.py", "outcome_signal": "completed",
   "effort_signal": {"input_tokens": 900, "output_tokens": 120, "model": "claude-opus-4-7"},
   "tool_actions": [{"tool": "Grep", "target": "retry", "outcome": "ok"}]},
  {"turn_index": 1, "goal_signal": "Raise the retry limit to 5",
   "action_signal": "Edited config.py then re-ran the failing test, which passed",
   "outcome_signal": "completed", "friction_signal": "",
   "effort_signal": {"input_tokens": 1400, "output_tokens": 300, "model": "claude-opus-4-7"},
   "tool_actions": [{"tool": "Edit", "target": "config.py", "outcome": "ok"}]}
]
</input>
<output>
{"per_turn_observations": [
  {"session_id": "sess-9c1", "turn_index": 0,
   "assessment": "Located the retry configuration by grepping and opening config.py.",
   "effort_signal": {"tokens_used": 1020, "model": "claude-opus-4-7", "context_occupancy": null,
     "tool_calls": [{"name": "Grep", "count": 1}]},
   "flags": ["pass_start"], "tool_verifications": []},
  {"session_id": "sess-9c1", "turn_index": 1,
   "assessment": "Raised the retry limit in config.py; the previously failing test then passed.",
   "effort_signal": {"tokens_used": 1700, "model": "claude-opus-4-7", "context_occupancy": null,
     "tool_calls": [{"name": "Edit", "count": 1}]},
   "flags": ["pass_end"], "tool_verifications": []}
 ],
 "draft_pass_classifications": [
  {"session_id": "sess-9c1", "turn_range": [0, 1], "pass_type": "successful_one_shot",
   "harness_gap_rationale": "None evident; the request was located and resolved without detours.",
   "contributing_gaps": null}
 ]}
</output>
</example>

Return only the JSON object — no markdown fences, no preamble.
"""

_USER_PROMPT_TEMPLATE = """\
<window>
session_id: {session_id}
window_index: {window_index}
turn_count_in_window: {turn_count}
descriptions:
{descriptions_json}
</window>

Produce the JSON object as instructed in the system prompt.
"""


def _build_user_prompt(session_id: str, window_index: int,
                       descriptions: list[dict]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        session_id=session_id,
        window_index=window_index,
        turn_count=len(descriptions),
        descriptions_json=json.dumps(descriptions, indent=2, default=str,
                                     sort_keys=True),
    )


def _cache_content(session_id: str, window_index: int,
                   descriptions: list[dict]) -> dict:
    return {
        "session_id": session_id,
        "window_index": window_index,
        "descriptions": descriptions,
    }


def _normalise_window_output(session_id: str, parsed: Any) -> dict:
    """Coerce the model's parsed JSON into the expected window shape.

    Force-echoes ``session_id`` on every per_turn_observation and every
    draft pass_classification so downstream stages can trust it.
    """
    if not isinstance(parsed, dict):
        raise ValueError(
            f"stage 1b expected a JSON object, got {type(parsed).__name__}"
        )
    observations = parsed.get("per_turn_observations") or []
    drafts = parsed.get("draft_pass_classifications") or []
    if not isinstance(observations, list):
        raise ValueError(
            "stage 1b per_turn_observations must be an array, got "
            f"{type(observations).__name__}"
        )
    if not isinstance(drafts, list):
        raise ValueError(
            "stage 1b draft_pass_classifications must be an array, got "
            f"{type(drafts).__name__}"
        )
    for obs in observations:
        if isinstance(obs, dict):
            obs["session_id"] = session_id
    for draft in drafts:
        if isinstance(draft, dict):
            draft["session_id"] = session_id
    return {
        "per_turn_observations": observations,
        "draft_pass_classifications": drafts,
    }


def observe_window(
    session_id: str,
    window_index: int,
    descriptions: list[dict],
    runner,
    repo: Path,
    model: str,
) -> dict:
    """Observe a single window of stage 1a descriptions.

    Cache lookup keyed on ``(stage_id, model, prompt_version,
    {session_id, window_index, descriptions})``. On hit, returns the
    cached dict without invoking the runner. On miss, invokes the
    runner exactly once, parses the JSON, normalises echoed
    identifiers, and writes the result to the cache.
    """
    content = _cache_content(session_id, window_index, descriptions)
    key = cache_key(
        stage_id=_STAGE_ID,
        model=model,
        prompt_version=STAGE_1B_PROMPT_VERSION,
        content=content,
    )
    cache = StageCache(repo=repo, stage_id=_STAGE_ID)

    cached = cache.get(key)
    if cached is not None:
        return cached

    user_prompt = _build_user_prompt(session_id, window_index, descriptions)
    raw = runner.invoke(
        system_prompt=STAGE_1B_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )
    parsed = extract_json(raw)
    out = _normalise_window_output(session_id, parsed)

    cache.set(key, out)
    return out


def _window_slices(n: int, window_size: int, overlap: int) -> list[tuple[int, int]]:
    """Compute (start, end_exclusive) for each window covering [0, n)."""
    if n <= 0:
        return []
    if window_size <= 0:
        raise ValueError("window_size must be > 0")
    if overlap < 0 or overlap >= window_size:
        raise ValueError("overlap must be in [0, window_size)")
    step = window_size - overlap
    slices: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + window_size, n)
        slices.append((start, end))
        if end >= n:
            break
        start += step
    return slices


def observe_session_windows(
    session_id: str,
    descriptions: list[dict],
    runner,
    repo: Path,
    model: str,
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> dict:
    """Window the session, observe each window, dedup, surface partial flag.

    Returns a dict:
      - per_turn_observations: list, deduped by turn_index (first-seen wins)
      - draft_pass_classifications: list concatenated across windows
      - partial_completion: bool, True if any window failed
      - failed_windows: list of {window_index, start, end, error}
    """
    slices = _window_slices(len(descriptions), window_size, overlap)

    aggregated_observations: List[dict] = []
    aggregated_drafts: List[dict] = []
    seen_turn_indices: set[int] = set()
    failed_windows: List[dict] = []

    for window_index, (start, end) in enumerate(slices):
        window_descs = descriptions[start:end]
        try:
            window_out = observe_window(
                session_id=session_id,
                window_index=window_index,
                descriptions=window_descs,
                runner=runner,
                repo=repo,
                model=model,
            )
        except Exception as exc:
            failed_windows.append({
                "window_index": window_index,
                "start": start,
                "end": end,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        for obs in window_out.get("per_turn_observations", []):
            if not isinstance(obs, dict):
                continue
            ti = obs.get("turn_index")
            if not isinstance(ti, int):
                continue
            if ti in seen_turn_indices:
                continue
            seen_turn_indices.add(ti)
            aggregated_observations.append(obs)

        for draft in window_out.get("draft_pass_classifications", []):
            if isinstance(draft, dict):
                aggregated_drafts.append(draft)

    aggregated_observations.sort(key=lambda o: o["turn_index"])

    return {
        "session_id": session_id,
        "per_turn_observations": aggregated_observations,
        "draft_pass_classifications": aggregated_drafts,
        "partial_completion": bool(failed_windows),
        "failed_windows": failed_windows,
    }
