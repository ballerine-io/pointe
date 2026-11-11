---
description: Show which vendor fills each Pointe role, and what is missing
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor:*)
---

Run `${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor $ARGUMENTS` with the Bash tool. Show its output, then name the one step that fixes what is missing, if anything is.
Arguments: optional `--live` makes one small paid call per text model.
