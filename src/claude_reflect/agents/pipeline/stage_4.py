"""Stage 4 — cross-session gap observation production.

Stage 4 consumes the merged corpus of stage 1b/2/3 outputs across the
window (per_turn_observations, pass_classifications, session_narratives)
and identifies recurring inefficiency patterns. The existing matchable gap
records (status open/stale) are injected into the prompt so the model can
mark a recurrence as a match against a known gap rather than minting a
duplicate. Output is a list of ``gap_observation`` objects matching the spec
schema in ``docs/spec/01-data-structures/evaluator-output.md``.

The known-gaps context is injected into the prompt only, NOT the cache key:
the cache stays keyed on the corpus so a re-run of the same window returns
the cached resolved output and never re-fires side effects (no
double-written evidence).

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
    list_gap_records,
    read_gap_record,
    update_gap_record,
)

# Bump this string whenever the stage-4 prompt is edited. It is part of
# the cache key, so a bump silently invalidates this stage's cache
# without touching stages 1a/1b/2/3.
STAGE_4_PROMPT_VERSION = "v3"

_STAGE_ID = "4"

# Existing gaps the model is allowed to match a new observation against.
# Only unaddressed gaps are matchable: matching an "open" gap appends
# evidence, and matching a "stale" gap reactivates it (gap-record.md allows
# "any status -> open" on a fresh observation of a stale record). We do not
# offer addressed / partially_addressed gaps as candidates, to avoid
# regressing their status on an incidental match.
_MATCHABLE_STATUSES = frozenset({"open", "stale"})

STAGE_4_SYSTEM_PROMPT = """\
<role>
You are the cross-session corpus gap-observer, the final stage of an evaluator
pipeline that reads Claude Code session logs to surface recurring inefficiencies
in how an AI coding agent works. Earlier stages described each turn, each
session's passes, and each session's narrative. You see the whole window at once
and your job is to name the patterns of wasted effort that recur across it. Each
pattern you name becomes one "gap" — the unit the downstream proposer reasons
over when it decides what to change about the agent's configuration.
</role>

<task>
You receive the whole-corpus view of the window (per_turn_observations,
pass_classifications, and session_narratives across all sessions) and, under
<known_gaps>, the inefficiency patterns the knowledge base has already recorded.
Identify recurring inefficiency patterns — behaviours that waste turns or tokens
or require human correction — that either span multiple sessions or repeat enough
within a single session to constitute a pattern. For each one, decide whether it
is the same underlying inefficiency as an existing known gap or a genuinely new
pattern, and emit one gap_observation per distinct pattern, each backed by
concrete evidence from the corpus.
</task>

<output_format>
Return one JSON object with exactly one field, gap_observations: an array of
objects, each with:

- matched_gap_id (string or null): the identifier of a known gap when this
  pattern is the same underlying inefficiency as one listed under <known_gaps>;
  null when it is a genuinely new pattern (see the rule below).
- characterization (string for a new pattern; may be null or a short refinement
  note when matched_gap_id is set): one to three sentences naming the pattern
  and what makes it inefficient. For a new pattern this becomes the gap record's
  description.
- kind (string): a short, reusable label for the pattern (for example
  "file-location-thrash", "premature-edit", "test-symptom-chasing"). Prefer a
  general label that future occurrences could share over a hyper-specific one.
- evidence_additions (array): one pointer per observed occurrence, each with:
    - session_id (string),
    - turn_range (either an [start, end] array or a {"start", "end"} object),
    - magnitude (object): the per-occurrence cost you can ground in the corpus —
      {"additional_turns", "additional_tokens", "correction_required"} plus any
      other concrete per-occurrence observation.
</output_format>

<rules>
- Every gap_observation must be grounded in specific sessions and turn ranges
  drawn from the corpus you were given. A pattern you cannot point to is not a
  gap.
- A pattern must actually recur. A one-off difficulty in a single pass is not a
  gap; two or more occurrences (across sessions, or repeated within one) is.
