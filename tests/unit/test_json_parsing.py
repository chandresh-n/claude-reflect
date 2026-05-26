"""
Unit tests for the shared tolerant JSON extractor.

Pins the recovery strategies used by the evaluator, proposer, and author
to handle preamble prose and ```json``` code fences in model output.
"""
from __future__ import annotations

import json

import pytest

from claude_reflect.agents._json_parsing import extract_json


def test_direct_json_object() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_direct_json_with_whitespace() -> None:
    assert extract_json('  \n {"a": 1}\n  ') == {"a": 1}


def test_fenced_json_no_preamble() -> None:
    raw = "```json\n{\"a\": 1}\n```"
    assert extract_json(raw) == {"a": 1}


def test_fenced_json_unlabeled() -> None:
    raw = "```\n{\"a\": 1}\n```"
    assert extract_json(raw) == {"a": 1}


def test_fenced_json_with_preamble_prose() -> None:
    """Regression: model emits prose before the fence; parser must recover.

    This mirrors the real failure mode where Opus prepended
    'The tools available are Gmail, Calendar, and Drive...' before
    a ```json``` block.
    """
    raw = (
        "The tools available are Gmail, Calendar, and Drive - none of "
        "which are needed for this task. Let me produce the proposal "
        "batch.\n\n"
        "```json\n"
        '{"batch_id": "batch-001", "proposals": [{"id": "p1"}]}\n'
        "```"
    )
    out = extract_json(raw)
    assert out == {"batch_id": "batch-001", "proposals": [{"id": "p1"}]}


def test_fenced_json_with_trailing_prose() -> None:
    raw = (
        "```json\n"
        '{"a": 1}\n'
        "```\n\n"
        "Let me know if you need anything else."
    )
    assert extract_json(raw) == {"a": 1}


def test_brace_fallback_when_no_fence() -> None:
    raw = "Here is the result: {\"a\": 1} — that's all."
    assert extract_json(raw) == {"a": 1}


def test_invalid_json_raises_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json("not json at all, just prose")


def test_invalid_json_inside_fence_raises() -> None:
    raw = "```json\n{not valid}\n```"
    with pytest.raises(json.JSONDecodeError):
        extract_json(raw)


def test_array_top_level() -> None:
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_nested_braces_are_handled() -> None:
    """Brace-fallback uses last '}' so nested objects parse correctly."""
    raw = "Preamble {\"a\": {\"b\": 1}, \"c\": [{\"d\": 2}]} trailing"
    assert extract_json(raw) == {"a": {"b": 1}, "c": [{"d": 2}]}
