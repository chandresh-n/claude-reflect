"""
Fixture runner for step 10 author eval set (SOFT gate).

Validates canned author outputs against the expected-output-shape schema
and asserts categorical properties:
- Valid intent -> success with a diff (non-null diff_reference, files_touched)
- Impossible intent -> author_failed with a specific failure reason

Does NOT invoke a real agent.

Run:
    python3.11 -m pytest tests/fixtures/author/test_author_eval_set.py -v
"""

import json
from pathlib import Path

import jsonschema
import pytest

FIXTURES_DIR = Path(__file__).parent


@pytest.fixture
def schema():
    """Load the author output JSON schema."""
    with open(FIXTURES_DIR / "expected_output_shape.json") as f:
        return json.load(f)


@pytest.fixture
def valid_intent():
    """Load the valid proposer intent fixture."""
    with open(FIXTURES_DIR / "valid_intent.json") as f:
        return json.load(f)


@pytest.fixture
def impossible_intent():
    """Load the impossible proposer intent fixture."""
    with open(FIXTURES_DIR / "impossible_intent.json") as f:
        return json.load(f)


@pytest.fixture
def canned_success():
    """Load the canned success output for the valid intent."""
    with open(FIXTURES_DIR / "canned_success_output.json") as f:
        return json.load(f)


