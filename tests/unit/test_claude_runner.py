"""
Unit tests for the claude_runner subprocess helper.

All tests mock subprocess.run to avoid actually invoking the claude CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
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
