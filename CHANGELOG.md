# Changelog

One entry per version, newest first. Each line is the subject of that version's commit; the commits before it, back to
the previous version, hold the detail. Versions are tagged from 1.14.3 on (`git log v1.14.3..v1.14.4`). The version is
the one in `.claude-plugin/plugin.json`, which the page and the iPhone app show. How a version is cut:
[RELEASING.md](RELEASING.md).

The public history starts on 2026-11-11 at 0.4.0. Earlier work was in a private repository and is not listed.

## 1.18

- **1.18.0** (2026-11-22): Setup asks one question, which setup, then only for its keys and checks each with a tiny live call; `pointe setup` lists the six setups with their measured results, cost and where your words go, and switches between them; a key the setup does not need shows as optional, not missing; a Claude subscription is explained as not an API key.

## 1.17

- **1.17.0** (2026-11-21): The Mac app has everything the page and the iPhone app have, on the iPhone app's own screens: meetings, briefings, challenge, whisper, the dictionary, the voice lock, machines, pairing a phone and the rest, with the page's sessions column in a wide window; Pointe's own help knows the Mac app; it needs macOS 15.

## 1.16

- **1.16.3** (2026-11-21): The iPhone app builds on the Xcode that CI uses again; the app is the same as in 1.16.2.
- **1.16.2** (2026-11-21): The iPhone app's New pill goes when tapped or scrolled to the end, Settings no longer jumps back while you scroll it, push to talk has a switch above the mic, and a press keeps its first word.
- **1.16.1** (2026-11-21): The iPhone and Mac apps build and install from source with one command each: `bin/pointe apps mac` and `bin/pointe apps ios` (a free Apple Account is enough), `ios --sim` for the Simulator, and `bin/pointe apps doctor` for what is missing and how to fix it.
- **1.16.0** (2026-11-21): Pointe starts a new Claude Code, OpenCode or Codex session for you: by voice after a read-back and your yes, or from New session on the page, the iPhone app and the Mac app, only in folders you already work in and never with permission prompts skipped.

## 1.15

- **1.15.0** (2026-11-21): A Mac app, built from source for now: Pointe in the menu bar with a native window for the call, approvals with Touch ID, a talk shortcut from any app, and the brain dump.

## 1.14

- **1.14.12** (2026-11-21): The voice answers how to use Pointe itself, with the exact path on the iPhone app or the page, instead of asking a session.
- **1.14.11** (2026-11-21): Every surface shows the Pointe logo with many points, like the app icon: the site, the page header and tab, the iPhone app header and the link preview.
- **1.14.10** (2026-11-21): A phone call survives a link slower than the bot's voice, and the greeting when a call opens no longer sends an earlier ask again.
- **1.14.9** (2026-11-21): Pointe has its own logo, Chorus: on the iPhone app icon, the page's header and tab, the site, the link previews and the README.
- **1.14.8** (2026-11-21): The voice closes sessions when asked: one at once, or several and "all except these" after reading the list back for a yes.
- **1.14.7** (2026-11-21): The header shows Pointe alone, and Settings has an About entry: open source, built and open-sourced by Ballerine Engineering.
- **1.14.6** (2026-11-20): Turns end as quickly on Soniox stt-rt-v6 as on v5: Pointe asks it for words it holds after a silence.
- **1.14.5** (2026-11-20): The ears run Soniox stt-rt-v6, because Soniox removes stt-rt-v5 on 2026-12-15.
- **1.14.4** (2026-11-20): The voice channel uses zod 4.6.7, which fixes a memory exhaustion on oversized input.
- **1.14.3** (2026-11-20): The doctor and setup price the Gemini and OpenAI ears, and setup says what a free-tier key means.
- **1.14.2** (2026-11-18): General knowledge passes the check for made-up facts.
- **1.14.1** (2026-11-17): A request that names its session is no longer refused for naming it.
- **1.14.0** (2026-11-16): A reply starts sooner, its first sentence said while the model writes the rest, the model reading a finished sentence while the turn settles, and the settle counted from the end of the user's sound.

