# One product on four surfaces

Pointe has four surfaces: the page the daemon serves (`ui.html`), the iPhone app (`apps/ios/Pointe`), the Mac app
(`apps/macos/PointeMac`), and the Linux hub, which serves the same page from a daemon on Linux ([linux.md](../linux.md)). This document is the audit of what each one has, the rule that keeps them the same, and the
architecture that makes "the same" cheap. The matrix itself is generated: [parity-matrix.md](parity-matrix.md).

## The matrix

`python3 tools/parity.py` reads the code of all four surfaces and writes `docs/design/parity-matrix.md`.

- A **feature** is a row in `tools/parity.py` (`GROUPS`): an id, a sentence a user would recognise, and per surface the
  regular expressions that must all be found in that surface's sources: a control's `id` or accessibility identifier,
  the view's type, the daemon route it calls. All found is `yes`, some is `partial`, none is `no`.
- A surface that **cannot** have a feature carries the reason instead of patterns, and is `n/a`. The reasons are
  listed in the generated file under "Bound to a platform".
- **Sources.** The page is `ui*.html`. The iPhone app is `apps/ios/Pointe`, `apps/ios/PointeShared`, `apps/ios/PointeWidget` and the
  package targets it links; the Mac app is `apps/macos/PointeMac` and the package targets it links. Shared Swift is read
  once per app with the other platform's `#if os(...)` branches blanked, so a screen compiled out of the Mac app does
  not count for the Mac. The Linux hub is the page's sources read with the page's patterns: a row gives it its own
  patterns or reason only where a Linux hub differs (`linux=`), and a row the page cannot have keeps the page's reason.
