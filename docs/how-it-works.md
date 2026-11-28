# How it works

```
browser tab or phone app (one WebSocket, echo cancel, shows the active session)
  -> ears: speech to text -> echo guard (drops the bot's own voice)
  -> brain: a text model decides, through tools (speak, send_to_claude_code, list_sessions, switch_session,
     ask_about_session). Speech is a tool call, so code checks each reply before you hear it.
  -> mouth: text to speech
  -> one worker per joined session (Claude Code, OpenCode, Codex, or one on another machine)
       in:  through its harness adapter (for Claude Code: its voice channel in launch mode, its inbox socket in attach mode)
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
- **Who may connect:** localhost, with a secret on every route, and `Origin` checked against `Host`. After you pair, a
  separate TLS listener on 7443 also takes phones, your other machines and invited people.

Background sessions stay quiet except for a one-line "finished" or "needs approval". A report you talk over comes back once
your question is answered.

When you start talking over the voice it steps back at once, before any of your words are recognized (about 10 dB
quieter: `daemon._duck_voice`). Your words then decide: "mm-hm", "okay" or a cough bring it back to full volume and it
goes on; anything else cuts it. Short lines it says often ("Sent to billing.", "Asking quarry.", "Approved.") are kept
as audio and played from memory, so a turn the daemon answers itself does not wait on the voice vendor
(`pointe/phrases.py`).

## Session mode speaks about one session

Orchestrator mode speaks for every session. Session mode ("let's focus on billing", "switch to billing", or a tap on a
session) speaks only about the one in focus, in code (`pointe/scope.py`, `daemon._out_of_focus`), on every path that could
bring up another session:

| Path | In session mode |
|---|---|
| A finished turn, an urgent one too, or a "joined" or "closed" | held, and not told to the brain either |
| A report queued before you focused, or held by a meeting, a hold or a brain dump | held when it would be said |
| An approval request from another session | not said; its card stays on every screen and stays tappable (Face ID or Touch ID in the apps), phone and desktop alerts still raise it, and one short chime with no words marks its arrival |
| A conflict alarm, a machine dropping with another session's approval | held; the conflict's card stays |
| A scheduled briefing that is ready | held; a briefing playing when you focus stops, and stays in Briefing |
| What the brain is told before each reply, and when a call starts | the session in focus and the count of what is held, never the others' state or needs |

Held news shows on the page, in the iPhone app and in the Mac app as one quiet line, "2 updates from other sessions";
a tap lists them, and Tell me has them said. They are said, waits first, when you go back to orchestrator mode by any
path (the mode switch, "orchestrator mode", or the session in focus leaving), or when you ask: "anything from the
others?", "what about the other sessions?", "what did I miss", "מה עם האחרים". Focusing on a session drops its own held
news: the switch says where it stands. An approval answered meanwhile is no longer listed.

**Why a chime for an approval.** A request blocks its agent, and goes back to its terminal when its harness's time runs
out. Nothing spoken would break the focus; nothing at all could leave an agent blocked while you look at another
session's work. One wordless cue, once per request (the brain dump's cue for the same case), tells you something needs a
tap without naming another session. It does not repeat; the card and the alerts carry it from there. A meeting's room
hears no chime.

## Echo

On laptop speakers the bot's voice reaches the microphone. The ears hear its words, and sound alone cannot tell them from
yours. Words and their timing can. The rules are in `pointe/echo.py`. `SonioxEars` in `pointe/daemon.py` applies them.

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
`scenarios.py` and `page_call.py` take it. At 0.3, one `scenarios.py brain` run on the code before these rules (a pre-release
build, 2026-11) had 10 echoes taken as your words and 10 cut-offs by the bot's own echo. At 0.5 it had 1 and 7. With
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

A reading model (`pointe/brief.py`, `CLAUDE_VOICE_READER`) does what the voice model cannot do fast:

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
`/pointe:voice-review` in a session investigates a call from there.
`daemon.log` keeps the full library-level detail.

## Tests

The offline suite, the end-to-end suites that drive real Claude Code sessions through a fake browser speaking
synthesized utterances (`tests/e2e/rig.py`), and the voice evals: [Running the tests](../CONTRIBUTING.md#running-the-tests).
