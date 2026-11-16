# UX review of the iPhone app (November 2026)

A pass over every screen and state of `ios/Pointe` against Apple's Human Interface Guidelines and Brand Guidelines V6
(`docs/design/brand-v6.md`): safe areas, alignment, truncation, Dynamic Type, touch targets, one primary action,
consistent radii and hairlines, keyboard avoidance, VoiceOver labels, contrast, Hebrew, and copy.

## How it was looked at

Every state is a demo fixture (`ios/Pointe/Demo.swift`, `-demo <screen>` in a Debug build), so no Mac and no real
session is involved. The review added the fixtures the layout's edges needed (`empty`, `noSessions`, `many` with twenty
sessions, `longNames` with a branch-long name and a Hebrew one, `longRequest`, `hold`, `speaking`, `muted`) and a
`-sheet <name>` argument that opens a settings sheet at launch.

| Device | Appearance | Type size | Screens |
|---|---|---|---|
| iPhone 18 Pro | light, dark | Large (default) | all fixtures and all sheets |
| iPhone 18 Pro | light | accessibility XXL | call, typing, request, conflict, brain dump, meeting, drive, sheets |
| iPhone SE (3rd generation) | light | Large | call, typing, request, whisper, long command, long names, conflict, meeting, brain dump, drive, sheets |
| iPhone 18 Pro Max | dark | Large | all fixtures and the main sheets |

Screenshots are named `<device>/<appearance>/<screen>.png` below; they were taken with `xcrun simctl io screenshot`
and are not committed (the five App Store images in `docs/ios/screenshots/` are, and were regenerated). The app is
portrait only, so there is no landscape to review.

Severity: **high** hides or cuts something the person needs, or breaks at a supported setting; **medium** is wrong
against the guidelines or the brand and visible in normal use; **low** is an inconsistency; **cosmetic** is taste.

## Findings

### High

| # | Where (screenshot) | What was wrong | Fix |
|---|---|---|---|
| H1 | Typing, keyboard up (`docs/ios/screenshots/4-typing.png`, `pro/*/typing`) | The type bar and the control bar sat on the conversation: bubbles showed between them and behind the keyboard, and the newest line was under the type bar. "At the newest line" was measured on the scroll view's whole bounds, which reach under the controls, so the view thought it was at the end while the end was covered. | The controls are a dock with an opaque ground and a short fade (`brandDock`). The end is measured above the dock's inset, and only a finger takes the view off the newest line: when the keyboard, the type bar or a card takes room, the view goes back to the end (`ScrollPin` in `CallView.chat`). |
| H2 | Every live call (`pro/*/call`) | Two Hang up controls, one in the header and one in the bar. The header's pushed the state line to two lines ("… · 1 / needs you"). | The header's pill shows only with no call up (Connect, Try again, Cancel). Live, Hang up is in the bar. |
| H3 | Meeting (`pro/*/meeting`) | The header read "Command cen… 1": the tagline cut and a sliver of the version. | In a meeting Hang up is a round icon like the menu beside it. The lockup drops the build number, then the tagline, before it cuts a word (`BrandHeader`). |
| H4 | Conflict card (`pro/*/conflict`) | "Ask river-la…", "Ask billing/…": session names cut in the buttons. | One row when all three fit, else the two questions over Dismiss, else a column (`ViewThatFits`). |
| H5 | Accessibility type sizes (`pro/ax-xxl/*`) | The bar's labels ran off both edges and into each other, header icons outgrew their circles, the drive screen pushed the header behind the status bar, and the brain dump's hint and buttons were cut ("Disc…"). | Chrome stops growing like a system bar does: the header row and chips at XXXL, the state line at AX2, the bars at Large with the Large Content Viewer on a long press, the drive line and the panels at XXXL/AX1. Words (bubbles, cards, sheets) scale all the way. |
| H6 | A long command; a small screen or the keyboard with a card up (`pro/light/longRequest`, `se/light/whisper`) | A nine-line command pushed Deny and Approve off the card. With the keyboard and a card, the dock was taller than the screen and the header slid up under the status bar. | The command scrolls in its box past 150 points. The cards over the bar scroll inside the dock once they would leave less than a strip of the conversation (`Dock`, `FitScroll`). |
| H7 | Every sheet (`pro/*/sessions`, `meetingStart`, …) | Section headers and footers were body size in ink, as loud as the rows they explain (they take the font around the list). | Headers are the brand's kicker (11 points, upper case, tracked, dim); footers are muted footnotes (`brandKicker`, `brandFootnote`, `KickerSection`). |
| H8 | Voice lock, Machines, Briefing sheets | "Enrol my voice", "Add this device", "Delete my voiceprint" and "Cancel" looked like lines of text: ink, and the deleting ones not red. | A settings-row button is the accent, red when it deletes, dim when disabled (`BrandRowButtonStyle`). |

