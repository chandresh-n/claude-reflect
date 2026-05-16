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


def extract_json(raw_text: str) -> Any:
    """Parse JSON from a model response, tolerant of preamble and fences.

    Strategies tried in order:
      1. Direct ``json.loads`` on the trimmed text.
      2. First ```...``` fenced block (with or without ``json`` tag) found
         anywhere in the text — handles preamble prose before the fence.
      3. Substring from the first ``{`` to the last ``}`` — last-resort
         extraction when prose surrounds bare JSON without a fence.

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

    assert last_err is not None  # at least the direct attempt failed
    raise last_err
