# Conversation flow: short answers, and the user's turn is the user's

Owner feedback from live use: "The voice agent should be more concise unless asked to elaborate, and keep the turns more
strictly. A lot of the time he asks me a question, I start answering, and then he gets some other update and interferes,
which breaks the flow of the conversation. The conversation experience is critical: it must be pleasant and human-like
to talk with."

This document measures both complaints on real calls, finds each cause in the code, sets the rules a good human
assistant on a call follows, and lists what shipped. `turn-taking.md` covers the other half (when the user's turn ends);
this one covers when Pointe may speak and how much.

## 1. Evidence

Source: the journal of ten calls over four days on 1.5 to 1.7 (352 spoken turns, 252 user turns, 87 of the spoken turns
in Hebrew), and the full log of the latest call, which carries the voice detector's start and stop stamps (238 user
voice stretches, 166 stretches of Pointe speaking). Counts and patterns only: no words from a call are kept here.

### 1.1 Length

| Spoken turns | n | Median words | p90 | Max | Over 30 words | Over 2 sentences |
|---|---|---|---|---|---|---|
| Replies to the user's words | 228 | 27 | 47 | 97 | 86 (38%) | 108 (47%) |
| Nobody asked (reports, resumes, queued news) | 124 | 38.5 | 72 | 104 | 84 (68%) | 84 (68%) |
| All | 352 | 30 | 59 | 104 | 170 (48%) | 192 (55%) |

- The prompt already said "one or two short sentences, under 30 words". 109 of 228 replies broke it when the user had
  not asked for detail (16 replies followed a request for detail).
- Longer turns are cut off more: the user barged in on 23–26% of turns up to 30 words and on 36–39% of turns over 30.
  116 barge-ins in all; 108 of 352 spoken turns ended by one.
- Pointe spoke for a median of 8.0 s per stretch, p90 21 s, the longest 42 s; 67 of 166 stretches ran over 10 s.
- 72 turns held a list of four or more parts.

### 1.2 Speaking into the user's turn

| What | Count |
|---|---|
| Spoken turns that ended on a question | 141 |
| Followed by another Pointe turn before the user's answer was taken | 30 (21%) |
| … of those, a session's finished-turn report | 17 |
| … a report resumed after a barge-in (`[resume]`) | 4 |
| … other queued news with no trigger of its own in the journal | 9 |
| … where the user had already started to answer | 10 |
| … that started within 5 s of the question's end | 14 |

With the voice detector's stamps (latest call, 65 questions): 14 were followed by another Pointe turn first; in 4 the
user was voicing, within 3 s of their last word, or had a sentence still settling, and in 2 more they had spoken since
the question. Pointe's audio started while the user's voice was active 15 times, and 4 more times within 1.2 s of
the user's voice stopping.

How long the user takes to start (latest call): after a question, median 5.0 s, p75 11.8 s, 33 of 39 within 20 s. After
a statement, median 6.2 s; 8 of 45 follow-ups start within 3 s and 19 within 5 s. Pauses inside the user's own speech:
median 0.7 s, p90 2.3 s, 36 of 134 longer than 1.2 s.

### 1.3 Other turn violations

| What | Count |
|---|---|
| Two Pointe turns in a row with no user turn between | 117 of 352 |
| … the second within 3 s of the first ending (or before it ended) | 44 |
| … the second a near copy of the first (over half the same words) | 9 |
| Two `speak` lines with no model step between (one step, two speak calls) | 5 in the latest call |
| "One sec." fillers | 5, all 4.5–7.5 s after the user's own words: none unprompted |
| "Say that again?" spoken right after Pointe's own question, on a turn the user did not start | 1 |
| Repeats cut by the existing filter | 38 in the latest call (it works; left alone) |
| Nudges | 3 |

## 2. Root causes (file:line on 1.7.1)

1. **An update waits for sound, not for the floor.** `FeedInjector.inject` (`daemon.py:609`) holds a report only while
   Pointe is speaking, for 4 s after it asked the model for a reply (`REPLY_WAIT_SECS`, `daemon.py:334`), or while
   `_user_talking()` (`daemon.py:513`): the voice detector is active or the last word is under 1.2 s old
   (`USER_GAP_SECS`, `daemon.py:510`). Nothing knows that Pointe asked a question, or that the user's sentence is still
   settling: `turns.py` holds an unfinished sentence for 3 s, and the news goes 1.2 s into that pause.
2. **Held speech goes the moment Pointe stops.** `daemon.py:579` releases what was held 0.3 s after
   `BotStoppedSpeakingFrame`, also when what Pointe just said was a question. That is the "within 5 s" group.
