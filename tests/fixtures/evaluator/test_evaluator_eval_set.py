"""
Fixture runner for step 8 evaluator eval set (SOFT gate).

Validates canned evaluator output against the expected-output-shape schema
and asserts categorical properties (gap observation kind, no scalar grades,
no recommendations). Does NOT invoke a real agent.

Run:
    python3.11 -m pytest tests/fixtures/evaluator/test_evaluator_eval_set.py -v
"""

import json
from pathlib import Path

import jsonschema
import pytest

FIXTURES_DIR = Path(__file__).parent


@pytest.fixture
def schema():
    """Load the evaluator output JSON schema."""
    with open(FIXTURES_DIR / "expected_output_shape.json") as f:
        return json.load(f)


@pytest.fixture
def canned_output():
    """Load the canned evaluator output for the tool-call-loop fixture."""
    with open(FIXTURES_DIR / "canned_output_tool_call_loop.json") as f:
        return json.load(f)


class TestEvaluatorOutputSchemaValidation:
    """Validate that the canned evaluator output matches the schema."""

    def test_canned_output_validates_against_schema(self, schema, canned_output):
        """The canned tool-call-loop output must validate against the
        evaluator output schema without errors."""
        jsonschema.validate(instance=canned_output, schema=schema)

    def test_per_turn_observations_exhaustive(self, canned_output):
        """Every turn in the session must have an observation."""
        observations = canned_output["per_turn_observations"]
        session_ids = {o["session_id"] for o in observations}
        assert len(session_ids) >= 1, "At least one session must be covered"
        # Turn indices must be contiguous starting from 0
        for sid in session_ids:
            turns = sorted(
                o["turn_index"] for o in observations if o["session_id"] == sid
            )
            assert turns == list(range(len(turns))), (
                f"Turn indices for {sid} are not contiguous from 0: {turns}"
            )

    def test_pass_classifications_cover_all_turns(self, canned_output):
        """Pass classifications must be non-overlapping and cover every turn."""
        observations = canned_output["per_turn_observations"]
        classifications = canned_output["pass_classifications"]

        for sid in {o["session_id"] for o in observations}:
            max_turn = max(
                o["turn_index"] for o in observations if o["session_id"] == sid
            )
            covered = set()
            for pc in classifications:
                if pc["session_id"] != sid:
                    continue
                r = pc["turn_range"]
                turn_set = set(range(r["start"], r["end"] + 1))
                overlap = covered & turn_set
                assert not overlap, (
                    f"Overlapping turns in pass classifications for {sid}: {overlap}"
                )
                covered |= turn_set

            expected = set(range(max_turn + 1))
            assert covered == expected, (
                f"Pass classifications for {sid} do not cover all turns. "
                f"Missing: {expected - covered}"
            )

    def test_session_narratives_present(self, canned_output):
        """Every session in the window must have a narrative."""
        obs_sessions = {o["session_id"] for o in canned_output["per_turn_observations"]}
        narr_sessions = {n["session_id"] for n in canned_output["session_narratives"]}
        assert obs_sessions == narr_sessions, (
            f"Narrative session mismatch. Observations: {obs_sessions}, "
            f"Narratives: {narr_sessions}"
        )


