"""
Author agent

Takes a single proposer intent and produces a concrete git diff on a
proposal branch, or returns author_failed honestly. One author is
spawned per proposal; each invocation is fresh-context.

Spec ref:
- docs/spec/03-agents/author.md

Constraints:
- No scalar grades, no rankings, no scoring.
- Fresh context per invocation (context isolation).
- Honor the addendum precisely — no extras, no omissions.
- Fail honestly rather than fabricate a diff.
- No commentary in authored files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from claude_reflect.agents.claude_runner import ClaudeRunnerError, invoke_claude


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
<role>
You are the author in claude-reflect, a system that improves how an AI coding
agent works by changing its Claude Code configuration. A proposer has already
decided that a particular change is worth making and why; your job is to turn
that single decision into the concrete file content that realizes it. You are a
craftsman, not a decision-maker: you do not reweigh whether the change is a good
idea — that judgment is already made and is not yours to revisit.

Claude Code is configured across several surfaces, and you author across all of
them — not just CLAUDE.md. Depending on the intent you may write a new skill,
add or edit a CLAUDE.md section, register a hook and the script it runs, author
a validation/eval script that guards against regressions, define a subagent, or
adjust settings.json or .mcp.json. Each surface has its own format and its own
way of taking effect; producing a valid, idiomatic artifact for the *right*
surface is the whole job.

You run in fresh context, one invocation per proposal. You see only this
proposal — not the other proposals in the batch and not the evaluator's
evidence. The authoring addendum in your input is your specification; treat it
as authoritative for what must be produced.
</role>

<task>
Read the proposal intent — especially its authoring addendum — and produce the
file content that implements it on the surface it names. For each action in the
addendum, create, modify, or delete the named file so that the result honors the
addendum's purpose, activation conditions, behavior constraints, examples, and
style hints. If you cannot honestly produce content that honors the intent, fail
and say precisely why.
</task>

<inputs>
Your input contains the proposal's title, a read-only rationale (for context
only — do not act on it beyond the addendum), the structural tags (including the
target `surface`), and the authoring addendum: its purpose, activation
conditions, the list of actions ({type, target_path}), behavior constraints,
optional examples, style hints, and reference material. For modify and create
actions the current content at the target path is inlined so you can match
conventions and detect conflicts.
</inputs>

<surfaces>
The `surface` tag and each action's target_path tell you which surface to
author. When the tag is missing or ambiguous, infer the surface from the
target_path's location and extension. Author for the surface that was specified.
The conventions below are the stable shape of each surface; when a precise
identifier (a hook event name, a frontmatter key) is not certain for this
project's Claude Code version, confirm it against the inlined current file
content and the reference material rather than guessing — and fail honestly if a
required identifier cannot be confirmed.

CLAUDE.md — project memory, a markdown file loaded into every session, so it is
always-on context. Keep additions short, imperative, and deduplicated; do not
restate guidance already present. Edit or add the smallest section that carries
the rule, match the surrounding heading style, and place it near related
guidance. This is the cheapest surface but also the weakest — it nudges; it does
not enforce. Use it for guidance, not for things that must be guaranteed.

Skills — a directory .claude/skills/<name>/ whose name matches the frontmatter
`name` (lowercase letters, digits, hyphens; no spaces or uppercase). SKILL.md
has YAML frontmatter with `name` and `description`, then the instruction body.
Only `name` + `description` are loaded until the skill activates (progressive
disclosure), so the `description` must state both what the skill does AND when
to use it — that text is what makes the agent reach for it. Put procedures and
detail in the body; put large supporting material in scripts/, references/, or
assets/ under the skill directory and refer to it by relative path. Use a skill
when a task needs a reusable, on-demand procedure that is too large or too
situational to live in always-on memory.

Hooks (+ their scripts) — a hook is registered in settings.json under "hooks" →
<EventName> → a list of {matcher, hooks: [{type: "command", command, timeout?}]}.
Common events include PreToolUse, PostToolUse, UserPromptSubmit, Stop,
SubagentStop, SessionStart, SessionEnd, PreCompact, and Notification; confirm the
exact event name and matcher semantics against the inlined settings and reference
material. The hook command receives a JSON object on stdin (fields include
session_id, transcript_path, cwd, hook_event_name, and for tool events tool_name
and tool_input). It controls behaviour by exit code — 0 proceeds, 2 blocks the
action and feeds the script's stderr back to the agent, other codes are
non-blocking errors — and may also print a JSON object on stdout (for example
{"continue": ..., "decision": ..., "reason": ..., "hookSpecificOutput":
{"additionalContext": ...}}). Use a hook when the change must actually fire
deterministically (enforce, block, inject context) rather than merely advise.
If the hook runs a script, author the script too — a hook pointing at a missing
script is broken. Place scripts under .claude/hooks/, give them a shebang, and
have the settings command invoke them through their interpreter
("python3 .claude/hooks/x.py", "bash .claude/hooks/x.sh") so they do not depend
on an executable bit you cannot set here.

Validation / eval scripts — scripts that assert an invariant about the agent's
output or the repo state so a future regression is caught. Write them
deterministic, dependency-light, fast, and self-contained, with an explicit
pass/fail (clear message, non-zero exit on failure). Wire them to actually run —
usually a hook (e.g. on Stop or PostToolUse) whose command runs the script and
relies on exit code 2 to block on failure — or as the standalone script the
addendum names. A check that never runs, or that always passes, is worse than
none: make it test something real and grounded in the intent.

Subagents — a markdown file under .claude/agents/ with YAML frontmatter (`name`,
`description`, optional `tools` as a comma list, optional `model`) and a body
that is the agent's system prompt. The `description` drives when the agent is
delegated to. Confirm the exact path and layout against existing agents in the
repo and match them.

Settings & MCP — settings.json holds permissions (allow/deny/defaultMode), env,
model, hooks, and similar keys; .mcp.json holds "mcpServers", each a stdio entry
{command, args, env} or an http entry {type: "http", url}. Editing either is a
JSON merge: preserve every existing key and append to the relevant arrays/objects;
never drop or rewrite unrelated configuration, and keep the file valid JSON.
</surfaces>

<output_format>
Return one JSON object, in exactly one of two shapes.

On success:
{
  "status": "success",
  "proposal_id": string,            // echo the input proposal_id
  "files": [
    {
      "path": string,               // repo-relative path, matching an action's target_path
      "action": "create" | "modify" | "delete",
      "content": string | null      // the full file content for create/modify; null for delete
    }
  ]
}

On failure:
{
  "status": "author_failed",
  "proposal_id": string,            // echo the input proposal_id
  "author_failure_reason": string   // specific, actionable reason (see rules)
}
</output_format>

<rules>
- Author the surface the addendum specifies, in full. If the actions or surface
  call for a skill, hook, script, subagent, settings, or MCP change, produce that
  artifact — do not substitute an easier surface, and never downsize a
  skill/hook/script/subagent into a CLAUDE.md note or leave a placeholder or TODO.
  A new skill, hook, or script must be complete and runnable, not a stub; a hook
  and the script it invokes are authored together in the same response. If you
  believe a different surface would serve the intent better, you still author what
  was specified or fail honestly — you do not silently switch surfaces.
- Honor the addendum exactly: implement every capability it specifies and add
  none that it does not. Your discretion is in craft, not in scope.
- Produce one files entry per action (a hook change that needs a script produces
  the settings edit AND the script as two entries). For "modify", return the
  complete updated file — change only what the intent requires, but output the
  whole file, not a patch. For "create", write the new file in full. For
  "delete", set content to null.
- Write valid, idiomatic artifacts for the target surface, following the
  conventions in <surfaces>. When a precise identifier is uncertain, consult the
  inlined current content and reference material rather than guessing.
- Match the surrounding conventions — tone, structure, headings, naming — of the
  existing artifact or its neighbours. Consistency across the configuration is
  itself valuable.
- Prefer clarity over brevity in what you write. These artifacts are read by
  future agent runs and by the reviewing human; clear content is worth more than
  saved tokens.
- Put no meta-commentary in authored files. The files are the configuration
  itself — they must not mention the proposer's intent, the rationale, this task,
  or your own reasoning. That context lives in the proposal and decision records.
- Fail honestly rather than fake it. Return status "author_failed" when you
  genuinely cannot realize the intent, and name the specific blocker: a path
  conflict (the create target already has substantial content), internally
  contradictory behavior constraints, an artifact type or activation Claude Code
  does not support, or a specification too vague to resolve from the reference
  material. A reason like "could not complete" is not acceptable — the proposer
  learns from this text on future runs, so it must name what could not be done
  and why.
- Produce no scores, grades, or rankings of any kind.
</rules>

<example>
<input>
## Proposal: prop-101
Title: Add a grep-first skill for locating code
Structural tags: surface=skill, change_type=addition
## Authoring addendum
Purpose: A reusable procedure that makes the agent search the project before
opening speculative file paths when it needs to locate code.
### Actions
- create: .claude/skills/grep-first/SKILL.md
### Behavior constraints
- The description must say what the skill does and when to use it.
- Keep the body to a few concrete steps.
</input>
<output>
{"status": "success", "proposal_id": "prop-101",
 "files": [{"path": ".claude/skills/grep-first/SKILL.md", "action": "create",
   "content": "---\\nname: grep-first\\ndescription: Use when locating a file, symbol, constant, or definition in the codebase. Searches the project before opening any speculative path.\\n---\\n\\nWhen you need to find where something lives:\\n\\n1. Run a project-wide search (ripgrep/grep) for the symbol or filename first.\\n2. Open only the path(s) the search returns.\\n3. Fall back to broadening the search pattern, not to guessing directories.\\n"}]}
</output>
</example>

<example>
<input>
## Proposal: prop-102
Title: Block stopping when tests were deleted
Structural tags: surface=hook, change_type=addition
## Authoring addendum
Purpose: When the agent tries to end its turn, fail if any test file was deleted
during the session, so test-deletion regressions are caught.
### Actions
- modify: .claude/settings.json
  Current content:
  ```
  {"permissions": {"allow": ["Bash(pytest:*)"]}}
  ```
- create: .claude/hooks/forbid_test_deletion.py
### Behavior constraints
- The hook must block (not merely warn) when a test file is missing.
</input>
<output>
{"status": "success", "proposal_id": "prop-102",
 "files": [
   {"path": ".claude/settings.json", "action": "modify",
    "content": "{\\n  \\"permissions\\": {\\"allow\\": [\\"Bash(pytest:*)\\"]},\\n  \\"hooks\\": {\\n    \\"Stop\\": [\\n      {\\"matcher\\": \\"*\\", \\"hooks\\": [{\\"type\\": \\"command\\", \\"command\\": \\"python3 .claude/hooks/forbid_test_deletion.py\\"}]}\\n    ]\\n  }\\n}\\n"},
   {"path": ".claude/hooks/forbid_test_deletion.py", "action": "create",
    "content": "#!/usr/bin/env python3\\nimport json, subprocess, sys\\n\\njson.load(sys.stdin)  # consume the hook payload\\ndeleted = subprocess.run([\\"git\\", \\"diff\\", \\"--name-only\\", \\"--diff-filter=D\\", \\"HEAD\\"], capture_output=True, text=True).stdout.split()\\nmissing = [p for p in deleted if \\"test\\" in p]\\nif missing:\\n    sys.stderr.write(\\"Refusing to stop: test files were deleted: \\" + \\", \\".join(missing))\\n    sys.exit(2)\\nsys.exit(0)\\n"}
 ]}
</output>
</example>

Return only the JSON object — no markdown fences, no text before or after it.
"""


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def _create_proposal_branch(repo: Path, proposal_id: str) -> str:
    """Create a proposal branch and return the branch name."""
    branch_name = f"claude-reflect/proposal/{proposal_id}"
    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return branch_name


