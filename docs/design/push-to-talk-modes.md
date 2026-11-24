# Push to talk: hold or tap

Two ways to press the talk button, the same on the page and in the iPhone app, each device choosing its own in
Settings → Microphone → Talk button:

- **Hold to talk** (the default, what push to talk did until now): press and hold, let go to send.
- **Tap to talk**: tap once to start talking, the microphone stays open, tap again to send.

Both styles send the same control message on the call socket (`{"type": "ptt", "open": true|false}`); the gate in
`ptt.py` is still the rule, with the same limits, and a press is one message in both (below, "A press is one message"). The style is a client choice, kept per
device (the page: `localStorage` `pointe.pttStyle`; the app: `UserDefaults` `talkStyle`), as the page's hold key already
is: one person may hold on the Mac and tap on the phone in a pocket.

## Why: the ring on the iPhone felt dead

Reported as "in iOS the button is not responsive". Reproduced on the iPhone 18 Pro simulator with
`apps/ios/PointeUITests/PushToTalkUITests.swift` on the demo call (no Mac), reading how long each press held the gate open
through a debug-only trace on the ring (`Call.talkTrace`):

| Press | Gate held |
|---|---|
| ring, 2.5 s | 2415 ms |
| ring, 1.0 s | 916 ms |
| ring, tap | 3 ms |
| conversation, 1.5 s | 1147 ms (after the 0.35 s long press, as designed) |
| ring, 1.0 s, while the status says the gate is open | nothing: no press sent |

So the gesture itself opens at touch down (the ~85 ms is XCUITest's own). Two things made it read as unresponsive:

1. **The ring took the Mac's word over the thumb.** `CallView.talking` was `call.talk.isOpen || status.ptt.open`, and the
   ring's touch-down handler pressed only `if !talking`. The status is polled every 400 ms, so after a release the ring
   stayed orange (and the haptic came late) until the next poll said closed, and a press inside that window, or while
   the status was stale for any other reason (a failed poll keeps the last status), was **swallowed whole**: no open,
   no haptic, no audio; the lift then released a hold that was never taken. Last row of the table. Quick successive
   presses, the natural thing to do when a button seems dead, hit it every time.
2. **A tap did nothing useful.** A tap is a 3 ms press: the gate opens and closes before a word. Nothing on screen said
   so, and a tap is what people try first. That is the gap Tap to talk fills.

Fix for 1: the ring shows and acts on the phone's own press, which changes at the touch; the Mac's open gate is shown
only when this phone holds no press and has not just let one go (`TalkGate.shows(macOpen:)`), so a press on the Mac's
side (`pointe talk`) still shows, and the demo's "talking" screen still reads Talking. The touch-down handler presses
unconditionally: `TalkGate.press` is idempotent (a second finger is not a new press). Haptics key off the phone's press.

## A press is one message

Owner feedback: "Tap to talk should only send the stuff when the button is released, not live like always-on. It should
be like a WhatsApp message." It applies to both styles and to every input that drives the gate (the ring, the talk key,
Caps Lock, `pointe talk`, the Talk intent, the AirPods stem): they all reach `PttGate._press` / `_release`.

**Root cause.** The gate decided only which audio reaches the ears. The ears then ended turns as in always on: each
Soniox endpoint (`<end>`, a pause of a few hundred ms) became a `TranscriptionFrame`, `SonioxEars` settled it
(`turns.settle`, 0-1 s for a whole sentence) and `_take` answered it (`on_user_utterance`, the brain's reply), and the
hold / brain dump / command phrases in `_take` acted on each piece. So a pause inside an open press ended the turn and
the bot answered mid-press. A hold's 8 s silence release could also fire inside a press.

**The rule.** From the press until the message is sent, `state.ptt.collecting` is true and:

- every final that passes the echo guard and the voice lock is kept (`Ptt.hear`), never settled or taken;
- interim words are `Ptt.live`; status `hearing` is the kept finals plus the live words, whatever their age, and
  `ptt.draft` is true;
- `_user_talking()` is true, so no news or nudge starts over the press or the gap after it;
- a hold's silence release waits (a pause in a press is no silence).

On release the existing tail runs (0.4 s, plus 0.2 s link slack), then the gate sends Soniox `finalize`. Soniox answers
with the last words and `<fin>`; `_tell_finalized` wraps the Soniox service's socket reader and pushes a `PressEnd` frame
behind those words, so it reaches `SonioxEars` after them, in order (a `ControlFrame`, not interruptible). `SonioxEars`
then sends the whole press as one turn through `_take`, the same path every turn takes, but without the settle time:
release is the end of the turn. `Ptt.take` empties it; an empty press sends nothing. If no `<fin>` comes within
`FINAL_WAIT_SECS` (2 s; other ears never send one) the gate pushes `PressEnd(why="timeout")` and what was heard goes.

The message's voice-lock verdict is the weakest of its parts', and if any part repeated the bot's suggestion it answers
no permission (`state.heard_own_words`): joining parts never makes a stranger's "yes" the owner's. A press made before
the last one was sent continues it. Without Pointe's own ears (`CLAUDE_VOICE_EARS=native`, a realtime model hears the
audio) nothing is kept: that model ends its own turns, as before. Always on is unchanged.

