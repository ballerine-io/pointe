"""Agents in the daemon (docs/design/agents.md): the routes the screens and `pointe agent` use, the relay that goes only
on the user's spoken yes, and the guard that keeps a relay from going out as an ordinary send."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agents  # noqa: E402
import harnesses  # noqa: E402
from harnesses import agent as base  # noqa: E402
from harnesses.base import HOST  # noqa: E402
from sessions import Session  # noqa: E402
from test_orchestrator import Params, client_for, d, model_says, open_gates  # noqa: E402,F401


class Stub(base.AgentHarness):
    """An agent kind whose turns finish at once: what the relay and the routes need, no network."""

    approvals = False

    def __init__(self, name):
        super().__init__()
        self.name = self.label = name
        self.agent = name.capitalize()
        self.got: list[tuple[str, str]] = []

    async def submit(self, session, agent, secret, message, turn):
        self.got.append((session.name, message))
        return {"n": len(self.got)}

    async def wait(self, session, agent, secret, handle):
        return base.Reply(f"{session.name} got it.")

    async def check(self, agent, secret):
        if secret != "good-token":
            raise base.AgentError("The gateway refused that token or password.")


@pytest.fixture
def world(d, tmp_path, monkeypatch):
    monkeypatch.setenv("POINTE_AGENTS", "on")
    monkeypatch.setattr(HOST, "state_dir", tmp_path)
    monkeypatch.setattr(HOST, "save_sessions", lambda: None, raising=False)
    kinds = {k: Stub(k) for k in ("openclaw", "hermes")}
    for k, harness in kinds.items():
        monkeypatch.setitem(harnesses._HARNESSES, k, harness)
    store = agents.Store(tmp_path)
    monkeypatch.setattr(d.AGENTS, "store", store)
    monkeypatch.setattr(base, "CONFIG", store.by_session)
    monkeypatch.setattr(base, "SECRET", lambda agent: "good-token")
    monkeypatch.setattr(agents, "save_secret", lambda agent, secret: None)
    monkeypatch.setattr(agents, "delete_secret", lambda agent: None)
    return SimpleNamespace(d=d, kinds=kinds, store=store, tmp=tmp_path)


def _add(w, name, kind):
    w.store.put(agents.Agent(name=name, kind=kind, url="http://127.0.0.1:1"))
    asyncio.run(w.d.AGENTS.register(w.store.get(name)))
    return w.d.REGISTRY.sessions[w.store.get(name).session_id]


def test_adding_an_agent_registers_a_private_session_and_says_where_its_words_go(world):
    client = client_for(world.d)
    refused = client.post("/voice/agents", json={"kind": "openclaw", "name": "openclaw", "url": "http://127.0.0.1:1",
                                                 "secret": "bad-token"})
    assert refused.status_code == 409 and "refused that token" in refused.text and "bad-token" not in refused.text
    assert client.post("/voice/agents", json={"kind": "openclaw", "name": "x", "url": "http://agent.example.com",
                                              "secret": "good-token"}).status_code == 409
    added = client.post("/voice/agents", json={"kind": "openclaw", "name": "openclaw", "url": "http://127.0.0.1:1",
                                               "secret": "good-token"})
    assert added.status_code == 200, added.text
    assert "good-token" not in added.text and "good-token" not in (world.tmp / "agents.json").read_text()
    session = world.d.REGISTRY.sessions["agent-openclaw"]
    assert session.harness == "openclaw" and session.pid == 0 and session.name == "openclaw"
    assert session.id in world.d.PEOPLE.people.private, "an agent is the owner's until shared"
    listed = client.get("/voice/agents").json()
    assert listed["enabled"] and [a["name"] for a in listed["agents"]] == ["openclaw"]
    assert {k["kind"] for k in listed["kinds"]} == set(agents.KINDS)
    status = client.get("/voice/status").json()
    assert status["agent_disclosure"]["agent"] == "openclaw"
    client.post("/voice/agents/seen", json={"name": "openclaw"})
    assert "agent_disclosure" not in client.get("/voice/status").json()
    assert client.post("/voice/agents", json={"kind": "hermes", "name": "openclaw", "url": "http://127.0.0.1:2",
                                              "secret": "good-token"}).status_code == 409, "one name, one agent"
    assert client.delete("/voice/agents/openclaw").status_code == 200
    assert "agent-openclaw" not in world.d.REGISTRY.sessions and world.store.get("openclaw") is None


def test_the_routes_say_the_feature_is_off(world, monkeypatch):
    monkeypatch.setenv("POINTE_AGENTS", "off")
    client = client_for(world.d)
    assert client.get("/voice/agents").json() == {"enabled": False, "agents": [], "kinds": []}
    assert client.post("/voice/agents", json={"kind": "hermes"}).status_code == 409


def test_an_agent_folder_is_never_offered_for_a_new_session(world):
    session = _add(world, "hermes", "hermes")
    assert session.cwd not in world.d.RECENT_FOLDERS.folders()
    assert not any(f["path"] == session.cwd for f in world.d._start_folders())


def _reply(session, text, depth=0):
    harnesses.of(session).reply(session, text, {"turn": "t", "relay": depth})


async def _say(d, said, typed=False):
    await d.on_user_utterance(said, typed=typed)


async def _relay(d, said, typed=False, speak=True):
    if said is not None:
        await _say(d, said, typed)
    p = Params()
    await d.relay_reply(p)
    if speak and "confirm_first" in p.results[0]:
        await model_says(d)
    return p.results[0]


def test_a_relay_is_read_back_and_sent_marked_only_after_a_spoken_yes(world):
    hermes, openclaw = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "The deploy window is Thursday at nine, after the freeze lifts.")

    async def scenario():
        first = await _relay(world.d, "give hermes's answer to openclaw")
        assert first["confirm_first"].startswith("Send hermes's last reply to openclaw? It begins: The deploy window")
        assert world.kinds["openclaw"].got == [], "nothing goes before the yes"
        second = await _relay(world.d, "yes")
        assert second["sent_to"] == ["openclaw"], second

    asyncio.run(scenario())
    (name, message), = world.kinds["openclaw"].got
    assert name == "openclaw" and base.RELAY_MARK in message and "another agent" in message
    assert "<<<BEGIN hermes REPLY>>>\nThe deploy window is Thursday at nine, after the freeze lifts.\n<<<END hermes REPLY>>>" in message
    assert json.loads(base.AgentHarness.mirror_path(openclaw.id).read_text().splitlines()[0])["pointeRelay"] == 1


@pytest.mark.parametrize("answer,typed", [("no", False), ("yes", True), ("what's the weather", False)])
def test_a_relay_without_a_spoken_yes_is_not_sent(world, answer, typed):
    hermes, _ = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "The deploy window is Thursday at nine.")

    async def scenario():
        assert "confirm_first" in await _relay(world.d, "give hermes's answer to openclaw")
        result = await _relay(world.d, answer, typed=typed)
        assert "error" in result and "Not sent" in result["error"], result

    asyncio.run(scenario())
    assert world.kinds["openclaw"].got == []


def test_a_reply_passed_three_times_is_not_passed_again(world):
    hermes, _ = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "Round and round.", depth=3)
    result = asyncio.run(_relay(world.d, "give hermes's answer to openclaw"))
    assert "already been passed between agents 3 times" in result["error"]


def test_a_relay_never_goes_as_an_ordinary_send(world, monkeypatch):
    hermes, openclaw = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "Revenue grew twelve percent while churn stayed flat across every region this quarter.")
    d = world.d
    open_gates(d, monkeypatch, "give hermes's answer to openclaw")
    refused = asyncio.run(d._send("Hermes said revenue grew twelve percent while churn stayed flat across every region"))
    assert "relay_reply" in refused["error"]
    open_gates(d, monkeypatch, "ask openclaw to check the budget")
    d.state.brain_target = "openclaw"
    carried = asyncio.run(d._send("Check this: revenue grew twelve percent while churn stayed flat across every region"))
    assert "relay_reply" in carried["error"], "an agent's words pasted into a send are a relay"
    assert d._relay_refusal("Check the budget for next quarter", openclaw) is None
