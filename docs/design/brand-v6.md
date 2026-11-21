# Brand Guidelines V6 on the page and the iPhone app

Pointe's two surfaces, the page the daemon serves (`ui.html`) and the iPhone app (`ios/Pointe`), carried the earlier
Ballerine look: a navy dark-only screen, the orange `#FF4F1F`, Inter bold and a serif italic tagline. Ballerine's
Brand Guidelines V6 (November 2026) replace all of that: warm black and warm greys, orange `#FF5A01` as a signal only,
light display type (Bricolage Grotesque 300/400) over a plain sans (Instrument Sans 400/500/600), flat cells divided by
hairlines, no gradient and no serif. This document maps V6 to both surfaces, defines the dark theme as its own theme,
and records the decisions that the guidelines leave to a product.

The guidelines describe web pages and decks. Pointe is a live tool, so the rule here is: **the brand shows through
type, colour and the logo; the layout stays an app.** The page keeps its dock and sheets, the phone keeps its native
lists and sheets.

## 1. One source

`assets/theme.json` holds the theme choices, every colour token for light and dark, the font files with their
SHA-256, and the harness marks. The page carries the tokens as CSS custom properties and the app as
`Brand.swift` constants, because the page must render with no build step and the app must compile without a resource
lookup. `tests/test_theme.py` reads all three and fails when either surface differs from the source.

## 2. Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `bg` | `#FFFFFF` | `#0A0400` | the screen behind a call |
| `surface` | `#FCFAFA` | `#0C0906` | the sessions column, a sheet, a drawer |
| `card` | `#FFFFFF` | `#0F0B08` | a bubble, a card, the dock |
| `raised` | `#F5F1EF` | `#1A1410` | a control, the user's bubble, a pressed or hovered row |
| `raised2` | `#E9E2DE` | `#26201B` | a switch track, a hover on `raised` |
| `group` / `cell` | `#F5F1EF` / `#FFFFFF` | `#0C0906` / `#1A1410` | a settings list: the ground and the rows on it |
| `text` | `#0A0400` | `#F7F2F0` | headlines and body |
| `muted` | `#5C5450` | `#B5ADA8` | secondary text |
| `dim` | `#6E6762` | `#958D88` | captions, kickers, timestamps |
| `line` / `line-strong` | `rgba(10,5,0,.10)` / `.18` | `rgba(255,255,255,.08)` / `.16` | hairlines; outline buttons |
| `orange` / `on-orange` | `#FF5A01` / `#0A0400` | same | the signal, and what sits on it |
| `accent` | `#C24F0D` | `#FF8C4A` | orange text |
| `tint` | `#FFF1E9` | `rgba(255,90,1,.14)` | the one selected row or chip |
| `orange-line` | `rgba(255,90,1,.45)` | same | the outline of a card that needs you |
| `success` / `success-text` | `#138A4B` / `#0E7A41` | `#138A4B` / `#3DBE7B` | working, online |
| `danger` / `danger-text` | `#C83A37` / `#C83A37` | `#C83A37` / `#F0706B` | hang up, a meeting being heard, a removed line |
| `primary` / `on-primary` | `#0A0400` / `#FCFAFA` | `#F7F2F0` / `#0A0400` | the primary button |
| `glow` | none | `rgba(255,90,1,.16)` | the dark screen's one radial glow |
| `scrim` | `rgba(10,4,0,.35)` | `rgba(0,0,0,.60)` | behind a sheet |

Where a value differs from the guideline, the reason is contrast:

- `dim` is `#6E6762`, not stone `#857E79`: stone is 3.99:1 on white and fails AA for caption text.
- `success-text` is `#0E7A41` on light (the brand green is 4.41:1 on white) and `#3DBE7B` on dark; `danger-text` is
  `#F0706B` on dark (the brand red is 4.0:1 on warm black). The brand green and red stay for dots and fills.
- What sits on orange is warm black (6.5:1). White on `#FF5A01` is 3.1:1, which is enough for an icon but not for the
  word "Connect".
- `accent` is set on `bg`, `surface`, `card` and `cell` only. On the tint or a raised fill it falls to 4.2:1, so a
  selected row's text is `text`, never orange.

