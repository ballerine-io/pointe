# Reading mode

Pointe stops speaking. Everything it would say arrives as text in the conversation, and you read it. You still talk or
type to it, and approvals work as they always do. For a quiet room, a call you are on, or anyone who reads faster than
they listen.

The rules live in `pointe/reading.py` (the phrases, the words, the status); the daemon applies them in one place,
`daemon.ReadingOut`, between the brain and the mouth.

## Use it

- **Voice:** "stop talking, I'll read", "I'll read", "reading mode", "text only", "מצב קריאה" turn it on. "Talk again",
  "you can talk again", "reading mode off", "back to normal", "תדבר שוב", "חזרה לרגיל" turn it off, only while it is on.
  Typed, the same words do the same. Each must be a whole short utterance; the voice model never gets them. Pointe
  answers in text: "Reading mode: I'll write instead of talking. Say "talk again" to hear me.", and "Talking again." aloud
  when it ends.
- **Page:** Read in the dock (it reads Reading while on). A card says "Reading mode: Pointe writes, you read.", with
  Talk again and Mark all read.
- **iPhone app:** Settings (⋯) → Read, and the same card.
- **Mac app:** the iPhone app's screens: Settings (••• at the top, or ⌘,) → Read, and the same card.

**Each device keeps its own choice.** The page keeps it in the browser, each app on its device. A device says its choice
when it calls (`?reading=1` on the call's address), so the first greeting is already text. Turned on or off by voice
during a call, the choice is sent to the device on the call, which keeps it. With no call up, Read changes only that
device's choice.

## What it does

- **Nothing is synthesised.** A line for the voice never reaches the mouth, so no text-to-speech request is made and no
  vendor bills for one. The "One sec." filler is not shown either.
- **The text arrives as it always did:** each line in the conversation, as on any call.
- **Unread and read.** Each of Pointe's replies shows **Unread** until you read it, then **Read**. A reply counts as read
  when you tap or click it (it and every reply before it), tap Mark all read, or talk or type after it. A reply that grows
  after you read it is unread again. The daemon keeps this for the call, so every screen shows the same.
- **Chimes stay.** A chime is not speech: a held approval in [session mode](../how-it-works.md#session-mode-speaks-about-one-session)
  still gets its one short cue.

## Approvals and read-backs: unchanged

- A permission request is shown word for word, as its read-out. A tap answers it (Face ID or Touch ID in the apps), or a
  spoken yes or no under the usual rules. In reading mode the bot's turn starts and ends the moment the line is shown, so
  a yes counts only when begun after the line appeared and with nothing said between: the same rule as after the voice
  stops.
- A read-back (a new session, sessions to add, a night's plan, the meeting's action items, a close) is shown as text and
  stays unread until you act. Its card's button confirms it, or a spoken yes under the read-back's rules.
- **A typed yes confirms nothing**, as without reading mode. In the apps a tap asks for Face ID or Touch ID; a typed
  "yes" must not get around that. `tests/test_reading_mode.py` runs the same approval answers with the mode off and on
  and asserts the same outcomes, and checks that a typed yes approves nothing.

## With other modes

- **Drive mode holds it.** On the road you cannot read, so Pointe talks while you drive; reading mode applies again when
  you stop. Asked for while driving, it waits: "Reading mode starts when drive mode ends. I keep talking while you
  drive." The card says "Drive mode holds reading mode: Pointe talks while you drive."
- **Whisper mode:** both apply. Nothing is spoken, so the halved volume does not matter; the raised microphone and the
  short replies still do.
- **Push to talk:** unchanged; it is about the microphone.
- **Meeting mode:** what Pointe would say into the room (participating) is shown instead.
- "Back to normal" ends one mode per utterance: drive mode, then a challenge, then whisper mode, then reading mode.

## Limits

- Only on the default voice pipeline (the brain). With a realtime front (`CLAUDE_VOICE_FRONT=gemini|openai`) the model
  makes its own audio, and reading mode does not stop it.
- A close by voice ("close billing and pricing") has no card: confirm it with a spoken yes, or close each session from
  its row.

## API

| | |
|---|---|
| `POST /voice/reading {on: true\|false}` | `{reading, applied}`. Sets the call's choice; `applied: false` with no call up. 400 unless `on` is a boolean |
| `POST /voice/read {through?: <talk id>}` | `{reading}`. Marks Pointe's lines read up to that id, or all of them |
| call address | `/voice/call?reading=1`, `/voice/phone?reading=1`: the calling device's choice |
| daemon to client, call socket | `{"type": "reading", "on": true\|false}` when the choice changed by voice |
| status `reading` | `{on, held, read_through}`. `held` is `"drive"` while drive mode suspends it |
| status `talk[].unread` | true for Pointe's lines after `read_through` |
