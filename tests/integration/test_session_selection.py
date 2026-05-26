"""
Tests for the post-build session-selection ergonomics:
  - `--session_id` flag on `review` (repeatable, mutex with --range/--pick).
  - `--pick` flag on `review` (interactive picker over the date range).

These are not part of any PLAN.md step; they're CLI ergonomics added on top
of the completed 15-step build. The tests stick to the public surface
(`build_parser`, `main`, `ReviewCommand`) plus a few module-private helpers
where the behavior would be awkward to drive end-to-end.
"""
from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meta_harness.cli import (
    ReviewCommand,
    _collect_sessions_by_id,
    _date_range_from_sessions,
    _parse_picker_selection,
    _present_session_picker,
    _read_session_cwd,
    build_parser,
    main,
)
from meta_harness.storage.session_logs import Session


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=str(path), capture_output=True, check=True,
    )
    (path / "README.md").write_text("x\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )


def _make_session(
    sid: str,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    file_path: Path,
    n_turns: int = 0,
) -> Session:
    return Session(
        session_id=sid,
        start_time=start,
        end_time=end,
        file_path=file_path,
        turns=[],
        compaction_events=[],
    )


# ---------------------------------------------------------------------------
# Argparse surface
# ---------------------------------------------------------------------------


class TestArgparseSurface:
    def test_session_id_is_repeatable(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["review", "--session_id", "abc", "--session_id", "def"]
        )
        assert args.session_ids == ["abc", "def"]

    def test_session_id_absent_defaults_to_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days"])
        assert args.session_ids is None

    def test_pick_is_store_true(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days", "--pick"])
        assert args.pick is True

    def test_pick_defaults_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--range", "last 7 days"])
        assert args.pick is False


# ---------------------------------------------------------------------------
# main() validation of mutually-exclusive flag combinations
# ---------------------------------------------------------------------------


class TestMainMutex:
    def test_session_id_and_range_are_mutex(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        with pytest.raises(SystemExit):
            main([
                "review",
                "--repo", str(tmp_path),
                "--session_id", "abc",
                "--range", "last 7 days",
            ])

    def test_session_id_and_pick_are_mutex(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        with pytest.raises(SystemExit):
            main([
                "review",
                "--repo", str(tmp_path),
                "--session_id", "abc",
                "--pick",
            ])

    def test_session_id_alone_dispatches_to_review_with_ids(
        self, tmp_path: Path
    ) -> None:
        _init_git_repo(tmp_path)
        with patch("meta_harness.cli.ReviewCommand") as MockReview:
            instance = MagicMock()
            instance.execute.return_value = {"status": "complete"}
            MockReview.return_value = instance

            main([
                "review",
                "--repo", str(tmp_path),
                "--session_id", "abc",
                "--session_id", "def",
            ])

            kwargs = MockReview.call_args.kwargs
            assert kwargs["session_ids"] == ["abc", "def"]
            assert kwargs["pick"] is False

    def test_pick_alone_dispatches_to_review_with_pick_true(
        self, tmp_path: Path
    ) -> None:
        _init_git_repo(tmp_path)
        with patch("meta_harness.cli.ReviewCommand") as MockReview:
            instance = MagicMock()
            instance.execute.return_value = {"status": "complete"}
            MockReview.return_value = instance

            main([
                "review",
                "--repo", str(tmp_path),
                "--range", "last 7 days",
                "--pick",
            ])

            kwargs = MockReview.call_args.kwargs
            assert kwargs["pick"] is True
            assert kwargs["session_ids"] is None


# ---------------------------------------------------------------------------
# _parse_picker_selection
# ---------------------------------------------------------------------------


class TestParsePickerSelection:
    def test_blank_selects_all(self) -> None:
        assert _parse_picker_selection("", 5) == [1, 2, 3, 4, 5]

    def test_all_keyword_selects_all(self) -> None:
        assert _parse_picker_selection("all", 4) == [1, 2, 3, 4]
        assert _parse_picker_selection("ALL", 4) == [1, 2, 3, 4]

    def test_comma_list(self) -> None:
        assert _parse_picker_selection("1,3,5", 5) == [1, 3, 5]

    def test_range_token(self) -> None:
        assert _parse_picker_selection("2-4", 5) == [2, 3, 4]

    def test_range_and_singles_mixed(self) -> None:
        assert _parse_picker_selection("1-2,4", 5) == [1, 2, 4]

    def test_reverse_range_is_accepted(self) -> None:
        # 3-1 should still cover {1,2,3}
        assert _parse_picker_selection("3-1", 5) == [1, 2, 3]

    def test_out_of_range_indices_dropped(self) -> None:
        assert _parse_picker_selection("0,1,99,5", 3) == [1]

    def test_non_numeric_tokens_dropped(self) -> None:
        assert _parse_picker_selection("xyz,2", 5) == [2]

    def test_duplicates_collapsed(self) -> None:
        assert _parse_picker_selection("1,1,2,2", 5) == [1, 2]


# ---------------------------------------------------------------------------
# _date_range_from_sessions
# ---------------------------------------------------------------------------


class TestDateRangeFromSessions:
    def test_empty_returns_unknown(self) -> None:
        assert _date_range_from_sessions([]) == {
            "start": "unknown",
            "end": "unknown",
        }

    def test_single_session(self, tmp_path: Path) -> None:
        ts = datetime.datetime(2026, 5, 1, 12, 0, tzinfo=datetime.timezone.utc)
        s = _make_session("a", ts, ts, file_path=tmp_path / "a.jsonl")
        assert _date_range_from_sessions([s]) == {
            "start": "2026-05-01",
            "end": "2026-05-01",
        }

    def test_multiple_sessions_spans_min_to_max(self, tmp_path: Path) -> None:
        a = _make_session(
            "a",
            datetime.datetime(2026, 5, 1, 9, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 1, 10, 0, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "a.jsonl",
        )
        b = _make_session(
            "b",
            datetime.datetime(2026, 5, 3, 9, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 3, 11, 0, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "b.jsonl",
        )
        assert _date_range_from_sessions([a, b]) == {
            "start": "2026-05-01",
            "end": "2026-05-03",
        }


# ---------------------------------------------------------------------------
# _read_session_cwd
# ---------------------------------------------------------------------------


class TestReadSessionCwd:
    def test_returns_first_cwd(self, tmp_path: Path) -> None:
        p = tmp_path / "s.jsonl"
        p.write_text(
            json.dumps({"type": "user", "cwd": "/home/me/project"}) + "\n"
            + json.dumps({"type": "assistant", "cwd": "/other"}) + "\n"
        )
        assert _read_session_cwd(p) == "/home/me/project"

    def test_skips_lines_without_cwd(self, tmp_path: Path) -> None:
        p = tmp_path / "s.jsonl"
        p.write_text(
            json.dumps({"type": "summary"}) + "\n"
            + json.dumps({"type": "user", "cwd": "/repo"}) + "\n"
        )
        assert _read_session_cwd(p) == "/repo"

    def test_tolerates_malformed_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "s.jsonl"
        p.write_text(
            "not json\n"
            + json.dumps({"type": "user", "cwd": "/repo"}) + "\n"
        )
        assert _read_session_cwd(p) == "/repo"

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        p = tmp_path / "s.jsonl"
        p.write_text(json.dumps({"type": "user"}) + "\n")
        assert _read_session_cwd(p) is None

    def test_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        assert _read_session_cwd(tmp_path / "missing.jsonl") is None


# ---------------------------------------------------------------------------
# _collect_sessions_by_id
# ---------------------------------------------------------------------------


def _write_session_jsonl(
    dir_: Path, session_id: str, when: datetime.datetime
) -> Path:
    """Write a minimal valid Claude Code session JSONL into dir_."""
    p = dir_ / f"{session_id}.jsonl"
    ts = when.isoformat()
    p.write_text(
        json.dumps({
            "type": "user",
            "sessionId": session_id,
            "timestamp": ts,
            "cwd": "/some/repo",
            "message": {"content": "hi"},
        }) + "\n"
    )
    return p


class TestCollectSessionsById:
    def test_finds_session_by_direct_filename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        _write_session_jsonl(
            log_dir, "session-xyz",
            datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc),
        )

        monkeypatch.setattr(
            "meta_harness.cli._find_session_log_dir", lambda repo: log_dir
        )

        sessions = _collect_sessions_by_id(tmp_path, ["session-xyz"])
        assert len(sessions) == 1
        assert sessions[0].session_id == "session-xyz"

    def test_missing_session_id_is_skipped_with_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        _write_session_jsonl(
            log_dir, "session-xyz",
            datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc),
        )

        monkeypatch.setattr(
            "meta_harness.cli._find_session_log_dir", lambda repo: log_dir
        )

        sessions = _collect_sessions_by_id(tmp_path, ["session-xyz", "nope"])
        assert [s.session_id for s in sessions] == ["session-xyz"]
        captured = capsys.readouterr()
        assert "nope" in captured.err

    def test_no_log_dir_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "meta_harness.cli._find_session_log_dir", lambda repo: None
        )
        assert _collect_sessions_by_id(tmp_path, ["any"]) == []


# ---------------------------------------------------------------------------
# _present_session_picker
# ---------------------------------------------------------------------------


class TestPresentSessionPicker:
    def _sessions(self, tmp_path: Path):
        a = _make_session(
            "alpha",
            datetime.datetime(2026, 5, 1, 9, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 1, 10, 0, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "alpha.jsonl",
        )
        b = _make_session(
            "beta",
            datetime.datetime(2026, 5, 2, 9, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 2, 10, 0, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "beta.jsonl",
        )
        c = _make_session(
            "gamma",
            datetime.datetime(2026, 5, 3, 9, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 3, 10, 0, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "gamma.jsonl",
        )
        for s in (a, b, c):
            s.file_path.write_text(json.dumps({"cwd": "/x"}) + "\n")
        return [a, b, c]

    def test_non_tty_returns_unchanged_with_warning(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=False):
            result = _present_session_picker(sessions)
        assert result == sessions
        assert "not a TTY" in capsys.readouterr().err

    def test_tty_input_filters_to_selection(self, tmp_path: Path) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="1,3"):
            result = _present_session_picker(sessions)
        assert [s.session_id for s in result] == ["alpha", "gamma"]

    def test_tty_blank_input_selects_all(self, tmp_path: Path) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value=""):
            result = _present_session_picker(sessions)
        assert [s.session_id for s in result] == ["alpha", "beta", "gamma"]

    def test_tty_all_keyword_selects_all(self, tmp_path: Path) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="all"):
            result = _present_session_picker(sessions)
        assert [s.session_id for s in result] == ["alpha", "beta", "gamma"]

    def test_tty_range_token(self, tmp_path: Path) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="2-3"):
            result = _present_session_picker(sessions)
        assert [s.session_id for s in result] == ["beta", "gamma"]

    def test_tty_invalid_input_falls_back_to_all(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="xyz"):
            result = _present_session_picker(sessions)
        assert [s.session_id for s in result] == ["alpha", "beta", "gamma"]
        assert "defaulting to all" in capsys.readouterr().err

    def test_picker_listing_shows_session_metadata(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sessions = self._sessions(tmp_path)
        with patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="all"):
            _present_session_picker(sessions)
        err = capsys.readouterr().err
        # short id, timestamp, turn count and folder all appear
        assert "alpha" in err
        assert "2026-05-01" in err
        assert "turns" in err
        assert "folder:" in err


# ---------------------------------------------------------------------------
# ReviewCommand wiring (does --session_id / --pick reach _collect_*?)
# ---------------------------------------------------------------------------


class TestReviewCommandWiring:
    def _setup_kb(self, repo: Path) -> None:
        from meta_harness.storage.knowledge_base import setup as kb_setup
        kb_setup(repo)

    def test_session_ids_path_skips_range_collection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_git_repo(tmp_path)
        self._setup_kb(tmp_path)

        called = {"by_id": 0, "by_range": 0}

        def fake_by_id(repo, ids, verbose=False):
            called["by_id"] += 1
            return []

        def fake_by_range(repo, dr, verbose=False):
            called["by_range"] += 1
            return []

        monkeypatch.setattr(
            "meta_harness.cli._collect_sessions_by_id", fake_by_id
        )
        monkeypatch.setattr(
            "meta_harness.cli._collect_sessions", fake_by_range
        )

        cmd = ReviewCommand(
            repo=tmp_path,
            date_range="last 7 days",
            session_ids=["abc", "def"],
        )
        # Replace the run loop with a mock so we don't actually run agents.
        with patch.object(cmd, "_make_run_loop") as mk:
            mk.return_value.run.return_value = MagicMock(
                run_id="r1", status="complete", decisions={}
            )
            cmd.execute()

        assert called["by_id"] == 1
        assert called["by_range"] == 0

    def test_pick_path_invokes_picker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_git_repo(tmp_path)
        self._setup_kb(tmp_path)

        a = _make_session(
            "alpha",
            datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "alpha.jsonl",
        )
        b = _make_session(
            "beta",
            datetime.datetime(2026, 5, 2, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 5, 2, tzinfo=datetime.timezone.utc),
            file_path=tmp_path / "beta.jsonl",
        )

        monkeypatch.setattr(
            "meta_harness.cli._collect_sessions",
            lambda repo, dr, verbose=False: [a, b],
        )

        picker_calls = {"count": 0, "received": None}

        def fake_picker(sessions):
            picker_calls["count"] += 1
            picker_calls["received"] = sessions
            return [sessions[0]]

        monkeypatch.setattr(
            "meta_harness.cli._present_session_picker", fake_picker
        )

        cmd = ReviewCommand(
            repo=tmp_path,
            date_range="last 7 days",
            pick=True,
        )
        with patch.object(cmd, "_make_run_loop") as mk:
            mk.return_value.run.return_value = MagicMock(
                run_id="r1", status="complete", decisions={}
            )
            cmd.execute()

        assert picker_calls["count"] == 1
        assert [s.session_id for s in picker_calls["received"]] == ["alpha", "beta"]
        # The run loop should have received the picker-narrowed list.
        assert [s.session_id for s in cmd._collected_sessions] == ["alpha"]

    def test_pick_with_no_sessions_skips_picker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_git_repo(tmp_path)
        self._setup_kb(tmp_path)

        monkeypatch.setattr(
            "meta_harness.cli._collect_sessions",
            lambda repo, dr, verbose=False: [],
        )

        called = {"picker": 0}

        def fake_picker(sessions):
            called["picker"] += 1
            return sessions

        monkeypatch.setattr(
            "meta_harness.cli._present_session_picker", fake_picker
        )

        cmd = ReviewCommand(
            repo=tmp_path,
            date_range="last 7 days",
            pick=True,
        )
        with patch.object(cmd, "_make_run_loop") as mk:
            mk.return_value.run.return_value = MagicMock(
                run_id="r1", status="complete", decisions={}
            )
            cmd.execute()

        assert called["picker"] == 0

    def test_existing_callers_without_new_kwargs_still_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression guard: the new __init__ params must default to inert.
        _init_git_repo(tmp_path)
        self._setup_kb(tmp_path)

        monkeypatch.setattr(
            "meta_harness.cli._collect_sessions",
            lambda repo, dr, verbose=False: [],
        )

        cmd = ReviewCommand(repo=tmp_path, date_range="last 7 days")
        with patch.object(cmd, "_make_run_loop") as mk:
            mk.return_value.run.return_value = MagicMock(
                run_id="r1", status="complete", decisions={}
            )
            cmd.execute()  # should not raise
