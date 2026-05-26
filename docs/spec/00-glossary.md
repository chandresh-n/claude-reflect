# Glossary

Terms used throughout the spec. Listed alphabetically.

---

**Active configuration.** The current state of the `.claude/` directory and related
configuration files that Claude Code reads during normal work. There is exactly
one active configuration at any moment. Transitions happen when an accepted
proposal merges its diff.

**Archive entry.** A record representing a complete configuration state the
system has inhabited at some point. One per accepted proposal. Specified in
`01-data-structures/archive-entry.md`.

**Author.** An agent that takes a proposer's structured intent and produces a
concrete git diff realizing that intent. One invocation per proposal. Specified
in `03-agents/author.md`.

**Authoring addendum.** A structured specification from the proposer to the
author for a single proposal. Contains target paths, purpose, activation
conditions, constraints, examples, and style hints. Not shown to the human.
Committed to git alongside the proposal's rationale.

**Batch.** A set of proposals produced in a single run, presented to the human
for per-item review.

**Canonical layers.** The knowledge base layers that are authoritative sources
of truth: session logs (immutable), decisions (git-tracked), gap records, and
archive entries. Contrast with the summary layer, which is a regenerable
synthesis on top of the canonical layers.

**Configuration.** The full set of files Claude Code reads to shape its
behavior in a repository: `CLAUDE.md`, skills under `.claude/skills/`, agents
under `.claude/agents/`, hooks in `settings.json`, MCP definitions, permission
rules, model selection.

**Decision.** The record of a proposal plus the human's response to it. One
per proposal. Status can be `accepted`, `rejected`, `pending`, `superseded`,
or `author-failed`. Specified in `01-data-structures/decision-record.md`.

**Evaluator.** An agent that reads session logs and produces structured
observations of what happened, without scoring or recommending. Specified
in `03-agents/evaluator.md`.

**Evidence pointer.** A reference to a specific location in a session log,
consisting of a session identifier and a turn range (start and end turn
indices). Used to cite observations back to raw evidence.

**Forced novelty.** A rule requiring that, with some probability on a given
run, at least one proposal in the batch be structurally different from recent
proposals. Purpose: prevent collapse onto a local hill.

**Gap.** An observable quality-or-effort inefficiency identified by the
evaluator in a session. Gaps accumulate across sessions into gap records.

**Gap record.** A tracked pattern of inefficiency with frequency, evidence,
and status. Specified in `01-data-structures/gap-record.md`.

**Graded composite.** The conceptual notion of subjective quality assessment.
In this system, the graded composite is not computed as a scalar by any
component; it is a conclusion the proposer reaches when reasoning over
evaluator evidence and knowledge base history.

**Hard gates.** Objective binary signals about session outcomes: tests passed
or failed, build succeeded or not, linter clean or not. Configurations that
produce outputs breaking hard gates are disqualified regardless of subjective
scores.

**Intent (proposer intent).** What the proposer produces for a single
proposal: the four-part rationale plus structural tags plus the authoring
addendum. The intent is the proposer's complete output; the author converts
the intent into a concrete diff.

**Knowledge base.** The claude-reflect's persistent state, living in the repo.
Four layers: session logs (immutable JSONL), decisions (git), gap records and
archive entries (structured records), and the summary layer (regenerable
markdown synthesis). Specified in `02-storage/knowledge-base.md`.

**Maintenance.** A side-car process that consolidates the summary layer,
transitions gap statuses, reconciles vocabulary, and keeps synthesis views
fresh. Triggered by content thresholds. Specified in
`04-processes/maintenance.md`.

**Null baseline.** A specific kind of forced-novelty proposal: strip the
configuration to its minimum (no skills, no hooks, minimal `CLAUDE.md`) and
measure against current state. Purpose: detect whether the current
scaffolding is still doing useful work.

**Pareto frontier.** The set of configurations that are not dominated on both
effort and quality axes. Used as a conceptual model for how the archive
organizes configurations. Not a machine-operational data structure; the
summary layer synthesizes the frontier's shape when needed, but agents reason
over concrete dimensions (surface, count profile, semantic focus), not
directly over frontier position.

**Pass.** A sequence of turns within a session on the same sub-goal. A pass
ends when the human accepts the output or redirects to a different sub-goal.
Classified by the evaluator as refinement, clarification, correction, retry,
or successful-one-shot.

**Pending proposal.** A proposal presented to the human but not yet acted on
(typically because the human paused review mid-batch). Detected and
re-presented on the next run.

**Proposal.** A generated change to the configuration, consisting of a
four-part rationale (why, what, how, prediction), structural tags, an
authoring addendum, and (after the author runs) a diff reference. Specified
in `01-data-structures/proposal.md`.

**Proposer.** An agent that reads evaluator output and the knowledge base,
then produces proposals. Specified in `03-agents/proposer.md`.

**Run.** One invocation of the claude-reflect skill, from human invocation
through decision commit. Sequence of phases specified in
`04-processes/run-loop.md`.

**Session.** A single Claude Code invocation, from open to close, recorded
as a JSONL log in Claude Code's session log directory.

**Session window.** The set of sessions the human selects for a run,
specified as a date range and resolved by the skill to concrete session
identifiers.

**Skill (Claude Code skill).** A directory under `.claude/skills/<name>/`
containing a `SKILL.md` and related files. Activated by Claude Code based on
the skill's frontmatter. Part of the configuration the claude-reflect proposes
changes to.

**Skill (claude-reflect skill).** The Claude Code skill that invokes the
claude-reflect itself. Not to be confused with the skills that are part of the
configuration being optimized.

**Structural fingerprint.** Summary metadata for an archive entry describing
the configuration's structural shape: skill count, hook count, agent count,
`CLAUDE.md` length. Used by forced-novelty reasoning to identify
generalization-vs-specialization posture.

**Summary layer.** A regenerable collection of LLM-maintained markdown pages
that synthesize views over canonical layers. Not a source of truth. Specified
in `02-storage/summary-layer.md`.

**Supersession.** When a later decision replaces an earlier one. The earlier
decision's status transitions to `superseded`; its reference to the
superseding decision is populated.

**Turn.** A single exchange within a session: one human input and the
assistant's response (including any tool calls it generated). The atomic unit
of analysis for the evaluator.

**Window.** See "session window."