def _commit_on_branch(repo: Path, files_touched: List[str], message: str) -> str:
    """Stage files and commit. Return the commit hash."""
    for f in files_touched:
        subprocess.run(
            ["git", "add", f],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    # Get commit hash
    hash_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return hash_result.stdout.strip()


def _cleanup_branch(repo: Path, original_branch: str, branch_name: str) -> None:
    """Switch back to the original branch and delete the proposal branch."""
    subprocess.run(
        ["git", "checkout", original_branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )


def _get_current_branch(repo: Path) -> str:
    """Return the current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _switch_branch(repo: Path, branch: str) -> None:
    """Switch to a branch."""
    subprocess.run(
        ["git", "checkout", branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------


def _read_existing_file(repo: Path, target_path: str) -> Optional[str]:
    """Read an existing file from the repo. Returns None if not found."""
    full_path = repo / target_path
    if full_path.exists():
        try:
            return full_path.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _read_reference_material(repo: Path, ref_paths: List[str]) -> str:
    """Read reference material files listed in the addendum."""
    parts = []
    for ref_path in ref_paths:
        full_path = repo / ref_path
        if full_path.is_file():
            try:
                content = full_path.read_text(encoding="utf-8")
                parts.append(f"### Reference: {ref_path}\n{content}")
            except OSError:
                parts.append(f"### Reference: {ref_path}\n(unreadable)")
        elif full_path.is_dir():
            # List files in the directory for context
            try:
                entries = sorted(full_path.iterdir())
                file_list = [str(e.relative_to(repo)) for e in entries if e.is_file()]
                parts.append(
                    f"### Reference directory: {ref_path}\n"
                    f"Files: {', '.join(file_list) if file_list else '(empty)'}"
                )
                # Read first few files for convention matching
                for entry in entries[:3]:
                    if entry.is_file():
                        try:
                            content = entry.read_text(encoding="utf-8")
                            parts.append(
                                f"#### {entry.relative_to(repo)}\n{content[:2000]}"
                            )
                        except OSError:
                            continue
            except OSError:
                parts.append(f"### Reference directory: {ref_path}\n(unreadable)")
        else:
            parts.append(f"### Reference: {ref_path}\n(not found)")
    return "\n\n".join(parts) if parts else "No reference material."


def _format_intent_for_prompt(intent: dict, repo: Path) -> str:
    """Format the full proposer intent and context for the author prompt."""
    parts = []

    # Proposal metadata
    parts.append(f"## Proposal: {intent.get('proposal_id', 'unknown')}")
    parts.append(f"Title: {intent.get('title', '')}")
    parts.append("")

    # Rationale (for context, not for the author to modify)
    parts.append("## Rationale (read-only context)")
    why = intent.get("why", {})
    parts.append(f"Summary: {why.get('prose_summary', '')}")
    parts.append("")

    # The authoritative input: the authoring addendum
    addendum = intent.get("authoring_addendum", {})
    parts.append("## Authoring addendum (YOUR PRIMARY INPUT)")
    parts.append(f"Purpose: {addendum.get('purpose', '')}")
    parts.append(
        f"Activation conditions: {addendum.get('activation_conditions', 'N/A')}"
    )
    parts.append("")

    # Actions
    parts.append("### Actions")
    for action in addendum.get("actions", []):
        parts.append(f"- {action.get('type', '?')}: {action.get('target_path', '?')}")
        # For modify actions, show current file content
        if action.get("type") == "modify":
            existing = _read_existing_file(repo, action["target_path"])
            if existing is not None:
                parts.append(f"  Current content:\n```\n{existing}\n```")
            else:
                parts.append("  (file not found — this may be an error)")
        elif action.get("type") == "create":
            existing = _read_existing_file(repo, action["target_path"])
            if existing is not None:
                parts.append(
                    f"  WARNING: file already exists at this path. "
                    f"Current content:\n```\n{existing}\n```"
                )
    parts.append("")

    # Behavior constraints
    constraints = addendum.get("behavior_constraints", [])
    if constraints:
        parts.append("### Behavior constraints")
        for c in constraints:
            parts.append(f"- {c}")
        parts.append("")

    # Examples
    examples = addendum.get("examples", [])
    if examples:
        parts.append("### Examples")
        for ex in examples:
            parts.append(f"```\n{ex}\n```")
        parts.append("")

    # Style hints
    style = addendum.get("style_hints", "")
    if style:
        parts.append(f"### Style hints\n{style}")
        parts.append("")

    # Reference material
    ref_paths = addendum.get("reference_material", [])
    if ref_paths:
        ref_content = _read_reference_material(repo, ref_paths)
        parts.append(f"## Reference material\n{ref_content}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def _parse_author_output(raw_text: str) -> dict:
    """Parse the author's raw text response into a structured dict.

    Tolerant of preamble prose and ```json``` fences — the model sometimes
    emits both even when the system prompt forbids markdown wrapping.
    """
    from claude_reflect.agents._json_parsing import extract_json

    try:
        output = extract_json(raw_text)
    except json.JSONDecodeError as e:
        raise AuthorError(
            f"Failed to parse author output as JSON: {e}\n"
            f"Raw text (first 500 chars): {raw_text[:500]}"
        ) from e

    if not isinstance(output, dict):
        raise AuthorError(
            f"Author output is not a JSON object (got {type(output).__name__})"
        )

    # Validate minimal structure
    if "status" not in output:
        raise AuthorError("Author output missing 'status' field")
    if "proposal_id" not in output:
        raise AuthorError("Author output missing 'proposal_id' field")

    status = output["status"]
    if status not in ("success", "author_failed"):
        raise AuthorError(f"Invalid author status: {status}")

    if status == "success":
        if not output.get("files"):
            raise AuthorError("Successful author output has no 'files'")
    elif status == "author_failed":
        reason = output.get("author_failure_reason", "")
        if not reason or len(reason.strip()) < 10:
            raise AuthorError(
                "author_failed without a specific author_failure_reason"
            )

    return output


# ---------------------------------------------------------------------------
# File application
# ---------------------------------------------------------------------------


def _apply_file_actions(repo: Path, files: List[dict]) -> List[str]:
    """
    Apply file actions from the author's output to disk.

    Returns the list of file paths that were touched.
    """
    touched = []
    for file_spec in files:
        path = file_spec["path"]
        action = file_spec["action"]
        full_path = repo / path

        if action == "create":
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(file_spec["content"], encoding="utf-8")
            touched.append(path)
        elif action == "modify":
            if not full_path.exists():
                raise AuthorError(
                    f"Cannot modify non-existent file: {path}"
                )
            full_path.write_text(file_spec["content"], encoding="utf-8")
            touched.append(path)
        elif action == "delete":
            if full_path.exists():
                full_path.unlink()
                touched.append(path)
        else:
            raise AuthorError(f"Unknown file action: {action}")

    return touched


# ---------------------------------------------------------------------------
# Main author function
# ---------------------------------------------------------------------------


def author(
    intent: dict,
    repo: Path,
    model: str = "claude-sonnet-4-6",
    commit_changes: bool = True,
) -> dict:
    """
    Run the author agent on a single proposer intent.

    Takes the intent, reads current configuration state, invokes the LLM
    to produce file content, applies changes to a proposal branch, and
    returns the result.

    Args:
        intent: The full proposer intent dict (one proposal from the batch).
        repo: Root of the target git repository.
        model: Anthropic model to use.
        commit_changes: Whether to commit changes to a git branch.

    Returns:
        Author output dict matching the author output schema:
        - On success: status, proposal_id, diff_reference, files_touched, branch_name
        - On failure: status, proposal_id, author_failure_reason, diff_reference=null,
          files_touched=null, branch_name=null

    Raises:
        AuthorError: If the agent encounters an unrecoverable error.
    """
    proposal_id = intent.get("proposal_id")
    if not proposal_id:
        raise AuthorError("Intent missing proposal_id")

    # Format prompt context
    context = _format_intent_for_prompt(intent, repo)

    # Invoke the author agent (fresh context via claude CLI)
    try:
        raw_text = invoke_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=context,
            model=model,
            label=f"author {proposal_id}",
        )
    except ClaudeRunnerError as e:
        raise AuthorError(f"Claude invocation failed: {e}") from e

    # Parse the output
    agent_output = _parse_author_output(raw_text)

    # Handle failure
    if agent_output["status"] == "author_failed":
        return {
            "status": "author_failed",
            "proposal_id": proposal_id,
            "author_failure_reason": agent_output["author_failure_reason"],
            "diff_reference": None,
            "files_touched": None,
            "branch_name": None,
        }

    # Handle success — apply files and optionally commit
    files = agent_output.get("files", [])
    if not files:
        return {
            "status": "author_failed",
            "proposal_id": proposal_id,
            "author_failure_reason": "Agent reported success but produced no files.",
            "diff_reference": None,
            "files_touched": None,
            "branch_name": None,
        }

    if not commit_changes:
        # Return success without git operations (for testing)
        files_touched = [f["path"] for f in files]
        return {
            "status": "success",
            "proposal_id": proposal_id,
            "diff_reference": "no-commit",
            "files_touched": files_touched,
            "branch_name": f"claude-reflect/proposal/{proposal_id}",
        }

    # Git operations: create branch, apply files, commit
    original_branch = _get_current_branch(repo)
    branch_name = None
    try:
        branch_name = _create_proposal_branch(repo, proposal_id)
        files_touched = _apply_file_actions(repo, files)
        commit_hash = _commit_on_branch(
            repo,
            files_touched,
            f"proposal {proposal_id}: {intent.get('title', 'authored change')}",
        )
        # Return to original branch
        _switch_branch(repo, original_branch)
        return {
            "status": "success",
            "proposal_id": proposal_id,
            "diff_reference": commit_hash,
            "files_touched": files_touched,
            "branch_name": branch_name,
        }
    except Exception as e:
        # Cleanup on failure
        if branch_name:
            _cleanup_branch(repo, original_branch, branch_name)
        else:
            try:
                _switch_branch(repo, original_branch)
            except Exception:
                pass
        return {
            "status": "author_failed",
            "proposal_id": proposal_id,
            "author_failure_reason": f"Git operation failed: {e}",
            "diff_reference": None,
            "files_touched": None,
            "branch_name": None,
        }


def author_from_fixture(
    intent: dict,
    repo: Path,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    Convenience: run the author without git commit operations.

    Suitable for fixture-based testing where we want to validate the
    agent's output shape without modifying git state.
    """
    return author(intent, repo, model=model, commit_changes=False)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class AuthorError(Exception):
    """Raised when the author agent fails to produce valid output."""
