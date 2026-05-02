"""
Live integration test for the evaluator agent.

This test calls the REAL claude -p subprocess (no mocks) with a tiny
single-session fixture. It validates the full pipeline:
  claude_runner.invoke_claude -> evaluator._parse_evaluator_output -> validate

Run with: pytest tests/integration/test_evaluator_live.py -v -s
The -s flag is critical to see all logging output.

Requires: claude CLI installed, authenticated via OAuth (Max plan).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from meta_harness.storage.session_logs import Session, Turn, ToolCall


# ---------------------------------------------------------------------------
# Fixture: a single tiny session with 3 turns
# ---------------------------------------------------------------------------

def _make_tiny_session() -> Session:
    """Create a minimal session that should comfortably fit in Sonnet's context."""
    turns = [
        Turn(
            timestamp=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            human_input="Create a hello.py file that prints hello world",
            assistant_response="I'll create that file for you.",
            tool_calls=[ToolCall(name="Write", input={"path": "hello.py"})],
            model="claude-sonnet-4-6",
            input_tokens=500,
            output_tokens=200,
        ),
        Turn(
            timestamp=datetime(2026, 5, 1, 10, 1, tzinfo=timezone.utc),
            human_input="Actually make it print hello universe instead",
            assistant_response="I'll update the file to print hello universe.",
            tool_calls=[ToolCall(name="Edit", input={"path": "hello.py"})],
            model="claude-sonnet-4-6",
            input_tokens=800,
            output_tokens=250,
        ),
        Turn(
            timestamp=datetime(2026, 5, 1, 10, 2, tzinfo=timezone.utc),
            human_input="Perfect, thanks!",
            assistant_response="You're welcome! The file is ready.",
            tool_calls=[],
            model="claude-sonnet-4-6",
            input_tokens=900,
            output_tokens=100,
        ),
    ]
    return Session(
        session_id="test-live-session-001",
        start_time=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 1, 10, 2, tzinfo=timezone.utc),
        file_path=Path("/tmp/test-live-session.jsonl"),
        turns=turns,
    )


# ---------------------------------------------------------------------------
# Test: invoke_claude directly with the evaluator system prompt
# ---------------------------------------------------------------------------

def test_invoke_claude_directly():
    """Test invoke_claude with a simple prompt to verify basic connectivity."""
    from meta_harness.agents.claude_runner import invoke_claude, ClaudeRunnerError

    print("\n=== TEST: invoke_claude directly ===", file=sys.stderr)
    print(f"ANTHROPIC_API_KEY in env: {'ANTHROPIC_API_KEY' in os.environ}", file=sys.stderr)
    if "ANTHROPIC_API_KEY" in os.environ:
        val = os.environ["ANTHROPIC_API_KEY"]
        print(f"ANTHROPIC_API_KEY value prefix: {val[:20]}...", file=sys.stderr)

    start = time.monotonic()
    try:
        result = invoke_claude(
            system_prompt="You are a test bot. Respond with exactly: OK",
            user_prompt="Say OK",
            model="claude-sonnet-4-6",
            timeout=120,
            label="connectivity-test",
        )
        elapsed = time.monotonic() - start
        print(f"Result ({elapsed:.1f}s): {result!r}", file=sys.stderr)
        assert result is not None
        assert len(result) > 0
    except ClaudeRunnerError as e:
        elapsed = time.monotonic() - start
        print(f"FAILED ({elapsed:.1f}s): {e}", file=sys.stderr)
        pytest.fail(f"invoke_claude failed: {e}")


# ---------------------------------------------------------------------------
# Test: format a session and show the prompt size
# ---------------------------------------------------------------------------

def test_session_prompt_size():
    """Show how large the formatted prompt is for our tiny session."""
    from meta_harness.agents.evaluator import (
        _format_sessions_for_prompt,
        SYSTEM_PROMPT,
    )

    session = _make_tiny_session()
    session_text = _format_sessions_for_prompt([session])
    user_prompt = (
        f"Evaluate the following session logs. Produce a complete evaluator "
        f"output JSON document covering all sessions and all turns.\n\n"
        f"## Session logs to evaluate\n\n{session_text}"
    )

    print(f"\n=== PROMPT SIZE ===", file=sys.stderr)
    print(f"System prompt: {len(SYSTEM_PROMPT)} chars", file=sys.stderr)
    print(f"User prompt: {len(user_prompt)} chars", file=sys.stderr)
    print(f"Total: {len(SYSTEM_PROMPT) + len(user_prompt)} chars", file=sys.stderr)
    print(f"Estimated tokens: ~{(len(SYSTEM_PROMPT) + len(user_prompt)) // 4}", file=sys.stderr)
    print(f"\n--- User prompt content ---", file=sys.stderr)
    print(user_prompt, file=sys.stderr)
    print(f"--- End user prompt ---\n", file=sys.stderr)

    # Should be well under 10K chars for this tiny session
    assert len(user_prompt) < 10_000, f"Prompt too large: {len(user_prompt)} chars"


