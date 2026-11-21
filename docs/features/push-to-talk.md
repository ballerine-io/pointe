# Push to talk

Press a key or a button to be heard. Otherwise nothing is heard, transcribed or sent to any vendor. For open offices,
noisy rooms, meetings, and anyone who does not want an open microphone.

The state lives in `ptt.py`; the gate (`PttGate`) is in `daemon.py`. The two ways to press are designed in
[docs/design/push-to-talk-modes.md](../design/push-to-talk-modes.md).

## Use it

The switch above the mic ("Always on" or "Hold to talk", which reads "Tap to talk" when that is the talk button), on
the page and in the iPhone app; or Settings → Microphone ("Always on" or "Push to talk"). In the iPhone app, Settings is
the ••• button at the top. It is one daemon setting, so every client agrees. Then **Talk button**, each device's own choice: **Hold to talk** (the default: press and hold, let go to
send) or **Tap to talk** (tap to start, the microphone stays open, tap again to send).

| | Page | iPhone app |
|---|---|---|
| The button | the mic ring with the mouse; **Space**, or another key you choose (stored per browser) | the mic ring (it acts on touch down); the conversation area after a 0.35 s press (so scrolling still works) |
| Hold to talk | press opens, release sends | the same |
| Tap to talk | press opens, the next press sends; the release is nothing | the same |
| Toggle, in both | **Caps Lock**: press to open, press to close | AirPods stem press |
| From any app | a system-wide shortcut running `pointe talk` (below) | the Action button, Back Tap or Siri: "Talk to Pointe" (below) |
| Shows | "Hold to talk" or "Tap to talk"; "Talking" ("Talking · tap to send"); "Sent" for a moment after a send | the same, with a haptic at the press and the send |
| Your words | in the caption, dashed and labelled "Draft · not sent yet", then "Sending" after the release | the live bubble, with the same label |

A press is one message, like a voice message: nothing you say while the button is open is a turn. Pause as long as you
like, start over, say "hold on" or "brain dump" mid-thought: none of it is acted on until you let go (Hold to talk) or tap
again (Tap to talk). Then all of it goes to Pointe as one turn, at once, without the "Wait before answering" delay,
since the release already says you are done. A press with nothing heard sends nothing. Always on is unchanged: there a
pause after a sentence still ends the turn ([turn taking](../design/turn-taking.md)).

On the page, a headset or AirPods button press reaches it as a media key (play/pause) and toggles talking, or mutes in
Always on. The system sends play/pause by itself too: when the call connects or media starts, on an audio route change
(a headset joins or leaves, an AirPod comes out), often several in a second. The page takes a media key as a press only
when it comes alone (nothing else within 0.3 s, so a press acts 0.3 s late) and not within 1.5 s of any of those; an
ignored one extends the 1.5 s. Each is logged as a page event, ignored or not.

A press under 0.25 s in Hold mode heard no word; the line says "Hold to talk · or choose Tap to talk in Settings" for
two seconds. A tap forgotten open closes after 90 s by the daemon's rule below; the line says "Talk closed after 90 s:
tap again".

## Talk from any app

The page's keys work only while its tab is focused: a browser gets no key events otherwise. To talk from whatever app
you are in, bind a system-wide shortcut to the daemon's CLI; the page or the phone app stays in the background with
the call up.

1. Settings → Microphone on the page shows the command and copies it: `~/.claude-voice/bin/pointe talk`. That
   launcher is written by the daemon at each start and runs the Pointe it runs from, so the shortcut survives a
   plugin update (the plugin cache path changes with each version).
2. In the Shortcuts app: new shortcut → action **Run Shell Script** → paste the command.
3. Open the shortcut's details (ⓘ) → **Add Keyboard Shortcut**, for example ⌃⌥Space. Shortcuts' keyboard shortcuts are
   system-wide; nothing else to install, no permission to grant.

Press once to talk, again to stop: the shortcut is a **toggle**, not a hold. Seeing a key held from any app needs an
event tap (Input Monitoring or Accessibility permission, a keylogger-class grant), which Pointe does not ask for. The
daemon's own limits still apply: a press forgotten open closes after 90 s, as Caps Lock does. For a real hold from any
app, a tool that sees key down and key up (Raycast, Hammerspoon, BetterTouchTool) runs `pointe talk on` on the press
and `pointe talk off` on the release.

