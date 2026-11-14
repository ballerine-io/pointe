"""The conversation's flow (docs/design/conversation-flow.md): short answers unless more is asked for, and nothing
unsolicited while the floor is the user's.

The simulator replays scripted timelines on a virtual clock (who speaks when, when a sentence is still settling, when
a session's report or an approval arrives) against two policies: the one shipped in 1.7.1, frozen here so it keeps
being measured, and conversation.Floor with conversation.Updates, the objects the daemon runs. All names, sessions and
sentences are invented.
"""

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

import conversation as cv  # noqa: E402
from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)

SPOKEN_CHARS_PER_SEC = 14
STEP = 0.1
REPORT_BILLING = "[billing: claude-code finished its turn] Tell the user this in English:\nThe retry fix is in and all checks pass."
REPORT_DOCS = "[docs finished its turn, not the active session] Say one short line, starting with its name:\nThe changelog is written."
REPORT_SEARCH = "[search finished its turn, not the active session] Say one short line, starting with its name:\nThe index rebuild failed."
NUDGE = "[idle session] lantern has been waiting about 3 minute(s) for the user: a yes to deploy."


# ---------- the simulator ----------

@dataclass
class Sim:
    """One call on a virtual clock. `script` is a list of events:
    ("say", t, text)                      Pointe says this (a question it asks, an answer already under way)
    ("voice", t0, t1)                     the user's voice
    ("settling", t0, t1)                  words heard that are not a turn yet (the settle time of turns.py)
    ("turn", t, reply, think_secs)        the user's turn is taken; Pointe thinks, then says `reply` ("" for silence)
    ("update", t, text)                   something nobody asked for arrives: a report, a nudge
    ("permission", t, secs_left)          the active session asks for approval, this long before it goes back
    """
    policy: str
    script: list
    floor: cv.Floor = field(default_factory=cv.Floor)
    updates: cv.Updates = field(default_factory=cv.Updates)
    old_queue: list = field(default_factory=list)
    spoken: list = field(default_factory=list)  # (start, kind, text, how many updates it carried)
    now: float = 0.0
    bot_until: float = 0.0
    busy_until: float = 0.0
    pending_until: float = 0.0
    reply: tuple | None = None
    permission: tuple | None = None
    turns: list = field(default_factory=list)
    voices: list = field(default_factory=list)

    def run(self, until: float) -> "Sim":
        events = sorted(self.script, key=lambda e: e[1])
        while self.now <= until:
            while events and events[0][1] <= self.now:
                self._event(events.pop(0))
            if self.floor.bot_speaking and self.now >= self.bot_until:
                self.floor.bot_stopped(self.now)
            for start, stop in self.voices:
                if abs(self.now - start) < STEP / 2:
                    self.floor.user_started(self.now)
                    if self.floor.bot_speaking:  # a barge-in cuts Pointe off
                        self.bot_until = self.now
                        self.floor.bot_stopped(self.now)
                if abs(self.now - stop) < STEP / 2:
                    self.floor.user_stopped(self.now)
            if self.reply and self.now >= self.reply[0]:
                text, self.reply = self.reply[1], None
                if text:
                    self._speak("reply", text)
            self._deliver()
            self.now = round(self.now + STEP, 3)
        return self

    def _event(self, e) -> None:
        kind = e[0]
        if kind == "say":
            self._speak("reply", e[2])
        elif kind == "voice":
            self.voices.append((e[1], e[2]))
        elif kind == "settling":
            self.pending_until = e[2]
        elif kind == "turn":
            self.floor.user_turn(self.now)
            self.turns.append(self.now)
            self.busy_until, self.reply = self.now + e[3], (self.now + e[3], e[2])
        elif kind == "update":
            if self.policy == "new":
                self.updates.add(e[2])
            else:
                self.old_queue.append(e[2])
        elif kind == "permission":
            self.permission = (self.now, e[2])

    def _speak(self, kind: str, text: str, count: int = 0) -> None:
        self.floor.said(text, self.now)
        self.floor.bot_started(self.now)
        self.bot_until = self.now + max(1.0, len(text) / SPOKEN_CHARS_PER_SEC)
        self.spoken.append((self.now, kind, text, count))

    def _deliver(self) -> None:
        busy, pending = self.now < self.busy_until, self.now < self.pending_until
        if self.policy == "old":
            # 1.7.1 (daemon.FeedInjector.inject, brain.Brain.turn): an update waits only for Pointe's own voice, for a
            # reply it queued behind, and for 1.2 s after the user's last sound; then each is said on its own.
            talking = self.floor.user_voicing or self.now - self.floor.user_voice_at < 1.2
            if self.old_queue and not self.floor.bot_speaking and not busy and not talking \
                    and self.now - self.floor.bot_stopped_at >= 0.3:
                self._speak("update", self.old_queue.pop(0), 1)
            if self.permission and not self.floor.bot_speaking and not busy:  # the read-out waited only for the brain
                self._speak("permission", "billing wants to run the migration. Should it?")
                self.permission = None
            return
        if self.permission:
            arrived, left = self.permission
            urgent = left - (self.now - arrived) <= cv.URGENT_LEFT_SECS
            if self.floor.blocked(self.now, busy, pending, urgent=urgent) is None:
                cut_in = self.floor.blocked(self.now, busy, pending) is not None
                self._speak("permission", ("One urgent thing. " if cut_in else "") + "billing wants to run the migration. Should it?")
                self.permission = None
                return
        if self.updates and self.floor.blocked(self.now, busy, pending) is None:
            items = self.updates.take()
            self._speak("update", items[0] if len(items) == 1 else cv.batch(items), len(items))

    # what the trace shows

    def unsolicited(self) -> list:
        return [s for s in self.spoken if s[1] in ("update", "permission")]

    def over_the_user(self) -> int:
        """Unsolicited turns that started while the user was voicing or their words were still settling."""
        return sum(1 for start, *_ in self.unsolicited()
                   if any(v0 <= start <= v1 for v0, v1 in self.voices)
                   or any(e[0] == "settling" and e[1] <= start < e[2] for e in self.script))


