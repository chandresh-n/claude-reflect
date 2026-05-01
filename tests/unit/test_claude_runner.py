"""
Unit tests for the claude_runner subprocess helper.

All tests mock subprocess.run to avoid actually invoking the claude CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meta_harness.agents.claude_runner import ClaudeRunnerError, invoke_claude


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_invoke_claude_returns_text(mock_run: MagicMock) -> None:
    """Mocks subprocess to return valid JSON; asserts helper returns the result text."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"type": "result", "is_error": False, "result": "hello"}),
        stderr="",
    )
    result = invoke_claude(system_prompt="You are a helper.", user_prompt="Say hello")
    assert result == "hello"


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_env_strips_api_key(mock_run: MagicMock) -> None:
    """Asserts ANTHROPIC_API_KEY is NOT in the env dict passed to subprocess."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"type": "result", "is_error": False, "result": "ok"}),
        stderr="",
    )
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-secret-key"}, clear=False):
        invoke_claude(system_prompt="sys", user_prompt="usr")

    call_kwargs = mock_run.call_args
    env_passed = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
    assert env_passed is not None, "env kwarg should be passed to subprocess.run"
    assert "ANTHROPIC_API_KEY" not in env_passed


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_error_handling(mock_run: MagicMock) -> None:
    """Asserts ClaudeRunnerError is raised when is_error is true."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(
            {"type": "result", "is_error": True, "result": "Connection failed"}
        ),
        stderr="",
    )
    with pytest.raises(ClaudeRunnerError, match="Connection failed"):
        invoke_claude(system_prompt="sys", user_prompt="usr")


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_nonzero_exit_raises(mock_run: MagicMock) -> None:
    """Asserts ClaudeRunnerError is raised on CalledProcessError / non-zero exit."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="some error",
    )
    with pytest.raises(ClaudeRunnerError):
        invoke_claude(system_prompt="sys", user_prompt="usr")


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_system_prompt_written_to_tempfile(mock_run: MagicMock) -> None:
    """Asserts --system-prompt-file flag points to a file with the system prompt."""
    system_prompt_text = "You are an expert reviewer."

    def capture_call(*args, **kwargs):
        cmd = args[0]
        # Find the --system-prompt-file arg and read the file
        idx = cmd.index("--system-prompt-file")
        sp_path = cmd[idx + 1]
        with open(sp_path) as f:
            content = f.read()
        assert content == system_prompt_text, (
            f"System prompt file content mismatch: {content!r}"
        )
        return MagicMock(
            returncode=0,
            stdout=json.dumps(
                {"type": "result", "is_error": False, "result": "done"}
            ),
            stderr="",
        )

    mock_run.side_effect = capture_call
    invoke_claude(system_prompt=system_prompt_text, user_prompt="Review this")


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_model_passed_through(mock_run: MagicMock) -> None:
    """Asserts --model flag matches the passed model arg."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"type": "result", "is_error": False, "result": "ok"}),
        stderr="",
    )
    invoke_claude(
        system_prompt="sys", user_prompt="usr", model="claude-opus-4-6"
    )
    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# T4: Author uses claude_runner instead of direct Anthropic SDK
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.claude_runner.subprocess.run")
def test_author_uses_runner(mock_run: MagicMock) -> None:
    """Verify author() delegates to invoke_claude instead of anthropic SDK."""
    from pathlib import Path
    import tempfile

    from meta_harness.agents.author import author

    canned_author_json = json.dumps({
        "status": "success",
        "proposal_id": "prop-001",
        "files": [
            {
                "path": "skills/test-skill.md",
                "action": "create",
                "content": "# Test skill\nHello world.",
            }
        ],
    })

    # Mock subprocess.run (used by invoke_claude) to return canned JSON
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "type": "result",
            "is_error": False,
            "result": canned_author_json,
        }),
        stderr="",
    )

    intent = {
        "proposal_id": "prop-001",
        "title": "Test proposal",
        "why": {"prose_summary": "Testing author migration."},
        "authoring_addendum": {
            "purpose": "Create a test skill",
            "actions": [
                {"type": "create", "target_path": "skills/test-skill.md"}
            ],
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        result = author(intent, repo, commit_changes=False)

    assert result["status"] == "success"
    assert result["proposal_id"] == "prop-001"
    assert result["files_touched"] == ["skills/test-skill.md"]
    assert result["branch_name"] == "meta-harness/proposal/prop-001"
    assert result["diff_reference"] == "no-commit"

    # Verify invoke_claude was called (subprocess.run was called by it)
    assert mock_run.called, "subprocess.run should have been called via invoke_claude"
    cmd = mock_run.call_args[0][0]
    assert "claude" in cmd[0], "Should invoke 'claude' CLI, not anthropic SDK"


@patch("meta_harness.agents.claude_runner.invoke_claude")
def test_evaluator_uses_runner(mock_invoke: MagicMock) -> None:
    """Evaluator must call invoke_claude (not anthropic SDK) and return 4-key output."""
    import importlib
    import inspect
    from datetime import datetime, timezone

    from meta_harness.storage.session_logs import Session, Turn

    # Canned evaluator JSON that invoke_claude will return
    canned = json.dumps({
        "per_turn_observations": [
            {
                "session_id": "test-session-1",
                "turn_index": 0,
                "assessment": "User asked for help.",
                "effort_signal": {
                    "tokens_used": 500,
                    "model": "claude-sonnet-4-6",
                    "context_occupancy": 0.05,
                    "tool_calls": [],
                },
                "flags": [],
            }
        ],
        "pass_classifications": [
            {
                "session_id": "test-session-1",
                "turn_range": {"start": 0, "end": 0},
                "pass_type": "successful_one_shot",
                "harness_gap_rationale": "None needed.",
                "contributing_gaps": None,
            }
        ],
        "gap_observations": [],
        "session_narratives": [
            {
                "session_id": "test-session-1",
                "outcome": "successful_and_accepted",
                "pass_counts_by_type": {"successful_one_shot": 1},
                "gaps_observed": [],
                "narrative": "Single turn, successful.",
            }
        ],
    })
    mock_invoke.return_value = canned

    # Build a minimal session
    turn = Turn(
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        human_input="Hello",
        assistant_response="Hi there",
        tool_calls=[],
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=400,
    )
    import tempfile
    from pathlib import Path

    session = Session(
        session_id="test-session-1",
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc),
        file_path=Path("/tmp/fake-session.jsonl"),
        turns=[turn],
    )

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        from meta_harness.agents.evaluator import evaluate

        result = evaluate(
            sessions=[session],
            repo=repo,
            write_gap_records=False,
        )

    # Assert invoke_claude was called
    mock_invoke.assert_called_once()

    # Assert the result has the expected 4 keys
    expected_keys = {
        "per_turn_observations",
        "pass_classifications",
        "gap_observations",
        "session_narratives",
    }
    assert set(result.keys()) == expected_keys

    # Assert anthropic is NOT imported at runtime in evaluator module
    evaluator_mod = importlib.import_module("meta_harness.agents.evaluator")
    source = inspect.getsource(evaluator_mod)
    assert "import anthropic" not in source, (
        "evaluator.py must not import anthropic directly"
    )
