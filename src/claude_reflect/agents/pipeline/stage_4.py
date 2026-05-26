"""Stage 4 — cross-session gap observation production.

Stage 4 consumes the merged corpus of stage 1b/2/3 outputs across the
window (per_turn_observations, pass_classifications, session_narratives)
and identifies recurring inefficiency patterns. Output is a list of
``gap_observation`` objects matching the spec schema in
``docs/spec/01-data-structures/evaluator-output.md``.

Side effects (the gap-record knowledge base):

  - Each ``gap_observation`` with ``matched_gap_id=None`` creates a new
    gap-record file under ``.claude-reflect/gaps/<gap_id>.json`` via the
    public storage API. The returned observation has ``matched_gap_id``
    populated with the new record's identifier so downstream consumers
    can resolve back to canonical state.
  - Each ``gap_observation`` with ``matched_gap_id`` set APPENDS its
    ``evidence_additions`` to the existing record. Pre-existing
    evidence is preserved (the matched-gap-id merge rule from
    ``gap-record.md``).
  - Stage 4 never deletes a gap-record file or destructively rewrites
    one it did not observe (the append-only invariant).

Cache: the resolved observations (post-side-effect, with new
``matched_gap_id`` values populated) are written to
``.claude-reflect/eval-cache/stage-4/<key>.json``. A cache hit returns
the cached resolved observations without invoking the runner and
without re-firing side effects — so a re-run does not double-write
evidence.

Spec: docs/spec/03-agents/evaluator.md and
docs/spec/01-data-structures/gap-record.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from claude_reflect.agents._json_parsing import extract_json
from claude_reflect.agents.pipeline.cache import StageCache, cache_key
from claude_reflect.storage.gap_record import (
    create_gap_record,
    read_gap_record,
    update_gap_record,
)

# Bump this string whenever the stage-4 prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/1b/2/3.
STAGE_4_PROMPT_VERSION = "v1"

_STAGE_ID = "4"

STAGE_4_SYSTEM_PROMPT = """\
You are the cross-session corpus gap-observer in an evaluator
pipeline. You receive the WHOLE-CORPUS view of the window:

  - per_turn_observations across all sessions
  - pass_classifications across all sessions
  - session_narratives across all sessions

Your job is to identify recurring inefficiency patterns that span
multiple sessions or that repeat enough within a single session to
constitute a pattern. Each pattern becomes one gap_observation.

Produce a JSON object with exactly one field:

gap_observations: an array of gap_observation objects, each with
exactly:
- matched_gap_id (string or null). null for new patterns. Set to an
  existing gap identifier ONLY when the pattern matches a record
  already in the knowledge base context shown to you.
- characterization (string for new patterns; null or short refinement
  note for matched).
- kind (free-form string label; reuse existing kinds when reasonable).
- evidence_additions (array of evidence pointers). Each pointer has:
    session_id (string),
    turn_range (either [start, end] array OR {start, end} object),
    magnitude (object with additional_turns, additional_tokens,
               correction_required, and any other per-occurrence
               observations you can ground in the corpus).

DO NOT produce scalar grades, quality scores, confidence numbers, or
priority ratings. DESCRIBE the pattern; do not judge.

Output a single JSON object. No markdown fences, no preamble prose.
"""

_USER_PROMPT_TEMPLATE = """\
<corpus>
per_turn_observations:
{observations_json}

pass_classifications:
{classifications_json}

session_narratives:
{narratives_json}
</corpus>

