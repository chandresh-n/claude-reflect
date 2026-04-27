"""
Session log reader for Claude Code's native JSONL session logs.

Read-only: this module never modifies, creates, or deletes session log files.

Spec ref: docs/spec/02-storage/session-logs.md
"""
from __future__ import annotations

import datetime
import json
import pathlib
from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class ToolCall:
    name: str
    input: dict


@dataclass
class Turn:
    timestamp: Optional[datetime.datetime]
    human_input: Optional[str]
    assistant_response: Optional[str]
    tool_calls: List[ToolCall] = field(default_factory=list)
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass
class Session:
    session_id: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    file_path: pathlib.Path
    turns: List[Turn]
    compaction_events: List[dict] = field(default_factory=list)


def _parse_timestamp(ts_str: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _extract_text(content) -> Optional[str]:
    if isinstance(content, str):
        return content if content else None
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(parts) if parts else None
    return None


def _extract_tool_calls(content) -> List[ToolCall]:
    if not isinstance(content, list):
        return []
    return [
        ToolCall(name=block.get("name", ""), input=block.get("input", {}))
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


class SessionLogReader:
    def __init__(self, directory: Union[str, pathlib.Path]) -> None:
        self._directory = pathlib.Path(directory)

    @staticmethod
    def read_session(path: Union[str, pathlib.Path]) -> Session:
        path = pathlib.Path(path)
        raw_lines = path.read_text(encoding="utf-8").splitlines()

        parsed_lines = []
        for raw in raw_lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed_lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue

        if not parsed_lines:
            epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
            return Session(
                session_id=path.stem,
                start_time=epoch,
                end_time=epoch,
                file_path=path,
                turns=[],
                compaction_events=[],
            )

        # Resolve session_id from the first line that has one
        session_id = path.stem
        for line in parsed_lines:
            sid = line.get("sessionId")
            if sid:
                session_id = sid
                break

        # Collect all timestamps to determine session start/end
        timestamps: List[datetime.datetime] = []
        for line in parsed_lines:
            ts_str = line.get("timestamp")
            if ts_str:
                try:
                    timestamps.append(_parse_timestamp(ts_str))
                except (ValueError, AttributeError):
                    pass

        epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        start_time = min(timestamps) if timestamps else epoch
        end_time = max(timestamps) if timestamps else epoch

        # Build Turn list and collect compaction events
        turns: List[Turn] = []
        compaction_events: List[dict] = []
        pending_turn: Optional[Turn] = None

        for line in parsed_lines:
            ltype = line.get("type")
            ts_str = line.get("timestamp")
            ts = _parse_timestamp(ts_str) if ts_str else None

            if ltype == "user":
                if pending_turn is not None:
                    turns.append(pending_turn)
                msg = line.get("message", {})
                content = msg.get("content", "")
                human_text = content if isinstance(content, str) else str(content)
                pending_turn = Turn(
                    timestamp=ts,
                    human_input=human_text,
                    assistant_response=None,
                    tool_calls=[],
                    model=None,
                    input_tokens=None,
                    output_tokens=None,
                )

            elif ltype == "assistant":
                msg = line.get("message", {})
                content = msg.get("content", [])
                response_text = _extract_text(content)
                tool_calls = _extract_tool_calls(content)
                model = msg.get("model")
                usage = msg.get("usage", {})
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")

                if pending_turn is not None:
                    pending_turn.assistant_response = response_text
                    pending_turn.tool_calls = tool_calls
                    pending_turn.model = model
                    pending_turn.input_tokens = input_tokens
                    pending_turn.output_tokens = output_tokens
                    turns.append(pending_turn)
                    pending_turn = None
                else:
                    turns.append(Turn(
                        timestamp=ts,
                        human_input=None,
                        assistant_response=response_text,
                        tool_calls=tool_calls,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    ))

            elif ltype == "summary":
                compaction_events.append(line)

            # tool_result lines are skipped; the tool call is already
            # captured from the preceding assistant message's content blocks.

        if pending_turn is not None:
            turns.append(pending_turn)

        return Session(
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            file_path=path,
            turns=turns,
            compaction_events=compaction_events,
        )

    def list_all_sessions(self) -> List[Session]:
        return [
            self.read_session(jsonl_file)
            for jsonl_file in sorted(self._directory.glob("*.jsonl"))
        ]

    def sessions_in_range(
        self,
        start: datetime.date,
        end: datetime.date,
    ) -> List[Session]:
        if start > end:
            return []
        return [
            s for s in self.list_all_sessions()
            if start <= s.start_time.date() <= end
        ]
