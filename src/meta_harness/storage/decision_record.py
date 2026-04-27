"""
Decision record read/write — Step 3 of the meta-harness build.

Spec ref: docs/spec/01-data-structures/decision-record.md

Public API:
- create_decision_record(data) -> dict
- format_commit_message(decision) -> str
- parse_commit_header(header) -> dict
- parse_commit_body(message) -> dict

Design constraints:
- Status-specific field invariants enforced at creation time.
- No scalar grades (no score, grade, priority, severity, etc.).
- Commit message format supports git log --grep queries on
  proposal_id, run_id, status, and targeted_gap.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = frozenset({
    "accepted", "rejected", "pending", "superseded", "author_failed"
})

VALID_CHANGE_TYPES = frozenset({
    "addition", "modification", "removal", "restructuring"
})

VALID_SURFACES = frozenset({
    "claude_md", "skill", "agent", "hook", "settings", "mcp"
})

VALID_NOVELTY_STATUSES = frozenset({
    "normal", "forced_novelty", "null_baseline"
})

VALID_PREDICTION_OUTCOME_STATUSES = frozenset({
    "not_yet_due", "overdue", "held", "not_held", "inconclusive"
})

REQUIRED_FIELDS = frozenset({
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
})

FORBIDDEN_GRADE_KEYS = frozenset({
    "score", "grade", "priority", "severity", "confidence",
    "rank", "quality", "effort",
})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class DecisionRecordError(ValueError):
    """Raised when a decision record fails schema validation or invariant checks."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_structural_tags(tags: dict) -> None:
    change_type = tags.get("change_type")
    if change_type not in VALID_CHANGE_TYPES:
        raise DecisionRecordError(
            f"Invalid structural_tags.change_type: {change_type!r}. "
            f"Must be one of {sorted(VALID_CHANGE_TYPES)}"
        )
    surface = tags.get("surface")
    if surface not in VALID_SURFACES:
        raise DecisionRecordError(
            f"Invalid structural_tags.surface: {surface!r}. "
            f"Must be one of {sorted(VALID_SURFACES)}"
        )
    novelty_status = tags.get("novelty_status")
    if novelty_status not in VALID_NOVELTY_STATUSES:
        raise DecisionRecordError(
            f"Invalid structural_tags.novelty_status: {novelty_status!r}. "
            f"Must be one of {sorted(VALID_NOVELTY_STATUSES)}"
        )


def _validate_prediction_outcome(po: dict) -> None:
    po_status = po.get("status")
    if po_status not in VALID_PREDICTION_OUTCOME_STATUSES:
        raise DecisionRecordError(
            f"Invalid prediction_outcome.status: {po_status!r}. "
            f"Must be one of {sorted(VALID_PREDICTION_OUTCOME_STATUSES)}"
        )


