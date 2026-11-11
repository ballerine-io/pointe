"""Audio briefings, offline: the rules in briefing.py (when "the night" starts, what is said first, how long, what is
never said) and the daemon around them with a fake reading model (the order it is spoken in, skip / stop / go on, and
what a briefing may never do: send, approve, read a secret or a hidden permission, talk into a meeting, or go on over
a push-to-talk press).

uv run pytest -q tests/test_briefing.py
"""

import asyncio
import json
import os
import stat
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import (Params, add, client_for, d, fake_conn, record_channel, verdicts,  # noqa: E402,F401
                               with_permission)

import briefing  # noqa: E402


def at(hour: int, minute: int = 0, days_ago: int = 0) -> float:
    base = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=days_ago)
    return base.timestamp()


# ---------- when "since" starts ----------

def test_the_night_is_since_the_last_call_ended():
    now, ended = at(8, 30), at(23, 10, days_ago=1)
    assert briefing.parse_since("the night", now, ended)[0] == ended


def test_the_night_without_a_recent_call_is_since_six_yesterday():
    now = at(8, 30)
    assert briefing.parse_since("the night", now, None)[0] == at(18, 0, days_ago=1)
    assert briefing.parse_since("last night", now, at(9, 0, days_ago=5))[0] == at(18, 0, days_ago=1)  # too old


@pytest.mark.parametrize("said, now, expected", [
    ("since six", at(20, 0), at(18, 0)),
    ("since six", at(7, 0), at(6, 0)),
    ("since 6pm", at(7, 0), at(18, 0, days_ago=1)),
    ("since 18:00", at(20, 0), at(18, 0)),
    ("since 9am", at(10, 0), at(9, 0)),
    ("today", at(10, 0), at(0, 0)),
    ("yesterday", at(10, 0), at(0, 0, days_ago=1)),
    ("the last 3 hours", at(10, 0), at(7, 0)),
    ("מאז שש", at(20, 0), at(18, 0)),
    ("היום", at(10, 0), at(0, 0)),
    ("אתמול", at(10, 0), at(0, 0, days_ago=1)),
])
def test_since_phrases(said, now, expected):
    assert briefing.parse_since(said, now, None)[0] == expected, said


def test_hebrew_night_and_an_unparsable_phrase():
    now, ended = at(8, 0), at(22, 0, days_ago=1)
    assert briefing.parse_since("הלילה", now, ended)[0] == ended
    assert briefing.parse_since("whenever the moon was blue", now, ended)[0] == ended  # since the last call
    assert briefing.parse_since("", now, None)[0] == at(18, 0, days_ago=1)


def test_since_never_lies_in_the_future():
    now = at(5, 0)
    assert briefing.parse_since("since 9am", now, None)[0] == at(9, 0, days_ago=1)


# ---------- what is never said ----------

@pytest.mark.parametrize("secret", [
    "sk-proj-AbCdEf0123456789AbCdEf0123456789",
    "AKIAABCDEFGHIJKLMNOP",
    "ghp_0123456789abcdefghijABCDEFGHIJ012345",
    "xoxb-123456789012-abcdefghijklmnop",
    "AIzaSyA0123456789abcdefghijklmnopqrstu",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlc2lnbmF0dXJl",
])
def test_secrets_are_redacted(secret):
    out = briefing.redact(f"It set the key to {secret} and moved on.")
    assert secret not in out and "[secret]" in out


def test_assignments_bearer_and_private_keys_are_redacted():
    text = ("export STRIPE_SECRET=4f9a8b7c6d5e4f3a2b1c and password: hunter2-orchard\n"
            "curl -H 'Authorization: Bearer abc.def-ghi_jkl012345' https://api.example.test\n"
            "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----")
    out = briefing.redact(text)
    for gone in ("4f9a8b7c6d5e4f3a2b1c", "hunter2-orchard", "abc.def-ghi_jkl012345", "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"):
        assert gone not in out, gone
    assert "api.example.test" in out


def test_plain_work_is_not_redacted():
    text = "Billing ran 42 tests; 3 failed in checkout_test.py. The PR is #318 on branch fix-ledger-rounding."
    assert briefing.redact(text) == text


