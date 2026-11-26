# The iPhone app

The iPhone app has the same call and controls as the page: the sessions, the conversation, approvals (Face ID), the
modes, and alerts that reach an Apple Watch. It draws the same screens as the Mac app, from the shared `PointeKit`
package. It needs a paired route to your Mac: [Connect your phone](phone.md) says which one to use and how to pair.

## Getting the app

**Get [Pointe: Voice Coding](https://apps.apple.com/app/id6838678047) on the App Store**, or try the next version early on [TestFlight](https://testflight.apple.com/join/gkRJccpc). Or you
build it on your own Mac with Xcode, from the plugin you installed. In Claude Code, `/pointe:setup apps` does it for you. In a terminal, one command does the
build, the signing and the install, and tells you what to do when something is missing:

```
pointe apps doctor      # what this Mac has and lacks, with the exact fix for each
pointe apps ios         # build, sign for your Apple Account, install on the connected iPhone
pointe apps ios --sim   # no iPhone or no Apple Account: run it in the iPhone Simulator
```

Contributors building from a clone run `bin/pointe apps …` there.

You need a Mac with Xcode 16 or newer (free in the App Store), an iPhone on iOS 18 or newer, and an Apple Account. A
free one is enough. Nothing is uploaded and no file in the repository is changed. Run the same command again at any
time: it updates the app in place and keeps its pairing and settings.

**What to do once, before the first run**

1. Open Xcode, then Settings (⌘,), Accounts, the + button, Apple Account, and sign in.
2. Select the account, press Manage Certificates, the + button, Apple Development.
3. Plug the iPhone into the Mac, unlock it, and tap Trust on "Trust This Computer?".
4. On the iPhone: Settings, Privacy & Security, Developer Mode, turn it on, restart, confirm.

`pointe apps doctor` checks each of these and says which is missing.

**What each step does, and why**

| Step | Why it is needed |
|---|---|
| Sign in to Xcode | An iPhone runs only apps that Apple has signed for a known developer. Your Apple Account is that developer. |
| Apple Development certificate | The key, in your Mac's keychain, that signs the app as you. The command reads your team from it, so you never type a Team ID. |
| Team, saved in `~/.claude-voice/apps/.team` | Xcode needs to know which team signs. With one team it is picked for you; with several the command asks once. It is saved outside the plugin's folder, so a plugin update keeps it (a clone keeps it in `apps/ios/.team`, which git ignores). |
| Bundle ID, saved in `~/.claude-voice/apps/.bundle-id` | Apple gives each bundle ID to one team, and `io.ballerine.pointe` belongs to the team that publishes Pointe. The command makes one for you (`io.ballerine.pointe.dev` plus eight characters) and passes it to Xcode on the command line (`POINTE_BUNDLE_ID`, from which the project derives the widget's ID and the app group), so the project file stays as committed. It is saved so every rebuild, and every plugin update, updates the same app and keeps its pairing (a clone keeps it in `apps/ios/.bundle-id`). |
| Trust This Computer | Lets this Mac install apps on the iPhone. |
| Developer Mode | iOS refuses apps that did not come from the App Store until you turn this on. |
| Build with `-allowProvisioningUpdates` | Lets Xcode ask Apple for a provisioning profile: the signed note that says this app, from this team, may run on this iPhone. It also registers the iPhone with your team. |
| `xcrun devicectl device install app` | Copies the signed app to the iPhone, over the cable or Wi-Fi. |
| Trust the developer (free account, first time) | On the iPhone: Settings, General, VPN & Device Management, your Apple Account, Trust. iOS asks this once per account. |

> **Free Apple Account or paid developer account?**
>
> | | Free (Personal Team) | Apple Developer Program ($99 a year) |
> |---|---|---|
> | Installs on your own iPhone | Yes | Yes |
> | How long a build opens | 7 days, then run `pointe apps ios` again | 1 year |
> | Trust the developer on the iPhone | Once, by hand | Not asked |
> | New bundle IDs | 10 every 7 days (the command reuses two: the app's, and its widget's, the same plus `.widget`) | No practical limit |
> | Devices | 3 | 100 of each kind |
> | Alerts, the Apple Watch, Face ID, the call | All work: Pointe uses no push server and no paid-only capability | The same |
> | Talk to Pointe: the Control, the Action button, Siri, the Live Activity | All work: they run in the app and need no paid-only capability | The same |
> | The Home Screen widget's Mac status | No: it needs an app group, and a free team's profiles carry none. The widget is a plain Talk to Pointe button, which works | Yes |
> | TestFlight or App Store | No | Yes ([ios/app-store.md](ios/app-store.md)) |
>
> A free account is enough to use Pointe every day. The one cost is the weekly rebuild: Xcode keeps one profile for 7
> days, so a rebuild inside that week ends at the same moment as the first one. When the app stops opening, run the
> command again; it prints the exact day and hour each time.

**When something fails**

The command prints the cause and the fix, and keeps Xcode's full output in `build.log` in the build folder (`~/.claude-voice/apps/build/ios`, or `apps/ios/build/apps` in a clone). The usual ones:

| What you see | What it means | Fix |
|---|---|---|
| "No Apple Development certificate on this Mac", or `No signing certificate "iOS Development" found`, or `No Accounts: Add a new account` | Xcode is not signed in, or has no certificate yet | Xcode, Settings, Accounts: sign in, then Manage Certificates, +, Apple Development |
| `Failed to register bundle identifier … not available` | The bundle ID belongs to another team | Delete the saved `.bundle-id` (`~/.claude-voice/apps/.bundle-id`, or `apps/ios/.bundle-id` in a clone) and run again, or pass `--bundle-id com.<yourname>.pointe` |
| `CoreDeviceError error 4016`, "The device is unavailable", or the iPhone shown as not reachable | Xcode knows the iPhone but cannot reach it now | Unlock it and keep the screen on; use a cable, or the same Wi-Fi as the Mac with no VPN in between; tap Trust if asked |
| "Untrusted Developer" on the iPhone, or `profile has not been explicitly trusted by the user` | iOS has not been told to trust your account | iPhone: Settings, General, VPN & Device Management, your Apple Account, Trust |
| `Developer Mode is disabled` | iOS blocks apps built from source | iPhone: Settings, Privacy & Security, Developer Mode, on, restart, confirm. The row appears after the iPhone was connected to a Mac with Xcode |
| The app closes the moment it opens, or "is no longer available", after about a week | The 7 days of a free account's profile ended | Run `pointe apps ios` again |
| `You have not agreed to the Xcode license agreements` | Xcode was installed or updated and never opened | `sudo xcodebuild -license accept` |
| `tool 'xcodebuild' requires Xcode, but active developer directory … is a command line tools instance` | The command line tools are selected instead of Xcode | `sudo xcode-select -s /Applications/Xcode.app` |

Options: `--device <name>` when more than one iPhone is connected, `--team <Team ID>` when the Mac has several teams,
`--no-launch` to install without opening the app, `--dry-run` to see the Xcode command without running it. With
`--sim`, add `--demo` to open the app with invented sessions and no Pointe running.

If you would rather use Xcode's window: open `apps/ios/Pointe.xcodeproj`, choose your team under Signing & Capabilities,
change the Bundle Identifier to one of your own (keep that change out of commits), choose the iPhone, press Run.
Without the app, the page works in the phone's browser ([Connect your phone](phone.md#in-the-phones-browser)).

## What stays on the Mac

The app does what the page does, with one deliberate exception: the voice model's full context is shown only on the
Mac. The page's "What the voice holds" lists the messages of the call's context; the app shows only the token count
(Sessions sheet), and the phone's key is refused `/voice/context`.

## Machines and people

Settings → Machines lists the machines on your voice. More than one person can use a machine, and one voice can reach
several machines ([design/people-and-machines.md](design/people-and-machines.md)).

- **Add a machine**: somebody invited you to their machine and sent you a line or showed you a code. The sheet opens on
  the camera; Paste takes the line from the clipboard. Face ID or the passcode first, then your Mac checks the machine's
  certificate and links. A refusal shows as one sentence and the line stays, to try again. The app asks for a name
  ("Call it") only when your voice already has a machine of that name. Then the list shows the machine with whose it
  is, and one line says, once, which services your voice sends its transcripts to.
- **People**: who you invited to this machine, what each can do (a menu changes it), whether they are online, and the
  services their voice uses. Invite a person takes a name and "Can talk to the sessions" or "Can only watch", asks for
  Face ID, and shows the line with its code to scan, Copy and Share. It works once, for ten minutes, and the sheet
  closes when they pair. Remove asks first, then Face ID. People shows only where your Mac would show an invite.
- **Whose it is**: a session or a machine of somebody else carries the owner's name ("Avi's"). On a machine you can
  only watch, the app offers no focus and no Approve. "Dana is using it" shows while a session works on her request.
  The Sessions sheet has a Mine chip once some session is not yours.
- **Private**: hold a session of your own on a machine that has people, then Private. The people invited to that
  machine no longer see it. Shared with people puts it back.
- **A request on somebody else's machine**: its owner is asked first. The card says who, with the seconds left ("Avi is
  asked first · 14 s"), and has no Approve or Deny until the request opens to you. Then it is a card like your own, and
  an alert like your own. When somebody else answers, one line says who ("Dana approved it"). On your own machine the
  card and the approvals record name the person who answered.
- **New session on somebody's machine**: when its owner allows it, the machine is in the New session sheet. Choose it
  and the sheet shows that machine's folders, whose machine it is, and whether its sessions ask before actions. The
  session shows "started by" your name on their screens. You can keep it Private; the machine's owner still sees it.
- **What people can do** (in People, on the machine's own Pointe): Approve requests, Start sessions, and whether the
  sessions they start always ask first. Each change asks for Face ID.
- A machine that removed you stays in the list as "avi-box removed you", with Remove.

A `pointe://machine` link that opens the app from outside opens Add a machine with the line in it. Nothing is sent
until you choose Add and pass Face ID ([SECURITY.md](../SECURITY.md)).

## Alerts and the Apple Watch

Menu → Alerts. "Alerts on this iPhone" posts a notification when a session needs you and the app is not on screen; iOS
mirrors it to an Apple Watch on your wrist while the iPhone is locked. There is no push server, so this works while the
app is alive: open, or in the background with the call up. With the call down and the app in the background, iOS checks
only when it grants a Background App Refresh (rarely, never in Low Power Mode, never after you swipe the app away).
"Approve from notifications" (shared with the page's Settings, off by default) adds Approve to a notification for a
request Pointe can read out; it needs an unlocked iPhone or a watch on the wrist instead of Face ID.

To check by hand on a real iPhone and watch (the simulator has no watch; not yet done on real devices):
1. Alerts on, call up, lock the iPhone, wear the watch. A request arrives: the watch taps, and shows the session and the
   read-out form, with Deny and Approve.
2. Approve on the watch: the session gets it; the iPhone notification is gone.
3. Answer one on the Mac instead: the watch notification disappears within a second or two.
4. Take the watch off (locked): Approve asks to unlock it first.
5. An unreadable request (`python3 -c …`): the watch shows only "Bash: open Pointe to see the exact request", Deny only.
