"""
Step 1 gate — Knowledge base & setup script (HARD gate): Unit tests.

Spec refs:
  docs/spec/02-storage/knowledge-base.md
  docs/spec/04-processes/run-loop.md  (Phase 1 only)
  docs/IMPLEMENTATION.md § "Storage layout"
  docs/IMPLEMENTATION.md § "Configuration file"
  docs/IMPLEMENTATION.md § "Default models"

Gate criteria verified here (from docs/PLAN.md, Step 1):
  1. Directory layout matches the spec.
  3. config has every required field with correct defaults.

Tests are intentionally narrow: each test asserts one factual claim from the
spec. No test checks more than one structural or type constraint at a time.

All tests must FAIL before implementation exists (Session A gate criterion).
"""
from pathlib import Path

import pytest
import yaml

from claude_reflect.storage.knowledge_base import setup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def kb(repo: Path) -> Path:
    """Return the .claude-reflect/ root path."""
    return repo / ".claude-reflect"


def cfg(repo: Path) -> dict:
    """Load and return the parsed config.yaml."""
    config_path = kb(repo) / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Required keys from IMPLEMENTATION.md § "Configuration file"
# ---------------------------------------------------------------------------

# Note: ``models`` is intentionally absent from this list. Per the c5
# iteration, kb_setup leaves the models section out so the first review
# pass can route through the interactive picker (or the non-TTY
# fallback). The TestConfigModels class below pins that new contract.
REQUIRED_TOP_LEVEL_KEYS = [
    "maintenance",
    "stale_gap_threshold_sessions",
    "forced_novelty",
    "window_warnings",
    "logging",
]

REQUIRED_MODEL_KEYS = ["evaluator", "proposer", "author"]

REQUIRED_THRESHOLD_KEYS = [
    "new_sessions",
    "new_decisions",
    "new_gap_records",
    "days_since_last",
]

REQUIRED_FORCED_NOVELTY_KEYS = ["probability", "null_baseline_probability"]

REQUIRED_WINDOW_WARNING_KEYS = [
    "small_window_threshold_sessions",
    "large_window_threshold_sessions",
]

REQUIRED_LOGGING_KEYS = ["default_verbosity", "save_full_transcripts"]


# ---------------------------------------------------------------------------
# Test class: directory layout
# ---------------------------------------------------------------------------

