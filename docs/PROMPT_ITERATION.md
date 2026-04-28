# Prompt iteration log

Tracks residual drift items for SOFT-gated steps (8, 9, 10).
Items here represent known differences between the spec's ideal and
what the current prompt reliably produces. Forward motion is allowed
per the plan.

---

## Step 8 — Evaluator agent

### Drift item 8-1: Pass type classification for friction within a single pass

The canned fixture classifies the tool-call-loop session as a single
`successful_one_shot` pass (turns 0–8) even though turns 1–3 exhibit a
repeated-search pattern. The spec defines `successful_one_shot` as
"length 1, produced acceptable output" — the fixture pass is length 9.

A live evaluator may classify this differently (e.g. as `refinement`
or split it into multiple passes). The eval set asserts pass_type is
from the valid vocabulary and that `contributing_gaps` is null for
`successful_one_shot`/`refinement`, so any valid classification passes
the gate. This is acceptable for v1 but may need prompt tuning to
produce more precise pass boundaries.

**Status:** known, acceptable for forward motion.
