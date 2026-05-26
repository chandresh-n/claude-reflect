"""
Session A failing-gate tests for step 15 — pipeline orchestrator.

The orchestrator sequences stages 1a → 1b → 2 → 3 → 4 over the
session window, surfaces per-stage progress under
``.claude-reflect/logs/eval/<timestamp>/stages/``, propagates
partial-completion flags through to the final
``session_narratives`` without aborting, and uses the per-stage
caches so a re-run with identical inputs makes zero model calls.

Pins (HARD — from docs/PLAN.md Step 15):

  - module is importable from ``claude_reflect.agents.pipeline.orchestrator``
    and exposes ``evaluate``
  - sequencing: with mocked stages 1a→1b→2→3→4, the orchestrator
    invokes them in order and threads each stage's output into the
    next; per-stage progress lands under
    ``.claude-reflect/logs/eval/<timestamp>/stages/``
  - partial-failure propagation: a stage 1b window failure on one
    session sets ``partial_completion=True`` on that session's
    narrative in the final output WITHOUT aborting the run or
    dropping unaffected sessions
  - cache-resume: a re-run with identical inputs makes ZERO model
    calls (every stage hits its cache)
  - new-session re-run: adding one new session only re-runs that
    session's 1a/1b/2/3 plus the corpus-level 4; the other sessions
    hit cache
  - final output has exactly the four spec keys
    (per_turn_observations, pass_classifications, gap_observations,
    session_narratives)
  - no scalar grades anywhere in the orchestrator's final output

Expected to FAIL on import until step 15 lands the orchestrator.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from claude_reflect.storage.session_logs import Session, Turn


_FORBIDDEN_SCALAR_KEYS = {
    "quality_score", "quality", "score", "confidence", "priority",
    "rating", "grade", "severity", "rank",
}


# ---------------------------------------------------------------------------
# Smart stage-dispatching mock runner
# ---------------------------------------------------------------------------


class StageDispatchRunner:
    """A Runner mock that classifies each invocation by stage and
    returns plausible canned JSON for that stage.

    Stage classification looks at the system_prompt for stable
    substrings emitted by each stage module. Stage 4's prompt must
    include the substring "cross-session" so the dispatcher can
    distinguish it from stages 1a/1b/2/3.

    The classifier also accepts a ``fail_predicate`` so individual
    invocations can be made to raise — used by the partial-failure
    test to make exactly one stage 1b window fail for one session.
    """

    def __init__(self, *, fail_predicate=None) -> None:
        self.fail_predicate = fail_predicate
        self.calls_by_stage: dict[str, int] = {
            "1a": 0, "1b": 0, "2": 0, "3": 0, "4": 0,
        }
        self.invocations: list[dict] = []

    @staticmethod
    def classify(system_prompt: str) -> str:
        sp = system_prompt.lower()
        # Stage 4 first: must be distinguishable from stages 1a-3.
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
            "the stage's system_prompt must contain one of the pinned "
            "markers (per-turn describer / windowed observer / "
            "pass-refiner / narrative writer / cross-session). "
            f"system_prompt[:200]={system_prompt[:200]!r}"
        )

    def _canned_for_stage(self, stage: str, user_prompt: str) -> str:
        if stage == "1a":
            # Use session_id+turn_index parsed from user prompt.
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
            # Count the number of turns by counting "turn_index" occurrences.
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

    def invoke(self, *, system_prompt: str, user_prompt: str,
               model: str, **kwargs) -> str:
        stage = self.classify(system_prompt)
        self.calls_by_stage[stage] += 1
        self.invocations.append({
            "stage": stage, "model": model,
            "system_prompt": system_prompt, "user_prompt": user_prompt,
        })
        if self.fail_predicate is not None:
            if self.fail_predicate(stage, system_prompt, user_prompt):
                raise RuntimeError(
                    f"simulated stage {stage} failure for test"
                )
        return self._canned_for_stage(stage, user_prompt)


def _parse_field(prompt: str, field: str) -> str:
    """Extract ``field: value`` (line-anchored) from a prompt string."""
    for line in prompt.splitlines():
        line = line.strip()
        prefix = f"{field}:"
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise AssertionError(
        f"could not find field {field!r} in prompt; first 400 chars="
        f"{prompt[:400]!r}"
    )


def _parse_turn_indices(prompt: str) -> list[int]:
    """Parse all turn_index integers appearing in the prompt's JSON."""
    import re

    matches = re.findall(r'"turn_index"\s*:\s*(\d+)', prompt)
    # De-dup while preserving order.
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


