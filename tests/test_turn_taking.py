"""Turn taking (docs/design/turn-taking.md): the settle time after a final transcript, the wider unfinished-sentence
check, the hold ("don't interrupt me"), the setting, and its parity between the page and the app. Offline: the harness
replays transcripts as Soniox delivers them, with the pauses a speaker left; no audio, no vendor.

uv run --locked pytest -q tests/test_turn_taking.py -s   (prints the premature-cutoff table)
"""

import asyncio
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import page_rig  # noqa: E402
import turns  # noqa: E402
from guards import unfinished  # noqa: E402
from test_orchestrator import client_for, d  # noqa: E402,F401  (d is the daemon fixture)

ROOT = Path(__file__).resolve().parents[1]

# ---------- the offline premature-cutoff harness ----------

# One utterance the speaker meant as one turn, as Soniox's endpoint cuts it: (final text, seconds of silence after it).
# The last segment ends the turn; its silence is what the speaker leaves before expecting an answer.
# Synthetic: invented projects, no one's real words.
CASES = [
    # English, a pause after a content word (reads complete): the common cut-off from live use
    [("Let's look at the parser.", 0.8), ("And see why it fails on empty input.", 2.0)],
    [("The retry loop is wrong.", 0.9), ("Because it has no backoff.", 2.0)],
    [("Run the tests.", 0.7), ("And then open the failing one.", 2.0)],
    [("Rename the module to billing.", 0.9), ("Then update the imports.", 2.0)],
    [("Check the nightly export.", 0.8), ("It took forty minutes yesterday.", 2.0)],
    [("Ask the notes session about the launch date.", 0.9), ("And whether marketing agreed.", 2.0)],
    [("I want to ship this today.", 0.8), ("So keep the change small.", 2.0)],
    [("Start with the migration.", 0.7), ("The schema part only.", 2.0)],
    [("The dashboard is slow.", 0.9), ("Mostly on the first load.", 2.0)],
    [("Deploy to staging.", 0.8), ("Not production.", 2.0)],
    # English, a pause after a dangling word or filler (reads unfinished)
    [("I want you to.", 0.7), ("Refactor the parser.", 2.0)],
    [("The thing I keep forgetting to check is the", 1.2), ("staging migration for the billing tables.", 2.0)],
    [("Can you remind me what the difference is between", 1.4), ("a mutex and a semaphore?", 2.0)],
    [("Before lunch I want to look at", 1.0), ("why the nightly export job is slow.", 2.0)],
    [("So basically,", 0.9), ("the retry loop never gives up.", 2.0)],
    [("And then", 1.1), ("it writes the report twice.", 2.0)],
    [("It fails when", 0.8), ("the input is empty.", 2.0)],
    [("Move the tests, which", 0.9), ("are flaky anyway, to a separate job.", 2.0)],
    [("I mean", 1.0), ("the whole module is a mess.", 2.0)],
    [("Do it after", 0.9), ("the deploy finishes.", 2.0)],
    [("Kind of", 0.8), ("like the old queue did.", 2.0)],
    [("It is not very", 0.9), ("clear what the flag does.", 2.0)],
    [("Send it to billing, or maybe", 1.2), ("to the notes session.", 2.0)],
    [("Rather than", 0.8), ("rewriting it, add a test first.", 2.0)],
    [("Hmm.", 1.3), ("Try the other branch.", 2.0)],
    # English, three pieces
    [("So the checkout keeps timing out.", 0.8), ("I think it's the retry loop.", 0.9), ("Five retries, no backoff.", 2.0)],
    [("Open the parser.", 0.7), ("The one in the ingest folder.", 0.8), ("And show me the tokenizer.", 2.0)],
    [("First the schema.", 0.9), ("Then the backfill.", 0.9), ("Then tell me what broke.", 2.0)],
    [("We need two things.", 0.8), ("A test for the empty case.", 0.9), ("And a log line when it retries.", 2.0)],
    [("Ask it to", 0.7), ("list the open pull requests.", 0.8), ("Only the ones from this week.", 2.0)],
    # Hebrew, a pause after a content word
    [("תריץ את הבדיקות.", 0.8), ("ואז תפתח את זאת שנפלה.", 2.0)],
    [("הדשבורד איטי.", 0.9), ("בעיקר בטעינה הראשונה.", 2.0)],
    [("תעלה לסטייג'ינג.", 0.8), ("לא לפרודקשן.", 2.0)],
    [("תשנה את השם של המודול.", 0.9), ("ותעדכן את הייבואים.", 2.0)],
    [("אני רוצה לשחרר את זה היום.", 0.8), ("אז תשמור על שינוי קטן.", 2.0)],
    [("תבדוק את הייצוא הלילי.", 0.9), ("לקח ארבעים דקות אתמול.", 2.0)],
    [("תתחיל מהמיגרציה.", 0.7), ("רק החלק של הסכמה.", 2.0)],
    [("הלופ של הניסיונות החוזרים שגוי.", 0.9), ("כי אין בו השהיה.", 2.0)],
    # Hebrew, a pause after a dangling word or filler
    [("אני רוצה שאתה", 0.8), ("תבדוק את הטסטים.", 2.0)],
    [("אני רוצה לבדוק את", 1.0), ("המיגרציה של הבילינג.", 2.0)],
    [("תעשה את זה אחרי", 0.9), ("שהדיפלוי נגמר.", 2.0)],
    [("זה נופל כש", 0.8), ("הקלט ריק.", 2.0)],
    [("אבל", 1.1), ("כל המודול הזה בלגן.", 2.0)],
    [("בעצם", 1.0), ("עדיף להוסיף טסט קודם.", 2.0)],
    [("תשלח את זה לבילינג או", 1.2), ("לסשן של ההערות.", 2.0)],
    [("כאילו", 0.9), ("כמו שהתור הישן עשה.", 2.0)],
    [("אה,", 1.0), ("תנסה את הענף השני.", 2.0)],
    [("קודם הסכמה.", 0.9), ("ואז המילוי לאחור.", 0.9), ("ואז תגיד לי מה נשבר.", 2.0)],
]
# Whole sentences said as one piece: these must not wait long, whatever the level.
WHOLE = ["Run the tests.", "What's the difference between a mutex and a semaphore?", "Deploy it to staging and tell me when it is up.",
         "Yes.", "No, stop.", "תריץ את הבדיקות", "כן", "מה השעה בניו יורק?"]