# ---------------------------------------------------------------------------
# Test: invoke_claude with the evaluator system prompt and tiny session
# ---------------------------------------------------------------------------

def test_evaluator_raw_invocation():
    """Call invoke_claude with the real evaluator system prompt and tiny session.

    This tests the raw LLM call without any parsing, to see exactly what
    the model returns.
    """
    from meta_harness.agents.claude_runner import invoke_claude, ClaudeRunnerError
    from meta_harness.agents.evaluator import (
        _format_sessions_for_prompt,
        SYSTEM_PROMPT,
    )

    session = _make_tiny_session()
    session_text = _format_sessions_for_prompt([session])
    user_prompt = (
        f"Evaluate the following session logs. Produce a complete evaluator "
        f"output JSON document covering all sessions and all turns.\n\n"
        f"## Session logs to evaluate\n\n{session_text}"
    )

    print(f"\n=== TEST: evaluator raw invocation ===", file=sys.stderr)
    start = time.monotonic()

    try:
        raw_text = invoke_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model="claude-sonnet-4-6",
            timeout=300,
            label="evaluator-live-test",
        )
        elapsed = time.monotonic() - start
        print(f"\nRaw response ({elapsed:.1f}s, {len(raw_text)} chars):", file=sys.stderr)
        print(raw_text[:2000], file=sys.stderr)
        if len(raw_text) > 2000:
            print(f"... ({len(raw_text) - 2000} more chars)", file=sys.stderr)

        # Try to parse as JSON
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            parsed = json.loads(text)
            print(f"\nParsed JSON keys: {list(parsed.keys())}", file=sys.stderr)
            print(f"per_turn_observations count: {len(parsed.get('per_turn_observations', []))}", file=sys.stderr)
            print(f"pass_classifications count: {len(parsed.get('pass_classifications', []))}", file=sys.stderr)
            print(f"gap_observations count: {len(parsed.get('gap_observations', []))}", file=sys.stderr)
            print(f"session_narratives count: {len(parsed.get('session_narratives', []))}", file=sys.stderr)
        except json.JSONDecodeError as e:
            print(f"\nFailed to parse as JSON: {e}", file=sys.stderr)
            print(f"First 500 chars: {text[:500]!r}", file=sys.stderr)

    except ClaudeRunnerError as e:
        elapsed = time.monotonic() - start
        print(f"\nFAILED ({elapsed:.1f}s): {e}", file=sys.stderr)
        pytest.fail(f"invoke_claude failed: {e}")


# ---------------------------------------------------------------------------
# Test: full evaluate() pipeline with tiny session
# ---------------------------------------------------------------------------

def test_evaluate_full_pipeline():
    """Run the full evaluate() function with a tiny session.

    This is the end-to-end test: session -> evaluate() -> validated output.
    """
    from meta_harness.agents.evaluator import evaluate, EvaluatorError

    session = _make_tiny_session()

    print(f"\n=== TEST: full evaluate() pipeline ===", file=sys.stderr)
    start = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        try:
            result = evaluate(
                sessions=[session],
                repo=repo,
                model="claude-sonnet-4-6",
                write_gap_records=False,
            )
            elapsed = time.monotonic() - start
            print(f"\nevaluate() succeeded in {elapsed:.1f}s", file=sys.stderr)
            print(f"Result keys: {list(result.keys())}", file=sys.stderr)

            # Validate structure
            assert "per_turn_observations" in result
            assert "pass_classifications" in result
            assert "gap_observations" in result
            assert "session_narratives" in result

            # Validate content
            obs = result["per_turn_observations"]
            print(f"per_turn_observations: {len(obs)} items", file=sys.stderr)
            assert len(obs) == 3, f"Expected 3 observations (one per turn), got {len(obs)}"

            for i, o in enumerate(obs):
                print(f"  turn {i}: session_id={o.get('session_id')}, "
                      f"turn_index={o.get('turn_index')}", file=sys.stderr)
                assert o.get("session_id") == "test-live-session-001"
                assert o.get("turn_index") == i

            classifications = result["pass_classifications"]
            print(f"pass_classifications: {len(classifications)} items", file=sys.stderr)
            assert len(classifications) >= 1

            narratives = result["session_narratives"]
            print(f"session_narratives: {len(narratives)} items", file=sys.stderr)
            assert len(narratives) == 1
            assert narratives[0].get("session_id") == "test-live-session-001"

            print(f"\nFull result:\n{json.dumps(result, indent=2)}", file=sys.stderr)

        except EvaluatorError as e:
            elapsed = time.monotonic() - start
            print(f"\nEvaluatorError ({elapsed:.1f}s): {e}", file=sys.stderr)
            pytest.fail(f"evaluate() failed: {e}")
