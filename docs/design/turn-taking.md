# Turn taking: when the voice may answer

Owner feedback from live use: "the voice agent cuts me off too often, even after a very small pause, before I've
finished a sentence." This document maps how a turn ends today, why short pauses end it, and the change: a settle time
after every final transcript that depends on whether the sentence reads finished, a "hold" the user can ask for, and a
Settings choice (Quick / Normal / Patient) on the page and the phone.

## 1. How a turn ends today

Soniox mode (`CLAUDE_VOICE_EARS` other than `native`; the default). The pipeline is
`VADProcessor(Silero) → MicGate → SonioxSTTService → SonioxEars` (`daemon.py:5838`).

| Stage | Where | Value today | Role in ending a turn |
|---|---|---|---|
| Silero VAD | `daemon.py:5838` `SileroVADAnalyzer()` with pipecat 1.15 defaults, `pipecat/audio/vad/vad_analyzer.py:25-28` | `confidence=0.7`, `start_secs=0.2`, `stop_secs=0.2`, `min_volume=0.6` | None directly. Sets `state.user_started_at` / `state.user_stopped_at` (`daemon.py:1066-1071`) and fires loud barge-ins (`daemon.py:1087`). The STT does not finalize on it: `vad_force_turn_endpoint=False`. |
| Soniox endpoint detection | `vendors.py:509-516` | `endpoint_sensitivity=-0.5` (env `CLAUDE_VOICE_ENDPOINT`), `max_endpoint_delay_ms=2500`, `endpoint_latency_adjustment_level` default 0, `should_interrupt=False` | The turn end. Soniox judges from "pauses, intonation, speech patterns and conversational context" (its docs), emits `<end>`, and pipecat turns the tokens into one `TranscriptionFrame`. Measured 0.31 s p50 after speech in `bench/` (comment at `vendors.py:512`). |
| Smart-turn model | none | pipecat ships `audio/turn/smart_turn/local_smart_turn_v3.py`; not wired, no model downloaded | – |
| Unfinished-sentence hold | `daemon.py:1137-1141` → `guards.unfinished` (`guards.py:70-95`) | `HOLD_UNFINISHED_SECS = 2.5`, `HOLD_MAX_SECS = 10.0` (`daemon.py:302-303`) | A final whose last word is in a closed list (`a the and or but so because if than between whether my your our their um uh` + `to at of for with about from into like is are was were` outside a question, 20 Hebrew particles) or ends in `, - – — …` waits 2.5 s of silence (`_release_held`, `daemon.py:1173-1182`); the next final is appended. |
| Everything else | `daemon.py:1142` `await self._take(heard)` | **0 s** | Any final that does not match the list is the turn, at once: `_take` pushes `InputTextRawFrame`, `BrainFront` interrupts what it was about to say and starts the reply (`daemon.py:1045-1052`). |
| Related timers (not turn ends) | `daemon.py:510` `USER_GAP_SECS = 1.2` (news may start this long after the user's last word); `daemon.py:304` `HEARING_SECS = 3.0`; `daemon.py:2820` `HOLD_ADDRESSED_SECS = 2.0` (meeting mode only) | | |

Native mode (`CLAUDE_VOICE_EARS=native`, Gemini/OpenAI realtime) has no ears in the pipeline (`daemon.py:5832-5834`); the
vendor's own turn detection decides and nothing below applies. It is not the default and not changed here.

## 2. Root cause

Soniox's endpoint is a good **candidate** for a turn end and a poor **verdict**. Three things compound:

1. **No settle time for a sentence that reads complete.** The only wait is for the closed dangling-word list. A pause
   after a content word, "let's look at the parser … and see why it fails", "the retry loop is wrong … because it has no
   backoff", gives a final ("Let's look at the parser.") that reads complete, and `_take` answers it in 0 s. Soniox's
   own patience (`-0.5`, 2.5 s cap) does not help: its endpoint is semantic, and a complete-looking clause is where it
   fires.
2. **The list has low recall.** Thinking speech pauses after conjunctions and fillers the list does not have ("which",
   "when", "also", "basically", "I mean", "you know", "kind of", "and then", "אבל", "ואז", "כאילו", "בעצם", "שאני …").
3. **One value for everyone.** 2.5 s is right for a dictation style and too long for quick commands; no way to choose.

Not the VAD: `stop_secs` 0.2 is only the stop-stamp latency. Not the brain: it answers what it is given.

## 3. The change

### 3.1 Settle time after every final (new module `turns.py`)

Every final transcript waits for **silence**, measured from the later of the VAD stop and the last live word
(`max(state.user_stopped_at, state.user_heard_at)`, as `_release_held` already does), before it becomes the turn. How
much depends on how the text reads:

| Text reads | Quick | Normal (default) | Patient |
|---|---|---|---|
| one or two words, nothing held ("yes", "stop", "run it", "כן") | 0 | 0 | 0 |
| complete | 0.4 s | 1.0 s | 1.8 s |
| unfinished (`guards.unfinished`, widened, §3.2) | 1.5 s | 3.0 s | 4.5 s |
| hard cap while the user keeps talking (`maximum`) | 6 s | 10 s | 14 s |

The silence is total silence since the user's last word, not time after the final: Soniox already delivers the final
~0.3–0.5 s after speech, so Quick is today's behaviour (no added wait), and Normal adds ~0.5–0.7 s to a complete
sentence and 0.5 s to an unfinished one. Short answers never wait: a yes, a no or a "stop" would otherwise lag an
approval or a barge-in. While the user is voicing again (`user_started_at > user_stopped_at`) the held text waits for
the next final and the two are joined, up to the cap, as today.

Since 1.14.0 the silence is counted from when the sound ended, with ears that time their own words (Soniox): the later
of the last word's end and the voice detector's stop less its 0.2 s (`VAD_STOP_SECS`, the delay it is built with). It
was counted from the detector's stamp as it came and from the arrival of the last live word, which is the network's
lag, and the held words were checked every 0.1 s: measured on a live call, Normal took the turn 1.3 s after the last
word. A live word restarts the count only when it came after the final transcript. Ears without word times keep the
old count. While a complete sentence settles, the model already reads it (`conversation-flow.md` §7); nothing is said
or done with its answer unless the turn is taken with exactly those words.

Soniox's parameters stay (`-0.5`, 2500 ms): the settle sits after them, and making Soniox slower would also delay the
live caption. From 1.14.6 the call also asks Soniox for words it holds (§3.5). `HOLD_UNFINISHED_SECS` / `HOLD_MAX_SECS` move into the levels.

### 3.2 A wider "unfinished" check (`guards.unfinished`)

Added, EN: `which who(m)? when while where after before until unless although also plus versus either neither not very
really pretty quite basically actually like I mean you know kind of sort of such as rather than as well as in order to
as soon as and then`; `like`, `when`, `where`, `who` only outside a question (as `to`, `at` already are).
HE: `אבל וגם ואז כאילו בעצם אחרי לפני עד כש בגלל למרות בשביל לגבי בתוך ליד מול אצל בלי כדי שאני שאתה שהוא שזה שהם
אה אמ`. The existing tests stay green (`tests/test_units.py:653`); new ones cover each language.

Not done: a smart-turn model. pipecat's `LocalSmartTurnAnalyzerV3` needs a new Hugging Face asset pinned by commit
(`assets.py`, egress and dependency allowlists, `THIRD_PARTY.md`) and its 23 languages do not include Hebrew. It would
help the English content-word case (prosody), so it is the natural next step once the owner says yes to the asset; the
settle time is where it would plug in (it would replace the `complete` row with "the model says finished").

### 3.3 Hold: "don't interrupt me"

A short utterance (≤ 10 words) that is a hold request starts a hold; nothing said is answered until a release.

- Start, EN: "hold on", "hang on", "don't interrupt (me)", "don't cut me off", "let me finish (my thought / talking)",
  "let me talk", "I'm not done / finished", "not done yet", "wait till I'm done", "give me a second / sec / minute /
  moment", "one second / sec / moment", "just a sec".
  HE: "אל תפריע לי", "אל תקטע אותי", "תן לי לסיים", "תן לי לדבר", "(עוד) לא סיימתי", "חכה רגע", "חכה שאסיים", "שנייה",
  "רק שנייה", "רגע אחד", "תן לי רגע", "אל תענה עדיין".
  Guarded: "don't interrupt the deploy", "let me finish the migration first", "give me a second opinion", "hold on to
  the old version" are content, not holds (the phrase must end the utterance, or name the speaker: me / אותי / לי).
- Release: an utterance (≤ 12 words) that **ends** with "I'm done", "done", "I'm finished", "that's it", "that's all",
  "go ahead", "over", "over to you", "your turn", "you can answer / talk / speak now", "answer now", "what do you
  think", "thoughts"; HE: "סיימתי", "זה הכל", "זהו", "קדימה", "תורך", "עכשיו אתה", "אתה יכול לדבר", "תענה", "מה אתה
  חושב", "מה דעתך", "נו". Or **8 s of silence** since the last word.
- 8 s: longer than any within-turn pause a person makes while thinking aloud (the hold exists for 2–5 s pauses, and
  the brainstorm mode exists for "stay quiet however long"); short enough that a forgotten hold does not read as a
  dead call (the idle hang-up is 30 min; a person waits about 10 s before asking "are you there?"). Not scaled by the
  setting: the release phrase is the primary exit and the silence is the safety net.
- While held: finals are kept in order (`state.hold.said`), the live caption still shows them, and the bot does not
  speak. It is a mode (`modes.HOLD`: approvals by tap only, news held, no nudges, no read-outs, `speech="never"`),
  narrower than conversation like brainstorm, so a "yes" said mid-thought approves nothing. The hold phrase itself
  interrupts the bot if it was talking. On release the whole of what was said, then the release words, go to the brain
  as one turn; held session news and a pending approval follow, as after a brain dump (`_after_quiet`).
- Shown: the page's state pill reads "Holding · say “go ahead” when you're done"; the phone's title line reads
  "Holding" with the same hint under it. Status carries `hold: {since, said} | null`.
- Not the brainstorm. Brainstorm ("just listen") is a mode the user enters for minutes, collects a transcript for a
  summary, chimes, and has no silence exit. Hold is a turn-level pause with a silence exit. They share the news-holding
  machinery and nothing else; a hold inside a brainstorm is just more brainstorm words.

### 3.4 Setting: "Wait before answering"

`prefs.py` `turns.patience: ("normal", ("quick", "normal", "patient"))`, one daemon setting both clients show.
Page: Settings → new group "Turn taking", `<select id="pref-patience">` Quick / Normal / Patient with the note "How
long a pause ends your sentence. Patient waits longer before answering; a hold ('don't interrupt me') waits for 'go
ahead' or 8 s of quiet." Phone: the menu's Picker "Wait before answering", same three labels, `turns.patience` via
`savePrefs`. An older Mac without the key decodes as Normal.

### 3.5 Asking Soniox for the words it holds (1.14.6)

Soniox's `stt-rt-v6` (1.14.5) keeps some whole sentences open until about 3 s after the speech, past its own
`max_endpoint_delay_ms`, and no turn can settle before its words are final: on the 560-clip bench the speech end to
final transcript p90 went from 0.83 s (v5) to 2.67 s, in Hebrew past 2.5 s. Soniox's own settings could not close it:
the delay cap is overshot by about 0.8 s at every value, and its lower-latency start (`endpoint_latency_adjustment_level`
2, `endpoint_sensitivity` 0.3, 1500 ms) split 38 of 560 sentences and still had a p90 of 2.13 s
(`bench/results/soniox-v6.md`).

So `PttGate.tick` sends Soniox a `finalize` when it holds words (`state.unfinalized`: an interim transcript with no final
after it), the voice detector says the user stopped, and `turns.finalize_after(level)` has passed since the sound ended:
a whole sentence's settle less the 0.3 s Soniox takes to answer, so the words are final when the settle ends and no
sooner (0.7 s at Normal, 1.5 s at Patient, never under Soniox's 0.2 s). Once per silence, at most every 2 s. Not while a
push-to-talk press collects (its release finalizes) or a meeting has the microphone, and only with Soniox ears. The
silence is the voice detector's, never word times: those lag the audio, and a finalize sent on them split words in the
middle ("apply. Underscore discount.").

The settle still decides the turn: a half sentence finalized in a pause waits its 3.0 s like any other unfinished final.
What changes is that Soniox's own hold no longer adds patience on top of the level. In `bench/pause_bench.py` (20
sentences, EN and HE, said in two parts with 1.2 or 2.0 s between): a first part that reads unfinished is never taken
(0 of 20, as with v5); one that reads whole is taken at Normal 60 of 60 times, against 52 of 60 with v5, whose endpoint
sometimes waited through the pause. At Patient a 1.2 s pause after a whole clause is not taken (0 of 30, v5 0 of 30).

## 4. Measuring: the offline harness (`tests/test_turn_taking.py`)

Soniox is a paid stream, so the harness replays **transcript events**, not audio: each case is a list of
`(final_text, silence_after_secs)` as Soniox would deliver them, with the true turn end at the last segment. The policy
is a pure function (`turns.settle(text, held, level) → seconds`); a cut is premature when the settle time is shorter
than the pause before the next segment. 48 cases: 30 EN, 18 HE; pauses 0.5–1.4 s; dangling words, fillers, and
content-word pauses, plus whole sentences that must not wait past `base`.

| Policy | Premature cuts / 48 | Longest wait for a whole sentence |
|---|---|---|
| Today (1.4.0: `base 0`, unfinished 2.5, old list) | **38** | 0.0 s |
| Quick | 24 | 0.4 s |
| Normal (default) | **0** | 1.0 s |
| Patient | 0 | 1.8 s |

The test asserts today's policy cuts at least a third of the cases, Normal and Patient cut none, Quick cuts fewer than
today, no whole sentence waits past 2 s, and a one-word answer never waits. The table is printed on every run
(`uv run --locked pytest -q tests/test_turn_taking.py -s`). Today's policy is frozen in the test file, so it keeps
being measured after the rules move on. Quick cuts the content-word cases on purpose: it is the "answer as soon as I
stop" choice, and still catches the dangling-word cases today misses.

## 5. What shipped (1.5.0)

- `turns.py`: `LEVELS`, `settle`, `maximum`, `hold_intent`, `release_intent`, `before_hold`, `Hold`,
  `HOLD_RELEASE_SILENCE_SECS = 8.0`.
- `guards.unfinished`: the wider lists and phrases, Soniox's closing full stop ignored, the question check on the words
  before the last one ("it fails when" is cut; "tell me when" asks).
- `daemon.py`: `SonioxEars` settles every final (`turns.settle`), `_release_held` takes the wait, `_start_hold` /
  `_watch_hold` / `_release_hold` and the hold prelude in `_take`; `state.hold`; `modes.HOLD` from `current_mode`;
  `hold` in `/voice/status`; `HOLD_UNFINISHED_SECS` and `HOLD_MAX_SECS` are gone.
- `prefs.py`: `turns.patience`. Page: Settings → Turn taking, the "Holding" pill. App: `Turns.swift`, the menu Picker,
  `API.Status.hold`, `API.Prefs.patience`, the "Holding" title.
- Tests: `tests/test_turn_taking.py` (the harness, `unfinished` in EN and HE, hold and release intents in both,
  the hold on the call with a phrase and with the silence release, the settle on the call, the setting's round trip,
  page/app parity of words and values), `ios/PointeTests/TurnsTests.swift`. The existing half-sentence test in
  `tests/test_orchestrator.py` now sets a fast level instead of the removed constant.
- Not shipped: the smart-turn model (§3.2), a page e2e (the offline parity test covers the setting; the live
  `tests/e2e/turn_taking.py` still runs against a real call when asked and its "answers within 3 s of the real end"
  check holds with Normal's 1.0 s).
