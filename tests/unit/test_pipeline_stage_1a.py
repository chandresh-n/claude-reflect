"""
Session A failing-gate tests for step 13 — stage 1a (per-turn description).

Stage 1a takes ONE turn at a time and produces a compact structured
description used by stages 1b/2/3 instead of the raw turn text.  Pins:

  - Output schema: session_id, turn_index, goal_signal, action_signal,
    outcome_signal (enum), friction_signal (str, possibly empty),
    effort_signal (input_tokens, output_tokens, model), tool_actions[],
    evidence_anchors[].
  - tool_actions extracts the target (file path / command / query /
    recipient) and outcome (ok|error|denied) for each tool call.
  - MCP tool calls denied by the user surface as outcome="denied".
  - Within-turn clustering of many similar tool calls is allowed and
    encouraged (cluster form has `count` and `targets[]`).
  - Cache hit on the same turn results in zero runner invocations.
  - One turn's failure does not prevent other turns from being described.

Expected to FAIL on import until step 13 lands stage_1a.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from meta_harness.storage.session_logs import Session, ToolCall, Turn


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _turn(human: str, asst: str,
          tools: list[tuple[str, dict]] | None = None) -> Turn:
    return Turn(
        timestamp=datetime(2026, 5, 14, tzinfo=timezone.utc),
        human_input=human,
        assistant_response=asst,
        tool_calls=[ToolCall(name=name, input=inp)
                    for name, inp in (tools or [])],
        model="claude-opus-4-7",
        input_tokens=120,
        output_tokens=80,
    )


def _session(sid: str, turns: list[Turn]) -> Session:
    base = datetime(2026, 5, 14, tzinfo=timezone.utc)
    return Session(
        session_id=sid, start_time=base,
        end_time=base + timedelta(minutes=len(turns)),
        file_path=Path(f"/tmp/{sid}.jsonl"), turns=turns,
    )


def _canned_runner(output: str | list[str]) -> MagicMock:
    """A Runner double whose .invoke returns canned text."""
    r = MagicMock()
    if isinstance(output, str):
        r.invoke.return_value = output
    else:
        r.invoke.side_effect = output
    return r


def _valid_description_for(session_id: str, turn_index: int,
                           **overrides) -> str:
    """Return a JSON string the model could plausibly emit for one turn."""
    base = {
        "session_id": session_id,
        "turn_index": turn_index,
        "goal_signal": "the human asked for X",
        "action_signal": "the assistant did Y",
        "outcome_signal": "completed",
        "friction_signal": "",
        "effort_signal": {
            "input_tokens": 120, "output_tokens": 80,
            "model": "claude-opus-4-7",
        },
        "tool_actions": [],
        "evidence_anchors": [],
    }
    base.update(overrides)
    return json.dumps(base)


# ---------------------------------------------------------------------------
# Importable + simple happy path
# ---------------------------------------------------------------------------


def test_stage_1a_module_importable() -> None:
    from meta_harness.agents.pipeline.stage_1a import (  # type: ignore  # noqa: F401
        describe_turn,
    )


def test_describe_turn_returns_dict_with_required_schema(tmp_path: Path) -> None:
    """Pin the schema for stage 1a's output.  Downstream stages
    consume these fields by name."""
    from meta_harness.agents.pipeline.stage_1a import describe_turn  # type: ignore

    t = _turn("how do tests run?", "use pytest")
    runner = _canned_runner(_valid_description_for("s1", 0))

    out = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )

    required = {
        "session_id", "turn_index",
        "goal_signal", "action_signal",
        "outcome_signal", "friction_signal",
        "effort_signal", "tool_actions", "evidence_anchors",
    }
    missing = required - set(out.keys())
    assert not missing, f"Description missing fields: {missing}"
    assert out["session_id"] == "s1"
    assert out["turn_index"] == 0
    assert out["outcome_signal"] in {
        "completed", "partial", "blocked",
        "tool_failure", "clarification_needed",
        "agent_continued_without_outcome",
    }


# ---------------------------------------------------------------------------
# tool_actions extraction across tool kinds (the level-2 signal)
# ---------------------------------------------------------------------------


def test_tool_actions_capture_read_file_path(tmp_path: Path) -> None:
    """For a Read tool call, tool_actions[*].target must be the file path
    so downstream stages can see *what* was read, not just `Read: 1`."""
    from meta_harness.agents.pipeline.stage_1a import describe_turn  # type: ignore

    t = _turn(
        "look at the evaluator",
        "reading it now",
        tools=[("Read", {"file_path": "src/meta_harness/agents/evaluator.py"})],
    )
    runner = _canned_runner(_valid_description_for(
        "s1", 0,
        tool_actions=[{
            "tool": "Read",
            "target": "src/meta_harness/agents/evaluator.py",
            "outcome": "ok",
        }],
    ))
    out = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )
    assert out["tool_actions"], "tool_actions must not be empty for a Read turn"
    first = out["tool_actions"][0]
    assert first["tool"] == "Read"
    assert first["target"].endswith("evaluator.py")
    assert first["outcome"] == "ok"


def test_tool_actions_capture_bash_command(tmp_path: Path) -> None:
    from meta_harness.agents.pipeline.stage_1a import describe_turn  # type: ignore

    t = _turn(
        "run tests",
        "running pytest",
        tools=[("Bash", {"command": "pytest -q tests/unit"})],
    )
    runner = _canned_runner(_valid_description_for(
        "s1", 0,
        tool_actions=[{
            "tool": "Bash",
            "target": "pytest -q tests/unit",
            "outcome": "ok",
        }],
    ))
    out = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )
    a = out["tool_actions"][0]
    assert a["tool"] == "Bash"
    assert "pytest" in a["target"]


def test_tool_actions_surface_denied_outcome_for_mcp_tools(tmp_path: Path) -> None:
    """The agentic-failure RCA showed batches stuck on denied MCP tool
    calls.  Stage 1a must surface that fact so pattern detection and
    gap-mining can see it as a distinct outcome, not as `error`."""
    from meta_harness.agents.pipeline.stage_1a import describe_turn  # type: ignore

    t = _turn(
        "ignore this — context for the model",
        "tried to email",
        tools=[("mcp__claude_ai_Gmail__create_draft",
                {"to": ["a@b"], "subject": "x"})],
    )
    runner = _canned_runner(_valid_description_for(
        "s1", 0,
        tool_actions=[{
            "tool": "mcp__claude_ai_Gmail__create_draft",
            "target": "a@b",
            "outcome": "denied",
        }],
    ))
    out = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )
    a = out["tool_actions"][0]
    assert a["outcome"] == "denied"


def test_tool_actions_accept_clustered_form_for_many_similar_calls(
    tmp_path: Path,
) -> None:
    """A turn with 12 Reads can be collapsed into a single clustered
    tool_action with `count` and `targets` to keep the description compact.
    Both flat and clustered forms must be schema-acceptable."""
    from meta_harness.agents.pipeline.stage_1a import describe_turn  # type: ignore

    targets = [f"src/file_{i}.py" for i in range(12)]
    t = _turn(
        "explore the codebase",
        "reading agent files",
        tools=[("Read", {"file_path": p}) for p in targets],
    )
    runner = _canned_runner(_valid_description_for(
        "s1", 0,
        tool_actions=[{
            "tool": "Read",
            "count": 12,
            "targets": targets,
            "outcome": "all_ok",
            "notes": "explored agent source files",
        }],
    ))
    out = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )
    a = out["tool_actions"][0]
    assert a.get("count") == 12
    assert isinstance(a.get("targets"), list)
    assert len(a["targets"]) == 12


# ---------------------------------------------------------------------------
# Cache integration
# ---------------------------------------------------------------------------


def test_describe_turn_caches_result_and_skips_runner_on_rerun(
    tmp_path: Path,
) -> None:
    """First call invokes the runner.  Second call on the same turn
    must reuse the cache and invoke the runner zero additional times."""
    from meta_harness.agents.pipeline.stage_1a import describe_turn  # type: ignore

    t = _turn("hi", "hello")
    runner = _canned_runner(_valid_description_for("s1", 0))

    out1 = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1

    out2 = describe_turn(
        session_id="s1", turn_index=0, turn=t,
        runner=runner, repo=tmp_path, model="m",
    )
    assert runner.invoke.call_count == 1, (
        "Second call must hit the cache and NOT invoke the runner again."
    )
    assert out2 == out1


# ---------------------------------------------------------------------------
# Failure isolation across turns
# ---------------------------------------------------------------------------


def test_one_turn_failure_does_not_taint_other_turns(tmp_path: Path) -> None:
    """A failed runner call for turn N must not prevent turn N+1's
    description from being produced.  This is the partial-with-flag
    failure policy at the per-turn granularity inside stage 1a."""
    from meta_harness.agents.pipeline.stage_1a import (  # type: ignore
        describe_session_turns,
    )

    s = _session("s1", [_turn("a", "b"), _turn("c", "d"), _turn("e", "f")])

    # Make the runner fail on turn 1 only.
    runner = MagicMock()
    def side(*, system_prompt, user_prompt, model, **kw):
        # turn_index encoded in the user_prompt by stage 1a; we don't need
        # to inspect it — fail on the second call regardless.
        runner.invoke.call_count  # noqa: B018  (left for clarity)
        if runner.invoke.call_count == 2:
            raise RuntimeError("simulated transient model failure")
        return _valid_description_for("s1", runner.invoke.call_count - 1)
    runner.invoke.side_effect = side

    results = describe_session_turns(
        session=s, runner=runner, repo=tmp_path, model="m",
    )

    # Three turns in, two descriptions out (turn 1 should be flagged
    # missing rather than crashing the whole call).
    assert len(results) == 3
    # Exactly one of them is the failure sentinel; the other two are
    # full descriptions.
    failures = [r for r in results if r.get("_failed")]
    successes = [r for r in results if not r.get("_failed")]
    assert len(failures) == 1
    assert len(successes) == 2
    # Successful turns still carry the schema.
    for ok in successes:
        assert "outcome_signal" in ok
