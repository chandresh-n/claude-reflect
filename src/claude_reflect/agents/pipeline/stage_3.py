"""Stage 3 — per-session narrative.

Stage 3 consumes a session's per_turn_observations,
pass_classifications, and gap_observations and produces exactly one
session_narrative per the spec. If upstream stages reported partial
data for this session, stage 3 propagates a ``partial_completion``
flag onto the narrative rather than dropping the session.

Spec: docs/spec/03-agents/evaluator.md and
docs/spec/01-data-structures/evaluator-output.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_reflect.agents._json_parsing import extract_json
from claude_reflect.agents.pipeline.cache import StageCache, cache_key

# Bump this string whenever the stage-3 prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/1b/2/4.
STAGE_3_PROMPT_VERSION = "v2"

_STAGE_ID = "3"

STAGE_3_SYSTEM_PROMPT = """\
<role>
You are the per-session narrative writer, a stage of an evaluator pipeline that
reads Claude Code session logs to surface recurring inefficiencies. You write
the one-paragraph summary of a single session. The narrative is a navigational
aid: another agent should be able to find this session later by searching for
its shape (for example, "sessions where the agent struggled to locate a file").
It is a cue for retrieval, not a verdict.
</role>

<task>
You receive, for ONE session: its per_turn_observations, its final
pass_classifications (non-overlapping), and the gap_observations touched by this
session. Summarise the session's shape and tally its passes. Describe; do not
score, rank, or recommend.
</task>

<output_format>
Return one JSON object — the session_narrative — with exactly:

- session_id (string): echo from input.
- outcome: one of "successful_and_accepted", "successful_with_friction",
  "abandoned", "ongoing".
- pass_counts_by_type (object): maps each pass_type that occurs in this session
  to its integer count.
- gaps_observed (array of gap-identifier strings): the gaps touched in this
  session, drawn from the gap_observations and from the contributing_gaps of the
  pass_classifications.
- narrative (string): short prose describing the session's shape, written to be
  searchable. A navigational cue, not a conclusion.
</output_format>

<rules>
- Ground the narrative and the outcome in the observations and passes you were
  given; do not introduce events they do not contain.
- "successful_with_friction" fits a session that reached an accepted result only
  after corrections, retries, or clarifications; reserve "successful_and_accepted"
  for a clean path.
- Produce no scores, grades, confidence values, or priority ratings — this
  pipeline has no scalar quality axis by design.
- If the input is flagged as partially complete, write the narrative from the
  turns you can see and do not speculate about the missing portion.
</rules>

<example>
<input>
session_id: sess-9c1
partial_completion: false
per_turn_observations: [ ...four turns... ]
pass_classifications: [
  {"turn_range": [0, 1], "pass_type": "successful_one_shot", "contributing_gaps": null},
  {"turn_range": [2, 3], "pass_type": "correction", "contributing_gaps": ["gap-routing-001"]}
]
gap_observations: [{"matched_gap_id": null, "kind": "task-misroute"}]
</input>
<output>
{"session_id": "sess-9c1", "outcome": "successful_with_friction",
 "pass_counts_by_type": {"successful_one_shot": 1, "correction": 1},
 "gaps_observed": ["gap-routing-001"],
 "narrative": "Raised a retry limit cleanly, then took a correction after misreading a follow-up task; resolved after the human redirected it."}
</output>
</example>

Return only the JSON object — no markdown fences, no preamble.
"""

_USER_PROMPT_TEMPLATE = """\
<session>
session_id: {session_id}
partial_completion: {partial_completion}
per_turn_observations:
{observations_json}

pass_classifications:
{classifications_json}

gap_observations:
{gaps_json}
</session>

Produce the JSON session_narrative as instructed in the system prompt.
"""


def _build_user_prompt(session_id: str,
                       per_turn_observations: list[dict],
                       pass_classifications: list[dict],
                       gap_observations: list[dict],
                       partial_completion: bool) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        session_id=session_id,
        partial_completion=str(bool(partial_completion)).lower(),
        observations_json=json.dumps(per_turn_observations, indent=2,
                                     default=str, sort_keys=True),
        classifications_json=json.dumps(pass_classifications, indent=2,
                                        default=str, sort_keys=True),
        gaps_json=json.dumps(gap_observations, indent=2,
                             default=str, sort_keys=True),
    )


def _cache_content(session_id: str,
                   per_turn_observations: list[dict],
                   pass_classifications: list[dict],
                   gap_observations: list[dict],
                   partial_completion: bool) -> dict:
    return {
        "session_id": session_id,
        "per_turn_observations": per_turn_observations,
        "pass_classifications": pass_classifications,
        "gap_observations": gap_observations,
        "partial_completion": bool(partial_completion),
    }


def _normalise_narrative(session_id: str, parsed: Any,
                         partial_completion: bool) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError(
            f"stage 3 expected a JSON object, got {type(parsed).__name__}"
        )
    parsed["session_id"] = session_id
    parsed["partial_completion"] = bool(partial_completion)
    return parsed


def summarize_session(
    session_id: str,
    per_turn_observations: list[dict],
    pass_classifications: list[dict],
    gap_observations: list[dict],
    runner,
    repo: Path,
    model: str,
    partial_completion: bool = False,
) -> dict:
    """Produce the session_narrative for one session.

    Cache lookup keyed on the full set of inputs INCLUDING the
    ``partial_completion`` flag — calling with the flag flipped must
    cascade to a cache miss because the narrative carries the flag.
    """
    content = _cache_content(
        session_id, per_turn_observations, pass_classifications,
        gap_observations, partial_completion,
    )
    key = cache_key(
        stage_id=_STAGE_ID,
        model=model,
        prompt_version=STAGE_3_PROMPT_VERSION,
        content=content,
    )
    cache = StageCache(repo=repo, stage_id=_STAGE_ID)

    cached = cache.get(key)
    if cached is not None:
        return cached

    user_prompt = _build_user_prompt(
        session_id, per_turn_observations, pass_classifications,
        gap_observations, partial_completion,
    )
    raw = runner.invoke(
        system_prompt=STAGE_3_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )
    parsed = extract_json(raw)
    out = _normalise_narrative(session_id, parsed, partial_completion)

    cache.set(key, out)
    return out