## 1.13

- **1.13.8** (2026-11-16): The UX reviews' leftovers closed on both surfaces, a ⋯ for touch, the dock's labels where they fit, plainer words, and the iPhone's bubbles, whisper card and request card.
- **1.13.7** (2026-11-16): VoiceOver finds the header and the session chips where they are drawn, in strip order; the app catches up with the version.
- **1.13.6** (2026-11-16): A faster first word, the question answered before the news, and no turn taken while words are still on their way.
- **1.13.5** (2026-11-16): Harnesses and machines after a live QA pass, with prompts seen with no call, one read-out after a restart, and every answer said.
- **1.13.4** (2026-11-16): The conversation after a live QA pass, with news told once, a request never read as a session's text, and a yes timed by its own words.
- **1.13.3** (2026-11-16): The iPhone app after a full QA pass, with the scroll kept where you read, a demo that answers every tap, and the live UI tests run for real.
- **1.13.2** (2026-11-16): The iPhone app after a UX review, with the newest line clear of the keyboard, one Hang up, and names whole.
- **1.13.1** (2026-11-15): The page after a UX review, with names whole, the Showing pane on screen at every width, and 44 px controls on a phone.
- **1.13.0** (2026-11-15): Brand Guidelines V6 on the page and the iPhone app, with a dark theme and a Light/Dark/System choice.

## 1.12

- **1.12.0** (2026-11-15): Held sends said, remote prompts shown, the phone quiet at the Mac, the Mac awake for a phone call.

## 1.11

- **1.11.0** (2026-11-15): A session stopped at a prompt in its terminal alerts the phone and the desktop, and is nudged on a call.

## 1.10

- **1.10.0** (2026-11-15): A Claude Code session stopped at a prompt in its terminal is no longer called working.

## 1.9

- **1.9.1** (2026-11-15): A media key the system sends by itself no longer toggles talking on the page.
- **1.9.0** (2026-11-15): Push to talk sends a press as one message, like a voice message.

## 1.8

- **1.8.0** (2026-11-15): Short answers unless asked for more, and nothing is said into the user's turn.

## 1.7

- **1.7.1** (2026-11-14): A brain dump sent to the orchestrator in session mode may reach any session.
- **1.7.0** (2026-11-14): A brain dump goes back where you were, a session or the orchestrator.

## 1.6

- **1.6.1** (2026-11-14): A calmer brain dump review, the same on the page and the phone.
- **1.6.0** (2026-11-14): Brain dump replaces brainstorm, structured for review before anything is sent.

## 1.5

- **1.5.0** (2026-11-14): The voice waits for the end of a sentence, holds when asked, and the wait is a setting.

## 1.4

- **1.4.4** (2026-11-14): Push to talk by hold or by tap, and an iPhone talk ring that answers the thumb.
- **1.4.3** (2026-11-14): The brain's history stays under a token budget on a long call.
- **1.4.2** (2026-11-14): A click on a session row puts the voice in session mode, as the phone app does.
- **1.4.1** (2026-11-14): A click on a session cuts the old topic and says where the new one stands.
- **1.4.0** (2026-11-14): The iPhone app ready for the App Store, with a demo for App Review.

## 1.3

- **1.3.1** (2026-11-14): The pairing code shows whole.
- **1.3.0** (2026-11-14): A Connect button that says why, and a supply chain that is checked.

## 1.2

- **1.2.1** (2026-11-14): The version on screen.
- **1.2.0** (2026-11-14): Talk from any app, a page that answers the click.

## 1.1

- **1.1.0** (2026-11-14): Machines, connect your phone, the new page.

## 1.0

- **1.0.1** (2026-11-14): Parity fixes, right-to-left text, centered mic.
- **1.0.0** (2026-11-13): The version commit names no single change.

## 0.4

- **0.4.0** (2026-11-11): Meeting mode on the page and in the app.
