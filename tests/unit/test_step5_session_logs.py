"""
Step 5 — Session log reader: failing gate (Session A).

Spec ref: docs/spec/02-storage/session-logs.md

Gate criteria (from docs/PLAN.md Step 5):
  1. Walk Claude Code's session log directory correctly.
  2. Parse JSONL; expose a session abstraction matching the spec.
  3. Date-range filtering is correct on edge cases (boundary days,
     empty range, range with no matching sessions).
  4. No code path under this module writes to the session-log directory
     (static check or audit).

All tests must FAIL before implementation exists (Session A gate criterion).

Synthetic fixtures live under tests/fixtures/session_logs/ and contain the
following sessions (by start date):
  session_basic.jsonl             — 2024-01-15
  session_with_tool_calls.jsonl   — 2024-01-15
  session_with_compaction.jsonl   — 2024-01-16
  session_mid_range.jsonl         — 2024-01-20
  session_end_range.jsonl         — 2024-02-01
"""
import ast
import datetime
import importlib.util
import json
import pathlib

import pytest

# This import drives the gate: all tests fail with ImportError until
# src/claude_reflect/storage/session_logs.py is implemented.
from claude_reflect.storage.session_logs import (
    Session,
    SessionLogReader,
    ToolCall,
    Turn,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "session_logs"


# ---------------------------------------------------------------------------
# Gate criterion 1 — directory walking
# ---------------------------------------------------------------------------


class TestDirectoryWalking:
    def test_walks_all_jsonl_files(self, tmp_path: pathlib.Path) -> None:
        """Reader discovers every .jsonl file in the session log directory."""
        for i in range(3):
            f = tmp_path / f"session_{i:04d}.jsonl"
            f.write_text(
                json.dumps({
                    "type": "user",
                    "sessionId": f"sid-{i}",
                    "uuid": f"uuid-{i:04d}",
                    "timestamp": f"2024-01-{15 + i:02d}T10:00:00.000Z",
                    "message": {"role": "user", "content": "test"},
                }) + "\n"
            )

        reader = SessionLogReader(tmp_path)
        sessions = reader.list_all_sessions()
        assert len(sessions) == 3

    def test_ignores_non_jsonl_files(self, tmp_path: pathlib.Path) -> None:
        """Reader ignores files that are not .jsonl."""
        (tmp_path / "session_0001.jsonl").write_text(
            json.dumps({
                "type": "user",
                "sessionId": "sid-0",
                "uuid": "uuid-0001",
                "timestamp": "2024-01-15T10:00:00.000Z",
                "message": {"role": "user", "content": "hello"},
            }) + "\n"
        )
        (tmp_path / "not_a_log.txt").write_text("should be ignored\n")
        (tmp_path / "notes.md").write_text("# Notes\n")

        reader = SessionLogReader(tmp_path)
        sessions = reader.list_all_sessions()
        assert len(sessions) == 1

    def test_empty_directory_returns_empty_list(self, tmp_path: pathlib.Path) -> None:
        """Reader returns an empty list when the directory has no .jsonl files."""
        reader = SessionLogReader(tmp_path)
        assert reader.list_all_sessions() == []

    def test_reader_accepts_path_object(self, tmp_path: pathlib.Path) -> None:
        """SessionLogReader accepts a pathlib.Path as its directory argument."""
        assert SessionLogReader(tmp_path) is not None

    def test_reader_accepts_string_path(self, tmp_path: pathlib.Path) -> None:
        """SessionLogReader accepts a string path as its directory argument."""
        assert SessionLogReader(str(tmp_path)) is not None

    def test_returns_session_objects(self, tmp_path: pathlib.Path) -> None:
        """list_all_sessions() returns a list of Session instances."""
        (tmp_path / "s.jsonl").write_text(
            json.dumps({
                "type": "user",
                "sessionId": "sid-x",
                "uuid": "uuid-x",
                "timestamp": "2024-01-15T10:00:00.000Z",
                "message": {"role": "user", "content": "hi"},
            }) + "\n"
        )
        reader = SessionLogReader(tmp_path)
        sessions = reader.list_all_sessions()
        assert len(sessions) == 1
        assert isinstance(sessions[0], Session)


# ---------------------------------------------------------------------------
# Gate criterion 2 — JSONL parsing and session abstraction
# ---------------------------------------------------------------------------


class TestJSONLParsing:
    def test_fixture_directory_has_expected_files(self) -> None:
        """All five synthetic fixture files are present."""
        expected = {
            "session_basic.jsonl",
            "session_with_tool_calls.jsonl",
            "session_with_compaction.jsonl",
            "session_mid_range.jsonl",
            "session_end_range.jsonl",
        }
        found = {p.name for p in FIXTURES.glob("*.jsonl")}
        assert expected <= found

    def test_parse_all_fixture_sessions(self) -> None:
        """Reader parses all fixture files without error."""
        reader = SessionLogReader(FIXTURES)
        sessions = reader.list_all_sessions()
        assert len(sessions) >= 5

    def test_session_has_session_id(self) -> None:
        """Every Session exposes a non-empty session_id string."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            assert hasattr(session, "session_id")
            assert session.session_id is not None
            assert len(str(session.session_id)) > 0

    def test_session_has_start_time(self) -> None:
        """Every Session exposes a start_time datetime."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            assert hasattr(session, "start_time")
            assert isinstance(session.start_time, datetime.datetime)

    def test_session_has_end_time(self) -> None:
        """Every Session exposes an end_time datetime."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            assert hasattr(session, "end_time")
            assert isinstance(session.end_time, datetime.datetime)

    def test_end_time_not_before_start_time(self) -> None:
        """end_time >= start_time for every session."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            assert session.end_time >= session.start_time

    def test_session_has_file_path(self) -> None:
        """Every Session exposes a file_path pointing to the source file."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            assert hasattr(session, "file_path")
            assert isinstance(session.file_path, pathlib.Path)
            assert session.file_path.exists()

    def test_session_has_turns_list(self) -> None:
        """Every Session exposes a list of Turn objects."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            assert hasattr(session, "turns")
            assert isinstance(session.turns, list)

    def test_sessions_with_messages_have_turns(self) -> None:
        """Sessions that contain user/assistant messages have at least one turn."""
        reader = SessionLogReader(FIXTURES)
        sessions = reader.list_all_sessions()
        sessions_with_turns = [s for s in sessions if len(s.turns) > 0]
        assert len(sessions_with_turns) >= 3

    def test_turn_fields_present(self) -> None:
        """Each Turn exposes timestamp, human_input, assistant_response, tool_calls."""
        reader = SessionLogReader(FIXTURES)
        sessions = reader.list_all_sessions()
        sessions_with_turns = [s for s in sessions if s.turns]
        assert sessions_with_turns, "Need at least one session with turns"
        turn = sessions_with_turns[0].turns[0]
        assert hasattr(turn, "timestamp")
        assert hasattr(turn, "human_input")
        assert hasattr(turn, "assistant_response")
        assert hasattr(turn, "tool_calls")

    def test_turn_timestamp_is_datetime_or_none(self) -> None:
        """Turn.timestamp is a datetime.datetime or None."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            for turn in session.turns:
                assert turn.timestamp is None or isinstance(turn.timestamp, datetime.datetime)

    def test_turn_tool_calls_is_list(self) -> None:
        """Turn.tool_calls is always a list (possibly empty)."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            for turn in session.turns:
                assert isinstance(turn.tool_calls, list)

    def test_session_with_tool_calls_has_tool_turns(self) -> None:
        """The tool-calls fixture produces at least one turn with tool_calls."""
        session = SessionLogReader.read_session(
            FIXTURES / "session_with_tool_calls.jsonl"
        )
        turns_with_tools = [t for t in session.turns if t.tool_calls]
        assert len(turns_with_tools) >= 1

    def test_tool_call_has_name_and_input(self) -> None:
        """Each ToolCall exposes a name (str) and input (dict)."""
        session = SessionLogReader.read_session(
            FIXTURES / "session_with_tool_calls.jsonl"
        )
        tool_calls = [tc for t in session.turns for tc in t.tool_calls]
        assert tool_calls, "Expected at least one ToolCall in tool-calls fixture"
        for tc in tool_calls:
            assert isinstance(tc, ToolCall)
            assert hasattr(tc, "name")
            assert isinstance(tc.name, str)
            assert hasattr(tc, "input")
            assert isinstance(tc.input, dict)

    def test_turn_has_model_and_token_fields(self) -> None:
        """Turns from assistant messages expose model, input_tokens, output_tokens."""
        session = SessionLogReader.read_session(FIXTURES / "session_basic.jsonl")
        assistant_turns = [t for t in session.turns if t.assistant_response is not None]
        assert assistant_turns, "Expected at least one assistant turn"
        for turn in assistant_turns:
            assert hasattr(turn, "model")
            assert hasattr(turn, "input_tokens")
            assert hasattr(turn, "output_tokens")

    def test_token_counts_are_int_or_none(self) -> None:
        """input_tokens and output_tokens are int (or None) for all turns."""
        reader = SessionLogReader(FIXTURES)
        for session in reader.list_all_sessions():
            for turn in session.turns:
                assert turn.input_tokens is None or isinstance(turn.input_tokens, int)
                assert turn.output_tokens is None or isinstance(turn.output_tokens, int)

    def test_session_with_compaction_has_compaction_events(self) -> None:
        """The compaction fixture exposes a compaction_events attribute."""
        session = SessionLogReader.read_session(
            FIXTURES / "session_with_compaction.jsonl"
        )
        assert hasattr(session, "compaction_events")
        assert isinstance(session.compaction_events, list)
        assert len(session.compaction_events) >= 1

    def test_read_session_classmethod_returns_session(self) -> None:
        """SessionLogReader.read_session(path) returns a Session instance."""
        session = SessionLogReader.read_session(FIXTURES / "session_basic.jsonl")
        assert isinstance(session, Session)

    def test_basic_fixture_session_id(self) -> None:
        """The basic fixture has the expected session_id."""
        session = SessionLogReader.read_session(FIXTURES / "session_basic.jsonl")
        assert session.session_id == "session-basic-001"

    def test_malformed_jsonl_line_does_not_crash(self, tmp_path: pathlib.Path) -> None:
        """A single malformed JSONL line is skipped; the rest of the session parses."""
        f = tmp_path / "session_bad.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "sessionId": "sid-bad",
                "uuid": "uuid-bad-01",
                "timestamp": "2024-01-15T10:00:00.000Z",
                "message": {"role": "user", "content": "hello"},
            }),
            "THIS IS NOT VALID JSON }{",
            json.dumps({
                "type": "assistant",
                "sessionId": "sid-bad",
                "uuid": "uuid-bad-02",
                "timestamp": "2024-01-15T10:00:05.000Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                    "model": "claude-opus-4-6",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            }),
        ]
        f.write_text("\n".join(lines) + "\n")
        reader = SessionLogReader(tmp_path)
        sessions = reader.list_all_sessions()
        assert len(sessions) == 1


# ---------------------------------------------------------------------------
# Gate criterion 3 — date-range filtering
# ---------------------------------------------------------------------------


class TestDateRangeFiltering:
    """
    Fixture dates:
      session_basic.jsonl           2024-01-15
      session_with_tool_calls.jsonl 2024-01-15
      session_with_compaction.jsonl 2024-01-16
      session_mid_range.jsonl       2024-01-20
      session_end_range.jsonl       2024-02-01
    """

    def test_wide_range_returns_all_sessions(self) -> None:
        """A range spanning all fixtures returns every session."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2000, 1, 1)
        end = datetime.date(2099, 12, 31)
        all_sessions = reader.list_all_sessions()
        filtered = reader.sessions_in_range(start, end)
        assert len(filtered) == len(all_sessions)

    def test_filter_returns_subset(self) -> None:
        """A mid-range filter returns fewer sessions than list_all_sessions."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 1, 20)
        end = datetime.date(2024, 2, 1)
        filtered = reader.sessions_in_range(start, end)
        # mid_range (Jan 20) and end_range (Feb 1)
        assert len(filtered) >= 2
        all_sessions = reader.list_all_sessions()
        assert len(filtered) < len(all_sessions)

    def test_boundary_start_day_is_inclusive(self) -> None:
        """A session whose date equals start is included."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 1, 15)
        end = datetime.date(2024, 1, 15)
        sessions = reader.sessions_in_range(start, end)
        assert len(sessions) >= 1
        for s in sessions:
            assert s.start_time.date() == datetime.date(2024, 1, 15)

    def test_boundary_end_day_is_inclusive(self) -> None:
        """A session whose date equals end is included."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 2, 1)
        end = datetime.date(2024, 2, 1)
        sessions = reader.sessions_in_range(start, end)
        assert len(sessions) >= 1
        for s in sessions:
            assert s.start_time.date() == datetime.date(2024, 2, 1)

    def test_start_greater_than_end_returns_empty(self) -> None:
        """When start > end the result is an empty list."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 1, 20)
        end = datetime.date(2024, 1, 15)
        assert reader.sessions_in_range(start, end) == []

    def test_future_range_with_no_sessions_returns_empty(self) -> None:
        """A range that contains no sessions returns an empty list."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2099, 1, 1)
        end = datetime.date(2099, 12, 31)
        assert reader.sessions_in_range(start, end) == []

    def test_single_day_gap_returns_empty(self) -> None:
        """A single day between sessions (no sessions on that day) returns empty."""
        reader = SessionLogReader(FIXTURES)
        # 2024-01-17 is between compaction (Jan 16) and mid_range (Jan 20)
        start = datetime.date(2024, 1, 17)
        end = datetime.date(2024, 1, 17)
        assert reader.sessions_in_range(start, end) == []

    def test_excludes_sessions_before_start(self) -> None:
        """Sessions whose date is before start are absent from the result."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 1, 20)
        end = datetime.date(2024, 2, 1)
        for s in reader.sessions_in_range(start, end):
            assert s.start_time.date() >= start

    def test_excludes_sessions_after_end(self) -> None:
        """Sessions whose date is after end are absent from the result."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 1, 15)
        end = datetime.date(2024, 1, 20)
        for s in reader.sessions_in_range(start, end):
            assert s.start_time.date() <= end

    def test_returns_list_of_session_objects(self) -> None:
        """sessions_in_range returns a list of Session instances."""
        reader = SessionLogReader(FIXTURES)
        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 12, 31)
        result = reader.sessions_in_range(start, end)
        assert isinstance(result, list)
        for s in result:
            assert isinstance(s, Session)


