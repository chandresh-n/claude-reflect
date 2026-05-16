"""
Evaluator agent — Step 8 of the meta-harness build.

Reads session logs and produces a structured evaluator output document.
Updates/creates gap records as a side effect.

Spec refs:
- docs/spec/03-agents/evaluator.md
- docs/spec/01-data-structures/evaluator-output.md

Constraints:
- No scalar grades, no recommendations, no rankings.
- Fresh context per invocation (context isolation).
- Every observation is evidence-grounded.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from meta_harness.agents.claude_runner import ClaudeRunnerError, invoke_claude
from meta_harness.storage.gap_record import (
    create_gap_record,
    read_gap_record,
    update_gap_record,
)
from meta_harness.storage.session_logs import Session, SessionLogReader

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVALUATOR_OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "per_turn_observations",
        "pass_classifications",
        "gap_observations",
        "session_narratives",
    ],
    "additionalProperties": False,
    "properties": {
        "per_turn_observations": {"type": "array", "minItems": 1},
        "pass_classifications": {"type": "array", "minItems": 1},
        "gap_observations": {"type": "array"},
        "session_narratives": {"type": "array", "minItems": 1},
    },
}

SYSTEM_PROMPT = """\
You are the evaluator agent for the meta-harness. Your role is to read session \
logs and produce structured observations of what happened. You do NOT grade, \
rank, or recommend. Your output is a structured report consumed by the proposer.

## Behavioral directives

- SKEPTICISM: Look for reasons a session went poorly, not reasons it went well. \
Examine friction even when the outcome was successful.
- TOOL-BACKED VERIFICATION: When making a verifiable claim, use tools to verify \
rather than accepting log assertions at face value.
- EVIDENCE-GROUNDED PROSE: Every assessment must have supporting evidence from \
the log or tool output. No speculation presented as observation.
- NO GRADING: Never produce a scalar quality score, confidence value, or ranking.
- NO RECOMMENDATIONS: Never suggest what should be done. That is the proposer's job.
- EXHAUSTIVE: Every turn must have an observation. Every pass must be classified.

## Output format

You MUST produce a JSON object with exactly these top-level keys:
- per_turn_observations: array of observation objects (one per turn, contiguous from 0)
- pass_classifications: array of pass classification objects (non-overlapping, covering all turns)
- gap_observations: array of gap observation objects (one per identified pattern)
- session_narratives: array of session narrative objects (one per session)

### Per-turn observation schema:
{
  "session_id": string,
  "turn_index": integer (0-indexed),
  "assessment": string (descriptive prose, not judgmental),
  "effort_signal": {
    "tokens_used": integer,
    "model": string,
    "context_occupancy": number (0-1),
    "tool_calls": [{"tool_name": string, "count": integer}]
  },
  "flags": [{"flag_type": string, "description": string (optional)}]
}

### Pass classification schema:
{
  "session_id": string,
  "turn_range": {"start": integer, "end": integer},
  "pass_type": one of ["successful_one_shot", "refinement", "clarification", "correction", "retry"],
  "harness_gap_rationale": string (what could the harness have done differently),
  "contributing_gaps": null (for successful_one_shot/refinement) or array of gap IDs
}

### Gap observation schema:
{
  "matched_gap_id": string or null,
  "characterization": string (for new patterns) or null (for matched),
  "kind": string (reuse existing kinds when reasonable),
  "evidence_additions": [{
    "session_id": string,
    "turn_range": {"start": integer, "end": integer},
    "magnitude": {
      "additional_turns": integer,
      "additional_tokens": integer,
      "correction_required": boolean
    }
  }]
}