# Today's policy, frozen here so the harness keeps measuring it after the rules move on (daemon.py at 1.4.0:
# HOLD_UNFINISHED_SECS = 2.5, no wait for a sentence that reads complete, this word list in guards.unfinished).
_OLD_DANGLING = {"a", "an", "the", "and", "or", "but", "so", "because", "if", "than", "between", "whether", "my", "your", "our",
                 "their", "um", "uh", "של", "את", "עם", "בין", "או", "כי", "אז", "ש", "ו", "ה", "ל", "ב", "מ", "כמו", "אם"}
_OLD_OUTSIDE_QUESTIONS = {"to", "at", "of", "for", "with", "about", "from", "into", "like", "is", "are", "was", "were", "על", "גם"}
_OLD_QUESTION = re.compile(r"\b(what|where|who|whom|which|when|why|how|whose)\b|\?|\b(מה|איפה|מי|מתי|למה|איך|איזה)\b")


def _old_unfinished(text: str) -> bool:
    stripped = text.strip()
    if re.search(r"(—|–|-|…|\.\.\.|,)$", stripped):
        return True
    words = re.findall(r"[\w']+", stripped.lower())
    return bool(words) and (words[-1] in _OLD_DANGLING or words[-1] in _OLD_OUTSIDE_QUESTIONS
                            and not _OLD_QUESTION.search(stripped.lower()))


def old_settle(text: str, held: bool) -> float:
    return 2.5 if _old_unfinished(text) else 0.0


def new_settle(level):
    return lambda text, held: turns.settle(text, held, level)


def premature_cuts(policy) -> list[str]:
    """Replays each case: a segment that settles before the next piece arrives was answered too early."""
    cut = []
    for case in CASES:
        held = ""
        for i, (text, silence) in enumerate(case):
            joined = f"{held} {text}".strip() if held else text
            if i == len(case) - 1:
                break
            if policy(joined, bool(held)) <= silence:
                cut.append(joined)
                break
            held = joined
    return cut


