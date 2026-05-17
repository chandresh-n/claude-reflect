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

from meta_harness.agents._json_parsing import extract_json
from meta_harness.agents.pipeline.cache import StageCache, cache_key

# Bump this string whenever the stage-3 prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/1b/2/4.
STAGE_3_PROMPT_VERSION = "v1"

_STAGE_ID = "3"

STAGE_3_SYSTEM_PROMPT = """\
You are the per-session narrative writer in an evaluator pipeline.

You receive, for ONE session:
- per_turn_observations (spec schema)
- pass_classifications (spec schema, non-overlapping)
- gap_observations touched by this session

Produce a JSON object — the session_narrative — with exactly:

- session_id (string, echo from input)
- outcome (one of "successful_and_accepted",
  "successful_with_friction", "abandoned", "ongoing")
- pass_counts_by_type (object mapping each pass_type string to its
  integer count in this session)
- gaps_observed (array of gap identifier strings touched in this
  session, drawn from gap_observations and pass_classifications'
  contributing_gaps)
- narrative (short prose for searchability; navigational, not a
  judgment)

DO NOT produce scalar grades, quality scores, confidence numbers, or
priority ratings.

Output a single JSON object. No markdown fences, no preamble prose.
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
