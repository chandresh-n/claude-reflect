"""
Subprocess wrapper for invoking Claude Code CLI as a subagent.

Replaces direct Anthropic SDK calls with `claude -p` subprocess invocations,
enabling the claude-reflect to run on a Claude Max subscription (OAuth)
without separate API billing.

Includes:
- Automatic retry with exponential backoff on transient API errors
  (overloaded_error, rate_limit, 5xx, etc.).
- A 5-line rolling tail of the model's streamed output plus a one-line
  status (turns observed / output tokens / elapsed) — gives the operator
  a sense of what the model is saying without flooding the terminal.
- Optional ``log_dir`` to tee the raw stream-json from the CLI to
  ``<log_dir>/stream.jsonl`` for after-the-fact RCA.
"""
from __future__ import annotations

import collections
import json
import os
import random
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, List, Optional


class ClaudeRunnerError(Exception):
    """Raised when a claude -p invocation fails (non-retryable)."""


class _RetryableAPIError(Exception):
    """Internal: API returned a transient error worth retrying."""


# Timeout scales with prompt size.  Large evaluator prompts need significant
# processing time before the first output token arrives.  Rule of thumb:
# ~1 second per 1000 chars of input, with a generous floor of 10 minutes.
_MIN_TIMEOUT = 600  # 10 minutes
_CHARS_PER_SECOND = 1000

# Tail panel: how many recent output lines stay visible during streaming.
_TAIL_LINES = 5
# Tail panel = 5 tail lines + 1 status line = 6 redrawable rows.
_PANEL_HEIGHT = _TAIL_LINES + 1

# Substrings in an error message that signal a transient failure.
_RETRYABLE_MARKERS = (
    # Server-side overload / rate-limit / capacity
    "overloaded",
    "rate_limit",
    "rate-limit",
    "rate limit",
    "429",
    "503",
    "529",
    "service_unavailable",
    "service unavailable",
    "internal_server_error",
    "internal server error",
    # Gateway / network plane
    "bad gateway",
    "gateway timeout",
    "504",
    # Transport-level: cli ↔ API connectivity that drops mid-stream.
    # Conservative on purpose — only retry on phrasings that imply the
    # request was interrupted, not refused for an authoritative reason.
    "socket",
    "connection closed",
    "connection was closed",
    "connection reset",
    "econnreset",
    "etimedout",
    "fetch failed",
)


def _is_retryable_error(message: str) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return any(m in lowered for m in _RETRYABLE_MARKERS)


