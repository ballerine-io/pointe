"""Brain dump (docs/design/brain-dump.md), offline: the rules in braindump.py (what starts, ends and commands it, the
record, structuring and its guard, the file) and the daemon around them with a fake model: nothing said while dumping
reaches the voice model or a session; done structures for review; only an explicit send delivers, word for word, and the
rules that are not judgment still refuse it; the dump outlives the call and the daemon; the page and the app share its words.

uv run pytest -q tests/test_brain_dump.py
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)

import braindump  # noqa: E402
import modes  # noqa: E402
from fake_secrets import fake  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
THOUGHTS = ["so the checkout keeps timing out for some customers",
            "I think it's the retry loop around the payment provider, it retries five times with no backoff",
            "we must not touch the tax service this sprint",
            "and I'm not sure whether the timeout is on our side or theirs"]
STRUCTURED = {"goal": "stop the checkout timing out for some customers",
              "context": ["the retry loop around the payment provider retries five times with no backoff"],
              "constraints": ["we must not touch the tax service this sprint"],
              "open_questions": ["whether the timeout is on our side or theirs"]}


# ---------- what starts, ends and commands it ----------

@pytest.mark.parametrize("said", ["Brain dump.", "okay, brain dump", "Brain dump mode", "let me dump my thoughts", "dump mode",
                                  "Just listen.", "Let me think out loud", "monologue mode", "רק תקשיב", "תן לי לחשוב בקול"])
def test_start_phrases_old_and_new(said):
    assert braindump.start_intent(said), said


@pytest.mark.parametrize("said", ["the brain dump feature should also work on the phone", "dump the cache and retry",
                                  "I'll just listen to what the customer says", "let me dump this table into a CSV file"])
def test_not_a_start(said):
    assert not braindump.start_intent(said), said


@pytest.mark.parametrize("said", ["Done.", "okay, done", "I'm done", "That's my dump", "structure it", "wrap it up",
                                  "Over to you.", "What do you think?", "Summarize that.", "Send that to billing.", "סיימתי", "זהו"])
def test_done_phrases_old_and_new(said):
    assert braindump.done_intent(said), said


@pytest.mark.parametrize("said", ["and when it's done we deploy", "the question is what do you think the customer wants",
                                  "it's done when the tests pass", "so the structure of the retry code is wrong"])
def test_a_phrase_inside_a_thought_is_a_thought(said):
    assert not braindump.done_intent(said), said


def test_send_names_its_target_or_the_active_session():
    assert braindump.send_target("Send it to billing") == "billing"
    assert braindump.send_target("okay send that to river lantern") == "river lantern"
    assert braindump.send_target("Send it.") == ""
    assert braindump.send_target("ship it") == ""
    assert braindump.send_target("תשלח את זה לבילינג") == "בילינג"
    assert braindump.send_target("the API should send that to the queue") is None


@pytest.mark.parametrize("said,asked", [("send it to billing", "send"), ("Send it.", "send"), ("add more", "more"), ("wait, more", "more"),
                                        ("not yet", "more"), ("discard", "discard"), ("forget it", "discard"), ("scrap that", "discard"),
                                        ("read it back", "read"), ("read it to me", "read"), ("what's billing doing", None),
                                        ("yes", None), ("send the invoice to the customer tomorrow", None)])
def test_review_commands(said, asked):
    assert braindump.review_intent(said) == asked


def test_the_words_after_the_start_phrase_are_the_first_thought():
    assert braindump.strip_start("Brain dump. The checkout keeps timing out.") == "The checkout keeps timing out."
    assert braindump.strip_start("Just listen, so the retry loop has no backoff") == "so the retry loop has no backoff"
    assert braindump.strip_start("just listen, okay") == ""
    assert braindump.strip_start("brain dump") == ""


# ---------- the record ----------

def test_the_record_keeps_every_thought_whole_and_counts_what_falls_off(monkeypatch):
    monkeypatch.setattr(braindump, "MAX_CHARS", 300)
    dump = braindump.Dump()
    for i in range(10):
        dump.add(f"thought number {i} " + "word " * 12)
    assert dump.dropped == 10 - len(dump.thoughts) > 0
    assert dump.thoughts[-1].text.startswith("thought number 9")
    assert sum(len(t.text) for t in dump.thoughts) <= 300
    assert dump.add("   ") is None and dump.add("") is None


def test_the_status_carries_the_whole_text_not_a_600_char_tail():
    dump = braindump.Dump()
    first = "the checkout keeps timing out for some customers on the retry path"
    dump.add(first)
    for i in range(12):
        dump.add(f"thought number {i} about the tax service cache and the backoff schedule we never set")
    status = dump.status()
    assert status["thoughts"][0]["text"] == first and len(status["thoughts"]) == 13
    assert status["state"] == "dumping" and status["prompt"] is None
    assert dump.compat()["said"].endswith(dump.thoughts[-1].text)  # the old field, for an older app


def test_the_text_sent_is_the_prompt_else_the_thoughts_under_context():
    dump = braindump.Dump()
    dump.add("the retry loop has no backoff")
    assert dump.text == "Context\n- the retry loop has no backoff"
    dump.prompt = braindump.edited("Goal: fix the retry loop\nConstraints:\n- no backoff changes")
    assert dump.text == "Goal: fix the retry loop\nConstraints:\n- no backoff changes"


# ---------- structuring ----------

def test_parse_keeps_the_users_words_and_drops_what_the_model_added():
    said = " ".join(THOUGHTS)
    reply = json.dumps({**STRUCTURED, "constraints": STRUCTURED["constraints"] + ["use exponential backoff with jitter and a circuit breaker"],
                        "open_questions": STRUCTURED["open_questions"] + ["should we migrate the database to Postgres 17"]})
    out = braindump.parse(reply, said)
    assert out["goal"] == STRUCTURED["goal"]
    assert out["constraints"] == STRUCTURED["constraints"]  # the invented one is gone
    assert out["open_questions"] == STRUCTURED["open_questions"]


def test_parse_takes_a_fenced_reply_and_a_goal_given_as_a_list():
    reply = "```json\n" + json.dumps({"goal": ["stop the checkout timing out for some customers"], "context": [], "constraints": [],
                                      "open_questions": []}) + "\n```"
    assert braindump.parse(reply, " ".join(THOUGHTS))["goal"] == "stop the checkout timing out for some customers"


def test_parse_raises_when_nothing_is_theirs_or_the_reply_is_not_json():
    with pytest.raises(ValueError):
        braindump.parse(json.dumps({"goal": "rewrite everything in Rust", "context": ["ship by Friday"], "constraints": [], "open_questions": []}),
                        " ".join(THOUGHTS))
    with pytest.raises(ValueError):
        braindump.parse("Here is the brief: the checkout...", " ".join(THOUGHTS))


def test_invented_is_about_content_words_not_glue():
    said = "the retry loop around the payment provider retries five times with no backoff"
    assert not braindump.invented("the retry loop retries five times with no backoff", said)
    assert not braindump.invented("Retry loop.", said)  # short: one of their words is enough
    assert braindump.invented("add a circuit breaker and jitter", said)
    assert braindump.invented("", said)


def test_the_prompt_text_is_the_sections_in_order_with_empty_ones_left_out():
    text = braindump.render({**STRUCTURED, "constraints": []})
    assert text.startswith(f"Goal\n{STRUCTURED['goal']}\n\nContext\n- {STRUCTURED['context'][0]}")
    assert "\n\nOpen questions\n- whether" in text
    assert "Constraints" not in text and ":" not in text.splitlines()[0]
    assert braindump.render({"goal": "", "context": ["x"], "constraints": [" "], "open_questions": []}) == "Context\n- x"  # no empty Goal


def test_the_framing_is_added_at_send_time_never_in_the_text_the_user_edits():
    text = braindump.structured(STRUCTURED)["text"]
    assert "nothing added" not in text and "Brain dump from the user" not in text
    assert "nothing added" in braindump.sent_header("billing") and "billing" in braindump.sent_header("billing")


def test_a_credential_in_a_thought_is_masked_in_the_prompt():
    key = fake("sk-proj-", "AbCdEf0123456789AbCdEf0123456789")
    out = braindump.parse(json.dumps({"goal": "", "context": [f"the test used key {key} and failed"], "constraints": [], "open_questions": []}),
                          f"the test used key {key} and failed")
    assert key not in out["context"][0] and "failed" in out["context"][0]


def test_the_fallback_is_the_thoughts_under_context_and_add_more_folds_into_the_existing_text():
    fb = braindump.fallback(THOUGHTS[:2])
    assert fb["context"] == THOUGHTS[:2] and fb["text"].startswith("Context\n- ") and "Goal" not in fb["text"] and THOUGHTS[1] in fb["text"]
    prompt = braindump.structure_prompt(["one more thing"], existing="Goal: x\nContext:\n- y")
    assert "already reviewed" in prompt and "- one more thing" in prompt and "keep the existing lines" in prompt
    assert braindump.structure_prompt(THOUGHTS[:1]).startswith("The thoughts, in order:")


# ---------- the file ----------

def test_the_file_round_trips_and_a_restart_marks_it_resumed(tmp_path):
    path = tmp_path / "brain_dump.json"
    dump = braindump.Dump()
    dump.add(THOUGHTS[0])
    braindump.save(path, dump)
    back = braindump.load(path)
    assert back is not None and back.id == dump.id and back.thoughts[0].text == THOUGHTS[0] and back.resumed and back.state == "dumping"
    dump.state, dump.prompt = "review", braindump.structured(STRUCTURED)
    braindump.save(path, dump)
    assert braindump.load(path).state == "review" and braindump.load(path).prompt["goal"] == STRUCTURED["goal"]
    dump.state = "structuring"  # cut mid-call: back to dumping, the thoughts kept
    braindump.save(path, dump)
    assert braindump.load(path).state == "dumping"
    braindump.save(path, None)
    assert not path.exists() and braindump.load(path) is None


def test_a_broken_or_empty_file_loads_as_nothing(tmp_path):
    path = tmp_path / "brain_dump.json"
    path.write_text("{not json")
    assert braindump.load(path) is None
    path.write_text(json.dumps({"id": "d1", "since": 1, "state": "dumping", "thoughts": [], "prompt": None}))
    assert braindump.load(path) is None
    path.write_text(json.dumps({"state": "nowhere", "thoughts": [{"text": "x", "at": 1}]}))
    assert braindump.load(path) is None


# ---------- the daemon around it ----------

class Brain:
    """What the voice model is told (inject) and what it would hear as a turn (push_frame)."""

    def __init__(self):
        self.told: list[tuple[str, bool]] = []
        self.turns: list[str] = []

    async def inject(self, text, respond):
        self.told.append((text, respond))

    async def push_frame(self, frame):
        self.turns.append(frame.text)


def call(d, monkeypatch, reply=None):
    brain = Brain()
    conn = fake_conn()
    conn.injector = brain
    d.state.conn, d.state.front = conn, SimpleNamespace(push_frame=lambda f: asyncio.sleep(0))
    monkeypatch.setattr(d, "_tone", lambda up: asyncio.sleep(0))
    calls = []

    async def text(choice, prompt, system=None, **kw):
        calls.append((choice, prompt, system, kw))
        if isinstance(reply, Exception):
            raise reply
        return reply if reply is not None else json.dumps(STRUCTURED)

    monkeypatch.setattr(d.vendors, "text", text)
    brain.calls = calls
    return brain


def ears(d):
    return d.SonioxEars()


def take(d, *said):
    e = ears(d)
    for s in said:
        asyncio.run(e._take(s))


def test_while_dumping_nothing_reaches_the_brain_and_done_structures_for_review(d, monkeypatch):
    brain = call(d, monkeypatch)
    take(d, "Brain dump.", *THOUGHTS)
    assert d._dumping() and d.current_mode() is modes.BRAIN_DUMP and modes.BRAIN_DUMP is modes.BRAINSTORM
    assert brain.turns == [] and brain.told == []
    assert [t.text for t in d.state.dump.thoughts] == THOUGHTS
    take(d, "Okay, done.")
    dump = d.state.dump
    assert dump.state == "review" and not d._dumping() and d.current_mode() is modes.CONVERSATION
    assert dump.prompt["goal"] == STRUCTURED["goal"] and dump.prompt["text"].startswith("Goal\n")
    assert brain.turns == [] and len(brain.told) == 1 and brain.told[0][0].startswith("[brain dump ready]") and brain.told[0][1]
    assert "retry loop" not in brain.told[0][0]  # the brain is told it is ready, never the content
    choice, prompt, system, kw = brain.calls[0]
    assert choice == "gemini:r" and kw["json_reply"] and THOUGHTS[1] in prompt and "Never add a requirement" in system


def test_done_with_nothing_said_is_silent(d, monkeypatch):
    brain = call(d, monkeypatch)
    client = client_for(d)
    assert client.post("/voice/listen", json={"on": True}).json() == {"monologue": True}
    assert client.post("/voice/listen", json={"on": False}).json() == {"monologue": False}
    assert brain.turns == [] and brain.told == [] and brain.calls == [] and d.state.dump is None


def test_the_buttons_do_what_the_words_do(d, monkeypatch):
    brain = call(d, monkeypatch)
    client = client_for(d)
    assert client.post("/voice/dump", json={"action": "done"}).status_code == 409
    r = client.post("/voice/dump", json={"action": "start"})
    assert r.status_code == 200 and r.json()["brain_dump"]["state"] == "dumping"
    take(d, *THOUGHTS[:2])
    status = client.get("/voice/status").json()
    assert status["mode_state"]["mode"] == "brain-dump" and status["brain_dump"]["thoughts"][1]["text"] == THOUGHTS[1]
    assert status["monologue"]["said"].endswith(THOUGHTS[1])  # the old field, while dumping
    r = client.post("/voice/dump", json={"action": "done"})
    assert r.json()["brain_dump"]["state"] == "review" and r.json()["brain_dump"]["prompt"]["goal"] == STRUCTURED["goal"]
    assert client.get("/voice/status").json()["monologue"] is None
    assert client.post("/voice/dump", json={"action": "start"}).status_code == 409  # review first
    assert client.post("/voice/dump", json={"action": "nope"}).status_code == 400
    assert brain.turns == []


def test_a_rhetorical_what_do_you_think_mid_dump_only_opens_the_review(d, monkeypatch):
    """Before: the whole dump went into the conversation and the model answered or sent. Now it is shown; nothing moves."""
    brain = call(d, monkeypatch)
    take(d, "just listen", THOUGHTS[0], "What do you think?")
    assert d.state.dump.state == "review" and brain.turns == [] and d.state.sent == []


def test_send_delivers_the_reviewed_text_word_for_word_and_records_it(d, monkeypatch):
    brain = call(d, monkeypatch)
    delivered = []

    async def deliver(session, text):
        delivered.append((session.name, text))
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    add(d, "b", "billing", "/w/billing")
    add(d, "x", "docs", "/w/docs")
    take(d, "brain dump", *THOUGHTS, "done")
    take(d, "what's docs doing")  # ordinary conversation while the card waits: a turn for the brain, not a thought
    assert d.state.last_utterance == "what's docs doing" and d.state.dump.state == "review" and len(d.state.dump.thoughts) == 4
    take(d, "Send it to billing.")
    assert len(delivered) == 1 and delivered[0][0] == "billing"
    header, body = delivered[0][1].split("\n", 1)
    assert header == braindump.sent_header("billing") and body == braindump.render(STRUCTURED)
    assert d.state.dump is None and d.state.sent == [f"billing: {body}"] and d.state.last_message == body
    assert d.state.dispatches[-1]["to"] == ["billing"] and d.state.dispatches[-1]["how"] == "brain dump: sent by the user"
    assert d.state.thread[0] == "b" and d.state.unconfirmed["b"] == [body]
    assert brain.told[-1][0].startswith("[brain dump sent]") and "billing" in brain.told[-1][0]
    assert not (d.STATE_DIR / "brain_dump.json").exists()


def test_the_send_button_names_the_session_or_takes_the_active_one(d, monkeypatch):
    call(d, monkeypatch)
    delivered = []

    async def deliver(session, text):
        delivered.append(session.name)
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    add(d, "b", "billing", "/w/billing")
    add(d, "x", "docs", "/w/docs")
    client = client_for(d)
    client.post("/voice/dump", json={"action": "start"})
    take(d, THOUGHTS[0])
    client.post("/voice/dump", json={"action": "done"})
    r = client.post("/voice/dump", json={"action": "send", "session": "nobody"})
    assert r.status_code == 409 and "nobody" in r.json()["detail"]
    r = client.post("/voice/dump", json={"action": "send", "session": "docs"})
    assert r.status_code == 200 and r.json()["sent_to"] == "docs" and r.json()["brain_dump"] is None and delivered == ["docs"]
    assert client.post("/voice/dump", json={"action": "send"}).status_code == 409  # nothing left to send


def test_a_spoken_send_while_dumping_structures_and_preselects_but_does_not_send(d, monkeypatch):
    brain = call(d, monkeypatch)
    delivered = []

    async def deliver(session, text):
        delivered.append(session.name)
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    add(d, "b", "billing", "/w/billing")
    take(d, "brain dump", THOUGHTS[0], "Send that to billing.")
    assert d.state.dump.state == "review" and d.state.dump.target == "billing" and delivered == []
    take(d, "send it")
    assert delivered == ["billing"] and d.state.dump is None
    assert brain.turns == []


def test_a_spoken_send_to_an_unknown_session_is_said_and_sends_nothing(d, monkeypatch):
    brain = call(d, monkeypatch)
    add(d, "b", "billing", "/w/billing")
    take(d, "brain dump", THOUGHTS[0], "done", "send it to lantern")
    assert d.state.dump is not None and d.state.dump.problem == "No session called lantern."
    assert brain.told[-1][0].startswith("[brain dump]") and "lantern" in brain.told[-1][0] and d.state.sent == []


def test_send_refusals_that_are_rules_not_judgment(d, monkeypatch):
    call(d, monkeypatch, reply=json.dumps({"goal": "rotate the prod api token before the retry change", "context": [], "constraints": [],
                                           "open_questions": []}))
    delivered = []

    async def deliver(session, text):
        delivered.append(session.name)
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    s = add(d, "b", "billing", "/w/billing")
    client = client_for(d)
    client.post("/voice/dump", json={"action": "start"})
    take(d, "rotate the prod api token before the retry change")
    client.post("/voice/dump", json={"action": "done"})
    r = client.post("/voice/dump", json={"action": "send", "session": "billing"})  # production credentials: refused once
    assert r.status_code == 409 and "production credentials" in r.json()["detail"] and delivered == []
    assert client.get("/voice/status").json()["brain_dump"]["problem"] == r.json()["detail"]
    s.typed_approval = "merge the release branch"
    client.post("/voice/dump", json={"action": "edit", "text": "Goal: go ahead and merge the release branch"})
    r = client.post("/voice/dump", json={"action": "send", "session": "billing"})  # relays an approval the session takes only typed
    assert r.status_code == 409 and "typed" in r.json()["detail"] and delivered == []
    s.typed_approval = None
    d.state.meeting = SimpleNamespace(mode="listening")
    r = client.post("/voice/dump", json={"action": "send", "session": "billing"})
    assert r.status_code == 409 and "meeting" in r.json()["detail"] and delivered == []
    d.state.meeting = None
    s.machine, s.online_override = "devbox", None
    monkeypatch.setattr(d, "online", lambda session: False)
    r = client.post("/voice/dump", json={"action": "send", "session": "billing"})
    assert r.status_code == 409 and "offline" in r.json()["detail"] and delivered == []
    monkeypatch.setattr(d, "online", lambda session: True)
    assert client.post("/voice/dump", json={"action": "send", "session": "billing"}).status_code == 200 and delivered == ["billing"]


def test_edit_add_more_and_discard(d, monkeypatch):
    brain = call(d, monkeypatch)
    client = client_for(d)
    take(d, "brain dump", *THOUGHTS[:2], "done")
    assert client.post("/voice/dump", json={"action": "edit", "text": ""}).status_code == 400
    r = client.post("/voice/dump", json={"action": "edit", "text": "Goal: fix the retry loop\nConstraints:\n- keep the tax service"})
    assert r.json()["brain_dump"]["prompt"]["text"] == "Goal: fix the retry loop\nConstraints:\n- keep the tax service"
    take(d, "add more")
    assert d._dumping() and d.state.dump.prompt["text"].startswith("Goal: fix the retry loop")  # the edit is kept
    take(d, THOUGHTS[2], "done")
    _, prompt, _, _ = brain.calls[-1]
    assert "Goal: fix the retry loop" in prompt and THOUGHTS[2] in prompt and THOUGHTS[0] not in prompt.split("New thoughts")[1]
    assert d.state.dump.state == "review" and d.state.dump.structured == 3
    take(d, "read it back")
    assert brain.told[-1][0].startswith("[read the brain dump back]") and STRUCTURED["goal"] in brain.told[-1][0]
    take(d, "discard")
    assert d.state.dump is None and client.post("/voice/dump", json={"action": "discard"}).status_code == 409
    assert brain.turns == []


@pytest.mark.parametrize("said", ["Discard.", "forget it", "never mind", "scrap that"])
def test_discard_by_voice_while_dumping_ends_it_with_nothing_kept(d, monkeypatch, said):
    brain = call(d, monkeypatch)
    take(d, "brain dump", THOUGHTS[0], said)
    assert d.state.dump is None and not (d.DUMP_FILE).exists() and brain.turns == []


@pytest.mark.parametrize("said", ["never mind the tax service, the retries are the problem", "we should scrap that retry loop"])
def test_discard_inside_a_thought_is_a_thought(said):
    assert not braindump.discard_intent(said), said


def test_discard_while_dumping_releases_what_waited(d, monkeypatch):
    brain = call(d, monkeypatch)
    take(d, "brain dump", THOUGHTS[0])
    d.state.monologue_held.append(("[billing finished its turn] done", True))
    asyncio.run(client_for(d).app.router.routes and d._discard_dump())
    assert d.state.dump is None and brain.told == [("[billing finished its turn] done", True)] and not d.state.monologue_held


def test_held_news_and_a_pending_approval_follow_the_review_line(d, monkeypatch):
    brain = call(d, monkeypatch)
    asked = []

    async def ask(session):
        asked.append(session.name)

    monkeypatch.setattr(d, "_ask_permission", ask)
    s = add(d, "b", "billing", "/w/billing")
    d.REGISTRY.active_id = "b"
    s.permission_id, s.permission_text = "p1", "billing wants to run: git status"
    take(d, "brain dump")
    assert s.permission_delivered_at == float("inf")
    d.state.monologue_held.append(("[docs finished its turn] done", True))
    take(d, THOUGHTS[0], "done")
    assert [t for t, _ in brain.told] == [braindump.review_line(d.state.dump), "[docs finished its turn] done"] and asked == ["billing"]


def test_when_the_model_fails_the_prompt_is_the_thoughts_as_said(d, monkeypatch):
    brain = call(d, monkeypatch, reply=RuntimeError("down"))
    take(d, "brain dump", *THOUGHTS[:2], "done")
    dump = d.state.dump
    assert dump.state == "review" and dump.fallback and dump.prompt["context"] == THOUGHTS[:2] and THOUGHTS[1] in dump.text
    assert "could not structure it" in brain.told[-1][0]


def test_a_discard_during_structuring_wins(d, monkeypatch):
    brain = call(d, monkeypatch)

    async def slow(*a, **k):
        await d._discard_dump()
        return json.dumps(STRUCTURED)

    monkeypatch.setattr(d.vendors, "text", slow)
    take(d, "brain dump", THOUGHTS[0], "done")
    assert d.state.dump is None and not any(t.startswith("[brain dump ready]") for t, _ in brain.told)


def test_the_dump_outlives_the_call_and_is_said_on_the_next_one(d, monkeypatch):
    brain = call(d, monkeypatch)
    take(d, "brain dump", *THOUGHTS[:2])
    path = d.STATE_DIR / "brain_dump.json"
    assert json.loads(path.read_text())["thoughts"][1]["text"] == THOUGHTS[1]
    d.state.conn = None
    d._call_ended()
    assert d._dumping()  # the call dropped: the dump stays
    # the next call: the same dump, said once
    d.state.conn = fake_conn()
    d.state.conn.injector = brain
    monkeypatch.setattr(d, "_add_worker", lambda s: asyncio.sleep(0))
    monkeypatch.setattr(d, "_start_briefs", lambda: None)
    monkeypatch.setattr(d, "_offer_briefing", lambda c: asyncio.sleep(0))
    monkeypatch.setattr(d, "_notify_call", lambda: None)
    asyncio.run(d._on_connect(d.state.conn))
    assert d.state.dump.resumed and brain.told[-1][0].startswith("[brain dump still here]") and "2 so far" in brain.told[-1][0]
    assert brain.turns == []


def test_the_dump_outlives_the_daemon(d, monkeypatch):
    call(d, monkeypatch)
    take(d, "brain dump", *THOUGHTS[:2], "done")
    assert (d.STATE_DIR / "brain_dump.json").exists()
    d.state.dump = None  # the daemon restarted
    d._load_dump()
    assert d.state.dump is not None and d.state.dump.state == "review" and d.state.dump.resumed
    assert d.state.dump.prompt["goal"] == STRUCTURED["goal"] and client_for(d).get("/voice/status").json()["brain_dump"]["resumed"]


def test_a_meeting_takes_the_thoughts_as_its_brief_and_a_challenge_as_its_plan(d, monkeypatch):
    call(d, monkeypatch)
    take(d, "brain dump", THOUGHTS[0])
    import inspect
    src = inspect.getsource(d.start_meeting)
    assert "state.dump.said" in src and "_save_dump()" in src  # the brief: tested live in tests/test_meeting_daemon.py
    monkeypatch.setattr(d, "_challenge_refusal", lambda: None)
    monkeypatch.setattr(d, "_challenge_evidence", lambda sessions: asyncio.sleep(0, result=[]))
    take(d, "challenge this")
    assert d.state.dump is None and d.state.challenge is not None and THOUGHTS[0] in d.state.challenge.plan
    assert not (d.STATE_DIR / "brain_dump.json").exists()


def test_typed_words_count_too(d, monkeypatch):
    brain = call(d, monkeypatch)
    client = client_for(d)
    client.post("/voice/dump", json={"action": "start"})
    assert client.post("/voice/say", json={"text": THOUGHTS[0]}).status_code == 200
    assert client.post("/voice/say", json={"text": "done"}).status_code == 200
    assert d.state.dump.state == "review" and brain.turns == [] and [t.text for t in d.state.dump.thoughts] == [THOUGHTS[0]]


def test_the_phone_key_reaches_the_dump_route(d):
    from guards import _PHONE_PATHS
    assert "/voice/dump" in _PHONE_PATHS


# ---------- the page and the app share their words ----------

def _swift_copy() -> dict:
    swift = (ROOT / "ios" / "Pointe" / "BrainDump.swift").read_text()
    block = swift[swift.index("enum BrainDumpCopy"):]
    block = block[:block.index("\n}\n")]
    return dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block))


def _page_copy() -> dict:
    page = (ROOT / "ui.html").read_text()
    block = page[page.index("const DUMP_COPY = {"):]
    block = block[:block.index("};")]
    return dict(re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block))


def test_the_page_the_app_and_the_daemon_use_the_same_words():
    """Parity: braindump.COPY is the single source; ui.html DUMP_COPY and BrainDump.swift BrainDumpCopy carry it word for word."""
    page, swift = _page_copy(), _swift_copy()
    expected = {k: v.replace("’", "'") for k, v in braindump.COPY.items()}
    assert {k: v.replace("\\'", "'").replace("’", "'") for k, v in page.items()} == expected
    assert {k: v.replace('\\"', '"').replace("’", "'") for k, v in swift.items()} == expected