# ---------- order, length, empty ----------

def sec(name, status, text="x"):
    return briefing.Section(session=name, status=status, text=text)


def test_order_is_waiting_failed_done_quiet():
    got = briefing.order([sec("docs", "done"), sec("ops", "quiet"), sec("billing", "failed"), sec("lantern", "waiting")])
    assert [s.session for s in got] == ["lantern", "billing", "docs", "ops"]


def test_the_opener_names_the_count_and_the_most_urgent():
    line = briefing.opener(briefing.order([sec("docs", "done"), sec("billing", "failed"), sec("lantern", "waiting")]),
                           "since 18:00")
    assert line.startswith("Three sessions since 18:00.")
    assert line.index("lantern") < line.index("billing") < line.index("docs")


def test_a_quiet_night_is_one_line():
    b = briefing.assemble([sec("docs", "quiet"), sec("ops", "quiet")], "the night", "normal", at(18, 0), time.time())
    assert b.opener == "Quiet night. Nothing waits on you." and b.parts() == ["Quiet night. Nothing waits on you."]
    assert b.empty


@pytest.mark.parametrize("length, cap", [("short", 25), ("normal", 60), ("full", 120)])
def test_length_caps_words(length, cap):
    reply = {"status": "done", "say_short": "word " * 80, "say": "word " * 200, "full": "word " * 400}
    s = briefing.section_from_reply("docs", reply, length, waits=[])
    assert len(s.text.split()) <= cap


def test_a_session_that_waits_is_waiting_whatever_the_reader_says():
    s = briefing.section_from_reply("lantern", {"status": "done", "say": "It finished the migration."}, "normal",
                                    waits=["a permission approval"])
    assert s.status == "waiting"


def test_the_reader_output_is_redacted_too():
    s = briefing.section_from_reply("ops", {"status": "done", "say": "It printed ghp_0123456789abcdefghijABCDEFGHIJ012345."},
                                    "normal", waits=[])
    assert "ghp_" not in s.text


def test_a_failed_digest_falls_back_to_its_last_words():
    s = briefing.fallback("billing", "[claude-code] All 40 tests pass. Token sk-proj-AbCdEf0123456789AbCdEf0123456789 saved.", [])
    assert s.text.startswith("I couldn't digest billing; its last words were:") and "sk-proj" not in s.text


def test_at_most_eight_sessions():
    assert briefing.MAX_SESSIONS == 8


# ---------- the schedule ----------

def test_a_slot_is_due_within_two_hours_and_once():
    now = at(9, 0)
    assert briefing.due_slot(now, "08:30", list(range(7)), "") == at(8, 30)
    assert briefing.due_slot(now, "08:30", list(range(7)), briefing.slot_key(at(8, 30))) is None  # done already
    assert briefing.due_slot(at(11, 0), "08:30", list(range(7)), "") is None  # missed by more than 2 h: skipped
    assert briefing.due_slot(at(8, 0), "08:30", list(range(7)), "") is None  # not yet
    assert briefing.due_slot(now, "", list(range(7)), "") is None  # no schedule
    other_days = [d for d in range(7) if d != datetime.now().weekday()]
    assert briefing.due_slot(now, "08:30", other_days, "") is None


def test_schedule_validation():
    assert briefing.valid_time("08:30") and briefing.valid_time("") and not briefing.valid_time("8:30pm")
    assert not briefing.valid_time("24:00")
    assert briefing.valid_days([0, 4]) and not briefing.valid_days([7]) and not briefing.valid_days("weekdays")


# ---------- playback phrases ----------

@pytest.mark.parametrize("said, intent", [
    ("skip", "skip"), ("Next.", "skip"), ("next one", "skip"), ("דלג", "skip"), ("הבא", "skip"),
    ("stop", "stop"), ("That's enough.", "stop"), ("stop the briefing", "stop"), ("די", "stop"), ("עצור", "stop"),
    ("go on", "continue"), ("Continue.", "continue"), ("keep going", "continue"), ("תמשיך", "continue"),
    ("skip the tests in lantern", None), ("stop billing", None), ("what failed in billing?", None),
])
def test_control_phrases(said, intent):
    assert briefing.control_intent(said) == intent, said