The CLI prints one line and exits 0, or 1 with the reason: "Microphone is Always on: set it to Push to talk in
Settings", "No call is up: press Connect on the page or in the app first", "Pointe is not running on this Mac".

On the iPhone the same thing is the **"Talk"** App Intent ("Talk to Pointe"): bind it to the Action button (Settings →
Action Button → Shortcut), to Back Tap, or say it to Siri. It toggles the app's own press on the call that is up, in the
background too (the call keeps the audio session); with no call up it opens the app and says so.

Either way the gate on the Mac is pressed, so the rules below hold, and the client that holds the call is told to send
its audio (it sends only while a press holds, its own or the shortcut's).

## What the daemon enforces

- The gate sits first after the transport, before the voice detector, the ears and any realtime model. Closed, it drops
  the microphone audio. Whatever a client sends, no audio passes it.
- While a press is open (and until it is sent) every final transcript is kept, not answered: no settle time, no hold
  phrase, no command, no reply, and no news spoken over it. Interim words and kept finals show as the draft.
- On release it keeps 0.4 s more, plus 0.2 s of link slack, so your last word is not cut, then asks the ears to finish
  the utterance. Soniox answers with the last words and a `<fin>` marker; once that marker is in, everything said in the
  press is one turn. Ears that give no marker get 2 s (`FINAL_WAIT_SECS`), then what was heard is sent.
- A second press before the first was sent (within that second or so) continues the same message.
- A press closes by itself after 90 s, or after 2 s with no audio (a lost release). The 90 s limit applies to toggles
  (Caps Lock, AirPods) as well as holds, because the daemon cannot tell them apart. When a press closes by itself, the
  clients drop the hold and say why: `held too long`, `no audio`.
- A new call starts closed.
- A press while the bot speaks interrupts it and cuts any read-out. For the approval rules, your utterance begins at the
  press.
- A press counts as activity for the idle hang-up.

## During a meeting

A [meeting](meeting-mode.md) you started (it asks for consent and shows a recording indicator) sends the room's audio
to the meeting's speech stream without a press. Talking to Pointe outside the meeting stream still needs one. The status
says so (`ptt.room_heard: true`).

## On the iPhone

In a voice-chat audio session, iOS delivers an AirPods stem press as an input mute, not as play/pause. In push to talk,
the app takes that mute as the toggle and unmutes the input again. It also handles play/pause in case iOS sends it.

The microphone runs for the whole call, in push to talk too; the app sends nothing while the gate is closed and keeps
only the last 1.5 s in memory. A press sends at once, right after its press message, the audio from 0.1 s before its
touch-down, then the live audio: the first word is not lost to the time the touch took to reach the gate, or to the wait
for the microphone's next buffer (`TalkSender.swift`). Nothing older than that 0.1 s ever leaves the phone. Measured on
the simulator with `ios/e2e/ptt_latency.py` (the real app and microphone, a stand-in Mac running `ptt.Ptt`): the first
chunk left 83 to 94 ms after the touch (it was 108 to 191 ms), and a press's audio now starts 100 ms before the touch
(it started 0 to 84 ms after it, so that much of the first word was lost).

## API

- Setting: `"microphone": "always" | "ptt"` in `GET/POST /voice/prefs` (default `always`).
- Control, client text on the call socket: `{"type": "ptt", "open": true|false, "at": <client ms>}`. Ignored unless the
  setting is `ptt`.
- From outside the call: `POST /voice/talk` `{"action": "on" | "off" | "toggle"}` (default `toggle`), with the page's
  key or the CLI token (`$STATE/token`), never a phone key. 409 with a plain-words `detail` when the microphone is Always
  on or no call is up; otherwise the gate is pressed as a client's message would press it, the client gets
  `{"type": "ptt", "open": bool, "by": "shortcut"}` on the call socket and sends accordingly, and the reply is
  `{"open": bool, "mode": "ptt"}`. `GET /voice/status` carries `talk_command` (the command to bind) on this Mac only.
- Status `ptt: {mode, open, opened_at, closed_at, closed_why, sent_bytes, room_heard, room_bytes, draft}`. `draft: true`
  while a press's words are kept and not sent yet; `hearing` is then all of them so far, however long the pause. `closed_why`:
  `released`, `held too long`, `no audio`, `switched to push to talk`. `sent_bytes` counts audio that passed the gate in
  this call. Clients show `open` as the truth.
