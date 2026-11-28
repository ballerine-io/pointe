# The Mac app

A native menu-bar app for macOS: the call, the transcript, approvals, sessions and the brain dump without a browser
tab. It is another client of the daemon on this Mac, as the page and the iPhone app are. The daemon stays the engine:
the app holds no model key, decides nothing about approvals, and opens no port.

Status: built (`apps/macos/`, `apps/PointeKit/`). Since 1.17.0 its window draws the iPhone app's screens and has every
feature the page and the phone have: [parity.md](parity.md) is the audit, the architecture and the component spec, and
supersedes "Code sharing", "Mac-native UX" (the window), "Parity", "Testing" and "Not in version 1" below, which are
kept as the record of version 1 (the store, the stub daemon and `CallLink` they name are gone: the shared call and
screens replaced them). What is unchanged: the protocol, the authentication, the audio wiring, the shortcut, the daemon's
lifecycle, distribution and the security rules.

## What it is not

(Version 1. The second point no longer holds: the app has all of it.)

- Not a second engine. Ears, brain, mouth, the read-out allowlist, the gate, push to talk's rule and every approval
  rule stay in `daemon.py` and its modules. A rule the app must follow is the daemon's, checked there.
- Not a replacement for the page. Meeting mode, the voice lock's enrolment, the dictionary, briefings, challenge, drive
  mode, show while it says, machines' pairing and phone pairing stay on the page in version 1; the app links to it.
- Not sandboxed, and not in the Mac App Store: it starts the installed plugin's daemon and reads `~/.claude-voice`,
  which a sandbox does not allow.

## Architecture

```
 menu bar item ─┐
 call window ───┤  PointeStore (one per app, main actor)        apps/PointeKit
 call bubble ───┤    polls GET /voice/status every 0.7 s        (shared with the iPhone app)
 notifications ─┘    actions: approve, switch, say, dump, prefs
                     CallLink: one WebSocket, ws://127.0.0.1:<port>/voice/call
                       up: 16-bit PCM 16 kHz, 20 ms chunks      down: 16-bit PCM 24 kHz
                       (IMA ADPCM both ways when the app offers it: protocol 5)
                       text: hello (protocol 5), ping/pong, its own keep-alive, ptt, interrupt
                                  │ loopback only, a proof of the page's key on each request
                     daemon.py on 127.0.0.1:7860 (unchanged)
```

### Which protocol