def mid_answer_script() -> list:
    """Pointe asks; the user starts to answer, pauses to think, goes on; a session finishes and a background report
    arrive during the answer."""
    return [
        ("say", 0.0, "The index rebuild can run tonight or wait for the release. Which do you want?"),  # ends ~5.5 s
        ("voice", 7.0, 9.0),  # "I think we should…"
        ("settling", 9.0, 12.0),  # an unfinished sentence waits 3 s (turns.LEVELS normal)
        ("update", 9.5, REPORT_BILLING),
        ("update", 10.0, REPORT_DOCS),
        ("voice", 11.5, 14.0),  # "…wait for the release, tonight is too risky."
        ("settling", 14.0, 15.0),
        ("turn", 15.0, "Waiting for the release, then. I told search.", 2.0),
    ]


def run(policy: str, script: list, until: float = 60.0) -> Sim:
    return Sim(policy, script).run(until)


# ---------- the scenario from the owner's report ----------

def test_updates_that_arrive_mid_answer_wait_for_the_answer_and_its_reply_then_come_as_one(capsys):
    old, new = run("old", mid_answer_script()), run("new", mid_answer_script())
    answered = 15.0
    # 1.7.1: the first report starts in the thinking pause, on top of the answer, and the second follows on its own.
    assert old.unsolicited()[0][0] < answered and old.over_the_user() >= 1
    assert len(old.unsolicited()) == 2
    # Now: nothing until the user's turn ended and Pointe answered it, then one turn that carries both.
    assert new.over_the_user() == 0
    assert [kind for _, kind, *_ in new.spoken] == ["reply", "reply", "update"]
    start, _, text, carried = new.unsolicited()[0]
    reply_start = new.spoken[1][0]
    reply_end = reply_start + len(new.spoken[1][2]) / SPOKEN_CHARS_PER_SEC
    assert start >= reply_end + cv.QUIET_GAP_SECS - STEP and carried == 2
    assert text.startswith("[updates: 2 ") and "billing" in text and "docs" in text
    with capsys.disabled():
        print(f"\nmid-answer timeline: 1.7.1 spoke {len(old.unsolicited())} updates, the first at {old.unsolicited()[0][0]:.1f} s "
              f"(the user's turn ended at {answered:.0f} s), {old.over_the_user()} over the user; now 1 batched update at "
              f"{start:.1f} s, {new.over_the_user()} over the user")


SCENARIOS = {
    "report mid-answer (the owner's case)": (mid_answer_script(), 15.0),
    "report one second after Pointe asks, answer starts six seconds later": ([
        ("say", 0.0, "Docs wants to squash its commits. Should it?"),  # ends ~3.1 s
        ("update", 4.1, REPORT_BILLING),
        ("voice", 9.0, 10.5), ("settling", 10.5, 11.5),
        ("turn", 11.5, "Squashing.", 1.5)], 11.5),
    "three reports during Pointe's answer, a follow-up three seconds after it": ([
        ("voice", 0.0, 2.0), ("turn", 3.0, "The deploy is green and the canary holds at five percent.", 2.0),
        ("update", 5.5, REPORT_BILLING), ("update", 6.0, REPORT_DOCS), ("update", 6.5, REPORT_SEARCH),
        ("voice", 12.3, 14.0), ("settling", 14.0, 15.0),
        ("turn", 15.0, "Ten percent, on it.", 2.0)], 15.0),
    "a nudge while the user thinks about a question": ([
        ("say", 0.0, "Lantern can deploy now or after the review. Which one?"),
        ("update", 8.0, NUDGE),
        ("voice", 14.0, 16.0), ("settling", 16.0, 17.0),
        ("turn", 17.0, "After the review, noted.", 1.5)], 17.0),
}


