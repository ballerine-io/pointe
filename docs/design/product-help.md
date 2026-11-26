# Product help: the voice answers "how do I…" about Pointe

Asked "how do I turn off push to talk?", the voice sent the question to a coding session, or guessed. It now answers
itself, in one or two sentences, with the exact path on the screen the user is on, and never relays such a question.

## 1. One source, generated from the UI

`product_help.json` is written by `tools/product_help.py` (standard library, no network) and checked in. It has two
parts:

- **`ui`: the labels the code shows**, read from the code. The iPhone app: Settings, the sheet behind the ••• button
  (`CallSettings.swift`: each item, each picker's options, with `Copy.member` constants, `ForEach(Copy.levels)` and
  `Type.allCases` labels resolved), the switch above the mic (`MicModeSwitch`), the bottom bar and its mic, the header, a session's long-press menu and the Sessions sheet (`Sessions.swift`), a request's
  card and the pairing screen. The page (`ui.html`): each Settings section by its nav name with its fields, ticks,
  options and buttons; the dock, the mic and the switch above it; the Sessions panel; the top bar; a session row's
  actions; the brain dump's review; a request's card.
- **`entries`: what a person asks.** 52 hand-written topics in the generator (`TOPICS`): the words people ask with in
  English and Hebrew, one or two sentences of explanation, a path per surface, a note where a path is not enough, the
  phrases that do the same by voice today, and the brain's own tool that does it. A topic that names a feature page in
  `docs/features/` gets that page's one line from the features table as `about`. Then one generated entry for every iPhone
  Settings item, page Settings section and dock button no topic covers, so a new item is findable the day it ships. 59 entries now.

A path is written as its place and the labels inside it, `("menu", "Microphone", "Always on|Push to talk")`, and
rendered for speech: `Settings (••• at the top) → Microphone → Always on / Push to talk` (iPhone), `Settings → Microphone → Always on /
Push to talk` (page; a field named like its section is said once). Every label in a path must be one the code shows in
that place, or the generator stops with what it found there. So:

- a label a topic names, renamed in `apps/ios/` or `ui.html`, fails the generator until the topic is fixed;
- any label in the inventory, changed without regenerating, fails `tests/test_product_help.py` (the committed file must
  equal what the generator writes), like the copy parity tests. Both are tested by editing a copy of the UI.

Run `python3 tools/product_help.py` after changing a menu, a setting, a dock button or their copy; `--check` exits 1 when
the file is stale.

## 2. How the brain reaches it

The help is not in the prompt. The brain gets one tool and one rule:

- **`how_to_use_pointe(question)`** (`daemon.how_to_use_pointe`, `howto.answer`): a local lookup, under a millisecond,
  that returns at most three entries, each with its `where` on the user's surface, a `note`, `say_instead` (voice
  phrases) and `your_tool`. The surface is the iPhone app while the call is the app's (`state.phone_socket`), else the
  page. A feature missing on this surface says so and gives the other's path. A page path through Settings adds where
  Settings is. A result is under 1,800 characters whatever the question. The tool is read-only, so meetings and
  challenges allow it (`modes.READ_ONLY_TOOLS`).
- **The rule** (`INSTRUCTIONS`, "When to answer vs delegate"): answer questions about using Pointe from the tool,
  yourself, in one or two sentences, with the path for the user's screen and the labels in English as written; never send
  such a question to a session; offer the voice phrases; use `your_tool` only when asked.
- **In code** (`daemon._howto_refusal`, CLAUDE.md: a rule lives in code): a `send_to_claude_code` whose user words are a
  question about using Pointe (`howto.about_pointe`: a question form, a match on a phrase of two words or more or on
  Pointe's name, and no code words such as code, test, file, bug, repo) is refused once, silently, with "call
  how_to_use_pointe". Not when the words name a session. Sent again for the same words, it goes: they meant a session
  working on Pointe's code.

The lookup (`howto.lookup`): English words are lower-cased and reduced by a few suffix rules ("renaming", "rename"); a
phrase found whole scores two per word. Hebrew phrases match by root: one leading ו and one of ה ב ל מ ש כ come off each
word, and every root must appear in the question ("מצמיד" finds "מצמידים"). A word of an entry's title or path adds a
half; a near spelling of a one-word phrase adds one. Entries scoring at least 2 and half the best are returned.

## 3. The conversation rules hold

The answer is a reply to the user's words, so `REPLY` applies (30 words, two sentences); the floor, the queue and the
length cut are unchanged. Hebrew in, Hebrew out (`_language_problem`); the labels stay in English, as the screen shows
them. Voice phrases are offered only where the code takes them today (`tests/test_product_help.py` checks each against
its intent function: hold, brain dump, meeting, challenge, drive, whisper, briefing, routing mode, switch, rename, close).
The microphone mode, mute and "Wait before answering" have no voice command, so none is offered for them: no new power.

## 4. Context budget

One tool schema (under 400 characters) and one rule (under 450) in a system prompt of about 6k tokens; no help text in
the prompt or the `[right now]` block (tested). A result is a tool result like any other, trimmed with the history
(`brain.HISTORY_TOKENS`).

## 5. Tests

`tests/test_product_help.py`: the lookup in English and Hebrew (push to talk off on the iPhone, hold or tap, mute, pair
the phone, voice lock, brain dump, close a session by voice, rename, wait before answering, appearance, the settings,
updating); questions about something else find nothing; each surface's path; voice phrases and tools checked against the
code; the sync check, and a renamed label failing it and the generator; the daemon's brain answering from the tool on
the iPhone and sending nothing; a send refused once and answered from the tool instead (Hebrew, page path); the refusal
not applying to code or a named session; the budget. `tests/e2e/page_conversation.py` section `howto`: on a real call,
"How do I switch between push to talk and always on?" is answered from the tool with the page's path, in at most 30
words, and reaches no session.