def whole_delays(policy) -> list[float]:
    return [policy(text, False) for text in WHOLE]


def test_the_harness_shows_todays_values_cut_people_off_and_normal_does_not(capsys):
    rows = [("today (1.4.0)", old_settle)] + [(level, new_settle(level)) for level in turns.LEVELS]
    table = {name: (premature_cuts(p), max(whole_delays(p))) for name, p in rows}
    with capsys.disabled():
        print(f"\n{'policy':14} {'premature cuts':>16} {'whole-sentence wait':>22}")
        for name, (cuts, wait) in table.items():
            print(f"{name:14} {len(cuts):>7} / {len(CASES):<6} {wait:>19.1f} s")
    today = table["today (1.4.0)"][0]
    assert len(today) >= len(CASES) // 3, today  # the complaint, reproduced: a third or more of these turns are cut
    assert table["normal"][0] == [], table["normal"][0]
    assert table["patient"][0] == []
    assert len(table["quick"][0]) < len(today)  # quick trades some of this back for speed, never below today
    assert all(wait <= 2.0 for _, wait in table.values())  # a whole sentence is never held past two seconds
    assert all(turns.settle(text, False, "patient") == 0.0 for text in ("Yes.", "No, stop.", "כן"))  # answers never wait


def test_each_level_is_more_patient_than_the_one_before_and_normal_is_more_patient_than_today():
    quick, normal, patient = (turns.LEVELS[k] for k in ("quick", "normal", "patient"))
    for a, b in ((quick, normal), (normal, patient)):
        assert a.complete < b.complete and a.unfinished < b.unfinished and a.maximum < b.maximum
    assert normal.complete >= 1.0 and normal.unfinished > 2.5  # noticeably more patient than 1.4.0 (0 and 2.5)
    assert turns.DEFAULT_LEVEL == "normal"
    assert turns.settle("Run the tests.", False, "no-such-level") == normal.complete  # an unknown level is Normal


def test_a_short_answer_waits_only_when_it_continues_something_held():
    assert turns.settle("yes", False, "normal") == 0.0
    assert turns.settle("the parser", True, "normal") == turns.LEVELS["normal"].complete  # "I want you to" + "the parser"
    assert turns.settle("and then", False, "normal") == turns.LEVELS["normal"].unfinished  # two words, but dangling


# ---------- the unfinished-sentence check, in both languages ----------

@pytest.mark.parametrize("text", [
    "Let me check the parser, which", "It fails when", "Do it after", "I mean", "You know", "Kind of", "and then",
    "It is not very", "or maybe", "rather than", "Basically.", "Also.", "Hmm", "as soon as", "Send it to billing, or maybe",
    "the thing is that it works while", "Fix it before", "Try this also", "my", "Deploy it, but",
    "אבל", "ואז", "כאילו", "בעצם", "תעשה את זה אחרי", "זה נופל כש", "אני רוצה שאתה", "בגלל", "אה,", "לגבי", "כדי", "מה ש",
])
def test_these_read_unfinished(text):
    assert unfinished(text), text


@pytest.mark.parametrize("text", [
    "Run the tests.", "Of course not.", "Not really.", "Me neither.", "Tell me more.", "Me too.", "Do that.", "Is it done?",
    "Where is the parser?", "Who did you send it to", "What are you looking at?", "Which one failed?", "When does it run?",
    "What do you like?", "Deploy it to staging and tell me when it is up.", "yes", "Stop.", "That's it.", "Go ahead.",
    "תריץ את הבדיקות", "כן", "זה הכל", "מה אתה חושב?", "מה השעה בניו יורק?", "תעשה את זה", "לא", "סיימתי",
])
def test_these_read_finished(text):
    assert not unfinished(text), text


# ---------- hold: "don't interrupt me" ----------

