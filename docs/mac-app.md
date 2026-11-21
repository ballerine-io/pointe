# The Mac app

Pointe in the menu bar: the call, the transcript, approvals, sessions and the brain dump in a native window, without a
browser tab. It talks to the same Pointe on this Mac that the page does, so the two can be used side by side (one call
at a time). The design, and what was and was not checked: [docs/design/macos-app.md](design/macos-app.md).

## Getting it

It is not notarized yet and there is no download: build it on your Mac (Xcode 16 or newer, macOS 14 or newer).

```
git clone https://github.com/ballerine-io/pointe.git && cd pointe
macos/build.sh --open
```

`build.sh` prints where the app is (`macos/build/dd/Build/Products/Debug/Pointe.app`); drag it to Applications if you
want to keep it. With `ios/.team` present (one line, your Apple Developer Team ID; gitignored) it is signed for that
team, and macOS remembers the microphone permission across rebuilds; without it the build is signed ad hoc and macOS
asks again after each rebuild. The plugin must be installed too (`claude plugin install pointe@pointe`, see the
[README](../README.md#install)): the app starts and talks to the plugin's daemon and has no engine of its own.

## Using it

- **The menu bar item** is the Chorus mark, dimmed with no call, with the number of sessions that wait beside it. Its
  menu has Connect, who needs you, Brain dump, Open Pointe, the call bubble and Settings.
- **The window** (Open Pointe, ⌘O): sessions on the left, grouped by machine; click one to make it the session the voice
  talks to. The conversation is on the right; click something you said to fix it. A request shows its exact text with
  Deny and Approve. Approve asks for Touch ID or your password; Deny does not. Type in the field to send words instead
  of speaking (typed words never approve).
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

- Built from source, signed for your own Mac, not notarized. Another Mac will refuse to open a copy of your build.
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