### Medium

| # | Where | What was wrong | Fix |
|---|---|---|---|
| M1 | The live bubble (`pro/*/call`, `talking`) | Set in the system font, bold, and italic for a push-to-talk draft. The brand has no italic and no system sans. | Instrument Sans medium; a draft is muted. The whisper size is the display family. |
| M2 | State line | The dot floated between the title and the subtitle. | The dot sits on the title's first line; the subtitle is indented under the title. |
| M3 | Whisper card with the keyboard up | Lines cut ("… A wh…"). | The lines are never cut. When the keyboard leaves less room than the card needs, the card scrolls inside the dock. |
| M4 | Meeting | Notes showed as ghost text under and below the bar (a 92% fade). | The same opaque dock as the call. |
| M5 | Touch targets | Header buttons 36 points, Connect pill 32, Demo badge 26, Send 38, session chips 34, machine filter 26, voice-lock levels and briefing days about 30. | Each takes a 44-point touch without growing what is drawn (`touchTarget`); the pill is 36 high. |
| M6 | Header with the Drive button | The version was cut to "1.13…". | As H3: the build number goes first. |
| M7 | Voice lock levels | The chosen level was a black block with the labels touching, unlike the app's segmented controls. | A card on the raised track with a hairline, footnote size. |
| M8 | No call, Mac not reachable (`pro/*/connect-unreachable`) | "Mac not reachable" twice (header and stage), and "No sessions" claimed before the Mac had answered. | The stage alone says it; the chips say nothing about sessions until there is a status. |
| M9 | Pairing (`pro/*/pair`) | A blank hole where the camera shows (before it starts, when it is denied, on a simulator), the system's bordered field, a small left-aligned Pair. | A framed viewfinder with one line under the camera, a brand field, Pair as the full-width primary button. |
| M10 | Empty call and empty meeting (`pro/*/empty`) | The description was larger and darker than a bubble. | A quiet symbol, a display line, one muted sentence (`EmptyNote`). |
| M11 | Session strip with a long name (`pro/*/longNames`) | One chip took the whole strip and the others were a long swipe away. | A chip's name is at most 220 points and keeps both ends. The full name is in the Sessions sheet and the request card. |
| M12 | Voice lock on, something ignored | "2 ignored (not your voice)" beside the state wrapped the line above it. | Its own line under the state, underlined as the link it is. |
| M13 | Alerts sheet | No Done, unlike every other sheet. | Done. |
| M15 | A raised hand on a wide phone (`max/dark/meetingHand`) | "Type it inst…": the three buttons were a hair too wide for one row and the last was cut. | The row's labels scale down a little before they are cut; narrower, the buttons stack as before. |
| M14 | Switches | The Alerts switches were the dark accent; the others the brand's orange. | Every switch in a sheet is orange (`BrandForm`, `BrandList`). |

### Low

