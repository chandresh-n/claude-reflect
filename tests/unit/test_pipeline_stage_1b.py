"""
Session A failing-gate tests for step 14 — stage 1b
(windowed per-turn observations + draft pass classifications).

Stage 1b consumes stage 1a descriptions for a session, applies a
per-pass-window with overlap, and produces:

  - ``per_turn_observations`` (spec schema from
    docs/spec/01-data-structures/evaluator-output.md)
  - draft ``pass_classifications`` (spec schema)

Pins (HARD — from docs/PLAN.md Step 14):

  - stage 1b output's per_turn_observation and pass_classification
    shapes match the spec exactly
  - 25-turn windows with 5-turn overlap dedup to exactly one
    observation per turn across the boundary (no duplicates, no gaps)
  - cache lives under .meta-harness/eval-cache/stage-1b/ and the key
    cascades: changing an upstream stage 1a description invalidates
    the stage 1b cache for any window that included it
  - one window's runner failure does not poison other windows'
    observations; partial_completion is surfaced for stage 3 to
    propagate
  - no scalar grades (quality/score/confidence/priority) anywhere
    in the output schema

Expected to FAIL on import until step 14 lands stage_1b.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_VALID_PASS_TYPES = {
    "successful_one_shot",
    "refinement",
    "clarification",
    "correction",
    "retry",
}


_FORBIDDEN_SCALAR_KEYS = {
    "quality_score", "quality", "score", "confidence", "priority",
    "rating", "grade",
}


def _stage_1a_description(session_id: str, turn_index: int,
                          **overrides: Any) -> dict:
    """A plausible stage 1a output dict for one turn."""
    base = {
        "session_id": session_id,
        "turn_index": turn_index,
        "goal_signal": f"goal at turn {turn_index}",
        "action_signal": f"action at turn {turn_index}",
        "outcome_signal": "completed",
        "friction_signal": "",
        "effort_signal": {
            "input_tokens": 120,
            "output_tokens": 80,
            "model": "claude-opus-4-7",
        },
        "tool_actions": [],
        "evidence_anchors": [f"anchor-{turn_index}"],
    }
    base.update(overrides)
    return base


def _per_turn_observation(session_id: str, turn_index: int,
                          **overrides: Any) -> dict:
    """A plausible per_turn_observation dict per the spec schema."""
    base = {
        "session_id": session_id,
        "turn_index": turn_index,
        "assessment": f"assessment for turn {turn_index}",
        "effort_signal": {
            "tokens_used": 200,
            "model": "claude-opus-4-7",
            "context_occupancy": None,
            "tool_calls": [],
        },
        "flags": [],
        "tool_verifications": [],
    }
    base.update(overrides)
    return base


def _draft_pass_classification(session_id: str, start: int, end: int,
                               pass_type: str = "successful_one_shot",
                               **overrides: Any) -> dict:
    """A plausible draft pass_classification per the spec schema."""
    base = {
        "session_id": session_id,
        "turn_range": [start, end],
        "pass_type": pass_type,
        "harness_gap_rationale": (
            "nothing the harness could have done differently"
            if pass_type in {"successful_one_shot", "refinement"}
            else "the harness should have asked sooner"
        ),
        "contributing_gaps": (
            None if pass_type in {"successful_one_shot", "refinement"}
            else []
        ),
    }
    base.update(overrides)
    return base


def _canned_window_response(session_id: str,
                            turn_indices: Iterable[int],
                            pass_type: str = "successful_one_shot") -> str:
    """A canned JSON the runner would emit for one window."""
    indices = list(turn_indices)
    payload = {
        "per_turn_observations": [
            _per_turn_observation(session_id, i) for i in indices
        ],
        "draft_pass_classifications": [
            _draft_pass_classification(
                session_id, indices[0], indices[-1], pass_type
            )
        ] if indices else [],
    }
    return json.dumps(payload)


def _scan_for_forbidden_scalar_keys(obj: Any) -> list[str]:
    """Walk a JSON-ish structure and return any forbidden scalar-grade keys."""
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


def test_stage_1b_module_importable() -> None:
    from meta_harness.agents.pipeline.stage_1b import (  # type: ignore  # noqa: F401
        observe_window,
        observe_session_windows,
    )


def test_stage_1b_exposes_prompt_version() -> None:
    """The cache key depends on a stage-local prompt_version constant
    so that bumping the prompt invalidates only this stage's cache."""
    from meta_harness.agents.pipeline import stage_1b  # type: ignore

    assert hasattr(stage_1b, "STAGE_1B_PROMPT_VERSION")
    assert isinstance(stage_1b.STAGE_1B_PROMPT_VERSION, str)
    assert stage_1b.STAGE_1B_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Output schema — per spec evaluator-output.md
