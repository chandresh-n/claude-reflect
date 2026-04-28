"""
Unit tests for Step 9 — proposer forced-novelty roll logic.

Tests the probabilistic forced-novelty mechanism with a mocked RNG.
Does NOT require a real agent. The implementation module
(src/meta_harness/agents/proposer.py) must expose a function that
determines whether a forced-novelty proposal is due for a given run.

The spec (docs/spec/03-agents/proposer.md) defines:
- With probability P (config parameter, e.g. 20%), one proposal in
  the batch must be structurally different from recent proposals.
- Within forced-novelty, with probability Q (e.g. 1%), the proposal
  is a null-baseline proposal.

Run:
    python3.11 -m pytest tests/unit/test_step9_forced_novelty.py -v
"""

from unittest.mock import patch

import pytest


class TestForcedNoveltyRollLogic:
    """Test the forced-novelty roll logic with a mocked RNG."""

    def test_roll_below_threshold_triggers_forced_novelty(self):
        """When RNG returns a value below the forced-novelty probability,
        forced-novelty is triggered."""
        from meta_harness.agents.proposer import check_forced_novelty

        # Mock random() to return 0.1 — below 0.2 threshold
        with patch("meta_harness.agents.proposer.random.random", return_value=0.1):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is True
        assert result["novelty_status"] in ("forced_novelty", "null_baseline")

    def test_roll_above_threshold_does_not_trigger(self):
        """When RNG returns a value above the forced-novelty probability,
        no forced-novelty is triggered."""
        from meta_harness.agents.proposer import check_forced_novelty

        # Mock random() to return 0.5 — above 0.2 threshold
        with patch("meta_harness.agents.proposer.random.random", return_value=0.5):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is False
        assert result["novelty_status"] == "normal"

    def test_roll_at_exact_threshold_does_not_trigger(self):
        """When RNG returns exactly the threshold value, forced-novelty
        is NOT triggered (strict less-than comparison)."""
        from meta_harness.agents.proposer import check_forced_novelty

        with patch("meta_harness.agents.proposer.random.random", return_value=0.2):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is False

    def test_null_baseline_triggered_when_second_roll_below_threshold(self):
        """When forced-novelty fires AND the second roll is below
        null_baseline_probability, the result is null_baseline."""
        from meta_harness.agents.proposer import check_forced_novelty

        # First roll: 0.1 < 0.2 → forced-novelty triggered
        # Second roll: 0.005 < 0.01 → null-baseline
        with patch(
            "meta_harness.agents.proposer.random.random",
            side_effect=[0.1, 0.005],
        ):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is True
        assert result["novelty_status"] == "null_baseline"

    def test_forced_novelty_without_null_baseline(self):
        """When forced-novelty fires but the second roll is above
        null_baseline_probability, the result is forced_novelty (not null_baseline)."""
        from meta_harness.agents.proposer import check_forced_novelty

        # First roll: 0.1 < 0.2 → forced-novelty triggered
        # Second roll: 0.5 >= 0.01 → NOT null-baseline
        with patch(
            "meta_harness.agents.proposer.random.random",
            side_effect=[0.1, 0.5],
        ):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is True
        assert result["novelty_status"] == "forced_novelty"

    def test_zero_probability_never_triggers(self):
        """With probability 0.0, forced-novelty never fires regardless of RNG."""
        from meta_harness.agents.proposer import check_forced_novelty

        with patch("meta_harness.agents.proposer.random.random", return_value=0.0):
            result = check_forced_novelty(
                forced_novelty_probability=0.0,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is False

    def test_one_probability_always_triggers(self):
        """With probability 1.0, forced-novelty always fires."""
        from meta_harness.agents.proposer import check_forced_novelty

        # Even with a high roll value, 1.0 threshold means everything is below
        with patch(
            "meta_harness.agents.proposer.random.random",
            side_effect=[0.999, 0.5],
        ):
            result = check_forced_novelty(
                forced_novelty_probability=1.0,
                null_baseline_probability=0.01,
            )
        assert result["triggered"] is True

    def test_result_includes_novelty_status_field(self):
        """The result dict must always include a 'novelty_status' field
        matching the spec vocabulary."""
        from meta_harness.agents.proposer import check_forced_novelty

        valid_statuses = {"normal", "forced_novelty", "null_baseline"}

        with patch("meta_harness.agents.proposer.random.random", return_value=0.5):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert "novelty_status" in result
        assert result["novelty_status"] in valid_statuses

    def test_result_includes_triggered_field(self):
        """The result dict must always include a boolean 'triggered' field."""
        from meta_harness.agents.proposer import check_forced_novelty

        with patch("meta_harness.agents.proposer.random.random", return_value=0.5):
            result = check_forced_novelty(
                forced_novelty_probability=0.2,
                null_baseline_probability=0.01,
            )
        assert "triggered" in result
        assert isinstance(result["triggered"], bool)