| # | Where | What was wrong | Fix |
|---|---|---|---|
| L1 | Briefing ready, briefing bar, Drive suggestion, both control bars, light theme | A card with no border on a ground of its own colour: floating text. | The card's hairline (`brandCard`). |
| L2 | Bubbles, type field | Radii 18 and 6, and 16 for an input: off the brand's scale. | 16 with 3 at the speaker's corner; 12 for the field. |
| L3 | Fix it sheet | "Heard" and "You meant" as bold captions, the same distance from their text as from each other. | Kickers that sit on what they name; a hairline on the field. |
| L4 | Sessions sheet | The mode control was inset from the cards under it; a 35-point hole under the title. | Edge to edge with the cards; 12 points under an inline title. |
| L5 | Briefing days | The chosen days were black blocks; every other chosen chip is the tint. | The tint with the orange hairline. |
| L6 | Header | No edge: bubbles were cut hard under it. | A hairline under the header. |
| L7 | Drive | The frame was 10 points from the edge, the cards under it 14. | 14. |

### Cosmetic, and left as it is

| # | Where | What | Why it stays |
|---|---|---|---|
| C2 | Typing | The type bar is over the control bar, not against the keyboard. | The mic's place is fixed by design ("the mic never moves"). Swapping them moves it. For the owner to decide. |
| C6 | Sheets | The space under a sheet's title is partly the system's bar (iOS 27). | Not the app's to change. |

### Closed after the review (1.13.8)

| # | Where | What was wrong | Fix |
|---|---|---|---|
| C1 | Your bubbles | Text of several lines was set to the right edge. | The bubble stays at the right; its lines start where the text reads from: English on the left, Hebrew on the right (`Bubble.textStart`). The live bubble too. |
| C3 | Hold | "Holding · say “go ahead” when you're done" was a two-line title. | The state is "Holding"; the line under it says "Say “go ahead” when you're done". The page says the same (`TurnsCopy`, `TURNS_COPY`). |
| C4 | Speakers sheet | Bare turn counts (9, 14, 6). | "9 turns" (`MeetingCopy.turns`). |
| C5 | Brain dump | "Brain dump" was the state line and the panel's title. | The panel shows its icon and its one line; the icon is the heading VoiceOver reads ("Brain dump"). |
| C7 | Request card at accessibility XXL | A long session name broke inside words beside the agent's badge. | At the accessibility sizes the badge goes under the name, which gets the card's width and breaks at its hyphens and slashes. |
| C8 | Whisper card, keyboard up | The card showed its first line and scrolled for the rest. | When the dock leaves it less than its whole height, it folds to its title and Show notes, on one line (an iPhone SE with the keyboard up has about 30 points). A tap opens the notes; with the room back it is whole. |
| — | Copy shared with the page | "Or type below" under Connect, with no type bar below; the meeting sheet did not say what Pointe does there; a disabled lock level gave no reason. | "Once connected, tap the keyboard to type"; "Pointe sits in and takes notes for you. It stays quiet unless you let it speak."; "Enrol your voice to use the other levels." |

### Not captured

- **Connect states that need a Mac to answer**: not paired (401), on a call elsewhere, connecting, reconnecting. They
  are the same stage as "Mac not reachable" with other words; `ConnectFace` is pure and unit tested for every state.
- **Notifications**: drawn by iOS; `AlertsUITests` covers their content against a test daemon.
- **Haptics and motion**: not visible in stills. Read in code: a warning on a new request, hand and conflict, success
  on an answer, impact on mute and brain dump, selection on a chip and a filter; transitions are 0.2 to 0.35 s.

## Tests

`ios/PointeUITests/LayoutUITests.swift`, on the demo call:

- the type bar and the keyboard never cover the newest line, launched with the bar open and when the bar is opened;
- at accessibility XXXL the header, the state line and all five bar controls are on the screen and do not overlap, and
  one swipe on a request's card brings Approve above the bar;
- a very long command leaves Deny and Approve on screen;
- one Hang up on a live call, and the labels VoiceOver reads for the controls, the state, the chips and the bubbles;
- a 36-point header button and the menu take a touch two points outside what is drawn.
- the whisper card folds above the type bar with the keyboard up, and Show notes opens it (`WhisperUITests`); at
  accessibility XXL the request card's badge sits under the name.

`BubbleAlignmentTests` draws a bubble and reads back where each line starts; `SharedWordsTests` holds the shared words
to the page's dictionaries.
