"""
Session A failing-gate regression test for step 15 — old evaluator
cutover.

The step-15 cutover removes the pre-pipeline batching code paths
from the single-call evaluator and forbids the old conversational
``Human:`` / ``Assistant:`` prompt shape from appearing anywhere
under ``src/meta_harness/agents/pipeline/``. It also pins the gap-
record append-only invariant: stage 4 must never call a deletion
verb on gap-record files.

Pins (HARD — from docs/PLAN.md Step 15):

  - the symbols ``_split_into_batches``, ``_chunk_large_sessions``,
    ``_evaluate_batch``, ``_format_sessions_for_prompt``, and
    ``_build_batch_prompt`` are absent from every file under
    ``src/``
  - the regex ``Human:`` followed by newline and ``Assistant:`` is
    absent from every file under ``src/meta_harness/agents/pipeline/``
  - no pipeline module (other than ``runner.py``) imports
    ``claude_runner``
  - pipeline modules do not call destructive gap-record operations
    (``unlink``, ``rmtree``, ``os.remove``) against
    ``.meta-harness/gaps/``
  - the matched-gap-id merge rule is exercised end-to-end via stage 4
    (covered in detail in ``test_pipeline_stage_4.py``; this file
    asserts the static-scan portion)

Expected to FAIL on the symbol-removal scan because the old
batching code still lives in ``src/meta_harness/agents/evaluator.py``
until step 15's implementation lands.
"""
from __future__ import annotations

import re
from pathlib import Path


# Resolve the src/ tree from the test file's own location.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"
_PIPELINE_DIR = _SRC_DIR / "meta_harness" / "agents" / "pipeline"


_FORBIDDEN_SYMBOLS = (
    "_split_into_batches",
    "_chunk_large_sessions",
    "_evaluate_batch",
    "_format_sessions_for_prompt",
    "_build_batch_prompt",
)


def _iter_src_python_files() -> list[Path]:
    return sorted(p for p in _SRC_DIR.rglob("*.py") if p.is_file())


def _iter_pipeline_python_files() -> list[Path]:
    return sorted(p for p in _PIPELINE_DIR.rglob("*.py") if p.is_file())


def _require_new_modules_present() -> None:
    """Trigger the cutover precondition. Every assertion in this file
    depends on the step-15 implementation having landed, so before any
    static-scan check we require ``stage_4`` and ``orchestrator`` to
    exist. This is what makes every test in this file fail at Session A
    time and turn green only once Session B has done the cutover work.
    """
    from meta_harness.agents.pipeline import stage_4  # type: ignore  # noqa: F401
    from meta_harness.agents.pipeline import orchestrator  # type: ignore  # noqa: F401


# ---------------------------------------------------------------------------
# Old batching symbols — must be removed from src/
# ---------------------------------------------------------------------------


def test_old_batching_symbols_absent_from_src() -> None:
    _require_new_modules_present()
    """The pre-pipeline batching helpers must be gone from src/.
    They are replaced by the staged pipeline.
    """
    offenders: dict[str, list[str]] = {}
    for path in _iter_src_python_files():
        text = path.read_text(encoding="utf-8")
        hits = [sym for sym in _FORBIDDEN_SYMBOLS if sym in text]
        if hits:
            offenders[str(path.relative_to(_REPO_ROOT))] = hits

    assert not offenders, (
        "Step 15 cutover requires the old batching code to be removed. "
        "These files still mention forbidden batching symbols:\n  "
        + "\n  ".join(
            f"{p}: {syms}" for p, syms in offenders.items()
        )
    )


# ---------------------------------------------------------------------------
# Conversational prompt shape — must be absent from pipeline/
# ---------------------------------------------------------------------------


_CONVERSATIONAL_PROMPT_RE = re.compile(
    r"Human:\s*\n\s*Assistant:", re.MULTILINE,
)


