"""
Proposer agent

Reads evaluator output and the full canonical knowledge base (gap records,
decisions, archive entries) — NOT the summary layer for authoritative state.
Produces a batch of proposal intents, each with a four-part rationale and
an authoring addendum.

Spec refs:
- docs/spec/03-agents/proposer.md
- docs/spec/01-data-structures/proposal.md

Constraints:
- No scalar grades, no rankings, no priority numbers.
- Fresh context per invocation (context isolation).
- Every cited gap, session, and prior decision resolves to a real record.
- Forced-novelty probability honored from config.
- Proposer does NOT produce diffs (author's job).
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from claude_reflect.agents.claude_runner import ClaudeRunnerError, invoke_claude
from claude_reflect.storage.gap_record import read_gap_record, update_gap_record
from claude_reflect.storage.archive_entry import ArchiveEntryError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CHANGE_TYPES = frozenset({"addition", "modification", "removal", "restructuring"})
VALID_SURFACES = frozenset({"claude_md", "skill", "agent", "hook", "settings", "mcp"})
VALID_NOVELTY_STATUSES = frozenset({"normal", "forced_novelty", "null_baseline"})

SYSTEM_PROMPT = """\
You are the proposer agent for the claude-reflect. Your role is to read the \
evaluator's report and the canonical knowledge base, then produce a batch of \
proposal intents — specific, actionable changes to the target project's \
Claude Code configuration.

## Behavioral directives

- EVIDENCE-GROUNDED PROPOSALS: Every proposal cites specific sessions, turns, \
and gaps. "The evaluator said this was a problem" is not sufficient.
- REUSE HISTORICAL LEARNING: Before proposing, check what has been tried. Do \
not re-propose rejected patterns without substantial change.
- KEEP THE AUTHORING ADDENDUM SPECIFIC: The author agent is fresh-context and \
does not see the 'how' prose. The addendum must carry everything needed.
- PREFER SMALLER CHANGES: A minimal change that addresses a gap is preferable \
to an ambitious change that addresses several.
- SIMPLICITY CRITERION: If a proposal could equivalently be stated as "remove \
something" or "add something," prefer remove when possible.
- MULTI-DIMENSIONAL PRIORITIZATION: Consider frequency, recency, and magnitude \
jointly. Do NOT collapse to a single axis.
- NO SCORING: Never produce scalar grades, confidence values, or rankings.
- NO PRIORITY RANKING: Proposals have no priority ordering.

## Output format

You MUST produce a JSON object with these top-level keys:
- batch_id: string (use the provided batch_id)
- run_id: string (use the provided run_id)
- created_at: ISO datetime string
- window: {"start": date_string, "end": date_string}
- proposal_ids: array of proposal_id strings
- batch_narrative: prose summary for the human (names count of proposals, \
what kinds of gaps they target, whether any are forced-novelty)
- contains_forced_novelty: boolean
- proposals: array of proposal objects

### Proposal object schema:
{
  "proposal_id": string,
  "batch_id": string,
  "run_id": string,
  "created_at": ISO datetime string,
  "title": one-line heading,
  "why": {
    "cited_gaps": [{"gap_id": string, "addressing_note": string}],
    "cited_sessions": [{"session_id": string, "turn_range": {"start": int, "end": int}}],
    "cited_prior_decisions": [{"decision_id": string, "relational_note": string}],
    "prose_summary": string
  },
  "what": {
    "diff_reference": null,
    "files_touched": null,
    "short_description": string
  },
  "how": string (mechanism explanation),
  "prediction": string (expected impact),
  "structural_tags": {
    "change_type": one of ["addition", "modification", "removal", "restructuring"],
    "surface": one of ["claude_md", "skill", "agent", "hook", "settings", "mcp"],
    "novelty_status": one of ["normal", "forced_novelty", "null_baseline"],
    "exploration_rationale": string (required if novelty_status != "normal")
  },
  "authoring_addendum": {
    "actions": [{"type": one of ["create", "modify", "delete"], "target_path": string}],
    "purpose": string,
    "activation_conditions": string (optional),
    "behavior_constraints": [string],
    "examples": [string] (optional),
    "style_hints": string (optional),
    "reference_material": [string] (optional)
  }
}

## Forced-novelty

If the forced_novelty flag is set in your context, you MUST include one \
proposal with novelty_status "forced_novelty" (or "null_baseline"). This \
proposal must be structurally different from recent proposals. Be honest in \
the 'how' prose that evidence is thin; the exploration is justified by \
maintaining the system's map of the space.