# ---------------------------------------------------------------------------


def test_observe_window_returns_per_turn_observations_with_spec_schema(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_1b import observe_window  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(3)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_window_response("s1", [0, 1, 2])

    out = observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )

    assert isinstance(out, dict)
    assert "per_turn_observations" in out
    obs_list = out["per_turn_observations"]
    assert isinstance(obs_list, list) and len(obs_list) == 3
    for obs in obs_list:
        required = {
            "session_id", "turn_index", "assessment",
            "effort_signal", "flags", "tool_verifications",
        }
        missing = required - set(obs.keys())
        assert not missing, (
            f"per_turn_observation missing fields per spec: {missing}"
        )
        assert obs["session_id"] == "s1"
        assert isinstance(obs["turn_index"], int)
        assert isinstance(obs["assessment"], str)
        assert isinstance(obs["effort_signal"], dict)
        assert "tokens_used" in obs["effort_signal"]
        assert "model" in obs["effort_signal"]
        assert isinstance(obs["flags"], list)
        assert isinstance(obs["tool_verifications"], list)


def test_observe_window_returns_draft_pass_classifications_with_spec_schema(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_1b import observe_window  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(3)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_window_response("s1", [0, 1, 2])

    out = observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )

    assert "draft_pass_classifications" in out
    drafts = out["draft_pass_classifications"]
    assert isinstance(drafts, list) and drafts
    for draft in drafts:
        required = {
            "session_id", "turn_range", "pass_type",
            "harness_gap_rationale", "contributing_gaps",
        }
        missing = required - set(draft.keys())
        assert not missing, (
            f"pass_classification missing fields per spec: {missing}"
        )
        assert draft["session_id"] == "s1"
        rng = draft["turn_range"]
        assert (
            isinstance(rng, (list, tuple))
            and len(rng) == 2
            and all(isinstance(x, int) for x in rng)
            and rng[0] <= rng[1]
        )
        assert draft["pass_type"] in _VALID_PASS_TYPES
        assert isinstance(draft["harness_gap_rationale"], str)
        cg = draft["contributing_gaps"]
        assert cg is None or isinstance(cg, list)
        # Per spec: contributing_gaps is null only for these two pass types.
        if cg is None:
            assert draft["pass_type"] in {"successful_one_shot", "refinement"}


def test_observe_window_no_scalar_grades_in_output(tmp_path: Path) -> None:
    """Spec is explicit: no scalar quality / confidence / priority anywhere
    in the evaluator output. Stage 1b must not introduce them."""
    from meta_harness.agents.pipeline.stage_1b import observe_window  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_window_response("s1", [0, 1])

    out = observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )

    bad = _scan_for_forbidden_scalar_keys(out)
    assert not bad, f"stage 1b output contains forbidden scalar keys: {bad}"


# ---------------------------------------------------------------------------
# Overlap dedup — 25-turn windows, 5-turn overlap, 45-turn session
# ---------------------------------------------------------------------------


def test_observe_session_windows_dedups_overlap_to_one_observation_per_turn(
    tmp_path: Path,
) -> None:
    """The gate names the exact fixture shape: 25-turn windows, 5-turn
    overlap. With a 45-turn session that produces two windows
    (turns 0-24 and turns 20-44), the 5-turn boundary (turns 20-24)
    appears in both. After dedup, every turn 0-44 must appear in
    per_turn_observations EXACTLY once."""
    from meta_harness.agents.pipeline.stage_1b import observe_session_windows  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(45)]

    # The runner is called once per window. Stage 1b is responsible for
    # picking the window boundaries and asking the model per window;
    # the canned responses below assume two windows of the requested
    # shape: [0..24], [20..44]. If stage 1b chooses a different split,
    # we still expect coverage 0..44 exactly once after dedup.
    runner = MagicMock()
    runner.invoke.side_effect = [
        _canned_window_response("s1", list(range(0, 25))),
        _canned_window_response("s1", list(range(20, 45))),
        # Defensive extras in case the implementation chose more windows.
        _canned_window_response("s1", []),
        _canned_window_response("s1", []),
    ]

    result = observe_session_windows(
        session_id="s1", descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
        window_size=25, overlap=5,
    )

    assert isinstance(result, dict)
    assert "per_turn_observations" in result
    obs = result["per_turn_observations"]
    indices = sorted(o["turn_index"] for o in obs)
    assert indices == list(range(45)), (
        "After dedup, per_turn_observations must cover turns 0..44 "
        f"exactly once. Got indices: {indices}"
    )
    # And no duplicate indices (paranoid second check — the equality
    # above already guarantees this).
    assert len(indices) == len(set(indices))


# ---------------------------------------------------------------------------
# Cache namespace + cascade invalidation
# ---------------------------------------------------------------------------