@pytest.mark.parametrize("said", [
    "Hold on.", "Hang on", "Don't interrupt me.", "Please don't interrupt me", "Don't cut me off", "Let me finish.",
    "Let me finish my thought", "Let me talk", "Wait, I'm not done.", "I'm not finished yet", "Not done yet", "Give me a second.",
    "One sec", "Just a moment", "Wait till I'm done", "Okay, don't interrupt",
    "אל תפריע לי", "אל תקטע אותי", "תן לי לסיים", "תן לי לדבר", "עוד לא סיימתי", "לא סיימתי", "חכה רגע", "חכה שאסיים",
    "רק שנייה", "שנייה", "רגע אחד", "תן לי רגע", "אל תענה עדיין",
])
def test_these_ask_for_a_hold(said):
    assert turns.hold_intent(said), said


@pytest.mark.parametrize("said", [
    "Don't interrupt the deploy while the tests run", "Hold on to the old version until the migration is done",
    "Let me finish the migration first and then we deploy", "Give me a second opinion on the schema",
    "Wait for the build to finish and then run the tests", "One second is too slow for the health check",
    "I'm not done with the parser, it still fails on empty input, so add a test for that case first",
    "Can you hold on the queue and let the workers drain", "אל תפריע לדיפלוי", "תן לי לסיים את המיגרציה קודם",
    "חכה שהבילד ייגמר ואז תריץ את הבדיקות", "Run the tests.", "yes",
])
def test_these_are_not_a_hold(said):
    assert not turns.hold_intent(said), said


@pytest.mark.parametrize("said", [
    "I'm done.", "Done", "I'm finished", "That's it.", "That's all", "Go ahead.", "Over.", "Over to you", "Your turn",
    "You can answer now", "Okay, what do you think?", "Thoughts?", "So that's the whole plan, go ahead.",
    "סיימתי", "זה הכל", "זהו", "קדימה", "תורך", "עכשיו אתה", "אתה יכול לדבר", "תענה", "מה אתה חושב?", "מה דעתך", "נו",
])
def test_these_release_a_hold(said):
    assert turns.release_intent(said), said


@pytest.mark.parametrize("said", [
    "I'm done with the parser but the tokenizer still fails", "Go ahead and run the tests after the build",
    "It's over there in the ingest folder", "What do you think the customer wants from the checkout redesign here",
    "and the second thing is the retry loop", "סיימתי עם הפרסר אבל הטוקנייזר עדיין נופל", "קדימה תריץ את הבדיקות",
    "The thing I keep forgetting to check is the staging migration and whether the billing tables are done",
])
def test_these_are_hold_content(said):
    assert not turns.release_intent(said), said


def test_the_words_before_the_hold_phrase_are_kept():
    assert turns.before_hold("I want to talk about the parser, hold on.") == "I want to talk about the parser"
    assert turns.before_hold("אני רוצה לדבר על הפרסר, אל תפריע לי") == "אני רוצה לדבר על הפרסר"
    assert turns.before_hold("Okay, hold on.") == ""  # a lead-in is not content
    assert turns.before_hold("Don't interrupt me") == ""


def test_the_hold_silence_release_is_between_eight_and_ten_seconds():
    assert 8.0 <= turns.HOLD_RELEASE_SILENCE_SECS <= 10.0


def test_hold_is_a_mode_that_narrows_conversation():
    import modes

    assert modes.HOLD in modes.ALL and modes.narrows(modes.HOLD)
    assert modes.HOLD.speech == "never" and modes.HOLD.holds_news and modes.HOLD.approvals == "tap"


# ---------- the daemon: a hold on the call, and the setting ----------

def _ears(d, monkeypatch):
    import asyncio

    ears = d.SonioxEars()
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    return ears