## Critical constraints

- diff_reference and files_touched MUST be null (the author fills those in).
- NO scalar grades, scores, priorities, severities, confidences, or rankings.
- Output ONLY valid JSON matching the schema above. No markdown wrapping.
"""


# ---------------------------------------------------------------------------
# Forced-novelty roll logic
# ---------------------------------------------------------------------------


def check_forced_novelty(
    forced_novelty_probability: float,
    null_baseline_probability: float,
) -> Dict[str, Any]:
    """
    Determine whether a forced-novelty proposal is due for this run.

    Uses random.random() for the roll. The first roll checks against
    forced_novelty_probability (strict less-than). If triggered, a second
    roll checks against null_baseline_probability to decide between
    forced_novelty and null_baseline.

    Args:
        forced_novelty_probability: Probability of triggering forced-novelty
            (e.g. 0.2 for 20%).
        null_baseline_probability: Probability of null-baseline given
            forced-novelty triggered (e.g. 0.01 for 1%).

    Returns:
        Dict with keys:
        - triggered: bool
        - novelty_status: "normal" | "forced_novelty" | "null_baseline"
    """
    roll = random.random()
    if roll < forced_novelty_probability:
        # Forced-novelty triggered — check for null-baseline
        second_roll = random.random()
        if second_roll < null_baseline_probability:
            return {"triggered": True, "novelty_status": "null_baseline"}
        return {"triggered": True, "novelty_status": "forced_novelty"}
    return {"triggered": False, "novelty_status": "normal"}


# ---------------------------------------------------------------------------
# Knowledge base reading (canonical layers only)
# ---------------------------------------------------------------------------


def _read_gap_records(repo: Path) -> List[dict]:
    """Read all gap records from the canonical layer."""
    gaps_dir = repo / ".claude-reflect" / "gaps"
    if not gaps_dir.exists():
        return []
    records = []
    for gf in sorted(gaps_dir.glob("*.json")):
        try:
            records.append(json.loads(gf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _read_archive_entries(repo: Path) -> List[dict]:
    """Read all archive entries from the canonical layer."""
    archive_dir = repo / ".claude-reflect" / "archive"
    if not archive_dir.exists():
        return []
    entries = []
    for af in sorted(archive_dir.glob("*.json")):
        try:
            entries.append(json.loads(af.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def _read_decisions(repo: Path) -> List[dict]:
    """Read recent decisions from the decisions branch via git log.

    Returns parsed decision records from the most recent commits on the
    claude-reflect/decisions branch.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "log", "claude-reflect/decisions", "--format=%B", "-n", "20", "--"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    decisions = []
    for block in result.stdout.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # Try to parse as JSON (commit body contains the decision JSON)
        try:
            decision = json.loads(block)
            decisions.append(decision)
        except json.JSONDecodeError:
            continue
    return decisions


