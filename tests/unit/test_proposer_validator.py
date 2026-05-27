"""Unit tests for proposer output schema enforcement.

Policy under test (per docs/spec/01-data-structures/proposal.md and the
c3b iteration plan):

  - Try ONE coercion pass to normalize common shape drifts:
    string-typed sections, missing proposal_id, missing scalar fields.
  - After coercion, validate the shape. Drop only if the proposal still
    cannot be made sensible (not a dict, no usable content).
  - Both repairs and drops surface as descriptive notes so the caller
    can mark the run complete_with_errors and tell the operator what
    happened.
"""
from __future__ import annotations

import pytest

from claude_reflect.agents.proposer_validator import (
    coerce_proposal,
    coerce_proposal_batch,
)


# ---------------------------------------------------------------------------
# Single-proposal coercion
# ---------------------------------------------------------------------------


def _well_formed_proposal() -> dict:
    """The spec-compliant shape every test starts from."""
    return {
        "proposal_id": "prop-001",
        "title": "Test proposal",
        "why": {
            "prose_summary": "tool-call loop in 3 sessions",
            "cited_gaps": [],
            "cited_sessions": [],
            "cited_prior_decisions": [],
        },
        "what": {
            "short_description": "Add a stop rule to CLAUDE.md",
            "diff_reference": None,
            "files_touched": [],
        },
        "how": {"mechanism_prose": "Append a 'When to stop' section"},
        "prediction": {"expected_impact_prose": "Loops drop 60%"},
    }


def test_well_formed_proposal_passes_through_unchanged() -> None:
    """A spec-compliant proposal must be returned unmodified with no
    repairs."""
    p = _well_formed_proposal()
    out = coerce_proposal(p)
    assert not out.dropped
    assert out.repairs == [], (
        f"well-formed proposal must have zero repairs, got {out.repairs!r}"
    )
    # All canonical sections preserved as dicts.
    for section in ("why", "what", "how", "prediction"):
        assert isinstance(out.proposal[section], dict)


def test_string_typed_how_is_normalised_to_dict() -> None:
    """The bug that crashed the renderer pre-fix: how as a plain string.
    Coercion must convert it to {mechanism_prose: <string>}."""
    p = _well_formed_proposal()
    p["how"] = "Append three lines to CLAUDE.md under 'When to stop'."
    out = coerce_proposal(p)
    assert not out.dropped
    assert isinstance(out.proposal["how"], dict)
    assert out.proposal["how"]["mechanism_prose"] == (
        "Append three lines to CLAUDE.md under 'When to stop'."
    )
    assert any("how" in r and "string" in r for r in out.repairs), (
        f"repair note for 'how' string drift expected, got {out.repairs!r}"
    )


def test_string_typed_every_section_is_normalised() -> None:
    """Worst-case shape drift: every section is a string. Each must be
    coerced into its canonical dict shape with the string preserved as
    the appropriate prose field."""
    p = {
        "proposal_id": "prop-allstr",
        "title": "All strings",
        "why": "saw it twice",
        "what": "add a rule",
        "how": "append three lines",
        "prediction": "should fix it",
    }
    out = coerce_proposal(p)
    assert not out.dropped
    assert out.proposal["why"]["prose_summary"] == "saw it twice"
    assert out.proposal["what"]["short_description"] == "add a rule"
    assert out.proposal["how"]["mechanism_prose"] == "append three lines"
    assert out.proposal["prediction"]["expected_impact_prose"] == "should fix it"


def test_missing_proposal_id_is_synthesised() -> None:
    """Renderer + author_results lookup both require a proposal_id."""
    p = _well_formed_proposal()
    del p["proposal_id"]
    out = coerce_proposal(p)
    assert not out.dropped
    assert out.proposal["proposal_id"].startswith("prop-coerced-"), (
        f"synthesised id should be prefixed; got {out.proposal['proposal_id']!r}"
    )
    assert any("proposal_id" in r for r in out.repairs)


def test_missing_title_defaults() -> None:
    """A proposal without title must still render, with a sensible default."""
    p = _well_formed_proposal()
    del p["title"]
    out = coerce_proposal(p)
    assert not out.dropped
    assert out.proposal["title"] == "Untitled proposal"


def test_missing_what_subfields_get_null_and_empty_list_defaults() -> None:
    """``what.diff_reference`` should default to None; ``what.files_touched``
    to []. Renderer + author rely on these shapes."""
    p = _well_formed_proposal()
    p["what"] = {"short_description": "do a thing"}
    out = coerce_proposal(p)
    assert not out.dropped
    assert out.proposal["what"]["diff_reference"] is None
    assert out.proposal["what"]["files_touched"] == []


