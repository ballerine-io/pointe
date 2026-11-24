---
description: Join this Claude Code session to Pointe (starts Pointe if needed; on a first run, points to /pointe:setup)
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe node status:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-first-run:*)
---

First run `${CLAUDE_PLUGIN_ROOT}/bin/voice-first-run --needed`. If it prints `needed`, Pointe has never been set up on this Mac: say in
one line "Pointe is not set up on this Mac yet: run `/pointe:setup` (about 5 minutes); it joins this session at the end.", and do not run anything below.

Otherwise run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach $ARGUMENTS` with the Bash tool and a 10-minute timeout: the first run downloads about 180 MB (less on a node, which installs no voice models). Report its output in one line, then its note about approvals in one sentence.
If its output says `"node": true`, this machine is a node: the call, its page and the phone app are on the hub it names, not here. Then say in one line that this session joined the voice on that hub, and that its permission prompts go there while a call is up and stay in this terminal otherwise.
If it fails because a key was refused, say so in one line and offer to fix it: `${CLAUDE_PLUGIN_ROOT}/bin/pointe key <vendor>` opens the vendor's page and a Mac window, checks the new key and restarts Pointe; then run `claude-voice-attach` again.
If it fails otherwise, show the error and the last 20 lines of `~/.claude-voice/daemon.log`; on a node, show the output of `${CLAUDE_PLUGIN_ROOT}/bin/pointe node status` instead.
Arguments: optional `--name <name>` to set how this session is called by voice.
