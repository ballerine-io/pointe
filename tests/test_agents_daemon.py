"""Agents in the daemon (docs/design/agents.md): the routes the screens and `pointe agent` use, the relay that goes only
on the user's spoken yes, and the guard that keeps a relay from going out as an ordinary send."""

import asyncio
import time
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


def test_the_labs_setting_turns_agents_on_and_off_without_a_restart(world, monkeypatch):
    """The owner's flag was an environment variable (`launchctl setenv`), lost at every reboot. It is a saved setting
    now: turning it on registers the configured agents and gives the brain its relay tool; off takes them off the voice
    and keeps their entries. POINTE_AGENTS, when set, decides instead, and the status says so."""
    d = world.d
    monkeypatch.delenv("POINTE_AGENTS", raising=False)
    monkeypatch.setattr(d, "PREFS", d.Prefs(world.tmp / "prefs.json"))
    monkeypatch.setattr(d.TOOLS, "_standard_tools", list(d.TOOLS.standard_tools))  # the next test gets the import's list
    world.store.put(agents.Agent(name="hermes", kind="hermes", url="http://127.0.0.1:1"))
    client = client_for(d)

    assert client.post("/voice/prefs", json={"agents.on": False}).status_code == 200
    assert "agent-hermes" not in d.REGISTRY.sessions and d.RELAY_TOOL not in d.TOOLS.standard_tools
    assert client.get("/voice/agents").json()["enabled"] is False
    assert client.get("/voice/status").json()["agents_setting"] == {"on": False, "forced": False}

    assert client.post("/voice/prefs", json={"agents.on": True}).json()["agents.on"] is True
    assert "agent-hermes" in d.REGISTRY.sessions, "the configured agent joins at once"
    assert d.RELAY_TOOL in d.TOOLS.standard_tools
    status = client.get("/voice/status").json()
    assert status["agents_setting"] == {"on": True, "forced": False} and status["agents"]["count"] == 1
    assert d.Prefs(world.tmp / "prefs.json").get("agents.on") is True, "saved: it survives a restart"

    client.post("/voice/prefs", json={"agents.on": False})
    assert "agent-hermes" not in d.REGISTRY.sessions and world.store.get("hermes") is not None
    assert d.RELAY_TOOL not in d.TOOLS.standard_tools

    monkeypatch.setenv("POINTE_AGENTS", "on")
    assert client.get("/voice/status").json()["agents_setting"] == {"on": True, "forced": True}
    client.post("/voice/prefs", json={"agents.on": False})
    assert client.get("/voice/agents").json()["enabled"] is True, "the environment wins over the saved setting"


def test_agents_on_with_none_configured_cost_the_brain_nothing(world, monkeypatch):
    """On by default must be inert for who has no agent: no agent rules, no relay tool in the brain's input until one
    is added, and none again once the last is removed."""
    d = world.d
    monkeypatch.setattr(d.TOOLS, "_standard_tools", list(d.TOOLS.standard_tools))
    client = client_for(d)
    d.AGENTS.changed()
    assert d.agents.enabled() and not d._agents_in_use() and d.RELAY_TOOL not in d.TOOLS.standard_tools
    added = client.post("/voice/agents", json={"kind": "hermes", "name": "hermes", "url": "http://127.0.0.1:1",
                                               "secret": "good-token"})
    assert added.status_code == 200, added.text
    assert d._agents_in_use() and d.RELAY_TOOL in d.TOOLS.standard_tools
    assert client.delete("/voice/agents/hermes").status_code == 200
    assert not d._agents_in_use() and d.RELAY_TOOL not in d.TOOLS.standard_tools


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


def test_an_agents_finished_turn_answers_the_question_that_started_it(world, monkeypatch):
    """Live run: "ask openclaw what the capital of Portugal is" was answered ("Lisbon"), but the reader listed no order as
    confirmed, so the next call greeted with "Still waiting on openclaw's answer". An agent's turn is the answer to the
    request that started it: nothing is still out once it ends and no other turn of it runs."""
    from brief import FINAL_MARK

    async def read(system, prompt, thinking=None):
        return {"status": "done", "urgency": "normal", "say": "Lisbon.", "line": "Lisbon.", "speak": True, "waiting": False,
                "orders_confirmed": []} if "ended its turn" in system else {}

    monkeypatch.setattr(world.d, "_read_model", read)
    openclaw = _add(world, "openclaw", "openclaw")
    world.d.state.unconfirmed[openclaw.id] = ["What is the capital of Portugal? One sentence?"]
    world.d.state.last_delegation_at = __import__("time").time()
    asyncio.run(world.d._digest_turn(openclaw, f"[openclaw finished its turn] {FINAL_MARK}Lisbon."))
    assert not world.d.state.unconfirmed.get(openclaw.id)
    assert "Still waiting" not in (world.d.fixed_greeting() or "")