The page's, on loopback: plain HTTP and one WebSocket on `127.0.0.1:<port>`. `/voice/call` is `socket_call(websocket,
"page")` in `daemon.py`: the same wire format as the phone's `/voice/phone` (`phone.py`, protocol 5), behind the page's
key. The phone's TLS listener is for another device: it needs a certificate, a pairing and an open address, and on the
same Mac it would only add ways to fail. On loopback the app is "the page on this Mac" to every rule that asks
(`_off_the_mac` is false: show while it says is allowed, alerts are never held as "at the Mac", the keep-awake rule
does not run).

### Authentication

`guards.LocalAuth` accepts, on the loopback listener, the cookie `pointe_local=<page key>` (the browser page, which
gets it from `bin/voice-open`), `Authorization: Bearer <token>` (scripts and hooks), or the app's proof; `Host` must be
a local name and an `Origin`, when sent, must equal it.

- **The app proves it holds the page key and never sends it** (`LocalProof.swift`, `local_proof.py`). It reads
  `page_key` and `token` from the state directory (`CLAUDE_VOICE_STATE`, else `~/.claude-voice`) at each connect, and
  puts on every request and on the call's socket `X-Pointe-Proof: v1.<time>.<nonce>.<body SHA-256>.<HMAC>`: an HMAC,
  keyed by HMAC(page key, the token), over the time, a random 128-bit nonce, the method, the path, the query and the
  body's SHA-256. The daemon checks it before it reads the body, accepts it once (the nonce), for 120 seconds either way,
  and only with this start's token, which `bin/voice-daemon` writes anew at every start. A proof then opens what the
  page's cookie opens, the routes only the page on this Mac may use included. With `Host: 127.0.0.1:<port>` and no
  `Origin`. The key and the token are held in memory only: never in UserDefaults, the app's Keychain, a log line, an
  error message, a header or a URL.
- Why a proof and not the key: the app checks the listener when it connects, but the daemon can stop and another
  program can take the port before the app looks again, and the next poll would have handed it the key. A proof it
  catches is spent, stale within two minutes, good for that one request, and bound to a daemon start that is over.
  The page key, not the token alone, keys it: the page key is the identity of "a person's screen on this Mac", which
  is what the app is, and the token is also in the hands of scripts and sessions.
- **Before the key is sent, the app checks who listens.** `bin/voice-daemon` refuses to hand the key to a squatter on
  the port ("answering is not enough"); the app keeps the same rule. `DaemonLocator` reads `daemon.pid`, asks `lsof`
  which process listens on the port, and connects only when the listener is that process or its child. Otherwise it
  says "Another program is answering on port N" and sends nothing.
- A 403 means the key file changed under the app (the file was deleted to rotate it) or the daemon restarted with a new
  token: the app finds and checks the daemon again and reads both files again, then says the page's `notPaired` line
  in the Mac's words.
- The URL session is ephemeral, with cookies and caches off, and connects to `127.0.0.1` only. App Transport Security
  stays on; the one exception is `NSAllowsLocalNetworking` (loopback HTTP).

### Audio

`MacAudio` (in the Mac target) is one `AVAudioEngine`:

- **Echo cancellation.** `inputNode.setVoiceProcessingEnabled(true)` before the engine starts. The bot's voice is
  played by an `AVAudioPlayerNode` on the same engine, so the voice-processing unit has it as the reference and takes it
  out of the microphone. This is what the iPhone app does (`apps/ios/Pointe/Call.swift`), and what Chrome's
  `echoCancellation: true` does for the page. On macOS 14 and later, other apps' audio is ducked as little as the
  system allows (`voiceProcessingOtherAudioDuckingConfiguration`, ducking level `.min`).
- **The wiring that starts.** On macOS the voice-processing unit would not initialise (`-10875`, `kAUInitialize` on the
  output node) with the engine's own mixer-to-output connection, which is in the output device's stereo format; the
  iPhone's same code has no such limit. Seven wirings were tried on a MacBook Pro's built-in microphone and speakers
  (macOS 27): the one that starts feeds the output **one channel at the device's rate**, with that rate read before the
  mixer is first asked for. `MacAudio` tries it first, then the engine's default connection, then no voice processing
  at all: in that last case the call is up, and the window says "This audio device gave no echo cancellation, so the
  bot may hear itself: use headphones."
- **Which channel.** With voice processing on, the built-in microphone's node reports 9 channels (the array and its
  references); channel 0 is the processed voice, and it is the one sent.
- **Formats.** The tap reads the input node's own format (voice processing may change the channel count and rate),
  takes channel 0, resamples to 16 kHz (`Wire.resample`) and sends 320-sample chunks. Down, 24 kHz mono floats are
  scheduled on the player; an `interrupt` stops the player and drops what is queued.
- **Permission.** `AVCaptureDevice.requestAccess(for: .audio)`, with `NSMicrophoneUsageDescription`. Denied: the
  Connect panel says so and offers System Settings → Privacy & Security → Microphone. The hardened runtime needs
  `com.apple.security.device.audio-input`.
- **Device changes.** On `AVAudioEngineConfigurationChange` (AirPods connect or leave, the default device changes, the
  sample rate changes) the engine is stopped, the tap removed, voice processing set again, and the engine restarted with
  the new format, while the WebSocket stays up. A restart that fails ends the call with the reason on the Connect panel.
- **AirPods.** Voice processing over Bluetooth uses the hands-free profile, as on a phone call: the microphone works and
  the output is mono, lower quality. The app follows the system's default devices in version 1; a device picker is not
  built. The stem press is read during a call: see "The AirPods press" below.
- **Mute.** In Always on, mute stops sending (the tap's chunks are dropped). In push to talk the gate decides. The
  system's input mute (`AVAudioApplication.setInputMuted`) follows the mic during a call, so the next AirPods press asks
  for the right state.

### The AirPods press

`apps/PointeKit/Sources/PointeUI/AirPods.swift`; tests in `AirPodsTests.swift`. Two inputs, and both belong to Pointe
only while a real call is up (never with no call, never in a demo):

- **The stem press: the input-mute gesture, macOS 14+.** `AVAudioApplication.setInputMuteStateChangeHandler` is macOS
  only. Apple's documentation says the system calls it "due to a Bluetooth audio accessory gesture (certain AirPods /
  Beats headphones)" and for `setInputMuted`, and that on macOS the app mutes its own input there
  ([setInputMuteStateChangeHandler](https://developer.apple.com/documentation/avfaudio/avaudioapplication/setinputmutestatechangehandler(_:)),
  [setInputMuted](https://developer.apple.com/documentation/avfaudio/avaudioapplication/setinputmuted(_:)); WWDC23
  session 10233, "Enhance your app's audio experience with AirPods": "on macOS, your application is responsible for
  muting any uplink audio when a gesture has been performed"). The handler is mapped to Mic off and on, the app's own
  mic state, so the system's chime and the app agree. In push to talk the press is the talk button, as on the iPhone,
  and the handler refuses the mute so the input stays open. The handler is registered when the call's audio starts and
  removed at hang-up, with the system's mute set back to off.
  Two facts come from one open-source app tested 2026-11-09 ([airpods-meet-mute](https://github.com/joelmgallant/airpods-meet-mute)),
  not from Apple. First, the gesture reaches only an app that records from the AirPods, and only one that also
  observes `inputMuteStateChangeNotification`; without the observer `audiomxd` logs "no recording audio apps found that
  are opted in to input muting" and rejects the press. Second, `setInputMuted` calls the handler synchronously, so the
  app's own change is marked and not taken as a press.
- **Play/pause: `MPRemoteCommandCenter`.** Settings → This Mac → Play/pause in a call: Mute Pointe (the default), Skip,
  or Nothing. macOS sends remote commands to the Now Playing app, and `MPNowPlayingInfoCenter.playbackState` "only
  applies to macOS. You must set this property every time the app begins or halts playback, otherwise remote control
  functionality may not work as expected"
  ([playbackState](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter/playbackstate)). So
  while the commands are held, Pointe's call is Now Playing ("Pointe call" in Control Center). At hang-up they are
  removed and the state is set to stopped, so the music gets its key back. With Nothing they are never taken.

**What one AirPods press sends.** This is not verified on hardware. No agent can press AirPods; a check by a person with
AirPods on a call is the test. Expected: while Pointe records from AirPods and has opted in, the press is the
input-mute gesture; with no call it stays play/pause for the Now Playing app, as before. Apple does not document
that a press is never sent both ways. `PressArbiter` therefore lets the first event win and drops the other source for
0.5 s, so one press never turns the mic off and also mutes Pointe. One open-source app
([meetpods](https://github.com/vinimlo/meetpods)) says macOS 27 no longer hands the gesture to third-party apps; no
Apple source confirms it. If that is so, a press reaches Pointe only as play/pause, which then does what Settings
says.

**Other headsets and the keyboard.** The gesture exists only for certain AirPods and Beats. Other Bluetooth or wired
headsets send their button as play/pause, and so does the keyboard's ⏯ key (F8). During a call both do what Play/pause
in a call says. Outside a call, or with Nothing, Pointe never takes them. Music started during a call becomes Now
Playing and takes the key back until Pointe's next call.
- Audio work never runs on the main thread: the tap converts and hands chunks to the link through a `Sendable` closure.

### What stays in the daemon

Everything that decides: which words approve, what is read out, what a notification may show (`attention[].title`,
`body`, `approvable`), the push-to-talk gate (it drops audio while closed, whatever a client sends), the 90 s limit,
routing, the brain dump's state and its send, preferences (`/voice/prefs`), the idle hang-up. The app keeps only what
belongs to this device: appearance, the talk style (hold or tap), the shortcut, the bubble toggle, launch at login,
alerts on or off.

## Code sharing: a Swift package, not Mac Catalyst

`apps/PointeKit` is a local Swift package (Swift 6 language mode, iOS 18 and macOS 14; macOS 15 since 1.17.0) with two libraries:

| Library | Holds | Used by |
|---|---|---|
| `PointeKit` | `API` models (the daemon's status and every nested type), `Wire`, `TalkGate` / `TalkStyle` / `TalkDraft`, the copy dictionaries the surfaces share, theme tokens, `DaemonAPI` (protocol) and `DaemonClient` (URLSession), `CallLink` (the socket's protocol, heartbeat, redial and refusal rules behind `CallSocket` and `CallAudio` protocols), `PointeStore` (status, the menu-bar state, sessions grouped by machine, approvals, the brain dump's review model), `StubDaemon` for tests and the demo | iOS and macOS |
| `PointeMacKit` | `DaemonLocator` (state dir, page key, pid and listener check, plugin discovery, `voice-daemon ensure`), `Shortcut` and `ReleaseWatch`, `KeychainPresence` | macOS |

Why a package:

- **The iPhone app stays what it is.** Mac Catalyst would make the Mac app a second build of the iOS target: every iOS
  view would have to work in a Mac window, and the things this app exists for are AppKit's (`MenuBarExtra`, a floating
  `NSPanel`, Carbon hot keys, `SMAppService`, launching a process). Catalyst can reach some through bridges, at the cost
  of `#if targetEnvironment(macCatalyst)` across the iPhone app's 12,000 lines and its 21 UI test files.