def test_conversational_prompt_shape_absent_from_pipeline() -> None:
    """The old ``Human:\\nAssistant:`` framing causes Claude to read
    user prompts as transcripts to continue. Pipeline modules must
    use XML-tag framing instead (per the existing stage prompts)."""
    _require_new_modules_present()
    offenders: list[str] = []
    for path in _iter_pipeline_python_files():
        text = path.read_text(encoding="utf-8")
        if _CONVERSATIONAL_PROMPT_RE.search(text):
            offenders.append(str(path.relative_to(_REPO_ROOT)))

    assert not offenders, (
        "The Human:/Assistant: conversational prompt shape must not "
        "appear in any pipeline module:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Runner-isolation guardrail
# ---------------------------------------------------------------------------


def test_only_runner_module_imports_claude_runner() -> None:
    """Pipeline isolation: only ``runner.py`` may import
    ``claude_runner``. Every other pipeline module talks to the
    abstract ``Runner``."""
    _require_new_modules_present()
    offenders: list[str] = []
    for path in _iter_pipeline_python_files():
        if path.name == "runner.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "claude_runner" in text:
            offenders.append(str(path.relative_to(_REPO_ROOT)))

    assert not offenders, (
        "Only pipeline/runner.py may import claude_runner; offenders:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Gap-record append-only guardrail
# ---------------------------------------------------------------------------


_DESTRUCTIVE_OP_RE = re.compile(
    r"(?:Path\([^)]*\)|gap[^=\n]*?\.json[^=\n]*?)\.unlink"
    r"|shutil\.rmtree"
    r"|os\.remove"
    r"|os\.unlink",
)


def test_pipeline_does_not_call_destructive_gap_record_ops() -> None:
    """Append-only invariant: the pipeline must never call a deletion
    verb on a gap-record file. This is a static scan; full semantic
    coverage is in ``test_pipeline_stage_4.py``."""
    _require_new_modules_present()
    offenders: list[tuple[str, str]] = []
    for path in _iter_pipeline_python_files():
        text = path.read_text(encoding="utf-8")
        for m in _DESTRUCTIVE_OP_RE.finditer(text):
            offenders.append(
                (str(path.relative_to(_REPO_ROOT)), m.group(0))
            )

    assert not offenders, (
        "Pipeline modules must not call destructive gap-record "
        "operations; offenders:\n  "
        + "\n  ".join(f"{p}: {op}" for p, op in offenders)
    )


# ---------------------------------------------------------------------------
# Public surface — evaluator.evaluate must remain callable
# ---------------------------------------------------------------------------


def test_evaluator_evaluate_remains_callable_after_cutover() -> None:
    """The run loop calls ``evaluator.evaluate(sessions, repo)`` at
    Phase 4. The cutover replaces the implementation but the public
    function name must remain importable so existing callers do not
    break."""
    _require_new_modules_present()
    from meta_harness.agents import evaluator  # type: ignore

    assert hasattr(evaluator, "evaluate"), (
        "meta_harness.agents.evaluator.evaluate must remain importable "
        "after the step-15 cutover so the run loop's Phase 4 call site "
        "is not stranded."
    )
    assert callable(evaluator.evaluate)


# ---------------------------------------------------------------------------
# Orchestrator presence
# ---------------------------------------------------------------------------


def test_orchestrator_module_present_in_pipeline_package() -> None:
    """The new pipeline orchestrator module must exist after the
    cutover."""
    orchestrator_path = _PIPELINE_DIR / "orchestrator.py"
    assert orchestrator_path.is_file(), (
        f"Step 15 cutover must land the orchestrator at "
        f"{orchestrator_path}"
    )


def test_stage_4_module_present_in_pipeline_package() -> None:
    """Stage 4 module must exist after step 15."""
    stage_4_path = _PIPELINE_DIR / "stage_4.py"
    assert stage_4_path.is_file(), (
        f"Step 15 must land stage 4 at {stage_4_path}"
    )