def test_the_same_reply_goes_to_the_same_agent_once_in_ten_minutes(world):
    hermes, openclaw = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "The deploy window is Thursday at nine.")

    async def scenario():
        await _relay(world.d, "give hermes's answer to openclaw")
        assert (await _relay(world.d, "yes"))["sent_to"] == ["openclaw"]
        return await _relay(world.d, "give hermes's answer to openclaw again")

    assert "got this same reply" in asyncio.run(scenario())["error"]
    assert len(world.kinds["openclaw"].got) == 1
    text = "The deploy window is Thursday at nine."
    assert world.d.RELAYS.repeated(openclaw.id, text)
    assert not world.d.RELAYS.repeated(openclaw.id, text, now=__import__("time").time() + 601), "ten minutes later it may go"


def test_with_the_voice_lock_on_a_yes_not_clearly_the_owners_relays_nothing(world, monkeypatch):
    hermes, _ = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "The deploy window is Thursday at nine.")
    monkeypatch.setattr(world.d, "lock_level", lambda: "approvals")
    monkeypatch.setattr(world.d.VOICE, "confident", lambda verdict: False)

    async def scenario():
        await _relay(world.d, "give hermes's answer to openclaw")
        return await _relay(world.d, "yes")

    assert "not clearly the owner's voice" in asyncio.run(scenario())["error"]
    assert world.kinds["openclaw"].got == []


def test_one_yes_sends_one_hop_and_a_late_or_unasked_yes_sends_nothing(world):
    hermes, _ = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "The deploy window is Thursday at nine.")
    d = world.d

    async def scenario():
        await _relay(d, "give hermes's answer to openclaw")
        assert (await _relay(d, "yes"))["sent_to"] == ["openclaw"]
        again = await _relay(d, "yes")  # the same yes cannot carry a second hop
        assert "error" in again, again
        unasked = await _relay(d, None)  # the model calls it again with nothing new said
        assert "error" in unasked, unasked
        _reply(hermes, "Friday works too.")
        await _relay(d, "give hermes's answer to openclaw")
        d.state.pending_relay = (d.state.pending_relay[0] - d.agent_relay.CONFIRM_SECS - 1, d.state.pending_relay[1])
        late = await _relay(d, "yes")
        assert "error" in late, late

    asyncio.run(scenario())
    assert len(world.kinds["openclaw"].got) == 1


def test_a_reply_passed_twice_still_asks_before_its_third_hop(world):
    hermes, _ = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")
    _reply(hermes, "Round and round.", depth=2)
    assert "confirm_first" in asyncio.run(_relay(world.d, "give hermes's answer to openclaw"))


def test_only_the_owner_reaches_the_agent_routes(world, monkeypatch):
    """A person's key (a voice linked over the TLS listener, not the owner's phone) is refused on every agents route,
    not only on reading the replies (tests/test_agent_reply_alerts.py)."""
    _add(world, "hermes", "hermes")
    monkeypatch.setattr("remote.Remote.on_tls_listener", staticmethod(lambda scope: True))
    monkeypatch.setattr(world.d.REMOTE, "_remote_request", lambda request: True)
    monkeypatch.setattr(world.d.REMOTE, "_paired", lambda request: True)
    client = client_for(world.d)
    for got in (client.get("/voice/agents"),
                client.post("/voice/agents", json={"kind": "openclaw", "name": "x", "url": "http://127.0.0.1:1", "secret": "good-token"}),
                client.post("/voice/agents/seen", json={"name": "hermes"}),
                client.delete("/voice/agents/hermes")):
        assert got.status_code == 403 and "hermes" not in got.text, (got.request.method, got.request.url.path, got.text)
    assert world.store.get("hermes") is not None and world.store.get("x") is None

@pytest.mark.parametrize("said", ["דבר עם הרמס", "תעבור להרמס", "talk to hermes"])
def test_talk_to_an_agent_in_hebrew_focuses_on_it_and_orchestrator_mode_leaves_it(world, said):
    """The owner's "דבר עם הרמס" was refused as "the user did not ask to switch": no Hebrew switch word, and the ears
    wrote the name in Hebrew letters."""
    d = world.d
    hermes, _ = _add(world, "hermes", "hermes"), _add(world, "openclaw", "openclaw")

    async def scenario():
        now = time.time()
        d.state.last_utterance, d.state.last_user_speech_at, d.state.last_switch_at = said, now, now - 30
        p = Params(name="hermes")
        await d.switch_session(p)
        return p.results[0]

    result = asyncio.run(scenario())
    assert result.get("active") == hermes.name and result.get("mode") == "session", result
    assert d.mode_intent("תחזור למצב מתזמר", list(d.REGISTRY.sessions.values())) == "orchestrator"
