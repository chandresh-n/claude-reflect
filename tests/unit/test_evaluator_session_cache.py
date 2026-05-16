"""
Tests for the per-session evaluator cache.

Pins the behavior that re-running the evaluator over an overlapping set
of sessions reuses cached per-session output, and only freshly-evaluates
sessions whose tail (end_time / turn_count) has changed or that weren't
seen before. This was added after the cache-key-too-coarse RCA where a
3-turn growth in one session invalidated the entire cache.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meta_harness.agents.evaluator import (
    _dedup_gap_observations,
    _merge_with_cached,
    _read_session_cache,
    _session_cache_key,
    _write_session_cache,
    evaluate,
)
from meta_harness.storage.session_logs import Session, Turn


def _mk_session(sid: str, n_turns: int, end_offset_minutes: int = 0) -> Session:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = base + timedelta(minutes=end_offset_minutes)
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


def _canned_output_for(sessions: list[Session]) -> str:
    """Build a valid evaluator JSON output covering exactly these sessions."""
    obs = []
    pcs = []
    narrs = []
    for s in sessions:
        for i in range(len(s.turns)):
            obs.append({
                "session_id": s.session_id,
                "turn_index": i,
                "assessment": f"obs {s.session_id} t{i}",
                "effort_signal": {
                    "tokens_used": 20,
                    "model": "m",
                    "context_occupancy": 0.01,
                    "tool_calls": [],
                },
                "flags": [],
            })
        pcs.append({
            "session_id": s.session_id,
            "turn_range": {"start": 0, "end": len(s.turns) - 1},
            "pass_type": "successful_one_shot",
            "harness_gap_rationale": "n/a",
            "contributing_gaps": None,
        })
        narrs.append({
            "session_id": s.session_id,
            "outcome": "successful_and_accepted",
            "pass_counts_by_type": {"successful_one_shot": 1},
            "gaps_observed": [],
            "narrative": f"narrative for {s.session_id}",
        })
    return json.dumps({
        "per_turn_observations": obs,
        "pass_classifications": pcs,
        "gap_observations": [],
        "session_narratives": narrs,
    })


# ---------------------------------------------------------------------------
# session_cache_key: stable, granular
# ---------------------------------------------------------------------------


def test_session_cache_key_changes_on_turn_growth() -> None:
    """RCA regression: one extra turn changes the cache key."""
    s_before = _mk_session("s1", n_turns=10, end_offset_minutes=10)
    s_after = _mk_session("s1", n_turns=11, end_offset_minutes=11)
    assert _session_cache_key(s_before, "m") != _session_cache_key(s_after, "m")


def test_session_cache_key_stable_when_unchanged() -> None:
    s1 = _mk_session("s1", n_turns=10, end_offset_minutes=10)
    s2 = _mk_session("s1", n_turns=10, end_offset_minutes=10)
    assert _session_cache_key(s1, "m") == _session_cache_key(s2, "m")


def test_session_cache_key_changes_with_model() -> None:
    s = _mk_session("s1", n_turns=10)
    assert _session_cache_key(s, "model-a") != _session_cache_key(s, "model-b")


# ---------------------------------------------------------------------------
# evaluate(): partial-cache-hit only re-evaluates uncached sessions
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_evaluate_skips_cached_sessions_on_rerun(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    """First run evaluates 3 sessions; second run with one grown session
    only invokes the LLM for the grown session."""
    s_a = _mk_session("s-a", n_turns=5, end_offset_minutes=5)
    s_b = _mk_session("s-b", n_turns=5, end_offset_minutes=5)
    s_c = _mk_session("s-c", n_turns=5, end_offset_minutes=5)

    # First run: all three sessions go through the model.
    mock_invoke.return_value = _canned_output_for([s_a, s_b, s_c])
    out1 = evaluate(
        [s_a, s_b, s_c], tmp_path, write_gap_records=False
    )
    assert mock_invoke.call_count == 1
    assert len(out1["per_turn_observations"]) == 15

    # Second run: s_b has grown by 3 turns; s_a and s_c are unchanged.
    s_b_grown = _mk_session("s-b", n_turns=8, end_offset_minutes=8)
    mock_invoke.reset_mock()
    mock_invoke.return_value = _canned_output_for([s_b_grown])

    out2 = evaluate(
        [s_a, s_b_grown, s_c], tmp_path, write_gap_records=False
    )

    # Only s_b_grown should have hit the model.
    assert mock_invoke.call_count == 1, (
        "Cache should have skipped s_a and s_c; model invoked only for s_b_grown"
    )

    # The merged output must cover all three sessions and include the new
    # turn count for s_b_grown.
    obs_by_sid: dict[str, int] = {}
    for o in out2["per_turn_observations"]:
        obs_by_sid[o["session_id"]] = obs_by_sid.get(o["session_id"], 0) + 1
    assert obs_by_sid == {"s-a": 5, "s-b": 8, "s-c": 5}


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_evaluate_full_cache_hit_skips_model_entirely(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    """If every session is cached, the LLM is never invoked."""
    s = _mk_session("s1", n_turns=4)
    mock_invoke.return_value = _canned_output_for([s])
    evaluate([s], tmp_path, write_gap_records=False)
    assert mock_invoke.call_count == 1

    mock_invoke.reset_mock()
    out = evaluate([s], tmp_path, write_gap_records=False)
    assert mock_invoke.call_count == 0
    assert len(out["per_turn_observations"]) == 4


# ---------------------------------------------------------------------------
# Cache layout: written under .meta-harness/eval-cache/sessions/
# ---------------------------------------------------------------------------


@patch("meta_harness.agents.evaluator.invoke_claude")
def test_session_cache_files_land_in_expected_dir(
    mock_invoke: MagicMock, tmp_path: Path
) -> None:
    s = _mk_session("s1", n_turns=2)
    mock_invoke.return_value = _canned_output_for([s])
    evaluate([s], tmp_path, write_gap_records=False)

    cache_dir = tmp_path / ".meta-harness" / "eval-cache" / "sessions"
    assert cache_dir.is_dir()
    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["session_id"] == "s1"
    assert data["session_signature"]["turn_count"] == 2


# ---------------------------------------------------------------------------
# Internal helpers: dedup of gap observations across cached + fresh
# ---------------------------------------------------------------------------


def test_dedup_gap_observations_unions_evidence_by_id() -> None:
    """Two observations of the same gap_id from different runs are merged
    into one with the union of their evidence_additions."""
    a = {
        "matched_gap_id": "gap-001",
        "evidence_additions": [
            {"session_id": "s-a", "turn_range": {"start": 0, "end": 1}}
        ],
    }
    b = {
        "matched_gap_id": "gap-001",
        "evidence_additions": [
            {"session_id": "s-b", "turn_range": {"start": 2, "end": 3}}
        ],
    }
    deduped = _dedup_gap_observations([a, b])
    assert len(deduped) == 1
    sids = {e["session_id"] for e in deduped[0]["evidence_additions"]}
    assert sids == {"s-a", "s-b"}


def test_dedup_gap_observations_distinguishes_new_gaps_by_characterization() -> None:
    a = {
        "matched_gap_id": None,
        "characterization": "pattern-X",
        "evidence_additions": [{"session_id": "s-a"}],
    }
    b = {
        "matched_gap_id": None,
        "characterization": "pattern-Y",
        "evidence_additions": [{"session_id": "s-b"}],
    }
    assert len(_dedup_gap_observations([a, b])) == 2


# ---------------------------------------------------------------------------
# Merging cached + fresh outputs preserves all 4 top-level lists
# ---------------------------------------------------------------------------


def test_merge_with_cached_concatenates_per_turn_obs() -> None:
    fresh = {
        "per_turn_observations": [{"session_id": "fresh", "turn_index": 0}],
        "pass_classifications": [],
        "gap_observations": [],
        "session_narratives": [],
    }
    cached = [
        {
            "per_turn_observations": [{"session_id": "old", "turn_index": 0}],
            "pass_classifications": [],
            "session_narrative": {
                "session_id": "old",
                "outcome": "successful_and_accepted",
                "pass_counts_by_type": {},
                "gaps_observed": [],
                "narrative": "n",
            },
            "gap_observations": [],
        }
    ]
    merged = _merge_with_cached(fresh, cached)
    sids = {o["session_id"] for o in merged["per_turn_observations"]}
    assert sids == {"fresh", "old"}
    assert len(merged["session_narratives"]) == 1
    assert merged["session_narratives"][0]["session_id"] == "old"
