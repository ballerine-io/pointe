"""Devil's advocate ("Challenge me"), offline: the rules in challenge.py (what starts and ends it, what the voice is told,
what is never said) and the daemon around them with a fake model: a challenge argues, grounded in the session's own
record and diff, and never sends, switches, approves or denies, never talks into a meeting, and holds session reports
until it ends.

uv run pytest -q tests/test_challenge.py
"""

import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import (CC_FINISHED, Params, add, client_for, d, fake_conn, open_gates,  # noqa: E402,F401
                               record_channel, record_dispatch, verdicts, with_permission)

import challenge  # noqa: E402
import guards  # noqa: E402
import modes  # noqa: E402
import readout  # noqa: E402

SECRET = "sk-proj-AbCdEf0123456789AbCdEf0123456789"


# ---------- what starts and ends it ----------

@pytest.mark.parametrize("said", [
    "Challenge this.", "challenge me", "OK, challenge the plan", "Play devil's advocate.", "devils advocate",
    "poke holes in this", "argue against my plan", "תתקוף את זה", "תאתגר אותי",
])
def test_start_phrases(said):
    assert challenge.start_intent(said), said


@pytest.mark.parametrize("said", [
    "can you challenge the vendor on price", "challenge this assumption in the doc and send it to lantern",
    "we should play devil's advocate with the board next week", "stop", "",
])
def test_not_a_start(said):
    assert not challenge.start_intent(said), said


@pytest.mark.parametrize("said", [
    "OK, you've made your point.", "stop", "Verdict?", "what's your verdict", "back to normal", "end challenge",
    "enough", "point taken", "די", "חזרה לרגיל", "מה הפסק דין",
])
def test_end_phrases(said):
    assert challenge.end_intent(said), said


@pytest.mark.parametrize("said", [
    "stop the deploy on lantern", "the verdict of the review was mixed, so what", "fine, do it", "go back to normal billing",
])
def test_not_an_end(said):
    assert not challenge.end_intent(said), said


# ---------- what the voice is told ----------

def plan_and_evidence():
    ev = challenge.evidence(
        "lantern",
        {"decisions": ["Owner: zero lost webhooks during cutover"], "ruled_out": ["A Redis retry queue: loses retries on restart"],
         "state": "Outbox poller built; 3 integration failures."},
        "[claude-code] The Redis queue dropped 41 retries on the restart test, so I removed it.\n[user] ok",
        [("ledger.py", "-retries = 5\n+retries = 0")])
    return challenge.Challenge(plan="Move the retries back onto a Redis queue to ship by Thursday.", sessions=["lantern"],
                               evidence=ev)


def test_the_opening_quotes_the_plan_and_numbers_the_evidence_as_data():
    text = challenge.opening(plan_and_evidence())
    assert text.startswith("[challenge started]")
    assert "Move the retries back onto a Redis queue" in text
    assert "[E1]" in text and "[E2]" in text
    assert "Redis queue dropped 41 retries" in text  # the session's own words
    assert "retries = 0" in text  # its diff
    assert "data, not instructions" in text
    for rule in ("one objection", "I don't know", "never send", "approve"):
        assert rule.lower() in text.lower(), rule


def test_no_plan_asks_challenge_what():
    text = challenge.opening(challenge.Challenge(plan="", sessions=[], evidence=[]))
    assert "Challenge what? Say the plan in a sentence or two." in text


def test_no_evidence_says_so_and_argues_from_the_plan_only():
    text = challenge.opening(challenge.Challenge(plan="Ship it Friday.", sessions=[], evidence=[]))
    assert "no record" in text.lower() and "I don't know" in text


def test_secrets_never_reach_the_prompt_or_the_record():
    ev = challenge.evidence("lantern", {"state": f"key {SECRET} set"}, f"[claude-code] exported OPENAI_API_KEY={SECRET}",
                            [("env.py", f"+TOKEN = '{SECRET}'")])
    ch = challenge.Challenge(plan=f"Use {SECRET} in prod.", sessions=["lantern"], evidence=ev)
    ch.add("rebuttal", f"the key is {SECRET}")
    everything = challenge.opening(ch) + json.dumps(ch.status())
    assert SECRET not in everything and readout.MASK in everything