def _backoff_seconds(attempt: int) -> int:
    """Exponential backoff with jitter: ~30, 60, 120, 240s (cap 300)."""
    base = min(30 * (2 ** attempt), 300)
    jitter = random.randint(0, max(1, base // 4))
    return base + jitter


def _compute_timeout(system_prompt: str, user_prompt: str) -> int:
    total_chars = len(system_prompt) + len(user_prompt)
    estimated = total_chars // _CHARS_PER_SECOND
    return max(_MIN_TIMEOUT, estimated)


def _is_tty_stderr() -> bool:
    """True if stderr is a real TTY supporting cursor escape sequences."""
    try:
        if not sys.stderr.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return True


def invoke_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-6",
    timeout: Optional[int] = None,
    label: Optional[str] = None,
    progress_total: Optional[int] = None,
    progress_pattern: Optional[str] = None,
    progress_unit: str = "items",
    max_retries: int = 4,
    log_dir: Optional[Path] = None,
) -> str:
    """
    Invoke claude -p as a subprocess and return the result text.

    Retries automatically on transient API errors with exponential backoff.

    Args:
        system_prompt: System prompt for the agent.
        user_prompt: User message sent on stdin.
        model: Model name (e.g. "claude-opus-4-6").
        timeout: Per-attempt subprocess timeout in seconds.  Defaults
                 to a value scaled by prompt size (>= 10 minutes).
        label: Short label for progress messages (e.g. "evaluator batch 3/14").
        progress_total: If set with progress_pattern, drives a progress
                        counter of pattern matches in streamed text.
        progress_pattern: Regex counted in streamed assistant text.
        progress_unit: Unit name for the progress counter (e.g. "turns").
        max_retries: Number of retries on transient errors.
        log_dir: If set, append raw stream-json events from the CLI to
                 ``<log_dir>/stream.jsonl`` for after-the-fact RCA.
                 All retry attempts append to the same file with
                 ``_meta`` marker lines between them.

    Returns:
        The text content from Claude's response.

    Raises:
        ClaudeRunnerError: If the invocation fails after all retries,
        or fails with a non-retryable error.
    """
    last_error: Optional[str] = None
    base_prefix = f"  [{label}]" if label else "  [claude]"

    for attempt in range(max_retries + 1):
        try:
            return _invoke_claude_once(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                timeout=timeout,
                label=label,
                progress_total=progress_total,
                progress_pattern=progress_pattern,
                progress_unit=progress_unit,
                attempt=attempt,
                log_dir=log_dir,
            )
        except _RetryableAPIError as e:
            last_error = str(e)
            if attempt >= max_retries:
                break
            wait = _backoff_seconds(attempt)
            print(
                f"\n{base_prefix} transient error "
                f"(attempt {attempt + 1}/{max_retries + 1}): {last_error}. "
                f"Retrying in {wait}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait)

    raise ClaudeRunnerError(
        f"Claude invocation failed after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )


def _invoke_claude_once(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    timeout: Optional[int],
    label: Optional[str],
    progress_total: Optional[int],
    progress_pattern: Optional[str],
    progress_unit: str,
    attempt: int,
    log_dir: Optional[Path],
) -> str:
    """Single subprocess attempt.

    Raises _RetryableAPIError on transient API errors so the wrapper can
    retry; ClaudeRunnerError on hard failures.
    """
    if timeout is None:
        timeout = _compute_timeout(system_prompt, user_prompt)

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    base_prefix = f"  [{label}]" if label else "  [claude]"
    prefix = f"{base_prefix} (retry {attempt})" if attempt > 0 else base_prefix

    pattern_re = re.compile(progress_pattern) if progress_pattern else None
    tty = _is_tty_stderr()

    # stream.jsonl for after-the-fact RCA.  All attempts append.
    stream_f = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stream_path = log_dir / "stream.jsonl"
        stream_f = stream_path.open("a", encoding="utf-8")
        stream_f.write(json.dumps({
            "_meta": "attempt_start",
            "attempt": attempt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "label": label,
        }) + "\n")
        stream_f.flush()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as sp_file:
        sp_file.write(system_prompt)
        sp_path = sp_file.name

    # Run from a clean cwd (system tempdir) so `claude -p` does NOT
    # auto-discover the claude-reflect repo's CLAUDE.md and inject its
    # text into the agent's system prompt.  Combined with
    # --strict-mcp-config (no MCP servers) and --disable-slash-commands
    # (no skills/slash commands), this keeps the model's context limited
    # to what the caller explicitly provided.  Without these, an
    # evaluator/proposer/author subprocess inherits the user's full MCP
    # toolbox (Gmail/Calendar/Drive etc.) plus the project's CLAUDE.md,
    # and can be tricked into acting as an agent on the session content
    # it was asked to analyze.
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
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--no-session-persistence",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=tempfile.gettempdir(),
        )
    except FileNotFoundError as e:
        os.unlink(sp_path)
        if stream_f:
            stream_f.close()
        raise ClaudeRunnerError(
            "claude CLI not found. Install Claude Code or ensure 'claude' is on PATH."
        ) from e

    proc.stdin.write(user_prompt)
    proc.stdin.close()

    # --- Streaming state ------------------------------------------------
    result_event: Optional[dict] = None
    start_time = time.monotonic()
    token_count = 0
    items_seen = 0
    accumulated_text = ""
    buf = ""

    # Tail panel: rolling window of recent complete output lines.
    tail_lines: Deque[str] = collections.deque(maxlen=_TAIL_LINES)
    partial_line = ""  # text accumulated since the last newline
    panel_drawn = False
    last_render = 0.0

    def _status_line() -> str:
        elapsed = int(time.monotonic() - start_time)
        if pattern_re and progress_total:
            return (
                f"{prefix} progress: {items_seen}/{progress_total} "
                f"{progress_unit} | {token_count:,} tok | {elapsed}s"
            )
        return f"{prefix} {token_count:,} tok | {elapsed}s"

    def _redraw_panel() -> None:
        """Repaint the 5-line tail + status in place (TTY only)."""
        nonlocal panel_drawn, last_render
        width = shutil.get_terminal_size((100, 24)).columns
        prefix_len = len(prefix) + 1
        max_w = max(20, width - prefix_len - 1)

        # Show the deque, plus the current partial as the bottom line so
        # a long line in flight is still visible.
        lines: List[str] = list(tail_lines)
        if partial_line:
            lines.append(partial_line)
        if len(lines) > _TAIL_LINES:
            lines = lines[-_TAIL_LINES:]
        while len(lines) < _TAIL_LINES:
            lines.insert(0, "")

        out_parts: List[str] = []
        if panel_drawn:
            out_parts.append(f"\x1b[{_PANEL_HEIGHT}A")  # cursor to panel top
        for line in lines:
            displayed = line[:max_w]
            out_parts.append(f"\r\x1b[2K{prefix} {displayed}\n")
        out_parts.append(f"\r\x1b[2K{_status_line()[:width]}\n")
        sys.stderr.write("".join(out_parts))
        sys.stderr.flush()
        panel_drawn = True
        last_render = time.monotonic()

    def _emit_plain(new_lines: List[str]) -> None:
        """Non-TTY fallback: print each complete output line on its own row."""
        for line in new_lines:
            sys.stderr.write(f"{prefix} {line}\n")
        sys.stderr.flush()

    def _maybe_render() -> None:
        if tty:
            now = time.monotonic()
            if now - last_render < 0.2:
                return
            _redraw_panel()

    def _ingest_text(text: str) -> List[str]:
        """Update the rolling window with new model output text.  Returns
        the list of complete lines newly seen (for plain-mode emission)."""
        nonlocal partial_line
        partial_line += text
        new_lines: List[str] = []
        while "\n" in partial_line:
            line, partial_line = partial_line.split("\n", 1)
            tail_lines.append(line)
            new_lines.append(line)
        return new_lines

    last_plain_status = start_time

    try:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                proc.kill()
                if panel_drawn and tty:
                    # leave the panel in place; just print error below
                    pass
                raise ClaudeRunnerError(
                    f"Claude invocation timed out after {int(elapsed)}s"
                )

            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                if proc.poll() is not None:
                    break
                # Periodic tick so the status line keeps moving.
                if tty:
                    _maybe_render()
                else:
                    now = time.monotonic()
                    if now - last_plain_status > 10.0:
                        last_plain_status = now
                        sys.stderr.write(_status_line() + "\n")
                        sys.stderr.flush()
                continue

            chunk = proc.stdout.read(8192)
            if not chunk:
                break  # EOF

            buf += chunk
            while "\n" in buf:
                raw_line, buf = buf.split("\n", 1)
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                # Tee every event to stream.jsonl before parsing.
                if stream_f is not None:
                    stream_f.write(raw_line + "\n")
                    stream_f.flush()

                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                if event_type == "system":
                    evt_model = event.get("model", "")
                    session_id = event.get("session_id", "")
                    if evt_model:
                        sys.stderr.write(
                            f"{prefix} model={evt_model}, "
                            f"session={session_id[:12]}...\n"
                        )
                        sys.stderr.flush()
                        # Seed an empty panel right below the system line so
                        # later in-place updates have a target to redraw.
                        if tty:
                            _redraw_panel()

                elif event_type == "assistant":
                    msg = event.get("message", {})
                    usage = msg.get("usage", {})
                    output_tokens = usage.get("output_tokens", 0)
                    if output_tokens > token_count:
                        token_count = output_tokens

                    new_complete_lines: List[str] = []
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if (
                                isinstance(block, dict)
                                and block.get("type") == "text"
                            ):
                                text = block.get("text", "")
                                accumulated_text += text
                                new_complete_lines.extend(_ingest_text(text))

                    if pattern_re:
                        items_seen = len(pattern_re.findall(accumulated_text))

                    if tty:
                        _maybe_render()
                    elif new_complete_lines:
                        _emit_plain(new_complete_lines)

                elif event_type == "result":
                    result_event = event
                    # Flush any trailing partial line into the tail window
                    # so the operator can see the final bytes the model
                    # produced (often the closing brace of the JSON).
                    if partial_line:
                        tail_lines.append(partial_line)
                        partial_line = ""
                        if not tty:
                            _emit_plain([tail_lines[-1]])
                    if tty:
                        _redraw_panel()
                    result_usage = result_event.get("usage", {})
                    total_input = result_usage.get("input_tokens", 0)
                    total_output = result_usage.get("output_tokens", 0)
                    cost = result_event.get("total_cost_usd", 0)
                    final_elapsed = int(time.monotonic() - start_time)
                    sys.stderr.write(
                        f"{prefix} done in {final_elapsed}s | "
                        f"in={total_input:,} out={total_output:,} "
                        f"cost=${cost:.4f}\n"
                    )
                    sys.stderr.flush()

    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.stderr.close()
        except Exception:
            pass
        proc.wait()
        try:
            os.unlink(sp_path)
        except OSError:
            pass

        # Trailing _meta marker so the log is self-describing per attempt.
        if stream_f is not None:
            outcome = "ok"
            err_msg: Optional[str] = None
            if result_event is None:
                outcome = "no_result_event"
            elif result_event.get("is_error"):
                err_msg = str(result_event.get("result", ""))
                outcome = (
                    "retryable_error"
                    if _is_retryable_error(err_msg) else "error"
                )
            stream_f.write(json.dumps({
                "_meta": "attempt_end",
                "attempt": attempt,
                "outcome": outcome,
                "error": err_msg,
                "duration_s": int(time.monotonic() - start_time),
                "output_tokens": token_count,
            }) + "\n")
            stream_f.flush()
            stream_f.close()

    if result_event is None:
        # No result event from the CLI: a hard failure (subprocess died,
        # CLI crashed, etc.).  Don't retry — symptom is unlikely transient.
        raise ClaudeRunnerError(
            f"claude -p produced no result event (exit code {proc.returncode})"
        )

    if result_event.get("is_error") or proc.returncode != 0:
        msg = str(result_event.get("result", "unknown error"))
        if _is_retryable_error(msg):
            raise _RetryableAPIError(msg)
        raise ClaudeRunnerError(f"Claude returned an error: {msg}")

    return result_event.get("result", "")
