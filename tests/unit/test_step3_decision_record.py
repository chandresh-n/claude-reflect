"""
Step 3 gate — Decision record + git ops (HARD gate): Unit tests.

Spec refs:
  docs/spec/01-data-structures/decision-record.md
  docs/spec/02-storage/decisions-git.md

Gate criteria (from docs/PLAN.md Step 3):
  1. Commit-message header parses correctly (proposal_id, run_id, status,
     targeted_gaps all extractable).
  2. Decision JSON roundtrips through the commit body.
  3. Status transitions (accepted/rejected/author_failed) are enforced.
  4. Proposal-branch lifecycle exercised end-to-end (covered in integration
     tests).

All tests must FAIL before implementation exists (Session A gate criterion).
"""
import json

import pytest

from claude_reflect.storage.decision_record import (
    create_decision_record,
    format_commit_message,
    parse_commit_header,
    parse_commit_body,
)


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_WHY = {
    "cited_gaps": [{"gap_id": "G-001", "note": "Addresses the tool-call-loop gap."}],
    "cited_sessions": [{"session_id": "sess-001", "turn_range": {"start": 0, "end": 3}}],
    "cited_prior_decisions": [],
    "prose_summary": "This proposal addresses the tool-call loop gap observed in recent sessions.",
}

VALID_WHAT = {
    "diff_reference": "abc123",
    "files_touched": ["CLAUDE.md"],
    "short_description": "Add tool-call loop recovery instruction to CLAUDE.md.",
}

VALID_PREDICTION_OUTCOME = {
    "status": "not_yet_due",
    "evidence": None,
    "commentary": None,
}

VALID_STRUCTURAL_TAGS = {
    "change_type": "addition",
    "surface": "claude_md",
    "novelty_status": "normal",
    "exploration_rationale": None,
}

# A fully valid accepted decision record
VALID_ACCEPTED_DECISION = {
    "proposal_id": "P-001",
    "run_id": "R-001",
    "batch_id": "B-001",
    "created_at": "2024-01-15T10:00:00+00:00",
    "reviewed_at": "2024-01-15T11:00:00+00:00",
    "status": "accepted",
    "human_reasoning": None,
    "author_failure_reason": None,
    "why": VALID_WHY,
    "what": VALID_WHAT,
    "how": "The instruction will guide the model to detect and break tool-call loops.",
    "prediction": "Tool-call loop frequency should drop over the next 5 sessions.",
    "prediction_outcome": VALID_PREDICTION_OUTCOME,
    "targeted_gaps": ["G-001"],
    "authoring_addendum": {"spec": "Add a recovery note after the tool-call section."},
    "structural_tags": VALID_STRUCTURAL_TAGS,
    "superseded_by": None,
}


def _make_decision(**overrides):
    """Return a copy of the base accepted decision with field overrides applied."""
    d = VALID_ACCEPTED_DECISION.copy()
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# Criterion 1: Commit-message header parses correctly
# ---------------------------------------------------------------------------