- Match against the existing gaps under <known_gaps>. For each pattern, judge —
  by characterization and kind, not exact wording — whether it is the same
  underlying inefficiency as one of them. If it is, set matched_gap_id to that
  gap's identifier; your evidence_additions are appended to that record, so you
  may leave characterization null or give a short refinement note. If it is
  genuinely new, set matched_gap_id to null and write a fresh characterization.
  When you are unsure, prefer null (a new record) over forcing a weak match —
  duplicates are reconciled later, but a wrong match corrupts an existing record.
- Reuse a kind label when a pattern recurs (matching an existing gap's kind when
  you match it), so related patterns group together.
- Produce no scores, grades, severities, confidence values, or priority
  rankings. Describe the pattern and its concrete cost; the proposer weighs
  frequency, recency, and magnitude itself rather than reading a single number.
</rules>

<example>
<input>
<known_gaps>
[{"identifier": "gap-7a2", "kind": "file-location-thrash", "status": "open",
  "characterization": "The agent guesses file paths and opens nonexistent files before searching.",
  "occurrence_count": 4}]
</known_gaps>
<corpus>
session_narratives: [
  {"session_id": "s1", "narrative": "Tried three wrong directories before grepping to find auth.py."},
  {"session_id": "s3", "narrative": "Edited config.py before reading it, then reverted after the change broke a test."}
]
per_turn_observations: [ ...turns showing failed file lookups in s1 turns 2-5, and a premature edit in s3 turns 1-3... ]
pass_classifications: [ ... ]
</corpus>
</input>
<output>
{"gap_observations": [
  {"matched_gap_id": "gap-7a2", "characterization": null, "kind": "file-location-thrash",
   "evidence_additions": [
     {"session_id": "s1", "turn_range": [2, 5],
      "magnitude": {"additional_turns": 3, "additional_tokens": 2600, "correction_required": false}}
   ]},
  {"matched_gap_id": null,
   "characterization": "The agent edits a file before reading its current contents, then has to revert when the blind edit breaks existing behaviour.",
   "kind": "premature-edit",
   "evidence_additions": [
     {"session_id": "s3", "turn_range": [1, 3],
      "magnitude": {"additional_turns": 2, "additional_tokens": 1900, "correction_required": true}}
   ]}
]}
</output>
</example>

Return only the JSON object — no markdown fences, no preamble.
"""

_USER_PROMPT_TEMPLATE = """\
<known_gaps>
These are the existing knowledge-base gaps (open and stale) that a new
observation may match against. Match by characterization and kind, not exact
wording. If none apply, the pattern is new.
{known_gaps_json}
</known_gaps>

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


def _load_known_gaps(repo: Path) -> list[dict]:
    """Compact view of the matchable existing gap records for the prompt.

    Returns one entry per open/stale gap with just the fields the model needs
    to recognise a recurrence: identifier (to echo into matched_gap_id), kind,
    characterization, status, and occurrence_count. Evidence and
    related_proposals are omitted to keep the prompt small.
    """
    known: list[dict] = []
    for record in list_gap_records(repo, statuses=_MATCHABLE_STATUSES):
        identifier = record.get("identifier")
        if not identifier:
            continue
        known.append({
            "identifier": identifier,
            "kind": record.get("kind", ""),
            "characterization": record.get("characterization", ""),
            "status": record.get("status", ""),
            "occurrence_count": record.get("occurrence_count", 0),
        })
    return known


def _build_user_prompt(per_turn_observations: list[dict],
                       pass_classifications: list[dict],
                       session_narratives: list[dict],
                       known_gaps: list[dict]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        known_gaps_json=json.dumps(known_gaps, indent=2, default=str,
                                   sort_keys=True),
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
        # The model referenced an id that is not in the knowledge base
        # (hallucinated, or a record that no longer exists). Rather than
        # silently drop the observation, treat it as a new gap so its
        # evidence is still captured.
        return _handle_new_gap(repo, {**gap_obs, "matched_gap_id": None})

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

    # Inject the existing matchable gaps into the PROMPT only, not the cache
    # key. The cache is keyed on the corpus so a re-run with the same window
    # returns the cached resolved output and never re-fires side effects
    # (no double-written evidence). The current knowledge-base gaps are what
    # the model needs on the first, uncached invocation to match recurrences.
    known_gaps = _load_known_gaps(repo)
    user_prompt = _build_user_prompt(
        per_turn_observations, pass_classifications, session_narratives,
        known_gaps,
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
