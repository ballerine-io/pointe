# Pointe for iPhone: plan

Status: phases 1 and 2 built and tested in the simulator; not yet run on a real iPhone (signing needs the Ballerine
Apple developer account in Xcode). `ios/` holds the app; `tests/e2e/ios_app.py` drives it against a test daemon. Decisions so far: native iOS first (Swift); approvals by voice, as on the desktop; several
ways for the phone to reach the Mac, chosen at pairing; Ballerine's Apple developer account for signing and TestFlight.

## What "top notch" means here

Measured, not felt. The app is done when each holds on a real iPhone over a home network:

| Goal | Target |
|---|---|
| Speech end to first bot audio | no worse than the desktop page (brain p50 2.3 s) plus 150 ms |
| Speakerphone, no headphones | the bot never answers its own voice (echo E2E 4/4 on the phone) |
| Screen locked, app in background | the call keeps going for 30 minutes |
| Network change (Wi-Fi to cellular) | the call comes back by itself within 5 s |
| AirPods press | mutes and unmutes the mic, with a sound cue |
| Battery | under 10% per hour of call |

## Architecture

The phone is a thin audio client. All intelligence stays in the daemon on the Mac.

```
iPhone app                                   Mac daemon
AVAudioEngine, voice processing on   <-->   /voice/phone  (WebSocket, our own protocol)
  (hardware echo cancel, noise)              -> the same brain, echo guard, sessions, approvals
AirPods mute, background audio, CallKit
Sessions list, exact request on screen      /voice/status (existing)
```

- **Transport: our own WebSocket, not WebRTC.** 16 kHz mono PCM up, 24 kHz PCM or Opus down, plus small JSON control
  messages (mute, interrupt, status). It is one TCP connection, so it crosses Tailscale, Twingate and tunnels without the
  UDP setup that `docs/phone.md` still marks untested. The cost: a little more latency on a lossy link than WebRTC.
- **Pipecat stays on the Mac.** The app never sees it, so this protocol is the seam if Pipecat is replaced later.
  Pipecat has a WebSocket transport, so the daemon side is an addition, not a rewrite.
- **Echo:** the iPhone's voice processing removes the bot from the mic in hardware. The daemon still runs its echo guard
  as a second layer.

## Approvals on the phone

Simple commands by voice, the same rules as the desktop (`SECURITY.md`); everything else by a tap on the exact request,
behind Face ID. The daemon side is done: `POST /voice/approve` and `/voice/status` take the phone key. Hardware echo
cancellation makes the bot's own "Should it?" less likely to come back as a yes than on laptop speakers.

## Reaching the Mac

Offered at pairing; all of them need the pairing secret and the app key on top.

| Option | For | Setup |
|---|---|---|
| Same Wi-Fi | trying it at home | none: the app finds the Mac on the local network (Bonjour); TLS with a pinned certificate |
| Tailscale | most developers | Tailscale on both; the app uses the Mac's tailnet name |
| Twingate | teams that already use it | the existing `bin/voice-remote` path |
| Cloudflare Tunnel with Access | no VPN, away from home | `cloudflared` on the Mac, an Access policy for your email; the most setup |

Open to the internet with no access layer (a bare ngrok URL, a port forward) is not offered: the pairing secret would be
the only thing between the internet and your Claude Code sessions.

Pairing: the Mac shows a QR code (`pointe pair`) with the address, the pairing secret, and the certificate fingerprint.
The app pins that fingerprint, so no CA has to be installed on the phone (today's AirDrop step goes away).

## Phases

| # | What | Done when | Size |
|---|---|---|---|
| 1 | Daemon: `/voice/phone` WebSocket transport, QR pairing, pinned TLS, Bonjour | the existing E2E scenarios pass through the new transport, driven by a test client | 2-3 days |
| 2 | iOS core: call screen, voice processing, AirPods mute, background audio, reconnect | a real call on an iPhone over same Wi-Fi and Tailscale | about 1 week |
| 3 | Sessions list, pending request on screen, Live Activity ("river-lantern waits on you"), notifications | a request raised with the phone locked shows on the lock screen | about 1 week |
| 4 | TestFlight beta, phone E2E, Cloudflare Tunnel option | 5 outside testers, the targets above measured | ongoing |

## Open questions

- Notifications when the app is closed need a push service, which means a server we run. Phase 3 starts with
  notifications only while the call is up.
- CallKit (the call shows like a phone call, survives other audio) is the strongest background behavior; Apple restricts
  it to VoIP apps. Check App Review risk before building on it.
- Android: after iOS meets its targets.
