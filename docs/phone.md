# Phone access

Start with your phone's browser: it needs nothing built or installed on the phone. The iPhone app is not on TestFlight
or in the App Store yet, so it is built with Xcode ([below](#the-iphone-app)); until it ships, the browser is the
quick way.

## In the phone's browser

1. Give the phone a private way to reach this Mac. Easiest: [Tailscale](https://tailscale.com/download) on the Mac and
   the phone, signed in to the same account, then `pointe pair tailscale`. A VPN that routes to this Mac (Twingate, for
   example): `pointe pair host <name>`. The same Wi-Fi only: `pointe pair wifi`. In Claude Code, `/pointe:setup phone`
   walks you through it.
2. `pointe pair link` prints an address. It holds a secret: send it only to your own phone (AirDrop or Notes), and
   open it once in the phone's browser. The page then works there like on the Mac.

If the browser refuses the Mac's certificate, the steps in [A certificate the phone trusts](#a-certificate-the-phone-trusts)
make it trust this one name. Not measured: how each phone browser treats the certificate on a first visit.

## The iPhone app

### Getting the app

The app is not in the App Store and not on TestFlight yet. Until it is, you build it on your own Mac with Xcode, from
the plugin you installed. In Claude Code, `/pointe:setup apps` does it for you. In a terminal, one command does the
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

`bin/pointe apps doctor` checks each of these and says which is missing.

**What each step does, and why**

| Step | Why it is needed |
|---|---|
| Sign in to Xcode | An iPhone runs only apps that Apple has signed for a known developer. Your Apple Account is that developer. |
| Apple Development certificate | The key, in your Mac's keychain, that signs the app as you. The command reads your team from it, so you never type a Team ID. |
| Team, saved in `~/.claude-voice/apps/.team` | Xcode needs to know which team signs. With one team it is picked for you; with several the command asks once. It is saved outside the plugin's folder, so a plugin update keeps it (a clone keeps it in `ios/.team`, which git ignores). |
| Bundle ID, saved in `~/.claude-voice/apps/.bundle-id` | Apple gives each bundle ID to one team, and `io.ballerine.pointe` belongs to the team that publishes Pointe. The command makes one for you (`io.ballerine.pointe.dev` plus eight characters) and passes it to Xcode on the command line, so the project file stays as committed. It is saved so every rebuild, and every plugin update, updates the same app and keeps its pairing (a clone keeps it in `ios/.bundle-id`). |
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
> | How long a build opens | 7 days, then run `bin/pointe apps ios` again | 1 year |
> | Trust the developer on the iPhone | Once, by hand | Not asked |
> | New bundle IDs | 10 every 7 days (the command reuses one) | No practical limit |
> | Devices | 3 | 100 of each kind |
> | Alerts, the Apple Watch, Face ID, the call | All work: Pointe uses no push server and no paid-only capability | The same |
> | TestFlight or App Store | No | Yes ([docs/ios/app-store.md](ios/app-store.md)) |
>
> A free account is enough to use Pointe every day. The one cost is the weekly rebuild: Xcode keeps one profile for 7
> days, so a rebuild inside that week ends at the same moment as the first one. When the app stops opening, run the
> command again; it prints the exact day and hour each time.

**When something fails**

The command prints the cause and the fix, and keeps Xcode's full output in `build.log` in the build folder (`~/.claude-voice/apps/build/ios`, or `ios/build/apps` in a clone). The usual ones:

| What you see | What it means | Fix |
|---|---|---|
| "No Apple Development certificate on this Mac", or `No signing certificate "iOS Development" found`, or `No Accounts: Add a new account` | Xcode is not signed in, or has no certificate yet | Xcode, Settings, Accounts: sign in, then Manage Certificates, +, Apple Development |
| `Failed to register bundle identifier … not available` | The bundle ID belongs to another team | Delete the saved `.bundle-id` (`~/.claude-voice/apps/.bundle-id`, or `ios/.bundle-id` in a clone) and run again, or pass `--bundle-id com.<yourname>.pointe` |
| `CoreDeviceError error 4016`, "The device is unavailable", or the iPhone shown as not reachable | Xcode knows the iPhone but cannot reach it now | Unlock it and keep the screen on; use a cable, or the same Wi-Fi as the Mac with no VPN in between; tap Trust if asked |
| "Untrusted Developer" on the iPhone, or `profile has not been explicitly trusted by the user` | iOS has not been told to trust your account | iPhone: Settings, General, VPN & Device Management, your Apple Account, Trust |
| `Developer Mode is disabled` | iOS blocks apps built from source | iPhone: Settings, Privacy & Security, Developer Mode, on, restart, confirm. The row appears after the iPhone was connected to a Mac with Xcode |
| The app closes the moment it opens, or "is no longer available", after about a week | The 7 days of a free account's profile ended | Run `bin/pointe apps ios` again |
| `You have not agreed to the Xcode license agreements` | Xcode was installed or updated and never opened | `sudo xcodebuild -license accept` |
| `tool 'xcodebuild' requires Xcode, but active developer directory … is a command line tools instance` | The command line tools are selected instead of Xcode | `sudo xcode-select -s /Applications/Xcode.app` |

Options: `--device <name>` when more than one iPhone is connected, `--team <Team ID>` when the Mac has several teams,
`--no-launch` to install without opening the app, `--dry-run` to see the Xcode command without running it. With
`--sim`, add `--demo` to open the app with invented sessions and no Pointe running.

If you would rather use Xcode's window: open `ios/Pointe.xcodeproj`, choose your team under Signing & Capabilities,
change the Bundle Identifier to one of your own (keep that change out of commits), choose the iPhone, press Run.
Without the app, the page works in the phone's browser ([above](#in-the-phones-browser)).

### Pairing

On the Mac, open Pointe's page: Settings → Phone → **Connect your phone**. The page lists the ways your phone can
reach this Mac (Tailscale, a name you set up such as a Twingate alias, the same Wi-Fi), recommends one, and shows a QR
code. Point the iPhone's Camera at it and tap "Open in Pointe" (or scan it in the app). The page turns to "Connected:
<phone>" when the app has paired. The code works once, for 5 minutes; the app gets its key from the Mac over the
certificate it checks. Each phone gets its own key: connecting another phone keeps the ones already paired, **Unpair**
on a phone signs out that phone only, and **Unpair all** signs out every one. A phone paired with `pointe pair` before
this keeps working; it shows as "Paired phone" until the app reports its name. If no way works, the page says what to
install.

Or, in a terminal, pick how the phone reaches the Mac, then scan the QR code in the app:

| Command | When |
|---|---|
| `pointe pair host <name>` | Twingate, a VPN, or a tunnel you route yourself to this Mac's port 7443 |
| `pointe pair tailscale` | the Mac and the phone are both on Tailscale |
| `pointe pair wifi` | same Wi-Fi only; pair again when the address changes |

With Twingate: a Connector on this Mac (Docker or Colima), a resource for the Mac with an alias such as
`pointe.example.internal`, TCP 7443, access for you only. Then `pointe pair host pointe.example.internal`. If the app says
"Mac not reachable" while Safari on the phone reaches `https://<name>:7443/voice/status` (a warning, then "Forbidden"),
pair again. If Safari can't reach it either, restart the Twingate client: new aliases sometimes don't resolve until then.

## The Mac stays awake during a call

While a call from the phone (or from the page on another device) is up and the Mac is on AC power, the daemon runs
`caffeinate -i -w <its pid>`, so the Mac does not idle-sleep and drop the call. It stops when the call ends or the Mac
goes to battery (checked every 5 seconds), and never runs on battery or when the power source cannot be read. Only idle
sleep is held off: the display may still sleep, and closing a laptop's lid still sleeps it. `/voice/status` says which,
in `keep_awake: {on, why}`.

## What stays on the Mac

The app does what the page does, with one deliberate exception: the voice model's full context is shown only on the
Mac. The page's "What the voice holds" lists the messages of the call's context; the app shows only the token count
(Sessions sheet), and the phone's key is refused `/voice/context`.

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

## A certificate the phone trusts

For the browser page over Twingate, with a certificate the phone trusts for this one name. Call audio is one WebSocket on the same HTTPS port, so no UDP resource is needed.

1. Twingate console: a remote network with a Connector running in Docker (Colima) on this Mac; a resource
   `host.docker.internal`, alias `phone.example.internal`, TCP 7443, access for you only.
2. Done on this Mac: `bin/voice-remote setup phone.example.internal`; the daemon serves HTTPS on 127.0.0.1:7443.
3. AirDrop `~/.claude-voice/tls/pointe-ca.crt` to the phone; trust it in Settings > General > About >
   Certificate Trust Settings. The CA can only vouch for that one name, and its key is destroyed after signing.
4. `bin/voice-remote link` in your own terminal (it prints the pairing secret); open the link on the phone once.

Remote requests need HTTPS, the configured name, and the pairing cookie; anything else gets 403.
