# Thinking and the waiting sound

From the end of your turn until Pointe answers, the call's status line says "Thinking…". Before this it said
"Listening" through the whole wait, so words that were heard looked the same as words that were lost. When the wait is
long, one soft sound says the same thing without a look at the screen.

The rules live in `pointe/thinking.py` (the state, the sound's timing and the words); the daemon stamps them at events
it already had (`daemon._turn_taken`, `MuteOut`, `BotSpeechTap`) and changes no timing of the turn itself.

## What the status line says

The same words and the same colours on the page, the iPhone, the Mac window, the Mac's call bubble and its menu bar
item. Green is your turn or a session's work; orange is Pointe's turn. The dot's motion tells the states apart without
colour, and Reduce Motion stops it: the words carry the state.

| The line | When | The dot |
|---|---|---|
| Listening | the call hears you and nothing else holds | green, still |
| Hearing you (the page) | your words are arriving | green, a ring on the mic |
| Thinking… | your turn was taken and the reply is not heard yet | orange, shrinking to a loader |
| Speaking… | Pointe's voice plays | orange, breathing |
| Writing… | Pointe is [muted](mute.md) and just wrote the line it would have said | orange, breathing |
| billing is working… | a session has your request and has not answered | green, breathing slowly, like the session's own row |

The first of these that holds is the line: Speaking… and Writing… come before Thinking…, and Thinking… before the
session's work. Mic off, a hold, a brain dump and a challenge keep their own lines, as before. In push to talk the line
says Thinking… too; while a session works it keeps the talk mode's own words, which say how to talk. The Mac's small
bubble shows three dots in its circle while Pointe thinks, and the menu bar item shows them beside the mark.

**Thinking… follows the work, not a timer.** It starts the moment your words become the turn and holds while Pointe
works on them: a yes being applied, a model step, your words on their way to a session, the reply's words on their way
to the voice. After a spoken "One sec." it comes back, because the work goes on. For a turn that gets no reply (an
"mm-hm") it ends by itself after about half a second. A report a session sends later is news, not thinking. A step
that hangs stops reading as thinking after 45 seconds.

**It shows at once.** The device on the call is told on the call's own link the moment the turn is taken, so the line
changes within 150 ms (tested on the page); every other screen shows it at its next status, about half a second.

## The waiting sound

One soft note, 120 ms, at a tenth of full volume, when you have waited 1.8 seconds since your last word and nothing has
been said. For typed words and a push-to-talk press it counts 1.2 seconds from the send.

- **Never for a fast reply.** A reply heard before the mark gets no sound, in that turn at all.
- **Never with the reply.** Once the reply's words have gone to the voice the sound is not played, so it cannot land on
  the first word. It travels in the call's own audio, in order with the voice.
- **Once in a turn.** A turn that takes ten seconds gets one sound, then the spoken "One sec." Pointe already says past
  4.5 seconds.
- **Not speech.** Nothing that times Pointe's voice (the echo guard, the yes window, the floor) takes it for Pointe
  speaking, and the status line does not say Speaking… for it.
- **Not where it would be wrong:** while Pointe is muted, in [whisper mode](whisper-mode.md), in a
  [meeting](meeting-mode.md), in a mode that never speaks, or while anyone is making a sound. In
  [drive mode](drive-mode.md) it plays even when you had muted Pointe: drive mode holds mute, and on the road the sound
  is the only sign your words were heard.

**Why the clock starts at your last word.** That is the silence you hear. The time Pointe waits to be sure you finished
is part of it, so a clock that started when the turn was taken would let a slow turn pass two seconds of dead air. It
also means a faster end of turn later makes the sound rarer, not earlier.

**Why a sound and not a spoken "got it".** Words said in the second after a question delay the answer they announce,
and a filler helps only on a wait of several seconds. So the ladder is: the state at once, the sound at 1.8 seconds,
the spoken "One sec." at 4.5.

## Turn it off

- **The page:** Settings → Turn taking → Waiting sound.
- **The iPhone and the Mac:** Settings (•••) → While you wait → Waiting sound.

On by default. The setting lives on the Mac (`thinking.cue`), so every screen shows the same. The Thinking… line has
no switch: it is the state.

## The wire

| What | Shape |
|---|---|
| `GET /voice/status` → `phase` | `null`, `{"name": "thinking", "session": null, "since": …}` or `{"name": "working", "session": "billing", "since": …}`. Always `null` while Pointe speaks or just wrote a line: `speaking` and `reading.writing` say those |
| The call's link | `{"type": "phase", "name": "thinking", "session": null}` when a turn is taken. A device shows it for 0.9 s unless the status confirms it |
| `POST /voice/prefs {"thinking.cue": false}` | the waiting sound, off |

An app from before this ignores `phase` and the link's message, and says Listening as it did.
