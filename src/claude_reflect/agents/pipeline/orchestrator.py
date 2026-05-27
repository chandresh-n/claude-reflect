"""Evaluator pipeline orchestrator.

``evaluate(sessions, repo, model, ...)`` sequences the five stages of
the evaluator pipeline:

  1a — per-turn description (per-turn cache).
  1b — windowed per-turn observations + draft pass classifications
       (per-session cache).
  2  — per-session refinement of pass classifications.
  3  — per-session narrative (carries the partial-completion flag).
  4  — cross-session gap observations + gap-record side effects
       (corpus cache).

Per-stage caching means that a re-run with identical inputs makes
ZERO model calls (every stage hits its per-stage cache). Adding one
new session to the window only re-runs that session's 1a/1b/2/3 plus
the corpus-level stage 4.

Partial-results-survive-failure: every stage is wrapped so a single
failure does not discard the whole evaluator output. Stage 1a/1b mark
the affected session ``partial_completion=True``. Stage 2/3/4 catch
the failure, log it to the stage artefact, and contribute empty
output for the failed slice — the rest of the pipeline runs to
completion, and the cache holds whatever did succeed so the next run
picks up from where it stopped.

Progress for each invocation lands under
``<repo>/.claude-reflect/logs/eval/<UTC-timestamp>/stages/<stage_id>/``
as a small JSON artefact per stage. The directory is created
deterministically per run; callers can override ``log_dir``.

Spec: docs/spec/03-agents/evaluator.md and
docs/spec/01-data-structures/evaluator-output.md.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from claude_reflect.agents.pipeline.runner import ClaudeCLIRunner, Runner
from claude_reflect.agents.pipeline.stage_1a import describe_session_turns
from claude_reflect.agents.pipeline.stage_1b import observe_session_windows
from claude_reflect.agents.pipeline.stage_2 import refine_session_passes
from claude_reflect.agents.pipeline.stage_3 import summarize_session
from claude_reflect.agents.pipeline.stage_4 import identify_corpus_gaps
from claude_reflect.storage.session_logs import Session


def _safe_id(identifier: str) -> str:
    return identifier.replace("/", "_").replace(":", "_") or "anon"


def _write_stage_artefact(stages_dir: Path, stage_id: str,
                          identifier: str, payload: dict) -> None:
    stage_dir = stages_dir / f"stage-{stage_id}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / f"{_safe_id(identifier)}.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=str),
        encoding="utf-8",
    )


def evaluate(
    *,
    sessions: List[Session],
    repo: Path,
    model: str = "claude-opus-4-7",
    runner: Optional[Runner] = None,
    write_gap_records: bool = True,
    log_dir: Optional[Path] = None,
    stage_1a_model: Optional[str] = None,
    max_concurrent_turn_descriptions: int = 1,
    max_concurrent_sessions: int = 1,
) -> dict:
    """Run the staged evaluator pipeline over ``sessions``.

    Returns a document with exactly the four spec keys:
    ``per_turn_observations``, ``pass_classifications``,
    ``gap_observations``, ``session_narratives``.

    Args:
        model: Default model for every stage.
        stage_1a_model: Optional override for stage 1a (per-turn
            description), which runs once per turn and benefits from a
            smaller, cheaper model. Falls back to ``model`` if None.
        max_concurrent_turn_descriptions: Ceiling on parallel stage-1a
            calls *within one session*. The default of 1 preserves the
            historical sequential behavior; values >1 fan the per-turn
            describer out to a bounded thread pool. Results are
            re-ordered by turn_index before returning so downstream
            stages always see temporal sequence.
        max_concurrent_sessions: Ceiling on parallel session pipelines
            (stages 1a → 1b → 2 → 3). Each session's pipeline runs
            sequentially internally; sessions run concurrently. Stage 4
            (corpus-level) remains serial because it must see every
            session's output. Worst-case process fanout is
            max_concurrent_sessions * max_concurrent_turn_descriptions.
    """
    if runner is None:
        runner = ClaudeCLIRunner()
    if stage_1a_model is None:
        stage_1a_model = model

    if log_dir is None:
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        log_dir = repo / ".claude-reflect" / "logs" / "eval" / run_ts
    stages_dir = log_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    per_turn_observations_all: list[dict] = []
    pass_classifications_all: list[dict] = []
    narratives_all: list[dict] = []

    def _process_session(session: Session) -> tuple[list, list, dict]:
        """Run stages 1a → 1b → 2 → 3 for a single session. Returns
        (session_observations, classifications, narrative). Closes
        over the outer scope's runner/repo/model parameters so the
        per-session worker stays a pure function of `session`.

        Internally sequential: 1b depends on 1a, 2 depends on 1b,
        3 depends on 2. Stage 4 (corpus-level) runs once after every
        session has finished here, so this helper never touches it.
        """
        sid = session.session_id

        # --- Stage 1a: per-turn description (per-turn failure isolated)
        descriptions = describe_session_turns(
            session=session, runner=runner, repo=repo, model=stage_1a_model,
            max_concurrent=max_concurrent_turn_descriptions,
        )
        stage_1a_failures = [
            d for d in descriptions
            if isinstance(d, dict) and d.get("_failed")
        ]
        valid_descs = [
            d for d in descriptions
            if isinstance(d, dict) and not d.get("_failed")
        ]
        _write_stage_artefact(stages_dir, "1a", sid, {
            "session_id": sid,
            "turn_count": len(session.turns),
            "described_count": len(valid_descs),
            "failed_turns": [d.get("turn_index") for d in stage_1a_failures],
        })

        # --- Stage 1b: windowed observations + draft pass classifications
        windowed = observe_session_windows(
            session_id=sid,
            descriptions=valid_descs,
            runner=runner,
            repo=repo,
            model=model,
        )
        session_observations: list[dict] = windowed.get(
            "per_turn_observations", []
        ) or []
        drafts: list[dict] = windowed.get(
            "draft_pass_classifications", []
        ) or []
        partial_completion = (
            bool(stage_1a_failures)
            or bool(windowed.get("partial_completion"))
            or bool(windowed.get("failed_windows"))
        )
        _write_stage_artefact(stages_dir, "1b", sid, {
            "session_id": sid,
            "observation_count": len(session_observations),
            "draft_count": len(drafts),
            "partial_completion": partial_completion,
            "failed_windows": windowed.get("failed_windows", []),
        })

        # --- Stage 2: per-session pass refinement
        # Skip the model call when there are no drafts (1b fully failed)
        # — there is nothing for the refiner to refine.
        stage_2_error: Optional[str] = None
        if drafts:
            try:
                classifications = refine_session_passes(
                    session_id=sid,
                    drafts=drafts,
                    total_turns=len(session.turns),
                    runner=runner,
                    repo=repo,
                    model=model,
                )
            except Exception as exc:
                stage_2_error = f"{type(exc).__name__}: {exc}"
                classifications = []
                partial_completion = True
                print(
                    f"  [orchestrator] stage 2 failed for {sid}: {stage_2_error} — "
                    f"continuing with empty classifications for this session.",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            classifications = []
        _write_stage_artefact(stages_dir, "2", sid, {
            "session_id": sid,
            "pass_count": len(classifications),
            "skipped": not drafts,
            "error": stage_2_error,
        })

        # --- Stage 3: per-session narrative (carries partial flag)
        stage_3_error: Optional[str] = None
        try:
            narrative = summarize_session(
                session_id=sid,
                per_turn_observations=session_observations,
                pass_classifications=classifications,
                gap_observations=[],
                runner=runner,
                repo=repo,
                model=model,
                partial_completion=partial_completion,
            )
        except Exception as exc:
            stage_3_error = f"{type(exc).__name__}: {exc}"
            narrative = {
                "session_id": sid,
                "narrative": "",
                "partial_completion": True,
                "error": stage_3_error,
            }
            print(
                f"  [orchestrator] stage 3 failed for {sid}: {stage_3_error} — "
                f"continuing with empty narrative for this session.",
                file=sys.stderr,
                flush=True,
            )
        _write_stage_artefact(stages_dir, "3", sid, {
            "session_id": sid,
            "partial_completion": partial_completion,
            "error": stage_3_error,
        })

        return session_observations, classifications, narrative

    # Dispatch the per-session work either sequentially (default) or
    # in a bounded thread pool. ex.map preserves submission order so
    # the aggregated lists are deterministic across runs even when the
    # underlying calls return out of order.
    if max_concurrent_sessions <= 1 or len(sessions) <= 1:
        session_outputs = [_process_session(s) for s in sessions]
    else:
        from concurrent.futures import ThreadPoolExecutor
        workers = min(max_concurrent_sessions, len(sessions))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            session_outputs = list(ex.map(_process_session, sessions))

    for session_observations, classifications, narrative in session_outputs:
        per_turn_observations_all.extend(session_observations)
        pass_classifications_all.extend(classifications)
        narratives_all.append(narrative)

    # --- Stage 4: corpus-level gap observations + gap-record side effects
    stage_4_error: Optional[str] = None
    try:
        gap_observations = identify_corpus_gaps(
            per_turn_observations=per_turn_observations_all,
            pass_classifications=pass_classifications_all,
            session_narratives=narratives_all,
            runner=runner,
            repo=repo,
            model=model,
            write_gap_records=write_gap_records,
        )
    except Exception as exc:
        stage_4_error = f"{type(exc).__name__}: {exc}"
        gap_observations = []
        print(
            f"  [orchestrator] stage 4 failed: {stage_4_error} — "
            f"returning partial evaluator output (no corpus gap observations). "
            f"Re-run to retry; stages 1-3 are cached.",
            file=sys.stderr,
            flush=True,
        )
    _write_stage_artefact(stages_dir, "4", "corpus", {
        "gap_observation_count": len(gap_observations),
        "error": stage_4_error,
    })

    return {
        "per_turn_observations": per_turn_observations_all,
        "pass_classifications": pass_classifications_all,
        "gap_observations": gap_observations,
        "session_narratives": narratives_all,
    }