Produce the JSON object as instructed in the system prompt.
"""


def _build_user_prompt(per_turn_observations: list[dict],
                       pass_classifications: list[dict],
                       session_narratives: list[dict]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        observations_json=json.dumps(per_turn_observations, indent=2,
                                     default=str, sort_keys=True),
        classifications_json=json.dumps(pass_classifications, indent=2,
                                        default=str, sort_keys=True),
        narratives_json=json.dumps(session_narratives, indent=2,
                                   default=str, sort_keys=True),
    )


def _cache_content(per_turn_observations: list[dict],
                   pass_classifications: list[dict],
                   session_narratives: list[dict]) -> dict:
    return {
        "per_turn_observations": per_turn_observations,
        "pass_classifications": pass_classifications,
        "session_narratives": session_narratives,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _handle_new_gap(repo: Path, gap_obs: dict) -> dict:
    """Create a fresh gap record from an unmatched observation.

    Returns the observation with ``matched_gap_id`` resolved to the new
    record's identifier. If the create call fails for any reason, the
    observation is returned unchanged (the cache then preserves the
    failure mode so re-runs do not re-create the record).
    """
    evidence = gap_obs.get("evidence_additions") or []
    characterization = gap_obs.get("characterization")
    if not isinstance(characterization, str) or not characterization:
        characterization = "(unspecified)"
    kind = gap_obs.get("kind")
    if not isinstance(kind, str) or not kind:
        kind = "unspecified"

    now = _now_iso()
    record_data = {
        "characterization": characterization,
        "kind": kind,
        "first_observed_at": now,
        "last_observed_at": now,
        "occurrence_count": len(evidence),
        "evidence": list(evidence),
        "status": "open",
        "related_proposals": [],
    }
    try:
        created = create_gap_record(repo, record_data)
    except Exception:
        return dict(gap_obs)
    return {**gap_obs, "matched_gap_id": created["identifier"]}


def _handle_matched_gap(repo: Path, gap_obs: dict) -> dict:
    """Append evidence to an existing gap record; preserve existing.

    Matched-gap-id merge rule from gap-record.md: existing evidence is
    preserved (append-only), the new evidence pointers are appended,
    ``occurrence_count`` is recomputed, ``last_observed_at`` advances.
    """
    gap_id = gap_obs["matched_gap_id"]
    new_evidence = gap_obs.get("evidence_additions") or []
    try:
        existing = read_gap_record(repo, gap_id)
    except FileNotFoundError:
        return dict(gap_obs)

    merged_evidence = list(existing.get("evidence", [])) + list(new_evidence)
    try:
        update_gap_record(repo, gap_id, {
            "evidence": merged_evidence,
            "occurrence_count": len(merged_evidence),
            "last_observed_at": _now_iso(),
            "status": "open",
        })
    except Exception:
        return dict(gap_obs)
    return dict(gap_obs)


def _write_gap_side_effects(repo: Path,
                            gap_observations: list[dict]) -> list[dict]:
    """Apply gap-record side effects: create new, append to matched."""
    resolved: list[dict] = []
    for gap_obs in gap_observations:
        if not isinstance(gap_obs, dict):
            continue
        if gap_obs.get("matched_gap_id") is None:
            resolved.append(_handle_new_gap(repo, gap_obs))
        else:
            resolved.append(_handle_matched_gap(repo, gap_obs))
    return resolved


def _normalise_output(parsed: Any) -> list[dict]:
    if not isinstance(parsed, dict):
        raise ValueError(
            f"stage 4 expected a JSON object, got {type(parsed).__name__}"
        )
    gap_observations = parsed.get("gap_observations")
    if not isinstance(gap_observations, list):
        raise ValueError(
            "stage 4 gap_observations must be an array, got "
            f"{type(gap_observations).__name__}"
        )
    return gap_observations


def identify_corpus_gaps(
    *,
    per_turn_observations: list[dict],
    pass_classifications: list[dict],
    session_narratives: list[dict],
    runner,
    repo: Path,
    model: str,
    write_gap_records: bool = True,
) -> list[dict]:
    """Identify cross-session gap_observations and apply side effects.

    Cache lookup keyed on
    ``(stage_id=4, model, prompt_version,
        {per_turn_observations, pass_classifications, session_narratives})``.

    On hit, returns the cached RESOLVED list (with matched_gap_id
    already populated for previously-new gaps) and does NOT re-run
    side effects — so a re-run with the same corpus does not
    double-write evidence to gap records.

    On miss, invokes the runner exactly once, parses the JSON, runs
    side effects (when ``write_gap_records=True``), and caches the
    resolved list.
    """
    content = _cache_content(per_turn_observations, pass_classifications,
                             session_narratives)
    key = cache_key(
        stage_id=_STAGE_ID,
        model=model,
        prompt_version=STAGE_4_PROMPT_VERSION,
        content=content,
    )
    cache = StageCache(repo=repo, stage_id=_STAGE_ID)

    cached = cache.get(key)
    if cached is not None:
        return cached

    user_prompt = _build_user_prompt(
        per_turn_observations, pass_classifications, session_narratives,
    )
    raw = runner.invoke(
        system_prompt=STAGE_4_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )
    parsed = extract_json(raw)
    gap_observations = _normalise_output(parsed)

    if write_gap_records:
        gap_observations = _write_gap_side_effects(repo, gap_observations)

    cache.set(key, gap_observations)
    return gap_observations