def _make_session(session_id: str, n_turns: int = 3) -> Session:
    base = datetime.datetime(2026, 5, 17, 12, 0, 0,
                             tzinfo=datetime.timezone.utc)
    turns = [
        Turn(
            timestamp=base + datetime.timedelta(minutes=i),
            human_input=f"please do thing {i} in {session_id}",
            assistant_response=f"did thing {i} in {session_id}",
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
# Importable + signature
# ---------------------------------------------------------------------------


def test_orchestrator_module_importable() -> None:
    from claude_reflect.agents.pipeline.orchestrator import (  # type: ignore  # noqa: F401
        evaluate,
    )


def test_orchestrator_evaluate_accepts_runner_injection(
    tmp_path: Path,
) -> None:
    """The orchestrator's ``evaluate`` must accept a ``runner`` kwarg so
    tests can inject a mock without touching real Claude subprocesses."""
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    runner = StageDispatchRunner()
    sessions = [_make_session("s1", n_turns=2)]
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )
    # If the call works at all, runner saw some calls.
    assert sum(runner.calls_by_stage.values()) > 0
    # Output present.
    assert isinstance(out, dict)


# ---------------------------------------------------------------------------
# Stage sequencing + per-stage logging
# ---------------------------------------------------------------------------


def test_orchestrator_sequences_all_five_stages(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    runner = StageDispatchRunner()
    sessions = [_make_session("s1", n_turns=3),
                _make_session("s2", n_turns=3)]
    evaluate(sessions=sessions, repo=tmp_path, model="m", runner=runner)

    # Every stage was invoked at least once.
    for stage in ("1a", "1b", "2", "3", "4"):
        assert runner.calls_by_stage[stage] >= 1, (
            f"stage {stage} was not invoked by the orchestrator; "
            f"counts={runner.calls_by_stage}"
        )

    # Stage 1a is per-turn: 2 sessions × 3 turns = 6 invocations.
    assert runner.calls_by_stage["1a"] == 6, (
        f"expected 6 stage 1a calls (2 sessions × 3 turns), got "
        f"{runner.calls_by_stage['1a']}"
    )
    # Stage 4 is corpus-level, exactly one call.
    assert runner.calls_by_stage["4"] == 1, (
        f"stage 4 must run exactly once for the corpus, got "
        f"{runner.calls_by_stage['4']}"
    )


def test_orchestrator_writes_per_stage_progress_logs(tmp_path: Path) -> None:
    """Per-stage progress lands under
    ``.claude-reflect/logs/eval/<timestamp>/stages/``. The orchestrator
    creates ONE timestamped run dir per invocation and a ``stages/``
    subdir inside it."""
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    runner = StageDispatchRunner()
    sessions = [_make_session("s1", n_turns=2)]
    evaluate(sessions=sessions, repo=tmp_path, model="m", runner=runner)

    log_root = tmp_path / ".claude-reflect" / "logs" / "eval"
    assert log_root.is_dir(), (
        f"orchestrator must create the eval log root at {log_root}"
    )
    run_dirs = [p for p in log_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1, (
        "Exactly one timestamped run dir must be created per invocation; "
        f"got {len(run_dirs)}: {run_dirs}"
    )
    stages_dir = run_dirs[0] / "stages"
    assert stages_dir.is_dir(), (
        f"orchestrator must create a stages/ subdir at {stages_dir}"
    )
    # Some artefact must be written for at least one stage.
    contents = list(stages_dir.rglob("*"))
    assert any(p.is_file() for p in contents), (
        f"stages/ must contain at least one progress artefact; "
        f"contents={contents}"
    )


# ---------------------------------------------------------------------------
# Final output shape
# ---------------------------------------------------------------------------


def test_orchestrator_final_output_has_exactly_four_spec_keys(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    runner = StageDispatchRunner()
    sessions = [_make_session("s1", n_turns=2)]
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    expected = {
        "per_turn_observations",
        "pass_classifications",
        "gap_observations",
        "session_narratives",
    }
    assert set(out.keys()) == expected, (
        f"orchestrator final output must have exactly {expected}; "
        f"got {set(out.keys())}"
    )
    assert isinstance(out["per_turn_observations"], list)
    assert isinstance(out["pass_classifications"], list)
    assert isinstance(out["gap_observations"], list)
    assert isinstance(out["session_narratives"], list)


def test_orchestrator_final_output_has_no_scalar_grades(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    runner = StageDispatchRunner()
    sessions = [_make_session("s1", n_turns=2)]
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    bad = _scan_for_forbidden_scalar_keys(out)
    assert not bad, (
        f"orchestrator final output contains forbidden scalar keys: {bad}"
    )


def test_orchestrator_produces_one_narrative_per_session(
    tmp_path: Path,
) -> None:
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    runner = StageDispatchRunner()
    sessions = [_make_session("s1", n_turns=2),
                _make_session("s2", n_turns=4),
                _make_session("s3", n_turns=3)]
    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    narratives = out["session_narratives"]
    assert len(narratives) == 3
    seen_ids = sorted(n["session_id"] for n in narratives)
    assert seen_ids == ["s1", "s2", "s3"]


# ---------------------------------------------------------------------------
# Partial-failure propagation
# ---------------------------------------------------------------------------


def test_orchestrator_propagates_partial_completion_per_session(
    tmp_path: Path,
) -> None:
    """A stage 1b window failure on session s1 must produce a narrative
    for s1 with ``partial_completion=True`` while s2 finishes cleanly
    (no flag) and the run does NOT abort or drop s1."""
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    def fail_on_s1_stage1b(stage: str, system_prompt: str, user_prompt: str) -> bool:
        if stage != "1b":
            return False
        sid = _parse_field(user_prompt, "session_id")
        return sid == "s1"

    runner = StageDispatchRunner(fail_predicate=fail_on_s1_stage1b)
    sessions = [_make_session("s1", n_turns=3),
                _make_session("s2", n_turns=3)]

    out = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=runner,
    )

    by_sid = {n["session_id"]: n for n in out["session_narratives"]}
    assert "s1" in by_sid, (
        "s1 must remain in the final output even though its stage 1b "
        "windows failed — partial-with-flag, not drop."
    )
    assert by_sid["s1"].get("partial_completion") is True, (
        "s1's narrative must carry partial_completion=True after a "
        "stage 1b failure for that session."
    )
    assert "s2" in by_sid
    assert by_sid["s2"].get("partial_completion", False) is False, (
        "s2's narrative must NOT carry partial_completion=True; "
        "the partial flag is per-session, not global."
    )


# ---------------------------------------------------------------------------
# Cache-resume
# ---------------------------------------------------------------------------


def test_orchestrator_identical_rerun_makes_zero_model_calls(
    tmp_path: Path,
) -> None:
    """A re-run with identical inputs must hit every stage's cache and
    invoke the runner zero times."""
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    sessions = [_make_session("s1", n_turns=3),
                _make_session("s2", n_turns=3)]

    # First run: populates caches.
    first_runner = StageDispatchRunner()
    out1 = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=first_runner,
    )
    assert sum(first_runner.calls_by_stage.values()) > 0

    # Second run with same inputs: runner must not be invoked at all.
    class ForbiddenRunner:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, *, system_prompt: str, user_prompt: str,
                   model: str, **kwargs) -> str:
            self.calls += 1
            raise AssertionError(
                "cache-resume violated: orchestrator invoked the runner "
                "on a re-run with identical inputs. system_prompt[:120]="
                f"{system_prompt[:120]!r}"
            )

    forbidden = ForbiddenRunner()
    out2 = evaluate(
        sessions=sessions, repo=tmp_path, model="m", runner=forbidden,
    )
    assert forbidden.calls == 0, (
        "Identical re-run must make ZERO model calls; "
        f"runner was invoked {forbidden.calls} time(s)"
    )

    # Outputs must be structurally equivalent (same 4 keys).
    assert set(out1.keys()) == set(out2.keys())


def test_orchestrator_new_session_only_re_runs_new_session_and_stage4(
    tmp_path: Path,
) -> None:
    """Adding one new session to the window must only re-run that
    session's 1a/1b/2/3, plus the corpus-level stage 4. Previously
    cached sessions hit their per-stage caches."""
    from claude_reflect.agents.pipeline.orchestrator import evaluate  # type: ignore

    first_sessions = [_make_session("s1", n_turns=3),
                      _make_session("s2", n_turns=3)]
    first_runner = StageDispatchRunner()
    evaluate(
        sessions=first_sessions, repo=tmp_path, model="m",
        runner=first_runner,
    )

    # Second run: add a new session s3 (n_turns=4 to differ from s1/s2).
    second_sessions = first_sessions + [_make_session("s3", n_turns=4)]
    second_runner = StageDispatchRunner()
    evaluate(
        sessions=second_sessions, repo=tmp_path, model="m",
        runner=second_runner,
    )

    # 1a: only s3's 4 turns should hit the runner (s1/s2 cached).
    assert second_runner.calls_by_stage["1a"] == 4, (
        f"stage 1a should only re-run for the new session's turns; "
        f"got {second_runner.calls_by_stage['1a']} (expected 4)"
    )
    # 1b/2/3: only s3 should re-run.
    assert second_runner.calls_by_stage["2"] == 1, (
        f"stage 2 should only re-run for s3; got "
        f"{second_runner.calls_by_stage['2']}"
    )
    assert second_runner.calls_by_stage["3"] == 1, (
        f"stage 3 should only re-run for s3; got "
        f"{second_runner.calls_by_stage['3']}"
    )
    # Stage 4 is corpus-level; corpus changed so it must re-run.
    assert second_runner.calls_by_stage["4"] == 1, (
        f"stage 4 must re-run after corpus changes; got "
        f"{second_runner.calls_by_stage['4']}"
    )
