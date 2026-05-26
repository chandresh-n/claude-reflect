---
description: Trigger a claude-reflect maintenance pass (regenerate summaries, transition stale gaps).
---

Run:
```bash
claude-reflect maintenance --repo "$(pwd)"
```

Maintenance:
- Regenerates the summary layer (idempotent)
- Transitions stale gap records
- Reconciles the gap-kind vocabulary

It runs automatically when thresholds in `config.yaml` are met. Manual invocation is always safe — maintenance is idempotent (running twice produces byte-identical state).

Report the run's summary output back to the user.