def test_the_harness_shows_1_7_1_talks_into_the_users_turn_and_the_floor_does_not(capsys):
    rows = []
    for name, (script, answered) in SCENARIOS.items():
        old, new = run("old", script), run("new", script)
        before = sum(1 for start, *_ in old.unsolicited() if start < answered)
        after = sum(1 for start, *_ in new.unsolicited() if start < answered)
        rows.append((name, before, old.over_the_user(), len(old.unsolicited()), after, new.over_the_user(), len(new.unsolicited())))
        assert after == 0 and new.over_the_user() == 0, name
        assert len(new.unsolicited()) == 1, name  # nothing lost: every update is said, in one turn
    assert sum(r[1] for r in rows) >= len(rows)  # 1.7.1 breaks into every one of these exchanges
    assert sum(r[3] for r in rows) > sum(r[6] for r in rows)  # and takes more turns to say the same
    with capsys.disabled():
        print("\nscenario | 1.7.1: before the answer / over the user / turns | now: before the answer / over the user / turns")
        for name, *numbers in rows:
            print(f"{name} | {numbers[0]} / {numbers[1]} / {numbers[2]} | {numbers[3]} / {numbers[4]} / {numbers[5]}")


def test_an_update_with_nobody_talking_is_said_at_once():
    sim = run("new", [("update", 30.0, REPORT_BILLING)])
    assert sim.unsolicited()[0][0] == pytest.approx(30.0, abs=STEP) and sim.unsolicited()[0][3] == 1


def test_a_question_nobody_answers_gives_the_floor_back_after_the_timeout():
    question = "Should search rebuild the index tonight?"
    sim = run("new", [("say", 0.0, question), ("update", 4.0, REPORT_BILLING)])
    asked_until = len(question) / SPOKEN_CHARS_PER_SEC
    start = sim.unsolicited()[0][0]
    assert asked_until + cv.QUESTION_FLOOR_SECS - STEP <= start <= asked_until + cv.QUESTION_FLOOR_SECS + 2 * STEP
    assert 15.0 <= cv.QUESTION_FLOOR_SECS <= 30.0  # long enough to think of an answer, short of "is it still there?"


def test_a_sound_from_the_user_restarts_the_wait_on_an_open_question():
    sim = run("new", [("say", 0.0, "Tonight or after the release?"), ("update", 3.0, REPORT_BILLING), ("voice", 15.0, 16.0)])
    assert sim.unsolicited()[0][0] >= 16.0 + cv.QUESTION_FLOOR_SECS - STEP  # "hmm…" is the start of an answer


def test_updates_are_ranked_and_a_newer_report_replaces_the_one_before():
    queue = cv.Updates()
    queue.add(NUDGE)
    queue.add("[billing: claude-code finished its turn] 3 of 7 checks", key="billing")
    queue.add(REPORT_DOCS, key="docs")
    queue.add("[lantern is waiting for a permission, not the active session] Tell the user in one line.")
    queue.add("[billing: claude-code finished its turn] all green", key="billing")
    order = queue.take()
    assert len(order) == 4 and not queue
    assert "waiting for a permission" in order[0] and order[-1] == NUDGE
    assert "all green" in " ".join(order) and "3 of 7" not in " ".join(order)
    line = cv.batch(order, hebrew=True)
    assert line.startswith("[updates: 4 ") and "Hebrew" in line and "ONE short line" in line
    assert cv.limit_for(line, "") is cv.BATCH


@pytest.mark.parametrize("text", [
    REPORT_BILLING, REPORT_DOCS, NUDGE, "[resume] You were cut off while reporting a session's result.",
    "[session joined] lantern is now available. Mention it in a few words.",
    "[session closed] lantern closed. Say it in one line.",
    "[lantern is waiting for a permission, not the active session] Tell the user in one line.",
    "[docs answered the user's question 'why did the build fail'] A missing lockfile.",
    "[two sessions disagree] billing said: \"done\". Moments later, docs said: \"not done\".",
    "[briefing ready] The morning briefing is ready. Ask the user in one short line if they want to hear it now.",
])
def test_these_are_updates_nobody_asked_for(text):
    assert cv.is_update(text)


@pytest.mark.parametrize("text", [
    "[permission answered] The user approved it. Acknowledge in two or three words.",
    "[briefing, part 1 of 3, prepared by the daemon from the sessions' record]\nBilling shipped the retry fix.",
    "[briefing asked] The user asked for a briefing; it is being read now.",
    "[switched by click] Say exactly this, nothing else: Now on docs.",
    "[whisper mode on] The user turned whisper mode on.",
    "[billing finished its turn, keep this in mind, say nothing] The retry fix is in.",
    "[brain dump not sent] No session has that name.",
    "What is billing doing?",
])
def test_these_answer_something_the_user_just_did(text):
    assert not cv.is_update(text)


# ---------- the one exception: an approval about to go back to its terminal ----------

def urgent_script(secs_left: float) -> list:
    return [
        ("say", 0.0, "Lantern can deploy now or after the review. Which one?"),  # ends ~3.9 s
        ("voice", 6.0, 9.0), ("settling", 9.0, 12.0),  # "I think after the review, because…"
        ("permission", 7.0, secs_left),
        ("voice", 11.0, 13.0), ("settling", 13.0, 14.0),
        ("turn", 14.0, "After the review, noted.", 1.5),
    ]


