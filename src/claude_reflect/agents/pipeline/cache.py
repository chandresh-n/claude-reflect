"""Per-stage cache for the evaluator pipeline.

Caches are written to ``<repo>/.claude-reflect/eval-cache/stage-<id>/<key>.json``.
The key derives from ``(stage_id, model, prompt_version, content)`` so:

  - Each stage has an isolated namespace (no collisions across stages).
  - Bumping ``prompt_version`` for one stage invalidates only that stage.
  - Changing the input content for a single turn / window / session
    invalidates only that entry.

The cache is append-only on disk: ``.set`` writes a new file; entries
under stale keys remain as orphans rather than being destructively
removed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional


def cache_key(
    *,
    stage_id: str,
    model: str,
    prompt_version: str,
    content: Any,
) -> str:
    """Stable hash of the four cache-key components.

    Any change to any of ``stage_id``, ``model``, ``prompt_version`` or
    ``content`` shifts the key. ``content`` is serialised with sorted
    keys so dict ordering is not part of the identity.
    """
    payload = {
        "stage_id": stage_id,
        "model": model,
        "prompt_version": prompt_version,
        "content": content,
    }
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class StageCache:
    """JSON-on-disk cache for a single pipeline stage."""

    def __init__(self, repo: Path, stage_id: str) -> None:
        self._repo = Path(repo)
        self._stage_id = stage_id
        self._dir = (
            self._repo / ".claude-reflect" / "eval-cache" / f"stage-{stage_id}"
        )

    def _path_for(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def get(self, key: str) -> Optional[Any]:
        # CLAUDE_REFLECT_NO_CACHE forces a cache miss across every stage,
        # honoured here so the CLI's --no-cache flag does not need to thread
        # an extra parameter through every stage signature. Writes are
        # unaffected so later runs still benefit from this run's outputs.
        if os.environ.get("CLAUDE_REFLECT_NO_CACHE"):
            return None
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, key: str, value: Any) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path_for(key).write_text(
            json.dumps(value, sort_keys=False, default=str),
            encoding="utf-8",
        )
