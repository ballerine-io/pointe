---
description: Join this Claude Code session to Pointe (starts Pointe if needed; sets it up on a first run)
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe node status:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-first-run:*), Read(${CLAUDE_PLUGIN_ROOT}/plugin/commands/setup.md), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-daemon:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/install-uv:*), Bash(command -v:*), Bash(ls:*), Bash(sw_vers:*), Bash(open:*), Bash(echo:*), Bash(mkdir -p ~/.claude-voice:*), Bash(touch ~/.claude-voice/setup-done:*)
---

First run `${CLAUDE_PLUGIN_ROOT}/bin/voice-first-run --needed`. If it prints `needed`, Pointe has never been set up on this Mac: say in
one line "Pointe is not set up on this Mac yet, so I'll do that first: about 5 minutes.", then read
`${CLAUDE_PLUGIN_ROOT}/plugin/commands/setup.md` and follow it from step 1; its step 4 joins this session, so do not run anything below.

Otherwise run `${CLAUDE_PLUGIN_ROOT}/bin/claude-voice-attach $ARGUMENTS` with the Bash tool and a 10-minute timeout: the first run downloads about 180 MB (less on a node, which installs no voice models). Report its output in one line, then its note about approvals in one sentence.
If its output says `"node": true`, this machine is a node: the call, its page and the phone app are on the hub it names, not here. Then say in one line that this session joined the voice on that hub, and that its permission prompts go there while a call is up and stay in this terminal otherwise.
If it fails because a key was refused, say so in one line and offer to fix it: `${CLAUDE_PLUGIN_ROOT}/bin/pointe key <vendor>` opens the vendor's page and a Mac window, checks the new key and restarts Pointe; then run `claude-voice-attach` again.
If it fails otherwise, show the error and the last 20 lines of `~/.claude-voice/daemon.log`; on a node, show the output of `${CLAUDE_PLUGIN_ROOT}/bin/pointe node status` instead.
Arguments: optional `--name <name>` to set how this session is called by voice.