def test_an_approval_about_to_time_out_waits_for_the_sentence_and_the_reply_and_only_then_cuts_in():
    sim = run("new", urgent_script(secs_left=40.0))
    start, kind, text, _ = sim.unsolicited()[0]
    reply_start = next(s[0] for s in sim.spoken[1:] if s[1] == "reply")
    reply_end = reply_start + len("After the review, noted.") / SPOKEN_CHARS_PER_SEC
    assert kind == "permission" and sim.over_the_user() == 0
    assert reply_end + cv.USER_GAP_SECS - STEP <= start < reply_end + cv.QUIET_GAP_SECS  # after the reply, ahead of the gap
    assert text.startswith("One urgent thing. ")


def test_an_approval_with_time_left_waits_for_the_gap_like_any_update():
    sim = run("new", urgent_script(secs_left=280.0))
    start, kind, text, _ = sim.unsolicited()[0]
    reply_end = 15.5 + len("After the review, noted.") / SPOKEN_CHARS_PER_SEC
    assert kind == "permission" and start >= reply_end + cv.QUIET_GAP_SECS - STEP and not text.startswith("One urgent")


def test_1_7_1_read_an_approval_out_over_the_users_answer():
    old = run("old", urgent_script(secs_left=280.0))
    assert old.unsolicited()[0][1] == "permission" and old.over_the_user() == 1


def test_urgent_never_starts_over_the_user_or_over_pointe():
    floor = cv.Floor()
    floor.user_started(10.0)
    assert floor.blocked(10.5, urgent=True) == "the user is speaking"
    floor.user_stopped(11.0)
    assert floor.blocked(11.5, urgent=True) == "the user is speaking"  # the last word is too fresh
    assert floor.blocked(13.0, pending=True, urgent=True) == "the user is speaking"  # the sentence is still settling
    assert floor.blocked(13.0, busy=True, urgent=True) == "Pointe is answering"
    assert floor.blocked(13.0, urgent=True) is None and floor.blocked(13.0) is not None


# ---------- concise by default ----------

LONG_EN = ("The retry fix is in and all 212 checks pass. It also cleaned up the backoff helper and renamed two functions. "
           "The lint job is still red on an unrelated file. Coverage went up by two points. Should it open the pull request?")
LONG_HE = ("התיקון ל-retry נכנס וכל 212 הבדיקות עוברות. הוא גם ניקה את פונקציית ה-backoff ושינה שני שמות. "
           "ה-lint עדיין אדום בקובץ אחר שלא קשור. הכיסוי עלה בשתי נקודות. לפתוח את ה-pull request?")


@pytest.mark.parametrize("said", [LONG_EN, LONG_HE])
def test_a_long_reply_is_sent_back_and_then_cut_in_code_keeping_the_closing_question(said):
    assert "Too long for speech" in cv.length_problem(said, cv.REPLY)
    cut = cv.trim(said, cv.REPLY)
    assert cv.length_problem(cut, cv.REPLY) is None
    assert len(cv.split_sentences(cut)) <= cv.REPLY.sentences and cv.count_words(cut) <= cv.REPLY.words
    assert cut.startswith(cv.split_sentences(said)[0]) and cut.endswith(cv.split_sentences(said)[-1])  # verdict, then the decision


@pytest.mark.parametrize("said,more", [
    ("The retry fix is in. All checks pass. The lint job is red on another file. Coverage went up two points.", cv.MORE_EN),
    ("התיקון נכנס. כל הבדיקות עוברות. ה-lint אדום בקובץ אחר. הכיסוי עלה בשתי נקודות.", cv.MORE_HE),
])
def test_a_cut_reply_without_a_question_says_there_is_more_and_does_not_ask(said, more):
    cut = cv.trim(said, cv.REPLY)
    assert cut.endswith(more) and not cv.asks(cut)  # an offer, not a question: it does not take the floor
    assert len(cv.split_sentences(cut[:-len(more)])) == cv.REPLY.sentences


@pytest.mark.parametrize("said", [
    "Yes, the deploy is green.", "כן, הדיפלוי ירוק.", "On it. I told billing to rerun the checks.", "",
    "Billing is waiting on your yes to merge. Docs and search are working.",
])
def test_a_short_reply_is_left_exactly_as_it_is(said):
    assert cv.length_problem(said, cv.REPLY) is None and cv.trim(said, cv.REPLY) == said


def test_one_sentence_that_is_too_long_on_its_own_is_cut_at_a_clause():
    said = ("The canary is holding at five percent with no new errors, the dashboards look flat, the queue depth is back "
            "under a hundred, the two alerts that fired this morning have cleared, and the on-call has signed off on moving ahead.")
    cut = cv.trim(said, cv.REPLY)
    assert cv.count_words(cut.replace(cv.MORE_EN, "")) <= cv.REPLY.words and cut.endswith(cv.MORE_EN)
    assert cut.startswith("The canary is holding at five percent with no new errors,")