def _format_context_for_prompt(
    evaluator_output: dict,
    gap_records: List[dict],
    archive_entries: List[dict],
    decisions: List[dict],
    forced_novelty_result: Dict[str, Any],
    run_id: str,
    batch_id: str,
    window: Dict[str, str],
) -> str:
    """Format all context for the proposer prompt."""
    parts = []

    # Run metadata
    parts.append(f"## Run metadata")
    parts.append(f"run_id: {run_id}")
    parts.append(f"batch_id: {batch_id}")
    parts.append(f"window: {window['start']} to {window['end']}")
    parts.append(f"forced_novelty: {forced_novelty_result['triggered']}")
    if forced_novelty_result["triggered"]:
        parts.append(f"novelty_type: {forced_novelty_result['novelty_status']}")
    parts.append("")

    # Evaluator output
    parts.append("## Evaluator report (primary input)")
    parts.append(json.dumps(evaluator_output, indent=2))
    parts.append("")

    # Gap records (canonical layer)
    parts.append("## Gap records (canonical layer — authoritative)")
    if gap_records:
        for gap in gap_records:
            parts.append(f"- ID: {gap.get('identifier', 'unknown')}")
            parts.append(f"  Kind: {gap.get('kind', 'unknown')}")
            parts.append(f"  Status: {gap.get('status', 'unknown')}")
            parts.append(f"  Occurrences: {gap.get('occurrence_count', 0)}")
            parts.append(f"  Last observed: {gap.get('last_observed_at', 'unknown')}")
            related = gap.get("related_proposals", [])
            if related:
                parts.append(f"  Related proposals: {related}")
            parts.append("")
    else:
        parts.append("No gap records yet.")
        parts.append("")

    # Archive entries
    parts.append("## Archive entries (canonical layer)")
    if archive_entries:
        for entry in archive_entries:
            status = "ACTIVE" if entry.get("active_at", {}).get("end") is None else "superseded"
            parts.append(f"- ID: {entry.get('entry_id', 'unknown')} [{status}]")
            parts.append(f"  Git ref: {entry.get('git_reference', 'unknown')}")
            fp = entry.get("structural_fingerprint", {})
            if fp:
                parts.append(f"  Fingerprint: {json.dumps(fp)}")
            parts.append("")
    else:
        parts.append("No archive entries yet.")
        parts.append("")

    # Recent decisions
    parts.append("## Recent decisions (canonical layer)")
    if decisions:
        for dec in decisions[:10]:
            parts.append(f"- Proposal: {dec.get('proposal_id', 'unknown')}")
            parts.append(f"  Status: {dec.get('status', 'unknown')}")
            parts.append(f"  Targeted gaps: {dec.get('targeted_gaps', [])}")
            reasoning = dec.get("human_reasoning", "")
            if reasoning:
                parts.append(f"  Human reasoning: {reasoning}")
            parts.append("")
    else:
        parts.append("No prior decisions.")
        parts.append("")

    return "\n".join(parts)


def _append_to_related_proposals(
    repo: Path, gap_id: str, proposal_id: str
) -> None:
    """Append proposal_id to a gap record's related_proposals list."""
    try:
        existing = read_gap_record(repo, gap_id)
        related = existing.get("related_proposals", [])
        if proposal_id not in related:
            related.append(proposal_id)
            update_gap_record(repo, gap_id, {"related_proposals": related})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main propose function
# ---------------------------------------------------------------------------


def propose(
    evaluator_output: dict,
    repo: Path,
    run_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    window: Optional[Dict[str, str]] = None,
    model: str = "claude-opus-4-6",
    forced_novelty_probability: float = 0.20,
    null_baseline_probability: float = 0.01,
    write_gap_updates: bool = True,
) -> dict:
    """
    Run the proposer agent to generate a batch of proposal intents.

    Reads canonical layers (gap records, decisions, archive entries) — not
    the summary layer for authoritative state. Produces a batch of proposal
    intents with rationale and authoring addendum.

    Args:
        evaluator_output: The evaluator's structured report for this run.
        repo: Root of the target git repository.
        run_id: Identifier for this run (auto-generated if None).
        batch_id: Identifier for this batch (auto-generated if None).
        window: {"start": date_str, "end": date_str} for the session window.
        model: Anthropic model to use for the proposer.
        forced_novelty_probability: Probability of forced-novelty trigger.
        null_baseline_probability: Probability of null-baseline given trigger.
        write_gap_updates: Whether to update gap records' related_proposals.

    Returns:
        Proposal batch dict matching the proposal batch schema.

    Raises:
        ProposerError: If the agent fails to produce valid output.
    """
    if run_id is None:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
    if batch_id is None:
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    if window is None:
        window = {"start": "", "end": ""}

    # Forced-novelty roll
    forced_novelty_result = check_forced_novelty(
        forced_novelty_probability, null_baseline_probability
    )

    # Read canonical layers
    gap_records = _read_gap_records(repo)
    archive_entries = _read_archive_entries(repo)
    decisions = _read_decisions(repo)

    # Format context
    context = _format_context_for_prompt(
        evaluator_output=evaluator_output,
        gap_records=gap_records,
        archive_entries=archive_entries,
        decisions=decisions,
        forced_novelty_result=forced_novelty_result,
        run_id=run_id,
        batch_id=batch_id,
        window=window,
    )

    # Invoke the proposer agent via claude_runner
    try:
        raw_text = invoke_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=context,
            model=model,
            label="proposer",
        )
    except ClaudeRunnerError as e:
        raise ProposerError(f"Claude invocation failed: {e}") from e

    batch = _parse_proposer_output(raw_text)

    # Validate the batch
    _validate_batch(batch, run_id, batch_id)

    # Write gap record side effects (append proposal_id to related_proposals)
    if write_gap_updates:
        for proposal in batch.get("proposals", []):
            for cited_gap in proposal.get("why", {}).get("cited_gaps", []):
                gap_id = cited_gap.get("gap_id")
                if gap_id:
                    _append_to_related_proposals(
                        repo, gap_id, proposal["proposal_id"]
                    )

    return batch


