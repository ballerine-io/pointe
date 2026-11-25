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
| Name (30 max) | Pointe: Conversational Coding |
| Subtitle (30 max) | Voice layer for coding agents |
| Category | Developer Tools (primary), none secondary |
| Age rating | 4+: every answer in the questionnaire is None or No (no web browser in the app, no chat between people, no user content) |
| Price | Free, every territory |
| Support URL | https://github.com/ballerine-io/pointe/issues |
| Marketing URL | https://eng.ballerine.com/pointe/ |
| Privacy Policy URL | https://github.com/ballerine-io/pointe/blob/main/PRIVACY.md |
| Copyright | 2026 Ballerine |
| Devices | iPhone only (`TARGETED_DEVICE_FAMILY = 1`). Leave "Apple Vision Pro" and "Mac (Designed for iPhone)" availability off: the app is not tested there |

The site has no privacy or support page of its own, so both go to GitHub; the issues page is where a person reaches the
maintainers. The app's Settings → About links the same privacy policy (App Review 5.1.1(i)). The seller is the
individual Apple developer account that publishes the app, not Ballerine. Ballerine is credited in the description
("Built and open-sourced by Ballerine Engineering"), never as the seller.

No "beta" anywhere in the listing or in the app: App Review 2.2 sends betas to TestFlight, which is where they are. The
app's version line drops "· beta" on the iPhone (`AppVersion.line`), whatever the version.

**Promotional text** (170 max, can change without a new build):

> Talk to the Claude Code, Codex and OpenCode sessions on your Mac. Ask what each one did, send work by name, and
> approve a command with Face ID.

**Keywords** (100 max, comma-separated, no spaces; a word already in the name or subtitle adds nothing):

> claude,codex,opencode,ai,developer,terminal,approve,dictation,speech,assistant,remote,mac,handsfree

**Description:**

> Pointe is a voice layer for your coding agents. Talk to every Claude Code, Codex and OpenCode session on your Mac
> from your iPhone: ask what a session did, send another one work by saying its name, and answer permission prompts
> away from the keyboard.
>
> The app needs Pointe on your Mac, which is free and open source: github.com/ballerine-io/pointe. Install it there,
> then pair this iPhone by scanning the code your Mac shows. No Mac yet? Tap "No Mac yet? Try a demo" on the first
> screen to use the app with sample sessions.
>
> • Ask "what's billing doing?" and hear the answer. Say a session's name to talk to that session alone.
> • See the exact command a session wants to run before you answer. Approve it with Face ID, or deny it with a tap.
> • Read the conversation as it happens. Fix a misheard word, or type instead of talking.
> • Mute Pointe to read its replies instead of hearing them, and skip to the next message.
> • Start a new session, or add one that is already open on the Mac.
> • Meeting notes, a briefing of what happened while you were away, Drive mode for the car, and the night shift for
> work that runs overnight.
> • Start talking from the Lock Screen, Control Center, the Action button or a widget. Alerts tell you when a session
> needs you.
>
> Privacy: the app connects only to your Mac, over an encrypted connection pinned to that Mac's certificate. There is
> no account, and the app has no analytics or tracking. Your Mac uses your own model keys, or models that run on the
> Mac.
>
> Pointe is open source (MIT). Built and open-sourced by Ballerine Engineering.

**What's New:** none for the first version; App Store Connect shows the field from the second version on. Write it
then from that version's line in `CHANGELOG.md`, without "beta".

## Screenshots

6.9-inch (1320 x 2868), from the iPhone 18 Pro Max simulator with the Debug-only `-demo` fixtures and `-demoEnglish`,
in [screenshots/](screenshots/): `1-call.png` (the conversation while Pointe talks, with mute and skip; `-demo
speaking`), `2-request.png` (a request waiting for approval), `3-sessions.png` (sessions and mode), `4-typing.png`
(typing instead of talking), `5-edit.png` (fixing a misheard line), `6-thinking.png` (the wait after a question). Taken
from the source that drops "· beta" from the iPhone's version line, at version 0.8.6 (66). App Store Connect scales the
6.9-inch set down for smaller iPhones, and the app is iPhone only, so no iPad set is asked for. To retake them, headless: `xcrun simctl create` an iPhone 18 Pro Max and `xcrun simctl boot` it
(Simulator.app stays closed), `xcodebuild build -scheme Pointe -configuration Debug -destination id=<udid>`,
`xcrun simctl install`, `xcrun simctl spawn <udid> defaults write com.apple.Preferences
DidShowContinuousPathIntroduction -bool true` (no keyboard tip over the typing screen), `xcrun simctl status_bar <udid>
override --time 9:41 --batteryState charged --batteryLevel 100 --cellularBars 4 --wifiBars 3`, then for each screen `xcrun simctl launch <udid> io.ballerine.pointe -demo <screen>
-demoEnglish -pointe.theme dark` and `xcrun simctl io <udid> screenshot <file>`.

