"""An agent's reply while no call is up (docs/design/agents.md, "Turns are asynchronous"): one notification, "<agent>
replied", through the same attention list as every other alert, so the same delivery, quiet rules and privacy apply.
Names only: the reply is the agent's own words and stays in the app and the page. Further replies from the same agent
add no notification until the first is heard on a call or read on a screen. A colleague is never told.

uv run --locked pytest -q tests/test_agent_reply_alerts.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
from fake_secrets import SK_LIVE  # noqa: E402
from harnesses import agent as base  # noqa: E402
from sessions import Session  # noqa: E402
from test_agents_daemon import Stub, _add, world  # noqa: E402,F401
from test_orchestrator import client_for, d  # noqa: E402,F401


class Agent(Stub):
    """A fake agent: each turn finishes with the next of `answers`."""

    def __init__(self, name):
        super().__init__(name)
        self.answers: list[str] = []

    async def wait(self, session, agent, secret, handle):
        return base.Reply(self.answers.pop(0))


class Phone:
    """A fake notifier, as the iPhone app's AlertPlan posts: once per id while away, withdrawn once its id is gone."""

    def __init__(self, client):
        self.client = client
        self.posted: dict[str, dict] = {}
        self.notified: list[dict] = []  # every notification it posted, in order

    def poll(self) -> None:
        items = [a for a in self.client.get("/voice/status").json()["attention"] if a["kind"] == "agent_reply"]
        ids = {a["id"] for a in items}
        self.posted = {k: v for k, v in self.posted.items() if k in ids}
        for a in items:
            if a["id"] not in self.posted and not a["quiet"]:
                self.posted[a["id"]] = a
                self.notified.append(a)


@pytest.fixture
def hermes(world, monkeypatch):
    agent = Agent("hermes")
    monkeypatch.setitem(harnesses._HARNESSES, "hermes", agent)
    session = _add(world, "hermes", "hermes")
    return session, agent


def replies(session, agent, *answers):
    """The user asked, and the agent answered each in the background, with no call up."""
    async def go():
        for answer in answers:
            agent.answers.append(answer)
            assert await agent.send(session, "check the calendar for Friday")
            await asyncio.gather(*agent._running.get(session.id, {}).values())

    asyncio.run(go())


