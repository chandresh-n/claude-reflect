"""
Session A failing-gate tests for step 14 — stage 2
(per-session refinement of draft pass classifications).

Stage 2 consumes all of a session's stage 1b draft
``pass_classifications`` (one batch per window), resolves seam
ambiguities across window boundaries, and emits the final
``pass_classifications`` per the spec.

Pins (HARD — from docs/PLAN.md Step 14):

  - output is a list of pass_classification dicts whose union covers
    every turn of the session non-overlappingly (no gaps, no overlaps)
  - output schema matches the spec's pass_classification shape
  - cache lives under .meta-harness/eval-cache/stage-2/ and cascades
    on upstream draft change
  - no scalar grades anywhere

Expected to FAIL on import until step 14 lands stage_2.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable
from unittest.mock import MagicMock


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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _draft(session_id: str, start: int, end: int,
           pass_type: str = "successful_one_shot") -> dict:
    return {
        "session_id": session_id,
        "turn_range": [start, end],
        "pass_type": pass_type,
        "harness_gap_rationale": (
            "no gap"
            if pass_type in {"successful_one_shot", "refinement"}
            else "harness lacked context"
        ),
        "contributing_gaps": (
            None if pass_type in {"successful_one_shot", "refinement"}
            else []
        ),
    }


def _canned_refinement(session_id: str,
                       ranges: Iterable[tuple[int, int, str]]) -> str:
    """Build a JSON string for a refined pass_classifications list."""
    payload = {
        "pass_classifications": [
            _draft(session_id, s, e, pt) for (s, e, pt) in ranges
        ],
    }
    return json.dumps(payload)


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


def _coverage_check(pass_classifications: list[dict],
                    expected_turn_count: int) -> None:
    """Assert non-overlap, no-gap coverage of turns 0..expected_turn_count-1."""
    ranges = sorted(
        ((pc["turn_range"][0], pc["turn_range"][1]) for pc in pass_classifications),
        key=lambda r: r[0],
    )
    assert ranges, "expected at least one pass_classification"
    assert ranges[0][0] == 0, (
        f"first pass must start at turn 0, got {ranges[0][0]}"
    )
    assert ranges[-1][1] == expected_turn_count - 1, (
        f"last pass must end at turn {expected_turn_count - 1}, "
        f"got {ranges[-1][1]}"
    )
    for prev, cur in zip(ranges, ranges[1:]):
        assert prev[1] + 1 == cur[0], (
            f"gap or overlap between ranges {prev} and {cur}: "
            "passes must be contiguous and non-overlapping"
        )


# ---------------------------------------------------------------------------
# Importable + module surface
# ---------------------------------------------------------------------------


def test_stage_2_module_importable() -> None:
    from meta_harness.agents.pipeline.stage_2 import (  # type: ignore  # noqa: F401
        refine_session_passes,
    )


def test_stage_2_exposes_prompt_version() -> None:
    from meta_harness.agents.pipeline import stage_2  # type: ignore

    assert hasattr(stage_2, "STAGE_2_PROMPT_VERSION")
    assert isinstance(stage_2.STAGE_2_PROMPT_VERSION, str)
    assert stage_2.STAGE_2_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Output coverage — non-overlapping, every turn covered exactly once
# ---------------------------------------------------------------------------


def test_refine_session_passes_covers_every_turn_no_gaps_no_overlaps(
    tmp_path: Path,
) -> None:
    """The spec invariant for pass_classifications is non-overlapping
    coverage of every turn in the session. Stage 2 must enforce that
    even when the upstream stage 1b drafts overlap at window seams."""
    from meta_harness.agents.pipeline.stage_2 import refine_session_passes  # type: ignore

    # Two windows overlap at the seam (turn 19 appears in both drafts).
    drafts = [
        _draft("s1", 0, 19),     # window 1
        _draft("s1", 19, 39),    # window 2 (seam overlap on turn 19)
    ]

    runner = MagicMock()
    # Model emits the refined, non-overlapping classification.
    runner.invoke.return_value = _canned_refinement(
        "s1",
        [(0, 19, "successful_one_shot"),
         (20, 39, "refinement")],
    )

    result = refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=40,
        runner=runner, repo=tmp_path, model="m",
    )

    assert isinstance(result, list)
    assert all(isinstance(pc, dict) for pc in result)
    _coverage_check(result, expected_turn_count=40)


def test_refine_session_passes_output_schema_matches_spec(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_2 import refine_session_passes  # type: ignore

    drafts = [_draft("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_refinement(
        "s1", [(0, 2, "successful_one_shot")],
    )

    result = refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )

    assert result, "stage 2 must return at least one pass_classification"
    for pc in result:
        required = {
            "session_id", "turn_range", "pass_type",
            "harness_gap_rationale", "contributing_gaps",
        }
        missing = required - set(pc.keys())
        assert not missing, (
            f"refined pass_classification missing fields per spec: {missing}"
        )
        assert pc["session_id"] == "s1"
        rng = pc["turn_range"]
        assert (
            isinstance(rng, (list, tuple))
            and len(rng) == 2
            and all(isinstance(x, int) for x in rng)
            and rng[0] <= rng[1]
        )
        assert pc["pass_type"] in _VALID_PASS_TYPES
        assert isinstance(pc["harness_gap_rationale"], str)
        cg = pc["contributing_gaps"]
        assert cg is None or isinstance(cg, list)
        if cg is None:
            assert pc["pass_type"] in {"successful_one_shot", "refinement"}


def test_refine_session_passes_no_scalar_grades(tmp_path: Path) -> None:
    from meta_harness.agents.pipeline.stage_2 import refine_session_passes  # type: ignore

    drafts = [_draft("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_refinement(
        "s1", [(0, 2, "successful_one_shot")],
    )

    result = refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )

    bad = _scan_for_forbidden_scalar_keys(result)
    assert not bad, f"stage 2 output contains forbidden scalar keys: {bad}"


# ---------------------------------------------------------------------------
# Cache namespace + cascade invalidation
# ---------------------------------------------------------------------------


def test_refine_session_passes_writes_cache_under_stage_2_namespace(
    tmp_path: Path,
) -> None:
    from meta_harness.agents.pipeline.stage_2 import refine_session_passes  # type: ignore

    drafts = [_draft("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_refinement(
        "s1", [(0, 2, "successful_one_shot")],
    )

    refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )

    cache_dir = tmp_path / ".meta-harness" / "eval-cache" / "stage-2"
    assert cache_dir.is_dir(), (
        f"Expected stage 2 cache dir at {cache_dir}"
    )
    files = list(cache_dir.glob("*.json"))
    assert len(files) >= 1


def test_refine_session_passes_cache_hit_skips_runner(tmp_path: Path) -> None:
    from meta_harness.agents.pipeline.stage_2 import refine_session_passes  # type: ignore

    drafts = [_draft("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_refinement(
        "s1", [(0, 2, "successful_one_shot")],
    )

    r1 = refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    r2 = refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1, (
        "Identical drafts must hit the stage 2 cache."
    )
    assert r2 == r1


def test_refine_session_passes_cache_invalidates_when_drafts_change(
    tmp_path: Path,
) -> None:
    """If stage 1b drafts change (e.g., a draft's pass_type was refined
    in an upstream rerun), the stage 2 cache for the session must miss
    and re-run."""
    from meta_harness.agents.pipeline.stage_2 import refine_session_passes  # type: ignore

    drafts = [_draft("s1", 0, 2)]
    runner = MagicMock()
    runner.invoke.return_value = _canned_refinement(
        "s1", [(0, 2, "successful_one_shot")],
    )

    refine_session_passes(
        session_id="s1", drafts=drafts, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    mutated = copy.deepcopy(drafts)
    mutated[0]["pass_type"] = "correction"
    mutated[0]["contributing_gaps"] = []

    refine_session_passes(
        session_id="s1", drafts=mutated, total_turns=3,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 2, (
        "Changing the upstream drafts must cascade to a stage 2 cache miss."
    )