def _validate_status_invariants(data: dict) -> None:
    status = data["status"]
    what = data.get("what", {})

    if status == "accepted":
        if what.get("diff_reference") is None:
            raise DecisionRecordError(
                "accepted decisions must have a non-null what.diff_reference"
            )
        if data.get("reviewed_at") is None:
            raise DecisionRecordError(
                "accepted decisions must have a non-null reviewed_at"
            )
        if data.get("author_failure_reason") is not None:
            raise DecisionRecordError(
                "accepted decisions must not have author_failure_reason"
            )

    elif status == "rejected":
        if data.get("human_reasoning") is None:
            raise DecisionRecordError(
                "rejected decisions must have non-null human_reasoning"
            )
        if data.get("reviewed_at") is None:
            raise DecisionRecordError(
                "rejected decisions must have a non-null reviewed_at"
            )
        if data.get("author_failure_reason") is not None:
            raise DecisionRecordError(
                "rejected decisions must not have author_failure_reason"
            )

    elif status == "author_failed":
        if data.get("author_failure_reason") is None:
            raise DecisionRecordError(
                "author_failed decisions must have non-null author_failure_reason"
            )
        if data.get("reviewed_at") is None:
            raise DecisionRecordError(
                "author_failed decisions must have non-null reviewed_at"
            )
        if what.get("diff_reference") is not None:
            raise DecisionRecordError(
                "author_failed decisions must have null what.diff_reference"
            )
        if data.get("human_reasoning") is not None:
            raise DecisionRecordError(
                "author_failed decisions must not have human_reasoning"
            )

    elif status == "pending":
        if data.get("reviewed_at") is not None:
            raise DecisionRecordError(
                "pending decisions must have null reviewed_at"
            )
        if data.get("human_reasoning") is not None:
            raise DecisionRecordError(
                "pending decisions must have null human_reasoning"
            )

    elif status == "superseded":
        if data.get("superseded_by") is None:
            raise DecisionRecordError(
                "superseded decisions must have non-null superseded_by"
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_decision_record(data: dict) -> dict:
    """
    Validate *data* against the decision record schema and return it.

    Enforces:
    - All required fields present.
    - status is one of the spec-defined values.
    - Status-specific field invariants (accepted, rejected, author_failed,
      pending, superseded).
    - structural_tags enum values.
    - prediction_outcome.status enum values.
    - No scalar grade fields.

    Raises DecisionRecordError (a ValueError subclass) on any violation.
    Returns the validated dict (same object, not a deep copy).
    """
    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise DecisionRecordError(f"Missing required field: {field!r}")

    # Status enum
    status = data["status"]
    if status not in VALID_STATUSES:
        raise DecisionRecordError(
            f"Invalid status: {status!r}. Must be one of {sorted(VALID_STATUSES)}"
        )

    # Status-specific invariants
    _validate_status_invariants(data)

    # structural_tags enum values
    _validate_structural_tags(data["structural_tags"])

    # prediction_outcome.status enum
    _validate_prediction_outcome(data["prediction_outcome"])

    # No scalar grades (cross-cutting caution)
    for key in FORBIDDEN_GRADE_KEYS:
        if key in data:
            raise DecisionRecordError(
                f"Scalar grade field {key!r} found in decision record. "
                "Spec explicitly excludes severity/confidence/priority scores."
            )

    return dict(data)


def format_commit_message(decision: dict) -> str:
    """
    Produce a git commit message encoding the decision record.

    Format:
        proposal_id: <id>
        run_id: <id>
        status: <status>
        targeted_gap: <gap1>
        targeted_gap: <gap2>

        <JSON body>

    The structured header lines support git log --grep queries.
    The JSON body carries the full decision record for lossless roundtrip.
    """
    header_lines = [
        f"proposal_id: {decision['proposal_id']}",
        f"run_id: {decision['run_id']}",
        f"status: {decision['status']}",
    ]
    for gap in decision.get("targeted_gaps", []):
        header_lines.append(f"targeted_gap: {gap}")

    header = "\n".join(header_lines)
    body = json.dumps(decision, indent=2)
    return f"{header}\n\n{body}"


def parse_commit_header(header: str) -> dict:
    """
    Parse a commit message header (or full commit message) and extract the
    four structured fields: proposal_id, run_id, status, targeted_gaps.

    The function is line-oriented: it reads every line looking for the
    recognised key: value patterns and ignores anything else (including
    the JSON body when called on a full commit message).

    Raises DecisionRecordError if proposal_id, run_id, or status are absent.
    """
    result: dict = {
        "proposal_id": None,
        "run_id": None,
        "status": None,
        "targeted_gaps": [],
    }

    for line in header.splitlines():
        line = line.strip()
        if line.startswith("proposal_id: "):
            result["proposal_id"] = line[len("proposal_id: "):]
        elif line.startswith("run_id: "):
            result["run_id"] = line[len("run_id: "):]
        elif line.startswith("status: "):
            result["status"] = line[len("status: "):]
        elif line.startswith("targeted_gap: "):
            result["targeted_gaps"].append(line[len("targeted_gap: "):])

    if result["proposal_id"] is None:
        raise DecisionRecordError("Missing proposal_id in commit header")
    if result["run_id"] is None:
        raise DecisionRecordError("Missing run_id in commit header")
    if result["status"] is None:
        raise DecisionRecordError("Missing status in commit header")

    return result


def parse_commit_body(message: str) -> dict:
    """
    Extract and parse the JSON body from a full commit message produced by
    format_commit_message.

    The body is separated from the header by a blank line (\n\n).

    Raises DecisionRecordError if no valid JSON body is present.
    """
    parts = message.split("\n\n", 1)
    if len(parts) < 2:
        raise DecisionRecordError(
            "No JSON body found in commit message: missing blank-line separator"
        )
    body = parts[1].strip()
    if not body:
        raise DecisionRecordError(
            "No JSON body found in commit message: body section is empty"
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DecisionRecordError(
            f"Invalid JSON in commit body: {exc}"
        ) from exc