# ---------------------------------------------------------------------------
# Gate criterion 4 — read-only enforcement (static check)
# ---------------------------------------------------------------------------


class TestReadOnlyEnforcement:
    """
    Reads the source of claude_reflect.storage.session_logs using importlib and
    ast, then asserts that no write-mode file operations appear in the module.

    This is a static audit, not a runtime test, so it works without invoking
    the reader on live session log directories.
    """

    @staticmethod
    def _source() -> str:
        spec = importlib.util.find_spec("claude_reflect.storage.session_logs")
        assert spec is not None, (
            "claude_reflect.storage.session_logs not found — "
            "implement src/claude_reflect/storage/session_logs.py first"
        )
        assert spec.origin is not None
        return pathlib.Path(spec.origin).read_text()

    @staticmethod
    def _all_call_names(source: str) -> set:
        tree = ast.parse(source)
        names: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    names.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    names.add(node.func.id)
        return names

    def test_no_write_method_calls(self) -> None:
        """Module contains no .write(), .write_text(), or .write_bytes() calls."""
        source = self._source()
        calls = self._all_call_names(source)
        prohibited = {"write", "write_text", "write_bytes"}
        found = prohibited & calls
        assert not found, f"Prohibited write calls found in module: {found}"

    def test_no_open_in_write_mode(self) -> None:
        """Module does not open any file in write or append mode."""
        source = self._source()
        write_modes = {"'w'", '"w"', "'wb'", '"wb"', "'a'", '"a"', "'ab'", '"ab"'}
        for mode in write_modes:
            assert mode not in source, (
                f"Source opens a file in write mode {mode}"
            )

    def test_no_file_deletion_calls(self) -> None:
        """Module contains no unlink, remove, rmtree, or rmdir calls."""
        source = self._source()
        calls = self._all_call_names(source)
        prohibited = {"unlink", "remove", "rmtree", "rmdir"}
        found = prohibited & calls
        assert not found, f"Prohibited deletion calls found in module: {found}"

    def test_no_shutil_write_operations(self) -> None:
        """Module does not invoke shutil write/move/copy functions."""
        source = self._source()
        for call in ("shutil.move", "shutil.copy", "shutil.copytree", "shutil.rmtree"):
            assert call not in source, f"Prohibited shutil call found: {call}"

    def test_reader_leaves_directory_unmodified(self, tmp_path: pathlib.Path) -> None:
        """Reading sessions does not create, modify, or delete any files."""
        import os

        session_file = tmp_path / "session_ro.jsonl"
        session_file.write_text(
            json.dumps({
                "type": "user",
                "sessionId": "sid-ro",
                "uuid": "uuid-ro-01",
                "timestamp": "2024-01-15T10:00:00.000Z",
                "message": {"role": "user", "content": "hello"},
            }) + "\n"
        )
        mtime_before = os.path.getmtime(session_file)
        files_before = set(tmp_path.iterdir())

        reader = SessionLogReader(tmp_path)
        reader.list_all_sessions()

        mtime_after = os.path.getmtime(session_file)
        files_after = set(tmp_path.iterdir())

        assert mtime_before == mtime_after, "Session file mtime changed after read"
        assert files_before == files_after, (
            f"Directory contents changed: before={files_before}, after={files_after}"
        )
