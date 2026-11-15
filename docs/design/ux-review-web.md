# UX review of the page (version 1.13.0)

A review of `ui.html` after the Brand Guidelines V6 restyle (`docs/design/brand-v6.md`): every screen and state, at
three widths (1440×900, 1024×768, 390×844), in light and dark. This document lists what was found, what was changed,
and what was left.

## Method

The page was run in a headless Chrome against the stub Mac of `tests/page_rig.py`, with the stub extended to answer the
routes a screen needs (fonts, notes, briefings, the dictionary, phone routes, an artifact). Sixty-one scenes were
rendered six times each (three widths, two themes): 366 screenshots before the fixes and 366 after. Each shot also ran
an audit in the page: horizontal overflow, elements off the screen, controls under 44 px, text cut by an ellipsis, and
the contrast of every text node against the surface under it. The images were then read one by one.

The scenes: not connected (one session, none, a conversation on screen), connecting, reconnecting, the three connect
errors, a call elsewhere, a live call (empty, the voice speaking, hearing you, muted, a problem line), push to talk
(Hold and Tap; idle, talking with a draft, sending), sessions (twenty on three machines with four agents, an offline
machine, long and Hebrew names, session mode, a rename, a disconnect being confirmed), approval cards (short, very long,
with no call), brain dump (dumping, structuring, the review, an armed send, an armed discard), meeting (the two sheets,
on, a raised hand, the transcript, the end sheet, the notes after it), briefing (the sheet, playing, the ready card),
challenge (on, ended), whisper, hold, drive, a conflict, every Settings section, phone pairing (routes, the code, an
unpair being confirmed), a machine invite, voice lock (enrolling, enrolled, a problem, the ignored list), the
dictionary and its toast, the context drawer, the Showing pane (file and diff), More, the sessions sheet, typing,
fixing a turn, the New pill, and keyboard focus.

Screenshot paths below are under `/tmp/ux-review/`: `web/` before, `after/` after, named
`<scene>@<width>-<theme>.png`. They are not committed.

Severity: **high** breaks a task or hides information; **medium** is wrong and visible; **low** is a rough edge;
**cosmetic** is taste.

## Findings

### High

| # | Finding | Before | Fix |
|---|---|---|---|
| H1 | **The Showing pane was off the screen under 900 px.** The narrow-screen rule for the sessions column was written for `aside`, and the Showing pane is an `aside` too: it took the column's `translateX(-102%)`. "Show while it says" showed nothing on a phone or a narrow window. | `web/82-showing@390-light.png` | The column's rules name `#side`. On a narrow screen the pane lies over the conversation only: the page measures where the conversation ends (`--under-stage`), so the top bar, an approval card and the dock stay in reach. |
| H2 | **With the Showing pane open on a small laptop the call was crushed** to about 315 px: the status line wrapped one word a line under the switch's label, and the dock stacked its buttons in columns. | `web/82-showing@1024-dark.png` | From 901 to 1339 px the sessions column steps aside while the pane is open (it is the sessions sheet, behind the Sessions button) and returns when the pane is folded. The pane is 34% wide (was 38%). Beside the pane the dock keeps one row of icons. |
| H3 | **Session names were cut twice.** `short()` cuts a name to 28 characters, then the row cut it again with a second ellipsis ("cfx-9994 · …with-the-ne…"), while the state word and the agent tile kept their width. "needs you" broke onto two lines. | `web/22-sessions-long-and-hebrew-names@1024-light.png` | A name takes two lines before any ellipsis; the state word never wraps. A row no longer gives up height when the list is long (a flex child of the scrolling list shrank, which also squeezed every row of a twenty-session list). |
| H4 | **The sessions sheet on a phone** had no scrim and no close control; it covered the Sessions button that opened it; closed, its shadow still showed as a grey band down the left edge of every screen, and its controls could still be reached with Tab. | `web/85-sessions-sheet@390-light.png`, left edge of `web/27-approval-very-long@390-light.png` | A scrim, a close button, Escape closes it, focus moves in and back out. Closed, it is `visibility: hidden` with no shadow. |
| H5 | **The talking ring covered the mic's label** ("Talking" read as "Taiking"): a 10 px ring and a 4% scale over a label 7 px below. | `web/17-ptt-hold-talking@1440-light.png` | The rings are 6 px and the mic does not scale while talking. |
| H6 | **Controls under 44 px on a phone**: the microphone switch (22 px), the top bar's pill (34), dock buttons (40), every close button (32), chips, Settings' strip, selects (36), day chips (38), note actions (29), the meeting bar's buttons (23 to 29). | audit of `web/*@390-*` | Under 760 px a real button grows to 44 px; a chip, a close button and a segment keep their look and take the room around them. |
| H7 | **The newest turn was left under a card.** When an approval card or the caption took room from the conversation, the list kept its scroll offset, so the last turn was cut mid-line under the card. The brain dump's list did the same. | `web/27-approval-very-long@1440-light.png`, `web/29-dump-dumping@1440-light.png` | A list that is at its end stays at its end when its height changes. |
| H8 | **Whisper mode left a gap and broke its buttons.** Its larger caption style out-ranked the hidden caption's, so the hidden caption kept 36 px of padding; on a phone "Back to normal" wrapped inside a third of a row. | `web/47-whisper@390-light.png` | The style applies only to a visible caption. The question's two answers share a row; Back to normal has its own. |