@pytest.mark.parametrize("asked", [
    "tell me more", "Can you elaborate on that?", "give me the details", "explain why it failed", "walk me through it",
    "read me the full thing", "go on", "what exactly did it say", "more", "list them all",
    "תפרט", "תרחיב על זה", "ספר לי עוד", "תסביר למה זה נכשל", "בפירוט בבקשה", "תמשיך", "עוד", "מה בדיוק הוא אמר",
])
def test_these_ask_for_more_and_get_the_long_limit(asked):
    assert cv.wants_detail(asked) and cv.limit_for(asked, asked) is cv.DETAIL
    assert cv.length_problem(LONG_EN, cv.DETAIL) is None and cv.trim(LONG_EN, cv.DETAIL) == LONG_EN


@pytest.mark.parametrize("asked", [
    "is the deploy done", "what is billing doing", "yes", "send it", "why", "האם הדיפלוי הסתיים", "מה קורה עם billing",
    "כן", "תשלח", "tell billing to rerun the checks", "moreover it failed",
])
def test_these_get_the_short_limit(asked):
    assert not cv.wants_detail(asked) and cv.limit_for(asked, asked) is cv.REPLY


def test_the_limit_follows_what_started_the_turn():
    assert cv.limit_for(REPORT_BILLING, "tell me more") is cv.REPORT  # a report is not the answer to "tell me more"
    assert cv.limit_for("[search finished its turn, not the active session, and this is urgent] Say this", "") is cv.URGENT_REPORT
    assert cv.limit_for("what's going on", "what's going on", status=True) is cv.STATUS
    assert cv.limit_for("[voice connected] Active session: billing.", "") is cv.STATUS
    assert cv.limit_for("[permission answered] The user approved it.", "") is cv.REPLY
    assert cv.limit_for("[briefing, part 2 of 4]", "") is None and cv.limit_for("[switched by click] Say exactly this", "") is None
    assert cv.limit_for("anything", "anything", drive_words=25) == cv.Limit(words=25, sentences=2)
    answer = "[docs answered the user's question 'explain the failure'] Three causes."
    assert cv.limit_for(answer, "explain the failure in detail") is cv.DETAIL and cv.limit_for(answer, "why did it fail") is cv.REPORT
    assert cv.REPLY.words <= 30 and cv.REPLY.sentences == 2 and cv.REPLY.items == 3


@pytest.mark.parametrize("said,kept,rest", [
    ("Open right now: billing, docs, lantern, search and parser.", "billing, docs, lantern", "and 2 more"),
    ("Four sessions are waiting on you right now, billing, docs, lantern, search, and parser.", "billing, docs, lantern", "and 2 more"),
    ("פתוחים כרגע: billing, docs, lantern, search ו-parser.", "billing, docs, lantern", "ועוד 2"),
])
def test_a_spoken_list_stops_at_three_and_says_how_many_more(said, kept, rest):
    assert cv.list_items(said) == 5 and "more than 3 things" in cv.length_problem(said, cv.REPLY)
    cut = cv.trim(said, cv.REPLY)
    assert kept in cut and rest in cut and "search" not in cut and cv.list_items(cut) <= 4  # three names and the count


@pytest.mark.parametrize("said", [
    "Setup waits on your phone choice: the tunnel, the mesh, Wi-Fi only, or skip.",
    "What goes on screen: three screenshots, a live channel, a diagram, the terminal, or nothing?",
    "מה על המסך: שלושה צילומים, ערוץ חי, תרשים, הטרמינל, או כלום?",
])
def test_the_options_of_a_choice_are_never_cut(said):
    assert cv.list_items(said) == 0 and cv.trim(said, cv.REPLY) == said  # they are the question: all must be heard


def test_a_list_of_four_is_sent_back_to_the_model_but_not_cut_in_code():
    said = "Working now: billing, docs, lantern and search."
    assert "more than 3 things" in cv.length_problem(said, cv.REPLY)
    assert cv.trim(said, cv.REPLY) == said  # "and 1 more" would be no shorter than the fourth name


def test_numbered_points_stop_at_three_with_an_offer():
    said = "One: who attends. Two: what the lead owns. Three: what was built before. Four: the budget. Five: the dates."
    cut = cv.trim(said, cv.STATUS)
    assert cut == f"One: who attends. Two: what the lead owns. Three: what was built before. {cv.MORE_EN}"


@pytest.mark.parametrize("said", [
    "Yes, I see it, and it's working, so wait.",  # clauses, not a list
    "Billing, docs and lantern are working.",  # three is fine
    "It failed at 1,200 rows, 3,400 rows and 9,000 rows.",
    "The fix is in, but the lint job is red, so it waits on you.",
])
def test_these_are_not_long_lists(said):
    assert cv.list_items(said) <= 3 and cv.trim(said, cv.REPLY) == said


def test_a_list_is_said_whole_when_the_user_asked_for_all_of_it():
    said = "Open right now: billing, docs, lantern, search and parser."
    assert cv.trim(said, cv.limit_for("list them all", "list them all")) == said


# ---------- the brain: the limit, one reply per step, and no filler on a turn nobody asked for ----------

