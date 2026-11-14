---
description: Show which vendor fills each Pointe role, and what is missing
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/pointe node status:*)
---

Run `${CLAUDE_PLUGIN_ROOT}/bin/voice-doctor $ARGUMENTS` with the Bash tool. Show its output, then name the one step that fixes what is missing, if anything is.
Also run `${CLAUDE_PLUGIN_ROOT}/bin/pointe node status`. If it says this machine is paired with a hub, it is a node of another Mac's voice: show that output first. Name the hub, whether the link is up and its round trip, the hub's vendors (this machine's session transcripts go to them, masked), the sessions here, the key fingerprint, and whether remote taps are limited to requests that can be read out (`remote_taps: readable_only`) or not. A node has no keys and no voice models by design: never suggest adding a key or downloading models on it. If the link is down, the one step is to check that the hub is awake and reachable, then `pointe node status` again.
Arguments: optional `--live` makes one small paid call per text model.
