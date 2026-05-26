"""
Shared pytest fixtures for the claude-reflect test suite.
"""
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """
    A temporary directory initialized as a git repository with a single
    commit on the default branch.

    Provides a clean, isolated git repo for tests that need to call setup()
    and inspect the resulting .claude-reflect/ state and git branches.
    """
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    # An initial commit is required so that HEAD resolves to a real branch
    # (e.g., "main" or "master") before setup() runs.
    readme = tmp_path / "README.md"
    readme.write_text("# Test repository\n")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path