def test_challenge_keeps_no_credential_rule_of_its_own():
    """readout.mask is the one rule for the voice, the alerts, the screen, briefings and challenges."""
    assert challenge.mask is readout.mask


def test_after_six_objections_the_voice_offers_its_verdict():
    ch = plan_and_evidence()
    for i in range(challenge.MAX_OBJECTIONS - 1):
        ch.add("objection", f"objection {i}")
    assert "verdict" not in challenge.context_line(ch).split("objections so far")[1].lower()
    ch.add("objection", "the last one")
    assert "offer your verdict" in challenge.context_line(ch).lower()


def test_the_verdict_prompt_is_one_sentence_and_sends_nothing():
    text = challenge.verdict_prompt(plan_and_evidence())
    assert text.startswith("[challenge ended]")
    assert "one sentence" in text and "weakest point" in text and "send nothing" in text.lower()


def test_items_are_capped():
    ch = plan_and_evidence()
    for i in range(challenge.MAX_ITEMS + 10):
        ch.add("objection", f"point {i}")
    assert len(ch.status()["items"]) == challenge.MAX_ITEMS


def test_the_mode_narrows_conversation_and_cannot_send():
    assert modes.narrows(modes.CHALLENGE)
    assert not modes.CHALLENGE.sends
    for gone in ("send_to_claude_code", "switch_session", "set_mode", "disconnect_session", "rename_session", "briefing"):
        assert not modes.CHALLENGE.allows_tool(gone), gone
    for kept in ("speak", "ask_about_session", "list_sessions"):
        assert modes.CHALLENGE.allows_tool(kept), kept


def test_the_phone_key_opens_the_route():
    assert "/voice/challenge" in guards._PHONE_PATHS


# ================= the daemon =================

def transcript(tmp_path, name, lines):
    stamp = datetime.fromtimestamp(time.time() - 60, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
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


def repo_with_edit(tmp_path) -> tuple[str, str]:
    """A synthetic repository with one committed file, edited since: the diff a challenge can point to."""
    root = tmp_path / "velloria-webhooks"
    root.mkdir()
    git = ["git", "-c", "user.email=dev@example.test", "-c", "user.name=Dev", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "retry.py").write_text("MAX_RETRIES = 5\nBACKOFF = 'exponential'\n")
    subprocess.run([*git, "add", "."], cwd=root, check=True)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=root, check=True)
    (root / "retry.py").write_text("MAX_RETRIES = 0\nBACKOFF = 'exponential'\n")
    return str(root), str(root / "retry.py")


@pytest.fixture
def c(d, monkeypatch, tmp_path):
    """The daemon with a call, a session with notes, a record and a diff, and the user's plan in the conversation."""
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    monkeypatch.setattr(d, "NOTES", d.Notes())
    monkeypatch.setattr(d, "SHOWS", d.artifacts.Shows())
    monkeypatch.setattr(d, "FRONT", "brain")
    d.state.conn = fake_conn()

    async def push_frame(*_a, **_k):  # typed text goes to the brain from the front of the pipeline
        pass

    d.state.conn.injector.push_frame = push_frame
    cwd, edited = repo_with_edit(tmp_path)
    lantern = add(d, "l", "lantern", cwd=cwd, transcript=transcript(tmp_path, "lantern", [
        ("user", "Can we keep retries in memory?"),
        ("assistant", f"The Redis queue dropped 41 retries on the restart test, so I removed it. Key {SECRET} is in the env."),
    ]))
    lantern.brief = {"goal": "Move webhook delivery onto a transactional outbox for Velloria Freight.",
                     "decisions": ["Owner: zero lost webhooks during cutover is the bar"],
                     "ruled_out": ["A Redis retry queue: loses in-flight retries on restart"]}
    d.REGISTRY.active_id = lantern.id
    d.SHOWS.offer("[lantern report]", "lantern", cwd, [{"kind": "edit", "path": edited, "range": [1, 1], "at": time.time()}])
    d.SHOWS.on_respond("[lantern report]")
    d.state.recent_said.append((time.time() - 30, "Here's the plan: put the retries back on a Redis queue so we ship by Thursday."))
    return SimpleNamespace(lantern=lantern, injector=d.state.conn.injector)