@pytest.fixture
def canned_failure():
    """Load the canned failure output for the impossible intent."""
    with open(FIXTURES_DIR / "canned_failure_output.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestAuthorOutputSchemaValidation:
    """Validate that canned outputs match the author output schema."""

    def test_success_output_validates_against_schema(self, schema, canned_success):
        """A successful author output must validate against the schema."""
        jsonschema.validate(instance=canned_success, schema=schema)

    def test_failure_output_validates_against_schema(self, schema, canned_failure):
        """A failed author output must validate against the schema."""
        jsonschema.validate(instance=canned_failure, schema=schema)


# ---------------------------------------------------------------------------
# Valid intent -> success assertions
# ---------------------------------------------------------------------------

class TestValidIntentProducesSuccess:
    """Assert that the canned output for the valid intent is a success."""

    def test_status_is_success(self, canned_success):
        assert canned_success["status"] == "success"

    def test_diff_reference_populated(self, canned_success):
        """Successful author output must have a non-null diff_reference."""
        assert canned_success["diff_reference"] is not None
        assert len(canned_success["diff_reference"]) > 0

    def test_files_touched_populated(self, canned_success):
        """Successful author output must list files touched."""
        assert canned_success["files_touched"] is not None
        assert len(canned_success["files_touched"]) >= 1

    def test_files_touched_match_intent_actions(self, valid_intent, canned_success):
        """Files touched must align with the target_paths in the intent's actions."""
        intent_paths = {
            a["target_path"] for a in valid_intent["authoring_addendum"]["actions"]
        }
        touched = set(canned_success["files_touched"])
        assert touched == intent_paths, (
            f"Files touched {touched} do not match intent actions {intent_paths}"
        )

    def test_branch_name_contains_proposal_id(self, canned_success):
        """Branch name must contain the proposal_id per spec."""
        assert canned_success["proposal_id"] in canned_success["branch_name"]

    def test_no_author_failure_reason(self, canned_success):
        """Successful output must not contain an author_failure_reason."""
        assert "author_failure_reason" not in canned_success

    def test_proposal_id_matches_intent(self, valid_intent, canned_success):
        """The output proposal_id must match the input intent."""
        assert canned_success["proposal_id"] == valid_intent["proposal_id"]


# ---------------------------------------------------------------------------
# Impossible intent -> author_failed assertions
# ---------------------------------------------------------------------------

class TestImpossibleIntentProducesFailure:
    """Assert that the canned output for the impossible intent is author_failed."""

    def test_status_is_author_failed(self, canned_failure):
        assert canned_failure["status"] == "author_failed"

    def test_diff_reference_is_null(self, canned_failure):
        """Failed author output must have null diff_reference."""
        assert canned_failure["diff_reference"] is None

    def test_files_touched_is_null(self, canned_failure):
        """Failed author output must have null files_touched."""
        assert canned_failure["files_touched"] is None

    def test_branch_name_is_null(self, canned_failure):
        """Failed author output must have null branch_name (no branch created)."""
        assert canned_failure["branch_name"] is None

    def test_failure_reason_present_and_specific(self, canned_failure):
        """author_failure_reason must be present, non-empty, and specific
        (not a generic message like 'could not complete')."""
        reason = canned_failure["author_failure_reason"]
        assert reason is not None
        assert len(reason) > 20, "Failure reason is too short to be specific"
        generic_phrases = ["could not complete", "unknown error", "failed"]
        for phrase in generic_phrases:
            if reason.strip().lower() == phrase:
                raise AssertionError(
                    f"Failure reason is too generic: '{reason}'"
                )

    def test_failure_reason_names_the_constraint(self, canned_failure):
        """The failure reason must reference the specific constraint that
        could not be satisfied — not just say it failed."""
        reason = canned_failure["author_failure_reason"].lower()
        # The impossible intent asks for tool-call interception which skills
        # cannot do. The reason should mention this architectural limitation.
        assert any(
            term in reason
            for term in ["intercept", "block", "skill", "activation", "tool call"]
        ), (
            f"Failure reason does not reference the specific unsatisfiable "
            f"constraint: '{canned_failure['author_failure_reason']}'"
        )

    def test_proposal_id_matches_intent(self, impossible_intent, canned_failure):
        """The output proposal_id must match the input intent."""
        assert canned_failure["proposal_id"] == impossible_intent["proposal_id"]


# ---------------------------------------------------------------------------
# Schema rejects invalid outputs
# ---------------------------------------------------------------------------

class TestSchemaRejectsInvalid:
    """The author output schema must reject malformed outputs."""

    def test_missing_status_rejected(self, schema):
        bad = {
            "proposal_id": "p1",
            "diff_reference": "abc",
            "files_touched": ["f.txt"],
            "branch_name": "b1",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_success_with_null_diff_rejected(self, schema):
        """A success status with null diff_reference must be rejected."""
        bad = {
            "status": "success",
            "proposal_id": "p1",
            "diff_reference": None,
            "files_touched": ["f.txt"],
            "branch_name": "b1",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_success_with_null_files_touched_rejected(self, schema):
        bad = {
            "status": "success",
            "proposal_id": "p1",
            "diff_reference": "abc",
            "files_touched": None,
            "branch_name": "b1",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_failure_without_reason_rejected(self, schema):
        """author_failed without author_failure_reason must be rejected."""
        bad = {
            "status": "author_failed",
            "proposal_id": "p1",
            "diff_reference": None,
            "files_touched": None,
            "branch_name": None,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_failure_with_non_null_diff_rejected(self, schema):
        """author_failed with a non-null diff_reference must be rejected."""
        bad = {
            "status": "author_failed",
            "proposal_id": "p1",
            "diff_reference": "abc",
            "files_touched": None,
            "branch_name": None,
            "author_failure_reason": "some reason",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_invalid_status_rejected(self, schema):
        bad = {
            "status": "partial",
            "proposal_id": "p1",
            "diff_reference": "abc",
            "files_touched": ["f.txt"],
            "branch_name": "b1",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_additional_properties_rejected(self, schema):
        """Extra fields like scalar grades must be rejected."""
        bad = {
            "status": "success",
            "proposal_id": "p1",
            "diff_reference": "abc",
            "files_touched": ["f.txt"],
            "branch_name": "b1",
            "quality_score": 0.9,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)


# ---------------------------------------------------------------------------
# Cross-cutting: no scalar grades
# ---------------------------------------------------------------------------

class TestNoScalarGrades:
    """Ensure no scalar grades leak into author outputs."""

    def test_no_scalar_grades_in_success(self, canned_success):
        output_str = json.dumps(canned_success).lower()
        forbidden = [
            "quality_score", "confidence_score", "priority_number",
            "ranking", "severity_score", "grade",
        ]
        for pattern in forbidden:
            assert pattern not in output_str, (
                f"Forbidden scalar grade pattern '{pattern}' in success output"
            )

    def test_no_scalar_grades_in_failure(self, canned_failure):
        output_str = json.dumps(canned_failure).lower()
        forbidden = [
            "quality_score", "confidence_score", "priority_number",
            "ranking", "severity_score", "grade",
        ]
        for pattern in forbidden:
            assert pattern not in output_str, (
                f"Forbidden scalar grade pattern '{pattern}' in failure output"
            )
