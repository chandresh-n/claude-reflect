"""
Tests for the runner's log_dir tee.

Pins:
- ``stream.jsonl`` is always written when log_dir is set, with attempt
  markers around the stream-json events.
- Multiple retry attempts all append to the same ``stream.jsonl`` and are
  distinguishable by their ``_meta`` lines.
- When log_dir is not passed, no log files are produced.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meta_harness.agents import claude_runner as cr
from meta_harness.agents.claude_runner import (
    ClaudeRunnerError,
    invoke_claude,
)


class _MockStdout:
    def __init__(self, data: str) -> None:
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> str:
        if self._pos >= len(self._data):
            return ""
        if n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + n]
            self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


def _make_mock_popen(stream_text: str, returncode: int = 0):
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = _MockStdout(stream_text)
    proc.stderr = MagicMock()
    proc.returncode = returncode
    proc.wait.return_value = returncode
    proc.poll.return_value = returncode
    return proc


def _select_ready(rlist, wlist, xlist, timeout=None):
    return (rlist, [], [])


_patch_select = patch(
    "meta_harness.agents.claude_runner.select.select", _select_ready
)


@_patch_select
@patch("meta_harness.agents.claude_runner.subprocess.Popen")
def test_stream_jsonl_written_when_log_dir_passed(
    mock_popen: MagicMock, tmp_path: Path
) -> None:
    """Stream events + attempt markers should land in <log_dir>/stream.jsonl."""
    events = "\n".join([
        json.dumps({"type": "system", "model": "m", "session_id": "abc123"}),
        json.dumps({
            "type": "assistant",
            "message": {
                "usage": {"output_tokens": 5},
                "content": [{"type": "text", "text": "hello\n"}],
            },
        }),
        json.dumps({"type": "result", "is_error": False, "result": "OK"}),
    ]) + "\n"
    mock_popen.return_value = _make_mock_popen(events)

    log_dir = tmp_path / "batch"
    result = invoke_claude(
        system_prompt="s", user_prompt="u", log_dir=log_dir,
    )
    assert result == "OK"

    stream_file = log_dir / "stream.jsonl"
    assert stream_file.is_file()
    lines = [
        json.loads(line)
        for line in stream_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Expect: attempt_start, system, assistant, result, attempt_end.
    metas = [ln for ln in lines if "_meta" in ln]
    assert len(metas) == 2
    assert metas[0]["_meta"] == "attempt_start"
    assert metas[1]["_meta"] == "attempt_end"
    assert metas[1]["outcome"] == "ok"

    # The runner's own events should also be there in original form.
    event_types = [ln.get("type") for ln in lines if "type" in ln]
    assert event_types == ["system", "assistant", "result"]


@_patch_select
@patch("meta_harness.agents.claude_runner.subprocess.Popen")
def test_no_log_files_when_log_dir_not_passed(
    mock_popen: MagicMock, tmp_path: Path
) -> None:
    """Calling without log_dir must not create any files."""
    events = json.dumps(
        {"type": "result", "is_error": False, "result": "OK"}
    ) + "\n"
    mock_popen.return_value = _make_mock_popen(events)

    invoke_claude(system_prompt="s", user_prompt="u")
    # tmp_path is empty
    assert list(tmp_path.iterdir()) == []


@_patch_select
@patch("meta_harness.agents.claude_runner.subprocess.Popen")
def test_retry_attempts_append_to_same_stream_jsonl(
    mock_popen: MagicMock, tmp_path: Path
) -> None:
    """Both attempts of a retried invocation should land in one stream.jsonl
    with two attempt_start/attempt_end pairs."""
    overloaded = json.dumps(
        {"type": "result", "is_error": True, "result": "Overloaded"}
    ) + "\n"
    success = json.dumps(
        {"type": "result", "is_error": False, "result": "OK"}
    ) + "\n"
    mock_popen.side_effect = [
        _make_mock_popen(overloaded, returncode=1),
        _make_mock_popen(success),
    ]

    log_dir = tmp_path / "batch"
    with patch.object(cr.time, "sleep", lambda s: None):
        result = invoke_claude(
            system_prompt="s", user_prompt="u",
            log_dir=log_dir, max_retries=1,
        )
    assert result == "OK"

    stream_file = log_dir / "stream.jsonl"
    lines = [
        json.loads(line)
        for line in stream_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    starts = [ln for ln in lines if ln.get("_meta") == "attempt_start"]
    ends = [ln for ln in lines if ln.get("_meta") == "attempt_end"]
    assert [s["attempt"] for s in starts] == [0, 1]
    assert [e["outcome"] for e in ends] == ["retryable_error", "ok"]


@_patch_select
@patch("meta_harness.agents.claude_runner.subprocess.Popen")
def test_stream_jsonl_records_hard_error_outcome(
    mock_popen: MagicMock, tmp_path: Path
) -> None:
    """Non-retryable error should be recorded as outcome=error in the
    attempt_end marker."""
    bad = json.dumps(
        {"type": "result", "is_error": True, "result": "Invalid API key"}
    ) + "\n"
    mock_popen.return_value = _make_mock_popen(bad, returncode=1)

    log_dir = tmp_path / "batch"
    with pytest.raises(ClaudeRunnerError):
        invoke_claude(
            system_prompt="s", user_prompt="u",
            log_dir=log_dir, max_retries=0,
        )

    lines = [
        json.loads(line)
        for line in (log_dir / "stream.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    end = [ln for ln in lines if ln.get("_meta") == "attempt_end"][-1]
    assert end["outcome"] == "error"
    assert "Invalid API key" in (end.get("error") or "")
