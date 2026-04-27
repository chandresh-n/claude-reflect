# Deferred features

Features the spec acknowledges but leaves out of the first implementation.
Each is listed with its scope, the reason for deferring, and where in
the schema it is reserved (so future implementation has a clear place
to attach).

---

## Prediction validation loop

**What it would do:** When a decision's prediction measurement window
passes, check whether the prediction held. Transition
`prediction_outcome.status` to `held`, `not_held`, or `inconclusive`.
For falsified predictions, generate reversion proposals in the next
run.

**Why deferred:** The prediction validation mechanism is nontrivial.
It requires:

- Reliable interpretation of prose predictions (the prediction is not
  structured; it is the proposer's prose articulation of expected
  impact). Extracting a machine-verifiable claim from prose requires
  LLM work and its own tuning.
- A measurement process that runs on the measurement window's sessions
  and compares against the prediction.
- Integration with the run loop (when does validation happen? Is it
  its own phase?).

The value of predictions today is grounding the proposer's reasoning
and helping the human decide. Both work without verification.
Verification is a future extension.

**Reserved in schema:**

- `01-data-structures/decision-record.md`: `prediction_outcome` field
  is present with status values `not_yet_due`, `overdue`, `held`,
  `not_held`, `inconclusive`. Transitions are specified. In the
  first implementation, `not_yet_due` may transition to `overdue`
  based on elapsed measurement window; transitions past that wait for
  the validation loop.

---

## Task-type-aware reasoning

**What it would do:** Allow gap records and proposer reasoning to
explicitly attend to what kind of task a session was addressing. "Gaps
of kind X recur on tasks of type Y" becomes a first-class query.

**Why deferred:** Requires a task-type classifier, either rule-based
or LLM-based, with its own tuning. The classification is also not
obviously well-defined (tasks rarely fit clean categories). And the
deferred behavior emerges naturally through gap recurrence and
session clusters in the summary layer, a gap that only shows up on
a certain kind of task becomes identifiable through its evidence
pattern.

**Reserved in schema:**

- Gap records do not have a task-type field today. When added, it
  would be a new field, populated by the evaluator at observation
  time.
- Session-cluster pages in the summary layer are the natural place
  for emergent task-type patterns in the meantime.

---

## Cross-user or cross-repository learning

**What it would do:** Share gap records, decisions, or summary layer
pages across multiple users or multiple repositories. Allow patterns
identified in one context to inform proposals in another.

**Why deferred:** Explicitly out of scope for the first version. The
premise is per-user, per-repository optimization. Generalization
across contexts is a different project with different privacy and
scope considerations.

**Reserved in schema:** No schema slot. Knowledge bases are local; if
federation is ever added, it is an additional layer on top, not a
field on existing records.

---

## Generalization to non-Claude-Code harnesses

**What it would do:** Allow the meta-harness to target Gemini CLI,
OpenCode, or other coding harnesses with different configuration
surfaces.

**Why deferred:** The first version targets Claude Code. The
architecture accommodates generalization because the agent behaviors
are parameterizable over the target harness. But the author agent's
prompt and reference material are Claude-Code-specific in the first
implementation; generalization happens by adding harness-specific
author variants and a harness selector in the skill invocation.

**Reserved in schema:** No schema slot in the current spec. When
generalization is added, it likely appears as a new field on the
proposal or the batch indicating the target harness, or as a
configuration parameter of the meta-harness installation.

---

## Reference material refresh for the author

**What it would do:** Keep the author agent's Claude Code
documentation reference current as Claude Code evolves. New hook
types, new skill frontmatter fields, new MCP capabilities, the
author should be writing against current docs.

**Why deferred:** In the first implementation, the author's prompt
includes a snapshot of relevant documentation or points to a local
mirror. Refresh is manual: the human updates the reference material
when Claude Code evolves.

**Reserved in schema:** No schema slot. A later implementation might
add a periodic doc-refresh task (possibly as a maintenance operation,
or as its own lightweight process).

---

## Background or scheduled invocation

**What it would do:** Allow the meta-harness to run on a schedule
(nightly, weekly) or trigger on events (a session completing, a
certain time elapsing). Reduce the explicit-invocation burden on the
human.

**Why deferred:** The first version is strictly on-demand. The human
triggers. Background behavior introduces complexity (when to run, how
to handle results the human hasn't asked for, how to avoid drift
without human oversight) that is not worth carrying in the first
version.

**Reserved in schema:** No schema slot. The run loop's Phase 0
assumes human invocation.

---

## Proposal modification during review

**What it would do:** Allow the human, during Phase 7, to edit a
proposal's diff before accepting rather than only accepting or
rejecting as-is.

**Why deferred:** Complicates the decision record (what exactly did
the human accept, the original proposal or the modified version?).
Complicates provenance. The simpler pattern is: if the human wants a
different change, they reject the proposal with reasoning, and the
next run may produce a proposal in the direction the reasoning
suggested. This keeps proposals as clean, auditable units.

**Reserved in schema:** No schema slot. If added later, it would
require a new field on the decision record capturing the human's
modification to the diff.

---

## Multi-user coordination on the same repository

**What it would do:** Allow multiple humans sharing a repository to
each run the meta-harness and coordinate (or compete) over the
configuration.

**Why deferred:** The premise is single-human optimization. Two
humans using the same repository would run their own meta-harness
instances with their own knowledge bases. Coordinating their changes
to a shared configuration is a git-merge problem the human solves
manually, outside the meta-harness's scope.

**Reserved in schema:** No schema slot. Git's normal merge tooling
is the coordination mechanism.