- **The Linux hub's differences** are the daemon's, not the page's: each function in `pointe/` that asks which system it
  runs on (`sys.platform`, `platform.system()`) has an entry in `LINUX_BRANCHES` saying which features it touches and what
  a Linux hub does instead: another path (the login keyring through secret-tool, tmux for a started session, the
  terminal key prompt), a limit (no reopen of the hub's own recent sessions, no one-step local mode), or a bound feature
  with its Linux reason. The generated file lists them at the end.
- **The guard.** `tests/test_parity_matrix.py` (offline suite, CI) fails when the generated file is stale, when a
  feature is missing from a surface without a reason, when a surface marked "cannot" has the feature's code after all,
  when the scan stops noticing a removed control, and when a Mac-only branch in `pointe/` has no `LINUX_BRANCHES` entry
  (or an entry outlives its branch). A gap being closed is listed in `KNOWN_GAPS` there; the list
  only shrinks, and a closed gap left in it fails too.

To add a feature: add its row, build it on every surface, run the script. To drop one from a surface: give the reason
in the row; the reviewer sees it in the diff.

## Where it stood (a pre-release build), and where it is

By the same scan, at a pre-release build (2026-11-21) (kept in `tools/parity_baseline.json`), and now:

| Surface | yes before | no before | yes now | no now | n/a |
|---|---|---|---|---|---|
| Page | 73 | 1 | 121 | 0 | 23 |
| iPhone | 79 | 1 | 131 | 0 | 13 |
| Mac | 43 | 40 | 135 | 0 | 9 |
| Linux hub | (not a surface then) | | 121 | 0 | 23 |

The pre-release Mac app had the call, typing, approvals, sessions by machine, the brain dump and New session. It had none
of: meetings, briefings, challenge, whisper, the dictionary, the conflict alarm, show while it says, machines and
invites, voice-lock enrolment, rename, Orchestrator/Session mode, Clean up my words, recent requests and context, About,
the demo, pairing a phone, or a place in the product help. Each of those sent the person to the page. All of them are in
the Mac app now, because it draws the iPhone app's screens (below).

What stays on one surface, with the reason, is the generated file's "Bound to a platform" table. In short:

- **The phone alone:** reading a pairing code and "Unpair this phone"; starting drive mode and the suggestion to
  (the page already said "drive mode is for a phone in a car", and the Mac follows it: both show the mode and stop it);
  the AirPods press and the lock screen's line; the line about the Mac keeping itself awake; Talk to Pointe from outside
  the app (the Control for Control Center, the Lock Screen and the Action button, the Home Screen widget, the call's Live
  Activity, and the setting that turns them off), which are iPhone system surfaces. The Mac has its own counterparts: the
  talk shortcut, the call bubble, the menu bar item.
- **The Mac alone:** the menu bar item, the call bubble, the talk shortcut named beside the talk mode, open at login, finding and starting Pointe, the keys' presence,
  the folders a new session may start in (the daemon takes that setting at the Mac only: the page has it too).
- **Not on the page:** the device's owner check on Approve (a page has no Touch ID without WebAuthn enrolment), actions
  on a notification, a demo (the page exists only while the daemon runs).
- **Not on the phone:** showing the pairing code; a key for every action (an iPhone has no keyboard by default).
- **The Linux hub:** what the page cannot have, for the page's reasons, and the line about keeping awake for a call
  (holding off sleep and the idle and power checks are macOS only). Its limits beside that: no reopening of its own
  recent sessions, and local roles set by hand instead of the one-step local mode.

## The architecture that keeps them the same

Before, each app had its own screens. The Mac's were a second, smaller set, written against copies of the models, the
push-to-talk gate and the words (`apps/PointeKit` held one copy, `apps/ios/Pointe` another, and a test compared them).

Now there is one of each:

```
 apps/ios/Pointe            the entry point, Siri's phrases, the icon, Info.plist             3 files
 apps/ios/PointeShared      the Talk to Pointe intents, compiled into the app and its widget  1 file
 apps/ios/PointeWidget      the widget extension: the Control, the Home Screen tile, the     5 files
                       call's Live Activity
 apps/macos/PointeMac       the shell: menu bar item, menus and keys, bubble, shortcut,       8 files
                       open at login, find/start the daemon, this Mac's settings
        │  both link
 apps/PointeKit
   PointeUI            every screen, the call (audio, socket, redial), the models,       the iPhone app's
                       the rules, the words, the tokens, fonts and the logo              sources, moved
   PointeKit           the wire format, the loopback endpoint, NewSession, MacCopy
   PointeMacKit        DaemonLocator, the shortcut's rules, Keychain presence           (macOS only)
```

- **`PointeUI` is the iPhone app.** Its sources moved from `apps/ios/Pointe` unchanged, then gained what a second platform
  needs: `DaemonLink` (the phone reaches a paired Mac over pinned TLS with its key; the Mac app reaches its own daemon
  on loopback with the page key, only after the listener was verified), and `#if os(...)` where a call differs.
  `Platform.swift` holds the small differences in one place: the clipboard, a sheet's size and title, Esc, the
  segmented control, "click" for "tap", Touch ID for Face ID.
- **One `Call`.** The iPhone's call class is the Mac's too: the same socket protocol, redial and refusal rules, the same
  push-to-talk sender (so the Mac got the "first word is not lost" fix the day the phone did). Only the audio session
  differs: `AVAudioSession` on the phone; on the Mac the three engine wirings found for 1.15.0, the restart on a device
  change, and mute by sending nothing.
- **A wide Mac window is the page's layout**: the sessions list docked as the left column (the same `SessionsSheet`,
  with New session and Settings at its foot), the conversation and the dock beside it. Under 780 points it is the
  phone's: the strip of sessions and the Sessions sheet.
