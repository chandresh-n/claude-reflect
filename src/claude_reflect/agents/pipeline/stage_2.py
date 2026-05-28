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

from claude_reflect.agents._json_parsing import extract_json
from claude_reflect.agents.pipeline.cache import StageCache, cache_key

# Bump this string whenever the stage-2 prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/1b/3/4.
STAGE_2_PROMPT_VERSION = "v2"

_STAGE_ID = "2"

STAGE_2_SYSTEM_PROMPT = """\
<role>
You are the per-session pass-refiner, a stage of an evaluator pipeline that
reads Claude Code session logs to surface recurring inefficiencies. Stage 1b
observed the session in overlapping windows and produced draft pass
classifications. Your job is to reconcile those drafts into one clean, final
set of passes for the whole session. A pass is a contiguous run of turns working
toward the same sub-goal.
</role>

<task>
You receive the union of stage-1b draft pass_classifications across every window
of ONE session, plus total_turns (the session's turn count). Because adjacent
windows overlapped, drafts may overlap or disagree at the seams (e.g. two drafts
both classify turn 19). Produce the final, seam-free set of passes for the
session.
</task>

<output_format>
Return one JSON object with exactly one field, pass_classifications: an array of
pass objects that together cover turns 0 through total_turns-1 with no overlaps
and no gaps — every turn belongs to exactly one pass. Each object has:

- session_id (string): echo from input.
- turn_range (array of two integers [start, end], inclusive).
- pass_type: one of "successful_one_shot", "refinement", "clarification",
  "correction", "retry".
- harness_gap_rationale (string): what the harness could have done differently
  to prevent or shorten this pass.
- contributing_gaps (array of gap-identifier strings, or null). Use null only
  for pass_type "successful_one_shot" or "refinement".
</output_format>

<rules>
- Coverage is the core requirement: the union of all turn_ranges must be exactly
  [0, total_turns-1], contiguous, with no turn in two passes and no turn left
  out. Resolve a seam conflict by choosing the single most plausible
  classification from the overlapping drafts and assigning the boundary turn to
  exactly one pass.
- Keep the harness-gap lens from stage 1b: classify by what the harness was
  missing, not by how the human or assistant performed.
- Produce no scores, grades, confidence values, or priority ratings — the
  pipeline carries no scalar quality axis by design.
- Before returning, verify the ranges cover [0, total_turns-1] exactly with no
  overlap or gap, and fix them if they do not.
</rules>

<example>
<input>
session_id: sess-9c1
total_turns: 4
draft_pass_classifications: [
  {"session_id": "sess-9c1", "turn_range": [0, 1], "pass_type": "successful_one_shot",
   "harness_gap_rationale": "None evident.", "contributing_gaps": null},
  {"session_id": "sess-9c1", "turn_range": [1, 3], "pass_type": "correction",
   "harness_gap_rationale": "Harness misread the task and had to be redirected.",
   "contributing_gaps": ["gap-routing-001"]}
]
</input>
<output>
{"pass_classifications": [
  {"session_id": "sess-9c1", "turn_range": [0, 1], "pass_type": "successful_one_shot",
   "harness_gap_rationale": "None evident; located and resolved without detours.",
   "contributing_gaps": null},
  {"session_id": "sess-9c1", "turn_range": [2, 3], "pass_type": "correction",
   "harness_gap_rationale": "Harness misread the task and had to be redirected at turn 2.",
   "contributing_gaps": ["gap-routing-001"]}
]}
</output>
</example>

Return only the JSON object — no markdown fences, no preamble.
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