def _brain(monkeypatch, replies: list, limit=None, filler=None):
    import brain as brain_module

    spoken, steps = [], []

    async def speak(text, request_id=None):
        spoken.append(text)

    async def step(choice, instructions, messages, decls):
        steps.append([m.get("content") for m in messages if m["role"] == "user"][-1])
        calls = replies.pop(0)
        if isinstance(calls, float):
            await asyncio.sleep(calls)
            calls = replies.pop(0)
        calls = [calls] if isinstance(calls, str) else calls
        return SimpleNamespace(calls=[{"id": f"c{len(steps)}{i}", "name": "speak", "args": {"text": t}} for i, t in enumerate(calls)],
                               said="", raw=None, vendor="fake", usage={})

    monkeypatch.setattr(brain_module.vendors, "step", step)
    known = " ".join(t for r in replies if not isinstance(r, float) for t in ([r] if isinstance(r, str) else r))
    b = brain_module.Brain("fake:model", "instructions", [], lambda: f"[right now] {known}", speak, filler)  # nothing made up
    b.may_stay_silent = lambda: False  # the user asked something
    if limit:
        b.limit = limit
    return b, spoken, steps


def test_a_long_reply_is_refused_once_then_the_shorter_one_is_spoken(monkeypatch):
    b, spoken, steps = _brain(monkeypatch, [LONG_EN, "The retry fix is in and all checks pass. Open the pull request?"],
                              limit=lambda trigger, asked: cv.limit_for(trigger, asked))
    asyncio.run(b.turn("How did billing do?"))
    assert spoken == ["The retry fix is in and all checks pass. Open the pull request?"] and len(steps) == 2
    refusal = [m for m in b.messages if m["role"] == "tool"][0]["results"][0]["result"]
    assert "Too long for speech" in refusal["error"]


@pytest.mark.parametrize("asked,long", [("How did billing do?", LONG_EN), ("איך הלך ל-billing?", LONG_HE)])
def test_a_reply_still_too_long_after_one_retry_is_cut_in_code_not_retried_again(monkeypatch, asked, long):
    b, spoken, steps = _brain(monkeypatch, [long, long], limit=lambda trigger, asked: cv.limit_for(trigger, asked))
    asyncio.run(b.turn(asked))
    assert len(steps) == 2 and len(spoken) == 1  # the model does not get a third go: the user is waiting
    assert cv.length_problem(spoken[0], cv.REPLY) is None and spoken[0] == cv.trim(long, cv.REPLY)


@pytest.mark.parametrize("asked", ["Tell me more about how billing did.", "תפרט איך הלך ל-billing"])
def test_asked_to_elaborate_the_same_reply_is_spoken_whole(monkeypatch, asked):
    b, spoken, steps = _brain(monkeypatch, [LONG_EN], limit=lambda trigger, asked: cv.limit_for(trigger, asked))
    asyncio.run(b.turn(asked))
    assert spoken == [LONG_EN] and len(steps) == 1


def test_a_report_gets_the_report_limit_whatever_the_user_asked_before(monkeypatch):
    report = ("Billing: the retry fix is in. All 212 checks pass. The lint job is red on another file. Coverage rose two "
              "points. It wants your yes to open the pull request.")
    b, spoken, _ = _brain(monkeypatch, ["Sure, here is all of it."] + [report, report],
                          limit=lambda trigger, asked: cv.limit_for(trigger, asked))

    async def run():
        await b.turn("tell me more")
        await b.turn(REPORT_BILLING)
    asyncio.run(run())
    assert len(cv.split_sentences(spoken[1].replace(cv.MORE_EN, ""))) <= cv.REPORT.sentences


def test_two_speak_calls_in_one_step_are_one_reply_the_last(monkeypatch):
    b, spoken, _ = _brain(monkeypatch, [["Sorry, the routing was mine, and I can switch if you like. Want me to?",
                                         "Sorry about the routing. Want me to switch to docs?"]])
    asyncio.run(b.turn("You sent that to the wrong session."))
    assert spoken == ["Sorry about the routing. Want me to switch to docs?"]


def test_no_filler_and_no_say_that_again_on_a_turn_the_user_did_not_start(monkeypatch):
    import brain as brain_module

    fillers = []

    async def filler():
        fillers.append(True)

    monkeypatch.setattr(brain_module, "FILLER_AFTER_SECS", 0.05)
    b, spoken, _ = _brain(monkeypatch, [0.15, "Billing finished: all checks pass."], filler=filler)
    asyncio.run(b.turn(REPORT_BILLING))  # the model is slow on a report: the user asked nothing and hears no "one sec"
    assert spoken == ["Billing finished: all checks pass."] and not fillers
    b, spoken, _ = _brain(monkeypatch, [0.15, "The deploy is green."], filler=filler)
    asyncio.run(b.turn("Is the deploy green?"))  # the user is waiting: the filler still comes
    assert fillers == [True]
    b, spoken, _ = _brain(monkeypatch, [[]], filler=filler)
    asyncio.run(b.turn(REPORT_DOCS))  # the model returned nothing on a report: nothing to ask the user to repeat
    assert spoken == []
    b, spoken, _ = _brain(monkeypatch, [[]], filler=filler)
    asyncio.run(b.turn("Is the deploy green?"))
    assert spoken == ["Sorry, I lost that. Say it again?"]