**Shown.** Page: the caption is dashed with the label "Draft · not sent yet", then "Sending" after the release, then
fades as the turn lands in the conversation. App: the live bubble carries the same label (`TalkDraft`); the parity is
in `tests/test_ptt_message.py`.

## States, on both surfaces

| State | Hold to talk | Tap to talk |
|---|---|---|
| idle | ring outlined; line "Hold to talk"; hint "Hold Space to talk · Caps Lock toggles" / app: "Hold to talk" | ring outlined; line "Tap to talk"; hint "Tap Space to talk, again to send" / app: "Tap to talk" |
| listening (gate open) | ring filled orange; line "Talking"; haptic on open | ring filled orange; line "Talking · tap to send"; haptic on open |
| sending (just closed, the 0.4 s tail runs) | line "Sent" for 0.6 s, then idle; haptic on close | the same |
| closed by the Mac (90 s, or no audio) | line "Talk closed after 90 s: press again" (8 s), falling tone | "Talk closed after 90 s: tap again" (8 s), falling tone |

The "sending" state is the tail the clients already keep (`PTT_TAIL_MS`, `TalkGate.tail`); it only gets a word now so a
send reads as taken. If the bot starts answering within it, "Speaking" wins.

**A too-short press in Hold mode** (under 250 ms): the gate opened at touch down and closed at the lift, as it must for
instant feedback, so nothing can be undone; the line says "Hold to talk · or choose Tap to talk in Settings" for 2 s,
which is the discoverability the complaint asked for. A press that short still interrupts the bot, as any press does.

**A forgotten open microphone in Tap mode**: the daemon's existing rule closes a press after 90 s (`MAX_OPEN_SECS`,
applied to toggles as to holds, since the daemon cannot tell them apart), the clients drop theirs and say why. 90 s is
the default and the only limit; a longer monologue is what Brain dump is for. The "no audio for 2 s" rule also still
applies.

## Inputs per mode

| Input | Hold to talk | Tap to talk |
|---|---|---|
| page: the ring with the mouse | hold (pointer down opens, up closes) | pointer down toggles; the up is ignored |
| page: the talk key (Space or chosen) | hold (keydown opens, keyup closes; auto-repeat ignored) | keydown toggles; the keyup is ignored |
| page: Caps Lock | toggle | toggle |
| page: keyboard-activated ring (Enter/Space on the focused button), media keys | toggle | toggle |
| page: media keys the system sends itself (connect, media start, a route change; bursts) | ignored | ignored |
| page: leaving the window (blur) | lets go of a held key | nothing: a toggled press stays (the daemon's 90 s rule covers it) |
| `pointe talk` (system-wide shortcut), the Talk intent, AirPods stem, VoiceOver activate | toggle | toggle |
| app: the ring | hold (touch down opens, lift closes) | touch down toggles; the lift is ignored |
| app: the conversation area, 0.35 s long press | hold | the long press toggles |

The last event wins everywhere, as before: a toggle while a hold is down closes it; letting go of the last hold closes
a toggled press.

## Accessibility

Ring label: "Hold to talk" / "Tap to talk" idle, "Talking" open. Hint: Hold: "Hold to talk. With VoiceOver, activate to
start and again to stop." Tap: "Tap to start talking, tap again to send." VoiceOver's activate toggles in both. The
page's ring carries the same label in `aria-label` and `title`.

## Settings

Page: Settings → Microphone gains "Talk button" (`#pref-style`, options `hold` "Hold to talk", `tap` "Tap to talk"),
saved with the hold key; the key's field reads "Talk key". App: Settings menu gains a "Talk button" picker (identifier
`talkStyleSetting`) under Microphone, shown with push to talk. Both read back the stored value on open.

## Parity

`tests/test_ptt_modes.py` reads `ui.html` and `apps/PointeKit/Sources/PointeUI/PushToTalk.swift` and checks both offer the same two styles
with the same labels, the same idle lines and the same 90 s wording; `apps/PointeKit/Tests/PointeUIUnitTests/ParityTests.swift` holds the
app's literals.

## Tests

- Python offline: `tests/test_ptt_modes.py` (parity; the page's tap logic in a headless Chrome on the stub Mac, as
  `tests/test_ui_perf.py` does, skipped without Chrome). `tests/test_ptt_message.py`: scripted finals and pauses inside a
  press give no turn, the release gives exactly one with all of it, the last words finalized after the release are in
  it, the 2 s fallback, an empty press, the draft in the status and on the page, the voice-lock verdict, Soniox's
  `<fin>` marker in order, and always on unchanged.
- Page e2e: `tests/e2e/page_ptt_tap.py`, state `/tmp/cv-state-ptt-tap`, daemon port 7923, TLS 7523, Chrome 9339.
- App: `apps/PointeKit/Tests/PointeUIUnitTests/PushToTalkTests.swift` (`TalkGate.shows`, `TalkStyle` persistence and labels, `TalkDraft`),
  `apps/ios/PointeUITests/PushToTalkUITests.swift` (touch down opens at once; a hold while the status still says open is
  taken; tap to talk opens on one tap and sends on the next).