### Medium

| # | Finding | Before | Fix |
|---|---|---|---|
| M1 | **Dimmed rows failed contrast.** In session mode every other session was at 55% opacity (2.2:1 to 2.5:1), including one that needs you; offline rows were at 45% (2.1:1); done and dismissed meeting notes at 45% (3.25:1). | `web/23-session-mode-focused@1440-light.png`, `web/21-sessions-offline-node@1440-light.png`, `web/37-meeting-on@1440-light.png` | Quieter by colour (`muted`, `dim`), never by opacity. A session that needs you keeps its orange in any mode. |
| M2 | **Recent requests vanished** under a long sessions list: the heading stayed with nothing under it. | `web/20-sessions-20-three-machines@1440-dark.png` | The section keeps room for a request and a half; the sessions list scrolls. |
| M3 | **A dead button.** "Sessions" in the dock toggles the sessions sheet, which exists only on a narrow screen. On a desktop it did nothing. | `web/11-live-bot-speaking@1440-light.png` | It shows only where the column is a sheet. |
| M4 | **Three different left edges** in the middle column: cards at 24 px, the drive bar and the whisper card at 28, and on a phone the conflict card at 24 beside cards at 16 and the dock at 12. | `web/49-drive@1440-light.png`, `web/50-conflict@390-light.png` | One `--gutter` for the column: 24, 16 under 900 px, 12 under 560 px. |
| M5 | **Settings marked the wrong section.** The last sections cannot scroll to the top of the panel, so a click on Alerts marked Conflict alarm. On a phone the marked pill could be off the strip. The mark's orange bar followed a 12 px corner and drew a crescent. | `web/6b-settings-g-alerts@1024-light.png`, `web/64-settings-g-briefings@390-light.png` | The section asked for keeps the mark until the user scrolls; the strip scrolls the mark into view; the list's rows are flat (a straight bar) and the strip's pills take an outline. |
| M6 | **Buttons that vanished in dark.** `raised` and `cell` are the same colour in dark, so Unpair, Revoke and Delete on a Settings row had no shape. In light the Settings close button had none either. | `web/71-phone-qr@390-dark.png` | Outline buttons, as Cancel is. The close button sits on `cell` with a hairline. No token changed. |
| M7 | **Missing hairlines in Settings cards.** A rule that removed the line after an empty note also removed it between two visible rows (the two Alerts switches; the paired phones and "How should your phone reach this Mac?"). | `web/6b-settings-g-alerts@1024-light.png` | The rule applies only to an empty first child. |
| M8 | **A bare switch in the phone's top bar.** Under 760 px "Clean up my words" lost its words and was a switch with no label. | `web/01-idle@390-dark.png` | On a narrow screen it is a row in More, with its label. The top bar keeps the state and the status line. |
| M9 | **The same words twice** in a brain dump: the live line in the panel and again in the caption under it. | `web/29-dump-dumping@1440-light.png` | The caption is hidden while the panel is on screen. |
| M10 | **The meeting bar on a phone** was four ragged rows (190 px) and the filters two more. | `web/38-meeting-hand@390-light.png` | Rows with an order: what it is and End; the facts; the speakers and the filters as single rows that scroll; the mode and Reconnect. |
| M11 | **Card buttons broke words** on a phone ("Asked s0-/shop", "Back to/normal"); "needs approval" broke in two; the agent chip in a card took the orange meant for "needs approval". | `web/50-conflict@390-light.png`, `web/22-sessions-long-and-hebrew-names@390-light.png` | A card's buttons wrap as whole buttons and never break a label; "needs approval" stays whole; the chip is neutral. |
| M12 | **Scrollbars** were either invisible (a `card`-coloured thumb on a card) or the browser's wide default inside rounded boxes. | `web/60-settings-voicelock@1440-light.png`, `web/45-challenge@1024-dark.png` | One thin scrollbar everywhere with a hairline thumb and no track. |
| M13 | **The brain dump's review opened at its last line** (the focus put the caret at the end), and its three secondary buttons wrapped on a phone. | `web/32-dump-review-armed-send@1440-light.png`, `web/33-dump-review-discard-armed@390-light.png` | It opens at the first line and grows with its text up to 44% of the height; the buttons keep one line. |
| M14 | **Keyboard focus on a session row** drew only a bottom edge: the list clipped the ring. Rename and Disconnect were 12 px marks. | `web/89-keyboard-focus@1440-light.png` | The ring is drawn inside the row. The marks are 24 px targets with a hover fill. While "disconnect?" asks, the state word steps aside. |
| M15 | **The dictionary on a phone** gave a long name 90 px and five lines beside its controls; "Learn from my fixes" had its switch against the words, not at the row's end. | `web/78-dictionary@390-light.png` | Under 560 px the name has its own line. A `.tick` row spreads its label and switch (a `margin-left: auto` that never applied). |
| M16 | **The status line broke mid-phrase** on a phone ("3 / need you"), and Hang up showed twice (the top pill and the red button by the mic). | `web/22-sessions-long-and-hebrew-names@390-light.png` | The phrase does not break. Under 560 px the top pill is hidden during a call; the red button is the one under the thumb. |
| M17 | **The dictionary's toast covered the dock** and sat in the middle of the window, not of the call. | `web/79-dictionary-toast@1440-light.png` | Under the top bar, centred on the call. |