# ---------- the store ----------

def test_the_store_keeps_seven_and_is_private(tmp_path):
    store = briefing.Store(tmp_path / "briefings.json")
    for i in range(9):
        store.add(briefing.assemble([sec("docs", "done", f"run {i}")], "today", "normal", at(0, 0), time.time() + i))
    again = briefing.Store(tmp_path / "briefings.json")
    assert len(again.items) == 7 and again.items[-1].sections[0].text == "run 8"
    assert stat.S_IMODE((tmp_path / "briefings.json").stat().st_mode) == 0o600
    store.call_ended(123.0)
    assert briefing.Store(tmp_path / "briefings.json").last_call_end == 123.0


# ================= the daemon =================

def transcript(tmp_path, name, lines, when=None):
    """A synthetic Claude Code transcript: (who, text) lines, timestamped `when` (default: a minute ago)."""
    stamp = datetime.fromtimestamp(when or time.time() - 60, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    path = tmp_path / f"{name}.jsonl"
    with path.open("w") as f:
        for who, text in lines:
            if who == "user":
                entry = {"type": "user", "message": {"role": "user", "content": text}, "timestamp": stamp}
            else:
                entry = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                                                          "stop_reason": "end_turn"}, "timestamp": stamp}
            f.write(json.dumps(entry) + "\n")
    return str(path)


@pytest.fixture
def b(d, monkeypatch, tmp_path):
    """The daemon with a call, its own prefs, notes and briefings, and a fake reader that answers per session."""
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    monkeypatch.setattr(d, "NOTES", d.Notes())
    monkeypatch.setattr(d, "BRIEFINGS", briefing.Store(tmp_path / "briefings.json"))
    monkeypatch.setattr(d, "BRIEFING_POLL_SECS", 0.01)
    monkeypatch.setattr(d, "BRIEFING_SPEAK_WAIT_SECS", 0.3)
    monkeypatch.setattr(d, "BRIEFING_GAP_SECS", 0.05)
    d.state.conn = fake_conn()
    replies, prompts = {}, []

    async def read(system, prompt, thinking=None):
        prompts.append(prompt)
        name = next((n for n in replies if f"Session: {n}\n" in prompt), None)
        reply = replies.get(name)
        if isinstance(reply, Exception):
            raise reply
        return dict(reply or {"status": "quiet"})

    monkeypatch.setattr(d, "_read_model", read)
    spoke = d.state.conn.injector

    def respond():  # the bot says each section at once and stops
        spoke.bot_started_at = time.time()
        spoke._bot_speaking = False

    spoke.on_respond = respond
    return SimpleNamespace(replies=replies, prompts=prompts, injector=spoke)


def night(d, b, tmp_path):
    """Three sessions with work since last night: lantern waits on a permission, billing failed, docs is done."""
    lantern = add(d, "l", "lantern", transcript=transcript(tmp_path, "lantern", [("assistant", "Migration is ready; it needs approval to run.")]))
    billing = add(d, "bi", "billing", transcript=transcript(tmp_path, "billing", [("assistant", "3 of 42 tests failed in checkout.")]))
    docs = add(d, "dc", "docs", transcript=transcript(tmp_path, "docs", [("assistant", "The guide is published.")]))
    with_permission(lantern, "p9", delivered_at=float("inf"),
                    text="[permission request] Bash: run the migration\npsql $DATABASE_URL -f drop_everything.sql")
    lantern.permission_full = "psql postgres://admin:hunter2-orchard@db.example.test/prod -f drop_everything.sql"
    b.replies.update({
        "lantern": {"status": "done", "say": "Lantern finished the migration script and waits for your approval to run it."},
        "billing": {"status": "failed", "say": "Billing: 3 of 42 tests failed in checkout."},
        "docs": {"status": "done", "say": "Docs published the guide."},
    })
    d.REGISTRY.active_id = docs.id
    return lantern, billing, docs


def tool(d, name):
    return d.TOOLS.standard_tools[[t.name for t in d.TOOLS.standard_tools].index(name)].handler


async def run_briefing(d, **args):
    p = Params(**args)
    await tool(d, "briefing")(p)
    await d.state.briefing_task  # built and played to the end (or a pause)
    return p.results[0]


