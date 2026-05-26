"""
Session A failing-gate integration test for step 15 — full evaluator
pipeline end-to-end with all five stages mocked.

The orchestrator runs 1a → 1b → 2 → 3 → 4 against a small synthetic
session set. The model is mocked by a single Runner that dispatches
on system_prompt content and returns canned-but-spec-shaped JSON for
every stage. The integration verifies:

  - the orchestrator produces a document with exactly the four
    top-level keys required by
    docs/spec/01-data-structures/evaluator-output.md
    (per_turn_observations, pass_classifications, gap_observations,
    session_narratives)
  - the four top-level arrays roughly cover every (session, turn) the
    pipeline saw — the spec-level "exhaustive over the window"
    invariant
  - every session has exactly one session_narrative
  - the output contains no scalar grade fields anywhere

Expected to FAIL on import until step 15 lands the orchestrator.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from claude_reflect.storage.session_logs import Session, Turn


_FORBIDDEN_SCALAR_KEYS = {
    "quality_score", "quality", "score", "confidence", "priority",
    "rating", "grade", "severity", "rank",
}


# ---------------------------------------------------------------------------
# Smart stage-dispatching mock Runner (duplicated from the unit test
# file so the integration test is self-contained — the integration
# test runs against a synthetic corpus rather than mocking individual
# stage functions).
# ---------------------------------------------------------------------------


class StageDispatchRunner:

    def __init__(self) -> None:
        self.calls_by_stage: dict[str, int] = {
            "1a": 0, "1b": 0, "2": 0, "3": 0, "4": 0,
        }

    @staticmethod
    def classify(system_prompt: str) -> str:
        sp = system_prompt.lower()
        if "cross-session" in sp or "corpus" in sp:
            return "4"
        if "per-turn describer" in sp:
            return "1a"
        if "windowed observer" in sp:
            return "1b"
        if "pass-refiner" in sp:
            return "2"
        if "narrative writer" in sp:
            return "3"
        raise AssertionError(
            "StageDispatchRunner could not classify invocation; "
            f"system_prompt[:200]={system_prompt[:200]!r}"
        )

    def invoke(self, *, system_prompt: str, user_prompt: str,
               model: str, **kwargs) -> str:
        stage = self.classify(system_prompt)
        self.calls_by_stage[stage] += 1
        if stage == "1a":
            sid = _parse_field(user_prompt, "session_id")
            ti = int(_parse_field(user_prompt, "turn_index"))
            return json.dumps({
                "session_id": sid,
                "turn_index": ti,
                "goal_signal": "g",
                "action_signal": "a",
                "outcome_signal": "completed",
                "friction_signal": "",
                "effort_signal": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "model": "m",
                },
                "tool_actions": [],
                "evidence_anchors": [],
            })
        if stage == "1b":
            sid = _parse_field(user_prompt, "session_id")
            indices = _parse_turn_indices(user_prompt)
            return json.dumps({
                "per_turn_observations": [
                    _spec_per_turn_obs(sid, i) for i in indices
                ],
                "draft_pass_classifications": [
                    _spec_pass_classification(
                        sid, indices[0], indices[-1],
                        pass_type="successful_one_shot",
                    ),
                ],
            })
        if stage == "2":
            sid = _parse_field(user_prompt, "session_id")
            total = int(_parse_field(user_prompt, "total_turns"))
            return json.dumps({
                "pass_classifications": [
                    _spec_pass_classification(
                        sid, 0, total - 1,
                        pass_type="successful_one_shot",
                    ),
                ],
            })
        if stage == "3":
            sid = _parse_field(user_prompt, "session_id")
            return json.dumps({
                "session_id": sid,
                "outcome": "successful_and_accepted",
                "pass_counts_by_type": {"successful_one_shot": 1},
                "gaps_observed": [],
                "narrative": f"{sid} did things",
            })
        if stage == "4":
            return json.dumps({"gap_observations": []})
        raise AssertionError(f"unknown stage {stage}")


def _parse_field(prompt: str, field: str) -> str:
    for line in prompt.splitlines():
        line = line.strip()
        prefix = f"{field}:"
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise AssertionError(
        f"could not find field {field!r} in prompt"
    )


def _parse_turn_indices(prompt: str) -> list[int]:
    import re

    matches = re.findall(r'"turn_index"\s*:\s*(\d+)', prompt)
    seen: set[int] = set()
    result: list[int] = []
    for m in matches:
        v = int(m)
        if v in seen:
            continue
        seen.add(v)
        result.append(v)
    return result


def _spec_per_turn_obs(session_id: str, turn_index: int) -> dict:
    return {
        "session_id": session_id,
        "turn_index": turn_index,
        "assessment": f"turn {turn_index} happened",
        "effort_signal": {
            "tokens_used": 150,
            "model": "m",
            "context_occupancy": None,
            "tool_calls": [],
        },
        "flags": [],
        "tool_verifications": [],
    }


def _spec_pass_classification(session_id: str, start: int, end: int,
                              pass_type: str) -> dict:
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


def _make_session(session_id: str, n_turns: int) -> Session:
    base = datetime.datetime(2026, 5, 17, 12, 0, 0,
                             tzinfo=datetime.timezone.utc)
    turns = [
        Turn(
            timestamp=base + datetime.timedelta(minutes=i),
            human_input=f"req {i} for {session_id}",
            assistant_response=f"resp {i} for {session_id}",
            tool_calls=[],
            model="m",
            input_tokens=100,
            output_tokens=50,
        )
        for i in range(n_turns)
    ]
    return Session(
        session_id=session_id,
        start_time=base,
        end_time=base + datetime.timedelta(minutes=n_turns),
        file_path=Path(f"/tmp/{session_id}.jsonl"),
        turns=turns,
    )


# ---------------------------------------------------------------------------
# E2E integration
# ---------------------------------------------------------------------------


def test_full_pipeline_produces_spec_shaped_document(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    sessions = [
        _make_session("s1", n_turns=3),
        _make_session("s2", n_turns=4),
    ]
    runner = StageDispatchRunner()

    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    # Exactly the four spec keys, no more, no less.
    assert set(out.keys()) == {
        "per_turn_observations",
        "pass_classifications",
        "gap_observations",
        "session_narratives",
    }, f"unexpected top-level keys: {sorted(out.keys())}"

    # Every stage was exercised — sanity check that the orchestrator
    # is in fact running the full pipeline.
    for stage in ("1a", "1b", "2", "3", "4"):
        assert runner.calls_by_stage[stage] >= 1, (
            f"stage {stage} never ran; counts={runner.calls_by_stage}"
        )


def test_full_pipeline_exhaustive_over_the_window(tmp_path: Path) -> None:
    """Spec invariant: every turn has an observation, every pass has a
    classification, every session has a narrative."""
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    sessions = [
        _make_session("s1", n_turns=2),
        _make_session("s2", n_turns=3),
        _make_session("s3", n_turns=5),
    ]
    runner = StageDispatchRunner()
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    # Every (session, turn) appears in per_turn_observations.
    obs_keys = {
        (o["session_id"], o["turn_index"])
        for o in out["per_turn_observations"]
    }
    expected_keys = {
        (s.session_id, i)
        for s in sessions for i in range(len(s.turns))
    }
    assert obs_keys == expected_keys, (
        f"per_turn_observations not exhaustive; "
        f"missing={expected_keys - obs_keys}, extra={obs_keys - expected_keys}"
    )

    # Every session has exactly one narrative.
    narrative_ids = sorted(n["session_id"] for n in out["session_narratives"])
    assert narrative_ids == sorted(s.session_id for s in sessions)


def test_full_pipeline_pass_classifications_cover_each_session(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    sessions = [_make_session("s1", n_turns=3)]
    runner = StageDispatchRunner()
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    pcs = [p for p in out["pass_classifications"]
           if p["session_id"] == "s1"]
    assert pcs, "no pass_classifications produced for s1"
    # Coverage of turns 0..2 (canned response covers the full range).
    covered = set()
    for pc in pcs:
        start, end = pc["turn_range"][0], pc["turn_range"][1]
        for i in range(start, end + 1):
            covered.add(i)
    assert covered == {0, 1, 2}, (
        f"pass_classifications must cover every turn of s1; got {covered}"
    )


def test_full_pipeline_no_scalar_grades_in_output(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    sessions = [_make_session("s1", n_turns=3)]
    runner = StageDispatchRunner()
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    bad = _scan_for_forbidden_scalar_keys(out)
    assert not bad, (
        f"orchestrator end-to-end output contains forbidden scalar "
        f"keys: {bad}"
    )