def propose_from_fixture(
    evaluator_output: dict,
    repo: Path,
    run_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    window: Optional[Dict[str, str]] = None,
    model: str = "claude-opus-4-6",
    forced_novelty_probability: float = 0.20,
    null_baseline_probability: float = 0.01,
) -> dict:
    """
    Convenience: run the proposer with gap-update side effects disabled.

    Suitable for fixture-based testing where gap records may not exist.
    """
    return propose(
        evaluator_output=evaluator_output,
        repo=repo,
        run_id=run_id,
        batch_id=batch_id,
        window=window,
        model=model,
        forced_novelty_probability=forced_novelty_probability,
        null_baseline_probability=null_baseline_probability,
        write_gap_updates=False,
    )


# ---------------------------------------------------------------------------
# Output parsing and validation
# ---------------------------------------------------------------------------


def _parse_proposer_output(raw_text: str) -> dict:
    """Parse the proposer's raw text response into a structured dict.

    Tolerant of preamble prose and ```json``` fences — the model sometimes
    emits both even when the system prompt forbids markdown wrapping.
    """
    from claude_reflect.agents._json_parsing import extract_json

    try:
        output = extract_json(raw_text)
    except json.JSONDecodeError as e:
        raise ProposerError(
            f"Failed to parse proposer output as JSON: {e}\n"
            f"Raw text (first 500 chars): {raw_text[:500]}"
        ) from e

    if not isinstance(output, dict):
        raise ProposerError(
            f"Proposer output is not a JSON object (got {type(output).__name__})"
        )
    return output


def _validate_batch(batch: dict, run_id: str, batch_id: str) -> None:
    """Validate the proposal batch structure."""
    required_keys = {
        "batch_id", "run_id", "created_at", "window",
        "proposal_ids", "batch_narrative", "contains_forced_novelty", "proposals",
    }
    missing = required_keys - set(batch.keys())
    if missing:
        raise ProposerError(f"Proposal batch missing required keys: {missing}")

    if not batch["proposals"]:
        raise ProposerError("Proposal batch must contain at least one proposal")

    # Validate each proposal has required structure
    for proposal in batch["proposals"]:
        _validate_proposal(proposal)


def _validate_proposal(proposal: dict) -> None:
    """Validate a single proposal structure."""
    required_keys = {
        "proposal_id", "batch_id", "run_id", "created_at", "title",
        "why", "what", "how", "prediction", "structural_tags",
        "authoring_addendum",
    }
    missing = required_keys - set(proposal.keys())
    if missing:
        raise ProposerError(
            f"Proposal {proposal.get('proposal_id', '?')} missing keys: {missing}"
        )

    # Validate why section
    why = proposal.get("why", {})
    if not why.get("cited_gaps"):
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has no cited_gaps"
        )
    if not why.get("prose_summary"):
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has no prose_summary"
        )

    # Validate structural tags
    tags = proposal.get("structural_tags", {})
    if tags.get("change_type") not in VALID_CHANGE_TYPES:
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has invalid change_type: "
            f"{tags.get('change_type')}"
        )
    if tags.get("surface") not in VALID_SURFACES:
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has invalid surface: "
            f"{tags.get('surface')}"
        )
    if tags.get("novelty_status") not in VALID_NOVELTY_STATUSES:
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has invalid novelty_status: "
            f"{tags.get('novelty_status')}"
        )

    # Validate authoring addendum
    addendum = proposal.get("authoring_addendum", {})
    if not addendum.get("actions"):
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} addendum has no actions"
        )
    if not addendum.get("purpose"):
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} addendum has no purpose"
        )
    if not addendum.get("behavior_constraints"):
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} addendum has no behavior_constraints"
        )

    # Ensure diff_reference and files_touched are null (proposer doesn't produce diffs)
    what = proposal.get("what", {})
    if what.get("diff_reference") is not None:
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has non-null diff_reference — "
            "proposer must not produce diffs"
        )
    if what.get("files_touched") is not None:
        raise ProposerError(
            f"Proposal {proposal['proposal_id']} has non-null files_touched — "
            "proposer must not produce diffs"
        )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ProposerError(Exception):
    """Raised when the proposer agent fails to produce valid output."""
