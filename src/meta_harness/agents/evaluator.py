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

import json
import sys
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


def _format_sessions_for_prompt(sessions: List[Session]) -> str:
    """Format session data as a string for the evaluator prompt."""
    parts = []
    for session in sessions:
        parts.append(f"## Session: {session.session_id}")
        parts.append(f"Start: {session.start_time.isoformat()}")
        parts.append(f"End: {session.end_time.isoformat()}")
        parts.append(f"Turns: {len(session.turns)}")
        parts.append("")
        for i, turn in enumerate(session.turns):
            parts.append(f"### Turn {i}")
            if turn.human_input:
                parts.append(f"Human: {turn.human_input}")
            if turn.assistant_response:
                parts.append(f"Assistant: {turn.assistant_response}")
            if turn.tool_calls:
                tc_str = ", ".join(f"{tc.name}" for tc in turn.tool_calls)
                parts.append(f"Tool calls: {tc_str}")
            if turn.model:
                parts.append(f"Model: {turn.model}")
            if turn.input_tokens is not None:
                total = (turn.input_tokens or 0) + (turn.output_tokens or 0)
                parts.append(f"Tokens: {total}")
            parts.append("")
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


def _estimate_session_chars(session: "Session") -> int:
    """Estimate the character count for a formatted session."""
    count = len(session.session_id) + 80  # header lines
    for turn in session.turns:
        count += len(turn.human_input or "") + len(turn.assistant_response or "")
        count += 100  # metadata lines per turn
    return count


def _split_into_batches(
    sessions: List["Session"], max_chars: int = _MAX_PROMPT_CHARS
) -> List[List["Session"]]:
    """Split sessions into batches that fit within the prompt size limit."""
    batches: List[List["Session"]] = []
    current_batch: List["Session"] = []
    current_chars = 0

    for session in sessions:
        session_chars = _estimate_session_chars(session)
        if current_batch and current_chars + session_chars > max_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(session)
        current_chars += session_chars

    if current_batch:
        batches.append(current_batch)

    return batches


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


def _evaluate_batch(
    sessions: List["Session"],
    repo: Path,
    model: str,
    existing_gaps: str,
    label: Optional[str] = None,
) -> dict:
    """Run the evaluator on a single batch of sessions."""
    session_text = _format_sessions_for_prompt(sessions)

    user_prompt = (
        f"Evaluate the following session logs. Produce a complete evaluator "
        f"output JSON document covering all sessions and all turns.\n\n"
        f"{existing_gaps}\n\n"
        f"## Session logs to evaluate\n\n{session_text}"
    )

    try:
        raw_text = invoke_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
            label=label,
        )
    except ClaudeRunnerError as e:
        raise EvaluatorError(f"Claude invocation failed: {e}") from e

    return _parse_evaluator_output(raw_text)


def evaluate(
    sessions: List[Session],
    repo: Path,
    model: str = "claude-sonnet-4-6",
    write_gap_records: bool = True,
) -> dict:
    """
    Run the evaluator agent on the given sessions.

    Automatically batches sessions if the combined prompt would exceed
    the context window, running separate evaluator calls and merging
    the results.

    Args:
        sessions: List of Session objects to evaluate.
        repo: Root of the target git repository (for gap record access).
        model: Anthropic model to use for evaluation.
        write_gap_records: Whether to write gap record side effects.

    Returns:
        Evaluator output dict matching the evaluator-output schema.

    Raises:
        EvaluatorError: If the agent fails to produce valid output.
    """
    if not sessions:
        raise EvaluatorError("No sessions provided for evaluation")

    existing_gaps = _format_existing_gaps(repo)
    batches = _split_into_batches(sessions)

    total = len(batches)
    if total == 1:
        output = _evaluate_batch(
            batches[0], repo, model, existing_gaps,
            label=f"evaluator ({len(sessions)} sessions)",
        )
    else:
        batch_outputs = []
        for i, batch in enumerate(batches):
            label = f"evaluator batch {i + 1}/{total} ({len(batch)} sessions)"
            print(f"  {label}...", file=sys.stderr, flush=True)
            batch_output = _evaluate_batch(
                batch, repo, model, existing_gaps, label=label,
            )
            batch_outputs.append(batch_output)
        output = _merge_evaluator_outputs(batch_outputs)

    # Write gap record side effects
    if write_gap_records and output.get("gap_observations"):
        output["gap_observations"] = _write_gap_side_effects(
            repo, output["gap_observations"]
        )

    return output


def evaluate_from_jsonl(
    session_paths: List[Path],
    repo: Path,
    model: str = "claude-sonnet-4-6",
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
