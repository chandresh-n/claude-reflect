"""
Session A failing-gate tests for step 13 — pluggable Runner abstraction.

The pipeline must talk to *a* model runner, not specifically to
``claude_runner.invoke_claude``.  This file pins:

  - ``claude_reflect.agents.pipeline.runner.Runner`` is a swappable
    abstraction with a single public method ``.invoke(...)``.
  - A ``ClaudeCLIRunner`` exists and is one concrete implementation,
    wrapping ``claude_runner.invoke_claude`` without leaking it to
    callers.
  - Pipeline modules (other than the runner module itself) do NOT
    import ``claude_runner`` directly — that's how swappability is
    enforced architecturally, not just by convention.

These tests are expected to FAIL on collection because the pipeline
package does not exist yet.  That's the gate.  Session B implements
``claude_reflect.agents.pipeline.runner`` and re-runs this file until
green.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_runner_protocol_is_importable_and_has_invoke() -> None:
    """The Runner abstraction is importable and exposes a callable
    ``.invoke(system_prompt, user_prompt, model, ...)``."""
    from claude_reflect.agents.pipeline.runner import Runner  # type: ignore

    # Runner is an abstract base or Protocol with an invoke method.
    assert hasattr(Runner, "invoke"), (
        "Runner must expose an .invoke method as its public contract."
    )

    sig = inspect.signature(Runner.invoke)
    params = set(sig.parameters.keys()) - {"self"}
    # The minimum surface: system_prompt + user_prompt + model.  Optional
    # extras (label, log_dir, etc.) are fine and remain forward-compatible.
    required = {"system_prompt", "user_prompt", "model"}
    assert required <= params, (
        f"Runner.invoke must accept at least {required}; got params {params}."
    )


def test_claude_cli_runner_exists_and_implements_runner() -> None:
    """ClaudeCLIRunner is one concrete Runner implementation."""
    from claude_reflect.agents.pipeline.runner import (  # type: ignore
        ClaudeCLIRunner,
        Runner,
    )

    runner = ClaudeCLIRunner()
    assert isinstance(runner, Runner), (
        "ClaudeCLIRunner must be a Runner (subclass or Protocol-compatible)."
    )
    assert hasattr(runner, "invoke") and callable(runner.invoke)


@patch("claude_reflect.agents.claude_runner.invoke_claude")
def test_claude_cli_runner_delegates_to_invoke_claude(
    mock_invoke: MagicMock,
) -> None:
    """ClaudeCLIRunner.invoke must delegate to claude_runner.invoke_claude.

    Other runner implementations (e.g. a local-model runner) replace
    this delegation entirely; pipeline code stays unchanged.
    """
    from claude_reflect.agents.pipeline.runner import ClaudeCLIRunner  # type: ignore

    mock_invoke.return_value = "model said this"
    runner = ClaudeCLIRunner()
    out = runner.invoke(
        system_prompt="you are a helper",
        user_prompt="say hi",
        model="claude-opus-4-6",
    )

    assert out == "model said this"
    mock_invoke.assert_called_once()
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs.get("system_prompt") == "you are a helper"
    assert kwargs.get("user_prompt") == "say hi"
    assert kwargs.get("model") == "claude-opus-4-6"


def test_runner_swappability_via_custom_subclass() -> None:
    """A test-only Runner subclass must work without any pipeline
    code change — that's swappability.  Confirms the contract is
    duck-typed, not name-typed."""
    from claude_reflect.agents.pipeline.runner import Runner  # type: ignore

    class FakeRunner(Runner):  # type: ignore[misc]
        def invoke(self, system_prompt, user_prompt, model, **kwargs):
            return f"fake[{model}]: {user_prompt[:8]}"

    fr = FakeRunner()
    out = fr.invoke(
        system_prompt="sp",
        user_prompt="hello world",
        model="test-model",
    )
    assert out == "fake[test-model]: hello wo"


def test_pipeline_modules_do_not_import_claude_runner_directly() -> None:
    """Architectural test: only the runner module may import
    claude_runner.  Every other pipeline module must talk to the
    Runner abstraction.  This is what makes a future swap to a
    local model a single-file change."""
    pipeline_dir = (
        Path(__file__).resolve().parents[2]
        / "src" / "claude_reflect" / "agents" / "pipeline"
    )
    assert pipeline_dir.is_dir(), (
        f"Pipeline package missing at {pipeline_dir}.  Step 13 creates it."
    )

    violations: list[str] = []
    for py in pipeline_dir.glob("*.py"):
        if py.name == "runner.py":
            continue  # the one allowed importer
        src = py.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if "claude_runner" in mod:
                    violations.append(f"{py.name} imports from {mod}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "claude_runner" in alias.name:
                        violations.append(f"{py.name} imports {alias.name}")

    assert not violations, (
        "Only pipeline/runner.py may import claude_runner. "
        "Violations:\n  - " + "\n  - ".join(violations)
    )
