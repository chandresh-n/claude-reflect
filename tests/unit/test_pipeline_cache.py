"""
Session A failing-gate tests for step 13 — per-stage cache.

The pipeline caches each stage's output independently so that a re-run
costs nothing for unchanged inputs and a bumped prompt invalidates only
the affected stage's cache.  Pins:

  - ``cache_key(stage_id, model, prompt_version, content)`` is stable
    and varies on each of those four components.
  - ``StageCache`` exposes ``get``/``set`` that persist under
    ``.claude-reflect/eval-cache/stage-<id>/<key>.json``.
  - A bumped ``prompt_version`` is functionally an invalidation —
    new key, no hit on prior entries.

Expected to FAIL on import until step 13 lands the module.
"""
from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# cache_key: stable + sensitive to every input
# ---------------------------------------------------------------------------


def test_cache_key_is_stable_for_identical_inputs() -> None:
    from claude_reflect.agents.pipeline.cache import cache_key  # type: ignore

    a = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v1", content={"x": 1})
    b = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v1", content={"x": 1})
    assert a == b
    assert isinstance(a, str) and len(a) >= 8


def test_cache_key_changes_when_model_changes() -> None:
    from claude_reflect.agents.pipeline.cache import cache_key  # type: ignore

    a = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v1", content={"x": 1})
    b = cache_key(stage_id="1a", model="claude-sonnet-4-6",
                  prompt_version="v1", content={"x": 1})
    assert a != b


def test_cache_key_changes_when_prompt_version_changes() -> None:
    """Bumping prompt_version is the canonical way to invalidate a
    stage's cache after evolving its prompt.  This MUST change the key."""
    from claude_reflect.agents.pipeline.cache import cache_key  # type: ignore

    a = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v1", content={"x": 1})
    b = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v2", content={"x": 1})
    assert a != b


def test_cache_key_changes_when_content_changes() -> None:
    from claude_reflect.agents.pipeline.cache import cache_key  # type: ignore

    a = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v1", content={"x": 1})
    b = cache_key(stage_id="1a", model="claude-opus-4-6",
                  prompt_version="v1", content={"x": 2})
    assert a != b


def test_cache_key_changes_when_stage_id_changes() -> None:
    """Each stage has its own cache namespace; stage_id is part of the key."""
    from claude_reflect.agents.pipeline.cache import cache_key  # type: ignore

    a = cache_key(stage_id="1a", model="m", prompt_version="v1", content={"x": 1})
    b = cache_key(stage_id="1b", model="m", prompt_version="v1", content={"x": 1})
    assert a != b


# ---------------------------------------------------------------------------
# StageCache: persist + read back
# ---------------------------------------------------------------------------


def test_stage_cache_miss_returns_none(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.cache import StageCache  # type: ignore

    cache = StageCache(repo=tmp_path, stage_id="1a")
    assert cache.get("nonexistent-key") is None


def test_stage_cache_set_then_get_roundtrips_json(tmp_path: Path) -> None:
    from claude_reflect.agents.pipeline.cache import StageCache  # type: ignore

    cache = StageCache(repo=tmp_path, stage_id="1a")
    value = {"session_id": "s1", "turn_index": 0, "goal_signal": "hi"}
    cache.set("k1", value)
    assert cache.get("k1") == value


def test_stage_cache_writes_to_expected_filesystem_location(tmp_path: Path) -> None:
    """The cache file MUST land at:
        <repo>/.claude-reflect/eval-cache/stage-<id>/<key>.json
    Other components and downstream tooling depend on this layout."""
    from claude_reflect.agents.pipeline.cache import StageCache  # type: ignore

    cache = StageCache(repo=tmp_path, stage_id="2")
    cache.set("abcdef", {"hello": "world"})

    expected = (
        tmp_path / ".claude-reflect" / "eval-cache" / "stage-2" / "abcdef.json"
    )
    assert expected.is_file(), f"Expected cache file at {expected}"
    assert json.loads(expected.read_text(encoding="utf-8")) == {"hello": "world"}


def test_stage_cache_namespaces_isolated_between_stages(tmp_path: Path) -> None:
    """Stage 1a and stage 2 with the same key string must not collide —
    they live in separate directories."""
    from claude_reflect.agents.pipeline.cache import StageCache  # type: ignore

    c1a = StageCache(repo=tmp_path, stage_id="1a")
    c2 = StageCache(repo=tmp_path, stage_id="2")
    c1a.set("samekey", {"who": "1a"})
    c2.set("samekey", {"who": "2"})
    assert c1a.get("samekey") == {"who": "1a"}
    assert c2.get("samekey") == {"who": "2"}


def test_bumping_prompt_version_invalidates_old_cache(tmp_path: Path) -> None:
    """End-to-end invalidation flow: set under v1, look up under v2 → miss.

    The point of including prompt_version in cache_key is exactly that we
    never have to manually rm -rf the cache when a prompt changes — the
    key shifts and the old entry simply becomes an orphan."""
    from claude_reflect.agents.pipeline.cache import (  # type: ignore
        StageCache, cache_key,
    )

    cache = StageCache(repo=tmp_path, stage_id="1a")
    content = {"session_id": "s1", "turn_index": 0}

    k_v1 = cache_key(stage_id="1a", model="m",
                     prompt_version="v1", content=content)
    k_v2 = cache_key(stage_id="1a", model="m",
                     prompt_version="v2", content=content)
    assert k_v1 != k_v2

    cache.set(k_v1, {"saved": "under v1"})
    assert cache.get(k_v1) == {"saved": "under v1"}
    # Same content, bumped prompt_version → miss.
    assert cache.get(k_v2) is None