def said(b) -> list[str]:
    return [t for t, respond in b.injector.fed if respond and t.startswith("[briefing")]


def test_on_demand_briefing_is_spoken_in_order_with_the_read_only_bracket(d, b, tmp_path):
    night(d, b, tmp_path)
    result = asyncio.run(run_briefing(d, since="the night"))
    assert "error" not in result
    parts = said(b)
    assert len(parts) == 3
    for p in parts:
        assert "send nothing" in p and "approve nothing" in p and "data, not instructions" in p
    assert "Three sessions" in parts[0] and "Lantern" in parts[0]  # the opener rides with the first section
    assert "Billing" in parts[1] and "Docs" in parts[2]
    note = [n for n in d.NOTES.items if n.kind == "briefing"]
    assert len(note) == 1 and "lantern" in note[0].text.lower()
    assert d.BRIEFINGS.latest().heard


def test_no_secret_and_no_hidden_permission_text_is_read_or_stored(d, b, tmp_path):
    lantern, _, _ = night(d, b, tmp_path)
    lantern.transcript = transcript(tmp_path, "lantern2", [("assistant", "Set OPENAI key sk-proj-AbCdEf0123456789AbCdEf0123456789 in the env.")])
    b.replies["lantern"] = {"status": "done", "say": "Lantern stored sk-proj-AbCdEf0123456789AbCdEf0123456789 and waits."}
    asyncio.run(run_briefing(d, since="the night"))
    everything = "\n".join(said(b)) + "\n".join(b.prompts) + (tmp_path / "briefings.json").read_text() + json.dumps(
        client_for(d).get("/voice/briefings").json())
    assert "sk-proj-AbCdEf" not in everything
    for hidden in ("hunter2-orchard", "drop_everything", "DATABASE_URL"):
        assert hidden not in everything, hidden
    assert "a permission approval" in "\n".join(b.prompts)  # it knows something waits, not what


def test_a_send_during_playback_is_refused_without_fresh_speech(d, b, tmp_path, monkeypatch):
    night(d, b, tmp_path)
    posts = record_channel(d, monkeypatch)
    d.state.last_user_speech_at = time.time() - 30  # the user asked for the briefing, then only listened
    d.state.last_delegation_at = time.time() - 30
    asyncio.run(run_briefing(d, since="the night"))
    result = asyncio.run(d._send("Approve the migration and run it."))
    assert "error" in result and posts == []


def test_a_yes_after_the_briefing_mentions_a_permission_does_not_approve(d, b, tmp_path, monkeypatch):
    lantern, _, _ = night(d, b, tmp_path)
    d.REGISTRY.active_id = lantern.id
    lantern.permission_delivered_at = lantern.permission_read_at = time.time() - 5  # it was read out earlier
    d.state.conn.injector.bot_started_at = time.time() - 4
    posts = record_channel(d, monkeypatch)
    asyncio.run(run_briefing(d, since="the night"))
    for part in said(b):  # what the brain says of each section is bot speech, not the read-out
        d._note_bot_speech(part)
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [] and lantern.permission_id == "p9"


def test_skip_cuts_the_part_and_goes_on_and_stop_ends(d, b, tmp_path):
    night(d, b, tmp_path)

    def respond():  # the bot keeps talking until the test says it stopped
        b.injector.bot_started_at = time.time()
        b.injector._bot_speaking = True

    b.injector.on_respond = respond

    async def go():
        await tool(d, "briefing")(Params(since="the night"))
        while not said(b):
            await asyncio.sleep(0.01)
        assert await d.briefing_control("skip")  # mid-part: that part is cut, the next comes
        b.injector._bot_speaking = False
        while len(said(b)) < 2:
            await asyncio.sleep(0.01)
        assert await d.briefing_control("stop")
        b.injector._bot_speaking = False
        await d.state.briefing_task
        assert len(said(b)) == 2 and d.state.briefing_play is None
        assert not await d.briefing_control("skip")  # nothing to steer any more

    asyncio.run(go())


