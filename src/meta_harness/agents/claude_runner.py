"""
Subprocess wrapper for invoking Claude Code CLI as a subagent.

Replaces direct Anthropic SDK calls with `claude -p` subprocess invocations,
enabling the meta-harness to run on a Claude Max subscription (OAuth)
without separate API billing.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


class ClaudeRunnerError(Exception):
    """Raised when a claude -p invocation fails."""


# Timeout scales with prompt size.  Large evaluator prompts (300K+ chars,
# ~75K tokens) need significant processing time before the first output
# token arrives.  Rule of thumb: ~1 second per 1000 chars of input, with
# a generous floor of 10 minutes.
_MIN_TIMEOUT = 600  # 10 minutes
_CHARS_PER_SECOND = 1000


def _compute_timeout(system_prompt: str, user_prompt: str) -> int:
    """Compute a reasonable timeout based on total prompt size."""
    total_chars = len(system_prompt) + len(user_prompt)
    estimated = total_chars // _CHARS_PER_SECOND
    return max(_MIN_TIMEOUT, estimated)


def invoke_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-6",
    timeout: Optional[int] = None,
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
        timeout: Subprocess timeout in seconds. If None, computed from
                 prompt size (minimum 10 minutes).
        label: Optional label for progress messages (e.g. "evaluator batch 1/3").

    Returns:
        The text content from Claude's response.

    Raises:
        ClaudeRunnerError: If the invocation fails.
    """
    if timeout is None:
        timeout = _compute_timeout(system_prompt, user_prompt)

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

    # Stream stdout line by line, parsing events for progress.
    # Use select() for non-blocking reads so timeout fires even when
    # the model is processing input tokens and no output is streaming.
    result_event = None
    start_time = time.monotonic()
    token_count = 0
    buf = ""
    last_progress_time = start_time

    try:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                proc.kill()
                raise ClaudeRunnerError(
                    f"Claude invocation timed out after {int(elapsed)}s"
                )

            # Print a waiting indicator every 30s if no tokens yet
            if token_count == 0 and time.monotonic() - last_progress_time > 30:
                last_progress_time = time.monotonic()
                print(
                    f"\r{prefix} {int(elapsed)}s elapsed, waiting for response...",
                    end="", file=sys.stderr, flush=True,
                )

            # Non-blocking read with 5s poll interval
            ready, _, _ = select.select([proc.stdout], [], [], 5.0)
            if not ready:
                # Check if process has exited
                if proc.poll() is not None:
                    break
                continue

            chunk = proc.stdout.read(8192)
            if not chunk:
                break  # EOF

            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                if event_type == "system":
                    # Init event — show model and session info
                    evt_model = event.get("model", "")
                    session_id = event.get("session_id", "")
                    if evt_model:
                        print(
                            f"{prefix} model={evt_model}, "
                            f"session={session_id[:12]}...",
                            file=sys.stderr, flush=True,
                        )

                elif event_type == "assistant":
                    msg = event.get("message", {})
                    usage = msg.get("usage", {})
                    output_tokens = usage.get("output_tokens", 0)
                    input_tokens = usage.get("input_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)

                    # Show token progress
                    if output_tokens > token_count:
                        token_count = output_tokens
                        if input_tokens and token_count <= 1:
                            # First output — show input token breakdown
                            print(
                                f"\r{prefix} input={input_tokens:,} "
                                f"(cache_read={cache_read:,}, "
                                f"cache_create={cache_create:,}), "
                                f"generating...",
                                end="", file=sys.stderr, flush=True,
                            )
                        else:
                            print(
                                f"\r{prefix} {int(elapsed)}s, "
                                f"{token_count:,} output tokens...",
                                end="", file=sys.stderr, flush=True,
                            )

                    # Stream text content to stderr
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    text_content = block.get("text", "")
                                    if text_content:
                                        # Clear the progress line, print text, restore
                                        print(
                                            f"\r{' ' * 80}\r",
                                            end="", file=sys.stderr, flush=True,
                                        )
                                        sys.stderr.write(text_content)
                                        sys.stderr.flush()

                elif event_type == "result":
                    result_event = event
                    result_usage = result_event.get("usage", {})
                    total_input = result_usage.get("input_tokens", 0)
                    total_output = result_usage.get("output_tokens", 0)
                    cost = result_event.get("total_cost_usd", 0)
                    print(
                        f"\n{prefix} done in {int(elapsed)}s | "
                        f"in={total_input:,} out={total_output:,} "
                        f"cost=${cost:.4f}",
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
