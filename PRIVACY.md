# Privacy

Pointe is open-source software you run yourself: a voice daemon on your own Mac, and an iPhone app that talks to that
Mac. It was built and open-sourced by Ballerine Engineering. Neither Ballerine nor the developer who publishes the iPhone
app runs a server for it, and nothing in Pointe sends anything to either.

## The iPhone app

**The app collects nothing.** It has no analytics, no crash reporting, no advertising, no tracking, no third-party SDKs
and no accounts. It contacts exactly one machine: the Mac you paired it with, at the address in the pairing code, over
TLS pinned to that Mac's own certificate. It contacts no other server, Ballerine's and the app publisher's included.

What the app sends to your Mac, and why:

| What | When | Why |
|---|---|---|
| Your voice (microphone audio) | only while a call is up and not muted | your Mac turns it into commands for your coding sessions |
| What you type, corrections, and your answers to requests (Approve, Deny) | when you send them | the same |
| This iPhone's name and a per-app device identifier | when you pair | so your Mac can list, name and unpair each phone |

What stays on the iPhone: the pairing (your Mac's address, its certificate fingerprint and this phone's key, in the
Keychain), and your settings. Face ID is checked by iOS; the app learns only whether it passed. Motion activity (for
the Drive mode suggestion) is read on the phone, is never sent anywhere, and only if you turn the suggestion on. The
camera reads the pairing QR code and nothing else. Notifications are posted by the app itself; there is no push server.
If you turn on the voice lock, your Mac learns your voiceprint from the call's audio and keeps it on the Mac.

"Try a demo" uses made-up sample data built into the app and contacts no server.

Unpair this phone (in the app's menu) deletes the pairing from the phone. To revoke that phone's key on the Mac as well,
unpair it from the Mac's page (Settings → Phone).

## The Mac daemon

Your Mac is where your voice and your sessions are processed. It reaches the speech and language services you chose
(for example Anthropic, Google Gemini, OpenAI, Soniox or ElevenLabs) with **your own API keys**, kept in your Mac's
Keychain, under your own agreements with those vendors. It can also run local models on the Mac instead, in which case
the voice does not leave the Mac. The full list of hosts the daemon may contact, and why, is in
[docs/security/egress-allowlist.txt](docs/security/egress-allowlist.txt). Neither Ballerine nor the app publisher
receives any of this traffic or has access to your Mac, your keys, your audio or your transcripts.

Transcripts, meeting notes and settings are stored on your Mac, under your user account, and stay there until you
delete them.

## Children

Pointe is a developer tool and is not directed at children.

## Changes and contact

Changes to this policy are made in this file, and its history is the [commit log](https://github.com/ballerine-io/pointe/commits/main/PRIVACY.md).
Questions: open an issue at [github.com/ballerine-io/pointe](https://github.com/ballerine-io/pointe/issues), or see
[SECURITY.md](SECURITY.md) to report a security problem privately.