class TestDirectoryLayout:
    """
    After setup(), the .claude-reflect/ directory layout must match the spec.

    Source: docs/IMPLEMENTATION.md § "Storage layout" and
            docs/spec/04-processes/run-loop.md Phase 1.
    """

    def test_kb_root_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert kb(tmp_git_repo).is_dir()

    def test_gaps_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "gaps").is_dir()

    def test_archive_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "archive").is_dir()

    def test_summary_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "summary").is_dir()

    def test_summary_gap_kinds_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "summary" / "gap-kinds").is_dir()

    def test_summary_archive_entries_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "summary" / "archive-entries").is_dir()

    def test_summary_session_clusters_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "summary" / "session-clusters").is_dir()

    def test_summary_decision_lineages_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "summary" / "decision-lineages").is_dir()

    def test_runs_directory_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "runs").is_dir()

    def test_summary_index_file_exists(self, tmp_git_repo):
        """Phase 1: 'Initialize the summary layer directory with an empty index.'"""
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "summary" / "index.md").is_file()

    def test_config_yaml_exists(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert (kb(tmp_git_repo) / "config.yaml").is_file()


# ---------------------------------------------------------------------------
# Test class: config top-level structure
# ---------------------------------------------------------------------------

class TestConfigTopLevel:
    """config.yaml is valid YAML and contains every required top-level key."""

    def test_config_is_valid_yaml(self, tmp_git_repo):
        setup(tmp_git_repo)
        config = cfg(tmp_git_repo)
        assert isinstance(config, dict)

    @pytest.mark.parametrize("key", REQUIRED_TOP_LEVEL_KEYS)
    def test_config_has_required_top_level_key(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        config = cfg(tmp_git_repo)
        assert key in config, f"config.yaml missing required top-level key: '{key}'"


# ---------------------------------------------------------------------------
# Test class: models section
# ---------------------------------------------------------------------------

class TestConfigModels:
    """models is intentionally absent from kb_setup defaults.

    Per the c5 iteration (interactive model picker), the models section
    is no longer written by setup(). It is filled on the first review
    pass — either by the picker when stdin is a TTY, or by the cli's
    fallback _DEFAULT_MODELS when non-interactive. These tests pin both
    halves of that contract.
    """

    def test_setup_does_not_write_models_section(self, tmp_git_repo):
        """kb_setup must leave the models section absent so the first
        review can route through the picker."""
        setup(tmp_git_repo)
        assert "models" not in cfg(tmp_git_repo), (
            "models section must be absent after kb_setup; the first-run "
            "picker (or non-TTY fallback in cli) is responsible for "
            "populating it."
        )

    @pytest.mark.parametrize("key", REQUIRED_MODEL_KEYS)
    def test_cli_default_models_has_required_key(self, key):
        """cli._DEFAULT_MODELS must cover every required agent so the
        non-TTY fallback resolves cleanly."""
        from claude_reflect.cli import _DEFAULT_MODELS
        assert key in _DEFAULT_MODELS, f"_DEFAULT_MODELS.{key} missing"

    @pytest.mark.parametrize("key", REQUIRED_MODEL_KEYS)
    def test_cli_default_model_value_is_non_empty_string(self, key):
        from claude_reflect.cli import _DEFAULT_MODELS
        val = _DEFAULT_MODELS[key]
        assert isinstance(val, str) and val, (
            f"_DEFAULT_MODELS.{key} must be a non-empty string"
        )

    def test_cli_default_evaluator_is_opus_family(self):
        """Evaluator default stays in the Opus family (1M context for
        large sessions)."""
        from claude_reflect.cli import _DEFAULT_MODELS
        assert "opus" in _DEFAULT_MODELS["evaluator"].lower()

    def test_cli_default_proposer_is_opus_family(self):
        """Proposer default stays in the Opus family (hardest reasoning)."""
        from claude_reflect.cli import _DEFAULT_MODELS
        assert "opus" in _DEFAULT_MODELS["proposer"].lower()

    def test_cli_default_author_is_sonnet_family(self):
        """Author default stays in the Sonnet family (cheaper, mechanical
        diff writing)."""
        from claude_reflect.cli import _DEFAULT_MODELS
        assert "sonnet" in _DEFAULT_MODELS["author"].lower()


# ---------------------------------------------------------------------------
# Test class: maintenance thresholds
# ---------------------------------------------------------------------------

class TestConfigMaintenanceThresholds:
    """maintenance.trigger_thresholds has all four threshold keys, all positive ints."""

    def test_maintenance_has_trigger_thresholds_key(self, tmp_git_repo):
        setup(tmp_git_repo)
        assert "trigger_thresholds" in cfg(tmp_git_repo)["maintenance"]

    @pytest.mark.parametrize("key", REQUIRED_THRESHOLD_KEYS)
    def test_threshold_key_present(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        thresholds = cfg(tmp_git_repo)["maintenance"]["trigger_thresholds"]
        assert key in thresholds, f"maintenance.trigger_thresholds.{key} missing"

    @pytest.mark.parametrize("key", REQUIRED_THRESHOLD_KEYS)
    def test_threshold_value_is_positive_int(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["maintenance"]["trigger_thresholds"][key]
        assert isinstance(val, int), f"maintenance.trigger_thresholds.{key} must be int, got {type(val)}"
        assert val > 0, f"maintenance.trigger_thresholds.{key} must be > 0, got {val}"


# ---------------------------------------------------------------------------
# Test class: stale gap threshold
# ---------------------------------------------------------------------------

class TestConfigStaleGapThreshold:
    def test_stale_gap_threshold_is_positive_int(self, tmp_git_repo):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["stale_gap_threshold_sessions"]
        assert isinstance(val, int)
        assert val > 0


# ---------------------------------------------------------------------------
# Test class: forced novelty
# ---------------------------------------------------------------------------

class TestConfigForcedNovelty:
    """forced_novelty has both probability fields, both floats in (0, 1)."""

    @pytest.mark.parametrize("key", REQUIRED_FORCED_NOVELTY_KEYS)
    def test_forced_novelty_key_present(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        assert key in cfg(tmp_git_repo)["forced_novelty"], f"forced_novelty.{key} missing"

    def test_probability_is_float_in_open_unit_interval(self, tmp_git_repo):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["forced_novelty"]["probability"]
        assert isinstance(val, (int, float))
        assert 0.0 < float(val) < 1.0, f"forced_novelty.probability must be in (0, 1), got {val}"

    def test_null_baseline_probability_is_float_in_open_unit_interval(self, tmp_git_repo):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["forced_novelty"]["null_baseline_probability"]
        assert isinstance(val, (int, float))
        assert 0.0 < float(val) < 1.0, (
            f"forced_novelty.null_baseline_probability must be in (0, 1), got {val}"
        )


# ---------------------------------------------------------------------------
# Test class: window warnings
# ---------------------------------------------------------------------------

class TestConfigWindowWarnings:
    @pytest.mark.parametrize("key", REQUIRED_WINDOW_WARNING_KEYS)
    def test_window_warnings_key_present(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        assert key in cfg(tmp_git_repo)["window_warnings"], f"window_warnings.{key} missing"

    @pytest.mark.parametrize("key", REQUIRED_WINDOW_WARNING_KEYS)
    def test_window_warnings_value_is_positive_int(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["window_warnings"][key]
        assert isinstance(val, int)
        assert val > 0


# ---------------------------------------------------------------------------
# Test class: logging
# ---------------------------------------------------------------------------

class TestConfigLogging:
    @pytest.mark.parametrize("key", REQUIRED_LOGGING_KEYS)
    def test_logging_key_present(self, tmp_git_repo, key):
        setup(tmp_git_repo)
        assert key in cfg(tmp_git_repo)["logging"], f"logging.{key} missing"

    def test_default_verbosity_is_quiet(self, tmp_git_repo):
        """Default verbosity is 'quiet'. Spec: IMPLEMENTATION.md § 'Logging'."""
        setup(tmp_git_repo)
        assert cfg(tmp_git_repo)["logging"]["default_verbosity"] == "quiet"

    def test_default_verbosity_is_valid_enum_value(self, tmp_git_repo):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["logging"]["default_verbosity"]
        assert val in ("quiet", "verbose"), f"logging.default_verbosity must be 'quiet' or 'verbose', got {val!r}"

    def test_save_full_transcripts_is_bool(self, tmp_git_repo):
        setup(tmp_git_repo)
        val = cfg(tmp_git_repo)["logging"]["save_full_transcripts"]
        assert isinstance(val, bool)


# ---------------------------------------------------------------------------
# Test class: cross-cutting cautions (no scalar grades)
# ---------------------------------------------------------------------------

class TestNoScalarGrades:
    """
    Cross-cutting caution: no scalar grades anywhere.

    'No quality scores, effort scores, priority numbers. If a function
    signature includes a numeric score, that's a bug.'
    — docs/IMPLEMENTATION.md § 'Implementation cautions'
    """

    FORBIDDEN_KEYS = frozenset({"score", "grade", "priority", "quality", "effort", "rank"})

    def _walk(self, obj, path: str = ""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in self.FORBIDDEN_KEYS, (
                    f"Scalar grade key '{k}' found at config path '{path}.{k}'. "
                    "No scalar grades allowed."
                )
                self._walk(v, f"{path}.{k}")

    def test_config_contains_no_scalar_grade_keys(self, tmp_git_repo):
        setup(tmp_git_repo)
        self._walk(cfg(tmp_git_repo))