def test_skip_while_paused_drops_the_next_part(d, b, tmp_path):
    night(d, b, tmp_path)

    async def go():
        first = asyncio.Event()

        def respond():
            b.injector.bot_started_at = time.time()
            first.set()

        b.injector.on_respond = respond
        await tool(d, "briefing")(Params(since="the night"))
        await first.wait()
        await d.on_user_utterance("hold on, what time is it?")
        await d.briefing_control("skip")
        await d.state.briefing_task
        parts = said(b)
        assert len(parts) == 2 and "Docs" in parts[1]  # billing was skipped

    asyncio.run(go())


def test_another_question_pauses_and_go_on_continues(d, b, tmp_path):
    night(d, b, tmp_path)

    async def go():
        first = asyncio.Event()

        def respond():
            b.injector.bot_started_at = time.time()
            b.injector._bot_speaking = False
            first.set()

        b.injector.on_respond = respond
        await tool(d, "briefing")(Params(since="the night"))
        await first.wait()
        await d.on_user_utterance("what failed in billing exactly?")  # a question: the briefing waits
        await asyncio.sleep(0.2)
        assert len(said(b)) == 1 and d.state.briefing_play.paused
        assert "paused" in d._brain_context().lower()
        await d.briefing_control("continue")
        await d.state.briefing_task
        assert len(said(b)) == 3

    asyncio.run(go())


def test_the_spoken_control_is_consumed_and_never_reaches_the_brain(d, b, tmp_path, monkeypatch):
    night(d, b, tmp_path)
    pushed = []
    ears = d.SonioxEars()

    async def push(frame, *a):
        pushed.append(frame)

    monkeypatch.setattr(ears, "push_frame", push)
    d.state.briefing_play = d.BriefingPlay(briefing=briefing.assemble([sec("docs", "done")], "today", "normal", 0, 0))
    asyncio.run(ears._take("stop"))
    assert pushed == [] and d.state.briefing_play is None


def test_at_commands_another_voice_cannot_stop_it(d, b, tmp_path, monkeypatch):
    import speaker
    from test_speaker import OTHER_HZ, FakeEmbedder, enrol
    from test_voice_lock import _utter

    lock = speaker.VoiceLock(tmp_path / "voiceprint", tmp_path / "models", FakeEmbedder())
    monkeypatch.setattr(d, "VOICE", lock)
    enrol(lock)
    d.PREFS.update({"voice_lock": "commands"})
    ears = d.SonioxEars()

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(ears, "broadcast_interruption", noop)
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    b.injector.resume_cut = noop
    play = d.state.briefing_play = d.BriefingPlay(briefing=briefing.assemble([sec("docs", "done")], "today", "normal", 0, 0))
    asyncio.run(_utter(d, ears, OTHER_HZ, "stop"))
    assert d.state.briefing_play is play


def test_never_into_a_meeting(d, b, tmp_path, monkeypatch):
    night(d, b, tmp_path)
    d.state.meeting = SimpleNamespace(mode="listening", id="m1", status=lambda: {"on": True}, hand=None)
    p = Params(since="the night")
    asyncio.run(tool(d, "briefing")(p))
    assert "Not available during meeting" in p.results[0]["error"]
    r = client_for(d).post("/voice/briefings", json={"action": "start"})
    assert r.status_code == 409
    assert said(b) == []


def test_a_meeting_that_starts_mid_briefing_stops_it(d, b, tmp_path):
    night(d, b, tmp_path)

    async def go():
        first = asyncio.Event()

        def respond():
            b.injector.bot_started_at = time.time()
            b.injector._bot_speaking = False
            first.set()
            d.state.meeting = SimpleNamespace(mode="listening", id="m1", hand=None)  # the meeting starts right then

        b.injector.on_respond = respond
        await tool(d, "briefing")(Params(since="the night"))
        await d.state.briefing_task
        assert len(said(b)) == 1

    asyncio.run(go())


def test_a_push_to_talk_press_pauses_it(d, b, tmp_path):
    night(d, b, tmp_path)
    d.PREFS.update({"microphone": "ptt"})

    async def go():
        first = asyncio.Event()

        def respond():
            b.injector.bot_started_at = time.time()
            b.injector._bot_speaking = False
            if not first.is_set():
                d.state.ptt.press(time.time())  # the owner pressed to talk while it spoke
                first.set()

        b.injector.on_respond = respond
        await tool(d, "briefing")(Params(since="the night"))
        await first.wait()
        await asyncio.sleep(0.2)
        assert len(said(b)) == 1 and d.state.briefing_play.paused

    asyncio.run(go())