### Low

| # | Finding | Fix |
|---|---|---|
| L1 | A machine's name was upper-cased in its header ("STUDIO"), which changes a name the user typed. | The name as typed; the facts beside it stay kickers. |
| L2 | The segmented control drew two rings 1 px apart. | 3 px of padding. |
| L3 | Voice lock enrolment: "Read this line aloud", the percentage and the reason sat 14 px right of the line and the bar. | One left edge. |
| L4 | Context drawer: "as of 15:04" took the big number's tracking and read "asof1504"; labels sat 4 px right of the rows. | Fixed. |
| L5 | Meeting ended: headings touched the text above them; the session select was 36 px beside a 44 px button. | Even spacing; the same height. |
| L6 | The raised-hand card had an orange fill and a full orange border. The brand: a card that waits for you has an `orange-line` border and no fill. | Outline, no fill. |
| L7 | The Showing pane took the sessions column's 20 px gap and padding (the same `aside` rule as H1), so its rows were unevenly spaced and its code box 6 px left of its header. | Its own spacing; one left edge. |
| L8 | No reduced-motion rule: the breathing dots, the wave and the slides ran for everyone. | `prefers-reduced-motion: reduce` stops them. |
| L10 | Showing pane: orange text on a raised chip ("Failing test", 4.24:1) and on the tint (highlighted line numbers, 4.30:1). | The chip sits on `card`; the numbers are `text`. |
| L9 | On a small phone (under 390 px) two 44 px controls each side of the mic did not fit. | The mic is 60 px there. |

### Cosmetic, fixed in passing

The artifact chips' scrollbar under the chips; the hover fill on session tools; the checks list's spacing in the meeting
sheet on a phone; the seven day chips on one row at 44 px.

## Left as it is

- **The dock under 1100 px shows icons without labels** (the labels are tooltips and screen-reader names). At 1024 px
  the seven labels fit only with 4 px to spare, and a fallback font would wrap them. A layout change (fewer controls in
  the dock, the rest in More, as on a phone) would fix it properly; that is a design decision, not a safe edit.
- **Rename and Disconnect on a session row need a pointer** (they show on hover or keyboard focus). On a phone a row
  only focuses the session. The app has both; the page on a phone does not.
- **Long notes under Settings sections** (Microphone is five lines). The words are right; the amount is a copy decision
  shared with the app.
- **Copy** was not changed. Several strings are shared with the iPhone app and checked by its parity tests
  (`ios/PointeTests/ParityTests.swift`), which this review did not touch. Candidates: "never answers every remark" (the
  meeting sheet), "Or type below once connected" on a phone where the box is folded, no reason given beside a disabled
  lock level.
- **An approval card's buttons span the column** (1000 px on a desktop). A cap would be taste.
- **An unusable phone route** (Settings → Phone) is at 55% opacity. It is an inactive control, which WCAG exempts, and
  its reason line is the one thing a person needs to read there; a quieter colour instead of opacity would be better.
- **Hover and active states** were read from the stylesheet, not rendered: a headless page has no pointer.

## What changed outside the page

- No theme token changed: `assets/theme.json` and the parity tests are as they were.
- No shared copy string changed.
- `tests/test_ui_page.py`: on a narrow screen More now also holds "Clean up my words" (`polishrow`).

## Tests

`tests/test_ui_layout.py`, in a headless Chrome on the stub Mac. Six of the seven fail on 1.13.0.

- a session name up to 28 characters is whole at 1440, 1024 and 390 px, its state word is one line, and a two-line
  name does not run into the reason under it;
- nothing runs off a 390 or 360 px screen (the call with a very long approval and a conflict, Settings, More);
- every control on a phone is 44 px to the finger, probed 21 px each way from its middle (the call, the sessions
  sheet, Settings, More, the briefing sheet);
- the sessions sheet: a column on a desktop with no Sessions button; closed on a phone it is hidden, off screen and
  has no shadow; open it has a scrim and the focus; Escape closes it;
- the Showing pane is on screen at 1440, 1280, 1024 and 390 px, never over the dock or the top bar, and beside the
  call it leaves 540 px, a one-row dock and a one-line status;
- the conversation stays on its newest turn when an approval card arrives;
- the talking ring clears the mic's label, and a hidden caption takes no room in whisper mode.