def test_observe_window_writes_cache_under_stage_1b_namespace(
    tmp_path: Path,
) -> None:
    """Cache files for stage 1b MUST land under
    .meta-harness/eval-cache/stage-1b/. Downstream tooling and the
    resume path depend on this layout."""
    from meta_harness.agents.pipeline.stage_1b import observe_window  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_window_response("s1", [0, 1])

    observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )

    cache_dir = tmp_path / ".meta-harness" / "eval-cache" / "stage-1b"
    assert cache_dir.is_dir(), (
        f"Expected stage 1b cache dir at {cache_dir}"
    )
    files = list(cache_dir.glob("*.json"))
    assert len(files) >= 1, (
        f"Expected at least one cached JSON file under {cache_dir}, "
        f"got {files}"
    )


def test_observe_window_cache_hit_skips_runner_on_rerun(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_1b import observe_window  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_window_response("s1", [0, 1])

    out1 = observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    out2 = observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1, (
        "Second call with identical descriptions must hit the cache."
    )
    assert out2 == out1


def test_observe_window_cache_invalidates_when_upstream_description_changes(
    tmp_path: Path,
) -> None:
    """Cascade invalidation: the stage 1b cache key must include the
    upstream stage 1a descriptions (or their digest). When one of those
    descriptions changes, the key must shift, the cache must miss, and
    the runner must be invoked again."""
    from meta_harness.agents.pipeline.stage_1b import observe_window  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_window_response("s1", [0, 1])

    observe_window(
        session_id="s1", window_index=0, descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    # Modify one upstream description's outcome signal — anything in the
    # content stream should cascade.
    mutated = copy.deepcopy(descs)
    mutated[1]["outcome_signal"] = "blocked"
    observe_window(
        session_id="s1", window_index=0, descriptions=mutated,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 2, (
        "Modifying an upstream stage 1a description must cascade "
        "to a stage 1b cache miss."
    )


# ---------------------------------------------------------------------------
# Per-window failure isolation + partial-completion flag
# ---------------------------------------------------------------------------


def test_observe_session_windows_one_window_failure_does_not_drop_others(
    tmp_path: Path,
) -> None:
    """One window's runner failure must NOT prevent other windows'
    observations from landing in the output. This is the partial-with-
    flag failure policy at the per-window granularity."""
    from meta_harness.agents.pipeline.stage_1b import observe_session_windows  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(45)]

    runner = MagicMock()
    call_counter = {"n": 0}

    def side(*, system_prompt, user_prompt, model, **kw):
        call_counter["n"] += 1
        # Fail on the first window; succeed on subsequent windows.
        if call_counter["n"] == 1:
            raise RuntimeError("simulated transient model failure")
        # Return a generic response covering the second half.
        return _canned_window_response("s1", list(range(20, 45)))

    runner.invoke.side_effect = side

    result = observe_session_windows(
        session_id="s1", descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
        window_size=25, overlap=5,
    )

    assert isinstance(result, dict)
    # At least the surviving window's per_turn_observations must be present.
    obs = result.get("per_turn_observations", [])
    surviving_indices = {o["turn_index"] for o in obs}
    assert surviving_indices, (
        "Surviving windows' observations must still be returned even "
        "when an earlier window failed."
    )
    # Some of the tail-window turns (20..44) must have made it through.
    assert surviving_indices & set(range(20, 45)), (
        "Expected at least some turns from the surviving window "
        f"(20..44) in the output; got {sorted(surviving_indices)}"
    )


def test_observe_session_windows_surfaces_partial_completion_on_failure(
    tmp_path: Path,
) -> None:
    """When any window fails inside a session, stage 1b's output for
    that session MUST carry a partial-completion signal that stage 3
    can propagate onto the session narrative. The signal can be a top-
    level ``partial_completion`` boolean (preferred) or an equivalent
    flag the orchestrator can inspect."""
    from meta_harness.agents.pipeline.stage_1b import observe_session_windows  # type: ignore

    descs = [_stage_1a_description("s1", i) for i in range(45)]

    runner = MagicMock()
    call_counter = {"n": 0}

    def side(*, system_prompt, user_prompt, model, **kw):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            raise RuntimeError("simulated transient model failure")
        return _canned_window_response("s1", list(range(20, 45)))

    runner.invoke.side_effect = side

    result = observe_session_windows(
        session_id="s1", descriptions=descs,
        runner=runner, repo=tmp_path, model="m",
        window_size=25, overlap=5,
    )

    assert result.get("partial_completion") is True, (
        "When at least one window failed, the per-session stage 1b "
        "output must set partial_completion=True (or an equivalent "
        "flag) so stage 3 can mark the narrative."
    )
