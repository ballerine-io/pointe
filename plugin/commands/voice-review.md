---
description: Read what the voice heard, said and knows in the latest call, to explain or fix how it behaved
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-log:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/voice-context:*)
---

Investigate the voice call with these read-only tools, then answer: $ARGUMENTS

- `${CLAUDE_PLUGIN_ROOT}/bin/voice-log --call`: the latest call in order: the opening context, every feed message in full, what the user said, what the bot said, every tool call with its result, refusals, barge-ins. Add `--session NAME` for one session, `--grep REGEX` to filter, or `--since HH:MM`.
- `${CLAUDE_PLUGIN_ROOT}/bin/voice-context`: what the voice model holds now, and its size. `voice-context all` for every message; `voice-context notes` for its notes on each session.

For each problem, quote what the voice was given next to what it said. That separates a knowledge problem (it was never told) from a judgment problem (it was told and said the wrong thing). The fixes live in the Pointe repo: `brief.py` (what is read and how reports are written), `daemon.py` (`INSTRUCTIONS`, `feed`, the gates). Check a change with `evals/sim.py` (real voice model, no audio; see `evals/README.md`) before asking to restart the daemon, since a restart drops a live call.

These records hold session content: do not paste them outside this session.
