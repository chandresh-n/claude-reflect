# Author

## Role

The author takes a single proposer intent and produces a concrete git
diff realizing it. Its job is authoring Claude Code configuration
artifacts, skills, hooks, agents, `CLAUDE.md` sections, settings, with
content that is specific, idiomatic, and honors the intent's constraints.

The author is a craftsman. It is not a decision-maker. It does not
reason about whether the change is a good idea or whether the gap is
worth targeting; those decisions were made by the proposer. The author
accepts the intent as a specification and implements against it.

One author is spawned per proposal. Each invocation is fresh-context.
The author does not see the batch as a whole; it sees only its
proposal's intent. If the batch has five proposals, five author
invocations happen in Phase 5b.

## Inputs

- The full proposer intent for one proposal:
  - The four-part rationale (`why`, `what`, `how`, `prediction`).
  - Structural tags.
  - The authoring addendum (the primary input for implementation).
- The current active configuration (readable from the active
  configuration git branch).
- Reference material pointed at by the addendum's `reference_material`.
- Access to documentation on Claude Code artifacts: how to write skills,
  hooks, agents, settings, MCP configs. The author's prompt includes
  (or points to) canonical docs. Keeping this reference material
  current is a responsibility of the claude-reflect installation (see
  `06-cross-cutting/deferred.md` for refresh strategy).

## Outputs

On success:

- A git branch containing the concrete diff. The branch is named by
  `proposal_id`. The diff modifies files as specified by the addendum's
  `actions`.
- The proposal's `what.diff_reference` is populated with the branch or
  commit hash. The proposal's `what.files_touched` is populated with
  the list of files the diff modifies.

On failure (the author cannot produce a valid diff):

- No git branch is created (or it is cleaned up).
- An `author_failure_reason` is produced: prose explaining why the
  author could not realize the intent. Examples: path conflict with
  existing file, the intent's constraints are internally
  contradictory, the activation conditions the addendum specifies are
  not expressible in the target harness's hook system.
- The proposal is marked `author_failed` at Phase 8 and committed to
  the decisions log with the failure reason. The human does not review
  author-failed proposals.

## Behavior

### Reading inputs

The author reads its proposal intent in full. It reads the addendum
carefully; the addendum is authoritative for what must be produced.

The author reads the current configuration state for:

- The target paths named in the addendum's `actions`, to see what
  currently exists there (for `modify` actions) or to verify no
  conflict (for `create` actions).
- Reference paths named in the addendum's `reference_material`, to
  understand existing conventions the author should match.
- Adjacent artifacts the author may need for context (e.g., if
  creating a new skill, the author reads existing skills to match
  their structure and tone).

### Producing the diff

For each action in the addendum:

- **create**: Write a new file at the specified path with content that
  honors `purpose`, `activation_conditions`, `behavior_constraints`,
  `examples`, and `style_hints`.
- **modify**: Read the existing file, produce a diff that changes it
  per the intent. The diff should be minimal, only the lines that
  need to change.
- **delete**: Remove the specified file.

For each authored file, the author honors Claude Code conventions. This
includes:

- Skill files under `.claude/skills/<n>/SKILL.md` with proper YAML
  frontmatter (description, activation triggers, etc.).
- Hooks in `settings.json` following Claude Code's hook schema.
- Agent definitions under `.claude/agents/` following the agent schema.
- `CLAUDE.md` sections matching existing tone and organization when
  modifying; establishing reasonable structure when creating.

### Commit discipline

The author creates a git branch named by `proposal_id`, commits its
diff there with a commit message summarizing what the diff does. The
commit message is brief and factual. Rationale lives in the proposal,
not in the commit.

### Failure modes

The author fails when it cannot honestly produce a diff that honors
the intent. Common cases:

- **Path conflict.** The addendum says `create: .claude/skills/foo/SKILL.md`
  but that file already exists with substantial content. The author
  does not silently overwrite; it fails and reports the conflict.
- **Contradictory constraints.** The addendum's `behavior_constraints`
  include requirements that cannot both be satisfied (e.g., "skill
  must fire on all file reads" and "skill must not fire in the
  `tests/` directory" when the activation mechanism doesn't support
  that exclusion).
- **Unknown artifact type.** The addendum specifies an action or
  artifact type the author does not know how to produce.
- **Insufficient specification.** The addendum is vague in a way the
  author cannot resolve by reading reference material. The author
  prefers failing to guessing.

In all failure cases, the author produces a specific
`author_failure_reason`: prose that names what could not be done and
why. This feedback is signal for the proposer on future runs.

## Behavioral directives (prompt-level)

- **Honor the addendum precisely.** The addendum is authoritative for
  what must be produced. Do not add capabilities not specified. Do not
  omit capabilities that are specified.
- **Match existing conventions.** When creating a new skill or modifying
  `CLAUDE.md`, read adjacent artifacts and match their tone, structure,
  and idiom. Consistency across the configuration is valuable.
- **Write for Claude Code.** The authored artifacts are consumed by
  Claude Code. Frontmatter syntax, file placement, activation triggers,
  hook event types, all must be valid for Claude Code's current
  version. When in doubt, consult the reference material.
- **Prefer clarity over brevity.** Authored artifacts will be read by
  future Claude Code invocations and by the human reviewing the
  proposal. Clarity in the artifact's own content is more valuable than
  token economy.
- **Fail honestly.** If the intent cannot be realized, do not fake it.
  Produce a failure reason the proposer can learn from.
- **No commentary in authored files.** The authored files should not
  contain meta-commentary about the proposer's intent, the rationale
  for the change, or the author's reasoning. Those live in the
  proposal and decision records. Authored files are the configuration
  itself.

## Invariants

- One author invocation per proposal. Fresh context each time.
- The author does not read other proposals in the batch. No
  cross-proposal coordination.
- The authored diff, if successful, merges cleanly into the active
  configuration branch.
- `files_touched` in the proposal matches the actual files in the
  produced diff.
- Failure produces a specific, actionable `author_failure_reason`. No
  generic failures like "could not complete."
- The author does not modify files outside the addendum's `actions`.
  If the addendum specifies creating `skill_X`, the author creates
  `skill_X` and nothing else.

## Explicitly excluded

- No access to the evaluator's output.
- No access to the knowledge base beyond the current configuration
  state and reference material.
- No access to other proposals in the batch.
- No human interaction.
- No reasoning about whether the change is a good idea.
- No scoring, grading, or ranking.
- No proposal modification. If the addendum seems wrong, the author
  fails; it does not "fix" the intent.

## Cross-references

- Proposal intent input: `01-data-structures/proposal.md` (specifically
  the `authoring_addendum` field).
- Failure captured in decision record:
  `01-data-structures/decision-record.md` (`author_failure_reason`,
  status `author_failed`).
- Active configuration branch: `02-storage/decisions-git.md`.
- Invoked per proposal in Phase 5b: `04-processes/run-loop.md`.
- Reference material refresh strategy: `06-cross-cutting/deferred.md`.
