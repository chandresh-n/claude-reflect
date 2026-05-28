"""
Session A failing-gate tests for step 15 — stage 4
(cross-session gap-observation production).

Stage 4 consumes the merged outputs of stages 1b/2/3 across the
corpus, identifies cross-session gap patterns, returns
``gap_observations`` per the spec, and writes append-only side
effects to the gap-record knowledge base.

Pins (HARD — from docs/PLAN.md Step 15):

  - module is importable from ``claude_reflect.agents.pipeline.stage_4``
    and exposes ``identify_corpus_gaps`` and ``STAGE_4_PROMPT_VERSION``
  - output schema matches the spec's gap_observation shape
    (matched_gap_id, characterization, kind, evidence_additions)
  - new unmatched obs ⇒ creates a new gap record on disk; the
    returned obs has ``matched_gap_id`` populated
  - matched obs ⇒ existing gap record's evidence is APPENDED
    (append-only); pre-existing evidence is preserved
  - gap records are never deleted by stage 4 (append-only invariant)
  - cache lives under ``.claude-reflect/eval-cache/stage-4/`` and the
    key cascades when any upstream input changes
  - no scalar grades anywhere in the output schema
  - pipeline module guardrail: only ``runner.py`` imports
    ``claude_runner``

Expected to FAIL on import (and on the cutover symbol scan) until
step 15 lands ``stage_4.py``.
"""
from __future__ import annotations

import copy
import json
import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


