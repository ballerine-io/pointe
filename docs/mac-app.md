# The Mac app

Pointe in the menu bar, with a native window that has everything the page and the iPhone app have: the call and its
transcript, approvals, sessions by machine, the brain dump, challenge, meetings, briefings, whisper, the voice lock, the
dictionary, the conflict alarm, show while it says, machines, pairing a phone, and Settings. The window draws the
iPhone app's own screens, so the two apps look and behave the same; a wide window adds the page's sessions column. It
talks to the same Pointe on this Mac that the page does, so the two can be used side by side (one call at a time).
What each surface has, and why the few differences exist: [design/parity.md](design/parity.md). The Mac's own parts
(the protocol, the audio, the shortcut, security): [design/macos-app.md](design/macos-app.md).

## Getting it

Download `Pointe-<version>.dmg` from the [newest release](https://github.com/ballerine-io/pointe/releases/latest), drag
Pointe to Applications, and open it. The app is signed with Ballerine's Developer ID and notarized by Apple, with the
ticket stapled, and so is the disk image: macOS opens them without a warning. You need macOS 15 or newer. On a Mac with no Pointe yet, the window is the setup: it installs Pointe
with the `install.sh` built into it (checked against a SHA-256 the app carries, and installing only the release of the
app's own version, checked against the SHA-256 pinned in that script), then asks one question, takes your key and
starts your first call: [Install, Mac](install.md#mac-download-pointedmg-drag-to-applications-open). An existing Claude
Code plugin or standalone install is found and used; the app never installs a second copy.

**Build it from source** instead, from the plugin you installed. In Claude Code, `/pointe:setup apps` does it for you.
In a terminal, one command builds it, signs it, and puts it in `~/Applications`:

```
pointe apps mac
```

You need Xcode 16 or newer (free in the App Store) and macOS 15 or newer. You do not need an Apple Account.
`pointe apps doctor` checks the Mac first and prints the fix for anything missing. The plugin must be installed too
(see the [README](../README.md#install)): built this way, the app starts and talks to the plugin's daemon, and `pointe`
is the command setup puts on your PATH. Contributors building from a clone run `bin/pointe apps mac` there.

**What the command does, and why**

| Step | Why |
|---|---|
| Checks Xcode | The build needs the full Xcode, selected and with its license accepted; the command line tools alone cannot build an app. |
| Chooses how to sign | With an Apple Development certificate in your keychain (a free Apple Account is enough, [how](iphone-app.md#getting-the-app)) it signs as your team. Without one it signs ad hoc, which Xcode calls "Sign to Run Locally". If signing as your team fails, it says why and signs ad hoc instead. |
| Builds Release | The optimized build, into `~/.claude-voice/apps/build/macos` (in a clone, `apps/macos/build/apps`, which git ignores). The first build took 44 s on an Apple-silicon Mac in the clean-install run. |
| Quits a running Pointe and replaces `~/Applications/Pointe.app` | So there is one copy, where Spotlight and Login Items find it. Only the copy at that path is quit; if it was running, the new one is opened. |

Both ways of signing give an app that runs on this Mac. The difference is the microphone permission: macOS ties it to
the signature. Signed as your team, the permission is kept across rebuilds. Signed ad hoc, macOS asks again after each
rebuild. With a team, the app's bundle ID is your own (the saved iPhone bundle ID plus `.mac`), for the same reason as on the
iPhone: `io.ballerine.pointe.mac` belongs to the team that publishes Pointe.

**Gatekeeper** does not stop it. Gatekeeper checks files that were downloaded (macOS marks them as quarantined), and an
app built on this Mac carries no such mark. A copy of your build sent to another Mac is refused there: build on each Mac.

**Start at login:** in the app, Settings, This Mac, "Open Pointe at login". macOS lists it under System Settings,
General, Login Items, where you can remove it.

Options: `--open` opens the app when it is installed, `--adhoc` signs to run locally even with a team, `--dest <folder>`
installs somewhere other than `~/Applications`, `--dry-run` shows the Xcode command without running it. Run the command
again to update. If the build fails, the command prints the cause and the fix; the table in
[The iPhone app](iphone-app.md#getting-the-app) covers the Xcode license, `xcode-select` and signing errors, and the full output
is in `build.log` in the build folder.

For work on the app itself, `apps/macos/build.sh --open` makes a Debug build in `apps/macos/build/dd` and installs nothing.

## Using it

- **The menu bar item** is the Chorus mark, dimmed with no call, with the number of sessions that wait beside it. Its
  menu has Connect, who needs you, Brain dump, Open Pointe, New Session, the call bubble and Settings.
- **The window** (Open Pointe, ⌘O). Wide, it has the sessions on the left, grouped by machine, with Orchestrator or
  Session over them and New session and Settings under them; click a session to make it the one the voice talks to,
  right-click it to rename it or take it off the voice. Narrow, the sessions are a strip over the conversation, as on
  the phone. The conversation is on the right; click something you said to fix it. A request shows its exact text with
  Deny and Approve. Approve asks for Touch ID or your password; Deny does not.
- **Opening the app** from Finder, Spotlight or the Dock opens the window, even when the menu bar item is hidden behind
  the notch. Opened at login, it stays in the menu bar.
- **Connect** (⌘↩): the first time, macOS asks for the microphone. A call that does not start opens the window, where
  Connect says why and what to do.
- **The talk mode** is named at the top of the window and in the bubble: Always on, or in push to talk the shortcut,
  as in "Hold ⌃⌥Space".
- **Talking.** The switch over the mic chooses Always on or push to talk. In push to talk, hold the mic, or hold Space
  while the window is in front, or hold the shortcut from any app (Settings → This Mac → Talk shortcut). Choose Tap to
  talk in Settings to press once to start and again to send. With Always on, the mic, Space and the shortcut mute.
- **AirPods** (during a call): a stem press turns the mic off and on, with the system's own chime;
  in push to talk it talks. The window shows "AirPods: press for mic off" beside the talk mode, and the bubble shows an
  AirPods glyph. Play/pause from other headsets and the keyboard's ⏯ key mutes Pointe by default; Settings → This Mac
  → Play/pause in a call can make it Skip, or Nothing. Outside a call Pointe takes neither, so the music keeps them.
  Mac app only. Details: [features/mute.md](features/mute.md#airpods-and-playpause-mac-app).
- **Type** (⌘T) to send words instead of speaking; typed words never approve.
- **Brain dump** (⌘B on a call): talk freely, press Done, then edit the structured prompt, choose where it goes, and
  press Send twice.
- **New Session** (⌘N): start a Claude Code, OpenCode or Codex session in a folder you already work in. Start asks for
  Touch ID or your password. A start the voice read back shows as a card with Cancel and Start.
  [features/new-session.md](features/new-session.md).
- **Settings** (⌘, or the ••• button): the same list as the iPhone app's (the microphone, the talk button, how long to
  wait before answering, Clean up my words, whisper, the dictionary, sessions and mode, machines, Phone, meetings,
  briefings, challenge, alerts, the voice lock, the conflict alarm, show while it says, appearance, About), then this
  Mac's own: the talk shortcut, the skip shortcut, play/pause in a call, the call bubble, open at login, Pointe on this Mac (running or not, its version, Start
  and Restart), the folders a new session may start in, and the model keys: the Setup menu (`pointe setup <id>`, the
  rows of [setups.md](setups.md)), one line on whether every role is filled,
  and each key as In use, Saved, not used, Needed (the one key an empty role needs) or Optional, never "missing" when
  no role needs it (`KeyPlan`, the daemon's `vendors.key_status`). Add… opens Pointe's own key window, then
  `pointe key check` tries the key with one tiny live call; the app never sees a key.
- **Phone** (Settings, or Call → Pair a Phone…): the paired phones, and Connect your phone, which shows the code the
  iPhone scans, as the page's Settings → Phone does.
- **Machines and people** (Settings → Machines, or Call → Machines): the same sheet as the iPhone app's
  ([iphone-app.md](iphone-app.md#machines-and-people)). Add a machine has one field: paste the line somebody sent you,
  or drop it there, then Add, with Touch ID or your password. People lists who you invited to this Mac, with Invite a
  person, each grant, and Remove. A session or a machine of somebody else carries the owner's name in the sessions
  column, a right-click on a session of your own offers Private once this Mac has people, and Mine shows only your
  sessions. A request on somebody else's machine says who is asked first and
  offers Approve only when it opens to you; New Session offers a machine you may start on, with its own folders; People
  has "What people can do". The Mac app registers no `pointe://` link: paste the line.
- **The Call menu:** Connect or Hang Up (⌘Return), Turn Mic Off (⇧⌘A, in Always on), Brain Dump (⌘B), Type Instead
  of Talking (⌘T), Approve Request (⌘Y, with Touch ID or the password, as the card's button) and Deny Request (⌘D) for
  the first card that waits, Sessions and Mode (⇧⌘S), Start a Meeting (⇧⌘M), Briefing (⇧⌘B), Night Shift (⇧⌘N),
  Machines, Pair a Phone…, Open the page (⇧⌘P). The File menu has New Session and Add Sessions (⇧⌘J). The Voice menu
  has reply length (⌘1 to ⌘4), this Mac's speaking speed (⌥⌘1 to ⌥⌘5) and Clean up my words (⇧⌘K). While a sheet is open the commands for the window wait for it to close.
  Esc closes a sheet and the Type bar. Help, Pointe Help (⌘?) opens this page.
- **Uninstall Pointe…** (in the Pointe menu): `pointe uninstall`'s list, one question (your keys only if you tick their
  box), then it removes Pointe, the app included, and quits.
- **Update Pointe to <version>** shows at the top of the window when the standalone install in your home folder is
  older than the app: it runs the app's `install.sh` for its own version, as on the first launch.
- **Before Pointe runs**, the window is the setup guide; Settings… (⌘,) opens this Mac's own settings over it, and About
  Pointe opens About.
- **The call bubble** (menu or Settings): a small panel over other apps while a call is up, with the state, the talk
  mode and a talk button; if a call did not start, it says why. Click it to open the window; drag it anywhere, and it
  keeps the place. − makes it a small pill that opens out when the pointer is over it; × hides it ("Show Call Bubble
  During Calls" in the menu, or Settings, brings it back). Right-click it for Keep on Screen with No Call, Reset
  Position and the rest.
- **Alerts** (Settings → Alerts): a notification when a session needs you and the window is not in front. Approve on a
  notification appears only for a request Pointe can read out and only with "Approve from notifications" on.
- **No Pointe on this Mac yet?** The window is a setup guide then, with what is missing and the one thing to do about
  each, and Try a demo: invented sessions to look around, with nothing sent anywhere.

Drive mode starts on the phone or by voice; the Mac shows it and can stop it, as the page does.

## Limits

- A copy you built from source is signed for your own Mac only: another Mac refuses it. `Pointe.dmg` is the one to share.
- One call at a time: hang up on the page or the phone to talk here.
- Echo cancellation is macOS's own. If the audio device gives none, the call still starts and the window says to use
  headphones.
- The microphone is the system's default one: there is no picker yet.
- While your words show, the caption's wave animates and takes about a tenth of a processor core.
- The app looks for no updates. When it and the plugin are at different versions, it says which side to update.

## Tests

`apps/macos/test.sh unit`, `smoke` and `ui`, and the live test against a real daemon:
[Running the tests, The apps](../CONTRIBUTING.md#the-apps).

## The signed disk image

`tools/build_dmg.sh` builds `Pointe-<version>.dmg` in one command: the app archived and exported with manual
Developer ID signing from the keychain, notarized with `notarytool`, stapled (`--xcode-account` keeps the old way, through
Xcode's account); a disk image with an Applications
link and the brand's background (`tools/dmg_background.swift`), itself signed, notarized and stapled. The steps around
it, and the GitHub Actions job that does the same with secrets: [releasing.md](releasing.md#4-the-github-release).
