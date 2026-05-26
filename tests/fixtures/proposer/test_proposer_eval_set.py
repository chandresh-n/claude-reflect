"""
Fixture runner for step 9 proposer eval set (SOFT gate).

Validates a canned proposer batch output against the expected-proposal-batch-shape
schema and asserts categorical properties (rationale present, authoring addendum
present, no scalar grades, no rankings). Does NOT invoke a real agent.

Run:
    python3.11 -m pytest tests/fixtures/proposer/test_proposer_eval_set.py -v
"""

import json
from pathlib import Path

import jsonschema
import pytest

FIXTURES_DIR = Path(__file__).parent


@pytest.fixture
def schema():
    """Load the proposal batch JSON schema."""
    with open(FIXTURES_DIR / "expected_proposal_batch_shape.json") as f:
        return json.load(f)


@pytest.fixture
def evaluator_output():
    """Load the evaluator output fixture that feeds the proposer."""
    with open(FIXTURES_DIR / "evaluator_output_fixture.json") as f:
        return json.load(f)


@pytest.fixture
def canned_batch():
    """Load a canned proposer batch output.

    Falls back to a minimal synthetic batch when canned_proposal_batch.json
    isn't present — that lets the schema-runner tests validate the
    fixture pipeline without depending on a real agent invocation.
    """
    canned_path = FIXTURES_DIR / "canned_proposal_batch.json"
    if not canned_path.exists():
        # Return a minimal valid batch for schema-runner validation
        return _minimal_valid_batch()
    with open(canned_path) as f:
        return json.load(f)


def _minimal_valid_batch():
    """A minimal proposal batch that should validate against the schema.

    Used to confirm the fixture runner itself executes without an agent.
    """
    return {
        "batch_id": "batch-test-001",
        "run_id": "run-test-001",
        "created_at": "2026-04-29T10:00:00Z",
        "window": {"start": "2026-04-22", "end": "2026-04-29"},
        "proposal_ids": ["prop-test-001"],
        "batch_narrative": "One proposal targeting a tool-call-loop gap observed in the evaluation window.",
        "contains_forced_novelty": False,
        "proposals": [
            {
                "proposal_id": "prop-test-001",
                "batch_id": "batch-test-001",
                "run_id": "run-test-001",
                "created_at": "2026-04-29T10:00:00Z",
                "title": "Add project file map to CLAUDE.md to reduce search loops",
                "why": {
                    "cited_gaps": [
                        {
                            "gap_id": "gap-001",
                            "addressing_note": "Repeated tool-call loops when searching for known files. A project map would eliminate search guessing."
                        }
                    ],
                    "cited_sessions": [
                        {
                            "session_id": "session-prop-001",
                            "turn_range": {"start": 3, "end": 5}
                        }
                    ],
                    "cited_prior_decisions": [],
                    "prose_summary": "The tool-call-loop gap has been observed repeatedly. Sessions show the assistant searching for files whose locations are predictable from project structure. Adding a project file map to CLAUDE.md would let the assistant skip exploratory searches."
                },
                "what": {
                    "diff_reference": None,
                    "files_touched": None,
                    "short_description": "Add a concise project file map section to CLAUDE.md listing key file paths."
                },
                "how": "The change adds a structured section to CLAUDE.md that maps common task types to their relevant file paths. When the assistant receives a task, it can consult this map before searching, reducing or eliminating exploratory tool-call loops.",
                "prediction": "Sessions involving file location should see fewer redundant search turns. The tool-call-loop gap's occurrence rate should decrease for tasks targeting files listed in the map.",
                "structural_tags": {
                    "change_type": "modification",
                    "surface": "claude_md",
                    "novelty_status": "normal"
                },
                "authoring_addendum": {
                    "actions": [
                        {"type": "modify", "target_path": ".claude/CLAUDE.md"}
                    ],
                    "purpose": "Add a project file map section that lists key directories and files by function, enabling the assistant to locate targets without exploratory searches.",
                    "activation_conditions": "The map is passive content read at session start. No activation trigger needed.",
                    "behavior_constraints": [
                        "Must not exceed 40 lines to avoid context bloat.",
                        "Must list only stable paths that are unlikely to change frequently.",
                        "Must use a flat list format, not nested trees."
                    ],
                    "examples": [
                        "## Project file map\n- API client: src/api_client.py\n- Config parser: lib/config_parser.py\n- Tests: tests/"
                    ],
                    "style_hints": "Match the existing CLAUDE.md tone: terse, imperative, no decorative formatting.",
                    "reference_material": [".claude/CLAUDE.md"]
                }
            }
        ]
    }


class TestProposalBatchSchemaValidation:
    """Validate that the proposer batch output matches the schema."""

    def test_batch_validates_against_schema(self, schema, canned_batch):
        """The proposal batch must validate against the proposal batch schema."""
        jsonschema.validate(instance=canned_batch, schema=schema)

    def test_batch_is_non_empty(self, canned_batch):
        """The batch must contain at least one proposal."""
        assert len(canned_batch["proposals"]) >= 1

    def test_proposal_ids_match_proposals(self, canned_batch):
        """proposal_ids list must match the actual proposal_id values."""
        listed_ids = set(canned_batch["proposal_ids"])
        actual_ids = {p["proposal_id"] for p in canned_batch["proposals"]}
        assert listed_ids == actual_ids