def test_a_hold_on_the_call_stays_quiet_until_the_release_then_hands_over_everything(d, monkeypatch):
    import asyncio
    import time

    from pipecat.frames.frames import InputTextRawFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    pushed, cuts, flushed = [], [], []

    async def run():
        ears = _ears(d, monkeypatch)

        async def push(frame, direction=None):
            pushed.append(frame.text if isinstance(frame, InputTextRawFrame) else frame)
        monkeypatch.setattr(ears, "push_frame", push)

        async def cut():
            cuts.append(time.time())
        monkeypatch.setattr(ears, "broadcast_interruption", cut)

        async def after():
            flushed.append(True)
        monkeypatch.setattr(d, "_after_quiet", after)

        async def final(text):
            d.state.user_stopped_at = time.time()
            await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        await final("Hold on, let me finish.")
        assert d.state.hold is not None and cuts and d.current_mode() is d.modes.HOLD
        assert pushed == []  # the hold phrase itself is not a turn
        await final("So the checkout keeps timing out.")
        await asyncio.sleep(0.05)
        await final("I think it's the retry loop.")
        await asyncio.sleep(0.05)
        assert pushed == [] and d.state.hold.said == ["So the checkout keeps timing out.", "I think it's the retry loop."]
        assert client_status(d)["hold"]["said"].endswith("retry loop.")
        await final("Okay, what do you think?")
        assert d.state.hold is None and flushed
        assert pushed == ["So the checkout keeps timing out. I think it's the retry loop. Okay, what do you think?"]
        assert client_status(d)["hold"] is None

    asyncio.run(run())


def test_a_hold_releases_itself_after_the_long_silence(d, monkeypatch):
    import asyncio
    import time

    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setattr(d.turns, "HOLD_RELEASE_SILENCE_SECS", 0.4)
    pushed = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def push(frame, direction=None):
            pushed.append(frame.text)
        monkeypatch.setattr(ears, "push_frame", push)
        monkeypatch.setattr(ears, "broadcast_interruption", lambda: asyncio.sleep(0))

        async def after():
            pass
        monkeypatch.setattr(d, "_after_quiet", after)

        async def final(text):
            d.state.user_stopped_at = time.time()
            await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        await final("אל תפריע לי")
        await final("הצ'קאאוט נופל בטיים-אאוט.")
        await asyncio.sleep(0.25)
        assert d.state.hold is not None and pushed == []  # still quiet
        d.state.user_started_at = time.time()  # voicing again: the clock does not run while they talk
        await asyncio.sleep(0.4)
        assert d.state.hold is not None
        d.state.user_stopped_at = time.time()
        await asyncio.sleep(0.7)
        assert d.state.hold is None and pushed == ["הצ'קאאוט נופל בטיים-אאוט."]

    asyncio.run(run())


def test_a_complete_sentence_waits_for_the_level_s_silence_and_a_short_answer_does_not(d, monkeypatch):
    import asyncio
    import time

    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setitem(d.turns.LEVELS, "normal", d.turns.Patience(complete=0.3, unfinished=0.6, maximum=5.0))
    taken = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def take(text):
            taken.append((text, time.time()))
        monkeypatch.setattr(ears, "_take", take)

        async def final(text):
            d.state.user_stopped_at = time.time()
            await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        t0 = time.time()
        await final("Let's look at the parser.")
        assert taken == []  # complete, but it waits: the next piece may be coming
        await asyncio.sleep(0.15)
        await final("And see why it fails.")
        await asyncio.sleep(0.5)
        assert [t for t, _ in taken] == ["Let's look at the parser. And see why it fails."]
        assert taken[0][1] - t0 >= 0.4  # 0.15 of talking, then 0.3 of silence
        d.state.floor.said("Should it run the tests?", time.time())  # a question waits for its answer
        await final("Yes.")
        assert taken[-1][0] == "Yes."  # an answer to it never waits (test_short_answer_settle.py: only when one is awaited)
        monkeypatch.setitem(d.PREFS.values, "turns.patience", "quick")
        monkeypatch.setitem(d.turns.LEVELS, "quick", d.turns.Patience(complete=0.0, unfinished=0.2, maximum=5.0))
        await final("Run the tests.")
        assert taken[-1][0] == "Run the tests."  # Quick: as before this change

    asyncio.run(run())


def client_status(d) -> dict:
    return client_for(d).get("/voice/status").json()


