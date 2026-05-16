"""
Tests for the evaluator's prompt-shape hardening.

Pins:
- Session content is wrapped in ``<archived_session_log>`` XML, not in
  conversational ``Human:`` / ``Assistant:`` headers (which the model
  would otherwise interpret as an open transcript to continue as an agent).
- The user prompt opens by framing the input as archived data and
  closes with the JSON-only schema instruction (last thing the model
  reads before generating).
- XML special chars in session content are escaped.

These pin a fix for the agentic-failure RCA: when MCP tools were in
context and the user prompt used Human:/Assistant: role headers, the
model treated the input as a conversation to continue and made 31 real
tool calls instead of producing the evaluator JSON schema.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from meta_harness.agents.evaluator import (
    _build_batch_prompt,
    _format_sessions_for_prompt,
    _xml_escape,
)
from meta_harness.storage.session_logs import Session, ToolCall, Turn


def _mk_session(sid: str, *, turns: list[Turn]) -> Session:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    return Session(
        session_id=sid,
        start_time=base,
        end_time=base + timedelta(minutes=len(turns)),
        file_path=Path(f"/tmp/{sid}.jsonl"),
        turns=turns,
    )


def _mk_turn(human: str, assistant: str, tools: list[str] | None = None) -> Turn:
    return Turn(
        timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        human_input=human,
        assistant_response=assistant,
        tool_calls=[ToolCall(name=t, input={}) for t in (tools or [])],
        model="claude-opus-4-7",
        input_tokens=10,
        output_tokens=10,
    )


# ---------------------------------------------------------------------------
# _format_sessions_for_prompt — XML structure, no role headers
# ---------------------------------------------------------------------------


def test_format_uses_archived_session_log_wrapper() -> None:
    s = _mk_session("s1", turns=[_mk_turn("hi", "hello")])
    out = _format_sessions_for_prompt([s])
    assert "<archived_session_log" in out
    assert "</archived_session_log>" in out
    assert 'session_id="s1"' in out


def test_format_has_no_conversational_role_headers() -> None:
    """The old shape used ``Human:`` / ``Assistant:`` / ``Tool calls:`` /
    ``### Turn N`` — those primed agentic continuation.  None of them
    should appear in the new prompt body."""
    s = _mk_session("s1", turns=[
        _mk_turn("a question", "an answer", tools=["Bash", "Read"]),
    ])
    out = _format_sessions_for_prompt([s])
    forbidden = ["Human:", "Assistant:", "Tool calls:", "### Turn ", "## Session:"]
    for f in forbidden:
        assert f not in out, (
            f"Forbidden conversational marker {f!r} found in prompt body — "
            f"this primes the model to act as an agent instead of an evaluator."
        )


def test_format_uses_past_tagged_content() -> None:
    s = _mk_session("s1", turns=[
        _mk_turn("a question", "an answer", tools=["Bash", "Read"]),
    ])
    out = _format_sessions_for_prompt([s])
    assert "<past_human>a question</past_human>" in out
    assert "<past_assistant>an answer</past_assistant>" in out
    assert "<past_tools_called>Bash, Read</past_tools_called>" in out


def test_format_includes_turn_offset_when_nonzero() -> None:
    s = _mk_session("s1", turns=[_mk_turn("h", "a")])
    out = _format_sessions_for_prompt([s], turn_offset=100)
    assert 'turn_offset="100"' in out
    assert 'index="100"' in out


def test_format_omits_turn_offset_attribute_when_zero() -> None:
    s = _mk_session("s1", turns=[_mk_turn("h", "a")])
    out = _format_sessions_for_prompt([s], turn_offset=0)
    assert "turn_offset=" not in out
    assert 'index="0"' in out


# ---------------------------------------------------------------------------
# XML escaping of session content
# ---------------------------------------------------------------------------


def test_xml_escape_handles_special_chars() -> None:
    assert _xml_escape("a<b&c>d") == "a&lt;b&amp;c&gt;d"
    assert _xml_escape("") == ""
    assert _xml_escape(None) == ""  # type: ignore[arg-type]


def test_format_escapes_xml_metachars_in_content() -> None:
    s = _mk_session("s1", turns=[
        _mk_turn(
            "look at <fake_tag> and & also </past_assistant>",
            "code: a<b && c>d",
        ),
    ])
    out = _format_sessions_for_prompt([s])
    # Raw < / & / > inside content should be escaped so they cannot prematurely
    # close our wrapper tags or break the model's structure recognition.
    assert "look at &lt;fake_tag&gt;" in out
    assert "&amp; also" in out
    assert "&lt;/past_assistant&gt;" in out
    assert "a&lt;b &amp;&amp; c&gt;d" in out


# ---------------------------------------------------------------------------
# _build_batch_prompt — framing at top, JSON instruction at bottom
# ---------------------------------------------------------------------------


def test_build_prompt_opens_with_archived_framing() -> None:
    s = _mk_session("s1", turns=[_mk_turn("h", "a")])
    chunks = [{"session": s, "turn_offset": 0, "total_turns": 1}]
    out = _build_batch_prompt(chunks, existing_gaps="")
    # First 200 chars must announce that the input is archived and the
    # model must not respond conversationally / not call tools.
    head = out[:400]
    assert "ARCHIVED" in head.upper()
    assert "not a conversation" in head.lower() or "not respond" in head.lower()
    assert "tool" in head.lower()  # mentions tool-call ban


def test_build_prompt_ends_with_json_only_instruction() -> None:
    """The schema-only instruction must be the LAST thing the model reads
    before generating, so it dominates the continuation decision."""
    s = _mk_session("s1", turns=[_mk_turn("h", "a")])
    chunks = [{"session": s, "turn_offset": 0, "total_turns": 1}]
    out = _build_batch_prompt(chunks, existing_gaps="")
    tail = out[-800:]
    # Schema keys must appear in the closing instruction.
    for key in (
        "per_turn_observations",
        "pass_classifications",
        "gap_observations",
        "session_narratives",
    ):
        assert key in tail, f"{key} should be reinforced in the closing instruction"
    # And explicit "no tools" / "no markdown" / "no preamble" reminders.
    low = tail.lower()
    assert "no" in low and "tool" in low
    assert "markdown" in low
    assert "preamble" in low or "postamble" in low


def test_build_prompt_wraps_sessions_inside_outer_tag() -> None:
    """All session XML must sit inside <archived_sessions_to_analyze>, not
    bare in the prompt body."""
    s = _mk_session("s1", turns=[_mk_turn("h", "a")])
    chunks = [{"session": s, "turn_offset": 0, "total_turns": 1}]
    out = _build_batch_prompt(chunks, existing_gaps="")
    open_idx = out.find("<archived_sessions_to_analyze>")
    close_idx = out.find("</archived_sessions_to_analyze>")
    inner_idx = out.find("<archived_session_log")
    assert open_idx != -1 and close_idx != -1
    assert open_idx < inner_idx < close_idx