def test_a_reader_timeout_reads_the_last_words_instead(d, b, tmp_path):
    night(d, b, tmp_path)
    b.replies["billing"] = TimeoutError()
    asyncio.run(run_briefing(d, since="the night"))
    assert any("I couldn't digest billing" in p for p in said(b))


def test_quiet_sessions_cost_no_reader_call(d, b, tmp_path):
    add(d, "o", "ops", transcript=transcript(tmp_path, "ops", [("assistant", "Done.")], when=time.time() - 3 * 86400))
    asyncio.run(run_briefing(d, since="today"))
    assert b.prompts == []
    assert "Quiet" in said(b)[0]


def test_departed_and_restarted_sessions_join_by_folder(d, b, tmp_path):
    # the run before a restart: a departed session in the same folder (a departed one with the very same name is
    # forgotten by the registry when the new one joins, so only a differently named one is still there to join)
    old = add(d, "old", "lantern/first-run", cwd="/work/lantern", transcript=transcript(tmp_path, "old", [("assistant", "Started.")]))
    d.REGISTRY.departed[old.id] = d.REGISTRY.sessions.pop(old.id)
    add(d, "new", "lantern", cwd="/work/lantern", transcript=transcript(tmp_path, "new", [("assistant", "Finished.")]))
    gone = add(d, "g", "archive", cwd="/work/archive", transcript=transcript(tmp_path, "g", [("assistant", "Closed.")]))
    d.REGISTRY.departed[gone.id] = d.REGISTRY.sessions.pop(gone.id)
    b.replies.update({"lantern": {"status": "done", "say": "Lantern finished."}, "archive": {"status": "done", "say": "Archive closed."}})
    asyncio.run(run_briefing(d, since="the night"))
    names = [s.session for s in d.BRIEFINGS.latest().sections]
    assert sorted(names) == ["archive", "lantern"]
    lantern_prompt = next(p for p in b.prompts if "Session: lantern\n" in p)
    assert "Started." in lantern_prompt and "Finished." in lantern_prompt


def test_scope_narrows_to_one_session(d, b, tmp_path):
    night(d, b, tmp_path)
    asyncio.run(run_briefing(d, since="today", scope="billing"))
    assert [s.session for s in d.BRIEFINGS.latest().sections] == ["billing"]


def test_hebrew_is_asked_for_when_the_user_speaks_hebrew(d, b, tmp_path):
    night(d, b, tmp_path)
    d.state.last_utterance = "תדריך על הלילה"
    asyncio.run(run_briefing(d, since="הלילה"))
    assert all("Say it in Hebrew" in p for p in said(b))
    assert all("Language: Hebrew" in p for p in b.prompts)


# ---------- routes, status, schedule ----------

def test_routes_list_and_latest(d, b, tmp_path):
    night(d, b, tmp_path)
    asyncio.run(run_briefing(d, since="the night"))
    c = client_for(d)
    all_ = c.get("/voice/briefings").json()
    assert len(all_["briefings"]) == 1 and all_["schedule"]["time"] == ""
    latest = c.get("/voice/briefings/latest").json()["briefing"]
    assert [s["session"] for s in latest["sections"]] == ["lantern", "billing", "docs"]
    st = c.get("/voice/status").json()["briefing"]
    assert st["playing"] is False and st["latest_id"] == latest["id"]


def test_start_by_tap_and_controls(d, b, tmp_path):
    night(d, b, tmp_path)
    c = client_for(d)
    r = c.post("/voice/briefings", json={"action": "start", "since": "the night", "length": "short"})
    assert r.status_code == 200, r.text
    assert c.post("/voice/briefings", json={"action": "nonsense"}).status_code == 400
    assert c.post("/voice/briefings", json={"action": "start", "length": "epic"}).status_code == 400
    d.state.conn = None
    assert c.post("/voice/briefings", json={"action": "start"}).status_code == 409


