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
- **Echo:** the bot's own voice through the speakers is never taken as your words, and never answers a permission. See
  [Echo](#echo). It needs Soniox as ears. Other ears have no such guard: use headphones.
- **Who may connect:** localhost only, with a secret on every route, and `Origin` checked against `Host`.

Background sessions stay quiet except for a one-line "finished" or "needs approval". A report you talk over comes back once
your question is answered.

## Echo

On laptop speakers the bot's voice reaches the microphone. The ears hear its words, and sound alone cannot tell them from
yours. Words and their timing can. The rules are in `echo.py`. `SonioxEars` in `daemon.py` applies them.

**What counts as the bot's words.** Three accounts of what it said:
- its written text, from the start of the reply that was playing. Its voice can stop and start inside one reply.
- the same text as the voice reads it (`spoken_form`): `README.md` is "readme dot md", `python3` is "python three".
- the mirror: a second Soniox stream on the bot's own audio. It spells words as the ears do, but it trails the audio
  by seconds.

Your transcript and the bot's text both pass through `echo.words`. Numbers are spelled out, including Hebrew number
words. "1,000" is 1000, and "%" is "percent". The same speech then compares equal, however each side wrote it.

**When words are judged.** By when they were said, not by when their transcript came. Soniox sends the final for an echoed
sentence about 3 s after the bot stops. `AudioClock` counts the audio Soniox really receives, so the word offsets in a
transcript map to wall time.
- Words said over the bot, or up to 1 s after it: the echo rules apply, however late the transcript is.
- One or two words said over the bot: compared only with what it was saying then. Against two whole replies, near
  spellings match any short phrase ("this" for "is").
- A yes or no the bot said at all stays its own: an echoed answer never counts.

**Cutting the bot off.** Two of your words in a row cut the bot off, or one stop word ("stop", "wait", "no", "רגע").
- Half of one of the bot's words proves nothing, first or last: "hold" of "holding", "on" of "python".
- A final that is only a stop word cuts in at once. Whether it is yours, and so whether it answers a permission, still
  waits for the mirror.
- Your voice well above the echo level cuts in, judged on fresh audio only.

**Permissions.** An echoed yes or no never answers (`EchoGuard.repeats_bot`, and words said over the bot). A read-out
that sounds like a switch command is still echo. A yes begun over the bot never approves. The bot asks for it again in
one line. After two of these on one request, it waits for a fresh yes or a tap.

**Measured.** The rig leaks the bot's audio into the mic at `POINTE_ECHO_GAIN`. `tests/e2e/page_challenge.py`,
`scenarios.py` and `page_call.py` take it. At 0.3, one `scenarios.py brain` run on the code before these rules (main
`1539cfd`, 2026-11) had 10 echoes taken as your words and 10 cut-offs by the bot's own echo. At 0.5 it had 1 and 7. With
all the rules, two runs at 0.3 had 0 echoes taken as your words and 1 cut-off (case below). `page_challenge` at 0.3 and
0.5 took no echo as your words. `page_call` passed at 0, 0.3 and 0.5.

**Not solved.**
- A stop word inside the echo can cut the bot off: "לא" is "no" and also "not", and "against" was once heard as
  "enough". Words cannot tell this from your own stop.
- When Soniox gives "stop" late, the bot stops about 1.7 to 2 s after you start talking.
- The rig's echo is instant, clean and linear. Real speakers add playback lag and echo-cancel distortion. The tolerances
  are 0.3 s for words over the bot and 1 s of tail.
- The loudness rule can still cut the bot off when a meeting opens the room over a reply.
- Hebrew teens ("אחת עשרה") are not mapped to numbers.
- Saying the exact words the bot is saying, while it says them, is dropped as echo. Wait for it to finish.

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
uv run --locked pytest -q tests/ --ignore=tests/e2e   # offline, no keys
export CLAUDE_VOICE_STATE=/tmp/cv-state CLAUDE_VOICE_DAEMON_PORT=7861
uv run --locked python -I tests/e2e/scenarios.py brain       # one session, about 15 min
uv run --locked python -I tests/e2e/multi_session.py         # two sessions: routing, switching, permissions
ECHO_GAIN=0.9 uv run --locked python -I tests/e2e/echo.py     # speakers leaking into the mic, no echo cancel
```

`evals/sim.py` runs a whole call on the real voice model without audio; see `evals/README.md`.

The end-to-end suites drive real Claude Code sessions through a fake browser that speaks synthesized
utterances over the call WebSocket and transcribes the replies (`tests/e2e/rig.py`).