class TestProposalCategoricalAssertions:
    """Assert categorical properties of proposals — not exact prose."""

    def test_every_proposal_has_rationale(self, canned_batch):
        """Every proposal must have all four rationale parts populated."""
        for proposal in canned_batch["proposals"]:
            assert proposal["why"]["cited_gaps"], (
                f"Proposal {proposal['proposal_id']} has no cited_gaps"
            )
            assert proposal["why"]["prose_summary"], (
                f"Proposal {proposal['proposal_id']} has no prose_summary"
            )
            assert proposal["how"], (
                f"Proposal {proposal['proposal_id']} has no 'how' section"
            )
            assert proposal["prediction"], (
                f"Proposal {proposal['proposal_id']} has no 'prediction' section"
            )

    def test_every_proposal_has_authoring_addendum(self, canned_batch):
        """Every proposal must have an authoring addendum with actions and
        behavior_constraints."""
        for proposal in canned_batch["proposals"]:
            addendum = proposal["authoring_addendum"]
            assert addendum["actions"], (
                f"Proposal {proposal['proposal_id']} addendum has no actions"
            )
            assert addendum["purpose"], (
                f"Proposal {proposal['proposal_id']} addendum has no purpose"
            )
            assert addendum["behavior_constraints"], (
                f"Proposal {proposal['proposal_id']} addendum has no behavior_constraints"
            )

    def test_no_scalar_grades_in_batch(self, canned_batch):
        """No scalar grades, rankings, or priority numbers in the batch."""
        batch_str = json.dumps(canned_batch).lower()
        forbidden_patterns = [
            "quality_score", "confidence_score", "priority_number",
            "ranking", "severity_score", "grade",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in batch_str, (
                f"Forbidden scalar grade pattern '{pattern}' found in batch"
            )

    def test_no_priority_ranking_in_batch(self, canned_batch):
        """No priority ranking field in any proposal — spec explicitly excludes it."""
        for proposal in canned_batch["proposals"]:
            assert "priority" not in proposal, (
                f"Proposal {proposal['proposal_id']} has forbidden 'priority' field"
            )
            assert "rank" not in proposal, (
                f"Proposal {proposal['proposal_id']} has forbidden 'rank' field"
            )

    def test_diff_reference_null_at_phase_5a(self, canned_batch):
        """At end of Phase 5a, diff_reference and files_touched should be null
        (not yet populated by the author)."""
        for proposal in canned_batch["proposals"]:
            # This assertion applies to proposer output before the author runs
            what = proposal["what"]
            assert what["diff_reference"] is None, (
                f"Proposal {proposal['proposal_id']} has diff_reference set — "
                "proposer should not produce diffs"
            )
            assert what["files_touched"] is None, (
                f"Proposal {proposal['proposal_id']} has files_touched set — "
                "proposer should not produce diffs"
            )

    def test_structural_tags_valid(self, canned_batch):
        """Structural tags must use the spec's vocabulary."""
        valid_change_types = {"addition", "modification", "removal", "restructuring"}
        valid_surfaces = {"claude_md", "skill", "agent", "hook", "settings", "mcp"}
        valid_novelty = {"normal", "forced_novelty", "null_baseline"}

        for proposal in canned_batch["proposals"]:
            tags = proposal["structural_tags"]
            assert tags["change_type"] in valid_change_types
            assert tags["surface"] in valid_surfaces
            assert tags["novelty_status"] in valid_novelty

    def test_forced_novelty_has_exploration_rationale(self, canned_batch):
        """If novelty_status is forced_novelty or null_baseline,
        exploration_rationale must be present."""
        for proposal in canned_batch["proposals"]:
            tags = proposal["structural_tags"]
            if tags["novelty_status"] in ("forced_novelty", "null_baseline"):
                assert "exploration_rationale" in tags and tags["exploration_rationale"], (
                    f"Proposal {proposal['proposal_id']} is {tags['novelty_status']} "
                    "but has no exploration_rationale"
                )


class TestSchemaRejectsInvalid:
    """The proposal batch schema itself must reject malformed batches."""

    def test_missing_proposals_rejected(self, schema):
        bad = {
            "batch_id": "b1",
            "run_id": "r1",
            "created_at": "2026-01-01",
            "window": {"start": "2026-01-01", "end": "2026-01-07"},
            "proposal_ids": ["p1"],
            "batch_narrative": "test",
            "contains_forced_novelty": False,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_empty_proposals_rejected(self, schema):
        bad = {
            "batch_id": "b1",
            "run_id": "r1",
            "created_at": "2026-01-01",
            "window": {"start": "2026-01-01", "end": "2026-01-07"},
            "proposal_ids": [],
            "batch_narrative": "test",
            "contains_forced_novelty": False,
            "proposals": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_invalid_change_type_rejected(self, schema):
        batch = _minimal_valid_batch()
        batch["proposals"][0]["structural_tags"]["change_type"] = "invalid_type"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=batch, schema=schema)

    def test_invalid_surface_rejected(self, schema):
        batch = _minimal_valid_batch()
        batch["proposals"][0]["structural_tags"]["surface"] = "invalid_surface"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=batch, schema=schema)