def test_the_setting_round_trips_through_the_daemon_and_defaults_to_normal(d, monkeypatch):
    c = client_for(d)
    monkeypatch.setattr(d.PREFS, "values", dict(d.PREFS.values))  # this test's writes end with it
    assert c.get("/voice/prefs").json()["turns.patience"] == "normal"
    assert c.post("/voice/prefs", json={"turns.patience": "patient"}).status_code == 200
    assert c.get("/voice/prefs").json()["turns.patience"] == "patient" and d._patience() == "patient"
    assert c.post("/voice/prefs", json={"turns.patience": "sometimes"}).status_code == 400
    assert c.get("/voice/prefs").json()["turns.patience"] == "patient"
    import prefs as prefs_mod
    again = prefs_mod.Prefs(d.PREFS.path)  # persisted: a restart keeps it
    assert again.get("turns.patience") == "patient"


# ---------- parity: the page and the app offer the same setting, with the same words ----------

LEVEL_LABELS = {"quick": "Quick", "normal": "Normal", "patient": "Patient"}
SETTING_TITLE = "Wait before answering"


def test_the_page_offers_the_setting_and_saves_it():
    page = (ROOT / "pointe" / "ui.html").read_text()
    assert 'id="pref-patience"' in page and SETTING_TITLE in page
    for value, label in LEVEL_LABELS.items():
        assert f'<option value="{value}">{label}</option>' in page, value
    assert "'turns.patience': $('pref-patience').value" in page  # saved with the other settings
    assert "$('pref-patience').value = prefs['turns.patience'] || 'normal'" in page  # loaded from the daemon
    assert "Holding" in page  # the state pill while a hold is on


def test_the_app_offers_the_same_setting_with_the_same_words():
    api = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "API.swift").read_text()
    view = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "CallView.swift").read_text()
    view += (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "CallSettings.swift").read_text()  # the picker is in Settings (the ••• button)
    copy = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Turns.swift").read_text()
    assert '"turns.patience"' in api and "var patience: String" in api
    assert '"turns.patience"' in view and "TurnsCopy.setting" in view and f'static let setting = "{SETTING_TITLE}"' in copy
    for value, label in LEVEL_LABELS.items():
        assert f'("{value}", "{label}")' in copy, value
    page = re.search(r"const TURNS_COPY = \{holding: '(.*?)', holdingHow: '(.*?)'\};", (ROOT / "pointe" / "ui.html").read_text().replace("\\'", "'"))
    assert "let hold: Hold?" in api and "TurnsCopy.holding" in view and "TurnsCopy.holdingHow" in view
    assert f'static let holding = "{page.group(1)}"' in copy and f'static let holdingHow = "{page.group(2)}"' in copy


def test_the_levels_in_code_are_the_three_the_clients_offer():
    import prefs as prefs_mod

    assert tuple(turns.LEVELS) == prefs_mod.SCHEMA["turns.patience"][1] == tuple(LEVEL_LABELS)



def test_words_heard_live_but_not_yet_final_keep_the_sentence_before_them_from_being_taken_alone(d, monkeypatch):
    """From live runs on a busy Mac (tests/e2e/harness_matrix.py): "Ask lighthouse to run exactly one command." was taken
    as the turn and sent while "uname dash a, redirected into where.txt" was still on its way: the words had been heard
    live, but Soniox's final for them came more than the settle time after the last of them (it may take 2.5 s), and the
    settle counted only the silence. They arrived as a second turn, after the first had been acted on."""
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setitem(d.turns.LEVELS, "normal", d.turns.Patience(complete=0.3, unfinished=0.6, maximum=5.0))
    monkeypatch.setattr(d, "HEARING_SECS", 1.2)
    taken = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def take(text):
            taken.append(text)
        monkeypatch.setattr(ears, "_take", take)

        async def final(text):
            d.state.hearing = (0.0, "")
            await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)

        def live(words):  # what an interim transcript does
            d.state.user_heard_at = d.state.user_stopped_at = time.time()
            d.state.hearing = (d.state.user_heard_at, words)

        d.state.user_stopped_at = time.time()
        await final("Ask lighthouse to run exactly one command.")
        live("uname dash a, redirected into")
        await asyncio.sleep(0.7)  # past the settle: the final for those words is late
        assert taken == []
        await final("Uname dash a, redirected into where.txt.")
        await asyncio.sleep(0.5)
        assert taken == ["Ask lighthouse to run exactly one command. Uname dash a, redirected into where.txt."]

        d.state.user_stopped_at = time.time()
        await final("Then tell me what it printed.")
        live("and")  # a live word whose final never comes does not hold the turn for ever
        await asyncio.sleep(1.6)
        assert taken[-1] == "Then tell me what it printed."

    asyncio.run(run())


