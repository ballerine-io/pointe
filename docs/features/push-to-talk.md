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
| Shows | "Talking" / "Hold to talk" | the same |

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
- Status `ptt: {mode, open, opened_at, closed_at, closed_why, sent_bytes, room_heard, room_bytes}`. `closed_why`:
  `released`, `held too long`, `no audio`, `switched to push to talk`. `sent_bytes` counts audio that passed the gate in
  this call. Clients show `open` as the truth.
