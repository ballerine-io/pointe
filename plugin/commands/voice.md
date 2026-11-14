---
description: Add this Claude Code session to the shared voice (starts the voice daemon if needed)
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe node status:*)
---

Run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach $ARGUMENTS` with the Bash tool and a 10-minute timeout: the first run downloads about 180 MB (less on a node, which installs no voice models). Report its output in one line, then its note about approvals in one sentence.
If `~/.claude-voice/node.json` exists, this machine is a node: the call, its page and the phone app are on the hub it names, not here. Then say in one line that this session joined the voice on that hub, and that its permission prompts go there while a call is up and stay in this terminal otherwise.
If it fails, show the error and the last 20 lines of `~/.claude-voice/daemon.log`; on a node, show the output of `${CLAUDE_PLUGIN_ROOT}/bin/pointe node status` instead.
Arguments: optional `--name <name>` to set how this session is called by voice.
