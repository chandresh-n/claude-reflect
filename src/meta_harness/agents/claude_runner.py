"""
Subprocess wrapper for invoking Claude Code CLI as a subagent.

Replaces direct Anthropic SDK calls with `claude -p` subprocess invocations,
enabling the meta-harness to run on a Claude Max subscription (OAuth)
without separate API billing.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


class ClaudeRunnerError(Exception):
    """Raised when a claude -p invocation fails."""


def invoke_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-6",
    timeout: int = 300,
) -> str:
    """
    Invoke claude -p as a subprocess and return the text result.

    Args:
        system_prompt: The system prompt for the agent.
        user_prompt: The user message to send.
        model: Model name (e.g. "claude-sonnet-4-6", "claude-opus-4-6").
        timeout: Subprocess timeout in seconds.

    Returns:
        The text content from Claude's response.

    Raises:
        ClaudeRunnerError: If the invocation fails.
    """
    # Build env without ANTHROPIC_API_KEY so OAuth is used
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as sp_file:
        sp_file.write(system_prompt)
        sp_path = sp_file.name

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--output-format", "json",
                "--model", model,
                "--system-prompt-file", sp_path,
                "--tools", "",
                "--no-session-persistence",
            ],
            input=user_prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeRunnerError(f"Claude invocation timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise ClaudeRunnerError(
            "claude CLI not found. Install Claude Code or ensure 'claude' is on PATH."
        ) from e
    finally:
        os.unlink(sp_path)

    if result.returncode != 0:
        raise ClaudeRunnerError(
            f"claude -p exited with code {result.returncode}: {result.stderr}"
        )

    # Parse the JSON envelope
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeRunnerError(
            f"Failed to parse claude output as JSON: {result.stdout[:500]}"
        ) from e

    if response.get("is_error"):
        raise ClaudeRunnerError(
            f"Claude returned an error: {response.get('result', 'unknown error')}"
        )

    return response.get("result", "")