`tests/test_theme.py` computes every text token against every surface it is set on, in both themes: 4.5:1 for text
(WCAG 2.2 AA, 1.4.3), 3:1 for a dot or a fill (1.4.11).

## 3. The dark theme

Dark is a theme of its own, not the light theme inverted.

- **Surfaces** are the guideline's dark band: warm black `#0A0400`, `#0C0906` and `#0F0B08`. They are close together on
  purpose. A fourth and fifth step (`raised`, `raised2`) exist only for controls.
- **Elevation is a hairline, not a shadow.** A card is one step lighter than its ground with a 1px `line` border. A
  sheet has a scrim behind it and a hairline around it. No glow sits under a button.
- **One orange glow** bleeds off the top right of the call screen, as on the guideline's dark band. Light has none.
- **Text** is bone `#F7F2F0`, never white; secondary text is warm grey, never blue-grey.
- **Orange is brighter against black**, so it is used less: text takes the softer `#FF8C4A`, and the tint is 14%.

## 4. Where orange goes

Orange marks; it does not fill a block or colour a paragraph. On a Pointe screen it is:

1. the microphone while it is live (the one large orange shape on the screen),
2. Connect, when there is no call (so the two never show together),
3. a 6px status dot: a session that needs you, the voice speaking,
4. a switch that is on, a progress bar, the caption's wave,
5. one phrase of orange text: "needs you", "approve", a problem line.

Every other primary action (Approve, Send, Done, Pair) is the guideline's primary button: warm black on light, bone on
dark, 12px corners. Deny and Cancel are outline buttons. A card that waits for you has an `orange-line` border and no
fill. The earlier orange gradients, orange drop shadows and orange-tinted panels (brain dump, challenge, the user's
bubbles) are gone.

## 5. Type

| Role | Family | Where |
|---|---|---|
| Display | Bricolage Grotesque 400 (300 for the largest lines) | "Pointe", the call state, a sheet's title, the caption while you speak, the drive line, big numbers |
| Text | Instrument Sans 400/500/600 | everything else: rows, bubbles, buttons, labels |
| Mono | the system monospace | commands, code, timestamps, a pairing code |

No weight above 600, no serif, no italic: the version under the name is plain muted text, and a draft or a
half-heard line is muted rather than italic. Section labels are 11px kickers in `dim`, upper case, tracked 0.12em.
Numerals are tabular.

On the phone, `Font.brand(_:_:)` maps the iOS text styles to the two families and keeps Dynamic Type; the title styles
are the display family. SF Symbols and the monospace stay the system's. Navigation titles and segmented controls take
the families through UIKit's appearance at launch.