class TestCommitHeaderParsing:
    """parse_commit_header must extract proposal_id, run_id, status, targeted_gaps."""

    def _build_header(
        self,
        proposal_id="P-001",
        run_id="R-001",
        status="accepted",
        targeted_gaps=None,
    ):
        """Helper: build a well-formed commit header string."""
        if targeted_gaps is None:
            targeted_gaps = ["G-001"]
        lines = [
            f"proposal_id: {proposal_id}",
            f"run_id: {run_id}",
            f"status: {status}",
        ]
        for g in targeted_gaps:
            lines.append(f"targeted_gap: {g}")
        return "\n".join(lines)

    def test_parse_extracts_proposal_id(self):
        """proposal_id must be extractable from the structured header."""
        header = self._build_header(proposal_id="P-042")
        parsed = parse_commit_header(header)
        assert parsed["proposal_id"] == "P-042"

    def test_parse_extracts_run_id(self):
        """run_id must be extractable from the structured header."""
        header = self._build_header(run_id="R-007")
        parsed = parse_commit_header(header)
        assert parsed["run_id"] == "R-007"

    def test_parse_extracts_status(self):
        """status must be extractable from the structured header."""
        header = self._build_header(status="rejected")
        parsed = parse_commit_header(header)
        assert parsed["status"] == "rejected"

    def test_parse_extracts_single_targeted_gap(self):
        """A single targeted_gap entry must appear in the parsed list."""
        header = self._build_header(targeted_gaps=["G-073"])
        parsed = parse_commit_header(header)
        assert "G-073" in parsed["targeted_gaps"]

    def test_parse_extracts_multiple_targeted_gaps(self):
        """Multiple targeted_gap lines must all appear in the parsed list."""
        header = self._build_header(targeted_gaps=["G-001", "G-002", "G-003"])
        parsed = parse_commit_header(header)
        assert set(parsed["targeted_gaps"]) == {"G-001", "G-002", "G-003"}

    def test_parse_returns_empty_list_when_no_targeted_gaps(self):
        """Header with no targeted_gap lines must produce an empty list (not an error)."""
        header = (
            "proposal_id: P-001\n"
            "run_id: R-001\n"
            "status: author_failed"
        )
        parsed = parse_commit_header(header)
        assert parsed["targeted_gaps"] == []

    def test_parse_raises_on_missing_proposal_id(self):
        """Header missing proposal_id must raise."""
        header = "run_id: R-001\nstatus: accepted\ntargeted_gap: G-001"
        with pytest.raises(Exception):
            parse_commit_header(header)

    def test_parse_raises_on_missing_run_id(self):
        """Header missing run_id must raise."""
        header = "proposal_id: P-001\nstatus: accepted\ntargeted_gap: G-001"
        with pytest.raises(Exception):
            parse_commit_header(header)

    def test_parse_raises_on_missing_status(self):
        """Header missing status must raise."""
        header = "proposal_id: P-001\nrun_id: R-001\ntargeted_gap: G-001"
        with pytest.raises(Exception):
            parse_commit_header(header)

    def test_parse_supports_git_log_grep_pattern(self):
        """
        The targeted_gap field must use a line format that git log --grep
        "targeted_gap: G-73" would match.

        Validate by ensuring the raw header contains the exact substring
        'targeted_gap: G-073' (one line per gap, with the colon+space).
        """
        gaps = ["G-073", "G-099"]
        header = self._build_header(targeted_gaps=gaps)
        assert "targeted_gap: G-073" in header
        assert "targeted_gap: G-099" in header

    def test_parse_all_four_fields_present_simultaneously(self):
        """All four fields must be extractable in one call."""
        header = self._build_header(
            proposal_id="P-555",
            run_id="R-100",
            status="accepted",
            targeted_gaps=["G-010", "G-020"],
        )
        parsed = parse_commit_header(header)
        assert parsed["proposal_id"] == "P-555"
        assert parsed["run_id"] == "R-100"
        assert parsed["status"] == "accepted"
        assert set(parsed["targeted_gaps"]) == {"G-010", "G-020"}


# ---------------------------------------------------------------------------
# Criterion 2: Decision JSON roundtrips through the commit body
# ---------------------------------------------------------------------------

class TestCommitBodyRoundtrip:
    """
    format_commit_message embeds the decision JSON in the commit body.
    parse_commit_body extracts and parses that JSON back.

    Together they must preserve every decision field.
    """

    def test_format_produces_a_non_empty_string(self):
        """format_commit_message must return a non-empty string."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        assert isinstance(msg, str) and msg.strip()

    def test_commit_message_contains_proposal_id_in_header(self):
        """The formatted commit message must contain the proposal_id header line."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        assert "proposal_id: P-001" in msg

    def test_commit_message_contains_run_id_in_header(self):
        """The formatted commit message must contain the run_id header line."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        assert "run_id: R-001" in msg

    def test_commit_message_contains_status_in_header(self):
        """The formatted commit message must contain the status header line."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        assert "status: accepted" in msg

    def test_commit_message_contains_targeted_gap_in_header(self):
        """Each targeted gap must appear as a targeted_gap: header line."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        assert "targeted_gap: G-001" in msg

    def test_commit_body_contains_valid_json(self):
        """The commit body section must contain a parseable JSON object."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        # parse_commit_body should extract the JSON without raising
        body = parse_commit_body(msg)
        assert isinstance(body, dict)

    def test_roundtrip_preserves_proposal_id(self):
        """proposal_id must survive the format → parse roundtrip."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        body = parse_commit_body(msg)
        assert body["proposal_id"] == decision["proposal_id"]

    def test_roundtrip_preserves_run_id(self):
        """run_id must survive the format → parse roundtrip."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        body = parse_commit_body(msg)
        assert body["run_id"] == decision["run_id"]

    def test_roundtrip_preserves_status(self):
        """status must survive the format → parse roundtrip."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        body = parse_commit_body(msg)
        assert body["status"] == decision["status"]

    def test_roundtrip_preserves_targeted_gaps(self):
        """targeted_gaps list must survive the format → parse roundtrip."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        body = parse_commit_body(msg)
        assert body["targeted_gaps"] == decision["targeted_gaps"]

    def test_roundtrip_preserves_why_section(self):
        """why section must survive the format → parse roundtrip."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        body = parse_commit_body(msg)
        assert body["why"]["prose_summary"] == decision["why"]["prose_summary"]

    def test_roundtrip_preserves_what_section(self):
        """what section must survive the format → parse roundtrip."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        msg = format_commit_message(decision)
        body = parse_commit_body(msg)
        assert body["what"]["short_description"] == decision["what"]["short_description"]

    def test_parse_commit_body_raises_on_missing_json(self):
        """parse_commit_body must raise if the message has no JSON body."""
        malformed = "proposal_id: P-001\nrun_id: R-001\nstatus: accepted"
        with pytest.raises(Exception):
            parse_commit_body(malformed)


