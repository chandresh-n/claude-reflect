"""Pluggable Runner abstraction.

Only this module in the pipeline package is allowed to import
``claude_runner``. Other pipeline modules talk to the ``Runner``
abstraction so a future swap to a local-model runner is a one-file
change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from claude_reflect.agents import claude_runner


class Runner(ABC):
    """Abstract model runner. One ``.invoke`` call == one model invocation."""

    @abstractmethod
    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        **kwargs,
    ) -> str:
        ...


class ClaudeCLIRunner(Runner):
    """Runner backed by ``claude -p`` via ``claude_runner.invoke_claude``."""

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        *,
        label: Optional[str] = None,
        log_dir: Optional[Path] = None,
        **kwargs,
    ) -> str:
        return claude_runner.invoke_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            label=label,
            log_dir=log_dir,
            **kwargs,
        )
