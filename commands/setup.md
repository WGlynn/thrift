---
description: Configure Thrift — asks about Remem opt-in, context-window size, and strict tier-routing, then writes ~/.claude/.thrift/config.json.
---

Walk the user through Thrift setup. Ask, do not assume. Use the question tool so they choose:

1. **Context window size** — "Are you on the standard ~200k context window, or the 1M-context variant?"
   - 200k → keep the default rotation tiers (warn 120k / deliberate 160k / ceiling 185k).
   - 1M → set higher tiers (warn 600000 / deliberate 800000 / ceiling 950000).

2. **Strict tier-routing** — "Should Thrift BLOCK mechanical work that's delegated on the expensive (opus) tier until you pick a cheaper model, or just recommend it?"
   - Block → `tier_route_strict: true`. Recommend → `tier_route_strict: false` (default).

3. **Remem (opt-in)** — "Do you want to opt into Remem (github: darks0l/remem), an optional recall module that fetches specific facts instead of re-carrying full history? It requires installing Remem separately. Off by default."
   - Yes → `remem_enabled: true` (and point them to install Remem if they haven't).
   - No → `remem_enabled: false`.

Then write their choices to `~/.claude/.thrift/config.json` (create the dir if needed), merging over the defaults from `${CLAUDE_PLUGIN_ROOT}/thrift.config.example.json`. Confirm what you wrote and remind them a restart applies hook changes. If they ever want to pause Thrift entirely, `touch ~/.claude/.thrift/DISABLE`.
