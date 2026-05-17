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

from meta_harness.agents._json_parsing import extract_json
from meta_harness.agents.pipeline.cache import StageCache, cache_key

# Bump this string whenever the stage-1b prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/2/3/4.
STAGE_1B_PROMPT_VERSION = "v1"

_STAGE_ID = "1b"

DEFAULT_WINDOW_SIZE = 25
DEFAULT_OVERLAP = 5

STAGE_1B_SYSTEM_PROMPT = """\
You are the windowed observer in an evaluator pipeline reading a
Claude Code session log via stage 1a per-turn descriptions.

You receive a WINDOW of stage 1a descriptions for one session.
Produce a JSON object with exactly two fields:

1. per_turn_observations: an array with one object per turn in the
   window. Each object has exactly these fields:
   - session_id (string, echo from input)
   - turn_index (integer, echo from input)
   - assessment (string): prose description of what happened at this
     turn, grounded in the stage 1a description. Descriptive, not
     judgmental.
   - effort_signal (object): {tokens_used (integer), model (string),
     context_occupancy (integer or null), tool_calls (array)}. Compute
     tokens_used as input_tokens + output_tokens from the stage 1a
     effort_signal. tool_calls is a list summarising tool usage as
     {name, count} entries (empty array if no tools).
   - flags (array of strings): zero or more of "hard_gate_failure",
     "pass_start", "pass_end", or any other event flag warranted by
     the description (empty array is fine).
   - tool_verifications (array): empty array in this stage.

2. draft_pass_classifications: an array of pass_classification objects
   covering this window. A pass is a contiguous sequence of turns
   working on the same sub-goal. Each object has exactly:
   - session_id (string, echo from input)
   - turn_range (array of two integers [start, end], inclusive)
   - pass_type (one of "successful_one_shot", "refinement",
     "clarification", "correction", "retry")
   - harness_gap_rationale (string): what could the harness have done
     differently to prevent or shorten this pass
   - contributing_gaps (array of gap identifier strings, or null;
     null is allowed ONLY for pass_type "successful_one_shot" or
     "refinement")

DO NOT produce scalar grades, quality scores, confidence numbers, or
priority ratings. DESCRIBE; do not judge.

Output a single JSON object. No markdown fences, no preamble prose.
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
