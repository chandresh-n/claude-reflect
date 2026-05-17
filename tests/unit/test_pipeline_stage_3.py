"""
Session A failing-gate tests for step 14 — stage 3
(per-session narrative).

Stage 3 consumes a session's per_turn_observations,
pass_classifications, and the gap_observations touched by the
session, and produces exactly one ``session_narrative`` per the spec.
If upstream stages dropped data for this session, stage 3 marks the
narrative with a partial-completion flag (NOT a session drop).

Pins (HARD — from docs/PLAN.md Step 14):

  - exactly one narrative per session
  - schema matches the spec's session_narrative shape
    (session_id, outcome enum, pass_counts_by_type, gaps_observed,
    narrative)
  - partial_completion flag propagates when upstream is partial
  - cache lives under .meta-harness/eval-cache/stage-3/ and cascades
    on upstream input change
  - one stage 1b window failing for a session yields a
    partial_completion flag on stage 3's narrative for that session,
    not a session drop (integration with stage 1b)
  - no scalar grades anywhere

Expected to FAIL on import until step 14 lands stage_3.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


_VALID_OUTCOMES = {
    "successful_and_accepted",
    "successful_with_friction",
    "abandoned",
    "ongoing",
}


_FORBIDDEN_SCALAR_KEYS = {
    "quality_score", "quality", "score", "confidence", "priority",
    "rating", "grade",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _per_turn_observation(session_id: str, turn_index: int) -> dict:
    return {
        "session_id": session_id,
        "turn_index": turn_index,
        "assessment": f"turn {turn_index} happened",
        "effort_signal": {
            "tokens_used": 200, "model": "claude-opus-4-7",
            "context_occupancy": None, "tool_calls": [],
        },
        "flags": [],
        "tool_verifications": [],
    }


def _pass_classification(session_id: str, start: int, end: int,
                         pass_type: str = "successful_one_shot") -> dict:
    return {
        "session_id": session_id,
        "turn_range": [start, end],
        "pass_type": pass_type,
        "harness_gap_rationale": "n/a",
        "contributing_gaps": (
            None if pass_type in {"successful_one_shot", "refinement"}
            else []
        ),
    }


def _canned_narrative_response(session_id: str, *,
                               outcome: str = "successful_and_accepted",
                               pass_counts: dict | None = None,
                               gaps_observed: list | None = None,
                               narrative: str = "the session did stuff") -> str:
    return json.dumps({
        "session_id": session_id,
        "outcome": outcome,
        "pass_counts_by_type": pass_counts or {"successful_one_shot": 1},
        "gaps_observed": gaps_observed if gaps_observed is not None else [],
        "narrative": narrative,
    })


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


# ---------------------------------------------------------------------------
# Importable + module surface
# ---------------------------------------------------------------------------


def test_stage_3_module_importable() -> None:
    from meta_harness.agents.pipeline.stage_3 import (  # type: ignore  # noqa: F401
        summarize_session,
    )


def test_stage_3_exposes_prompt_version() -> None:
    from meta_harness.agents.pipeline import stage_3  # type: ignore

    assert hasattr(stage_3, "STAGE_3_PROMPT_VERSION")
    assert isinstance(stage_3.STAGE_3_PROMPT_VERSION, str)
    assert stage_3.STAGE_3_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Output shape — one narrative per session, schema per spec
# ---------------------------------------------------------------------------


def test_summarize_session_returns_one_narrative_per_session(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(3)]
    passes = [_pass_classification("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    out = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )

    # Output is a single dict (one narrative for this session). The
    # caller — the orchestrator — collects one of these per session.
    assert isinstance(out, dict)
    assert out.get("session_id") == "s1"


def test_summarize_session_output_schema_matches_spec(tmp_path: Path) -> None:
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(3)]
    passes = [_pass_classification("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response(
        "s1",
        outcome="successful_with_friction",
        pass_counts={"successful_one_shot": 1},
        gaps_observed=["gap-abc"],
        narrative="explored, retried once, accepted",
    )

    out = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )

    required = {
        "session_id", "outcome", "pass_counts_by_type",
        "gaps_observed", "narrative",
    }
    missing = required - set(out.keys())
    assert not missing, (
        f"session_narrative missing fields per spec: {missing}"
    )
    assert out["session_id"] == "s1"
    assert out["outcome"] in _VALID_OUTCOMES, (
        f"outcome must be one of {_VALID_OUTCOMES}, got {out['outcome']}"
    )
    assert isinstance(out["pass_counts_by_type"], dict)
    for k, v in out["pass_counts_by_type"].items():
        assert isinstance(k, str)
        assert isinstance(v, int) and v >= 0
    assert isinstance(out["gaps_observed"], list)
    assert isinstance(out["narrative"], str)


def test_summarize_session_no_scalar_grades(tmp_path: Path) -> None:
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", 0)]
    passes = [_pass_classification("s1", 0, 0)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    out = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )

    bad = _scan_for_forbidden_scalar_keys(out)
    assert not bad, f"stage 3 output contains forbidden scalar keys: {bad}"


# ---------------------------------------------------------------------------
# Partial-completion flag — direct propagation
# ---------------------------------------------------------------------------


def test_summarize_session_marks_partial_when_input_partial_true(
    tmp_path: Path,
) -> None:
    """Direct test of the flag-propagation contract: if the caller
    (the orchestrator) passes partial_completion=True, the narrative
    MUST carry partial_completion=True in its output."""
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(3)]
    passes = [_pass_classification("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    out = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
        partial_completion=True,
    )

    assert out.get("partial_completion") is True, (
        "Stage 3 must propagate partial_completion=True onto the "
        "session narrative."
    )


def test_summarize_session_does_not_mark_partial_when_input_partial_false(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(3)]
    passes = [_pass_classification("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    out = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
        partial_completion=False,
    )

    # Either omitted entirely, or explicitly False — both are acceptable
    # signals that this session ran to completion.
    assert out.get("partial_completion", False) is False, (
        "When upstream succeeded for this session, the narrative must "
        "not carry partial_completion=True."
    )


# ---------------------------------------------------------------------------
# Partial-completion flag — end-to-end with stage 1b
# ---------------------------------------------------------------------------


def test_stage_1b_window_failure_propagates_partial_completion_to_stage_3(
    tmp_path: Path,
) -> None:
    """End-to-end gate criterion (#6): one stage 1b window failure for a
    session yields a partial_completion flag on stage 3's narrative for
    that session, not a session drop. We wire stage 1b → stage 3
    directly (no orchestrator yet) and verify the flag survives."""
    from meta_harness.agents.pipeline.stage_1b import observe_session_windows  # type: ignore
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    descs = [
        {
            "session_id": "s1",
            "turn_index": i,
            "goal_signal": "g", "action_signal": "a",
            "outcome_signal": "completed", "friction_signal": "",
            "effort_signal": {
                "input_tokens": 100, "output_tokens": 50,
                "model": "claude-opus-4-7",
            },
            "tool_actions": [], "evidence_anchors": [],
        }
        for i in range(45)
    ]

    # Stage 1b runner: first window fails, second window returns a
    # plausible response covering turns 20..44.
    stage_1b_runner = MagicMock()
    call_counter = {"n": 0}

    def side(*, system_prompt, user_prompt, model, **kw):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            raise RuntimeError("simulated transient model failure")
        return json.dumps({
            "per_turn_observations": [
                _per_turn_observation("s1", i) for i in range(20, 45)
            ],
            "draft_pass_classifications": [
                _pass_classification("s1", 20, 44, "refinement"),
            ],
        })

    stage_1b_runner.invoke.side_effect = side

    stage_1b_out = observe_session_windows(
        session_id="s1", descriptions=descs,
        runner=stage_1b_runner, repo=tmp_path, model="m",
        window_size=25, overlap=5,
    )

    assert stage_1b_out.get("partial_completion") is True

    # Now feed stage 1b's per_turn_observations + a placeholder
    # pass_classifications into stage 3, propagating the partial flag.
    stage_3_runner = MagicMock()
    stage_3_runner.invoke.return_value = _canned_narrative_response("s1")

    narrative = summarize_session(
        session_id="s1",
        per_turn_observations=stage_1b_out["per_turn_observations"],
        pass_classifications=[_pass_classification("s1", 20, 44, "refinement")],
        gap_observations=[],
        runner=stage_3_runner, repo=tmp_path, model="m",
        partial_completion=stage_1b_out["partial_completion"],
    )

    assert narrative["session_id"] == "s1"
    assert narrative.get("partial_completion") is True, (
        "The partial_completion flag from stage 1b's failed window "
        "must surface on stage 3's narrative for that session, "
        "not cause a session drop."
    )


# ---------------------------------------------------------------------------
# Cache namespace + cascade invalidation
# ---------------------------------------------------------------------------


def test_summarize_session_writes_cache_under_stage_3_namespace(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(2)]
    passes = [_pass_classification("s1", 0, 1)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )

    cache_dir = tmp_path / ".meta-harness" / "eval-cache" / "stage-3"
    assert cache_dir.is_dir(), (
        f"Expected stage 3 cache dir at {cache_dir}"
    )
    files = list(cache_dir.glob("*.json"))
    assert len(files) >= 1


def test_summarize_session_cache_hit_skips_runner(tmp_path: Path) -> None:
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(2)]
    passes = [_pass_classification("s1", 0, 1)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    out1 = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    out2 = summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1, (
        "Identical inputs must hit the stage 3 cache."
    )
    assert out2 == out1


def test_summarize_session_cache_invalidates_when_upstream_changes(
    tmp_path: Path,
) -> None:
    """Cascade invalidation: changing the per_turn_observations or the
    pass_classifications must change the stage 3 cache key."""
    from meta_harness.agents.pipeline.stage_3 import summarize_session  # type: ignore

    obs = [_per_turn_observation("s1", i) for i in range(2)]
    passes = [_pass_classification("s1", 0, 1)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_narrative_response("s1")

    summarize_session(
        session_id="s1",
        per_turn_observations=obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    # Mutate one observation's assessment — the stage 3 cache must miss.
    mutated_obs = copy.deepcopy(obs)
    mutated_obs[0]["assessment"] = "something different happened"

    summarize_session(
        session_id="s1",
        per_turn_observations=mutated_obs,
        pass_classifications=passes,
        gap_observations=[],
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 2, (
        "Changing the upstream per_turn_observations must cascade "
        "to a stage 3 cache miss."
    )
