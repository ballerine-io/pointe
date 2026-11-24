# Skip

Skip what Pointe is saying and go on to the next message. For a report you already read on the screen, a line that runs
long, or three sessions that finished at once.

The rules live in `pointe/skip.py` (the phrases and the words); the daemon applies them in `daemon.skip_speech`.

## Use it

- **The button:** beside the call's status line, after the [mute](mute.md) button, on the page, in the iPhone app and
  in the Mac app. It shows only while Pointe speaks, and says "Skip this message".
- **The Mac's key:** ⌃⌥S from any app, like the talk shortcut. Change it in the Mac app's Settings, under This Mac,
  "Skip shortcut" (Delete removes it). It cannot be the talk shortcut's keys. The window shows it beside the talk mode
  ("Skip ⌃⌥S"), and the call bubble shows it, with a skip button, while Pointe speaks.
- **Voice:** "skip", "next", "skip this", "next one", "skip this message", "דלג", "הבא", said over a line or right
  after you cut one off. Each must be a whole short utterance: "skip the tests" is a request, and long after Pointe's
  last word "next" is a word like any other.

## What it does

- **The audio stops at once,** on the Mac and on the device you hear it from.
- **The rest of that reply is not said,** and a report skipped this way is not offered again. (A report you talk over
  is offered again, "coming back to it"; a skip says you do not want it.)
- **The next message follows after a breath,** not after the quiet gap that news usually waits for.
- **Nothing is lost:** the skipped line is in the conversation as text.
- **A briefing skips one part,** as "skip" always did while one plays.

## What it never does

A skip answers nothing. It is not a yes and not a no. A permission request whose read-out you skipped is read out again
before a yes can count, by the same rule as one you talked over.

## A switch drops what waited

Moving to the orchestrator or to a session, by a click, a tap or by voice, stops Pointe at once and drops every message
that waited to be said for the place you left. Nothing queued plays after the switch. The dropped lines stay in the
conversation as text ("Not said, from billing: …"), and Pointe can still answer "what did billing say?". Going back to
the orchestrator still gets the one short summary of what the other sessions said while you were focused
([session mode](../how-it-works.md#session-mode-speaks-about-one-session)).

## The wire

| Call | Answer |
|---|---|
| `POST /voice/skip {}` | `{skipped, waiting}`. `skipped`: a line was being said and was cut; `waiting`: how many messages waited behind it. With no call up, `{skipped: false, waiting: 0}` |