def test_schedule_route_validates_and_persists(d, b):
    c = client_for(d)
    r = c.post("/voice/briefings/schedule", json={"time": "08:30", "days": [0, 1, 2, 3, 4], "length": "short",
                                                  "speak_on_connect": False, "skip_empty": True})
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] == {"time": "08:30", "days": [0, 1, 2, 3, 4], "length": "short", "speak_on_connect": False,
                                    "skip_empty": True}
    assert d.PREFS.get("briefings.time") == "08:30"
    for bad in ({"time": "8.30"}, {"days": [9]}, {"length": "epic"}, {"speak_on_connect": "yes"}, {"surprise": 1}):
        assert c.post("/voice/briefings/schedule", json=bad).status_code == 400, bad
    assert c.post("/voice/briefings/schedule", json=[1]).status_code == 400


def test_the_phone_key_reaches_the_briefing_routes():
    import guards

    assert {"/voice/briefings", "/voice/briefings/latest", "/voice/briefings/schedule"} <= guards._PHONE_PATHS


def test_the_scheduler_builds_without_a_call_and_raises_attention(d, b, tmp_path, monkeypatch):
    night(d, b, tmp_path)
    d.state.conn = None
    now = time.time()
    slot = datetime.fromtimestamp(now - 60)
    d.PREFS.update({"briefings.time": slot.strftime("%H:%M")})
    asyncio.run(d._scheduled_briefing(now))
    ready = d.BRIEFINGS.latest()
    assert ready is not None and ready.scheduled and not ready.heard and said(b) == []
    items = client_for(d).get("/voice/status").json()["attention"]
    assert any(i["kind"] == "briefing" and i["id"] == f"briefing:{ready.id}" for i in items)
    asyncio.run(d._scheduled_briefing(now + 30))
    assert len(d.BRIEFINGS.items) == 1  # once per slot


def test_a_quiet_scheduled_briefing_stays_silent_when_asked(d, b, tmp_path):
    d.state.conn = None
    d.PREFS.update({"briefings.time": datetime.fromtimestamp(time.time() - 60).strftime("%H:%M"), "briefings.skip_empty": True})
    asyncio.run(d._scheduled_briefing(time.time()))
    latest = d.BRIEFINGS.latest()
    assert latest is not None and latest.empty
    assert not [i for i in d._attention() if i["kind"] == "briefing"]


def test_on_connect_it_is_offered_not_spoken(d, b, tmp_path):
    night(d, b, tmp_path)
    d.state.conn = None
    d.PREFS.update({"briefings.time": datetime.fromtimestamp(time.time() - 60).strftime("%H:%M")})
    asyncio.run(d._scheduled_briefing(time.time()))
    conn = fake_conn()
    asyncio.run(d._offer_briefing(conn))
    offered = [t for t, r in conn.injector.fed if r]
    assert len(offered) == 1 and "is ready" in offered[0] and "Lantern finished" not in offered[0]
    d.PREFS.update({"briefings.speak_on_connect": False})
    conn2 = fake_conn()
    asyncio.run(d._offer_briefing(conn2))
    assert conn2.injector.fed == []


def test_playing_the_ready_briefing_marks_it_heard(d, b, tmp_path):
    night(d, b, tmp_path)
    d.state.conn = None
    d.PREFS.update({"briefings.time": datetime.fromtimestamp(time.time() - 60).strftime("%H:%M")})
    asyncio.run(d._scheduled_briefing(time.time()))
    d.state.conn = fake_conn()
    b.injector = d.state.conn.injector
    b.injector.on_respond = lambda: setattr(b.injector, "bot_started_at", time.time())
    n = len(b.prompts)
    asyncio.run(run_briefing(d))  # no "since": the one waiting
    assert len(b.prompts) == n  # not built again
    assert d.BRIEFINGS.latest().heard
    assert not [i for i in d._attention() if i["kind"] == "briefing"]


def test_the_call_end_is_remembered(d, b):
    d._call_ended()
    assert abs(d.BRIEFINGS.last_call_end - time.time()) < 2


def test_the_notes_stream_accepts_briefings():
    import notes

    assert "briefing" in notes.KINDS