# ---------- the page ----------

@pytest.mark.skipif(not os.path.exists(page_rig.CHROME), reason="headless Chrome is not installed here")
def test_the_page_says_holding_on_its_own_call_while_a_hold_is_on():
    """The pill is the page's own call's: checked here on the stub Mac, since the live e2e's call is the test's."""
    async def run():
        status = page_rig.fixture(connected=True)
        status["hold"] = {"since": time.time() - 3, "said": ["the cache should live per merchant"]}
        stub = await page_rig.StubMac(page_rig.free_port()).start()
        stub.status = status
        async with page_rig.Browser() as browser:
            page = await browser.open(stub.url)
            await asyncio.sleep(1.0)
            await page.eval("(() => { call.state = 'live'; showState(); return true; })()")
            holding = await page.eval("[document.getElementById('state').textContent, document.getElementById('sub').textContent]")
            stub.status = {**status, "hold": None}
            await asyncio.sleep(1.2)
            await page.eval("(() => { call.state = 'live'; showState(); return true; })()")
            after = await page.eval("document.getElementById('state').textContent")
        await stub.stop()
        return holding, after

    holding, after = asyncio.run(run())
    assert holding == ["Holding", "Say “go ahead” when you're done"] and "Holding" not in after  # a short title; how to go on under it


# ---------- the settle counts the user's silence, not the transcript's lag ----------

def _settle_run(d, monkeypatch, clocked: bool, live_after: float | None = None) -> float:
    """Seconds from a final transcript to the turn, for a sentence whose sound ended 0.3 s before the final arrived."""
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setitem(d.turns.LEVELS, "normal", d.turns.Patience(complete=0.6, unfinished=1.2, maximum=5.0))
    taken = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def take(text):
            taken.append(time.time())
        monkeypatch.setattr(ears, "_take", take)
        now = time.time()
        ended = now - 0.3
        monkeypatch.setattr(d, "_spoken", lambda frame: (ended - 2.0, ended) if clocked else None)
        d.state.user_stopped_at = ended + d.VAD_STOP_SECS  # the voice detector's stamp comes after the sound ended
        d.state.user_heard_at = now - 0.05  # the last live word reached us just before its final did
        await d.SonioxEars.process_frame(ears, TranscriptionFrame(text="The retry loop has no backoff at all.", user_id="u",
                                                                  timestamp="t"), FrameDirection.DOWNSTREAM)
        if live_after is not None:
            await asyncio.sleep(live_after)
            d.state.user_heard_at = time.time()  # a new word, after the final: the user went on
        await asyncio.sleep(1.2)
        return taken[0] - now
    return asyncio.run(run())


def test_with_timed_words_the_settle_counts_from_the_end_of_the_sound(d, monkeypatch):
    """Measured on a live call: a 1.0 s settle took the turn 1.3 s after the last word, because it counted from the voice
    detector's stamp (0.2 s late by design) and from the arrival of the last live word (the network's lag)."""
    waited = _settle_run(d, monkeypatch, clocked=True)
    assert 0.25 <= waited < 0.45, waited  # 0.6 s of silence, 0.3 s of it already past when the final came


def test_a_word_heard_after_the_final_restarts_the_settle(d, monkeypatch):
    waited = _settle_run(d, monkeypatch, clocked=True, live_after=0.15)
    assert 0.7 <= waited < 0.95, waited  # 0.15 s to the new word, then the whole 0.6 s


def test_ears_without_word_times_keep_counting_from_the_stamps_as_they_came(d, monkeypatch):
    waited = _settle_run(d, monkeypatch, clocked=False)
    assert 0.5 <= waited < 0.75, waited  # from the live word's arrival, 0.05 s before the final


def test_the_voice_detector_is_built_with_the_stop_time_the_settle_takes_off():
    assert "VADParams(stop_secs=VAD_STOP_SECS)" in (ROOT / "pointe" / "daemon.py").read_text()
