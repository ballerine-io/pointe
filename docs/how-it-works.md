# How it works

```
browser tab or phone app (one WebSocket, echo cancel, shows the active session)
  -> ears: speech to text -> echo guard (drops the bot's own voice)
  -> brain: a text model decides, through tools (speak, send_to_claude_code, list_sessions, switch_session,
     ask_about_session). Speech is a tool call, so code checks each reply before you hear it.
  -> mouth: text to speech
  -> one worker per registered Claude Code session
       in:  its voice channel (launch mode) or its inbox socket (attach mode)
       out: its transcript, followed live; a reader model turns each final message into what you must hear
```

Built on [Pipecat](https://github.com/pipecat-ai/pipecat).

## Rules enforced in code

- **Permissions:** the daemon builds the read-out from what will run, and only your own yes and nothing else, right after that
  line, approves a prompt, and only the active session's. No model wording can open this window, and any other speech closes it.
  "Okay, tell me more" does not count. Neither does a yes to any other question, or one older than two minutes. The page shows
  the exact request.
- **Targeting:** a request or a switch goes to another session only if you said its name, or said yes to a question that named
  it. Fuzzy, so "nights lantern" finds `river-lantern/main`; a full tie means it asks. Generic words like "dev" never select a session.
- **One yes, one delivery:** nothing is sent unless you spoke since that session's last request, so reconnects never replay
  history and the model cannot chain tasks on its own.
- **Echo:** with Soniox as ears, a second stream transcribes the bot's own audio, and only words it did not say cut it off. Other
  ears have no such guard: use headphones.
- **Who may connect:** localhost only, with a secret on every route, and `Origin` checked against `Host`.

Known limit: saying the exact words the bot is saying, while it says them, is dropped as echo. Wait for it to finish.

Background sessions stay quiet except for a one-line "finished" or "needs approval". A report you talk over comes back once
your question is answered.

## Channel mode

`bin/pointe start` starts a session with a Claude Code channel instead of `/pointe:voice`. It needs Node.js and a restart, and uses
`--dangerously-load-development-channels`, which Claude Code requires for a channel outside its allowlist. Pick "I am using this for
local development" at its warning. [SECURITY.md](../SECURITY.md) says what it loads.

On a Claude Team or Enterprise plan, channels are off unless an administrator sets `channelsEnabled: true` in managed
settings. Without it, Claude Code starts but silently drops every message to the session. Use `/pointe:voice` there.

## Approvals, exactly

When a session in the voice needs permission, the daemon reads the command out, and your yes or no goes to Claude Code through its
`PermissionRequest` hook. A yes to a question the session asks in conversation is different: Claude Code sees those words as a message
from another session, not as you typing, and can ask you to type before it sends a message, merges or deletes. Any process on the
machine could write such a message, so do not add a rule that trusts it.

Mute: tap your AirPods, or click the mic button. A falling tone means muted, a rising one live.

## What the voice knows and says

A reading model (`brief.py`, `CLAUDE_VOICE_READER`) does what the voice model cannot do fast:

- **Notes on each session:** goal, state, decisions, what was ruled out, what is open. Read from the whole record when a
  session registers, updated as it works, and kept in `~/.claude-voice/briefs` (0600), so they survive a restart.
- **Reports:** when a session ends its turn, the whole final message is read and turned into what you must hear: the
  outcome, what limits it, and the one decision or next move. Its open questions and clocks are tracked in code until
  something settles them, and "what do I need to do" is answered from that record.

Harness text (system reminders, task notifications) is not treated as you typing; a background agent's finding is kept.


## Investigating a call

`bin/voice-log` reads `~/.claude-voice/journal.jsonl` (0600): what the user said, what the bot said, every tool
call with its result, routing, gate refusals, echo drops, barge-ins, permissions. Any Claude Code session can run
it: `bin/voice-log --call` (the latest call, with everything the model was given), `bin/voice-log --session NAME`,
`bin/voice-log --since 14:20`, `bin/voice-log --grep 'refused|blocked'`. `bin/voice-context notes` shows the notes, and
`/voice-review` in a session investigates a call from there.
`daemon.log` keeps the full library-level detail.

## Tests

Tests run against an isolated daemon so they never touch a voice you are using:

```
uv run pytest -q tests/test_orchestrator.py tests/test_units.py tests/test_http.py tests/test_security.py tests/test_remote.py   # offline, no keys
export CLAUDE_VOICE_STATE=/tmp/cv-state CLAUDE_VOICE_DAEMON_PORT=7861
uv run python -I tests/e2e/scenarios.py brain       # one session, about 15 min
uv run python -I tests/e2e/multi_session.py         # two sessions: routing, switching, permissions
ECHO_GAIN=0.9 uv run python -I tests/e2e/echo.py     # speakers leaking into the mic, no echo cancel
```

`evals/sim.py` runs a whole call on the real voice model without audio; see `evals/README.md`.

The end-to-end suites drive real Claude Code sessions through a fake browser that speaks synthesized
utterances over the call WebSocket and transcribes the replies (`tests/e2e/rig.py`).
