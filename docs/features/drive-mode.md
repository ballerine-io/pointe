# Drive & walk mode

Driving or walking with AirPods: you hear short answers, approve only what can be read out and loses nothing, and are
never asked to look at or touch a screen. Nothing destructive is approved from the road.

The rules live in `drive.py` (the road allowlist, the phrases, the copy). The daemon asks it at the read-out, at a yes,
and when it picks the current mode.

## Use it

- **Voice:** "drive mode", "walk mode", "I'm driving", "מצב נהיגה" turn it on. "Back to normal", "I've stopped", "exit
  drive mode", "חזרה לרגיל", "עצרתי" turn it off. Each must be a whole short utterance; it never reaches the voice model.
  The daemon answers "Drive mode. Short answers, …" or "Back to normal." in your language.
- **Page:** no Drive button (drive mode is for a phone in a car: the app or the voice starts it). While on, whoever turned
  it on: one big line (who needs you, else Speaking / Listening / N working / All quiet), "I've stopped" to end it, typing
  folded away, and the approval card without buttons.
- **iPhone app:** a Drive button (a car) at the top, beside Start a meeting, a drive screen with the same line and the live caption, Now Playing
  "Pointe · lantern needs you", and play/pause as mute. The app suggests "Switch to Drive mode?" when CarPlay's audio
  route carries the call, or after 60 s of motion detected as driving. It is never entered automatically. Menu →
  "Suggest Drive mode in the car" (per device, on by default) controls this. Motion is used only after you tap that
  setting on, when iOS asks for motion permission; until then only CarPlay is detected. A plain Bluetooth car kit looks
  like a headset to iOS.
- **Mac app:** no Drive button, as on the page: a Mac has no motion sensor and no car audio route. While drive mode is
  on, the window shows the same drive screen, with "I've stopped" to end it.

It cannot be turned on with no call or during a meeting.

## Approvals while driving

A spoken yes approves only when every normal rule holds (the daemon's own read-out, a yes begun after it ended, within
120 s, nothing else said, never typed, never the bot's echo, never aimed at another session), and also:

1. the read-out allowlist can say the request whole (a credential-like value is never read out);
2. the request loses nothing (`drive.road_safe`, a second allowlist): read-only programs, tests, `mkdir`, `touch`,
   `git status`, `diff`, `log`, `show`, `fetch`, `pull`, `add`, `commit`, and `push` without force, delete, mirror,
   `+ref` or `:ref`; no `--amend`, `--no-verify`, `--rebase`, `--prune`, or `add -f`; plain `curl` GETs; and edits inside
   the project. `rm`, `mv`, `cp`, redirects into files, `git reset`, `clean`, `rebase`, `checkout`, `stash`, `npm run`,
   `make`, `gh`, edits outside the project, and any edit in a session on another machine wait;
3. with a voiceprint stored, the yes itself is a strong match for your voice (score ≥ 0.55, ≥ 1 s of speech), at any
   [voice lock](voice-lock.md) level, Off included. Utterances are scored while driving even with the lock off.

Otherwise the voice says "X wants to run: … I won't approve that while you drive. It waits until you stop, or say no."
(or "X needs an approval I can't read out. …"), and opens no yes window: a yes repeats the line. **A no from anyone
denies.** A destructive request is said in full and waits; it is not denied for you.

A tap still answers any request. The page and the app hide the buttons while driving; "I've stopped" leaves the mode,
and the pending request is read out again in its normal form. Entering or leaving the mode closes an open yes window and
reads the pending request again in the new mode's form.

## Short answers

The mode's rules are added to the voice model's context. A reply over 25 words is sent back ("Shorter: they are
driving"), an active session's report is one line, and the model's "Sorry, I lost that" is not spoken.

## With other modes

- **Challenge:** never both, and driving wins. Entering drive mode ends a challenge with no verdict; a challenge is
  refused while driving.
- **Whisper:** drive mode holds it: full volume while driving, and whisper mode applies again when you stop.
- **Meeting** and brain dump rank above it for the mode shown, but the road rules for approvals are keyed on drive mode
  itself, so they hold whatever else is on.
- "Back to normal" ends one mode per utterance: drive mode, then a challenge, then whisper mode.

## Ends with the call

A hang-up or the idle hang-up ends it at once. A dropped link (a tunnel) keeps it for 5 minutes; a call back within that
time keeps it on.

## Limits

- Not measured on real car hands-free (HFP) audio. Advice to switch to the iPhone microphone on poor car audio waits for
  that measurement.
- The voiceprint rule is covered by offline tests, not by a live end-to-end run.
- The voice model's own short replies are worded in Hebrew only where they are fixed lines.

## API

| | |
|---|---|
| `POST /voice/drive {on: true\|false}` | `{drive: <status>}`. 400 unless `on` is a boolean; turning it on is 409 with no call or a meeting on. Page cookie, bearer token, phone key |
| status `drive` | `{on, since, how: voice\|button, dropped_at, pending: [{session, request_id, voice}]}`. `voice`: a spoken yes may answer that request while driving |
| status `mode_state` | `{mode: "drive", approvals: "drive"}` while on |
