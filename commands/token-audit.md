---
description: Audit this machine's real Claude Code token burn (weekly/daily/by-model/by-session) from local transcripts. Nothing leaves the machine.
---

Run the bundled analyzer against the user's local Claude Code transcripts and report the findings:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/analyze_usage.py"
```

Then summarize for the user, plainly and without rounding up:
- Total API-equivalent burn and the worst week/day (this is the proxy for how fast plan limits are hit).
- The cache-read : new-input ratio (this is usually the whole story — re-reading context, not new work).
- Model mix (opus vs cheaper tiers) and subagent-offload share.
- Whether peak context size correlates with the expensive sessions.

Close with the two or three highest-leverage moves for THIS user's pattern (rotate context sooner, route mechanical work to a cheaper tier, consolidate tool round-trips) — the same levers Thrift's hooks enforce. Do not promise a savings number; point them at re-running this command to measure their own before/after.
