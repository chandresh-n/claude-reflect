---
description: Report claude-reflect knowledge base state for the current repository.
---

Run:
```bash
claude-reflect status --repo "$(pwd)"
```

Then summarize:
- Whether the knowledge base is initialized
- Number of gap records tracked
- Number of archive entries (configuration history)
- Number of completed runs

If the knowledge base is uninitialized (`{"initialized": false}`), tell the user they can initialize it implicitly by running `/claude-reflect:review`.

If `claude-reflect` isn't on PATH, suggest running `/claude-reflect:setup`.