@pytest.mark.parametrize("said,kept", [
    ("I sent your yes to billing. I'll read it out when it arrives.", "I sent your yes to billing."),
    ("Noted and sent to docs. Waiting on its next question.", "Noted and sent to docs."),
    ("I asked search. I'll let you know when it answers.", "I asked search."),
    ("שלחתי ל-billing. אעדכן אותך כשזה יגיע.", "שלחתי ל-billing."),
    ("I'll let you know.", "I'll let you know."),  # alone, it is the whole reply
    ("Billing is waiting on your yes to merge.", "Billing is waiting on your yes to merge."),
])
def test_a_closing_promise_to_report_later_is_dropped(said, kept):
    from brain import without_closer

    assert without_closer(said) == kept


# ---------- the daemon: the real injector, the real floor, small clocks ----------

@pytest.fixture
def call(d, monkeypatch):  # noqa: F811
    """A call with the real FeedInjector; what it asks the voice to say is recorded instead of spoken."""
    from pipecat.frames.frames import InputTextRawFrame

    monkeypatch.setattr(cv, "USER_GAP_SECS", 0.05)
    monkeypatch.setattr(cv, "QUIET_GAP_SECS", 0.4)
    monkeypatch.setattr(cv, "QUESTION_FLOOR_SECS", 1.5)
    monkeypatch.setattr(d, "UPDATE_POLL_SECS", 0.02)
    monkeypatch.setattr(d, "REPLY_WAIT_SECS", 0.1)
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    asked = []
    box = SimpleNamespace(asked=asked, d=d)

    async def push(frame, direction=None):
        if isinstance(frame, InputTextRawFrame):
            asked.append((time.time(), frame.text))

    def start():
        injector = d.FeedInjector()
        monkeypatch.setattr(injector, "push_frame", push)
        d.state.conn = SimpleNamespace(injector=injector, ptt=None)
        d.state.floor = cv.Floor()
        box.injector = injector
        return injector

    async def bot(text: str, secs: float = 0.1):
        """Pointe says this: the words go to the mouth, the sound plays for `secs`, then it stops."""
        from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
        from pipecat.processors.frame_processor import FrameDirection

        d.state.floor.said(text, time.time())
        await box.injector.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(secs)
        await box.injector.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    box.start, box.bot = start, bot
    return box


def test_on_the_call_reports_that_arrive_mid_answer_come_after_it_as_one_turn(call):
    d = call.d  # noqa: F811

    async def run():
        injector = call.start()
        await call.bot("The index rebuild can run tonight or wait. Which do you want?")
        asked_at = time.time()
        d.state.floor.user_started(time.time())  # the user starts to answer
        await injector.inject(REPORT_BILLING, True)
        await injector.inject(REPORT_DOCS, True)
        await asyncio.sleep(0.3)
        assert call.asked == [] and injector.queued == 2  # nothing while they talk
        d.state.floor.user_stopped(time.time())
        d.state.settling = True  # a thinking pause: the sentence is not a turn yet
        await asyncio.sleep(0.6)
        assert call.asked == []  # 1.7.1 spoke here, 1.2 s after the last sound
        d.state.settling = False
        d.state.floor.user_turn(time.time())  # the turn is taken; Pointe answers it
        await call.bot("Waiting for the release, then.")
        answered_at = time.time()
        assert call.asked == []
        await asyncio.sleep(1.0)
        assert len(call.asked) == 1 and not injector.queued  # one turn for both
        at, text = call.asked[0]
        assert at - answered_at >= cv.QUIET_GAP_SECS - 0.05 and at > asked_at
        assert text.startswith("[updates: 2 ") and "billing" in text and "docs" in text

    asyncio.run(run())


def test_on_the_call_one_report_alone_is_said_as_it_came_and_at_once_when_nobody_talks(call):
    async def run():
        injector = call.start()
        await injector.inject(REPORT_BILLING, True)
        await asyncio.sleep(0.15)
        assert [text for _, text in call.asked] == [REPORT_BILLING]

    asyncio.run(run())


def test_on_the_call_an_open_question_holds_a_report_until_the_timeout(call):
    async def run():
        injector = call.start()
        await call.bot("Should search rebuild tonight?")
        await injector.inject(REPORT_BILLING, True)
        await asyncio.sleep(1.0)
        assert call.asked == []  # the floor is the user's
        await asyncio.sleep(0.9)
        assert [text for _, text in call.asked] == [REPORT_BILLING]

    asyncio.run(run())


def test_on_the_call_a_reply_the_user_asked_for_is_not_queued_behind_the_floor(call):
    async def run():
        injector = call.start()
        await call.bot("Should search rebuild tonight?")
        await injector.inject("[permission answered] The user approved it. Acknowledge in two or three words.", True)
        await asyncio.sleep(0.3)
        assert [text for _, text in call.asked] == ["[permission answered] The user approved it. Acknowledge in two or three words."]

    asyncio.run(run())