class TestEvaluatorOutputCategoricalAssertions:
    """Assert categorical properties of the canned output — not exact prose."""

    def test_gap_observation_has_tool_call_loop_kind(self, canned_output):
        """The tool-call-loop fixture must produce at least one gap observation
        with kind containing 'tool_call_loop'."""
        gap_kinds = [g["kind"] for g in canned_output["gap_observations"]]
        assert any("tool_call_loop" in k for k in gap_kinds), (
            f"Expected a gap observation with kind containing 'tool_call_loop', "
            f"got kinds: {gap_kinds}"
        )

    def test_gap_observation_has_evidence(self, canned_output):
        """Every gap observation must have at least one evidence addition."""
        for gap in canned_output["gap_observations"]:
            assert len(gap["evidence_additions"]) >= 1, (
                f"Gap '{gap['kind']}' has no evidence additions"
            )

    def test_no_scalar_grades_in_output(self, canned_output):
        """No scalar grades, quality scores, confidence values, or rankings
        may appear in the output structure."""
        output_str = json.dumps(canned_output).lower()
        forbidden_patterns = [
            "quality_score", "confidence_score", "confidence_value",
            "ranking", "severity_score", "grade", "priority_number",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in output_str, (
                f"Forbidden scalar grade pattern '{pattern}' found in output"
            )

    def test_no_recommendations_in_output(self, canned_output):
        """No recommendations or proposals may appear in evaluator output."""
        output_str = json.dumps(canned_output).lower()
        # Check that no field is named 'recommendation' or 'proposal'
        # at the schema level (not in prose, where the word may appear
        # naturally in assessments about the harness).
        for key_path in _walk_keys(canned_output):
            assert "recommendation" not in key_path.lower(), (
                f"Forbidden key '{key_path}' suggests recommendations in output"
            )
            # 'proposal' as a top-level key would be a violation;
            # 'related_proposals' in gap records is fine (it's in the gap
            # record schema, not the evaluator output schema)
            if key_path in ("proposal", "proposals"):
                raise AssertionError(
                    f"Forbidden key '{key_path}' suggests proposals in evaluator output"
                )

    def test_pass_type_values_are_valid(self, canned_output):
        """All pass_type values must be from the spec's vocabulary."""
        valid_types = {
            "successful_one_shot", "refinement", "clarification",
            "correction", "retry",
        }
        for pc in canned_output["pass_classifications"]:
            assert pc["pass_type"] in valid_types, (
                f"Invalid pass_type '{pc['pass_type']}'. Valid: {valid_types}"
            )

    def test_session_outcome_values_are_valid(self, canned_output):
        """All session outcome values must be from the spec's vocabulary."""
        valid_outcomes = {
            "successful_and_accepted", "successful_with_friction",
            "abandoned", "ongoing",
        }
        for narr in canned_output["session_narratives"]:
            assert narr["outcome"] in valid_outcomes, (
                f"Invalid outcome '{narr['outcome']}'. Valid: {valid_outcomes}"
            )

    def test_contributing_gaps_null_for_successful_passes(self, canned_output):
        """contributing_gaps must be null for successful_one_shot and
        refinement passes per the spec."""
        for pc in canned_output["pass_classifications"]:
            if pc["pass_type"] in ("successful_one_shot", "refinement"):
                assert pc["contributing_gaps"] is None, (
                    f"Pass type '{pc['pass_type']}' must have null contributing_gaps"
                )


class TestSchemaRejectsInvalid:
    """The schema itself must reject malformed outputs."""

    def test_missing_per_turn_observations_rejected(self, schema):
        bad = {
            "pass_classifications": [],
            "gap_observations": [],
            "session_narratives": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_empty_per_turn_observations_rejected(self, schema):
        bad = {
            "per_turn_observations": [],
            "pass_classifications": [
                {
                    "session_id": "s1",
                    "turn_range": {"start": 0, "end": 0},
                    "pass_type": "successful_one_shot",
                    "harness_gap_rationale": "none",
                    "contributing_gaps": None,
                }
            ],
            "gap_observations": [],
            "session_narratives": [
                {
                    "session_id": "s1",
                    "outcome": "successful_and_accepted",
                    "pass_counts_by_type": {},
                    "gaps_observed": [],
                    "narrative": "a narrative",
                }
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_invalid_pass_type_rejected(self, schema):
        bad = {
            "per_turn_observations": [
                {
                    "session_id": "s1",
                    "turn_index": 0,
                    "assessment": "test",
                    "effort_signal": {
                        "tokens_used": 100,
                        "model": "test",
                        "context_occupancy": 0.1,
                        "tool_calls": [],
                    },
                    "flags": [],
                }
            ],
            "pass_classifications": [
                {
                    "session_id": "s1",
                    "turn_range": {"start": 0, "end": 0},
                    "pass_type": "invalid_type",
                    "harness_gap_rationale": "test",
                    "contributing_gaps": None,
                }
            ],
            "gap_observations": [],
            "session_narratives": [
                {
                    "session_id": "s1",
                    "outcome": "successful_and_accepted",
                    "pass_counts_by_type": {},
                    "gaps_observed": [],
                    "narrative": "a narrative",
                }
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_scalar_grade_field_rejected_by_additional_properties(self, schema):
        """Adding a 'quality_score' field to a per_turn_observation must be
        rejected by additionalProperties: false."""
        bad_obs = {
            "session_id": "s1",
            "turn_index": 0,
            "assessment": "test",
            "effort_signal": {
                "tokens_used": 100,
                "model": "test",
                "context_occupancy": 0.1,
                "tool_calls": [],
            },
            "flags": [],
            "quality_score": 0.85,
        }
        bad = {
            "per_turn_observations": [bad_obs],
            "pass_classifications": [
                {
                    "session_id": "s1",
                    "turn_range": {"start": 0, "end": 0},
                    "pass_type": "successful_one_shot",
                    "harness_gap_rationale": "test",
                    "contributing_gaps": None,
                }
            ],
            "gap_observations": [],
            "session_narratives": [
                {
                    "session_id": "s1",
                    "outcome": "successful_and_accepted",
                    "pass_counts_by_type": {},
                    "gaps_observed": [],
                    "narrative": "a narrative",
                }
            ],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)


def _walk_keys(obj, prefix=""):
    """Yield all keys in a nested dict/list structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v, prefix=f"{prefix}.{k}")
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item, prefix=prefix)
