"""Schema enforcement for proposer output.

The proposer occasionally drifts from the spec shape — most commonly
returning a section (``why`` / ``what`` / ``how`` / ``prediction``) as a
plain string instead of a ``{field: prose}`` dict. The renderer was
hardened against the string-variant in commit e3b685c, but a downstream
defensive fix is a backstop, not a contract.

This module is the contract: it normalizes proposer output into a
predictable shape so every consumer (renderer, author, decision
recorder) can rely on the same field layout.

Policy
------

For every proposal in a batch:

  1. Try to **coerce** the proposal into the canonical shape. Single-
     pass repairs include:
       - string-typed section → ``{<known_field>: <string>}`` dict
       - missing ``proposal_id`` → synthesised ``prop-coerced-<short-uuid>``
       - missing scalar sub-field → ``null`` placeholder
       - missing list sub-field → ``[]``
  2. **Re-validate** the result. If the proposal still cannot be made
     sensible (not a dict, no usable content at all), it is **dropped**
     from the batch and the drop is reported.

Each repair carries a short human-readable note so the caller can
surface them to the operator without re-deriving what happened.

Schema reference: ``docs/spec/01-data-structures/proposal.md``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class ProposalCoercionResult:
    """Outcome of coercing a single proposer-generated proposal."""

    proposal: dict | None  # None if the proposal was unrecoverable.
    repairs: list[str] = field(default_factory=list)
    drop_reason: str | None = None  # set iff proposal is None.

    @property
    def dropped(self) -> bool:
        return self.proposal is None


@dataclass
class BatchCoercionResult:
    """Outcome of coercing every proposal in a batch."""

    batch: dict  # The original batch dict with ``proposals`` replaced.
    repairs_by_proposal: dict[str, list[str]] = field(default_factory=dict)
    drops: list[dict] = field(default_factory=list)  # {original, drop_reason}

    @property
    def kept_count(self) -> int:
        return len(self.batch.get("proposals", []))

    @property
    def dropped_count(self) -> int:
        return len(self.drops)

    def summary_for_stage_errors(self) -> list[str]:
        """One stage-error string per repair set + drop, ready to be
        appended to ReviewCommand._stage_errors so the run reports
        complete_with_errors when shape drift was encountered."""
        out: list[str] = []
        for pid, repairs in self.repairs_by_proposal.items():
            if repairs:
                joined = "; ".join(repairs)
                out.append(f"proposer (repaired {pid}): {joined}")
        for drop in self.drops:
            original_id = (
                (drop.get("original") or {}).get("proposal_id")
                or "<no proposal_id>"
            )
            out.append(
                f"proposer (dropped {original_id}): {drop['drop_reason']}"
            )
        return out


def coerce_proposal_batch(raw_batch: Any) -> BatchCoercionResult:
    """Top-level entry point. Returns a BatchCoercionResult whose
    ``batch`` field is safe to hand to the renderer, author, and
    decision recorder.

    If ``raw_batch`` itself is unusable (not a dict, or has no
    ``proposals`` list), the result is an empty batch carrying a
    single drop entry describing the failure — the caller can still
    proceed without crashing."""
    if not isinstance(raw_batch, dict):
        return BatchCoercionResult(
            batch={"proposals": [], "proposal_ids": []},
            drops=[{
                "original": None,
                "drop_reason": (
                    f"proposer returned {type(raw_batch).__name__} instead of a "
                    f"batch dict; entire batch discarded"
                ),
            }],
        )

    raw_proposals = raw_batch.get("proposals")
    if not isinstance(raw_proposals, list):
        return BatchCoercionResult(
            batch={"proposals": [], "proposal_ids": []},
            drops=[{
                "original": None,
                "drop_reason": (
                    f"batch.proposals was "
                    f"{type(raw_proposals).__name__}, expected a list; "
                    f"entire batch discarded"
                ),
            }],
        )

    kept: list[dict] = []
    repairs_by_proposal: dict[str, list[str]] = {}
    drops: list[dict] = []

    for raw in raw_proposals:
        outcome = coerce_proposal(raw)
        if outcome.dropped:
            drops.append({
                "original": raw if isinstance(raw, dict) else None,
                "drop_reason": outcome.drop_reason or "unknown",
            })
            continue
        kept.append(outcome.proposal)
        if outcome.repairs:
            repairs_by_proposal[outcome.proposal["proposal_id"]] = outcome.repairs

    new_batch = dict(raw_batch)
    new_batch["proposals"] = kept
    new_batch["proposal_ids"] = [p["proposal_id"] for p in kept]
    return BatchCoercionResult(
        batch=new_batch,
        repairs_by_proposal=repairs_by_proposal,
        drops=drops,
    )


def coerce_proposal(raw: Any) -> ProposalCoercionResult:
    """Coerce a single proposal dict (or near-dict) into the canonical
    shape. Returns a ProposalCoercionResult. The caller checks
    ``.dropped`` before consuming ``.proposal``."""
    if not isinstance(raw, dict):
        return ProposalCoercionResult(
            proposal=None,
            drop_reason=(
                f"proposal was {type(raw).__name__}, expected a dict"
            ),
        )

    repairs: list[str] = []
    coerced: dict = {}

    # proposal_id: synthesise if missing or empty.
    pid = raw.get("proposal_id")
    if not isinstance(pid, str) or not pid.strip():
        pid = f"prop-coerced-{uuid.uuid4().hex[:8]}"
        repairs.append(f"missing proposal_id; synthesised {pid}")
    coerced["proposal_id"] = pid

    # title
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        coerced["title"] = "Untitled proposal"
        repairs.append("missing title; defaulted to 'Untitled proposal'")
    else:
        coerced["title"] = title

    # Section coercions.
    coerced["why"] = _coerce_section(
        raw.get("why"), str_field="prose_summary",
        list_fields=("cited_gaps", "cited_sessions", "cited_prior_decisions"),
        section_name="why", repairs=repairs,
    )
    coerced["what"] = _coerce_section(
        raw.get("what"), str_field="short_description",
        nullable_fields=("diff_reference",),
        list_fields=("files_touched",),
        section_name="what", repairs=repairs,
    )
    coerced["how"] = _coerce_section(
        raw.get("how"), str_field="mechanism_prose",
        section_name="how", repairs=repairs,
    )
    coerced["prediction"] = _coerce_section(
        raw.get("prediction"), str_field="expected_impact_prose",
        section_name="prediction", repairs=repairs,
    )

    # Optional pass-through fields that the renderer/recorder might use.
    for k in ("batch_id", "run_id", "created_at", "structural_tags",
              "authoring_addendum"):
        if k in raw:
            coerced[k] = raw[k]

    # Final sanity gate: if every section's primary prose is empty, the
    # proposal has nothing useful to show the human — drop it.
    if _all_sections_empty(coerced):
        return ProposalCoercionResult(
            proposal=None,
            repairs=repairs,
            drop_reason=(
                "every section (why/what/how/prediction) is empty after "
                "coercion; nothing to show the human"
            ),
        )

    return ProposalCoercionResult(proposal=coerced, repairs=repairs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_section(
    raw_section: Any,
    *,
    str_field: str,
    section_name: str,
    repairs: list[str],
    nullable_fields: Iterable[str] = (),
    list_fields: Iterable[str] = (),
) -> dict:
    """Normalize a single section into a dict.

    ``str_field`` is the field that receives the raw value if the
    proposer returned the section as a plain string (the most common
    drift). ``nullable_fields`` get None when absent; ``list_fields``
    get an empty list when absent.
    """
    if raw_section is None:
        repairs.append(f"missing '{section_name}' section; defaulted to empty")
        out: dict = {str_field: ""}
    elif isinstance(raw_section, str):
        repairs.append(
            f"'{section_name}' was a string; "
            f"normalised to {{'{str_field}': <string>}}"
        )
        out = {str_field: raw_section}
    elif isinstance(raw_section, dict):
        out = dict(raw_section)
        if str_field not in out:
            out[str_field] = ""
            repairs.append(
                f"'{section_name}' was missing '{str_field}'; defaulted to empty"
            )
    else:
        repairs.append(
            f"'{section_name}' was {type(raw_section).__name__}; "
            f"replaced with empty section"
        )
        out = {str_field: ""}

    for nf in nullable_fields:
        out.setdefault(nf, None)
    for lf in list_fields:
        if not isinstance(out.get(lf), list):
            out[lf] = []
    return out


def _all_sections_empty(proposal: dict) -> bool:
    """True iff every section's primary prose field is empty/whitespace."""
    primary_fields = {
        "why": "prose_summary",
        "what": "short_description",
        "how": "mechanism_prose",
        "prediction": "expected_impact_prose",
    }
    for section, field_name in primary_fields.items():
        s = proposal.get(section)
        if isinstance(s, dict):
            v = s.get(field_name, "")
            if isinstance(v, str) and v.strip():
                return False
    return True