def read(client, name="hermes"):
    r = client.post(f"/voice/agents/{name}/replies", json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_reply_with_no_call_up_is_one_notification_with_the_agents_name_and_none_of_its_words(world, hermes):
    session, agent = hermes
    phone = Phone(client_for(world.d))
    phone.poll()
    assert phone.notified == []
    replies(session, agent, f"Friday is clear. The staging key is {SK_LIVE}, keep it safe.")
    phone.poll()
    (n,) = phone.notified
    assert n["title"] == "hermes replied" and n["session"] == "hermes" and n["approvable"] is False
    assert n["body"] == "Open Pointe to read it."
    text = json.dumps(phone.client.get("/voice/status").json()["attention"])
    assert "Friday" not in text and "sk-live" not in text, "a lock screen shows the agent's name, never its words"


def test_further_replies_wait_under_the_first_notification_until_it_is_read(world, hermes):
    session, agent = hermes
    phone = Phone(client_for(world.d))
    replies(session, agent, "Friday is clear.")
    phone.poll()
    replies(session, agent, "Also, the dentist moved to Monday.", "And the flight is on time.")
    phone.poll()
    assert len(phone.notified) == 1, "one notification for an agent until its first reply is heard or seen"

    shown = read(phone.client)
    assert [r["text"] for r in shown["replies"]] == ["Friday is clear.", "Also, the dentist moved to Monday.",
                                                     "And the flight is on time."]
    assert shown["agent"] == "hermes"
    phone.poll()
    assert phone.posted == {}, "read on a screen: withdrawn"
    assert not session.needs, "read is heard: it no longer waits in what needs me"
    assert read(phone.client)["replies"] == [{"text": "And the flight is on time.", "at": shown["replies"][-1]["at"]}], \
        "opened again with nothing new: the last reply"

    replies(session, agent, "One more thing: the hotel confirmed.")
    phone.poll()
    assert len(phone.notified) == 2 and phone.notified[0]["id"] != phone.notified[1]["id"]
    assert [r["text"] for r in read(phone.client)["replies"]] == ["One more thing: the hotel confirmed."]


def test_heard_at_the_next_call_withdraws_it_and_the_next_reply_notifies_again(world, hermes):
    session, agent = hermes
    phone = Phone(client_for(world.d))
    replies(session, agent, "Friday is clear.")
    phone.poll()
    heard: list[str] = []

    async def feed(s, text, final):
        heard.append(text)

    async def call():
        (watcher,) = agent.watch(session, feed)
        task = asyncio.create_task(watcher)
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(call())
    assert any("Friday is clear." in h for h in heard)
    phone.poll()
    assert phone.posted == {}
    replies(session, agent, "The dentist moved to Monday.")
    phone.poll()
    assert len(phone.notified) == 2


def test_with_a_call_up_a_reply_is_said_on_the_call_and_raises_no_notification(world, hermes):
    session, agent = hermes
    phone = Phone(client_for(world.d))
    session.followed = True  # the call's watcher follows the agent's record
    replies(session, agent, "Friday is clear.")
    phone.poll()
    assert phone.notified == []


def test_a_reply_waits_quietly_while_the_user_is_at_the_mac(world, hermes):
    session, agent = hermes
    replies(session, agent, "Friday is clear.")
    (item,) = [a for a in world.d._attention(quiet=True) if a["kind"] == "agent_reply"]
    assert item["quiet"] is True, "the phone holds it, as every alert, until the user leaves the Mac"


def test_a_colleague_is_never_told_and_cannot_read_it(world, hermes, monkeypatch):
    session, agent = hermes
    replies(session, agent, "Friday is clear.")
    assert session.id in world.d.PEOPLE.people.private
    # Another machine's copy of an agent session (a node, a machine somebody invited you to) never notifies here.
    there = Session(id="agent-juniper", name="juniper", cwd="/tmp", pid=0, transcript="/tmp/none.jsonl", harness="hermes",
                    machine="devbox", needs={"need": base.UNHEARD, "unblock": "what did juniper say"})
    world.d.REGISTRY.add(there)
    assert [a["session"] for a in world.d._attention() if a["kind"] == "agent_reply"] == ["hermes"]
    # A page paired over the private network gets through the listener's guard; the agent's words are still not its.
    monkeypatch.setattr("remote.Remote.on_tls_listener", staticmethod(lambda scope: True))
    monkeypatch.setattr(world.d.REMOTE, "_remote_request", lambda request: True)
    monkeypatch.setattr(world.d.REMOTE, "_paired", lambda request: True)
    refused = client_for(world.d).post("/voice/agents/hermes/replies", json={})
    assert refused.status_code == 403 and "Friday" not in refused.text, "only this Mac's page and the owner's phone"
    assert session.needs, "a refused read is not a read"


def test_reading_an_agent_nobody_connected_is_a_404(world, hermes):
    assert client_for(world.d).post("/voice/agents/juniper/replies", json={}).status_code == 404


def test_a_notification_keeps_its_id_after_a_restart(world, hermes):
    """The liveness probe sets the unheard reply again after a restart; the id stays, so nothing is posted twice."""
    session, agent = hermes
    replies(session, agent, "Friday is clear.")
    before = [a["id"] for a in world.d._attention() if a["kind"] == "agent_reply"]
    session.needs = None
    agent._health[session.id] = (time.time(), "")  # no health check in a test
    asyncio.run(agent.probe(session))
    assert [a["id"] for a in world.d._attention() if a["kind"] == "agent_reply"] == before
