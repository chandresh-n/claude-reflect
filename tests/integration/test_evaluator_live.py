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
        _build_batch_prompt,
        SYSTEM_PROMPT,
    )

    session = _make_tiny_session()
    chunks = [{"session": session, "turn_offset": 0,
               "total_turns": len(session.turns)}]
    user_prompt = _build_batch_prompt(chunks, existing_gaps="")

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
        _build_batch_prompt,
        SYSTEM_PROMPT,
    )

    session = _make_tiny_session()
    chunks = [{"session": session, "turn_offset": 0,
               "total_turns": len(session.turns)}]
    user_prompt = _build_batch_prompt(chunks, existing_gaps="")

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


# ---------------------------------------------------------------------------
# Test: real session from disk (not mocked)
# ---------------------------------------------------------------------------

_REAL_SESSION_DIR = Path.home() / ".claude" / "projects" / "-Users-chandresh-Documents-Slop-meta-harness"


def _find_real_session(min_turns: int = 2, max_turns: int = 20):
    """Find a real session file with a manageable number of turns."""
    from meta_harness.storage.session_logs import SessionLogReader
    from datetime import date, timedelta

    if not _REAL_SESSION_DIR.exists():
        pytest.skip(f"Session directory not found: {_REAL_SESSION_DIR}")

    reader = SessionLogReader(_REAL_SESSION_DIR)
    end = date.today()
    start = end - timedelta(days=7)
    sessions = reader.sessions_in_range(start, end)

    # Find sessions with a reasonable number of turns
    candidates = [s for s in sessions if min_turns <= len(s.turns) <= max_turns]
    if not candidates:
        pytest.skip(f"No sessions found with {min_turns}-{max_turns} turns")

    return candidates[0]


def _find_big_session(min_turns: int = 100):
    """Find the biggest real session to test limits."""
    from meta_harness.storage.session_logs import SessionLogReader
    from datetime import date, timedelta

    if not _REAL_SESSION_DIR.exists():
        pytest.skip(f"Session directory not found: {_REAL_SESSION_DIR}")

    reader = SessionLogReader(_REAL_SESSION_DIR)
    end = date.today()
    start = end - timedelta(days=7)
    sessions = reader.sessions_in_range(start, end)

    candidates = [s for s in sessions if len(s.turns) >= min_turns]
    if not candidates:
        pytest.skip(f"No sessions found with {min_turns}+ turns")

    return max(candidates, key=lambda s: len(s.turns))


def test_evaluate_real_small_session():
    """Run evaluate() on a real session with few turns (2-20).

    This tests with ACTUAL session data, not mock fixtures.
    """
    from meta_harness.agents.evaluator import (
        evaluate, EvaluatorError, _format_sessions_for_prompt, SYSTEM_PROMPT,
    )
    from meta_harness.agents.claude_runner import _compute_timeout

    session = _find_real_session(min_turns=2, max_turns=20)
    text = _format_sessions_for_prompt([session])

    print(f"\n=== TEST: real small session ===", file=sys.stderr)
    print(f"Session: {session.session_id}", file=sys.stderr)
    print(f"Turns: {len(session.turns)}", file=sys.stderr)
    print(f"Prompt chars: {len(text):,}", file=sys.stderr)
    print(f"Estimated tokens: ~{len(text) // 4:,}", file=sys.stderr)

    user_prompt = f"Evaluate...\n\n{text}"
    timeout = _compute_timeout(SYSTEM_PROMPT, user_prompt)
    print(f"Computed timeout: {timeout}s ({timeout // 60}m)", file=sys.stderr)

    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = evaluate(
                sessions=[session],
                repo=Path(tmpdir),
                model="claude-sonnet-4-6",
                write_gap_records=False,
            )
            elapsed = time.monotonic() - start
            print(f"\nSUCCESS in {elapsed:.1f}s", file=sys.stderr)
            print(f"per_turn_observations: {len(result['per_turn_observations'])}", file=sys.stderr)
            print(f"pass_classifications: {len(result['pass_classifications'])}", file=sys.stderr)
            print(f"gap_observations: {len(result['gap_observations'])}", file=sys.stderr)
            print(f"session_narratives: {len(result['session_narratives'])}", file=sys.stderr)

            assert len(result["per_turn_observations"]) == len(session.turns)
            assert len(result["session_narratives"]) == 1

        except EvaluatorError as e:
            elapsed = time.monotonic() - start
            print(f"\nFAILED ({elapsed:.1f}s): {e}", file=sys.stderr)
            pytest.fail(f"evaluate() failed: {e}")


