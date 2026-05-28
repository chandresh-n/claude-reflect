"""
Tolerant JSON extraction from model responses.

Models occasionally precede their JSON output with prose ("Let me produce
the proposal batch.") and/or wrap it in a ```json``` fence even when the
system prompt says "no markdown wrapping". The naive ``json.loads`` on the
raw response then fails at character 0 on the prose. This helper centralises
the recovery strategy used by the evaluator, proposer, and author so all
three behave the same way.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def _try_repair(candidate: str) -> Optional[Any]:
    """Best-effort structural repair of malformed JSON via ``json_repair``.

    Recovers common LLM defects that the strict strategies cannot — most
    importantly an unescaped double-quote inside a string value (which ends
    the string early and breaks the rest of a multi-thousand-token batch),
    plus trailing commas and stray control characters.

    Only a repaired top-level **object** (non-empty dict) is accepted: every
    agent using this extractor expects an object, and ``json_repair`` will
    otherwise happily turn non-JSON prose into an empty string or coerce
    garbage into a junk list, which must not be passed off as a successful
    parse. Returns the repaired dict, or ``None`` when ``json_repair`` is
    unavailable or does not yield a usable object.
    """
    try:
        from json_repair import repair_json
    except ImportError:
        return None
    try:
        obj = repair_json(candidate, return_objects=True)
    except Exception:
        return None
    if isinstance(obj, dict) and obj:
        return obj
    return None


def extract_json(raw_text: str) -> Any:
    """Parse JSON from a model response, tolerant of preamble, fences, and
    common structural defects.

    Strategies tried in order:
      1. Direct ``json.loads`` on the trimmed text.
      2. First ```...``` fenced block (with or without ``json`` tag) found
         anywhere in the text — handles preamble prose before the fence.
      3. Substring from the first ``{`` to the last ``}`` — last-resort
         extraction when prose surrounds bare JSON without a fence.
      4. Structural repair via ``json_repair`` (accepting only a repaired
         object), which recovers defects the strict parser rejects — e.g. an
         unescaped quote inside a string value. Non-JSON prose still raises.

    Raises ``json.JSONDecodeError`` from the most recent failure if no
    strategy succeeds.
    """
    text = raw_text.strip()
    last_err: Optional[json.JSONDecodeError] = None

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        last_err = e

    fence = _FENCE_RE.search(text)
    if fence is not None:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError as e:
            last_err = e

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError as e:
            last_err = e

    # 4. Structural repair as a last resort. Try the brace substring first
    #    (prose stripped), then the full text, then any fenced block.
    for candidate in (
        text[first:last + 1] if first != -1 and last > first else None,
        text,
        fence.group(1) if fence is not None else None,
    ):
        if candidate is None:
            continue
        repaired = _try_repair(candidate)
        if repaired is not None:
            return repaired

    assert last_err is not None  # at least the direct attempt failed
    raise last_err
