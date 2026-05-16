"""
Session A failing-gate tests for step 13 — deterministic session manifest.

The manifest gives downstream stages session-level orientation (counts,
duration, what tools were used, first/last turn excerpts) without paying
for a model call.  It MUST be:

  - Deterministic: same session in → byte-identical output.
  - Zero-cost: no LLM call.  Derived purely from parsed JSONL.
  - Sufficient: every field used by later stages is present.

Expected to FAIL on import until step 13 lands the module.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from meta_harness.storage.session_logs import Session, ToolCall, Turn


def _turn(human: str, asst: str, tools: list[str] | None = None,
          ts_offset_min: int = 0) -> Turn:
    base = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    return Turn(
        timestamp=base + timedelta(minutes=ts_offset_min),
        human_input=human,
        assistant_response=asst,
        tool_calls=[ToolCall(name=t, input={}) for t in (tools or [])],
        model="claude-opus-4-7",
        input_tokens=100,
        output_tokens=80,
    )


def _session(sid: str, turns: list[Turn]) -> Session:
    return Session(
        session_id=sid,
        start_time=turns[0].timestamp if turns else
            datetime(2026, 5, 14, tzinfo=timezone.utc),
        end_time=turns[-1].timestamp if turns else
            datetime(2026, 5, 14, tzinfo=timezone.utc),
        file_path=Path(f"/tmp/{sid}.jsonl"),
        turns=turns,
    )


def test_manifest_module_importable() -> None:
    from meta_harness.agents.pipeline.manifest import (  # type: ignore  # noqa: F401
        build_session_manifest,
    )


def test_manifest_has_required_fields() -> None:
    """Downstream stages depend on a specific set of fields; this pins them."""
    from meta_harness.agents.pipeline.manifest import (  # type: ignore
        build_session_manifest,
    )

    s = _session("s-demo", [
        _turn("install deps", "running pip install", tools=["Bash"],
              ts_offset_min=0),
        _turn("now run tests", "running pytest", tools=["Bash"],
              ts_offset_min=5),
        _turn("which file is failing?", "checking", tools=["Read"],
              ts_offset_min=10),
    ])
    m = build_session_manifest(s)

    # Allow either a dict or a dataclass — read as a dict for the assertions.
    if not isinstance(m, dict):
        m = m.__dict__  # type: ignore[attr-defined]

    required = {
        "session_id",
        "turn_count",
        "duration_seconds",
        "tool_call_counts",
        "first_turn_excerpts",
        "last_turn_excerpts",
    }
    missing = required - set(m.keys())
    assert not missing, f"Manifest missing required fields: {missing}"


def test_manifest_fields_are_populated_correctly() -> None:
    from meta_harness.agents.pipeline.manifest import (  # type: ignore
        build_session_manifest,
    )

    s = _session("s-demo", [
        _turn("install deps", "running pip install", tools=["Bash"],
              ts_offset_min=0),
        _turn("now run tests", "running pytest", tools=["Bash"],
              ts_offset_min=5),
        _turn("which file is failing?", "checking", tools=["Read"],
              ts_offset_min=10),
        _turn("fix it", "editing file", tools=["Edit"],
              ts_offset_min=15),
    ])
    m = build_session_manifest(s)
    if not isinstance(m, dict):
        m = m.__dict__

    assert m["session_id"] == "s-demo"
    assert m["turn_count"] == 4
    assert m["duration_seconds"] == 15 * 60   # 0 → 15 min
    assert m["tool_call_counts"] == {"Bash": 2, "Read": 1, "Edit": 1}
    # Excerpts should be small (first 3 / last 3 of the human side at minimum).
    assert isinstance(m["first_turn_excerpts"], list)
    assert isinstance(m["last_turn_excerpts"], list)
    assert len(m["first_turn_excerpts"]) <= 3
    assert len(m["last_turn_excerpts"]) <= 3


def test_manifest_is_deterministic_byte_identical() -> None:
    """Run twice on identical input — JSON serialization must be identical.

    This is required for caching and for the manifest itself to be a stable
    cache-key component."""
    from meta_harness.agents.pipeline.manifest import (  # type: ignore
        build_session_manifest,
    )

    s = _session("s-demo", [_turn("a", "b", tools=["Bash"], ts_offset_min=0)])
    a = build_session_manifest(s)
    b = build_session_manifest(s)
    a_dict = a if isinstance(a, dict) else a.__dict__
    b_dict = b if isinstance(b, dict) else b.__dict__
    # Sort keys to compare canonical JSON; values must already be in
    # deterministic order internally.
    assert json.dumps(a_dict, sort_keys=True, default=str) == \
           json.dumps(b_dict, sort_keys=True, default=str)


def test_manifest_makes_zero_model_calls() -> None:
    """Building a manifest must NOT invoke any LLM.  The whole point is
    that it's cheap, derived from parsed JSONL.  We mock invoke_claude
    at the runner layer and assert it never fired."""
    from meta_harness.agents.pipeline.manifest import (  # type: ignore
        build_session_manifest,
    )

    s = _session("s-demo", [_turn("a", "b", tools=["Bash"])])
    with patch(
        "meta_harness.agents.claude_runner.invoke_claude"
    ) as mock_invoke:
        build_session_manifest(s)
        assert mock_invoke.call_count == 0


def test_manifest_handles_empty_session() -> None:
    from meta_harness.agents.pipeline.manifest import (  # type: ignore
        build_session_manifest,
    )

    s = _session("s-empty", [])
    m = build_session_manifest(s)
    if not isinstance(m, dict):
        m = m.__dict__
    assert m["turn_count"] == 0
    assert m["tool_call_counts"] == {}