# ---------------------------------------------------------------------------
# Criterion 3: Status transitions and invariants are enforced
# ---------------------------------------------------------------------------

class TestStatusInvariants:
    """
    create_decision_record must enforce the field invariants per
    docs/spec/01-data-structures/decision-record.md § Invariants.
    """

    # --- accepted ---

    def test_accepted_decision_is_valid(self):
        """A fully valid accepted decision must be accepted without raising."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        assert decision["status"] == "accepted"

    def test_accepted_requires_diff_reference(self):
        """accepted decisions must have a non-null diff_reference."""
        bad = _make_decision(what={**VALID_WHAT, "diff_reference": None})
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_accepted_requires_reviewed_at(self):
        """accepted decisions must have a non-null reviewed_at."""
        bad = _make_decision(reviewed_at=None)
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_accepted_forbids_author_failure_reason(self):
        """accepted decisions must not have author_failure_reason."""
        bad = _make_decision(author_failure_reason="some failure reason")
        with pytest.raises(Exception):
            create_decision_record(bad)

    # --- rejected ---

    def test_rejected_decision_is_valid(self):
        """A fully valid rejected decision must be accepted without raising."""
        rejected = _make_decision(
            status="rejected",
            human_reasoning="The change is too broad; prefer a focused approach.",
            what={**VALID_WHAT, "diff_reference": None},  # no diff needed for rejected
            author_failure_reason=None,
        )
        decision = create_decision_record(rejected)
        assert decision["status"] == "rejected"

    def test_rejected_requires_human_reasoning(self):
        """rejected decisions must have non-null human_reasoning."""
        bad = _make_decision(
            status="rejected",
            human_reasoning=None,
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_rejected_requires_reviewed_at(self):
        """rejected decisions must have non-null reviewed_at."""
        bad = _make_decision(
            status="rejected",
            human_reasoning="Too broad.",
            reviewed_at=None,
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_rejected_forbids_author_failure_reason(self):
        """rejected decisions must not have author_failure_reason."""
        bad = _make_decision(
            status="rejected",
            human_reasoning="Too broad.",
            author_failure_reason="shouldn't be here",
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    # --- author_failed ---

    def test_author_failed_decision_is_valid(self):
        """A fully valid author_failed decision must be accepted without raising."""
        author_failed = _make_decision(
            status="author_failed",
            reviewed_at="2024-01-15T10:30:00+00:00",
            human_reasoning=None,
            author_failure_reason="Could not locate the target file in the repository.",
            what={**VALID_WHAT, "diff_reference": None},
        )
        decision = create_decision_record(author_failed)
        assert decision["status"] == "author_failed"

    def test_author_failed_requires_author_failure_reason(self):
        """author_failed decisions must have non-null author_failure_reason."""
        bad = _make_decision(
            status="author_failed",
            reviewed_at="2024-01-15T10:30:00+00:00",
            author_failure_reason=None,
            what={**VALID_WHAT, "diff_reference": None},
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_author_failed_requires_reviewed_at(self):
        """author_failed decisions must have non-null reviewed_at."""
        bad = _make_decision(
            status="author_failed",
            reviewed_at=None,
            author_failure_reason="Could not produce a valid diff.",
            human_reasoning=None,
            what={**VALID_WHAT, "diff_reference": None},
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_author_failed_requires_null_diff_reference(self):
        """author_failed decisions must have null diff_reference."""
        bad = _make_decision(
            status="author_failed",
            reviewed_at="2024-01-15T10:30:00+00:00",
            author_failure_reason="Could not produce a valid diff.",
            what={**VALID_WHAT, "diff_reference": "some-commit"},  # non-null is wrong
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_author_failed_forbids_human_reasoning(self):
        """author_failed decisions must not have human_reasoning."""
        bad = _make_decision(
            status="author_failed",
            reviewed_at="2024-01-15T10:30:00+00:00",
            author_failure_reason="Could not produce a valid diff.",
            human_reasoning="shouldn't be here",
            what={**VALID_WHAT, "diff_reference": None},
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    # --- pending ---

    def test_pending_decision_is_valid(self):
        """A fully valid pending decision must be accepted without raising."""
        pending = _make_decision(
            status="pending",
            reviewed_at=None,
            human_reasoning=None,
            author_failure_reason=None,
        )
        decision = create_decision_record(pending)
        assert decision["status"] == "pending"

    def test_pending_requires_null_reviewed_at(self):
        """pending decisions must have null reviewed_at."""
        bad = _make_decision(
            status="pending",
            reviewed_at="2024-01-15T11:00:00+00:00",
            human_reasoning=None,
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_pending_requires_null_human_reasoning(self):
        """pending decisions must have null human_reasoning."""
        bad = _make_decision(
            status="pending",
            reviewed_at=None,
            human_reasoning="premature reasoning",
        )
        with pytest.raises(Exception):
            create_decision_record(bad)

    # --- superseded ---

    def test_superseded_requires_superseded_by(self):
        """superseded decisions must have non-null superseded_by."""
        bad = _make_decision(status="superseded", superseded_by=None)
        with pytest.raises(Exception):
            create_decision_record(bad)

    def test_superseded_decision_is_valid(self):
        """A fully valid superseded decision must be accepted without raising."""
        superseded = _make_decision(
            status="superseded",
            superseded_by="P-002",
        )
        decision = create_decision_record(superseded)
        assert decision["status"] == "superseded"

    # --- invalid status ---

    def test_invalid_status_raises(self):
        """create_decision_record must reject unknown status values."""
        bad = _make_decision(status="approved")  # not in spec
        with pytest.raises(Exception):
            create_decision_record(bad)

    @pytest.mark.parametrize("valid_status", [
        "accepted", "rejected", "pending", "superseded", "author_failed"
    ])
    def test_all_valid_statuses_are_accepted(self, valid_status):
        """Every spec-defined status value must be accepted by create_decision_record."""
        if valid_status == "accepted":
            decision = _make_decision(status="accepted")
        elif valid_status == "rejected":
            decision = _make_decision(
                status="rejected",
                human_reasoning="Too broad.",
                author_failure_reason=None,
            )
        elif valid_status == "pending":
            decision = _make_decision(
                status="pending",
                reviewed_at=None,
                human_reasoning=None,
                author_failure_reason=None,
            )
        elif valid_status == "superseded":
            decision = _make_decision(
                status="superseded",
                superseded_by="P-002",
            )
        elif valid_status == "author_failed":
            decision = _make_decision(
                status="author_failed",
                reviewed_at="2024-01-15T10:30:00+00:00",
                author_failure_reason="Could not produce a valid diff.",
                human_reasoning=None,
                what={**VALID_WHAT, "diff_reference": None},
            )
        result = create_decision_record(decision)
        assert result["status"] == valid_status

    # --- required fields ---

    @pytest.mark.parametrize("missing_field", [
        "proposal_id",
        "run_id",
        "batch_id",
        "created_at",
        "status",
        "why",
        "what",
        "how",
        "prediction",
        "prediction_outcome",
        "targeted_gaps",
        "authoring_addendum",
        "structural_tags",
    ])
    def test_create_rejects_missing_required_field(self, missing_field):
        """create_decision_record must reject records missing any required field."""
        bad = VALID_ACCEPTED_DECISION.copy()
        del bad[missing_field]
        with pytest.raises(Exception):
            create_decision_record(bad)

    # --- structural_tags enum values ---

    def test_invalid_change_type_raises(self):
        """structural_tags.change_type must be one of the spec-defined enum values."""
        bad = _make_decision(structural_tags={**VALID_STRUCTURAL_TAGS, "change_type": "upgrade"})
        with pytest.raises(Exception):
            create_decision_record(bad)

    @pytest.mark.parametrize("change_type", ["addition", "modification", "removal", "restructuring"])
    def test_valid_change_types_accepted(self, change_type):
        """Each valid change_type value must be accepted."""
        decision = _make_decision(structural_tags={**VALID_STRUCTURAL_TAGS, "change_type": change_type})
        result = create_decision_record(decision)
        assert result["structural_tags"]["change_type"] == change_type

    def test_invalid_surface_raises(self):
        """structural_tags.surface must be one of the spec-defined enum values."""
        bad = _make_decision(structural_tags={**VALID_STRUCTURAL_TAGS, "surface": "unknown"})
        with pytest.raises(Exception):
            create_decision_record(bad)

    @pytest.mark.parametrize("surface", ["claude_md", "skill", "agent", "hook", "settings", "mcp"])
    def test_valid_surfaces_accepted(self, surface):
        """Each valid surface value must be accepted."""
        decision = _make_decision(structural_tags={**VALID_STRUCTURAL_TAGS, "surface": surface})
        result = create_decision_record(decision)
        assert result["structural_tags"]["surface"] == surface

    def test_invalid_novelty_status_raises(self):
        """structural_tags.novelty_status must be one of the spec-defined enum values."""
        bad = _make_decision(structural_tags={**VALID_STRUCTURAL_TAGS, "novelty_status": "rare"})
        with pytest.raises(Exception):
            create_decision_record(bad)

    @pytest.mark.parametrize("novelty_status", ["normal", "forced_novelty", "null_baseline"])
    def test_valid_novelty_statuses_accepted(self, novelty_status):
        """Each valid novelty_status value must be accepted."""
        decision = _make_decision(structural_tags={**VALID_STRUCTURAL_TAGS, "novelty_status": novelty_status})
        result = create_decision_record(decision)
        assert result["structural_tags"]["novelty_status"] == novelty_status

    # --- prediction_outcome.status enum ---

    @pytest.mark.parametrize("po_status", [
        "not_yet_due", "overdue", "held", "not_held", "inconclusive"
    ])
    def test_valid_prediction_outcome_statuses_accepted(self, po_status):
        """Each valid prediction_outcome.status value must be accepted."""
        decision = _make_decision(
            prediction_outcome={**VALID_PREDICTION_OUTCOME, "status": po_status}
        )
        result = create_decision_record(decision)
        assert result["prediction_outcome"]["status"] == po_status

    def test_invalid_prediction_outcome_status_raises(self):
        """An invalid prediction_outcome.status must raise."""
        bad = _make_decision(
            prediction_outcome={**VALID_PREDICTION_OUTCOME, "status": "unknown"}
        )
        with pytest.raises(Exception):
            create_decision_record(bad)


# ---------------------------------------------------------------------------
# Cross-cutting caution: no scalar grades in decision records
# ---------------------------------------------------------------------------

class TestNoScalarGrades:
    """
    Cross-cutting caution: no scalar grades anywhere.
    Spec (decision-record.md § 'Explicitly excluded'):
      No separate effort-vs-quality prediction fields.
    Spec (IMPLEMENTATION.md § 'Implementation cautions'):
      No quality scores, effort scores, priority numbers.
    """

    FORBIDDEN_GRADE_KEYS = frozenset({
        "score", "grade", "priority", "severity", "confidence",
        "rank", "quality", "effort",
    })

    def test_created_decision_has_no_scalar_grade_fields(self):
        """The record returned by create_decision_record must contain no scalar grade keys."""
        decision = create_decision_record(VALID_ACCEPTED_DECISION.copy())
        for key in self.FORBIDDEN_GRADE_KEYS:
            assert key not in decision, (
                f"Scalar grade field '{key}' found in decision record. "
                "Spec explicitly excludes severity/confidence/priority scores."
            )
