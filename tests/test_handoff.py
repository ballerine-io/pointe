"""Moving the call to another machine the client holds, by voice (docs/design/multi-machine-clients.md, 1.4). Decided
in code, never by the model: "call kite" moves the call when the client listed kite in its hello; "go to kite" keeps
its old meaning (a session there) when this voice links kite; a machine the client does not hold gets one sentence."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pointe"))
import handoff  # noqa: E402

PHONE = [{"id": "m1", "name": "studio"}, {"id": "m2", "name": "kite"}, {"id": "m3", "name": "avi-box"}]


def test_call_names_a_machine_the_client_holds_and_moves_the_call_there():
    for said in ("call kite", "Call kite.", "move the call to kite", "please hand me over to kite", "take me to kite",
                 "move me to Kite"):
        assert handoff.intent(said, PHONE, linked=set(), here="m1") == ("move", {"id": "m2", "name": "kite"}), said
    assert handoff.intent("call avi box", PHONE, linked=set(), here="m1") == ("move", {"id": "m3", "name": "avi-box"})


def test_go_to_a_machine_this_voice_links_keeps_meaning_its_session():
    assert handoff.intent("go to kite", PHONE, linked={"kite"}, here="m1") is None
    assert handoff.intent("switch to kite", PHONE, linked=set(), here="m1") == ("move", {"id": "m2", "name": "kite"})
    assert handoff.intent("call kite", PHONE, linked={"kite"}, here="m1")[0] == "move", "call always means the call"


def test_the_machine_already_on_the_call_and_one_the_client_does_not_hold():
    assert handoff.intent("call studio", PHONE, linked=set(), here="m1") == ("here", {"id": "m1", "name": "studio"})
    assert handoff.intent("call devbox", PHONE, linked={"devbox"}, here="m1") == ("unpaired", {"id": "", "name": "devbox"})
    assert handoff.intent("call devbox", PHONE, linked=set(), here="m1") is None, "not a machine anyone knows: not ours"


def test_words_that_only_mention_a_machine_or_come_from_an_older_client_move_nothing():
    for said in ("tell kite to pull", "what's on kite", "fix the kite config", "call the tests on kite", "recall kite"):
        assert handoff.intent(said, PHONE, linked=set(), here="m1") is None, said
    assert handoff.intent("call kite", [], linked=set(), here="m1") is None


def test_what_it_says():
    assert handoff.line("move", "kite") == "Moving you to kite."
    assert handoff.line("here", "studio") == "You're on studio already."
    assert handoff.line("unpaired", "devbox") == "This phone is not paired with devbox. Add it in Machines, on the phone."


def test_the_hello_list_is_cleaned_before_it_is_used():
    raw = [{"id": "m2", "name": "kite"}, {"id": "../x", "name": "a" * 500}, "junk", {"name": "no-id"}] + [{"id": f"x{i}", "name": f"n{i}"} for i in range(40)]
    got = handoff.machines(raw)
    assert got[0] == {"id": "m2", "name": "kite"} and len(got) <= handoff.MAX_MACHINES
    assert all(len(m["name"]) <= 60 and m["id"] != "../x" for m in got)
    assert handoff.machines(None) == [] and handoff.machines("kite") == []


# ---------- on a call (the daemon) ----------

from types import SimpleNamespace  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mute import _call, _ears  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (a fixture)


def _holding(d, machines):
    sock = _call(d)
    d.state.call_client = SimpleNamespace(client={"device": "iPhone", "machines": machines})
    return sock


def test_said_on_a_call_it_says_the_line_and_tells_the_device_where_to_dial(d, monkeypatch):
    sock = _holding(d, [{"id": d.HUB.nodes.hub_id, "name": "studio"}, {"id": "m2", "name": "kite"}])
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("call kite"))
    assert said == ["Moving you to kite."] and not reached, "decided in code: the brain never gets it"
    assert sock.sent[-1] == {"type": "handoff", "machine": {"id": "m2", "name": "kite"}}


def test_typed_it_moves_the_call_too_and_the_machine_on_the_call_moves_nothing(d, monkeypatch):
    sock = _holding(d, [{"id": d.HUB.nodes.hub_id, "name": "studio"}, {"id": "m2", "name": "kite"}])
    _, _, said = _ears(d, monkeypatch)
    asyncio.run(d._user_text("call studio"))
    assert said == ["You're on studio already."] and not any(m.get("type") == "handoff" for m in sock.sent)
    asyncio.run(d._user_text("move the call to kite"))
    assert sock.sent[-1]["type"] == "handoff"


def test_a_device_that_lists_no_machines_is_never_moved(d, monkeypatch):
    sock = _holding(d, None)
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("call kite"))
    assert not said and not any(m.get("type") == "handoff" for m in sock.sent)


def test_the_call_keeps_the_machines_a_hello_lists_and_never_its_token():
    import phone
    s = phone.PhoneSerializer(phone.Heartbeat())
    hello = {"type": "hello", "protocol": 5, "device": "iPhone", "resume": "secret-token", "machines": [{"id": "m2", "name": "kite"}]}
    asyncio.run(s.deserialize(__import__("json").dumps(hello)))
    assert s.client == {"protocol": 5, "device": "iPhone", "machines": [{"id": "m2", "name": "kite"}]}