3. **A report queued behind the user's words is answered the instant their reply is handed to the mouth.**
   `Brain.turn` (`brain.py:325-329`) runs the waiting news as a new turn straight after the reply: two turns back to
   back. Most of the 44 "within 3 s" double turns.
4. **A cut-off report comes back at once.** `daemon.py:572` re-offers it (`[resume]`) at the next stop, in the middle
   of the exchange that cut it.
5. **`_release_unanswered` (`daemon.py:650`)** lets held speech go 4 s after a reply was asked for, whatever the
   conversation is doing.
6. **The approval read-out bypasses all of it.** `_read_out_when_quiet` (`daemon.py:4971`) waits only for the brain to
   be idle, then `front._speak` (`daemon.py:4953`) talks, over the user if they are mid-sentence. The nudger re-reads
   it the same way (`daemon.py:1845`).
7. **Every `speak` call of a step is spoken.** `brain.py:388` loops over them: a draft and its rewrite in one step
   are both said (the near copies).
8. **Fillers and "say that again" do not check who started the turn.** `Brain._step` (`brain.py:446`, `480`) and
   `brain.py:376` run on a report's turn as on the user's.
9. **Length is only asked for.** `daemon.py:393` says "one to three sentences", `daemon.py:687` says under 30 words
   "unless … a report needs more", and no code checks either outside drive mode (`drive.length_problem`). The report
   writer is told "at most 65 words … up to 90" (`brief.py:69`), which is why unprompted turns are the longest. The
   prompt also says "After delegating, say … it is on it, then keep talking" (`daemon.py:450`).
10. **Joins, closes and an answer to a side question** (`daemon.py:4594`, `4393`) go through the same `inject`, so they
    land mid-exchange too.

## 3. Design

A good human assistant on a call: answers what was asked and stops; asks one thing and then waits; keeps a note of
what came in while you were talking and tells you at the next pause, in one breath; and interrupts only for something
that cannot wait, after you finish your sentence.

### 3.1 Concise by default (`conversation.Limit`, enforced in `brain.py`)

| The turn was started by | Limit | Words | Sentences | List items |
|---|---|---|---|---|
| The user's words | `REPLY` | 30 | 2 | 3 |
| The user's words, asking for more | `DETAIL` | 120 | 8 | any |
| A status question ("what's going on"), the greeting | `STATUS` | 60 | 4 | 3 |
| A session's report, a resumed report, a side question's answer | `REPORT` | 45 | 3 | 3 |
| An urgent report | `URGENT_REPORT` | 60 | 4 | 3 |
| Several updates at once | `BATCH` | 40 | 2 | 3 |
| Drive mode | drive's own 25 words | 25 | 2 | 3 |
| A briefing part, a brain-dump read-back, a challenge, a meeting, a line the daemon wrote | none | | | |

- **Asking for more** (`wants_detail`): "tell me more", "say more", "elaborate", "details", "in detail", "explain",
  "walk me through", "the full/whole thing", "read it", "everything", "all of them", "list them", "the rest", "go on",
  "continue", "longer", a lone "more"; Hebrew "תפרט", "בפירוט", "תרחיב", "בהרחבה", "תסביר", "ספר לי עוד", "עוד פרטים",
  "תקריא", "מה בדיוק", "הכל", "את השאר", "תמשיך", "עוד". It is read from the user's latest own words, so it lasts one
  answer. A report that arrives afterwards is still a report.