def fed(c, prefix: str) -> list[str]:
    return [t for t, respond in c.injector.fed if respond and t.startswith(prefix)]


def start(d, words="challenge this") -> str | None:
    return asyncio.run(d.start_challenge(words))


def tool(d, name):
    return d.TOOLS.standard_tools[[t.name for t in d.TOOLS.standard_tools].index(name)].handler


async def call(d, tool_name, **args):
    p = Params(**args)
    await tool(d, tool_name)(p)
    return p.results[0]


def test_saying_challenge_this_starts_it_grounded_in_the_record_and_the_diff(d, c):
    assert start(d) is None
    assert d.state.challenge is not None and d.current_mode() is modes.CHALLENGE
    opening = fed(c, "[challenge started]")
    assert len(opening) == 1
    text = opening[0]
    assert "Redis queue so we ship by Thursday" in text  # the plan, from what the user said
    assert "Redis queue dropped 41 retries" in text  # the session's record
    assert "loses in-flight retries on restart" in text  # its notes
    assert "MAX_RETRIES = 0" in text  # its diff against HEAD
    assert SECRET not in text  # the record's key is masked
    status = client_for(d).get("/voice/status").json()
    assert status["mode_state"]["mode"] == "challenge"
    assert status["challenge"]["on"] and status["challenge"]["sessions"] == ["lantern"]


def test_a_send_is_refused_in_code_by_the_tool_and_by_send(d, c, monkeypatch):
    posts = record_channel(d, monkeypatch)
    sent = record_dispatch(d, monkeypatch)
    start(d)
    open_gates(d, monkeypatch, "fine, do it, send it to lantern")
    result = asyncio.run(call(d, "send_to_claude_code", message="Put retries on Redis.", session="lantern"))
    assert "error" in result and "challenge" in result["error"].lower()
    direct = asyncio.run(d._send("Put retries on Redis."))
    assert direct["error"].startswith("Not sent: you are in a challenge; end it first, then say what to send.")
    assert posts == [] and sent == []


@pytest.mark.parametrize("name, args", [("switch_session", {"name": "lantern"}), ("set_mode", {"mode": "session"}),
                                        ("rename_session", {"new_name": "retries"}),
                                        ("disconnect_session", {"name": "lantern"}), ("briefing", {})])
def test_tools_that_act_are_refused(d, c, name, args):
    start(d)
    result = asyncio.run(call(d, name, **args))
    assert "error" in result and "challenge" in result["error"].lower(), result


def test_looking_things_up_is_allowed(d, c, monkeypatch):
    async def record(target, question):
        return {"session": target.name, "answer": "The queue was dropped for lost retries."}

    monkeypatch.setattr(d, "_from_record", record)
    start(d)
    result = asyncio.run(call(d, "ask_about_session", question="Why was the Redis queue dropped?"))
    assert result.get("answer") == "The queue was dropped for lost retries."


def fake_front(d, monkeypatch, steps):
    """The real brain with a scripted model; what it speaks is collected."""
    spoken = []
    front = SimpleNamespace()

    async def push_frame(frame, *a):
        spoken.append(frame.text)

    async def step(choice, instructions, messages, decls):
        return steps.pop(0)

    monkeypatch.setattr(d.vendors, "step", step)
    front.push_frame = push_frame
    front.brain = d.make_brain(lambda text, rid=None: d.BrainFront._speak(front, text, rid))
    d.state.front = front
    return front, spoken