_FORBIDDEN_SCALAR_KEYS = {
    "quality_score", "quality", "score", "confidence", "priority",
    "rating", "grade", "severity", "rank",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _per_turn_observation(session_id: str, turn_index: int) -> dict:
    return {
        "session_id": session_id,
        "turn_index": turn_index,
        "assessment": f"turn {turn_index} happened in {session_id}",
        "effort_signal": {
            "tokens_used": 200, "model": "claude-opus-4-7",
            "context_occupancy": None, "tool_calls": [],
        },
        "flags": [],
        "tool_verifications": [],
    }


def _pass_classification(session_id: str, start: int, end: int,
                         pass_type: str = "correction") -> dict:
    return {
        "session_id": session_id,
        "turn_range": [start, end],
        "pass_type": pass_type,
        "harness_gap_rationale": "harness lacked file-location context",
        "contributing_gaps": (
            None if pass_type in {"successful_one_shot", "refinement"}
            else []
        ),
    }


def _narrative(session_id: str,
               outcome: str = "successful_with_friction") -> dict:
    return {
        "session_id": session_id,
        "outcome": outcome,
        "pass_counts_by_type": {"correction": 1},
        "gaps_observed": [],
        "narrative": f"{session_id} corrected once before completing",
    }


def _canned_gap_observation(
    *,
    matched_gap_id: Any = None,
    characterization: str | None = "claude struggles to locate files",
    kind: str = "file-location-confusion",
    evidence_additions: list[dict] | None = None,
) -> dict:
    return {
        "matched_gap_id": matched_gap_id,
        "characterization": characterization,
        "kind": kind,
        "evidence_additions": evidence_additions or [
            {
                "session_id": "s1",
                "turn_range": [3, 5],
                "magnitude": {
                    "additional_turns": 2,
                    "additional_tokens": 1500,
                    "correction_required": True,
                },
            },
        ],
    }


def _canned_corpus_response(gap_observations: list[dict]) -> str:
    return json.dumps({"gap_observations": gap_observations})


def _scan_for_forbidden_scalar_keys(obj: Any) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _FORBIDDEN_SCALAR_KEYS:
                found.append(k)
            found.extend(_scan_for_forbidden_scalar_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_scan_for_forbidden_scalar_keys(item))
    return found


def _make_corpus_inputs(session_ids: list[str]) -> dict:
    """Default corpus inputs covering several sessions."""
    per_turn = [
        _per_turn_observation(sid, i)
        for sid in session_ids for i in range(3)
    ]
    passes = [_pass_classification(sid, 0, 2) for sid in session_ids]
    narratives = [_narrative(sid) for sid in session_ids]
    return {
        "per_turn_observations": per_turn,
        "pass_classifications": passes,
        "session_narratives": narratives,
    }


# ---------------------------------------------------------------------------
# Importable + module surface
# ---------------------------------------------------------------------------


def test_stage_4_module_importable() -> None:
    from claude_reflect.agents.pipeline.stage_4 import (  # type: ignore  # noqa: F401
        identify_corpus_gaps,
    )


def test_stage_4_exposes_prompt_version() -> None:
    from claude_reflect.agents.pipeline import stage_4  # type: ignore

    assert hasattr(stage_4, "STAGE_4_PROMPT_VERSION")
    assert isinstance(stage_4.STAGE_4_PROMPT_VERSION, str)
    assert stage_4.STAGE_4_PROMPT_VERSION


def test_stage_4_does_not_import_claude_runner_directly() -> None:
    """Pipeline guardrail: only ``runner.py`` may import claude_runner."""
    import claude_reflect.agents.pipeline.stage_4 as stage_4_mod  # type: ignore

    src = Path(stage_4_mod.__file__).read_text(encoding="utf-8")
    assert "claude_runner" not in src, (
        "stage_4 must not import claude_runner directly; "
        "talk to the Runner abstraction in pipeline/runner.py."
    )


# ---------------------------------------------------------------------------
# Output shape — spec gap_observation
# ---------------------------------------------------------------------------


def test_identify_corpus_gaps_returns_list(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    inputs = _make_corpus_inputs(["s1", "s2"])
    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    out = identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=inputs["session_narratives"],
        runner=runner, repo=tmp_path, model="m",
    )

    assert isinstance(out, list)
    assert len(out) == 1


def test_identify_corpus_gaps_output_schema_matches_spec(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    inputs = _make_corpus_inputs(["s1"])
    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    [obs] = identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=inputs["session_narratives"],
        runner=runner, repo=tmp_path, model="m",
    )

    required = {"matched_gap_id", "characterization", "kind",
                "evidence_additions"}
    missing = required - set(obs.keys())
    assert not missing, (
        f"stage 4 gap_observation missing fields per spec: {missing}"
    )
    assert isinstance(obs["kind"], str) and obs["kind"]
    assert isinstance(obs["evidence_additions"], list)
    for ev in obs["evidence_additions"]:
        assert "session_id" in ev
        assert "turn_range" in ev
        assert "magnitude" in ev


def test_identify_corpus_gaps_no_scalar_grades(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    inputs = _make_corpus_inputs(["s1"])
    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    out = identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=inputs["session_narratives"],
        runner=runner, repo=tmp_path, model="m",
    )

    bad = _scan_for_forbidden_scalar_keys(out)
    assert not bad, f"stage 4 output contains forbidden scalar keys: {bad}"


# ---------------------------------------------------------------------------
# Gap-record side effects — append-only
# ---------------------------------------------------------------------------


def test_unmatched_gap_observation_creates_new_gap_record(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(matched_gap_id=None),
    ])

    out = identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", 0)],
        pass_classifications=[_pass_classification("s1", 0, 0)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    # Returned observation must have matched_gap_id populated for the
    # new record. The proposer depends on this resolution.
    assert out[0].get("matched_gap_id"), (
        "Stage 4 must populate matched_gap_id on the returned observation "
        "after creating a new gap record so downstream consumers can "
        "link the observation to the canonical record."
    )

    gaps_dir = tmp_path / ".claude-reflect" / "gaps"
    assert gaps_dir.is_dir()
    gap_files = list(gaps_dir.glob("*.json"))
    assert len(gap_files) == 1, (
        "Stage 4 must create exactly one gap-record file per "
        "unmatched observation."
    )


def test_matched_gap_observation_appends_to_existing_record(
    tmp_path: Path,
) -> None:
    """The matched-gap-id merge rule: existing gap records gain new
    evidence; pre-existing evidence is preserved (append-only)."""
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore
    from claude_reflect.storage.gap_record import (
        create_gap_record,
        read_gap_record,
    )

    # Seed an existing record on disk.
    existing = create_gap_record(tmp_path, {
        "characterization": "claude struggles to locate files",
        "kind": "file-location-confusion",
        "first_observed_at": "2026-05-01T00:00:00Z",
        "last_observed_at": "2026-05-01T00:00:00Z",
        "occurrence_count": 1,
        "evidence": [{
            "session_id": "older-session",
            "turn_range": {"start": 1, "end": 2},
            "magnitude": {"additional_turns": 1,
                          "additional_tokens": 800,
                          "correction_required": True},
        }],
        "status": "open",
        "related_proposals": [],
    })
    existing_id = existing["identifier"]

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(
            matched_gap_id=existing_id,
            characterization=None,
            evidence_additions=[{
                "session_id": "s1",
                "turn_range": {"start": 3, "end": 5},
                "magnitude": {"additional_turns": 2,
                              "additional_tokens": 1500,
                              "correction_required": True},
            }],
        ),
    ])

    identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", i) for i in range(6)],
        pass_classifications=[_pass_classification("s1", 0, 5)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    updated = read_gap_record(tmp_path, existing_id)
    # Evidence must include both the original AND the new pointer.
    assert len(updated["evidence"]) == 2, (
        "Existing evidence must be preserved when stage 4 appends new "
        f"evidence; got {len(updated['evidence'])} entries"
    )
    older_present = any(
        e["session_id"] == "older-session"
        for e in updated["evidence"]
    )
    new_present = any(
        e["session_id"] == "s1"
        for e in updated["evidence"]
    )
    assert older_present, "Append-only: pre-existing evidence was lost"
    assert new_present, "New evidence pointer was not appended"
    assert updated["occurrence_count"] == 2


def test_stage_4_does_not_delete_existing_gap_records(
    tmp_path: Path,
) -> None:
    """Append-only invariant: stage 4 must never delete gap-record files,
    even when its observations do not cover an existing gap."""
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore
    from claude_reflect.storage.gap_record import create_gap_record

    # Seed an existing record that stage 4 will NOT observe.
    untouched = create_gap_record(tmp_path, {
        "characterization": "an unrelated existing gap",
        "kind": "unrelated-kind",
        "first_observed_at": "2026-05-01T00:00:00Z",
        "last_observed_at": "2026-05-01T00:00:00Z",
        "occurrence_count": 1,
        "evidence": [{
            "session_id": "older-session",
            "turn_range": {"start": 0, "end": 1},
            "magnitude": {"additional_turns": 1,
                          "additional_tokens": 500,
                          "correction_required": False},
        }],
        "status": "open",
        "related_proposals": [],
    })
    untouched_id = untouched["identifier"]
    untouched_path = (
        tmp_path / ".claude-reflect" / "gaps" / f"{untouched_id}.json"
    )
    assert untouched_path.is_file()
    original_bytes = untouched_path.read_bytes()

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        # A wholly different unmatched observation
        _canned_gap_observation(matched_gap_id=None,
                                kind="something-else"),
    ])

    identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", 0)],
        pass_classifications=[_pass_classification("s1", 0, 0)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    assert untouched_path.is_file(), (
        "Stage 4 must never delete an existing gap-record file."
    )
    assert untouched_path.read_bytes() == original_bytes, (
        "Stage 4 must not destructively rewrite gap records it did not "
        "observe."
    )


# ---------------------------------------------------------------------------
# Cache namespace + cascade invalidation
# ---------------------------------------------------------------------------


def test_identify_corpus_gaps_writes_cache_under_stage_4_namespace(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", 0)],
        pass_classifications=[_pass_classification("s1", 0, 0)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    cache_dir = tmp_path / ".claude-reflect" / "eval-cache" / "stage-4"
    assert cache_dir.is_dir(), (
        f"Expected stage 4 cache dir at {cache_dir}"
    )
    files = list(cache_dir.glob("*.json"))
    assert len(files) >= 1


def test_identify_corpus_gaps_cache_hit_skips_runner(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    inputs = _make_corpus_inputs(["s1", "s2"])
    out1 = identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=inputs["session_narratives"],
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    out2 = identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=inputs["session_narratives"],
        runner=runner, repo=tmp_path, model="m",
    )

    assert runner.invoke.call_count == 1, (
        "Identical inputs must hit the stage 4 cache and skip the runner."
    )


def test_identify_corpus_gaps_cache_invalidates_when_upstream_changes(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    inputs = _make_corpus_inputs(["s1", "s2"])
    identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=inputs["session_narratives"],
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    mutated = copy.deepcopy(inputs["session_narratives"])
    mutated[0]["narrative"] = "something different happened in s1"

    identify_corpus_gaps(
        per_turn_observations=inputs["per_turn_observations"],
        pass_classifications=inputs["pass_classifications"],
        session_narratives=mutated,
        runner=runner, repo=tmp_path, model="m",
    )

    assert runner.invoke.call_count == 2, (
        "Changing an upstream session_narrative must cascade to a "
        "stage 4 cache miss."
    )


# ---------------------------------------------------------------------------
# Known-gap injection — the model is shown existing matchable gaps
# ---------------------------------------------------------------------------


def _seed_gap(repo: Path, *, kind: str, characterization: str,
              status: str = "open") -> str:
    from claude_reflect.storage.gap_record import create_gap_record
    rec = create_gap_record(repo, {
        "characterization": characterization,
        "kind": kind,
        "first_observed_at": "2026-05-01T00:00:00Z",
        "last_observed_at": "2026-05-01T00:00:00Z",
        "occurrence_count": 1,
        "evidence": [{
            "session_id": "older",
            "turn_range": {"start": 0, "end": 1},
            "magnitude": {"additional_turns": 1, "additional_tokens": 100,
                          "correction_required": False},
        }],
        "status": status,
        "related_proposals": [],
    })
    return rec["identifier"]


def test_open_gap_is_injected_into_the_prompt(tmp_path: Path) -> None:
    """An existing open gap must appear in the user prompt so the model can
    match a recurrence against it instead of minting a duplicate."""
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    gap_id = _seed_gap(tmp_path, kind="file-location-thrash",
                       characterization="Guesses paths before searching.")

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", 0)],
        pass_classifications=[_pass_classification("s1", 0, 0)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    user_prompt = runner.invoke.call_args.kwargs["user_prompt"]
    assert gap_id in user_prompt, "open gap's identifier must be in the prompt"
    assert "Guesses paths before searching." in user_prompt, (
        "open gap's characterization must be in the prompt"
    )


def test_addressed_gap_is_not_offered_as_a_match_candidate(tmp_path: Path) -> None:
    """Only open/stale gaps are matchable; an addressed gap must not appear in
    the prompt (matching it would regress its status on an incidental hit)."""
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    addressed_id = _seed_gap(tmp_path, kind="resolved-thing",
                             characterization="Already handled.",
                             status="addressed")

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(),
    ])

    identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", 0)],
        pass_classifications=[_pass_classification("s1", 0, 0)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    user_prompt = runner.invoke.call_args.kwargs["user_prompt"]
    assert addressed_id not in user_prompt, (
        "addressed gaps must not be offered as match candidates"
    )


def test_unknown_matched_gap_id_falls_back_to_new_record(tmp_path: Path) -> None:
    """If the model returns a matched_gap_id that does not resolve to a real
    record, the observation must not be silently dropped — it becomes a new
    gap so its evidence is still captured."""
    from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps  # type: ignore

    runner = MagicMock()
    runner.invoke.return_value = _canned_corpus_response([
        _canned_gap_observation(matched_gap_id="does-not-exist-id"),
    ])

    out = identify_corpus_gaps(
        per_turn_observations=[_per_turn_observation("s1", 0)],
        pass_classifications=[_pass_classification("s1", 0, 0)],
        session_narratives=[_narrative("s1")],
        runner=runner, repo=tmp_path, model="m",
    )

    # A real record was created and the returned obs points at it.
    gaps_dir = tmp_path / ".claude-reflect" / "gaps"
    gap_files = list(gaps_dir.glob("*.json"))
    assert len(gap_files) == 1, (
        "an unresolvable matched_gap_id must fall back to creating a new "
        f"record, not be dropped; found {len(gap_files)} gap files"
    )
    resolved_id = out[0].get("matched_gap_id")
    assert resolved_id and resolved_id != "does-not-exist-id", (
        "returned observation must point at the newly created record's id"
    )
