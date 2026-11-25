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

A smart-turn model was not part of 1.5.0. §6 measures one: it now ships inside the pinned pipecat wheel, so it needs
no new asset. It is judged and logged on every turn, and it does not change the wait.

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
  page/app parity of words and values), `apps/PointeKit/Tests/PointeUIUnitTests/TurnsTests.swift`. The existing half-sentence test in
  `tests/test_orchestrator.py` now sets a fast level instead of the removed constant.
- Not shipped: the smart-turn model (§3.2), a page e2e (the offline parity test covers the setting; the live
  `tests/e2e/turn_taking.py` still runs against a real call when asked and its "answers within 3 s of the real end"
  check holds with Normal's 1.0 s).

## 6. A shorter wait when three signals agree: measured, not shipped (0.8.x)

The 1.0 s at Normal is the largest single stage of a turn that needs no model step. The idea: wait less when the turn's
end is sure. Three signals, each known when the final transcript arrives:

- **The words** read whole (`guards.unfinished` is false).
- **Soniox ended them itself** (`<end>`), not on a finalize Pointe asked for (`state.finalize_asked_at`).
- **The voice sounded finished** when it stopped: Smart Turn v3.2 (`pointe/turnsound.py`), the 8.7 MB ONNX model inside
  the pinned pipecat wheel (BSD-2-Clause), on the audio of the turn so far. About 40 ms on one core, on this Mac: no
  audio leaves, nothing is downloaded. A turn with the bot's own voice in it is not judged, nor are Hebrew words.

The candidate rule (`turns.CANDIDATE`): all three agree, 0.3 s; the words and one other, 0.6 s; otherwise 1.0 s; words
that trail off, 3.0 s as before; a sentence said in parts, 1.0 s. When the voice sounded finished Soniox is asked for
its held words 0.3 s after the sound instead of 0.7 s.

### What it did (`bench/turn_bench.py`, 280 clips, real Soniox, load median 6.4)

Sentences said in two parts with a pause, and whole sentences, by two synthetic voices. A cut-in is a turn taken before
the second part.

| First part | Pause | Clips | Normal today | Candidate |
|---|---|---|---|---|
| trails off, English | 0.5, 0.8, 1.2 s | 78 | 1 (1%) | 7 (9%) |
| trails off, Hebrew | all | 12 | 0 | 0 |
| reads whole, English | 0.5 s | 34 | 0 (0%) | 32 (94%) |
| reads whole, English | 0.8 s | 34 | 5 (15%) | 32 (94%) |
| reads whole, English | 1.2 s | 34 | 34 (100%) | 34 (100%) |
| reads whole, Hebrew | all | 48 | 19 (40%) | 22 (46%) |
| all hesitations | | 240 | 59 (25%) | 127 (53%) |

A whole English turn was taken 0.60 s after its last sound instead of 1.00 s (median and p90, 30 clips). Hebrew stayed
at 1.00 s.

The sound's score does not tell a pause from an end on these clips: a whole turn scored 0.97 at the median, and a first
part that reads whole scored 0.97 too (91% of them at 0.8 or over). It does tell a trailing voice: first parts that
trail off scored 0.19 at the median. The text rules already hold those, and where Soniox dropped the trailing word
("Move the tests, which" heard as "Move the tests.") the candidate took the turn.

### Why it is not shipped

- **It doubles the cut-ins.** A pause of 0.5 to 0.8 s after a clause that reads whole is the complaint this document
  began with, and the candidate takes that turn 94% of the time against 0 to 15%.
- **It does not make the first word sooner where a model answers.** The model step already starts at the final
  transcript, 0.45 s after the last sound, and its first sentence is ready 0.9 to 1.3 s later: after the 1.0 s wait
  has passed. On `tests/e2e/latency.py` (12 plain questions, load 7 to 11) the turn was taken 0.44 s sooner and the
  first sound came no sooner. The gain is only on turns the daemon answers itself and on a send's acknowledgement,
  and a send is where a cut-in costs most: half an instruction reaches the session.
  On 21 dialogues of the suite run side by side (load 5 to 9, 30 timed turns each): the turn was taken 0.83 s after
  the last word instead of 1.18 s; turns with no model step were heard at 1.26 s instead of 1.44 s; the first word's
  median was 2.28 s against 2.14 s and its p90 4.58 s against 4.32 s, which is the model's own variation. No turn was
  cut in on in either run (one pause item).
- **The clips cannot settle it.** A synthetic voice reads "The retry loop is wrong" as a sentence; a person who stops
  to think may not. The sound model may do better on people. That needs recorded human pauses (the acceptance in the
  backlog: at least 100), not these clips.

### What is in the code

`turns.settle` takes the two new signals, and `SonioxEars._settle` gives them to it. The three levels wait as before
whatever the signals say. Each turn's timing line carries what they said (`"endpoint"`, `"sound"`, `"wait"`), so a
recorded-human run or a live call shows how often they agree and what a shorter wait would have done. To try the
candidate: set a level's `agreed` and `likely` in `turns.LEVELS`.

The live words cannot start the model sooner either. At the voice detector's stop Soniox's live words lack the last
one to three words ("What time zone is Tel" for "What time zone is Tel Aviv in?", 12 of 12 turns); the whole sentence
arrives with the final.

### On recorded people (`bench/human_turns.py`, AMI meeting speech)

The same two rules on real mid-sentence pauses of 0.5 to 2.0 s and real ends of turn, rows taken at load 20 or under.
The first two rows of rules are `human_turns.py report`; the narrower rules and the other levels were replayed from
the same Soniox rows (the `before` streams) with `turns.settle` and a changed `agreed`, in a script that is not kept.

| Rule | Cut-ins on 205 pauses | 193 ends: taken before 0.95 s | Mean wait at an end |
|---|---|---|---|
| Normal today | 47 (22.9%) | 10% | 1.05 s |
| The candidate as tried (0.3 s, 0.6 s, Soniox asked sooner), 165 pauses and 164 ends heard under both | 65 (39%) against 37 (22%) | median 0.60 s against 1.00 s | |
| Only when both agree: Soniox ended it itself and the sound is 0.8 or over, then 0.3 s; Soniox asked as today | 48 (23.4%) | 30% | 0.94 s |
| The same with the sound at 0.98 or over | 47 (22.9%) | 18% | 1.01 s |
| Quick today | 66 (32.2%) | 83% | 0.68 s |
| Patient today | 4 (2.0%) | 4% | 1.86 s |

- **The candidate stays off.** On people it cuts in on 39% of pauses against 22%: the 0.6 s wait on the sound alone,
  with Soniox asked sooner, is what does it. A person's unfinished clause sounds finished to the model 41% of the
  time (a finished turn: 58%).
- **A narrower rule is safe on this set and small.** Waiting 0.3 s only when Soniox ended the words itself and the
  sound agrees adds one cut-in in 205 and takes 30% of ends before 0.95 s instead of 10%. The median end is still
  taken at 1.00 s, because Soniox rarely ends a person's turn by itself inside the first 0.7 s. On the synthetic
  clips the same rule doubles the cut-ins (51% against 25%): those voices read half a sentence as a whole one.
  To try it: `agreed=0.3` on Normal in `turns.LEVELS`, nothing else.
- **What the people show about today.** Normal takes the turn inside 23% of real pauses of half a second or more
  (55 to 64% of those of 0.8 s or more, where the words read whole); Patient inside 2%.