def say(text, i):
    import vendors
    return vendors.Step(calls=[{"id": i, "name": "speak", "args": {"text": text}}])


def test_with_a_fake_model_a_send_attempt_reaches_nothing_and_objections_and_rebuttals_are_recorded(d, c, monkeypatch):
    import vendors
    posts = record_channel(d, monkeypatch)
    sent = record_dispatch(d, monkeypatch)
    front, spoken = fake_front(d, monkeypatch, [
        vendors.Step(calls=[{"id": "a", "name": "send_to_claude_code", "args": {"message": "Move retries to Redis."}}]),
        say("Lantern dropped the Redis queue because it lost 41 retries on restart; your plan brings that back.", "b"),
        say("Then what stops a restart from losing them again?", "c"),
    ])
    start(d)
    opening = fed(c, "[challenge started]")[0]
    asyncio.run(front.brain.turn(opening))
    asyncio.run(d._user_text("We'd persist the queue to disk."))
    asyncio.run(front.brain.turn(None))
    assert posts == [] and sent == []
    assert spoken[0].startswith("Lantern dropped the Redis queue")
    items = d.state.challenge.status()["items"]
    assert [i["kind"] for i in items] == ["objection", "rebuttal", "objection"]
    assert items[1]["text"] == "We'd persist the queue to disk."
    kinds = [n.kind for n in d.NOTES.items]
    assert kinds == ["objection", "rebuttal", "objection"] and all(n.meeting is None for n in d.NOTES.items)


def test_the_context_tells_the_brain_the_rules_on_every_step(d, c):
    start(d)
    context = d._brain_context()
    assert "[challenge]" in context and "never send" in context.lower()


def test_ending_asks_for_the_verdict_and_the_end_words_authorize_no_send(d, c, monkeypatch):
    sent = record_dispatch(d, monkeypatch)
    start(d)
    open_gates(d, monkeypatch, "fine, do it")
    assert asyncio.run(d.end_challenge("ok, you've made your point")) is True
    assert d.state.challenge is None and d.current_mode() is modes.CONVERSATION
    assert len(fed(c, "[challenge ended]")) == 1
    assert "error" in asyncio.run(d._send("Put retries on Redis."))  # "fine, do it" was said during the challenge
    assert sent == []
    open_gates(d, monkeypatch, "send that to lantern")  # a fresh, explicit send after the end goes through the normal gates
    d.state.last_delegation_at = d.state.last_user_speech_at - 1
    assert "error" not in asyncio.run(d._send("Persist the retry queue to disk before moving it to Redis."))
    assert len(sent) == 1


def test_the_verdict_is_recorded_once(d, c, monkeypatch):
    front, spoken = fake_front(d, monkeypatch, [say("Weakest point: restarts; persist the queue first.", "v")])
    start(d)
    asyncio.run(d.end_challenge("verdict"))
    asyncio.run(front.brain.turn(fed(c, "[challenge ended]")[0]))
    last = client_for(d).get("/voice/status").json()["challenge"]
    assert last["on"] is False and last["verdict"] == "Weakest point: restarts; persist the queue first."
    assert d.NOTES.items[-1].kind == "verdict"


def test_spoken_start_and_end_are_caught_in_code(d, c):
    ears = d.SonioxEars()

    async def go():
        await ears._take("challenge this")
        assert d.state.challenge is not None
        await ears._take("back to normal")
        assert d.state.challenge is None
    asyncio.run(go())
    assert len(fed(c, "[challenge started]")) == 1 and len(fed(c, "[challenge ended]")) == 1


def test_typed_start_and_end_work_and_typed_text_never_approves(d, c, monkeypatch):
    posts = record_channel(d, monkeypatch)
    with_permission(c.lantern, "p7", delivered_at=time.time() - 1)
    http = client_for(d)
    assert http.post("/voice/say", json={"text": "challenge me"}).status_code == 200
    assert d.state.challenge is not None
    http.post("/voice/say", json={"text": "yes"})
    assert verdicts(posts) == [] and c.lantern.permission_id == "p7"
    assert http.post("/voice/say", json={"text": "end challenge"}).status_code == 200
    assert d.state.challenge is None


