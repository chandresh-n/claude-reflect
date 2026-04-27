# Meta-harness for Claude Code. Technical Spec

This directory specifies the components, contracts, and run-time behavior of a
meta-harness for Claude Code. Read in conjunction with the vision PRD (separate
document). The PRD answers *why*. This spec answers *what* and *how*, at the
level of interfaces, not implementation.

## What this spec does and does not do

**Does:** specify data structures, storage layers, agent roles, processes,
and invariants. Specifies contracts between components in enough detail
for each to be implemented in relative isolation.

**Does not:** specify implementation language, file encoding, specific
libraries, deployment tooling, or UX polish. Those are implementation
choices downstream of this spec.

## How to read

The directory is organized bottom-up: data structures first, then storage
that holds them, then agents that operate on them, then processes that
orchestrate the agents, then interfaces exposed to the human.

Each component file follows a consistent internal structure:

1. **Role**, one-paragraph summary of what this component is for.
2. **Inputs**, what it reads, from where.
3. **Outputs**, what it produces, to where.
4. **Schema** (data) or **Behavior** (agents/processes), the substance.
5. **Invariants**, what must always be true.
6. **Explicitly excluded**, what this component deliberately does not do.
7. **Cross-references**, pointers to related files.

## Directory layout

```
00-glossary.md                  Definitions used throughout
01-data-structures/             Schemas for records and outputs
  gap-record.md
  evaluator-output.md
  decision-record.md
  proposal.md
  archive-entry.md
02-storage/                     How data is held
  knowledge-base.md
  session-logs.md
  decisions-git.md
  summary-layer.md
03-agents/                      Entities that read and write
  evaluator.md
  proposer.md
  author.md
04-processes/                   Orchestration and maintenance
  maintenance.md
  run-loop.md
05-interfaces/                  Exposed to the human
  skill-invocation.md
  human-review.md
06-cross-cutting/               System-wide concerns
  invariants.md
  deferred.md
  scope-boundaries.md
```

## Terminology

All terms in **bold** on first use within a file are defined in
`00-glossary.md`. Later uses assume the reader has that glossary available.

## Target platform

Claude Code, initially. The system is intended to generalize to other coding
harnesses (Gemini CLI, OpenCode) later. The spec assumes Claude Code as the
target; points where generalization is relevant are called out explicitly
in `06-cross-cutting/scope-boundaries.md`.