- **The Mac's shell reads, it does not draw the call.** `MacSession` (public, in `PointeUI`) holds the one `Call`, which
  outlives the window, and gives the menu bar item, the bubble and the shortcut what they show (`CallTitle.line`, the
  same function as the window's title). Menus ask the screen for a sheet (`ask(.newSession)`); notifications are the
  phone's `AlertCenter`. This Mac's own settings are sections the shell hands to the shared Settings sheet.
- **One copy of every dictionary and token.** `tests/test_macos_parity.py` fails when a type is declared in two places.
  The colours are `Brand.swift`'s for both apps, held to `assets/theme.json` and the page by `tests/test_theme.py`.
- **macOS 15** is now the Mac app's minimum (it was 14): the shared screens use the scroll-geometry and section APIs
  that came with iOS 18 and macOS 15.

The page keeps its HTML. It follows the same spec:

## Component spec

One spec for three renderers. Values are points on the apps and CSS pixels on the page.

| Component | Spec | Page | Apps |
|---|---|---|---|
| Tokens | `assets/theme.json`: every colour for light and dark, the fonts, the agent marks | CSS custom properties | `Brand.swift` (both apps) |
| Type | Display (Bricolage Grotesque 300/400): the name, the state line, a sheet's title, the drive line. Text (Instrument Sans 400/500/600): everything else. Mono: the system's, for commands. Sizes: 34, 28, 22, 20, 17 (body), 16, 15, 13, 12, 11 | `--display`, `--font` | `Font.brand(_:_:)`, `Font.display(_:)` |
| Spacing | 4, 8, 10, 12, 14, 16, 18, 22. A screen's gutter is 14 to 18; a card's padding 12 to 16; rows 9 to 12 | `--gutter` | literal paddings |
| Radius | 0 (rows), 12 (buttons, inputs, a settings card), 16 (bubbles, cards, the dock), pill (chips) | same | same |
| Elevation | a hairline (`line`), never a shadow; a card that waits for you has `orange-line` | same | `brandCard`, `orangeLine` |
| State line | a 6-point dot, the title in display type, one muted line under it. Order of states: challenge, brain dump, holding, talking, speaking, a press's note, muted, listening | `showState` | `CallTitle.line` |
| Conversation | your bubbles right on `raised`, the voice's left on `card`; 16 radius, 3 at the speaker's corner; follows the newest line unless you scrolled up, then a New pill | `#list`, `#newpill` | `ConversationView`, `ScrollFollow` |
| Request card | name "needs approval", the exact command in mono on `raised`, one hint line, Deny (outline) and Approve (primary) side by side | `#attention` | `RequestCard` |
| Dock | the mic in the exact middle, 70 points, orange only while live; side controls 46 points with an 11-point label; the Always on / Hold to talk switch over it | `.dock` | `BottomBar`, `MicModeSwitch` |
| Sessions | wide: a left column with mode, sessions by machine, recent requests, New session and Settings at its foot. Narrow: a strip of chips and a sheet | `#side` | `SessionsSheet` docked, `SessionChips` |
| Settings | kicker (11 points, upper case, tracked, `dim`), a card of rows with hairlines, a muted footnote; a switch that is on is orange; the chosen segment is a card on the raised track, never orange | `.settings .group` | `BrandForm` (iOS grouped list; `MacSections` on the Mac) |
| Buttons | primary: `primary`/`on-primary`, 12 radius. Quiet: outline `line-strong`. Row: accent text, red when it deletes | `.go`, plain | `brandPrimary`, `brandQuiet`, `BrandRowButtonStyle` |
| Motion | a card arrives from the bottom edge with opacity (snappy, about 0.25 s); a panel swap is opacity with a 0.98 scale (smooth, 0.3 s); nothing else moves | CSS transitions | `.transition`, `.animation(.snappy/.smooth)` |
| Words | one dictionary per feature; the page's is the source, the apps' are held to it. "tap" on the phone is "click" on the Mac and the page's own wording there | `*_COPY` | `*Copy` enums, `…Here` where the Mac differs |

## What "not smooth" measured as (the 1.16.0 Mac app)

Measured on the 1.16.0 build on its stub daemon (`-PointeStub busy`), a MacBook Pro, macOS 27, with Instruments' Time
Profiler attached (`xctrace record --template 'Time Profiler' --attach`) while the Accessibility API resized the window
480 times and switched session six times:

- **No main-thread blocking.** 1.93 s of main-thread time in a 14 s recording; the heaviest path was window layout
  during the resize, about 2.7 ms per pass (`NSHostingView.layout`), under the 8.3 ms a 120 Hz frame allows. Idle on a
  call: 0.2% CPU. Nothing in the app's own code was above 1 ms per sample: the status poll decodes off the main actor
  and assigns only when the status changed.
- So the roughness was not load. It was **motion and continuity**: nothing animated. A request card, the brain dump
  and the review replaced the conversation in one frame; the conversation jumped to its end on every word heard
  (`scrollTo` without an animation, even while reading further up: there was no "New" pill); a session switch
  repainted the sidebar with no selection transition; the window was the system font and default controls, so it did
  not read as the product the iPhone app and the page are.

The fix is the architecture above: the Mac app draws the iPhone app's screens, with their transitions, their
scroll-follow rule and New pill, their type and their cards, instead of a second set of views.

### The same measurement on the new app

Same Mac, a Debug build on the demo fixtures (`-demo request`, `-demo longTalk`), the iPhone UI suite running in the
simulator beside it:

| | 1.16.0 window | shared screens |
|---|---|---|
| Idle on a call, nothing heard | 0.2% CPU | 0.0 to 0.1% |
| While your words show (the caption's wave animates) | no animation | 6 to 13% |
| A window resize step, 7 turns | 5.4 ms (2.7 ms of layout) | 8.9 ms |
| A window resize step, a long conversation | not measured | 10 to 12 ms (about 10 ms of layout) |
| Main-thread work outside layout and drawing | none above 1 ms | none above 1 ms: `CallView.body` is 0.6 ms a pass |

What this says, plainly: nothing blocks the main thread, and the interactions (a card arriving, a sheet, a session
switch) are short animations that hold a frame. Two things cost more than the old window did. The caption's wave is a
repeating symbol effect that redraws its layer every frame while words are on screen: the phone has the same one, and
on a Mac it is a tenth of a core for as long as you speak. And a resize lays out every bubble, because the conversation
is a plain stack (which is what lets it stay pinned to the newest line): on a long conversation that is about 10 ms a
step in a Debug build, over the 8.3 ms of a 120 Hz frame, so a fast drag of the window's edge can drop frames there.
Neither was changed in this pass; both are listed under "Left for later".

## How it is tested

| What | Where | Runs |
|---|---|---|
| The matrix: stale file, a missing feature, a "cannot" that can, the scan itself | `tests/test_parity_matrix.py` | offline suite, CI |
| The words, the tokens, one copy of each dictionary, the Mac's own lines against the page's | `tests/test_copy_parity.py`, `test_theme.py`, `test_macos_parity.py`, and the per-feature ones | offline suite, CI |
| The product help's Mac paths, read from the screens as the Mac compiles them | `tests/test_product_help.py` | offline suite, CI |
| The shared module: models, rules, the call's refusals, the link, the title, phone pairing | `apps/PointeKit/Tests/PointeUIUnitTests` | `swift test` on the Mac and `xcodebuild test` in the iPhone simulator, both in CI |
| The iPhone app, every screen | `apps/ios/PointeUITests` | locally, on a simulator |
| Talk to Pointe from outside the app: the press, the Lock Screen's Send, Cancel and Hang up, the real Control Center control with the app closed | `apps/ios/e2e/talk_outside_ui.py` (a stand-in Mac) | locally, on a simulator |
| The Mac app's flows on the demo fixtures | `apps/macos/e2e/smoke.py` (Accessibility API) and `apps/macos/PointeMacUITests` (XCUITest) | the smoke unattended; XCUITest only after a person unlocks Automation Mode |
| The Mac app against a real daemon, with nothing of the room sent | `apps/macos/e2e/live.py` | by hand |

## Screenshots

The same screens on the three surfaces, light and dark, are made by:

```
uv run --locked python tools/parity_shots.py            # the page, at a desktop and a phone width
python3 -I apps/macos/e2e/smoke.py --shots /tmp/parity-shots/mac
xcrun simctl launch <simulator> io.ballerine.pointe -demo request   # then: xcrun simctl io <simulator> screenshot
```

They land in `/tmp/parity-shots/` and are not committed: they show invented sessions only, and are retaken at will.

Pictures for the site are in English only. The apps' demo data holds a few Hebrew samples for the right-to-left checks;
add `-demoEnglish` to the launch (`-demo machines -demoEnglish`) and they are swapped for English ones
(`Demo.englishSamples`). `tests/test_site.py` fails when a page of the site holds Hebrew text.

## Left for later

- The conversation as a lazy stack, with the pin to the newest line kept: the cost of a resize on a long conversation.
- The caption's wave as a drawn animation that does not redraw its layer every frame.
- A microphone picker on the Mac, and VoiceOver passes by ear on the Mac's sheets.
- Right-to-left layout was the phone's and is the Mac's now; a Hebrew pass on the Mac's own settings sections is not done.
- The XCUITest suite for the Mac has not run since it was rewritten for the shared screens (Automation Mode needs a person).
