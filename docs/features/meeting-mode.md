# Meeting mode

Open the laptop, or put the phone on the table, in a meeting. Pointe is linked to one or more sessions that hold the
context (the agenda, the design doc, yesterday's decisions). It takes part in the meeting without answering every
sentence:

- **Listening:** it never speaks. It writes what matters into your notes: open questions (and, if you allow it, the
  answer it found in a session), decisions, and action items with an owner.
- **Participating:** it speaks only when you ask it ("Pointe, what do you think?"). Otherwise, when it has something
  worth saying, it **raises a hand**: a one-line summary you can let it speak, put off, or turn into a note.

At the end: a summary, decisions, action items and open questions, exported or sent to a session only when you ask.

The rules live in `meeting.py`; the meeting reuses the notes stream (`notes.py`) and the job runner (`jobs.py`).

## Start

**Meeting** in the dock (page) or the app opens a sheet: Listening or Participating, the context (paste or type an
agenda), the sessions it may look things up in, and "Auto lookups" (answer open questions from those sessions without
asking first). Then a consent step: "The room's audio leaves this Mac while the meeting runs. Nothing is stored unless
you export it." and a tick for "Everyone in the room knows this is being transcribed and sent to the speech vendor".
A recording indicator stays on screen while the meeting runs.

By voice, "Meeting mode, listening" (or "מצב פגישה, השתתפות") starts one once the consent step was accepted on this
Mac.

Meeting mode needs a Soniox key: its ears are a separate Soniox stream with speaker separation.

## Who said what

The room's audio goes to a dedicated Soniox stream that separates speakers. The conversation's own ears get no audio at
all during a meeting, which keeps a "yes" said in the room away from the approval code.

You are identified in one of two ways:

- **By the words that started it:** a voice start replays the last 5 s of audio into the meeting stream, so whoever
  said "meeting mode" is you. After a tap start, tap "That was me" on one of your turns.
- **By the [voice lock](voice-lock.md),** when a voiceprint is stored and the lock is on: a turn in your voice binds
  you, "Pointe, that's me" in your voice moves the seat to you, and a "that's me" in another voice is refused.

With no voiceprint a label is all Pointe has, and anyone in the room can say "that's me": so nobody takes the seat by
voice, whether it is empty or held. Pointe answers the claim with a note to tap "That was me" instead. Once the seat is
yours, only a tap moves it.

Other speakers are "Speaker 2", "Speaker 3". The note-taker may suggest a name from an introduction; a name is applied
only when you accept it or say "Pointe, speaker two is Dana".

## Voice commands

Only your addressed words act ("Pointe, …", Hebrew "פוינט, …", "היי פוינט"): `that's me`, `speaker two is Dana`, `the
agenda is …`, `join in` or `participate` (to Participating; "Pointe, meeting mode, participating" too), `just listen` or
`go back to listening` (to Listening), `go ahead` (let a raised hand speak), `look that up`, `anything waiting?`, `what
do you think?` or any question (a spoken answer in Participating, a note in Listening), and `end the meeting`. The end
and mode commands must be the whole sentence: "Pointe, should we close the meeting?" and "Pointe, should you join in?"
are questions. Joining is acknowledged in two words ("I'm in"); going back to listening is silent.

A question that names a session ("Pointe, what does billing's session say about the retry limit?") is looked up in a
read-only copy of that session, any session of yours, linked or not: in Participating Pointe says the answer to the
room in two sentences at most, and in both modes it is written as an answer note. The live session gets nothing. Another speaker's commands are ignored; their
"that's me" moves the owner label only with a voiceprint, as a strong match for your voice (no voice action in a
meeting sends or approves).

## What it does, and when

- A note-taker (the reading model) reads the room after 60 s of new speech, 8 new turns, or a 12 s pause with something
  new, whichever comes first, never per sentence.
- **Lookups:** an open question that a linked session could answer is looked up in a read-only copy of that session
  (the live session is never touched), automatically with Auto lookups, else on "Look it up" or "Pointe, look that up".
- **Hands:** one at a time, at most one per 2 minutes unless urgent; Let it speak, Not now, or Type it instead. In
  Listening, a hand becomes a note.
- **Speaking:** in Participating, the room hears only the one reply you asked for. Any speaker talking over it stops it.
- **Session reports** are held as collapsed notes and delivered after the meeting.

## Safety

- **No sends during a meeting.** Sends are refused in code; the only session access is read-only lookups.
- **No voice approvals during a meeting.** A permission request is not read out; it becomes a card (and an alert), and
  only a tap approves.
- **Room words are data.** They reach only the note-taker's prompt, labelled as meeting content, never as
  instructions.
- **Challenges, briefings and conflict alarms** are not spoken during a meeting.

## Privacy

- Room audio goes to Soniox. Speaker-tagged transcript windows go to the reading-model vendor for notes. Your addressed
  commands go to the brain vendor, and Pointe's spoken replies to the mouth vendor. The sheet shows which vendors these
  are before you start (`POST /voice/meeting {action: "vendors"}`).
- The transcript lives in memory only, with turns older than 2 hours dropped (a running summary keeps their gist). It
  reaches disk only if you export it.
- The daemon log and the journal keep no words from the room or from the bot during a meeting.
- **Export** writes Markdown at 0600 under `~/.claude-voice/meetings/` (0700), with the transcript only if you ask.
  **Discard** forgets the meeting, its transcript and its notes.

## End

"Pointe, end the meeting" or End meeting. A final pass writes the summary, decisions, action items and open questions.
Then: Export, Send the action items to a session (after a second tap, word for word as the sheet lists them), or
Discard. Nothing happens by default.

By voice, after the end: "send the action items to billing" is read back in full, every item with its owner and due
date ("Send 2 action items to billing: Raise the retry limit, for Sam, due Friday; Update the runbook, for Dana. Send
them?"), and sent on your next plain yes, word for word as read back (never rewritten by the model), as Send does. Only
what was read back is sent: more than 5 items are not read out, and Pointe says to send them from the end sheet. A no or
anything else sends nothing; the yes keeps a permission prompt's rules (a yes and nothing else, begun after the
read-back ended, the read-back the last thing Pointe said), the read-back heard back and typed words are not a yes, and
with the voice lock on only your voice's yes counts. The end sheet on the page and in the apps shows the
read-back while it waits, and where the action items went.

If the call drops for 5 minutes the meeting ends, and held news reaches the next call. If the speech stream drops, it
reconnects by itself (1 s backoff doubling to 30 s); speakers are relabelled, and you tap "That was me" again (with a
voiceprint, your next turn binds you by itself).

## Limits

- It hears the room through the microphone. Remote participants heard through headphones are not captured; through
  the laptop speakers they are heard like anyone else.
- Speaker labels are anonymous and can drift early in a stream; a short interjection may be credited to a neighbour.
- Not built: a global hotkey for "go ahead", a Live Activity on the iPhone, a cost estimate in the banner.

## API

Every route is reachable with the page cookie, the bearer token and the phone key.

| Route | Body | Returns |
|---|---|---|
| `POST /voice/meeting` `start` | `{mode: "listening"\|"participating", consent: true, brief?, sessions?: [name], auto_lookups?}` | `{meeting: <status>}`; 400 without `consent: true` or on a bad body; 409 with the reason (no call, no Soniox key, already on, a realtime front, native ears) |
| `vendors` | | `{vendors: {room_audio, notes, speech, commands}, soniox}` |
| `mode` | `{mode}` | switches listening/participating |
| `hand` | `{decision: "speak"\|"type"\|"later"}` | |
| `speaker` | `{label, name}` | names a speaker |
| `owner` | `{turn_id}` | binds you to the speaker of that turn |
| `brief` | `{text}` | replaces the brief |
| `lookup` | `{note_id}` | looks up an answerable question note |
| `ask` | `{text}` | a typed "Pointe, …" |
| `end` | | `{ended, summary, decisions, action_items, open_questions}`; 409 while an end runs |
| `reconnect` | | `{reconnecting: true}` |
| `export` | `{transcript?: bool}` | `{exported: path}` |
| `send_actions` | `{session}` | after the end only; `{asked: true}` at once, the items go as listed; a spoken read-back waiting is dropped |
| `discard` | | forgets the ended meeting; 409 while it is on |
| `GET /voice/meeting/transcript` | | `{turns: [{id, who, speaker, at, lang, text}]}` |
| `GET /voice/notes` | `?since=<id>&kinds=a,b&changed_since=<version>&meeting=<id>` | `{version, meeting_id, notes: [...]}` |
| `POST /voice/notes` | `{id, state?: open\|done\|dismissed, accept?: true}` | |
| `GET/POST /voice/prefs` | `meeting.default_mode`, `meeting.auto_lookups`, `meeting.notes_language`, `meeting.consented` | |

Status: `mode_state`, `meeting` (`{on, id, ending, mode, since, speakers, owner_known, hand, speaking, paused, vendors,
recording, sessions, auto_lookups, turns}` while on; `{on: false, ended, result, send_pending: {session, line,
expires_in} | null, sent_to}` after the end), `notes: {version, last_id}`, `attention`, `jobs`.