def test_non_dict_proposal_is_dropped() -> None:
    """A string (or any non-dict) at the proposal level is unrecoverable."""
    out = coerce_proposal("just a string, not a proposal")
    assert out.dropped
    assert out.drop_reason is not None
    assert "dict" in out.drop_reason


def test_proposal_with_no_content_at_all_is_dropped() -> None:
    """If every section is empty after coercion there is nothing to show
    the human; drop with a clear reason."""
    p = {"proposal_id": "prop-empty", "title": "Empty"}
    # No why/what/how/prediction at all.
    out = coerce_proposal(p)
    assert out.dropped, (
        f"a proposal with no sections must be dropped; got {out.proposal!r}"
    )
    assert "empty" in (out.drop_reason or "").lower()


# ---------------------------------------------------------------------------
# Batch-level coercion
# ---------------------------------------------------------------------------


def test_batch_coercion_keeps_recoverable_drops_unrecoverable() -> None:
    """A mixed batch should produce: well-formed pass-throughs, repaired
    proposals (with repair notes), and dropped proposals (with drop
    reasons). All accountable in the BatchCoercionResult."""
    raw = {
        "proposals": [
            _well_formed_proposal(),
            # String-typed how: repairable.
            {**_well_formed_proposal(), "proposal_id": "prop-002", "how": "string how"},
            # Empty: unrecoverable.
            {"proposal_id": "prop-003", "title": "empty"},
            # Not a dict at all: unrecoverable.
            "garbage",
        ],
    }

    out = coerce_proposal_batch(raw)

    # 2 kept (well-formed + repaired), 2 dropped.
    assert out.kept_count == 2, (
        f"expected 2 kept proposals, got {out.kept_count}; "
        f"batch={out.batch!r}"
    )
    assert out.dropped_count == 2

    pids = [p["proposal_id"] for p in out.batch["proposals"]]
    assert "prop-001" in pids
    assert "prop-002" in pids
    assert "prop-003" not in pids

    # Repair notes only for the repaired one.
    assert "prop-001" not in out.repairs_by_proposal, (
        "well-formed proposal must not appear in repairs_by_proposal"
    )
    assert "prop-002" in out.repairs_by_proposal
    assert any("how" in r for r in out.repairs_by_proposal["prop-002"])


def test_batch_coercion_summary_messages() -> None:
    """summary_for_stage_errors emits one informational line per repair
    set and one per drop, ready to be appended to ReviewCommand's
    _stage_errors list so the run reports complete_with_errors."""
    raw = {
        "proposals": [
            {**_well_formed_proposal(), "proposal_id": "prop-r", "how": "str how"},
            {"proposal_id": "prop-d", "title": "drop me"},
        ],
    }
    out = coerce_proposal_batch(raw)
    msgs = out.summary_for_stage_errors()

    assert any("repaired prop-r" in m for m in msgs), (
        f"expected a 'repaired prop-r' message; got {msgs!r}"
    )
    assert any("dropped prop-d" in m for m in msgs), (
        f"expected a 'dropped prop-d' message; got {msgs!r}"
    )


def test_batch_coercion_handles_non_dict_input() -> None:
    """If the proposer returns a string or None at the top level, the
    coercer must not raise — it produces an empty batch with a single
    drop reason."""
    out = coerce_proposal_batch("not a batch")
    assert out.kept_count == 0
    assert out.dropped_count == 1
    assert "entire batch" in out.drops[0]["drop_reason"]


def test_batch_coercion_handles_proposals_field_wrong_type() -> None:
    """A batch dict whose ``proposals`` field is not a list must not
    raise; report it as a drop and return an empty batch."""
    out = coerce_proposal_batch({"proposals": "not a list"})
    assert out.kept_count == 0
    assert out.dropped_count == 1
    assert "list" in out.drops[0]["drop_reason"]


def test_batch_coercion_preserves_top_level_metadata() -> None:
    """Top-level batch fields outside of ``proposals`` (batch_id,
    run_id, batch_narrative, etc.) must pass through unchanged."""
    raw = {
        "batch_id": "batch-xyz",
        "run_id": "run-abc",
        "batch_narrative": "Three proposals this week.",
        "proposals": [_well_formed_proposal()],
    }
    out = coerce_proposal_batch(raw)
    assert out.batch["batch_id"] == "batch-xyz"
    assert out.batch["run_id"] == "run-abc"
    assert out.batch["batch_narrative"] == "Three proposals this week."

    # proposal_ids must be regenerated to reflect kept proposals.
    assert out.batch["proposal_ids"] == ["prop-001"]