- **Testable without a simulator.** `swift test` runs the shared logic on macOS in seconds, in CI too. The iOS unit
  tests keep running against the same code.
- **One definition of the words and rules.** The parity tests (`tests/test_copy_parity.py` and the others) read Swift
  source; they read the package, and both apps get the same strings from it.

The cost is honest: SwiftUI views are not shared. An iPhone sheet and a Mac window differ in navigation, density,
pointer and keyboard behaviour; sharing them would bend one to the other. Models, rules and words are shared; each
platform draws them.

**Extraction from `apps/ios/` is in steps, each with the iPhone suite green and no change in behaviour.** The iOS target
keeps its call sites through type aliases (`typealias Wire = PointeKit.Wire`), so a move is a deletion plus an alias,
not a rewrite.

- **Step 1 (this version).** The iPhone project links the package, and takes `Wire` (the call's PCM codec, rates and
  control messages) from it; `apps/ios/Pointe/Audio.swift` is gone.
- **Still in both places:** the models, the talk gate, the words, `MachineView` and the alert plan were lifted into the
  package from the iPhone sources and the Mac app uses them there, but the iPhone target still compiles its own copies.
  Eight Python test files and `tools/product_help.py` read those iPhone files by path (`apps/ios/Pointe/PushToTalk.swift`,
  `Turns.swift`, `BrainDump.swift`, `API.swift`, …), and other work was landing in `apps/ios/` the same day, so moving them
  is its own change: each move deletes the iPhone copy, adds an alias, and repoints the tests that read it.
  Until then `tests/test_macos_parity.py` fails when a dictionary in the package differs from the iPhone's.
