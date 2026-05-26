# Scope boundaries

The claude-reflect's scope is narrow by design. This file states what is
in scope, what is out of scope, and where the line is drawn. It
complements `06-cross-cutting/deferred.md`: deferred features may
become in-scope later; boundaries listed here are architectural
commitments unlikely to change.

---

## In scope

- A single human working in a single repository with a single
  underlying model.
- Configurations personal to that human-model-repository triple.
- On-demand invocation, triggered by the human through a Claude Code
  skill.
- Proposal generation against real session history, not synthetic
  benchmarks.
- Per-proposal human review with explicit acceptance.
- Persistent local knowledge base owned by the user.
- Evolution of the knowledge base over time as usage accumulates.
- Writing Claude Code configuration artifacts (skills, hooks, agents,
  `CLAUDE.md` sections, settings, MCP configurations).

## Out of scope

- **Benchmark-driven optimization.** The claude-reflect does not
  optimize against synthetic tasks. Signal comes from real session
  history.
- **Team-wide configuration consensus.** Different humans on the same
  team will produce different configurations through different
  claude-reflect instances. The claude-reflect does not enforce or
  facilitate cross-user agreement.
- **Fully autonomous configuration changes.** No proposal is ever
  applied without human review. The system proposes; the human
  decides.
- **Background or always-on operation.** Every run is explicitly
  invoked.
- **Cross-user or federated learning.** Knowledge bases are local.
  What the claude-reflect learns for user A is not shared with user
  B, even on the same repository.
- **Grading of sessions, configurations, or proposals.** No scalar
  judgments are computed or stored.
- **Automated adoption of forced-novelty or null-baseline proposals.**
  These are still subject to human review. The claude-reflect does not
  auto-apply any change.
- **External network access during runs.** All reads and writes are
  local. The claude-reflect does not call external APIs, download data,
  or communicate with remote services during a run.

## Where the line is

Several features sit near the boundary. Each is classified here with
reasoning:

### Maintenance writes to canonical state

Maintenance writes to gap records (status transitions, kind
reconciliations). This is within scope because the writes are
alignment operations, not judgments. Maintenance does not decide
which gaps matter or which kinds are correct; it reconciles drift and
surfaces staleness. The distinction is: maintenance aligns, agents
judge.

### Author agent produces configuration content

The author writes real content, skill files, hook configurations,
`CLAUDE.md` sections. This is within scope because the author's role
is authoring against a specification produced by the proposer. The
author does not decide what to write; it implements the proposer's
intent. The distinction is: the proposer decides, the author
implements.

### The summary layer synthesizes cross-session patterns

The summary layer's maintenance process produces pages that
synthesize across many sessions (session clusters, decision
lineages, exploration profiles). This is within scope because the
synthesis is a view, not a judgment. The pages describe patterns
that already exist in the canonical layers; they do not make new
claims beyond what is in the evidence.

### Predictions without verification

The spec includes predictions on every proposal but defers the
validation loop that checks them. This is in scope because
predictions have value without verification (grounding the
proposer's reasoning, helping the human decide). Verification is a
future extension.

---

## Anti-patterns

Things the implementation should avoid, even if they would appear to
improve the system:

- **Computing composite scores to simplify proposer reasoning.** The
  prohibition against scalar grades is architectural; it prevents
  drift and preserves the multi-dimensional nature of effort and
  quality. Any implementation that introduces "a single priority
  score" or "an aggregate quality number" has drifted from the spec.
- **Allowing agents to share context.** Separation of the evaluator,
  proposer, and author contexts is load-bearing. Implementations
  that fold two or more into a single agent for efficiency will
  reintroduce self-evaluation bias and coupling.
- **Treating the summary layer as authoritative for decisions.** The
  summary layer is a cache. Any proposer decision that depends
  solely on summary layer reads (and not canonical sources) is
  vulnerable to staleness.
- **Silently applying proposals.** Every proposal reaches the human.
  Even forced-novelty and null-baseline proposals. The system's
  discipline depends on the human being the final gate.
- **Hiding information from the human.** The human sees full
  rationale for every proposal. Including `exploration_rationale`
  for forced-novelty proposals. Hiding why a proposal exists biases
  the review.

## Cross-references

- Deferred features: `06-cross-cutting/deferred.md`.
- System-wide invariants: `06-cross-cutting/invariants.md`.
- The specific commitments each agent makes:
  - `03-agents/evaluator.md`
  - `03-agents/proposer.md`
  - `03-agents/author.md`
