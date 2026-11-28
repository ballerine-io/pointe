# Accessibility

Pointe is a voice product, so the screen has one job for accessibility: nothing may be told by sound alone, by motion
alone or by colour alone, and every control must have a name. This page says what holds on the page, the iPhone and
the Mac, and which test keeps it.

## A screen reader

Every control of the call screen has a name VoiceOver (or a browser's screen reader) can say: the microphone, mute,
skip, the mode switch above the mic, the bottom bar, the session chips and rows, the request's Approve and Deny, the
composer and Settings. A button drawn as a symbol or as "×" or "•••" carries a name of words. The state line is one
element, read as "Thinking…, Orchestrating 3 sessions", and the page says it again when it changes (`role="status"`).
A session's agent is read as "runs on Codex".

VoiceOver speaks through the same speaker as Pointe. Pointe does not lower its voice for VoiceOver and VoiceOver does
not wait for Pointe: with both on, mute Pointe (the button beside the state line) and read the conversation, which
holds every line Pointe would have said. That pass was made by reading the labels, not by a person who uses
VoiceOver every day: see "Not done".

## Reduce Motion

With Reduce Motion on (iOS and macOS: Settings → Accessibility → Motion; a browser: `prefers-reduced-motion`), nothing
on a Pointe screen moves by itself and no change is animated:

- the state's dot is still (it shrinks while Pointe thinks and breathes while it speaks or a session works);
- the wave beside the words being heard, the brain dump's and the challenge's symbols do not pulse;
- cards, sheets, the conversation's new lines and the mode switch change at once, with no slide or fade;
- on the page no animation runs or loops, and a scroll the page starts jumps instead of gliding.

Nothing is lost: the state is always in the line's words. In Swift every animation goes through
`apps/PointeKit/Sources/PointeUI/Motion.swift`; a test fails for one that does not.

## Every sound has something to see

| Sound | When | What is on screen with it |
|---|---|---|
| Pointe's voice | every line | the line in the conversation, as it is said |
| the waiting sound | a reply takes long ([Thinking](thinking.md)) | the state line says "Thinking…" |
| a session's tone | [session tones](session-tones.md) are on, and a background session reports | the session's row names its tone ("Codex · tone: rise"), and the report is a line in the conversation |
| the two-note chime | a brain dump or a challenge starts or ends, a request is held for later | the state line ("Brain dump", "Challenge") and the card or panel that opened or closed |
| the page's mute tone | the microphone is turned off or on from the page or an AirPods tap | the mic button and the state line ("Mic off") |
| the iPhone's chime when the Mac closes a press | push to talk: the Mac ended a press by itself | the state line says why ("Sent: held too long") |
| the Mac's chime when it closes a press | the same, in the Mac app | the same line |
| an alert's sound | a session needs you while no call is up ([Alerts](alerts.md)) | the notification's banner, with the session's name and what it needs |

A haptic on the iPhone always comes with a change on the screen: it is attached to that change.

## Large text

The iPhone app follows Dynamic Type: the state line grows up to the second accessibility size and wraps to as many
lines as it needs, with the mute button beside it and the microphone still in reach. The page is whole at 320 CSS pixels wide (a
1280-pixel window at 400% zoom): the state line wraps, and nothing scrolls sideways. The Mac app has no text-size
setting of its own; it follows the window's size.

## The tests

| What | Where |
|---|---|
| Every control of the call screen has a name; Reduce Motion stops the dot, the wave and the pulsing symbols (pictures taken over 1.5 s are the same picture); the state line is whole at the largest text size | `apps/ios/PointeUITests/AccessibilityUITests.swift` |
| Every control of the Mac's call window has a name; with Reduce Motion the state's dot is still | `apps/macos/e2e/smoke.py` |
| Motion.swift's rules | `apps/PointeKit/Tests/PointeUIUnitTests/MotionTests.swift` |
| The page: names, no running animation with reduced motion, the state line at 320 pixels; every Swift animation goes through Motion.swift; every sound has a row above | `tests/test_accessibility.py` |

## Not done

- No pass by a person who uses VoiceOver, Switch Control or a braille display daily. The tests check that names exist
  and read sensibly; they do not check the order of a long session or how it feels beside Pointe's own voice.
- Sheets other than the call screen (Settings, Sessions, Night shift, Meeting) were not walked control by control.
- The Mac app does not scale its text.
- On the iPhone the bottom bar's labels stay at the default text size; the
  state line and the conversation grow.
- Captions for the site's film are in English only.