### Session narrative schema:
{
  "session_id": string,
  "outcome": one of ["successful_and_accepted", "successful_with_friction", "abandoned", "ongoing"],
  "pass_counts_by_type": object mapping pass_type to count,
  "gaps_observed": array of gap IDs touched,
  "narrative": string (navigational description of the session's shape)
}

## Processing order

Process sessions chronologically. Within each session, process turns in order. \
Pass classification depends on turn-to-turn relationships.

## Kind vocabulary discipline

Reuse existing kinds when a pattern reasonably matches. Only introduce new kinds \
when no existing kind honestly applies.

## Critical constraints

- NO scalar grades, scores, priorities, severities, confidences, rankings ANYWHERE.
- NO recommendations, proposals, or suggestions ANYWHERE.
- Output ONLY valid JSON matching the schema above. No markdown wrapping.
"""


def _xml_escape(s: str) -> str:
    """Minimal XML escaping for content embedded in the archived_session_log
    XML structure.  Keeps & and < safe; quotes are not in attribute
    position so we don't escape them in element bodies."""
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_sessions_for_prompt(
    sessions: List[Session], turn_offset: int = 0
) -> str:
    """Format session data as XML for the evaluator prompt.

    The structure deliberately AVOIDS conversational role headers
    (``Human:`` / ``Assistant:`` / ``Tool calls:``).  Those headers
    are how Claude internally formats its OWN chat history, so an
    LLM reading them in a user prompt tends to interpret the input
    as an in-progress conversation it should continue — i.e. to act
    as an agent rather than as an evaluator.  Wrapping the same
    information in ``<archived_session_log>`` / ``<past_human>`` /
    ``<past_assistant>`` tags reframes the content as historical
    data being shown to the model, not as a transcript open at the
    bottom for continuation.
    """
    parts: List[str] = []
    for session in sessions:
        attrs = (
            f'session_id="{session.session_id}"'
            f' start="{session.start_time.isoformat()}"'
            f' end="{session.end_time.isoformat()}"'
            f' turns="{len(session.turns)}"'
        )
        if turn_offset > 0:
            attrs += f' turn_offset="{turn_offset}"'
        parts.append(f"<archived_session_log {attrs}>")
        for i, turn in enumerate(session.turns):
            parts.append(f'  <turn index="{turn_offset + i}">')
            if turn.human_input:
                parts.append(
                    f"    <past_human>{_xml_escape(turn.human_input)}</past_human>"
                )
            if turn.assistant_response:
                parts.append(
                    f"    <past_assistant>{_xml_escape(turn.assistant_response)}"
                    f"</past_assistant>"
                )
            if turn.tool_calls:
                tc_str = ", ".join(tc.name for tc in turn.tool_calls)
                parts.append(
                    f"    <past_tools_called>{_xml_escape(tc_str)}"
                    f"</past_tools_called>"
                )
            if turn.model:
                parts.append(
                    f"    <past_model>{_xml_escape(turn.model)}</past_model>"
                )
            if turn.input_tokens is not None:
                total = (turn.input_tokens or 0) + (turn.output_tokens or 0)
                parts.append(f"    <past_token_count>{total}</past_token_count>")
            parts.append("  </turn>")
        parts.append("</archived_session_log>")
    return "\n".join(parts)


def _format_existing_gaps(repo: Path) -> str:
    """Format existing gap records for the evaluator to match against."""
    gaps_dir = repo / ".meta-harness" / "gaps"
    if not gaps_dir.exists():
        return "No existing gap records."

    gap_files = sorted(gaps_dir.glob("*.json"))
    if not gap_files:
        return "No existing gap records."

    parts = ["## Existing gap records (match against these when possible)\n"]
    for gf in gap_files:
        try:
            record = json.loads(gf.read_text(encoding="utf-8"))
            parts.append(
                f"- ID: {record.get('identifier', 'unknown')}\n"
                f"  Kind: {record.get('kind', 'unknown')}\n"
                f"  Characterization: {record.get('characterization', 'N/A')}\n"
                f"  Status: {record.get('status', 'unknown')}\n"
            )
        except (json.JSONDecodeError, OSError):
            continue
    return "\n".join(parts)


def _write_gap_side_effects(
    repo: Path, gap_observations: List[dict]
) -> List[dict]:
    """
    Write gap record side effects from evaluator output.

    For new gaps (matched_gap_id is null): create a new gap record.
    For matched gaps: update evidence and counters.

    Returns the gap_observations list with matched_gap_id populated for new gaps.
    """
    updated_observations = []
    for gap_obs in gap_observations:
        if gap_obs.get("matched_gap_id") is None:
            # New gap — create a record
            evidence = gap_obs.get("evidence_additions", [])
            record_data = {
                "characterization": gap_obs.get("characterization", ""),
                "kind": gap_obs.get("kind", ""),
                "first_observed_at": evidence[0]["session_id"] if evidence else "",
                "last_observed_at": evidence[-1]["session_id"] if evidence else "",
                "occurrence_count": len(evidence),
                "evidence": evidence,
                "status": "open",
                "related_proposals": [],
            }
            try:
                created = create_gap_record(repo, record_data)
                gap_obs = {**gap_obs, "matched_gap_id": created["identifier"]}
            except Exception:
                pass
        else:
            # Existing gap — update evidence
            gap_id = gap_obs["matched_gap_id"]
            evidence = gap_obs.get("evidence_additions", [])
            try:
                existing = read_gap_record(repo, gap_id)
                new_evidence = existing.get("evidence", []) + evidence
                update_gap_record(repo, gap_id, {
                    "evidence": new_evidence,
                    "occurrence_count": len(new_evidence),
                    "last_observed_at": evidence[-1]["session_id"] if evidence else existing.get("last_observed_at", ""),
                    "status": "open",
                })
            except Exception:
                pass
        updated_observations.append(gap_obs)
    return updated_observations


# Rough estimate: ~4 chars per token.  Leave headroom for system prompt
# and response tokens within a 200K context window.
_MAX_PROMPT_CHARS = 400_000  # ~100K tokens for session text

# Max turns per evaluator call.  289 turns = ~30K output tokens which
# takes hundreds of minutes to generate.  50 turns = ~5K output tokens
# which finishes in a few minutes.
_MAX_TURNS_PER_CHUNK = 50


def _estimate_session_chars(session: "Session") -> int:
    """Estimate the character count for a formatted session."""
    count = len(session.session_id) + 80  # header lines
    for turn in session.turns:
        count += len(turn.human_input or "") + len(turn.assistant_response or "")
        count += 100  # metadata lines per turn
    return count


def _chunk_large_sessions(sessions: List["Session"]) -> List[dict]:
    """Split sessions with too many turns into smaller chunks.

    Returns a list of dicts with:
      - "session": the Session object (possibly a subset of turns)
      - "turn_offset": the starting turn index in the original session
      - "total_turns": the total number of turns in the original session

    Sessions with <= _MAX_TURNS_PER_CHUNK turns are returned as-is.
    """
    result: List[dict] = []
    for session in sessions:
        if len(session.turns) <= _MAX_TURNS_PER_CHUNK:
            result.append({
                "session": session,
                "turn_offset": 0,
                "total_turns": len(session.turns),
            })
            continue

        from meta_harness.storage.session_logs import Session as _Session

        total = len(session.turns)
        for start in range(0, total, _MAX_TURNS_PER_CHUNK):
            chunk_turns = session.turns[start:start + _MAX_TURNS_PER_CHUNK]
            chunk = _Session(
                session_id=session.session_id,
                start_time=session.start_time,
                end_time=session.end_time,
                file_path=session.file_path,
                turns=chunk_turns,
            )
            result.append({
                "session": chunk,
                "turn_offset": start,
                "total_turns": total,
            })
    return result


def _split_into_batches(
    sessions: List["Session"], max_chars: int = _MAX_PROMPT_CHARS
) -> List[List[dict]]:
    """Split sessions into batches that fit within the prompt size limit.

    Batches are constrained by BOTH prompt size AND turn count (since
    each turn requires output tokens for its observation).

    Returns a list of batches.  Each batch is a list of chunk dicts
    (from _chunk_large_sessions).
    """
    # First, chunk any session that has too many turns
    chunked = _chunk_large_sessions(sessions)

    batches: List[List[dict]] = []
    current_batch: List[dict] = []
    current_chars = 0
    current_turns = 0

    for chunk in chunked:
        session_chars = _estimate_session_chars(chunk["session"])
        chunk_turns = len(chunk["session"].turns)
        # Enforce both char limit and turn limit per batch
        if current_batch and (
            current_chars + session_chars > max_chars
            or current_turns + chunk_turns > _MAX_TURNS_PER_CHUNK
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
            current_turns = 0
        current_batch.append(chunk)
        current_chars += session_chars
        current_turns += chunk_turns

    if current_batch:
        batches.append(current_batch)

    return batches


def _content_hash(sessions: List["Session"], model: str) -> str:
    """Stable hash over sessions + model.  Used as the in-run per-batch
    checkpoint key (the cheaper, batch-set-keyed cache below the
    per-session cache)."""
    parts: List[str] = [model]
    for s in sorted(sessions, key=lambda s: s.session_id):
        parts.append(s.session_id)
        parts.append(s.start_time.isoformat())
        parts.append(s.end_time.isoformat())
        parts.append(str(len(s.turns)))
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _session_cache_key(session: "Session", model: str) -> str:
    """Stable per-session cache key.  Re-runs reuse this entry as long as
    the session's tail (end_time, turn_count) hasn't moved."""
    parts = [
        model,
        session.session_id,
        session.start_time.isoformat(),
        session.end_time.isoformat(),
        str(len(session.turns)),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _read_session_cache(
    cache_dir: Path, session: "Session", model: str
) -> Optional[dict]:
    """Return the cached per-session output, or None if missing/corrupt."""
    key = _session_cache_key(session, model)
    f = cache_dir / f"{key}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    if "per_turn_observations" not in data or "pass_classifications" not in data:
        return None
    return data


def _write_session_cache(
    cache_dir: Path,
    sessions: List["Session"],
    fresh_output: dict,
    model: str,
) -> None:
    """Split the merged fresh output by session_id and persist one cache
    file per session.  Sessions with no observations are not cached
    (an empty cache entry would lock in a bad result)."""
    by_id = {s.session_id: s for s in sessions}

    obs_by_sid: dict[str, list] = {sid: [] for sid in by_id}
    for obs in fresh_output.get("per_turn_observations", []):
        sid = obs.get("session_id")
        if sid in obs_by_sid:
            obs_by_sid[sid].append(obs)

    pass_by_sid: dict[str, list] = {sid: [] for sid in by_id}
    for pc in fresh_output.get("pass_classifications", []):
        sid = pc.get("session_id")
        if sid in pass_by_sid:
            pass_by_sid[sid].append(pc)

    narr_by_sid: dict[str, dict] = {}
    for n in fresh_output.get("session_narratives", []):
        sid = n.get("session_id")
        if sid in by_id:
            narr_by_sid[sid] = n

    # gap_observations: attach to every session cited in evidence.  The
    # merge step dedups by gap id when a re-run rejoins them.
    gaps_by_sid: dict[str, list] = {sid: [] for sid in by_id}
    for go in fresh_output.get("gap_observations", []):
        cited: set[str] = set()
        for e in go.get("evidence_additions", []):
            esid = e.get("session_id")
            if esid in gaps_by_sid:
                cited.add(esid)
        for sid in cited:
            gaps_by_sid[sid].append(go)

    cache_dir.mkdir(parents=True, exist_ok=True)
    for sid, session in by_id.items():
        if not obs_by_sid.get(sid):
            # No observations produced for this session — skip caching so
            # the next run re-evaluates it.
            continue
        key = _session_cache_key(session, model)
        f = cache_dir / f"{key}.json"
        data = {
            "session_id": sid,
            "model": model,
            "session_signature": {
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "turn_count": len(session.turns),
            },
            "per_turn_observations": obs_by_sid.get(sid, []),
            "pass_classifications": pass_by_sid.get(sid, []),
            "session_narrative": narr_by_sid.get(sid),
            "gap_observations": gaps_by_sid.get(sid, []),
        }
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _dedup_gap_observations(gap_obs: List[dict]) -> List[dict]:
    """Merge duplicate gap_observations by matched_gap_id, unioning evidence."""
    by_key: dict[tuple, dict] = {}
    for go in gap_obs:
        gid = go.get("matched_gap_id")
        if gid is not None:
            key = ("id", gid)
        else:
            key = ("char", go.get("characterization", ""))
        if key in by_key:
            existing = by_key[key]
            seen = {
                (
                    e.get("session_id"),
                    tuple(sorted((e.get("turn_range") or {}).items())),
                )
                for e in existing.get("evidence_additions", [])
            }
            for e in go.get("evidence_additions", []):
                e_key = (
                    e.get("session_id"),
                    tuple(sorted((e.get("turn_range") or {}).items())),
                )
                if e_key not in seen:
                    existing["evidence_additions"].append(e)
                    seen.add(e_key)
        else:
            by_key[key] = {
                **go,
                "evidence_additions": list(go.get("evidence_additions", [])),
            }
    return list(by_key.values())


def _merge_with_cached(
    fresh: dict, cached_chunks: List[dict]
) -> dict:
    """Combine fresh evaluator output with per-session cached chunks.

    Per-turn observations, pass classifications, and session narratives are
    concatenated.  Gap observations are deduped by matched_gap_id (or by
    characterization when no id is set), unioning evidence_additions.
    """
    merged = {
        "per_turn_observations": list(fresh.get("per_turn_observations", [])),
        "pass_classifications": list(fresh.get("pass_classifications", [])),
        "gap_observations": list(fresh.get("gap_observations", [])),
        "session_narratives": list(fresh.get("session_narratives", [])),
    }
    for chunk in cached_chunks:
        merged["per_turn_observations"].extend(
            chunk.get("per_turn_observations", [])
        )
        merged["pass_classifications"].extend(
            chunk.get("pass_classifications", [])
        )
        if chunk.get("session_narrative"):
            merged["session_narratives"].append(chunk["session_narrative"])
        merged["gap_observations"].extend(chunk.get("gap_observations", []))

    merged["gap_observations"] = _dedup_gap_observations(
        merged["gap_observations"]
    )
    return merged


def _merge_evaluator_outputs(outputs: List[dict]) -> dict:
    """Merge multiple evaluator outputs from batched runs."""
    merged = {
        "per_turn_observations": [],
        "pass_classifications": [],
        "gap_observations": [],
        "session_narratives": [],
    }
    for output in outputs:
        merged["per_turn_observations"].extend(
            output.get("per_turn_observations", [])
        )
        merged["pass_classifications"].extend(
            output.get("pass_classifications", [])
        )
        merged["gap_observations"].extend(
            output.get("gap_observations", [])
        )
        merged["session_narratives"].extend(
            output.get("session_narratives", [])
        )
    return merged


def _build_batch_prompt(chunks: List[dict], existing_gaps: str) -> str:
    """Build the user prompt for a batch.

    Three structural choices to keep the model in evaluator mode and out
    of agent mode:

      1. Opening framing tells the model the input is archived data and
         it must not respond conversationally or call tools.
      2. Session content lives inside ``<archived_session_log>`` XML —
         no ``Human:`` / ``Assistant:`` role headers that look like an
         open transcript.
      3. The "produce JSON only" instruction comes AFTER the data, so
         it's the last thing the model reads before generating.

    Extracted as a helper so the failure-log writer can reproduce the
    exact prompt without re-running the model.
    """
    parts = []
    for chunk in chunks:
        part = _format_sessions_for_prompt(
            [chunk["session"]], turn_offset=chunk["turn_offset"]
        )
        parts.append(part)
    session_text = "\n".join(parts)

    return (
        "You are analyzing ARCHIVED Claude Code session logs.  The XML below "
        "is historical data — a record of past conversations that have "
        "already ended.  It is NOT a conversation you are part of.  "
        "Do NOT respond to it.  Do NOT call any tools.  Your only output "
        "is the structured JSON evaluation document.\n\n"
        f"{existing_gaps}\n\n"
        "<archived_sessions_to_analyze>\n"
        f"{session_text}\n"
        "</archived_sessions_to_analyze>\n\n"
        "Produce the evaluator output now.  Output ONLY a valid JSON object "
        "with these four top-level keys (and no others): "
        "per_turn_observations, pass_classifications, gap_observations, "
        "session_narratives.  Match the schema described in the system "
        "prompt.  Do NOT call any tools.  Do NOT wrap the JSON in markdown "
        "fences.  Do NOT add preamble or postamble prose.  Begin your "
        "response with the opening brace { and end with the closing brace }."
    )


def _evaluate_batch(
    chunks: List[dict],
    repo: Path,
    model: str,
    existing_gaps: str,
    label: Optional[str] = None,
    expected_turns: Optional[int] = None,
    log_dir: Optional[Path] = None,
) -> dict:
    """Run the evaluator on a single batch of session chunks."""
    user_prompt = _build_batch_prompt(chunks, existing_gaps)
    total_turns = sum(len(c["session"].turns) for c in chunks)
    session_ids = set(c["session"].session_id for c in chunks)
    print(
        f"  prompt: {len(user_prompt):,} chars (~{len(user_prompt)//4:,} tokens), "
        f"{total_turns} turns across {len(session_ids)} session(s), "
        f"model={model}",
        file=sys.stderr, flush=True,
    )

    try:
        raw_text = invoke_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
            label=label,
            progress_pattern=r'"turn_index"',
            progress_total=expected_turns or total_turns,
            progress_unit="turns",
            log_dir=log_dir,
        )
    except ClaudeRunnerError as e:
        raise EvaluatorError(f"Claude invocation failed: {e}") from e

    print(
        f"  output: {len(raw_text):,} chars (~{len(raw_text)//4:,} tokens)",
        file=sys.stderr, flush=True,
    )

    return _parse_evaluator_output(raw_text)


def evaluate(
    sessions: List[Session],
    repo: Path,
    model: str = "claude-opus-4-6",
    write_gap_records: bool = True,
    checkpoint_dir: Optional[Path] = None,
    log_dir: Optional[Path] = None,
) -> dict:
    """
    Run the evaluator agent on the given sessions.

    Automatically batches sessions if the combined prompt would exceed
    the context window, running separate evaluator calls and merging
    the results.

    When ``checkpoint_dir`` is provided, each batch's output is written
    to ``checkpoint_dir/batch-NNN.json`` as it completes, and existing
    checkpoints are loaded instead of re-running their batches.  This
    makes a partially-failed evaluation cheap to resume: re-run with the
    same checkpoint_dir and only the missing batches are re-executed.

    Args:
        sessions: List of Session objects to evaluate.
        repo: Root of the target git repository (for gap record access).
        model: Anthropic model to use for evaluation.
        write_gap_records: Whether to write gap record side effects.
        checkpoint_dir: If set, persist per-batch outputs here for resume.

    Returns:
        Evaluator output dict matching the evaluator-output schema.

    Raises:
        EvaluatorError: If the agent fails to produce valid output.
    """
    if not sessions:
        raise EvaluatorError("No sessions provided for evaluation")

    # Per-run RCA log dir: ``.meta-harness/logs/eval/<UTC-timestamp>/``.
    # Every batch gets its own subdirectory under ``batches/`` with the
    # raw model stream, a status.json, and (on failure) a prompt.txt.
    if log_dir is None:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        log_dir = repo / ".meta-harness" / "logs" / "eval" / run_ts
    log_dir.mkdir(parents=True, exist_ok=True)
    summary_path = log_dir / "summary.txt"

    def _tee(msg: str) -> None:
        """Print to stderr AND append to the run's summary.txt."""
        print(msg, file=sys.stderr, flush=True)
        try:
            with summary_path.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass

    _tee(f"  evaluator run log: {log_dir}")

    # Per-session cache: skip sessions whose (session_id, end_time,
    # turn_count) signature already has cached observations.  This is the
    # key fix for re-runs where one session has grown (e.g. the very
    # Claude Code session running the meta-harness keeps appending turns)
    # — only the changed/new sessions go to the model.
    session_cache_dir = repo / ".meta-harness" / "eval-cache" / "sessions"
    session_cache_dir.mkdir(parents=True, exist_ok=True)

    cached_chunks: List[dict] = []
    uncached_sessions: List[Session] = []
    for s in sessions:
        cached = _read_session_cache(session_cache_dir, s, model)
        if cached is not None:
            cached_chunks.append(cached)
        else:
            uncached_sessions.append(s)

    n_cached = len(cached_chunks)
    n_uncached = len(uncached_sessions)
    _tee(
        f"  evaluator: {n_cached}/{len(sessions)} sessions cached, "
        f"{n_uncached} need evaluation"
    )

    fresh: dict = {
        "per_turn_observations": [],
        "pass_classifications": [],
        "gap_observations": [],
        "session_narratives": [],
    }

    if uncached_sessions:
        existing_gaps = _format_existing_gaps(repo)
        batches = _split_into_batches(uncached_sessions)

        total = len(batches)
        total_turns = sum(
            len(chunk["session"].turns)
            for batch in batches
            for chunk in batch
        )

        # In-run per-batch checkpoint dir: keyed on the uncached set so a
        # crashed mid-evaluation can resume cheaply on re-run.
        if checkpoint_dir is None:
            cache_key = _content_hash(uncached_sessions, model)
            checkpoint_dir = (
                repo / ".meta-harness" / "eval-cache" / "batches" / cache_key
            )
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        _tee(
            f"  evaluator: {total} batch(es), {total_turns} turns total, "
            f"batch checkpoints: {checkpoint_dir}"
        )

        batch_outputs: List[dict] = []
        failed: List[int] = []

        for i, batch in enumerate(batches):
            batch_turns = sum(len(c["session"].turns) for c in batch)
            ckpt_path = checkpoint_dir / f"batch-{i + 1:03d}.json"
            batch_log_dir = log_dir / "batches" / f"batch-{i + 1:03d}"
            batch_log_dir.mkdir(parents=True, exist_ok=True)
            batch_session_ids = sorted(
                {c["session"].session_id for c in batch}
            )

            if ckpt_path.exists():
                try:
                    cached = json.loads(ckpt_path.read_text(encoding="utf-8"))
                    _validate_output_structure(cached)
                    _tee(
                        f"  [evaluator batch {i + 1}/{total}] "
                        f"resumed from checkpoint ({batch_turns} turns)"
                    )
                    (batch_log_dir / "status.json").write_text(
                        json.dumps({
                            "batch_index": i + 1,
                            "total_batches": total,
                            "outcome": "resumed_from_checkpoint",
                            "turns_in_batch": batch_turns,
                            "session_ids": batch_session_ids,
                            "observations": len(
                                cached.get("per_turn_observations", [])
                            ),
                        }, indent=2),
                        encoding="utf-8",
                    )
                    batch_outputs.append(cached)
                    continue
                except (json.JSONDecodeError, OSError, EvaluatorError):
                    _tee(
                        f"  [evaluator batch {i + 1}/{total}] "
                        f"checkpoint corrupt, re-running"
                    )

            label = f"evaluator batch {i + 1}/{total}"
            batch_started = time.monotonic()
            try:
                batch_output = _evaluate_batch(
                    batch, repo, model, existing_gaps,
                    label=label, expected_turns=batch_turns,
                    log_dir=batch_log_dir,
                )
            except EvaluatorError as e:
                duration = int(time.monotonic() - batch_started)
                # Failure-only: write the prompt so RCA has the full input.
                try:
                    prompt_text = _build_batch_prompt(batch, existing_gaps)
                    (batch_log_dir / "prompt.txt").write_text(
                        prompt_text, encoding="utf-8"
                    )
                except OSError:
                    pass
                (batch_log_dir / "status.json").write_text(
                    json.dumps({
                        "batch_index": i + 1,
                        "total_batches": total,
                        "outcome": "failed",
                        "error": str(e),
                        "duration_s": duration,
                        "turns_in_batch": batch_turns,
                        "session_ids": batch_session_ids,
                    }, indent=2),
                    encoding="utf-8",
                )
                failed.append(i + 1)
                _tee(
                    f"  [evaluator batch {i + 1}/{total}] FAILED: {e}"
                )
                _tee(
                    f"    RCA artifacts: {batch_log_dir}"
                )
                continue

            duration = int(time.monotonic() - batch_started)
            ckpt_path.write_text(
                json.dumps(batch_output, indent=2), encoding="utf-8"
            )
            (batch_log_dir / "status.json").write_text(
                json.dumps({
                    "batch_index": i + 1,
                    "total_batches": total,
                    "outcome": "ok",
                    "duration_s": duration,
                    "turns_in_batch": batch_turns,
                    "session_ids": batch_session_ids,
                    "observations": len(
                        batch_output.get("per_turn_observations", [])
                    ),
                }, indent=2),
                encoding="utf-8",
            )
            batch_outputs.append(batch_output)

        if failed:
            _tee(
                f"  evaluator: {len(failed)} of {total} batches failed: {failed}"
            )
            raise EvaluatorError(
                f"{len(failed)} of {total} batches failed: {failed}. "
                f"RCA artifacts under {log_dir}/batches/. "
                f"Re-run to retry only the failed batches."
            )

        fresh = _merge_evaluator_outputs(batch_outputs)

        # Apply gap record side effects ONLY to fresh observations.
        # Cached observations already wrote their effects on the prior
        # run; replaying them would double-add evidence.
        if write_gap_records and fresh.get("gap_observations"):
            fresh["gap_observations"] = _write_gap_side_effects(
                repo, fresh["gap_observations"]
            )

        # Cache the fresh per-session output for future re-runs.
        _write_session_cache(
            session_cache_dir, uncached_sessions, fresh, model
        )

    return _merge_with_cached(fresh, cached_chunks)


def evaluate_from_jsonl(
    session_paths: List[Path],
    repo: Path,
    model: str = "claude-opus-4-6",
    write_gap_records: bool = True,
) -> dict:
    """
    Convenience: read sessions from JSONL files and evaluate.

    Args:
        session_paths: Paths to JSONL session log files.
        repo: Root of the target git repository.
        model: Anthropic model to use.
        write_gap_records: Whether to write gap record side effects.

    Returns:
        Evaluator output dict.
    """
    sessions = [SessionLogReader.read_session(p) for p in session_paths]
    return evaluate(sessions, repo, model=model, write_gap_records=write_gap_records)


def _parse_evaluator_output(raw_text: str) -> dict:
    """
    Parse the evaluator's raw text response into a structured dict.

    Handles cases where the LLM wraps JSON in markdown code fences,
    and cases where preamble text appears before the code fence.
    """
    text = raw_text.strip()

    # Try direct JSON parse first
    try:
        output = json.loads(text)
        _validate_output_structure(output)
        return output
    except (json.JSONDecodeError, EvaluatorError):
        pass

    # Extract JSON from markdown code fence (may have preamble text before it)
    import re
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        try:
            output = json.loads(fence_match.group(1))
            _validate_output_structure(output)
            return output
        except json.JSONDecodeError:
            pass

    # Last resort: find the first { and last } and try to parse that
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            output = json.loads(text[first_brace:last_brace + 1])
            _validate_output_structure(output)
            return output
        except json.JSONDecodeError:
            pass

    raise EvaluatorError(
        f"Failed to parse evaluator output as JSON.\n"
        f"Raw text (first 500 chars): {raw_text[:500]}"
    )


def _validate_output_structure(output: dict) -> None:
    """Validate that the output has the required top-level structure."""
    required_keys = {
        "per_turn_observations",
        "pass_classifications",
        "gap_observations",
        "session_narratives",
    }
    missing = required_keys - set(output.keys())
    if missing:
        raise EvaluatorError(
            f"Evaluator output missing required keys: {missing}"
        )

    if not output["per_turn_observations"]:
        raise EvaluatorError("per_turn_observations must not be empty")
    if not output["pass_classifications"]:
        raise EvaluatorError("pass_classifications must not be empty")
    if not output["session_narratives"]:
        raise EvaluatorError("session_narratives must not be empty")


class EvaluatorError(Exception):
    """Raised when the evaluator agent fails to produce valid output."""
