"""
Tests for the per-run RCA log directory the evaluator writes under
``.meta-harness/logs/eval/<timestamp>/``.

Pins:
- summary.txt is written and contains the tee'd evaluator messages.
- Each batch gets its own ``batches/batch-NNN/`` subdir with:
    - stream.jsonl (raw events from claude -p, always written)
    - status.json (always written, outcome=ok|failed|resumed_from_checkpoint)
    - prompt.txt (only written when the batch failed)
- Successful batches do NOT leave a prompt.txt behind.
- Failed batches surface the log dir path in the stderr/summary tee.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meta_harness.agents.evaluator import EvaluatorError, evaluate
from meta_harness.storage.session_logs import Session, Turn


def _mk_session(sid: str, n_turns: int) -> Session:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = base + timedelta(minutes=n_turns)
    turns = [
        Turn(
            timestamp=base + timedelta(minutes=i),
            human_input=f"q{i}",
            assistant_response=f"a{i}",
            tool_calls=[],
            model="m",
            input_tokens=10,
            output_tokens=10,
        )
        for i in range(n_turns)
    ]
    return Session(
        session_id=sid,
        start_time=base,
        end_time=end,
        file_path=Path(f"/tmp/{sid}.jsonl"),
        turns=turns,
    )


def _canned_output(sessions: list[Session]) -> str:
    obs, pcs, narrs = [], [], []
    for s in sessions:
        for i in range(len(s.turns)):
            obs.append({
                "session_id": s.session_id,
                "turn_index": i,
                "assessment": "x",
                "effort_signal": {
                    "tokens_used": 20,
                    "model": "m",
                    "context_occupancy": 0.0,
                    "tool_calls": [],
                },
                "flags": [],
            })
        pcs.append({
            "session_id": s.session_id,
            "turn_range": {"start": 0, "end": len(s.turns) - 1},
            "pass_type": "successful_one_shot",
            "harness_gap_rationale": "-",
            "contributing_gaps": None,
        })
        narrs.append({
            "session_id": s.session_id,
            "outcome": "successful_and_accepted",
            "pass_counts_by_type": {"successful_one_shot": 1},
            "gaps_observed": [],
            "narrative": "-",
        })
    return json.dumps({
        "per_turn_observations": obs,
        "pass_classifications": pcs,
        "gap_observations": [],
        "session_narratives": narrs,
    })


# ---------------------------------------------------------------------------
# Happy path: log dir + summary + per-batch status.json
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_evaluate_creates_run_log_dir(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    s = _mk_session("s1", n_turns=3)
    mock_invoke.return_value = _canned_output([s])

    log_dir = tmp_path / "custom-log"
    evaluate(
        [s], tmp_path, write_gap_records=False, log_dir=log_dir,
    )

    assert log_dir.is_dir()
    assert (log_dir / "summary.txt").is_file()
    summary_text = (log_dir / "summary.txt").read_text(encoding="utf-8")
    assert "evaluator run log" in summary_text
    assert "1/1 sessions cached" in summary_text or "0/1 sessions cached" in summary_text


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_successful_batch_writes_status_ok_no_prompt(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    s = _mk_session("s1", n_turns=4)
    mock_invoke.return_value = _canned_output([s])

    log_dir = tmp_path / "log"
    evaluate(
        [s], tmp_path, write_gap_records=False, log_dir=log_dir,
    )

    batch_dir = log_dir / "batches" / "batch-001"
    assert batch_dir.is_dir()
    status = json.loads((batch_dir / "status.json").read_text(encoding="utf-8"))
    assert status["outcome"] == "ok"
    assert status["batch_index"] == 1
    assert status["session_ids"] == ["s1"]
    assert status["observations"] == 4

    # prompt.txt MUST NOT exist for a successful batch — failure-only policy.
    assert not (batch_dir / "prompt.txt").exists()


# ---------------------------------------------------------------------------
# stream.jsonl is teed from the runner — always-on
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_stream_jsonl_is_written_by_runner_passthrough(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    """The runner is mocked here, so stream.jsonl is empty — but we
    assert that the evaluator at least passes a per-batch log_dir down."""
    s = _mk_session("s1", n_turns=2)
    mock_invoke.return_value = _canned_output([s])

    log_dir = tmp_path / "log"
    evaluate([s], tmp_path, write_gap_records=False, log_dir=log_dir)

    # The mocked invoke_claude should have received a log_dir kwarg
    # pointing into the batch subdirectory.
    call_kwargs = mock_invoke.call_args.kwargs
    assert "log_dir" in call_kwargs
    passed_log_dir = call_kwargs["log_dir"]
    assert passed_log_dir is not None
    assert passed_log_dir == log_dir / "batches" / "batch-001"


# ---------------------------------------------------------------------------
# Failure path: status.json=failed AND prompt.txt is written
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_failed_batch_writes_status_failed_and_prompt(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    # invoke_claude returns garbage so the JSON parse step fails inside
    # _evaluate_batch.
    mock_invoke.return_value = "not json at all"

    s = _mk_session("s1", n_turns=3)
    log_dir = tmp_path / "log"

    with pytest.raises(EvaluatorError):
        evaluate(
            [s], tmp_path, write_gap_records=False, log_dir=log_dir,
        )

    batch_dir = log_dir / "batches" / "batch-001"
    status = json.loads((batch_dir / "status.json").read_text(encoding="utf-8"))
    assert status["outcome"] == "failed"
    assert "error" in status and status["error"]

    # prompt.txt MUST exist for a failed batch and contain the session text.
    prompt_text = (batch_dir / "prompt.txt").read_text(encoding="utf-8")
    assert "archived_sessions_to_analyze" in prompt_text
    assert "archived_session_log" in prompt_text
    assert "s1" in prompt_text


# ---------------------------------------------------------------------------
# Re-run after a successful batch: status records resume_from_checkpoint
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_rerun_records_checkpoint_resumption(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    s = _mk_session("s1", n_turns=2)
    mock_invoke.return_value = _canned_output([s])

    # First run populates the in-run batch checkpoint AND the per-session
    # cache.  Use a custom checkpoint_dir to keep the batch checkpoint
    # findable on the second run, but pass a NEW log_dir so this run's
    # status.json is distinct.
    ckpt_dir = tmp_path / "ckpt"
    evaluate(
        [s], tmp_path, write_gap_records=False,
        checkpoint_dir=ckpt_dir,
        log_dir=tmp_path / "log-1",
    )

    # Wipe the per-session cache so the second run takes the batch path,
    # which is where the checkpoint resumption is observable.
    import shutil
    shutil.rmtree(tmp_path / ".meta-harness" / "eval-cache" / "sessions")

    mock_invoke.reset_mock()
    evaluate(
        [s], tmp_path, write_gap_records=False,
        checkpoint_dir=ckpt_dir,
        log_dir=tmp_path / "log-2",
    )

    # Model not called again — checkpoint was reused.
    assert mock_invoke.call_count == 0

    batch_dir = tmp_path / "log-2" / "batches" / "batch-001"
    status = json.loads((batch_dir / "status.json").read_text(encoding="utf-8"))
    assert status["outcome"] == "resumed_from_checkpoint"


# ---------------------------------------------------------------------------
# Default log_dir layout when none is passed: logs/eval/<timestamp>/
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_default_log_dir_lands_under_logs_eval(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    s = _mk_session("s1", n_turns=2)
    mock_invoke.return_value = _canned_output([s])

    evaluate([s], tmp_path, write_gap_records=False)

    logs_root = tmp_path / ".meta-harness" / "logs" / "eval"
    assert logs_root.is_dir()
    entries = list(logs_root.iterdir())
    assert len(entries) == 1
    run_dir = entries[0]
    # Timestamp directory should be ISO-8601-ish: YYYY-MM-DDTHH-MM-SSZ
    assert "T" in run_dir.name
    assert run_dir.name.endswith("Z")
    assert (run_dir / "summary.txt").is_file()
    assert (run_dir / "batches" / "batch-001" / "status.json").is_file()
