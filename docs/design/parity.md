# One product on three surfaces

Pointe has three surfaces: the page the daemon serves (`ui.html`), the iPhone app (`ios/Pointe`) and the Mac app
(`macos/PointeMac`). This document is the audit of what each one has, the rule that keeps them the same, and the
architecture that makes "the same" cheap. The matrix itself is generated: [parity-matrix.md](parity-matrix.md).

## The matrix

`python3 tools/parity.py` reads the code of all three surfaces and writes `docs/design/parity-matrix.md`.

- A **feature** is a row in `tools/parity.py` (`GROUPS`): an id, a sentence a user would recognise, and per surface the
  regular expressions that must all be found in that surface's sources: a control's `id` or accessibility identifier,
  the view's type, the daemon route it calls. All found is `yes`, some is `partial`, none is `no`.
- A surface that **cannot** have a feature carries the reason instead of patterns, and is `n/a`. The reasons are
  listed in the generated file under "Bound to a platform".
- **Sources.** The page is `ui*.html`. The iPhone app is `ios/Pointe` and the package targets it links; the Mac app is
  `macos/PointeMac` and the package targets it links. Shared Swift is read once per app with the other platform's
  `#if os(...)` branches blanked, so a screen compiled out of the Mac app does not count for the Mac.
- **The guard.** `tests/test_parity_matrix.py` (offline suite, CI) fails when the generated file is stale, when a
  feature is missing from a surface without a reason, when a surface marked "cannot" has the feature's code after all,
  and when the scan stops noticing a removed control. A gap being closed is listed in `KNOWN_GAPS` there; the list
  only shrinks, and a closed gap left in it fails too.

To add a feature: add its row, build it on every surface, run the script. To drop one from a surface: give the reason
in the row; the reviewer sees it in the diff.

## Where it stood (1.16.0)

By the same scan, at commit `a9ddfea` (kept in `tools/parity_baseline.json`):

| Surface | yes | no | n/a |
|---|---|---|---|
| Page | 73 | 1 | 14 |
| iPhone | 79 | 1 | 8 |
| Mac | 43 | 40 | 5 |

The Mac app had the call, typing, approvals, sessions by machine, the brain dump and New session. It had none of:
meetings, briefings, challenge, whisper, drive, the dictionary, the conflict alarm, show while it says, machines and
invites, voice-lock enrolment, rename, Orchestrator/Session mode, Clean up my words, recent requests and context, About,
the demo, or a place in the product help. Each of those sent the person to the page.

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

The fixes are in the architecture below: the Mac app now draws the iPhone app's screens, with their transitions,
their scroll-follow rule and their type, instead of a second set of views.