- **Enforced twice.** The prompt states the limits (`INSTRUCTIONS` "How to talk", `BRAIN_RULES` "Length", the report
  writer's "say" field: 45 words, 60 when urgent). In code, a reply over its limit is refused once with the reason
  (`length_problem`), like drive mode's rule: the model shortens better than a cut. A second long one is cut
  (`trim`): the first sentences that fit, the closing question kept (it is the decision asked of the user), one
  sentence too long on its own cut at a clause, then "There's more if you want it." / "יש עוד, אם תרצה." That line is
  a statement, not a question, so it does not take the floor (§3.2). One retry, not two: a second costs another model
  step (about 2 s) with the user waiting. Since 1.13.5 a reply over only on sentences, within the words, skips the
  retry and is cut at once (§6).
- **Lists.** Three items, then how many more ("billing, docs, lantern, and 2 more"). The model is sent back for a list
  of four or more. The code cut applies from five: "and 1 more" is no shorter than the fourth name. Never cut: the
  options of a choice put to the user (a question, or an "or" list): they are the question. A part longer than three
  words is a clause, not an item. Numbered points ("One: … Two: …") stop after the third with the offer.
- **Closing promises go.** A last sentence that only says Pointe is waiting or will report later ("I'll read it out
  when it arrives", "Waiting on its next question", "אעדכן אותך …") is dropped, next to the existing empty closers.
- Not changed: the repeat filter, the "end on the next move" rule, the answer-first rule.

### 3.2 The floor (`conversation.Floor`)

One object says who may speak, fed by the call's events: Pointe's words handed to the mouth (`said`), its sound
starting and stopping, the user's voice starting and stopping, a live word heard, the user's turn taken. `blocked(now,
busy, pending, urgent)` returns why nothing unsolicited may start, or `None`. In order:

| # | State | Blocked while | Applies to the urgent exception |
|---|---|---|---|
| 1 | **The user is speaking** | the voice detector is active; or the last sound or live word is under 1.2 s old (`USER_GAP_SECS`); or `pending`: the ears hold words that are not a turn yet (the settle time, so the "Wait before answering" setting stretches it), a push-to-talk press is open, or a hold ("don't interrupt me") is on | yes |
| 2 | **Pointe is answering** | its sound is playing; the brain is working on a reply (`busy`); or its last words or sound are under 1.2 s old (a breath between two turns of its own) | yes |
| 3 | **Pointe asked a question** | its last turn ended in "?" and the user has not taken a turn since, for 20 s (`QUESTION_FLOOR_SECS`) of silence counted from the end of the question or the user's last sound, whichever is later | no |
| 4 | **Mid-exchange** | less than 5 s (`QUIET_GAP_SECS`) since Pointe stopped, the user's last sound, or the user's last turn | no |

- **The question closes** when the user takes a turn: an answer, another topic, "later", a typed line. Any sound from
  them restarts the 20 s (an "hmm" is the start of an answer). A click that makes Pointe speak replaces the question.
- **20 s**: measured, 33 of 39 answers started within 20 s of the question (median 5.0 s, p75 11.8 s). Past that the
  user is working on something else or thinking long, and a person in the room would say "by the way". Shorter (10 s)
  would break into one answer in four; longer keeps a finished session silent for half a minute on every question the
  user chose not to answer. The question itself stays in Pointe's notes and on the page.
- **5 s**: 8 of 45 follow-ups to a statement started within 3 s and 19 within 5 s; inside the user's own speech 90%
  of pauses are under 2.3 s. A gap of 5 s is past the point where a follow-up is likely and short enough that a
  finished session is heard about in the same breath of the conversation. If the user starts in those 5 s, rule 1 takes
  over and the wait starts again after Pointe's reply.
- **Nobody talking** (rules 1–4 all clear): an update is said at once, as before.

### 3.3 Updates (`conversation.is_update`, `conversation.Updates`)

An **update** is speech the daemon starts on its own: a session's finished-turn report (active or background), a
resumed report, a nudge about an idle session, a session joined or closed, a machine offline, an approval waiting in
another session or in a terminal, the answer to a side question, two sessions disagreeing, a briefing that is ready.
A **reply** is anything the user just asked for or did: their words, a briefing part, their answer to an approval, a
click, a mode they switched. Replies keep today's path. Updates queue.

- **Queued, not spoken**, while the floor is blocked. The queue keeps one report per session, the newest ("3 of 7
  checks", then "all green", is one update).
- **Delivered at the first gap**, all of them, as **one turn**. One update: said as it came (a report keeps its
  prepared text, within `REPORT`). Two or more: one line under `BATCH`, most important first, "Two updates: billing
  finished and needs your yes to merge, docs is done." Three named at most, then how many more. No details and no
  question: the user asks, and the full text of each is in the brain's history for that.
- **Order** (`priority`): what blocks an agent or is marked urgent (an approval waiting elsewhere, an urgent report),
  then results (reports, resumes, answers), then joins and closes, then nudges.
- **An update the user talked over before a word was heard** (they spoke between the hand-off to the voice and its
  first sound) goes back to the front of the queue. One the user cut mid-way comes back as `[resume]`, as before, but
  through the queue: at the next gap, not at the next stop.
- **Modes**: brain dump, hold and meeting already keep news for their end (`holds_news`); the queue sits behind that
  check and re-checks at delivery, so an update queued just before a dump starts waits for the dump's end.
- **The call ends**: what was still queued is dropped with it, and the floor starts clean on the next call. The next
  call's greeting and the page say where each session stands.
- **The nudger** also asks the floor before it picks a session, on top of its own 20 s / 10 s quiet rule.

### 3.4 The one exception: an approval about to go back to its terminal

A permission request holds an agent. Its read-out for the active session now waits for the floor like any update: not
over the user, not while they answer a question, after Pointe's reply. The card on the page and the phone shows it the
whole time, and a tap answers it.

It becomes **urgent** when it is within 60 s (`URGENT_LEFT_SECS`) of its harness's deadline (Claude Code: 280 s, then
its own prompt takes over; OpenCode and Codex: 600 s). Urgent skips rules 3 and 4 and nothing else: it still waits for
the user to finish the sentence (rule 1, including a sentence that is settling) and for Pointe's reply to it (rule 2),
then says "One urgent thing. billing wants to …. Should it?" ("דבר אחד דחוף. …"). 60 s leaves time to hear it and say
yes. An urgent report is not an exception: it is first in the batch.

A yes still counts only after the read-out, as before; a yes to Pointe's own question never approves a request that
was not read.

### 3.5 No double turns, no fillers

- One `speak` per model step: the last. Earlier ones in the same step are returned to the model as replaced.
- A turn nobody asked for (an update or a batch) never says "One sec.", "Sorry, I lost that. Say it again?", "The
  model took too long …" or "That took too many steps": the user said nothing and may be thinking. The update stays
  in the history and on the page.
- Rule 2's breath and rule 4's gap sit between any two Pointe turns that the user did not ask for.
- The prompt: one question per turn, never follow your own question, never say you are waiting; "then keep talking"
  became "then stop".

### 3.6 Settings

None added. "Wait before answering" (`turns.patience`) is respected through `pending`: a Patient user's longer settle
keeps the floor theirs for longer. Hold mode and brain dump are `pending` and `holds_news` as before. The four waits are
constants in `conversation.py`; a setting comes only if use shows one value does not fit.

## 4. Measuring: the simulator (`tests/test_conversation_flow.py`)

Scripted timelines on a virtual clock (Pointe says, the user's voice, a sentence settling, the user's turn and
Pointe's reply to it, an update arriving, an approval arriving with its time left), run against two policies: 1.7.1's,
frozen in the test, and the shipped `Floor` and `Updates`. Printed on every run.

| Scenario | 1.7.1: before the answer / over the user / turns | Now |
|---|---|---|
| A report and a background report arrive mid-answer (the owner's case) | 1 / 1 / 2 | 0 / 0 / 1 |
| A report one second after Pointe asks; the answer starts six seconds later | 1 / 0 / 1 | 0 / 0 / 1 |
| Three reports during Pointe's answer; a follow-up three seconds after it | 1 / 0 / 3 | 0 / 0 / 1 |
| A nudge while the user thinks about a question | 1 / 0 / 1 | 0 / 0 / 1 |

In the owner's case 1.7.1 starts the first report at 10.3 s, in the thinking pause of an answer that ends at 15 s, and
the second on its own after it; now one batched turn starts at 25.3 s, 5 s after Pointe's reply to the answer ends. An
approval with 40 s left cuts in 1.2 s after that reply, with "One urgent thing."; with 280 s left it waits for the gap;
1.7.1 read it out over the answer.

Replaying the 352 real spoken turns through the length rules (the code cut alone, no model retry): 158 (45%) are over
their limit and would be sent back once; cut in code they go from a median of 30 words (p90 58) to 23 (p90 38), 26%
fewer words in all.

A small live check (the real `Brain` on Gemini 3.8 Flash, five invented sessions, 14 short questions in English and
Hebrew, 3 requests for detail, 1 report; not a call, and not the Anthropic brain the logged calls ran on):

| | Short questions over 30 words | Over 2 sentences | Median words | Asked for detail: median words |
|---|---|---|---|---|
| 1.7.1 prompt, no limit | 3 of 14 | 1 | 27.5 | 36 |
| 1.8.0 prompt and limit | 0 of 14 | 0 | 25.5 | 48 |

How often a reply needs the retry or the cut on real calls is not measured yet: it needs calls on this version.

## 5. What shipped (1.8.0)

- `conversation.py` (new, pure): `Limit` and the limits, `wants_detail`, `limit_for`, `length_problem`, `trim`,
  `list_items`; `is_update`, `priority`, `batch`, `Updates`; `Floor`; the four waits.
- `brain.py`: `Brain.limit`; a long reply refused once, then cut; one `speak` per step; no filler or "say that again"
  on an update's turn; closing promises dropped in `without_closer`.
- `daemon.py`: `state.floor` fed by `SonioxEars`, `BrainFront._speak`, `BotSpeechTap`, `FeedInjector` and
  `on_user_utterance`; `state.settling` from the ears' held words; `_floor_blocked`; `FeedInjector._queue_update` /
  `_deliver_updates` (the queue, the batch, the re-queue of an unheard update); `[resume]` through the queue;
  `_read_out_when_quiet` and `_permission_urgent` (the exception); the nudger asks the floor; `_reply_limit`; the
  prompts.
- `brief.py`: a report's "say" is 45 words, 60 when urgent (was 65 and 90).
- Tests: `tests/test_conversation_flow.py`: the simulator and its before/after table, the floor's rules, the queue's
  order and batching, the urgent exception, length in English and Hebrew, elaborate on request, lists, the brain's
  retry-then-cut, one reply per step, no filler on an update, and the real `FeedInjector` and read-out on small clocks.
  The daemon fixture in `tests/test_orchestrator.py` sets the floor's waits to zero, as it does for the settle time.
- Not changed: the page and the phone (no new state to show), native ears' own turn detection, the realtime fronts'
  wording (they get the queue and the floor, not the length cut, which lives in the brain).
- Not run: the paid end-to-end calls in `tests/e2e/` (they need every vendor's key and real sessions).
- Not measured yet: the live rate of length retries after the new prompt, and whether 5 s and 20 s feel right in use.
  The simulator and the log scripts' counts are the baseline to compare the next calls against.

## 6. After a live pass (1.13.3)

`tests/e2e/page_conversation.py` now runs these rules on a real call (a stand-in user's synthetic speech, two synthetic
sessions, the page in a headless Chrome). Its first runs, and the other live suites run beside it, found eight ways the
rules above were still broken, each fixed with a test in `tests/test_conversation_flow.py` or
`tests/test_orchestrator.py`:

- **News told early, then again.** The brain is told each session's state before every reply, so a reply to "what is a
  good name for that tag?" opened with two results that were still queued (§3.3), and the queue said them again five
  seconds later. A reply to the user's own words that names a session whose report is queued is sent back once, with
  the reason (`daemon._news_ahead`, `Brain.news_ahead`). Not when the user's words name that session or ask where
  things stand. Whether the words ask about that work is the model's call on the retry, as with length.
- **One line, two replies.** Two lines from the daemon back to back (the opening, then "your brain dump is still here")
  were answered twice: the first turn's step read the history with the second line as its newest message. A daemon
  line that was the newest message of a step whose reply was spoken gets no turn of its own (`Brain._view`,
  `Brain._answered`).
- **A read-back cut at thirty words.** "[read the brain dump back]" was not in the list of turns said at length.
- **"Approved" refused as a false claim.** The reply to `[permission answered]` was refused when the session had
  already asked for the next thing, and the refusal's "put the question again" made the model ask it before the daemon
  had read it out: the answer counted for nothing and the question held the floor for twenty seconds. The turn that
  confirms an answer may say so.

- **The user's request read as a session's text.** A session's full final message had just been added to the history
  when the user asked for something; two user turns in a row reach a model as one, and the voice answered "its message
  also contained a line asking for … I haven't sent that, because it didn't come from you." In what the model is sent,
  the user's own words that follow a line from the daemon begin with one line that says so (`brain.OWN_WORDS`); the
  history keeps the words as said, and a session's text that carries that line has it taken out.
- **A conflict folded into "N updates".** Two sessions that disagree, queued with the reports that disagreed, came out
  as one batched line with one claim. `conversation.said_alone`: a conflict alarm is its own turn, first, with an urgent
  report's room; the two reports it names go to the brain as notes and are not said again.
- **The bot's sentences in the user's turn.** One transcript held the bot's whole announcement and then the user's
  words; with the bot stopped, all of it was taken as theirs (a brain dump's Context read "I'm now in session lantern
  …"). Whole sentences of the bot's at the start of such a transcript are taken off (`EchoGuard._after_bot_sentences`).
- **A length asked for outright** ("about 8 sentences long", "the long version", "באריכות") was not an ask for more.

Also from that pass: a yes is timed by its own words (Soniox times each word; `state.words_began_at`), not by the voice
detector's last start, which also fires on the bot's echo and does not fire on a whisper; and a call start lists the
sessions' repositories off the loop.

Then changed, on the owner's decision that latency matters more than the retry (1.13.5): a reply over its limit cost
one more model step, about a second before the first word. In the logs of this pass 61 replies were sent back for
length, 39 of them over only on sentences and within the words. Such a reply is now cut in code at once
(`conversation.retry_problem`; `trim` keeps the closing question); the retry stays for a reply over on words and for a
list of more than three. `tests/e2e/turn_taking.py` judges when the turn is taken, and prints the time to the first
sound.