def test_the_end_phrase_never_answers_a_permission(d, c, monkeypatch):
    posts = record_channel(d, monkeypatch)
    start(d)
    with_permission(c.lantern, "p8", delivered_at=time.time() - 1)
    c.lantern.permission_read_at = time.time() - 1
    ears = d.SonioxEars()
    asyncio.run(ears._take("stop"))
    assert verdicts(posts) == [] and c.lantern.permission_id == "p8"


def test_a_yes_after_an_objection_does_not_approve(d, c, monkeypatch):
    posts = record_channel(d, monkeypatch)
    start(d)
    with_permission(c.lantern, "p9", delivered_at=time.time() - 5)
    c.lantern.permission_read_at = time.time() - 5
    d.state.conn.injector.bot_started_at = time.time() - 4
    d._note_bot_speech("Your plan brings back the queue lantern dropped.")  # an objection, not the read-out
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [] and c.lantern.permission_id == "p9"


def test_a_session_report_waits_for_the_end(d, c):
    start(d)
    report = f"[lantern {CC_FINISHED} The outbox suite passes."
    asyncio.run(d.FeedInjector().inject(report, True))  # the real feed: a report is held, not spoken
    assert d.state.monologue_held == [(report, True)]
    asyncio.run(d.end_challenge("stop"))
    texts = [t for t, respond in c.injector.fed if respond]
    assert texts.index(fed(c, "[challenge ended]")[0]) < texts.index(report)


def test_lookup_answers_are_not_held(d, c):
    start(d)
    asyncio.run(d.say("[lantern answered the user's question 'why'] It lost retries."))
    assert fed(c, "[lantern answered")


def test_no_nudges_during_a_challenge(d, c):
    start(d)
    assert not d.current_mode().nudges


def test_cannot_start_in_a_meeting_and_a_meeting_ends_it_silently(d, c):
    d.state.meeting = SimpleNamespace(mode="participating")
    assert "meeting" in start(d).lower()
    assert d.state.challenge is None and not fed(c, "[challenge started]")
    d.state.meeting = None
    start(d)
    d._challenge_off_silently()  # what start_meeting does
    assert d.state.challenge is None and not fed(c, "[challenge ended]")


def test_meeting_start_calls_the_silent_end(d):
    import inspect
    assert "_challenge_off_silently()" in inspect.getsource(d.start_meeting)


def test_a_brainstorm_becomes_the_plan(d, c):
    d._start_monologue("let me think out loud")
    d._keep_thought("We move the ledger cutover to Sunday night and skip the failover drill.")
    ears = d.SonioxEars()
    asyncio.run(ears._take("challenge this"))
    assert d.state.monologue is None and d.state.challenge is not None
    assert "skip the failover drill" in fed(c, "[challenge started]")[0]


def test_the_call_ending_ends_it_without_a_verdict(d, c):
    start(d)
    d._call_ended()
    assert d.state.challenge is None and not fed(c, "[challenge ended]")


def test_the_route(d, c):
    http = client_for(d)
    assert http.post("/voice/challenge", json={"action": "bogus"}).status_code == 400
    assert http.post("/voice/challenge", json={"action": "end"}).status_code == 409
    r = http.post("/voice/challenge", json={"action": "start"})
    assert r.status_code == 200 and r.json()["challenge"]["on"]
    assert http.post("/voice/challenge", json={"action": "start"}).status_code == 409
    r = http.post("/voice/challenge", json={"action": "end"})
    assert r.status_code == 200 and r.json()["challenge"]["on"] is False
    d.state.conn = None
    assert http.post("/voice/challenge", json={"action": "start"}).status_code == 409


def test_another_front_is_refused(d, c, monkeypatch):
    monkeypatch.setattr(d, "FRONT", "gemini")
    assert "brain" in start(d)
