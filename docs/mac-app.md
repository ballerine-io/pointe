# The Mac app

Pointe in the menu bar, with a native window that has everything the page and the iPhone app have: the call and its
transcript, approvals, sessions by machine, the brain dump, challenge, meetings, briefings, whisper, the voice lock, the
dictionary, the conflict alarm, show while it says, machines, pairing a phone, and Settings. The window draws the
iPhone app's own screens, so the two apps look and behave the same; a wide window adds the page's sessions column. It
talks to the same Pointe on this Mac that the page does, so the two can be used side by side (one call at a time).
What each surface has, and why the few differences exist: [design/parity.md](design/parity.md). The Mac's own parts
(the protocol, the audio, the shortcut, security): [design/macos-app.md](design/macos-app.md).

## Getting it

It is not notarized yet and there is no download: you build it on your Mac. One command builds it, signs it, and puts
it in `~/Applications`:

```
git clone https://github.com/ballerine-io/pointe.git && cd pointe
bin/pointe apps mac
```

You need Xcode 16 or newer (free in the App Store) and macOS 15 or newer. You do not need an Apple Account.
`bin/pointe apps doctor` checks the Mac first and prints the fix for anything missing. The plugin must be installed
too (`claude plugin install pointe@pointe`, see the [README](../README.md#install)): the app starts and talks to the
plugin's daemon and has no engine of its own.

**What the command does, and why**

| Step | Why |
|---|---|
| Checks Xcode | The build needs the full Xcode, selected and with its license accepted; the command line tools alone cannot build an app. |
| Chooses how to sign | With an Apple Development certificate in your keychain (a free Apple Account is enough, [how](phone.md#getting-the-app)) it signs as your team. Without one it signs ad hoc, which Xcode calls "Sign to Run Locally". If signing as your team fails, it says why and signs ad hoc instead. |
| Builds Release | The optimized build, into `macos/build/apps` (git ignores it). The first build takes a few minutes. |
| Quits a running Pointe and replaces `~/Applications/Pointe.app` | So there is one copy, where Spotlight and Login Items find it. Only the copy at that path is quit; if it was running, the new one is opened. |

Both ways of signing give an app that runs on this Mac. The difference is the microphone permission: macOS ties it to
the signature. Signed as your team, the permission is kept across rebuilds. Signed ad hoc, macOS asks again after each
rebuild. With a team, the app's bundle ID is your own (`ios/.bundle-id` plus `.mac`), for the same reason as on the
iPhone: `io.ballerine.pointe.mac` belongs to the team that publishes Pointe.

**Gatekeeper** does not stop it. Gatekeeper checks files that were downloaded (macOS marks them as quarantined), and an
app built on this Mac carries no such mark. A copy of your build sent to another Mac is refused there: build on each Mac.

**Start at login:** in the app, Settings, General, "Open Pointe at login". macOS lists it under System Settings,
General, Login Items, where you can remove it.

Options: `--open` opens the app when it is installed, `--adhoc` signs to run locally even with a team, `--dest <folder>`
installs somewhere other than `~/Applications`, `--dry-run` shows the Xcode command without running it. Run the command
again to update. If the build fails, the command prints the cause and the fix; the table in
[phone.md](phone.md#getting-the-app) covers the Xcode license, `xcode-select` and signing errors, and the full output
is in `macos/build/apps/build.log`.

For work on the app itself, `macos/build.sh --open` makes a Debug build in `macos/build/dd` and installs nothing.

## Using it

- **The menu bar item** is the Chorus mark, dimmed with no call, with the number of sessions that wait beside it. Its
  menu has Connect, who needs you, Brain dump, Open Pointe, New Session, the call bubble and Settings.
- **The window** (Open Pointe, ⌘O). Wide, it has the sessions on the left, grouped by machine, with Orchestrator or
  Session over them and New session and Settings under them; click a session to make it the one the voice talks to,
  right-click it to rename it or take it off the voice. Narrow, the sessions are a strip over the conversation, as on
  the phone. The conversation is on the right; click something you said to fix it. A request shows its exact text with
  Deny and Approve. Approve asks for Touch ID or your password; Deny does not.
- **Connect** (⌘↩): the first time, macOS asks for the microphone.
- **Talking.** The switch over the mic chooses Always on or push to talk. In push to talk, hold the mic, or hold Space
  while the window is in front, or hold the shortcut from any app (Settings → This Mac → Talk shortcut). Choose Tap to
  talk in Settings to press once to start and again to send. With Always on, the mic, Space and the shortcut mute.
- **Type** (⌘T) to send words instead of speaking; typed words never approve.
- **Brain dump** (⌘B on a call): talk freely, press Done, then edit the structured prompt, choose where it goes, and
  press Send twice.
- **New Session** (⌘N): start a Claude Code, OpenCode or Codex session in a folder you already work in. Start asks for
  Touch ID or your password. A start the voice read back shows as a card with Cancel and Start.
  [features/new-session.md](features/new-session.md).
- **Settings** (⌘, or the ••• button): the same list as the iPhone app's (the microphone, the talk button, how long to
  wait before answering, Clean up my words, whisper, the dictionary, sessions and mode, machines, Phone, meetings,
  briefings, challenge, alerts, the voice lock, the conflict alarm, show while it says, appearance, About), then this
  Mac's own: the talk shortcut, the call bubble, open at login, Pointe on this Mac (running or not, its version, Start
  and Restart), the folders a new session may start in, and the model keys: the Setup menu (`pointe setup <id>`, the
  rows of [setups.md](setups.md)), one line on whether every role is filled,
  and each key as In use, Saved, not used, Needed (the one key an empty role needs) or Optional, never "missing" when
  no role needs it (`KeyPlan`, the daemon's `vendors.key_status`). Add… opens Pointe's own key window, then
  `pointe key check` tries the key with one tiny live call; the app never sees a key.
- **Phone** (Settings, or Call → Pair a Phone…): the paired phones, and Connect your phone, which shows the code the
  iPhone scans, as the page's Settings → Phone does.
- **The Call menu** has a key for each: Sessions and Mode (⇧⌘S), Start a Meeting (⇧⌘M), Briefing (⇧⌘B), Open the page
  (⇧⌘P). Esc closes a sheet.
- **The call bubble** (menu or Settings): a small panel over other apps with the state and a talk button.
- **Alerts** (Settings → Alerts): a notification when a session needs you and the window is not in front. Approve on a
  notification appears only for a request Pointe can read out and only with "Approve from notifications" on.
- **No Pointe on this Mac yet?** The window is a setup guide then, with what is missing and the one thing to do about
  each, and Try a demo: invented sessions to look around, with nothing sent anywhere.

Drive mode starts on the phone or by voice; the Mac shows it and can stop it, as the page does.

## Limits

- Built from source ([one command](#getting-it)), signed for your own Mac, not notarized. Another Mac will refuse to
  open a copy of your build.
- One call at a time: hang up on the page or the phone to talk here.
- Echo cancellation is macOS's own. If the audio device gives none, the call still starts and the window says to use
  headphones.
- The microphone is the system's default one: there is no picker yet.
- While your words show, the caption's wave animates and takes about a tenth of a processor core.
- The app looks for no updates. When it and the plugin are at different versions, it says which side to update.

## Tests

```
macos/test.sh unit    # the shared package and the app's unit tests: what CI runs
macos/test.sh smoke   # every main flow on invented sessions, through the Accessibility API: no daemon, no microphone
macos/test.sh ui      # the same flows with XCUITest; macOS asks you to allow UI automation first
uv run --locked python -I macos/e2e/live.py   # the real app against its own real daemon: keys, sound, nothing of the room sent
```

## A notarized build (when there is a Developer ID)

Not done yet: it needs a Developer ID Application certificate. The steps, for whoever holds one:

1. `xcodebuild archive -project macos/PointeMac.xcodeproj -scheme PointeMac -configuration Release -archivePath
   build/Pointe.xcarchive DEVELOPMENT_TEAM=<team> CODE_SIGN_IDENTITY="Developer ID Application"`, then export with
   `method: developer-id`. The hardened runtime is already on, with one entitlement (the microphone).
2. `ditto -c -k --keepParent Pointe.app Pointe.zip`, `xcrun notarytool submit Pointe.zip --keychain-profile <profile>
   --wait`, `xcrun stapler staple Pointe.app`.
3. A disk image (`hdiutil create -volname Pointe -srcfolder Pointe.app -ov -format UDZO Pointe.dmg`), notarized and
   stapled the same way, attached to the GitHub release; then a Homebrew cask pointing at it with its SHA-256.
