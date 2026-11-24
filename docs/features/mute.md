# Mute

One button mutes Pointe's voice. Everything it would say arrives as text in the conversation, and you read it. You still
talk or type to it, and approvals work as they always do. For a quiet room, a call you are on, or anyone who reads faster
than they listen. It replaces reading mode, and keeps its two phrases.

The rules live in `pointe/mute.py` (the phrases, the words, the status); the daemon applies them in one place,
`daemon.MuteOut`, between the brain and the mouth.

## Use it

- **The button:** a speaker with a slash, beside the call's status line, on the page, in the iPhone app and in the Mac
  app. It says "Mute Pointe"; muted, it is filled and says "Unmute Pointe".
- **The status line:** while Pointe speaks it says "Speaking…". Muted, it says "Writing…" whenever Pointe would have
  spoken, and the reply is in the conversation.
- **Voice:** "stop talking, I'll read", "I'll read", "reading mode", "text only", "מצב קריאה" mute it. "Talk again",
  "you can talk again", "reading mode off", "back to normal", "תדבר שוב", "חזרה לרגיל" unmute it, only while it is muted.
  Typed, the same words do the same. Each must be a whole short utterance; the voice model never gets them. Pointe
  answers in text: "Muted: I'll write instead of talking. Say "talk again" to hear me.", and "Talking again." aloud when
  it ends.

**Muting in the middle of a reply** stops the audio at once, on the Mac and on the device you hear it from. The reply
goes on as text: the sentences Pointe had not said yet are written.

**Each device keeps its own choice.** The page keeps it in the browser, each app on its device. A device says its choice
when it calls (`?reading=1` on the call's address), so the first greeting is already text, and a call that reconnects
is still muted. Muted or unmuted by voice during a call, the choice is sent to the device on the call, which keeps it.
While a call is up every screen shows the call's choice, and the button on any of them changes it. With no call up, the
button changes only that device's choice.

## What it does

- **Nothing is synthesised.** A line for the voice never reaches the mouth, so no text-to-speech request is made and no
  vendor bills for one. The "One sec." filler is not shown either.
- **The text arrives as it always did:** each line in the conversation, as on any call.
- **"Writing…"** shows for two seconds after a line was written instead of spoken (`mute.WRITING_SECS`).
- **Chimes stay.** A chime is not speech: a held approval in [session mode](../how-it-works.md#session-mode-speaks-about-one-session)
  still gets its one short cue.

## Approvals and read-backs: unchanged

- A permission request is shown word for word, as its read-out. A tap answers it (Face ID or Touch ID in the apps), or a
  spoken yes or no under the usual rules. Muted, the bot's turn starts and ends the moment the line is shown, so a yes
  counts only when begun after the line appeared and with nothing said between: the same rule as after the voice stops.
- A read-back (a new session, sessions to add, a night's plan, the meeting's action items, a close) is shown as text.
  Its card's button confirms it, or a spoken yes under the read-back's rules.
- **A typed yes confirms nothing**, as without mute. In the apps a tap asks for Face ID or Touch ID; a typed "yes" must
  not get around that. `tests/test_mute.py` runs the same approval answers unmuted and muted and asserts the same
  outcomes, and checks that a typed yes approves nothing.

## With other modes

- **Drive mode holds it.** On the road you cannot read, so Pointe talks while you drive; mute applies again when you
  stop. Asked for while driving, it waits: "Mute starts when drive mode ends. I keep talking while you drive." The
  button says "Drive mode holds mute: Pointe talks while you drive."
- **Whisper mode:** both apply. Nothing is spoken, so the halved volume does not matter; the raised microphone and the
  short replies still do.
- **Push to talk and the microphone's own Mute:** unchanged; they are about what Pointe hears. With the microphone
  muted the status line says "Muted", as before.
- **Meeting mode:** what Pointe would say into the room (participating) is shown instead.
- "Back to normal" ends one mode per utterance: drive mode, then a challenge, then whisper mode, then mute.

## What went with reading mode

The Read button in the page's dock, the Read switch in the apps' Settings, the card ("Reading mode: Pointe writes, you
read", Talk again, Mark all read) and the Unread and Read marks under each reply are gone. Nothing marks a reply read.
A device that had reading mode on is muted.

## Limits

- Only on the default voice pipeline (the brain). With a realtime front (`CLAUDE_VOICE_FRONT=gemini|openai`) the model
  makes its own audio, and mute does not stop it.
- A close by voice ("close billing and pricing") has no card: confirm it with a spoken yes, or close each session from
  its row.
- An iPhone or Mac app from before 0.8.3 on a call with a 0.8.3 Mac still shows its Read switch and card; they work.

## API

The names are reading mode's, so an app built before the mute button still works on a call.

| | |
|---|---|
| `POST /voice/reading {on: true\|false}` | `{reading, applied}`. Sets the call's choice; `applied: false` with no call up. 400 unless `on` is a boolean |
| call address | `/voice/call?reading=1`, `/voice/phone?reading=1`: the calling device's choice |
| daemon to client, call socket | `{"type": "reading", "on": true\|false}` when the choice changed by voice |
| status `reading` | `{on, held, writing, read_through}`. `held` is `"drive"` while drive mode suspends it; `writing` is true for a moment after a line was shown instead of spoken |
| `POST /voice/read`, status `talk[].unread`, `read_through` | what an older app's Unread and Read marks use; nothing in 0.8.3 shows them |
