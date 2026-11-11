---
description: Add this Claude Code session to the shared voice (starts the voice daemon if needed)
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*)
---

Run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach $ARGUMENTS` with the Bash tool and a 10-minute timeout: the first run downloads about 600 MB. Report its output in one line, then its note about approvals in one sentence.
If it fails, show the error and the last 20 lines of `~/.claude-voice/daemon.log`.
Arguments: optional `--name <name>` to set how this session is called by voice.
