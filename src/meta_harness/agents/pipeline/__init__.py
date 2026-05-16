"""Evaluator pipeline: staged refactor of the single-call evaluator.

Stage 1a (per-turn description), 1b (per-window pass observation), 2
(session-level pass refinement), 3 (session narrative), 4 (cross-session
gap observations) are wired through a pluggable ``Runner`` abstraction
and cached per-stage under ``.meta-harness/eval-cache/stage-<id>/``.

Spec: docs/spec/03-agents/evaluator.md
"""