def test_on_the_call_an_update_the_user_talked_over_before_it_was_heard_comes_back(call):
    from pipecat.frames.frames import InputTextRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    d = call.d  # noqa: F811

    async def run():
        injector = call.start()
        await injector.inject(REPORT_BILLING, True)
        await asyncio.sleep(0.1)
        assert len(call.asked) == 1  # handed to the voice, not yet heard
        d.state.floor.user_turn(time.time())  # the user speaks first: the brain drops what it was about to say
        await injector.process_frame(InputTextRawFrame(text="Hang on, what about the deploy?"), FrameDirection.DOWNSTREAM)
        assert injector.queued == 1
        await call.bot("The deploy is green.")
        await asyncio.sleep(0.8)
        assert [text for _, text in call.asked if text.startswith("[billing")] == [REPORT_BILLING, REPORT_BILLING]

    asyncio.run(run())


def test_on_the_call_the_read_out_waits_for_the_users_sentence_and_cuts_in_only_when_it_is_about_to_time_out(call, monkeypatch):
    d = call.d  # noqa: F811
    read = []

    async def read_out(session, unsure=False, early=False, urgent=False):
        read.append((time.time(), urgent))

    monkeypatch.setattr(d, "_read_out", read_out)
    monkeypatch.setattr(d, "online", lambda s: True)

    async def run(left: float):
        read.clear()
        call.start()
        session = add(d, "s1", "billing")
        d.REGISTRY.active_id = "s1"
        session.permission_id, session.permission_since = "p1", time.time() - (d.harnesses.of(session).permission_deadline - left)
        await call.bot("Lantern can deploy now or later. Which one?")
        d.state.floor.user_started(time.time())
        task = asyncio.create_task(d._read_out_when_quiet(session, "p1"))
        await asyncio.sleep(0.3)
        assert read == []  # never over the user, urgent or not
        d.state.floor.user_stopped(time.time())
        stopped = time.time()
        await asyncio.sleep(0.5)
        await asyncio.wait_for(task, 3.0)
        return read[0][0] - stopped, read[0][1]

    waited, urgent = asyncio.run(run(left=30.0))
    assert urgent and waited < 0.5  # about to go back to the terminal: right after the sentence
    waited, urgent = asyncio.run(run(left=200.0))
    assert not urgent and waited >= cv.QUESTION_FLOOR_SECS - 0.1  # time left: the question keeps the floor


def test_a_request_is_read_out_once_and_not_by_a_mode_that_does_not_read_out(call, monkeypatch):
    d = call.d  # noqa: F811
    read = []

    async def read_out(session, unsure=False, early=False, urgent=False):
        read.append(urgent)

    monkeypatch.setattr(d, "_read_out", read_out)
    monkeypatch.setattr(d, "online", lambda s: True)

    async def run():
        call.start()
        session = add(d, "s1", "billing")
        d.REGISTRY.active_id = "s1"
        session.permission_id, session.permission_since = "p1", time.time()
        d.state.floor.user_started(time.time())
        both = [asyncio.create_task(d._read_out_when_quiet(session, "p1")) for _ in range(2)]  # asked twice
        await asyncio.sleep(0.1)
        d.state.floor.user_stopped(time.time())
        await asyncio.wait_for(asyncio.gather(*both), 3.0)
        assert read == [False]
        read.clear()
        d.state.hold = d.turns.Hold(since=time.time(), said=[], last_at=time.time())  # "don't interrupt me"
        await asyncio.wait_for(d._read_out_when_quiet(session, "p1"), 1.0)
        assert read == []  # the hold's end asks again (_after_quiet)

    asyncio.run(run())


def test_updates_queued_when_the_call_ends_are_dropped_with_it(call):
    d = call.d  # noqa: F811

    async def run():
        injector = call.start()
        d.state.floor.user_started(time.time())
        await injector.inject(REPORT_BILLING, True)
        assert injector.queued == 1
        injector.call_over()
        await asyncio.sleep(0.2)
        assert injector.queued == 0 and call.asked == [] and injector._deliverer.cancelled()

    asyncio.run(run())


def test_the_floor_is_fed_by_the_call(d, monkeypatch):  # noqa: F811
    """The user's turn closes Pointe's question, and Pointe's own words open one."""
    async def run():
        d.state.floor.said("Which one?", time.time())
        assert d.state.floor.question
        await d.on_user_utterance("The second one.")
        assert not d.state.floor.question and d.state.floor.user_turn_at > 0

    asyncio.run(run())


def test_the_prompts_ask_for_the_same_limits_the_code_enforces(d):  # noqa: F811
    import brief

    assert f"under {cv.REPLY.words} words" in d.BRAIN_RULES and "tell me more" in d.BRAIN_RULES
    assert "three" in d.BRAIN_RULES and "never follow your own question" in d.INSTRUCTIONS
    assert f"at most {cv.REPORT.words} words" in brief.REPORT_SYSTEM and f"up to {cv.URGENT_REPORT.words} words" in brief.REPORT_SYSTEM
