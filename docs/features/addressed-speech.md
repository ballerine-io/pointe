# Only when I say Pointe

A microphone setting between Always on and Push to talk. Pointe hears everything, and acts on a spoken turn only
when its words say Pointe's name or a session's. Everything else is side talk: a phone call at your desk, a colleague
at the door, you thinking aloud. It is dropped before it is remembered, sent to a model or a session, or taken for an
answer to a request.

The rule is `pointe/addressed.py`; the daemon applies it where a spoken turn is taken (`daemon._addressed_words`). It
reads the recognizer's text only: no second model, no extra wait.

## Use it

| Surface | Where |
|---|---|
| The page | the switch above the mic: Always on · Say “Pointe” · Hold to talk; or Settings → Microphone → Only when I say Pointe |
| iPhone | the same switch above the mic; or Settings (•••) → Microphone |
| Mac | the same switch; or Settings → Microphone |

It is one setting on the Mac, so every screen agrees. While it is on and nothing else holds, the state line says
"Say “Pointe” to talk" where it said "Listening". No phrase switches it.

## What counts as said to Pointe

| You say | Taken as |
|---|---|
| "Pointe, what's billing doing?" · "Hey Pointe, is the build green?" · "So, Pointe, what changed?" | the words after the name |
| "Approve it, Pointe." · "Yes, Pointe." | the words before the name |
| "Pointe." or "Pointe?" alone | nothing yet: the next words, within 6 seconds, need no name |
| "Billing, run the tests again." · "Docs: update the changelog." | the whole turn, for that session |
| "Tell docs to update the changelog." · "Ask billing whether…" · "Switch to harbor." | the whole turn |

And what does not: the name inside a sentence ("the point is…", "that's a good point", "at this point"), a session's
name as an everyday word ("docs are in the shared drive", "I sent the docs to the client"), and anything with no name
at all, a bare "yes" included.

**A yes needs the name.** In this mode "yes" alone approves nothing, whoever says it: say "Pointe, yes" or "yes,
Pointe". The read-out and every other rule of an approval are unchanged; the tap is unchanged.

A recognizer often writes the name as "point". That is taken as the name where a name is called: first in the turn
("Point, what's billing doing", "Point yes"), or last ("Yes point"), unless the words around it make it a noun ("point
of order", "point taken", "a fair point", "data point"). In this mode the Mac gives the recognizer the name "Pointe",
so Soniox usually writes it as spelled (the setting is read when a call starts: hang up and call again after
switching).

## What still hears everything

- Typed words, and push to talk (its own setting).
- A brain dump, "don't interrupt me", a challenge: once started with the name ("Pointe, brain dump"), every word is
  theirs until they end.
- A meeting: it has its own rules for when the room is talking to Pointe.
- A lone "stop" still silences Pointe's voice. Other side talk does not cut it off; if side talk did cut a line before
  its words were known, the line goes on.

## What is kept of side talk

Nothing of its words. It is not in the conversation, not in the context of any model, not sent to a session. The
journal gets one line with its length ("not addressed: 9 word(s) dropped"). The live caption shows words as they are
heard, as in every mode, and they go when the turn is dropped. The audio goes to the recognizer as in Always on: this
mode decides what Pointe acts on, not what the ears hear. For nothing heard at all, use Push to talk.

## Measured

`bench/addressed_bench.py`, on 100 clips, each heard by a recognizer Pointe ships and judged by the same function the
daemon calls. The transcripts are committed (`bench/addressed_heard.*.jsonl`) and `tests/test_addressed.py` judges
them again on every run.

- **Side talk**: 50 whole utterances of people talking to each other in a meeting, from the AMI Meeting Corpus
  (Carletta et al., 2005, https://groups.inf.ed.ac.uk/ami/corpus/), Creative Commons Attribution 4.0 (CC BY 4.0):
  the "end" clips of `bench/human_turns.jsonl`, two a speaker. Only the
  recognizer's text of each clip is in this repository, with the meeting and the speaker; no audio.
- **Addressed**: 50 lines said to Pointe or to a session by name, in the dialogue suite's eight Kokoro voices
  (synthetic, Apache-2.0).

| Ears | Side talk acted on | Addressed lines taken |
|---|---|---|
| Soniox, the default setup's, given the name as a context term | 0 of 50 | 50 of 50 |
| Whisper large-v3-turbo on this Mac, the local setup's | 0 of 50 | 48 of 50 |

The target was 0 of 50 and 50 of 50. The default ears meet both. The local ears meet the first and miss the second by
two clips, each time because the recognizer wrote a name as another word: "docs" as "darks", and "No, Pointe." as "No
point.", which is also a phrase. The rule accepts one changed, added or dropped letter in a name that is called
("Dogs, what did you change?", "Tell Harbour to rebase"), and no more: a looser match would start to answer side talk.
With the local ears, "Hey Pointe" or a pause after the name is the surer way to be taken.

One run on each ears, on one day; the rule was changed while these clips were being measured (a recognizer writes
"Point yes." with no comma), so the clips are not a held-out set. A second set the rule has never seen is owed.

## Limits

- The side talk is real people, in English, in a meeting about a remote control, on headsets. It is not a phone call
  at a developer's desk, not Hebrew, not a far voice on a laptop's microphone.
- The addressed lines are synthetic voices reading clean sentences. No recorded person said "Pointe" for this.
- A session named for a common word and followed by an order reads as a call: "billing run finished late" would be
  taken for billing. Side talk that happens to begin "Tell billing to…" would too.
- Hebrew: the name is taken as "פוינט" at the start of a turn. It was tested on written examples only, on no audio.
- It needs ears that give words: with a speech-to-speech model hearing the audio itself (`CLAUDE_VOICE_EARS=native`) there
  is no text to read, and the setting changes nothing.
- There is no sound or spoken sign that side talk was dropped: the state line and the missing reply are the sign.
- Another person in the room who says "Pointe, …" is taken as you are, unless the [voice lock](voice-lock.md) is on.

## The tests

| What | Where |
|---|---|
| The rule: what addresses Pointe, a session, nobody; the daemon drops side talk, takes addressed words with the name off, never answers a request from side talk, and journals no word of it; the committed transcripts judged again | `tests/test_addressed.py` |
| The page: the switch's three choices, the state line, Settings | `tests/test_addressed_page.py` |
| The apps: the state line, the mode is not push to talk, the demo | `apps/PointeKit/Tests/PointeUIUnitTests/AddressedTests.swift` |
| iPhone and Mac screens | `apps/ios/PointeUITests/AddressedUITests.swift`, `apps/macos/e2e/smoke.py` |
