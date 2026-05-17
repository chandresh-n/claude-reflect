"""Stage 2 — per-session refinement of draft pass classifications.

Stage 2 consumes the union of stage 1b's draft pass_classifications
for one session and produces the FINAL pass_classifications per the
spec: non-overlapping, contiguous, covering every turn of the session.

Spec: docs/spec/03-agents/evaluator.md and
docs/spec/01-data-structures/evaluator-output.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from meta_harness.agents._json_parsing import extract_json
from meta_harness.agents.pipeline.cache import StageCache, cache_key

# Bump this string whenever the stage-2 prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/1b/3/4.
STAGE_2_PROMPT_VERSION = "v1"

_STAGE_ID = "2"

STAGE_2_SYSTEM_PROMPT = """\
You are the per-session pass-refiner in an evaluator pipeline.

You receive the union of stage 1b draft pass_classifications across
all windows of ONE session. Adjacent windows overlapped, so drafts may
overlap or disagree at window seams (e.g., two drafts both classify
turn 19). You also receive ``total_turns``, the count of turns in the
session.

Produce a JSON object with exactly one field:

pass_classifications: an array of pass_classification objects that
covers turns [0..total_turns-1] NON-OVERLAPPINGLY with NO GAPS. Every
turn belongs to exactly one pass. Resolve seam conflicts by picking
the most plausible classification from the drafts.

Each pass_classification object has exactly:
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
priority ratings.

Output a single JSON object. No markdown fences, no preamble prose.
"""

_USER_PROMPT_TEMPLATE = """\
<session>
session_id: {session_id}
total_turns: {total_turns}
draft_pass_classifications:
{drafts_json}
</session>

Produce the JSON object as instructed in the system prompt.
"""


def _build_user_prompt(session_id: str, total_turns: int,
                       drafts: list[dict]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        session_id=session_id,
        total_turns=total_turns,
        drafts_json=json.dumps(drafts, indent=2, default=str, sort_keys=True),
    )


def _cache_content(session_id: str, total_turns: int,
                   drafts: list[dict]) -> dict:
    return {
        "session_id": session_id,
        "total_turns": total_turns,
        "drafts": drafts,
    }


def _normalise_output(session_id: str, parsed: Any) -> List[dict]:
    if not isinstance(parsed, dict):
        raise ValueError(
            f"stage 2 expected a JSON object, got {type(parsed).__name__}"
        )
    classifications = parsed.get("pass_classifications")
    if not isinstance(classifications, list):
        raise ValueError(
            "stage 2 pass_classifications must be an array, got "
            f"{type(classifications).__name__}"
        )
    for pc in classifications:
        if isinstance(pc, dict):
            pc["session_id"] = session_id
    return classifications


def refine_session_passes(
    session_id: str,
    drafts: list[dict],
    total_turns: int,
    runner,
    repo: Path,
    model: str,
) -> List[dict]:
    """Refine stage 1b drafts into the spec's final pass_classifications.

    Cache lookup keyed on ``(stage_id, model, prompt_version,
    {session_id, total_turns, drafts})``. On hit, returns the cached
    list. On miss, invokes the runner exactly once.
    """
    content = _cache_content(session_id, total_turns, drafts)
    key = cache_key(
        stage_id=_STAGE_ID,
        model=model,
        prompt_version=STAGE_2_PROMPT_VERSION,
        content=content,
    )
    cache = StageCache(repo=repo, stage_id=_STAGE_ID)

    cached = cache.get(key)
    if cached is not None:
        return cached

    user_prompt = _build_user_prompt(session_id, total_turns, drafts)
    raw = runner.invoke(
        system_prompt=STAGE_2_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )
    parsed = extract_json(raw)
    out = _normalise_output(session_id, parsed)

    cache.set(key, out)
    return out