**Fonts are bundled, not fetched.** Both are SIL OFL 1.1 with no reserved font name (the licence texts are beside the
files and are byte-identical to the ones in Google Fonts' repository). The five static TrueType files come from the
upstream repositories at fixed commits (`THIRD_PARTY.md`), are committed under `assets/fonts/` and `ios/Pointe/Fonts/`,
and are pinned by SHA-256 in `assets/theme.json`. The page loads them from the daemon (`GET /voice/font/<name>`, which
serves only a pinned name and only bytes with its hash); the app registers them in `Info.plist` (`UIAppFonts`). No
font CDN is contacted, so `docs/security/egress-allowlist.txt` is unchanged. JetBrains Mono, which the guideline names
for IDs, is not bundled: the system monospace does that job and costs nothing.

**Hebrew.** Neither family has Hebrew glyphs. On the page each `@font-face` has a Latin `unicode-range`, so a Hebrew
run never asks for the file and falls to the system font next in `--font`. On the phone, iOS substitutes the system
font glyph by glyph. A mixed line ("תריץ את הבדיקות של checkout") sets its Latin words in Instrument Sans and its
Hebrew in the system font.

## 6. Shape

The guideline's radius scale is 0, 3, 8, 12, 16 and 999. On the page: session rows and settings cards are flat cells
with hairlines (0); buttons and inputs are 12; a bubble, the dock and a sheet are 16; chips and the footer buttons
are pills. Nothing sits between 16 and 999. On the phone the same scale applies to custom shapes, while a native
grouped list keeps iOS's own inset corners: redrawing it would stop being an iOS app.

The page's stage has the guideline's six faint gridlines behind the conversation, fading at the top and bottom. The
phone has none: at that width they read as noise.

## 7. Appearance: System, Light, Dark

Both surfaces follow the system appearance by default and offer the same three choices with the same words.

| | Page | iPhone app |
|---|---|---|
| Where | Settings → Appearance (a three-part control) | the Settings menu → Appearance |
| Kept in | this browser (`localStorage` `pointe.theme`) | this phone (`UserDefaults` `pointe.theme`) |
| Applied by | `data-theme` on `<html>`, set before the first paint | `preferredColorScheme` |

The choice is per device and is not sent to the Mac: a phone in the sun and a desk monitor at night want different
answers.

## 8. Logo and icon

Pointe is an open-source project built and open-sourced by Ballerine Engineering, not a Ballerine product, so the
header on both surfaces is the name "Pointe" alone with the version under it: no Ballerine lockup. Settings → About
carries the credit and the links (`AboutCopy` in the app, `ABOUT_COPY` in the page). The guidelines define no app icon for
products, so the app icon is kept as it is.

## 9. Sessions: by machine, with the agent beside the name

Asked for with the restyle, and built on what multi-machine already had.

- **Grouping.** With more than one machine, sessions are grouped by machine, under the machine's own name: the hub
  first ("studio · this Mac"), then each node by its node name. On the page's sessions column and in the phone's
  Sessions sheet a group has a header: a 6px dot (green while online, a ring while offline), the OS and round trip or
  "offline since …", and how many of its sessions need you. Inside a group the order is as before: what needs you
  first.
- **One row on the phone's call screen.** The strip of session chips is one row. It is grouped the same way, each
  group behind a small divider (the dot and the machine's name). The machine filter (All · studio · devbox) is in the
  Sessions sheet, not a second row above the strip; what it picks still narrows the strip and the status line. On the
  page the filter sits in the sessions column, which is the sheet on a narrow screen, so the same rule holds there.
- **One machine: no header and no divider.** The page shows the plain list; the phone's sheet keeps its one "On the
  voice" section title. A header that names the only machine is clutter.
- **No machine badge on a row.** The header or the divider says it.
- **Harness mark.** Every session shows a small monochrome tile beside its name for the coding agent that runs it, on
  both surfaces, with the label "runs on Claude" (and so on) for a screen reader. **The session's name gets the
  width:** on the page's rows and the phone's chips the agent is the tile only, with its name as the label and the
  tooltip. The phone's Sessions sheet has the room, so there the agent's name is written beside the tile once the
  voice mixes agents.
- **Voice is unchanged.** "The sessions on devbox" and routing by machine name work as before; no session is renamed.

**Why letters, not logos.** Each vendor's own terms were read on 2026-11-15:

| Agent | Terms | Result |
|---|---|---|
| Claude Code (Anthropic) | Trademark guidelines: marks only "as specifically permitted by us and only in materials we approve beforehand"; "No alterations … (changes to color, font, proportion, or otherwise)". | Not without permission. |
| Codex (OpenAI) | Brand guidelines: do not "use the logo without permission"; an app should be "free of OpenAI's brands"; use the logo "exactly as provided". | Not without permission. |
| OpenCode (Anomaly) | Brand page: tools that work with OpenCode "can say so" with a badge or lockup, but "do not recolor the logo". | Allowed only in its own two tones, so not as a monochrome mark. |
| Pi | A press kit with no usage terms. | Unclear. |

So no vendor logo is bundled. The mark is a neutral letter in a hairline tile (C, X, O, P) with the agent's name, the
same on both surfaces (`assets/theme.json` → `harnesses`). If a vendor grants permission later, its mark replaces the
letter in one place per surface.

## 10. Tests

- `tests/test_theme.py`: the page's and the app's tokens equal the source in light and dark; the same theme choices,
  default and words on both; AA contrast for every text and mark token; the font files at their pinned hashes on both
  surfaces with the licence; the daemon serves a pinned font and nothing else; the page loads fonts from this Mac only;
  the same harness marks on both; in a headless Chrome, the page follows the system until a choice is made, groups by
  machine, drops the header for one machine, and marks an offline machine.
- `ios/PointeTests/ThemeTests.swift`: the theme choices and their colour scheme, the bundled fonts load by name, the
  harness marks, and the machine grouping with mixed agents.