## App Privacy

Answer **Data Not Collected**. "Collected" in Apple's sense means sent off the device where the developer, or a third
party the app integrates, can read it. The app sends audio, text and the device name only to the user's own Mac, which
the user runs and neither the developer nor Ballerine can reach; it embeds no third-party SDK; it has no analytics or
crash reporting. The Mac's calls to model vendors use the Mac owner's own keys under the owner's own accounts, outside
the app. `tests/test_app_store.py` holds this: every URL the iPhone app compiles is a link a person taps (About, the
connection help), and every connection is built on the paired Mac's host (`Pairing.base`, `Pairing.callURL`,
`PairingInvite.pairURL`) with the certificate pin.

The privacy manifests (`apps/ios/Pointe/PrivacyInfo.xcprivacy`, `apps/ios/PointeWidget/PrivacyInfo.xcprivacy`) say the
same, and give the reasons for the required-reason APIs the code calls: user defaults (CA92.1, the app's own settings;
1C8F.1, the app group the widget reads) and the system uptime (35F9.1, the audio clock). The same test fails when the
code calls one the manifest does not name.

Tracking: **No**. Export compliance: `ITSAppUsesNonExemptEncryption` is `false` in `Info.plist`. The TLS to the user's
Mac is Apple's (URLSession), and the app's own crypto only hashes and authenticates (SHA-256 of the Mac's certificate
for the pin, an HMAC proof): both exempt. App Store Connect asks nothing per build. A cipher in the app's code fails
the test, so the answer is looked at again.

## App Review notes

Sign-in required: **No**. Contact: the publishing account's name, phone and email.

**App Review notes** (4000 max):

> Pointe is the iPhone app for Pointe, free and open-source software (MIT) that a developer runs on their own Mac,
> next to the AI coding agents it voices: Claude Code, Codex and OpenCode. Source: https://github.com/ballerine-io/pointe
>
> The app pairs with that one Mac by scanning a QR code the Mac shows. Then it carries the developer's voice to the
> Mac, and shows the sessions, the conversation, and the commands waiting for approval. There is no server run by us
> and no account: the app talks only to the paired Mac.
>
> To review without a Mac: on the first screen, tap "No Mac yet? Try a demo" at the bottom. It opens a sample call with
> made-up sessions, marked "Demo" in the header. In it you can:
> - scroll the conversation, and type a line (Type, in the bottom bar);
> - answer the waiting request: Deny with a tap, or Approve, which asks for Face ID or the passcode first;
> - open Sessions (bottom bar): switch to one session, or start a new one;
> - open Settings (the … button, top right), including Settings → About → Privacy policy.
> Tap the "Demo" badge, or "Exit demo" at the end of Settings, to go back to the pairing screen. The demo uses sample
> data built into the app and makes no network request.
>
> Permissions: the camera only scans the pairing code; the microphone carries the voice to the paired Mac during a
> call; local network reaches the Mac on the same Wi-Fi; Face ID confirms approvals; motion activity (asked for only
> when the user turns on the Drive suggestion) suggests Drive mode. The audio background mode keeps a call up with the
> screen locked, like a phone call; background fetch checks the Mac for a waiting request when iOS allows. The "Talk
> to Pointe" control, widget and Action button open the app on that call; with the call up, the Lock Screen shows it
> in a Live Activity.
>
> NSAllowsArbitraryLoads: the Mac's address is a name the user chooses (a Tailscale or VPN name, or a Wi-Fi address),
> and its certificate is self-signed, so App Transport Security cannot vouch for it. The app pins that Mac's exact
> certificate instead, which it received when it scanned the code, and refuses any other.
>
> Third-party AI: the app sends nothing to an AI provider. The user's own Mac reaches the speech and language
> providers the user chose, with the user's own API keys, or runs local models. The privacy policy says so.
