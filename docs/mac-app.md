# The Mac app

Pointe in the menu bar: the call, the transcript, approvals, sessions and the brain dump in a native window, without a
browser tab. It talks to the same Pointe on this Mac that the page does, so the two can be used side by side (one call
at a time). The design, and what was and was not checked: [docs/design/macos-app.md](design/macos-app.md).

## Getting it

It is not notarized yet and there is no download: you build it on your Mac. One command builds it, signs it, and puts
it in `~/Applications`:

```
git clone https://github.com/ballerine-io/pointe.git && cd pointe
bin/pointe apps mac
```

You need Xcode 16 or newer (free in the App Store) and macOS 14 or newer. You do not need an Apple Account.
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
  menu has Connect, who needs you, Brain dump, Open Pointe, the call bubble and Settings.
- **The window** (Open Pointe, ⌘O): sessions on the left, grouped by machine; click one to make it the session the voice
  talks to. The conversation is on the right; click something you said to fix it. A request shows its exact text with
  Deny and Approve. Approve asks for Touch ID or your password; Deny does not. Type in the field to send words instead
  of speaking (typed words never approve).
- **New session**, under the sessions: start a Claude Code, OpenCode or Codex session in a folder you already work
  in. Start asks for Touch ID or your password. A start the voice read back shows as a card with Cancel and Start.
  [features/new-session.md](features/new-session.md).
- **Connect** (⌘↩): the first time, macOS asks for the microphone.
- **Talking.** With the microphone set to Push to talk (Settings → Voice), hold the round button, or hold Space while
  the window is in front, or hold the shortcut from any app (⌃⌥Space unless you change it). Choose Tap to talk to press
  once to start and again to send. With Always on, the button, Space and the shortcut mute.
- **Brain dump** (⌘B on a call): talk freely, press Done, then edit the structured prompt, choose where it goes, and
  press Send twice.
- **The call bubble** (menu or Settings): a small panel over other apps with the state and a talk button.
- **Alerts** (Settings → General): a notification when a session needs you and the window is not in front. Approve on
  a notification appears only for a request Pointe can read out and only with "Approve from notifications" on.
- **Settings → Pointe on this Mac**: whether Pointe is running and which version, Start and Restart, and each model
  key as "In the Keychain" or "Missing". Add… opens Pointe's own key window; the app never sees a key.

Everything else (meeting mode, voice-lock enrolment, the dictionary, briefings, machines, phone pairing) is on the
page: Call → Open the page (⇧⌘P).

## Limits

- Built from source ([one command](#getting-it)), signed for your own Mac, not notarized. Another Mac will refuse to
  open a copy of your build.
- One call at a time: hang up on the page or the phone to talk here.
- Echo cancellation is macOS's own. If the audio device gives none, the call still starts and the window says to use
  headphones.
- The window uses the system font, and Hebrew turns are not laid out right to left yet.
- The app looks for no updates. When it and the plugin are at different versions, it says which side to update.

## Tests

```
macos/test.sh unit    # the shared package and the app's unit tests: what CI runs
macos/test.sh ui      # the UI tests, on a stub daemon; macOS asks you to allow UI automation
uv run --locked python -I macos/e2e/live.py   # the real app against its own real daemon: microphone, keys, sound
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