def test_diagnose_big_session():
    """Diagnose WHY big sessions fail — is it prompt size, output size, or timeout?

    This test does NOT call the evaluator. It just measures the problem.
    """
    from meta_harness.agents.evaluator import (
        _format_sessions_for_prompt, SYSTEM_PROMPT, _split_into_batches,
    )
    from meta_harness.agents.claude_runner import _compute_timeout

    session = _find_big_session()
    text = _format_sessions_for_prompt([session])

    print(f"\n=== DIAGNOSIS: big session ===", file=sys.stderr)
    print(f"Session: {session.session_id}", file=sys.stderr)
    print(f"Turns: {len(session.turns)}", file=sys.stderr)
    print(f"Prompt chars: {len(text):,}", file=sys.stderr)
    print(f"Estimated input tokens: ~{len(text) // 4:,}", file=sys.stderr)

    # Sonnet context: 200K tokens, max output: 64K tokens (but realistically 16K-32K)
    input_tokens = len(text) // 4
    system_tokens = len(SYSTEM_PROMPT) // 4
    total_input = input_tokens + system_tokens
    remaining_for_output = 200_000 - total_input

    print(f"\nContext budget (Sonnet 200K):", file=sys.stderr)
    print(f"  System prompt: ~{system_tokens:,} tokens", file=sys.stderr)
    print(f"  Session text:  ~{input_tokens:,} tokens", file=sys.stderr)
    print(f"  Total input:   ~{total_input:,} tokens", file=sys.stderr)
    print(f"  Remaining:     ~{remaining_for_output:,} tokens for output", file=sys.stderr)

    # Expected output size
    obs_per_turn = 400  # chars per per_turn_observation
    expected_output_chars = len(session.turns) * obs_per_turn + 5000  # + overhead
    expected_output_tokens = expected_output_chars // 4
    print(f"\nExpected output:", file=sys.stderr)
    print(f"  {len(session.turns)} turns * ~{obs_per_turn} chars = ~{expected_output_chars:,} chars", file=sys.stderr)
    print(f"  Estimated output tokens: ~{expected_output_tokens:,}", file=sys.stderr)

    fits = expected_output_tokens < remaining_for_output
    print(f"\n  Output fits in remaining context? {'YES' if fits else 'NO'}", file=sys.stderr)
    if not fits:
        print(f"  OVERFLOW by ~{expected_output_tokens - remaining_for_output:,} tokens", file=sys.stderr)

    # Batching check
    batches = _split_into_batches([session])
    print(f"\nBatching:", file=sys.stderr)
    print(f"  _split_into_batches produces {len(batches)} batch(es)", file=sys.stderr)
    print(f"  Batch limit: 400,000 chars", file=sys.stderr)
    print(f"  Session size: {len(text):,} chars", file=sys.stderr)
    if len(text) < 400_000:
        print(f"  -> Session fits in ONE batch (not split)", file=sys.stderr)
        print(f"  -> But this is a SINGLE session — can't split across batches anyway", file=sys.stderr)

    # Timeout
    user_prompt = f"Evaluate...\n\n{text}"
    timeout = _compute_timeout(SYSTEM_PROMPT, user_prompt)
    print(f"\nTimeout: {timeout}s ({timeout // 60}m {timeout % 60}s)", file=sys.stderr)

    # Time estimate: ~1 token/s for output generation
    est_time = expected_output_tokens  # ~1 tok/s
    print(f"Estimated generation time at 1 tok/s: {est_time}s ({est_time // 60}m)", file=sys.stderr)
    if est_time > timeout:
        print(f"  -> WILL TIMEOUT: generation ({est_time}s) > timeout ({timeout}s)", file=sys.stderr)

    # Per-turn size analysis
    turn_sizes = []
    for turn in session.turns:
        h = len(turn.human_input or "")
        a = len(turn.assistant_response or "")
        turn_sizes.append(h + a)

    print(f"\nPer-turn sizes:", file=sys.stderr)
    print(f"  Min: {min(turn_sizes):,} chars", file=sys.stderr)
    print(f"  Max: {max(turn_sizes):,} chars", file=sys.stderr)
    print(f"  Avg: {sum(turn_sizes) // len(turn_sizes):,} chars", file=sys.stderr)
    print(f"  Median: {sorted(turn_sizes)[len(turn_sizes)//2]:,} chars", file=sys.stderr)

    # Suggested fix
    print(f"\n=== SUGGESTED FIX ===", file=sys.stderr)
    print(f"Truncate assistant_response per turn to ~500 chars.", file=sys.stderr)
    truncated = 0
    for turn in session.turns:
        h = len(turn.human_input or "")
        a = min(len(turn.assistant_response or ""), 500)
        truncated += h + a + 100
    print(f"Truncated prompt would be ~{truncated:,} chars (~{truncated // 4:,} tokens)", file=sys.stderr)
    print(f"Reduction: {len(text):,} -> {truncated:,} ({100 - truncated * 100 // len(text)}% smaller)", file=sys.stderr)
