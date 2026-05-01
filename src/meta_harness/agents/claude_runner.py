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
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


class ClaudeRunnerError(Exception):
    """Raised when a claude -p invocation fails."""


def invoke_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-6",
    timeout: int = 300,
    label: Optional[str] = None,
) -> str:
    """
    Invoke claude -p as a subprocess and return the text result.

    Uses stream-json output format to show real-time progress on stderr
    while collecting the final result.

    Args:
        system_prompt: The system prompt for the agent.
        user_prompt: The user message to send.
        model: Model name (e.g. "claude-sonnet-4-6", "claude-opus-4-6").
        timeout: Subprocess timeout in seconds.
        label: Optional label for progress messages (e.g. "evaluator batch 1/3").

    Returns:
        The text content from Claude's response.

    Raises:
        ClaudeRunnerError: If the invocation fails.
    """
    # Build env without ANTHROPIC_API_KEY so OAuth is used
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    prefix = f"  [{label}]" if label else "  [claude]"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as sp_file:
        sp_file.write(system_prompt)
        sp_path = sp_file.name

    try:
        proc = subprocess.Popen(
            [
                "claude",
                "-p",
                "--output-format", "stream-json",
                "--verbose",
                "--model", model,
                "--system-prompt-file", sp_path,
                "--tools", "",
                "--no-session-persistence",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError as e:
        os.unlink(sp_path)
        raise ClaudeRunnerError(
            "claude CLI not found. Install Claude Code or ensure 'claude' is on PATH."
        ) from e

    # Send user prompt via stdin and close
    proc.stdin.write(user_prompt)
    proc.stdin.close()

    # Stream stdout line by line, parsing events for progress
    result_event = None
    start_time = time.monotonic()
    token_count = 0

    try:
        for line in proc.stdout:
            # Check timeout
            if time.monotonic() - start_time > timeout:
                proc.kill()
                raise ClaudeRunnerError(
                    f"Claude invocation timed out after {timeout}s"
                )

            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "assistant":
                # Extract token progress from usage
                msg = event.get("message", {})
                usage = msg.get("usage", {})
                output_tokens = usage.get("output_tokens", 0)
                if output_tokens > token_count:
                    token_count = output_tokens
                    elapsed = int(time.monotonic() - start_time)
                    print(
                        f"\r{prefix} {elapsed}s elapsed, "
                        f"{token_count} output tokens...",
                        end="", file=sys.stderr, flush=True,
                    )

            elif event_type == "result":
                result_event = event
                # Final newline after progress
                if token_count > 0:
                    elapsed = int(time.monotonic() - start_time)
                    print(
                        f"\r{prefix} done in {elapsed}s, "
                        f"{token_count} output tokens.   ",
                        file=sys.stderr, flush=True,
                    )

    finally:
        proc.stdout.close()
        proc.stderr.close()
        proc.wait()
        os.unlink(sp_path)

    if result_event is None:
        raise ClaudeRunnerError(
            f"claude -p produced no result event (exit code {proc.returncode})"
        )

    if result_event.get("is_error") or proc.returncode != 0:
        raise ClaudeRunnerError(
            f"Claude returned an error: {result_event.get('result', 'unknown error')}"
        )

    return result_event.get("result", "")