- **Later.** The iOS `Call` class onto `CallLink` (the Mac app's call, already behind socket and audio protocols).

## Mac-native UX

Following Apple's Human Interface Guidelines for macOS: the menu bar extra is a status item with a short menu, the
window is an ordinary resizable window with a sidebar, Settings is the Settings scene (⌘,), and every action has a
keyboard path.

- **Menu bar extra** (`MenuBarExtra`, menu style). The icon is the Chorus mark as a template image: at 18 points it is
  the brand's favicon drawing (`docs/brand/logo.md`), in the menu bar's one ink, never redrawn. The state is said beside
  it and in its label, never by colour alone: the mark dimmed with no call, a microphone while talking, and the number
  of sessions that wait. The menu: the state line; Connect or Hang Up; "N need you" with one item per
  request that opens the window on it; Brain Dump; Open Pointe (⌘O); Show Call Bubble During Calls; Settings… (⌘,); Quit.
  Menu items are in title case, as every Mac menu is; Help → Pointe Help (⌘?) opens docs/mac-app.md.
- **The call window** (`Window`, one instance, 760 × 560 by default, remembers its frame). A sidebar lists sessions
  grouped by machine (this Mac first; a machine's header shows offline), each with its agent mark and state (working,
  approve, needs you, idle, offline); selecting one switches the active session (`/voice/switch`). The detail column is
  the conversation: turns, the live hearing bubble (a draft while a press is open), pending approvals as cards with the
  exact request and Deny and Approve, the state line, the talk control, and a field to type. The brain dump replaces
  the conversation while one is on: thoughts, then the structured prompt for review (edit, add more, read it back,
  discard, To:, Send with a second click).
- **The call bubble** (optional; Settings or the menu). A small floating panel (`NSPanel`, non-activating, joins all
  Spaces): the state, the hearing line (or why the last call did not start), the talk mode with the shortcut, a talk
  button, the count of requests, and − and ×. It shows while a call is up or being placed, and with no call only when
  pinned ("Keep it on screen with no call"). It never takes key focus, so the app in front keeps the keyboard; its view
  takes the first mouse, or AppKit would swallow every click on it while another app is active. A click opens the
  window, a drag moves it (the frame is remembered, except in a demo or a test); − makes it a pill that opens out on
  hover or a click, × turns it off. Its menu: Open Pointe, Keep on Screen with No Call, Make Small, Reset Position,
  Hide the Bubble.
- **Launch.** A launch the person made (Finder, Spotlight, the Dock) opens the window, so the app is in reach when the
  menu bar item is hidden by the notch; a login item's launch stays in the menu bar. A call placed from the bubble, the
  menu or ⌘↩ that ends before it starts opens the window on Connect's reason.
- **Settings** (`Settings` scene, tabs). General: appearance (System, Light, Dark), launch at login (`SMAppService
  .mainApp`), the call bubble, alerts. Voice: microphone (Always on or Push to talk, the daemon's pref), talk button
  (Hold or Tap, this Mac's), wait before answering (the daemon's `turns.patience`), voice lock level (read from status;
  changing it or enrolling opens the page), the global shortcut recorder. Pointe on this Mac: the daemon's state and
  version, the plugin found, Start and Restart, each vendor's key as "in the Keychain" or "missing" with Add…, and the
  local mode line.
- **Notifications** (`UNUserNotificationCenter`). One category per kind the daemon names. A permission request has Deny
  first, then Approve only when the daemon marked it `approvable` (the request can be read out and "Approve from
  notifications" is on). The text is the daemon's `title` and `body`: the read-out form, never the full request. The
  action posts `/voice/approve` with `via: "notification"` and the request's id; the daemon checks it again. Posted only
  while the window is not the key window; withdrawn when the item is answered. Approve carries
  `.authenticationRequired`, so a locked Mac asks to unlock first.
- **Approve needs you.** In the window, Approve asks `LAContext.evaluatePolicy(.deviceOwnerAuthentication)`: Touch ID,
  Apple Watch, or the account password where the iPhone asks for Face ID. Deny never asks. A Mac with no way to
  authenticate (no password set) cannot approve from the app; the terminal still can.
- **Global push to talk.** A shortcut the user records (default ⌃⌥Space) talks from any app.

### The shortcut: Carbon hot keys, checked

`RegisterEventHotKey` (Carbon, still shipped and used by every hot-key library) delivers `kEventHotKeyPressed` and
`kEventHotKeyReleased` to the app's event target, system-wide, without the Accessibility or Input Monitoring
permission: the system matches the combination and tells only the app that registered it; the app never sees other
keys. That is what real hold-to-talk needs. Checked on macOS 27 (Xcode 27.2):

- Registration returns `noErr` from a non-sandboxed process for ⌃⌥Space, ⌥Space, ⌥⇧Space, F5 alone and a letter alone.
  (Since macOS 15 a sandboxed app is refused Option-only combinations; this app is not sandboxed.)
- Registration also returns `noErr` for ⌘Space, which Spotlight owns: the system's own shortcuts win silently. The
  recorder therefore refuses a combination with no modifier other than Shift (it would swallow typing), warns about the
  known system ones, and Settings shows "Press it now" to prove the shortcut arrives.
- Press and release both arrive, from another app, with Pointe holding no Accessibility or Input Monitoring
  permission: `apps/macos/e2e/hold_shortcut.swift` held ⌃⌥Space for 700, 300 and 60 ms with Finder in front, and the app
  logged the press and the release 736, 304 and 98 ms apart.
- A press with no length at all (XCUITest's synthesized key) lost its release about one run in three. A person cannot
  press that fast, but a missed release would leave the microphone open, so there is a net under the event: while a
  press is open the app reads that one key's state ten times a second (`CGEventSource.keyState`, no permission, no
  other key seen), and ends the press once the key was seen down and then up three times running (`ReleaseWatch`).

Hold style: press opens the gate (`TalkGate.press(.shortcut)`), release closes it. Tap style: press toggles, release is
nothing. The daemon's own rules still bound it (closed after 90 s, or after 2 s with no audio).

Fallbacks, in order: (1) if a release never arrives and the key's state cannot be read either, the daemon's 90 s rule
closes the gate and the status poll closes the app's side; (2) Tap style needs only
the press; (3) the existing `pointe talk on|off|toggle` bound in any launcher keeps working, since the daemon tells the
call's client to send (`{"type":"ptt","by":"shortcut"}`) and `CallLink` follows it; (4) an `NSEvent` global monitor
was rejected: it needs Input Monitoring and sees every key.

## Daemon lifecycle

- **Find it.** `DaemonLocator` looks, in order, at: a folder the user chose in Settings; `installPath` of `pointe@pointe`
  in `~/.claude/plugins/installed_plugins.json` (and under `CLAUDE_CONFIG_DIR` when set); the newest version folder in
  `~/.claude/plugins/cache/pointe/pointe/`; the folder of a running daemon (from its pid's command line). A candidate
  counts only if it has `bin/voice-daemon` and `.claude-plugin/plugin.json` named `pointe`.
- **Start it.** "Start Pointe" runs `<plugin>/bin/voice-daemon ensure` with `CLAUDE_VOICE_STATE` and
  `CLAUDE_VOICE_DAEMON_PORT` when they are not the defaults and `PATH` extended with `~/.local/bin` and Homebrew (a
  GUI app's `PATH` has neither, and `uv` lives there). The script is the plugin's, unchanged: it checks the port,
  syncs the locked environment, runs the preflight and detaches the daemon, which reads its keys from the Keychain
  itself. Its last lines are shown when it fails. The app never starts `daemon.py` itself and never stops a daemon it
  did not start unless the user presses Restart. Every script is started disclaimed (`ProcessRunner`), so macOS does
  not count it as the app and it gets none of the app's microphone permission (SECURITY.md, "The Mac app").
- **A node.** If `node.json` names a hub, this machine has no call: the app says so, as `bin/voice-open` does.
- **Versions.** The app's version is the plugin's (`tests/test_version.py` holds them together). Status carries the
  daemon's. When they differ the window and Settings say "Pointe on this Mac is 1.14.8; this app is 1.15.0" and how to
  bring the older side up: the plugin with `claude plugin marketplace update pointe`, `claude plugin update
  pointe@pointe`, then Restart; the app from the release page. The app makes no network request to look for updates:
  it compares against the daemon and the installed plugin only.
- **First run.** A short guide in the window, each step with its state: the plugin (found, or the install command to
  copy), a model key (present in the Keychain or the environment as the daemon reports through its preflight, or
  `pointe local`), the daemon (Start), the microphone (Allow), a session (run `/pointe:voice`).
- **Keys.** The app never reads, shows, stores or logs a key. Whether a key is there is `SecItemCopyMatching` for the
  service names in `vendors.KEYS` (`gemini-api-key`, `anthropic-api-key`, …) asking for attributes only, which loads
  no secret and raises no prompt. "Add…" runs the plugin's `bin/pointe key <vendor>`: the existing hidden-input dialog,
  which saves the key through `security -i` on its standard input and reads it back.

## Distribution

- **Now:** a Debug build signed with the team in `apps/ios/.team` (gitignored), for the owner's Macs. `apps/macos/build.sh`
  builds and signs it; nothing is uploaded.
- **Next, once the Developer ID account is approved:** Developer ID Application signing, hardened runtime, `notarytool`
  and a stapled DMG (the steps are in `docs/mac-app.md`; no script is shipped before it can be run), then a Homebrew cask in a `ballerine-io/homebrew-tap`
  repository (`brew install --cask ballerine-io/tap/pointe`) whose `url` is the GitHub release's DMG and whose `sha256`
  the release script prints. A cask in homebrew-cask proper needs notarization and some adoption first.
- **Entitlements, all of them:** `com.apple.security.device.audio-input`. No App Sandbox (it launches the plugin's
  script and reads `~/.claude-voice`), no Apple Events (the key dialog is the plugin's own `osascript` process, not the
  app scripting another app), no network server, no JIT, no library-validation exception.
- Info.plist: `LSUIElement` (no Dock icon while only the menu bar item shows; the app becomes a regular app while a
  window is open, so it has a menu bar and ⌘-Tab), `NSMicrophoneUsageDescription`, `NSAllowsLocalNetworking`.

## Security and privacy

- **No new listener.** The app opens no port and registers no URL scheme.
- **No new outbound host.** It connects to `127.0.0.1` only. `docs/security/egress-allowlist.txt` is unchanged, and
  `tests/test_supply_chain.py` greps the Swift sources' URL literals as it does every other source. No analytics, no
  crash reporter, no update check, no third-party package: the package and the app depend on Apple frameworks only.
- **Approvals are the daemon's.** A click approves the request id the card showed and nothing else (`/voice/approve`
  answers 409 for a request no longer pending); a notification's Approve is offered and accepted only for what the
  daemon can read out; a spoken yes is judged by the daemon alone. Typed words never approve. The app shows the
  `request` text of status as the page does (the exact request; for a session on another machine, the masked preview).
- **Keys never leave the Keychain.** Vendor keys are not read by the app. The page key and the token are read from 0600
  files into memory and never sent: each request carries a proof made with them.
- **Logs.** `os.Logger` (subsystem `io.ballerine.pointe.mac`). Session names, transcripts, requests and anything from
  the daemon's status are logged with `privacy: .private` or not at all; keys and cookies are never passed to a logger.
- **Trust boundary, unchanged:** code running as the user can already read the page key and the token
  (SECURITY.md, Known limits). The app adds no secret and no new holder of an existing one beyond its own memory.

## Parity

The Mac app's words are the page's and the iPhone app's: the shared dictionaries live in `PointeKit` (`ConnectCopy`,
`TurnsCopy`, `BrainDumpCopy`, `TalkStyle`, `TalkDraft`, `AboutCopy`), and the Mac-only lines in `MacCopy`.
`tests/test_macos_parity.py` holds the Mac's dictionary to `ui.html`'s (`CONNECT_COPY`, `DUMP_COPY`, `TURNS_COPY`, the
state titles and the session tags), and the existing parity tests find each Swift dictionary wherever it lives
(`apps/ios/Pointe/` or the package). The theme tokens are `assets/theme.json`'s, checked by `tests/test_theme.py`.

## Testing

| Layer | What | Where |
|---|---|---|
| Shared logic | models decode real status fixtures, `Wire`, `TalkGate`, `CallLink` (hello, pong, interrupt, dead link, redial, refusals) with a fake socket, `PointeStore` (menu-bar state, grouping, approval flow with a fake authenticator, dump targets), `DaemonLocator` against a temporary folder, the listener check, version comparison | `apps/PointeKit/Tests`, `swift test` |
| Mac app | hot-key recorder rules, notification content from attention items, launch-at-login wrapper | `apps/macos/PointeMacTests` |
| UI (XCUITest) | the real app on its stub daemon (`-PointeStub`): Connect, transcript, push to talk by key, approve and deny, sessions by machine, brain dump review and send, Settings, the menu bar item, the global shortcut from another app | `apps/macos/PointeMacUITests`, `apps/macos/test.sh ui` |
| Live | the real app against a real daemon with its own `CLAUDE_VOICE_STATE` and port (never 7860, 7443 or `~/.claude-voice`): found and verified, a call on the microphone, a request denied in the window, one approved through the app's client, a brain dump | `apps/macos/e2e/live.py`, run by hand; it presses the app's controls through the Accessibility API (`axdrive.swift`) |
| Words | the Mac's copy against the page's | `tests/test_macos_parity.py` (offline suite) |
| Versions | the Mac app's `MARKETING_VERSION` equals the plugin's | `tests/test_version.py` |

CI (`.github/workflows/apps.yml`, job `macos`): `swift test` for the package, then `xcodebuild test` of the Mac app's
unit tests, signed ad hoc (it also builds the UI tests). The UI tests run locally: macOS lets XCUITest drive apps only
after a person unlocks Automation Mode (`automationmodetool`: "requires user authentication"), which lapses, so they
cannot run unattended. The live run does not use XCUITest for that reason.

## Verification (2026-11-21, a MacBook Pro, macOS 27, Xcode 27.2)

Checked live, against an isolated daemon (`apps/macos/e2e/live.py`, 22 of 22 checks): the locator found the daemon and
verified the listener; the page key opened it and a wrong key got 403; the app placed the call as a protocol 4 client;
the bot's greeting was played; the built-in microphone, with voice processing on, was heard and came back as a turn; a
request appeared word for word and Deny in the window reached the session with no authentication; a second request was
approved through the app's own client and a repeat was refused as no longer pending; a brain dump was started from the
window, kept what was said, was structured for review and discarded with nothing sent; Hang up ended the call. The
shortcut's press and release were timed from another app (above).

Not checked live: Approve's Touch ID sheet (no script can press it; the store's tests cover both answers and the UI test
covers both with a stand-in), notifications posted by a real daemon, AirPods and a device change during a call, launch
at login, starting the daemon from the app on a Mac where it is stopped (the locator's tests run the script through a
fake runner; the live run started the daemon with the same `voice-daemon ensure`), light appearance, VoiceOver by ear,
and echo cancellation's quality: the run's own `say` through the speakers was not transcribed while people talking in
the room were, which is what cancellation should do, and is not a measurement.

## Decisions

1. Loopback page protocol and the page key, with the listener check before the key is sent.
2. A shared package for models, rules and words; platform views stay separate; no Catalyst.
3. Menu-bar agent that becomes a regular app while a window is open.
4. Carbon hot keys for hold-to-talk; no Input Monitoring.
5. Approve in the window needs Touch ID or the password; a notification's Approve follows the daemon's existing
   `via: "notification"` rule.
6. The app starts the daemon only through the plugin's own `voice-daemon ensure`.
7. Not sandboxed, Developer ID, one entitlement.

## Not in version 1

Meeting mode, voice-lock enrolment, dictionary, briefings, challenge, drive and whisper modes, show while it says,
machine and phone pairing (all on the page, one click away), a microphone picker, the brand's two typefaces (the
window uses the system font), right-to-left layout of Hebrew turns, a string catalogue (every string is English, in one
place per dictionary), the rest of the iPhone extraction, notarization and the cask.
