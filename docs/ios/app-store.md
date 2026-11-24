# The iPhone app on the App Store

What to paste into App Store Connect for Pointe, and how a build gets there. The listing text below is a draft: change
it here first, then in App Store Connect, so the two stay the same.

## Build and upload

`apps/ios/release.sh` archives a Release build and exports it for App Store Connect, signed automatically with the team in
`apps/ios/.team` (gitignored). `--bump` raises `CURRENT_PROJECT_VERSION` by one first (commit that), `--upload` sends the
export straight to App Store Connect; without it the `.ipa` lands in `apps/ios/build/export/` for Transporter. Every upload
needs a build number higher than the last one for that version.

Export needs a team in the paid Apple Developer Program, with an App Store distribution certificate and an App Store
Connect record for the bundle ID `io.ballerine.pointe`. A personal team archives but cannot export: "does not have
permission to create iOS App Store provisioning profiles".

## Listing

| Field | Value |
|---|---|
| Name | Pointe |
| Subtitle (30 max) | Conversation for coding agents |
| Category | Developer Tools (primary) |
| Age rating | 4+ (no objectionable content; no unrestricted web access) |
| Price | Free |
| Support URL | https://github.com/ballerine-io/pointe |
| Privacy Policy URL | https://github.com/ballerine-io/pointe/blob/main/PRIVACY.md |
| Copyright | Ballerine |

The seller is the individual Apple developer account that publishes the app, not Ballerine. Ballerine is credited in the
description ("Built and open-sourced by Ballerine Engineering"), never as the seller.

**Promotional text** (170 max, can change without a new build):

> A conversational layer for your coding agents. Talk to Claude Code, OpenCode and Codex sessions on your Mac:
> hear what each did, and approve commands from your iPhone.

**Keywords** (100 max, comma-separated, no spaces after commas; 93 characters):

> claude,code,coding,agent,voice,developer,terminal,approve,codex,opencode,ai,assistant,remote,mac

**Description:**

> Pointe puts every coding-agent session on your Mac one call away. Talk to them from your iPhone: ask what a session
> did, tell another one what to do next, and answer their permission prompts without walking back to the keyboard.
>
> Pointe is the iPhone companion for the free, open-source Pointe daemon, which runs on your own Mac. Install the
> daemon there first (github.com/ballerine-io/pointe), then pair this iPhone by scanning the code your Mac shows.
>
> • One conversation across sessions. Claude Code, OpenCode and Codex, side by side. Ask "what is billing doing?" and
> hear the answer; say a session's name to switch to it.
> • Approvals you can trust. A request waiting for you shows the exact command it will run. Approve it with Face ID,
> or deny it with a tap.
> • A live transcript. See what was heard, fix a misheard word, or type instead of talking.
> • Meetings, briefings and Drive mode. Bring your sessions into a meeting, hear a briefing of what happened while you
> were away, and keep requests safe while you drive.
> • Private by design. The app talks only to your own Mac, over an encrypted connection pinned to that Mac's
> certificate. No account, no analytics, no tracking. Your Mac uses your own model keys, or models that run on the Mac.
>
> No Mac yet? Tap "Try a demo" on the pairing screen to look around with sample sessions.
>
> Pointe is open source (MIT). Built and open-sourced by Ballerine Engineering.

**What's New in 1.4.0:**

> A "Try a demo" button on the pairing screen, to see Pointe with sample sessions before you set up your Mac.

## Screenshots

6.9-inch (1320 x 2868), from the iPhone 18 Pro Max simulator with the Debug-only `-demo` fixtures, in
[screenshots/](screenshots/): `1-call.png` (the conversation), `2-request.png` (a request waiting for approval),
`3-sessions.png` (sessions and mode), `4-typing.png` (typing instead of talking), `5-edit.png` (fixing a misheard
line). App Store Connect scales the 6.9-inch set down for smaller iPhones. To retake them: install a Debug simulator
build, `xcrun simctl status_bar booted override --time 9:41 --batteryState charged --batteryLevel 100`, then for each
screen `xcrun simctl launch booted io.ballerine.pointe -demo <screen>` and `xcrun simctl io booted screenshot <file>`.

## App Privacy

Answer **Data Not Collected**. "Collected" in Apple's sense means sent off the device where the developer, or a third
party the app integrates, can read it. The app sends audio, text and the device name only to the user's own Mac, which
the user runs and neither the developer nor Ballerine can reach; it embeds no third-party SDK; it has no analytics or crash reporting. The
Mac daemon's calls to model vendors use the Mac owner's own keys under the owner's own accounts, outside the app.
Checked against the Swift sources: every `URLSession` the iPhone app compiles (`apps/PointeKit/Sources/PointeUI`) is built on the paired Mac's address
(`Pairing.base`, `Pairing.callURL`, `PairingInvite.pairURL`) with the certificate pin, and no other host appears.
Settings → About links to the repository and ballerine.com; a tap opens them in Safari, and the app fetches nothing.

Tracking: **No**. Export compliance: `ITSAppUsesNonExemptEncryption` is `false` in `Info.plist` (standard TLS through
URLSession, and SHA-256 of a certificate for the pin), so App Store Connect asks nothing per build.

## App Review notes

Paste into App Review Information → Notes. Sign-in required: **No**.

> Pointe is a companion app for a self-hosted daemon. The daemon is free, open-source software
> (github.com/ballerine-io/pointe) that a developer runs on their own Mac, next to the AI coding agents (Claude Code,
> OpenCode, Codex) it voices. The app pairs with that one Mac by scanning a QR code the Mac shows, then carries the
> developer's voice to it and shows the sessions, the conversation, and the commands waiting for approval. There is no
> server operated by us and no account: the app talks only to the paired Mac.
>
> To review without a Mac: on the first screen, tap "No Mac yet? Try a demo" at the bottom. It opens a sample call
> with made-up sessions, marked with a "Demo" badge in the header. In it you can scroll the conversation, open Sessions
> (bottom bar), open Settings (… at the top right), and answer the waiting request: Deny with a tap, or Approve, which
> asks for Face ID first. Tap the "Demo" badge, or "Exit demo" at the end of Settings, to return to the pairing screen.
>
> Permissions: the camera only scans the pairing code; the microphone carries the voice to the paired Mac during a
> call; local network reaches the Mac on the same Wi-Fi; Face ID confirms approvals; motion activity (asked for only
> when the user turns on the Drive suggestion) suggests Drive mode. Audio background mode keeps a call up with the
> screen locked, like a phone call. The "Talk to Pointe" control, widget and Action button open
> the app on that call, talking; with the call up, the Lock Screen shows it in a Live Activity with Send and Cancel.
