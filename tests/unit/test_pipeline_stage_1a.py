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

from claude_reflect.storage.session_logs import Session, ToolCall, Turn


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
    from claude_reflect.agents.pipeline.stage_1a import (  # type: ignore  # noqa: F401
        describe_turn,
    )


def test_describe_turn_returns_dict_with_required_schema(tmp_path: Path) -> None:
    """Pin the schema for stage 1a's output.  Downstream stages
    consume these fields by name."""
    from claude_reflect.agents.pipeline.stage_1a import describe_turn  # type: ignore

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
    from claude_reflect.agents.pipeline.stage_1a import describe_turn  # type: ignore

    t = _turn(
        "look at the evaluator",
        "reading it now",
        tools=[("Read", {"file_path": "src/claude_reflect/agents/evaluator.py"})],
    )
    runner = _canned_runner(_valid_description_for(
        "s1", 0,
        tool_actions=[{
            "tool": "Read",
            "target": "src/claude_reflect/agents/evaluator.py",
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
    from claude_reflect.agents.pipeline.stage_1a import describe_turn  # type: ignore

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
    from claude_reflect.agents.pipeline.stage_1a import describe_turn  # type: ignore

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
    from claude_reflect.agents.pipeline.stage_1a import describe_turn  # type: ignore

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
    from claude_reflect.agents.pipeline.stage_1a import describe_turn  # type: ignore

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


def _multi_turn_session(sid: str, n: int):
    """n turns, each with a unique human message so prompts differ."""
    return _session(sid, [_turn(f"q{i}", f"a{i}") for i in range(n)])


def test_describe_session_turns_preserves_turn_order_under_parallelism(
    tmp_path: Path,
) -> None:
    """Phase 2 contract: with max_concurrent > 1, per-turn calls run on
    a thread pool and may complete in arbitrary order. The returned
    list must still be in turn_index order so downstream stages
    (1b/2/3) see temporal sequence.

    Verified by deliberately making the EARLIEST turn the SLOWEST so
    completion order is the reverse of submission order; any naive
    'append as completed' implementation would surface bug visibly.
    """
    import threading
    import time

    from claude_reflect.agents.pipeline.stage_1a import (  # type: ignore
        describe_session_turns,
    )

    n_turns = 6
    s = _multi_turn_session("s-order", n_turns)

    # Make turn 0 sleep the most, turn 1 less, etc. Completion order
    # under parallel execution will be turn 5, 4, 3, 2, 1, 0 — the
    # opposite of turn_index order.
    runner = MagicMock()
    call_lock = threading.Lock()
    invocation_order: list[int] = []

    def side(*, system_prompt, user_prompt, model, **kw):
        # Pluck turn_index out of the prompt.
        ti = int(_parse_field(user_prompt, "turn_index"))
        time.sleep(0.05 * (n_turns - ti))  # earlier turn → longer sleep
        with call_lock:
            invocation_order.append(ti)
        return _valid_description_for("s-order", ti)
    runner.invoke.side_effect = side

    results = describe_session_turns(
        session=s, runner=runner, repo=tmp_path, model="m",
        max_concurrent=n_turns,
    )

    # Completion order should NOT match turn_index order (sanity check
    # that we actually exercised the out-of-order path; otherwise the
    # ordering assertion below is vacuous).
    assert invocation_order != sorted(invocation_order), (
        f"test setup is broken — calls should have completed out of "
        f"order with this sleep profile but got {invocation_order!r}"
    )
    # Output must still be in turn_index order regardless.
    assert [r["turn_index"] for r in results] == list(range(n_turns)), (
        f"parallel describe_session_turns must reorder results by "
        f"turn_index; got {[r['turn_index'] for r in results]!r}"
    )


def test_describe_session_turns_respects_max_concurrent_ceiling(
    tmp_path: Path,
) -> None:
    """The ceiling must actually bound thread-pool fanout. We submit
    more turns than the ceiling allows and verify the observed peak
    in-flight count never exceeds the ceiling."""
    import threading
    import time

    from claude_reflect.agents.pipeline.stage_1a import (  # type: ignore
        describe_session_turns,
    )

    n_turns = 12
    ceiling = 3
    s = _multi_turn_session("s-cap", n_turns)

    in_flight = 0
    peak = 0
    lock = threading.Lock()
    runner = MagicMock()

    def side(*, system_prompt, user_prompt, model, **kw):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        # Hold the slot long enough that competing submissions would
        # also try to enter if the pool let them.
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        ti = int(_parse_field(user_prompt, "turn_index"))
        return _valid_description_for("s-cap", ti)
    runner.invoke.side_effect = side

    describe_session_turns(
        session=s, runner=runner, repo=tmp_path, model="m",
        max_concurrent=ceiling,
    )
    assert peak <= ceiling, (
        f"max_concurrent={ceiling} but observed {peak} concurrent calls"
    )
    # Lower bound: we should have exceeded sequential execution.
    assert peak > 1, (
        f"max_concurrent={ceiling} but the pool never ran more than 1 "
        f"call concurrently — parallelism not actually exercised"
    )


def test_describe_session_turns_parallel_isolates_per_turn_failure(
    tmp_path: Path,
) -> None:
    """Failure isolation must hold under parallelism: one failing
    invocation must surface as a _failed sentinel, not a thread-pool
    exception that crashes the whole call."""
    from claude_reflect.agents.pipeline.stage_1a import (  # type: ignore
        describe_session_turns,
    )

    s = _multi_turn_session("s-fail", 5)
    runner = MagicMock()

    def side(*, system_prompt, user_prompt, model, **kw):
        ti = int(_parse_field(user_prompt, "turn_index"))
        if ti == 2:
            raise RuntimeError("simulated failure on turn 2")
        return _valid_description_for("s-fail", ti)
    runner.invoke.side_effect = side

    results = describe_session_turns(
        session=s, runner=runner, repo=tmp_path, model="m",
        max_concurrent=4,
    )

    assert len(results) == 5
    failures = [r for r in results if r.get("_failed")]
    successes = [r for r in results if not r.get("_failed")]
    assert len(failures) == 1
    assert failures[0]["turn_index"] == 2
    assert len(successes) == 4


def _parse_field(prompt: str, field: str) -> str:
    """Pull ``field: value`` out of a stage 1a prompt. Duplicated from
    the orchestrator test for self-containment."""
    for line in prompt.splitlines():
        line = line.strip()
        prefix = f"{field}:"
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise AssertionError(
        f"could not find field {field!r} in prompt; first 400 chars="
        f"{prompt[:400]!r}"
    )


def test_one_turn_failure_does_not_taint_other_turns(tmp_path: Path) -> None:
    """A failed runner call for turn N must not prevent turn N+1's
    description from being produced.  This is the partial-with-flag
    failure policy at the per-turn granularity inside stage 1a."""
    from claude_reflect.agents.pipeline.stage_1a import (  # type: ignore
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
