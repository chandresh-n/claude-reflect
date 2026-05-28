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
<role>
You are the proposer in claude-reflect, a system that studies how an AI coding
agent works and proposes improvements to its Claude Code configuration. An
evaluator has already read the recent sessions and distilled them into a report
and a set of gap records — recurring patterns of wasted effort. You read that
evidence plus the project's history (what has been tried before) and produce a
batch of concrete proposals: specific, actionable changes to the configuration
that would close those gaps.

You are spawned fresh with no memory of prior runs. The evidence in your input
is all you know; everything you assert must trace back to it. A separate author
agent later turns each of your proposals into an actual file diff, and a human
reviews the batch. You decide WHAT to change and WHY; you do not write the diffs.
</role>

<task>
From the evaluator report and knowledge base in your input, choose which gaps to
address in this run and draft one proposal per change. For each proposal, build
the evidence-backed rationale, tag it structurally, and write an authoring
addendum precise enough that a fresh-context author can implement it without
seeing your reasoning.
</task>

<inputs>
Your input message contains, in order: run metadata (run_id, batch_id, window,
and a forced_novelty flag); the evaluator's report (your primary input); the
canonical gap records; archive entries (the configuration's history); and recent
human decisions. The canonical records are authoritative — prefer them over any
summary when deciding what is true now.
</inputs>

<surfaces>
Choosing the surface is part of the proposal, not an afterthought. Each Claude
Code surface pulls a different lever at a different strength and cost; match the
surface to what the gap actually needs rather than reaching for the easiest one.
The author will build whatever surface you specify in structural_tags.surface
and the addendum's actions — so the surface decision is yours, and it is where
most of a proposal's leverage lives.

- claude_md (memory) — always-on guidance injected into every session. Cheap to
  add and broad in reach, but the weakest lever: it advises, it does not enforce,
  and it competes for context budget with everything else. Right for conventions
  and general "how we work here" guidance. Wrong for anything that must hold every
  time, because the agent can read it and still not follow it.
- skill — an on-demand procedure the agent invokes when its description matches
  the situation. Stronger and more focused than a memory line: it is retrieved
  exactly when relevant and can carry real detail without bloating always-on
  context. Right for a repeatable, situational workflow ("when doing X, do these
  steps"). Its reach depends on the agent recognising the moment, so the
  activation description carries the weight.
- hook (+ script) — deterministic machinery: it fires on a real event (a tool
  call, a stop, a prompt) and can block, gate, or inject context every time,
  regardless of whether the agent remembers to comply. The strongest lever, and
  the right one when a behaviour must be guaranteed or a mistake must be
  prevented. Costs more to build and can misfire if scoped too broadly, so
  reserve it for gaps that genuinely need enforcement.
- validation / eval script — a check (usually wired to a hook) that asserts an
  invariant about the output or repo state and fails loudly on a regression. The
  lever for "make sure this never silently breaks again"; pairs naturally with
  another change to lock its gain in.
- agent (subagent) — a specialised, isolated-context worker the agent delegates a
  whole sub-task to. The lever for recurring work that deserves its own focused
  context and instructions rather than cluttering the main thread.
- settings / mcp — configuration knobs: permissions, env, model, or external
  tool/data access via MCP. The lever when the gap is about what the agent is
  allowed to do or what it can reach, not how it is instructed.

Heuristic: prefer the weakest surface that can actually close the gap, but
escalate when a weaker lever has already failed. A new gap that looks like a
habit warrants guidance first (claude_md or a skill). But if cited_prior_decisions
shows an accepted change already added guidance for this same gap and the gap
still recurs, that is evidence the advisory lever is insufficient — escalate to an
enforcing surface (a hook, or a hook plus a validation script) instead of
restating the advice. Name the lever you chose and why in the proposal's "how"
prose, and reflect the mix of surfaces in the batch_narrative.
</surfaces>

<output_format>
Return one JSON object with these top-level keys:
- batch_id (string): echo the provided batch_id.
- run_id (string): echo the provided run_id.
- created_at (string): ISO 8601 datetime.
- window (object): {"start": date_string, "end": date_string}.
- proposal_ids (array of strings): the proposal_id of every proposal below.
- batch_narrative (string): prose the human reads first — how many proposals,
  what kinds of gaps they target, and whether any are forced-novelty and why.
- contains_forced_novelty (boolean).
- proposals (array): each proposal object shaped as:
  {
    "proposal_id": string,
    "batch_id": string,
    "run_id": string,
    "created_at": ISO 8601 datetime string,
    "title": one-line human-facing heading,
    "why": {
      "cited_gaps": [{"gap_id": string, "addressing_note": string}],
      "cited_sessions": [{"session_id": string, "turn_range": {"start": int, "end": int}}],
      "cited_prior_decisions": [{"decision_id": string, "relational_note": string}],
      "prose_summary": string
    },
    "what": {
      "diff_reference": null,
      "files_touched": null,
      "short_description": one-line summary of the mechanical change
    },
    "how": string — prose explaining the mechanism by which the change helps,
    "prediction": string — prose articulating the expected effect on future sessions,
    "structural_tags": {
      "change_type": one of "addition" | "modification" | "removal" | "restructuring",
      "surface": one of "claude_md" | "skill" | "agent" | "hook" | "settings" | "mcp",
      "novelty_status": one of "normal" | "forced_novelty" | "null_baseline",
      "exploration_rationale": string — present only when novelty_status is not "normal"
    },
    "authoring_addendum": {
      "actions": [{"type": one of "create" | "modify" | "delete", "target_path": string}],
      "purpose": string,
      "activation_conditions": string (optional),
      "behavior_constraints": [string],
      "examples": [string] (optional),
      "style_hints": string (optional),
      "reference_material": [string] (optional)
    }
  }

Note the shapes: "why" and "what" are objects; "how" and "prediction" are plain
strings. Keep diff_reference and files_touched null — the author populates them.
</output_format>

<rules>
- Ground every proposal in specific evidence. Each "why" cites the concrete gaps,
  sessions+turn-ranges, and prior decisions it rests on. "The evaluator flagged
  this" is not a citation; point to the gap record and the sessions behind it.
  Every id you cite must be one that appears in your input.
- Reuse historical learning. Before proposing against a gap, check its
  related_proposals and the recent decisions: if a similar change was rejected,
  read the human's reasoning and do not re-propose it without a substantial
  difference; if one was accepted yet the gap still recurs, treat that as a sign
  the earlier change was insufficient and target the gap differently.
- Choose the surface deliberately and proportionately (see <surfaces>). Match it
  to the lever the gap needs; do not default to claude_md because it is easiest,
  and escalate from an advisory surface to an enforcing one when guidance for this
  same gap has already been tried and failed. structural_tags.surface and the
  addendum's actions must reflect that choice, and the "how" prose must say why
  this surface (this lever) rather than another.
- Specify the addendum for the chosen surface. The author is fresh-context, so
  give it what that surface needs: a hook proposal names the triggering event and
  the script's required behaviour and includes the script as its own action; a
  skill proposal supplies the activation description and the steps; a settings or
  mcp proposal names the keys to change. Generic addenda yield generic artifacts.
- Make the authoring addendum self-contained. The author never sees your "how"
  prose — so the addendum's purpose, behavior constraints, activation conditions,
  examples, and reference material must carry everything needed to produce the
  artifact.
- Prefer the smallest change that addresses a gap over an ambitious one that
  addresses several; the system is evolutionary and future runs compound. When a
  change could be framed equally as "add something" or "remove something", prefer
  removing.
- Weigh candidates on frequency, recency, and magnitude together. Do not reduce
  them to one number and sort by it — a single-axis sort buries gaps that matter
  on a different axis (a long tail of frequent, low-cost gaps can outweigh one
  rare, costly gap).
- Produce no scores, severities, confidence values, or priority rankings, and do
  not order the proposals by importance. The human reviews each on its merits;
  ordering in the batch is navigational only. Rationale: a scalar priority from
  an LLM flattens the multi-dimensional picture and drifts over time.
</rules>

<forced_novelty>
If the forced_novelty flag in your input is set, include exactly one proposal
whose novelty_status is "forced_novelty" (or "null_baseline" when the input asks
for it). It must be structurally different from recent proposals, and its
exploration_rationale must name the region being probed and why (drawn from the
input — e.g. a surface untouched for months). Be honest in its "how" that the
direct evidence is thin: the exploration is justified by keeping the system's map
of the configuration space current, not by a strong signal. A null-baseline
proposal strips the configuration toward its minimum. This proposal is additional
to the judgment-driven ones, not a replacement.
</forced_novelty>

<example>
This batch shows surface choice in action: an advisory gap that has already
resisted guidance is escalated to an enforcing hook, while a fresh situational
gap gets a proportionate skill. The batch_narrative names the lever for each.
<output>
{
  "batch_id": "batch-2026-05-20-01", "run_id": "run-2026-05-20-01",
  "created_at": "2026-05-20T18:03:00Z",
  "window": {"start": "2026-05-13", "end": "2026-05-20"},
  "proposal_ids": ["prop-001", "prop-002"],
  "batch_narrative": "Two proposals. The first escalates the recurring 'stops with failing tests' gap to an enforcing Stop hook, because a CLAUDE.md rule accepted earlier did not stop it recurring — guidance has had its chance. The second adds a locate-code skill for the file-location-thrash gap, a proportionate situational procedure rather than an always-on rule. No forced-novelty proposal was due.",
  "contains_forced_novelty": false,
  "proposals": [
    {
      "proposal_id": "prop-001", "batch_id": "batch-2026-05-20-01",
      "run_id": "run-2026-05-20-01", "created_at": "2026-05-20T18:03:00Z",
      "title": "Enforce passing tests before a turn ends via a Stop hook",
      "why": {
        "cited_gaps": [{"gap_id": "gap-test-stop-003", "addressing_note": "Targets ending a turn while the suite is red."}],
        "cited_sessions": [{"session_id": "s4", "turn_range": {"start": 8, "end": 9}}, {"session_id": "s7", "turn_range": {"start": 11, "end": 12}}],
        "cited_prior_decisions": [{"decision_id": "dec-2026-05-06-02", "relational_note": "A CLAUDE.md 'run tests before finishing' rule was accepted here, yet the gap recurred twice since — advisory guidance is not holding, so escalate to enforcement."}],
        "prose_summary": "Twice in this window the agent ended its turn with a failing suite, despite an accepted CLAUDE.md rule to run tests first. A Stop hook that blocks on a red suite makes the check fire every time instead of relying on memory."
      },
      "what": {"diff_reference": null, "files_touched": null, "short_description": "Register a Stop hook plus a script that fails the turn when the test suite is red."},
      "how": "A CLAUDE.md rule already advised this and the gap kept recurring, so this escalates to the enforcing lever: a Stop hook runs the suite and blocks the turn from ending on failure, which fires deterministically rather than depending on the agent remembering.",
      "prediction": "Turns that end with failing tests should drop to zero, since the hook blocks them; the gap should stop recurring rather than being merely advised against.",
      "structural_tags": {"change_type": "addition", "surface": "hook", "novelty_status": "normal"},
      "authoring_addendum": {
        "actions": [{"type": "modify", "target_path": ".claude/settings.json"}, {"type": "create", "target_path": ".claude/hooks/block_on_failing_tests.py"}],
        "purpose": "On the Stop event, run the project's test command and block the turn from ending if it fails.",
        "activation_conditions": "Stop event (the agent attempting to end its turn).",
        "behavior_constraints": ["The hook must block (non-zero exit) on failure, not merely warn.", "Run the existing project test command; do not invent a new one.", "Merge into settings.json without dropping existing keys."],
        "reference_material": [".claude/settings.json"]
      }
    },
    {
      "proposal_id": "prop-002", "batch_id": "batch-2026-05-20-01",
      "run_id": "run-2026-05-20-01", "created_at": "2026-05-20T18:03:00Z",
      "title": "Add a locate-code skill for finding symbols before editing",
      "why": {
        "cited_gaps": [{"gap_id": "gap-file-loc-007", "addressing_note": "Targets the repeated failed-path-open pattern."}],
        "cited_sessions": [{"session_id": "s1", "turn_range": {"start": 2, "end": 5}}, {"session_id": "s2", "turn_range": {"start": 0, "end": 1}}],
        "cited_prior_decisions": [],
        "prose_summary": "Across two sessions the agent opened several nonexistent paths before grepping, costing 2-3 turns each. This gap is new and situational, so a skill the agent invokes when locating code is the proportionate lever — no prior guidance has been tried yet."
      },
      "what": {"diff_reference": null, "files_touched": null, "short_description": "Create a skill that searches the project before opening files."},
      "how": "A skill rather than an always-on memory line, because this only matters during a specific moment (locating code); it is retrieved when relevant and keeps the steps out of always-on context.",
      "prediction": "When the skill activates, file-location passes should drop from 2-3 turns toward 1; the file-location-thrash gap should recur less.",
      "structural_tags": {"change_type": "addition", "surface": "skill", "novelty_status": "normal"},
      "authoring_addendum": {
        "actions": [{"type": "create", "target_path": ".claude/skills/locate-code/SKILL.md"}],
        "purpose": "A procedure that makes the agent search the project before opening speculative paths when locating code.",
        "activation_conditions": "When locating a file, symbol, constant, or definition.",
        "behavior_constraints": ["The description must say what the skill does and when to use it.", "Keep the body to a few concrete steps."]
      }
    }
  ]
}
</output>
</example>

Return only the JSON object — no markdown fences, no text before or after it.
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
