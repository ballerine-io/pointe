# Push to talk

Hold a key or a button to be heard. Release it, and nothing is heard, transcribed or sent to any vendor. For open
offices, noisy rooms, meetings, and anyone who does not want an open microphone.

The state lives in `ptt.py`; the gate (`PttGate`) is in `daemon.py`.

## Use it

Settings → Microphone: "Always on" or "Push to talk", on the page or in the app. It is one daemon setting, so both
clients agree.

| | Page | iPhone app |
|---|---|---|
| Hold | **Space**, or another key you choose (stored per browser); hold the mic ring with the mouse | touch and hold the mic ring (it opens on touch down); hold the conversation area for 0.35 s (so scrolling still works) |
| Toggle | **Caps Lock**: press to open, press to close | AirPods stem press |
| From any app | a system-wide shortcut running `pointe talk` (below) | the Action button, Back Tap or Siri: "Talk to Pointe" (below) |
| Shows | "Talking" / "Hold to talk" | the same |

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
Settings", "No call is up: press the mic on the page or open the app first", "Pointe is not running on this Mac".

On the iPhone the same thing is the **"Talk"** App Intent ("Talk to Pointe"): bind it to the Action button (Settings →
Action Button → Shortcut), to Back Tap, or say it to Siri. It toggles the app's own press on the call that is up, in the
background too (the call keeps the audio session); with no call up it opens the app and says so.

Either way the gate on the Mac is pressed, so the rules below hold, and the client that holds the call is told to send
its audio (it sends only while a press holds, its own or the shortcut's).

## What the daemon enforces

- The gate sits first after the transport, before the voice detector, the ears and any realtime model. Closed, it drops
  the microphone audio. Whatever a client sends, no audio passes it.
- On release it keeps 0.4 s more, plus 0.2 s of link slack, so your last word is not cut, then asks the ears to finish
  the utterance.
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

## API

- Setting: `"microphone": "always" | "ptt"` in `GET/POST /voice/prefs` (default `always`).
- Control, client text on the call socket: `{"type": "ptt", "open": true|false, "at": <client ms>}`. Ignored unless the
  setting is `ptt`.
- From outside the call: `POST /voice/talk` `{"action": "on" | "off" | "toggle"}` (default `toggle`), with the page's
  key or the CLI token (`$STATE/token`), never a phone key. 409 with a plain-words `detail` when the microphone is Always
  on or no call is up; otherwise the gate is pressed as a client's message would press it, the client gets
  `{"type": "ptt", "open": bool, "by": "shortcut"}` on the call socket and sends accordingly, and the reply is
  `{"open": bool, "mode": "ptt"}`. `GET /voice/status` carries `talk_command` (the command to bind) on this Mac only.
- Status `ptt: {mode, open, opened_at, closed_at, closed_why, sent_bytes, room_heard, room_bytes}`. `closed_why`:
  `released`, `held too long`, `no audio`, `switched to push to talk`. `sent_bytes` counts audio that passed the gate in
  this call. Clients show `open` as the truth.
