"""The fleet benchmark's turns, replayed offline against a fleet of its shape: 5 machines of 20 sessions, 10 of 30,
with "shop", "api" and "web" on several machines, joined in the simulator's order. The paid runs of 2026-11-26 sent 15
of 100 clear turns to the wrong session with the fleet rules on; every one was decided by code, not by a model, and
each cause has its row here. Then every turn whose outcome code alone decides must come out by rule, whatever the
brain names and whatever the conversation was about: on a fleet made here by the benchmark's rules, and on the
benchmark's own frozen dataset when this checkout has it (bench/fleet/dataset). Nothing here calls a model.

uv run --locked pytest -q tests/test_fleet_dataset_routing.py
"""

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scale  # noqa: E402
import sessions as sessions_mod  # noqa: E402
from test_mixed_harnesses import node  # noqa: E402,F401  (a fixture)
from test_orchestrator import Params, add, d, fake_conn, open_gates, record_dispatch  # noqa: E402,F401

DATASET = ROOT / "bench" / "fleet" / "dataset"
FROZEN = {"fleet-5x20.json": "69534134ec5f963b3c89991a5bba747cceced77d8b443e3f9a49d485f1ed0964",
          "turns-5x20.json": "9b3d35443b7ae2da381c2a2fe9612869f0c1316de85ea94f18bc9af6078eb4bd",
          "fleet-1x4.json": "7c36b40a112e9cb472dcc2b034f7f2d0ea7a317e9c7e5245a5dca535e340a584",
          "turns-1x4.json": "398a5954689f67a4d77aa4ca3cce6739459eb6c9422c2772aa69b257fa61e084",
          "fleet-10x30.json": "275e6af100aa9fd2cebc2422e98aa0080a3c68be3331f72ff935454a883bc889",
          "turns-10x30.json": "78717476a6af70010a135eb4fa5955a3da864b5690358cb8292fcf0a69516002"}  # bench/fleet/FROZEN.json


MACHINES = "studio avi-box dana-rig omer-lab noa-mini lior-tower maya-node eitan-rack tamar-nuc gil-cube".split()
SHARED = {"shop": [0, 1, 2, 3], "api": [1, 2, 3], "web": [2, 3, 4]}  # the name, and the machines that have one
THINGS = ("receipt roster quota banner payroll pallet badge parcel ticket rebate permit stipend ballot freight "
          "tenant ration docket levy").split()
PARTS = ("digest sampler batcher resolver watchdog exporter validator importer notifier scheduler throttle "
         "archiver indexer planner tracker mapper splitter merger").split()
TASKS = ["rebase onto main", "run the tests", "bump the patch version", "sort the imports", "count the failing tests",
         "check the code coverage", "list the open TODO comments", "print the last commit message"]


def _names(n: int) -> list[str]:
    """n made-up names no two of which the daemon hears as one word, nor as a machine's or a shared name."""
    taken = [w for m in MACHINES for w in m.split("-")] + list(SHARED) + ["nimbus", "drizzle"]
    taken += [w for t in TASKS for w in t.split() if len(w) > 2] + ["again", "session", "working", "whoever"]
    out: list[str] = []
    made_of = [(a, v, b, w, e) for a in "bdfgklmnprstvz" for v in "aeiou" for b in ("lk", "mb", "nd", "rg", "sk", "zt", "lv", "rp", "nx")
               for w in "oaiue" for e in "rnslmx"]
    for k in range(len(made_of)):
        name = "".join(made_of[k * 7919 % len(made_of)])  # far apart in the list: unlike the one before
        if not any(sessions_mod._hears(t, name) or sessions_mod._hears(name, t) or sessions_mod._alike(t, name) for t in taken + out):
            out.append(name)
        if len(out) == n:
            return out
    raise AssertionError("not enough names")


def made(hosts: int, per: int) -> tuple[dict, list[dict]]:
    """A fleet and its turns by the benchmark's rules (bench/fleet/gen.py, turns.py), with names made here: the same
    kinds of turn, labelled from the fleet's description alone."""
    machines = MACHINES[:hosts]
    names = iter(_names(hosts * per))
    topics = iter([f"{a} {b}" for b in PARTS for a in THINGS])
    sessions = []
    for m, machine in enumerate(machines):
        shared = [n for n, on in SHARED.items() if m in on]
        for i in range(per):
            name = shared[i] if i < len(shared) else next(names)
            sessions.append({"id": f"{m:02d}{i:02d}-{name}", "machine": machine, "name": name, "shared": name in SHARED,
                             "topic": next(topics), "twin": False})
    plain = [s for s in sessions if not s["shared"]]
    for a, b in ((3, per + 5), (7, 2 * per + 9)) if hosts > 2 else ():  # two topics that two sessions share
        plain[b]["topic"], plain[a]["twin"], plain[b]["twin"] = plain[a]["topic"], True, True
    for s in sessions:
        s["goal"] = f"Find why the {s['topic']} drops records under load and fix it."
        s["files"] = [s["topic"].replace(" ", "_") + ".py", "test_" + s["topic"].replace(" ", "_") + ".py", "README.md"]
    turns: list[dict] = []
    task = iter(TASKS * 20)

    def add(kind: str, text: str, expect: dict, **more) -> None:
        turns.append({"id": f"{kind}-{sum(t['kind'] == kind for t in turns):02d}", "kind": kind, "text": text, "expect": expect, **more})

    single = [s for s in plain if not s["twin"]]
    for s in single[::max(1, len(single) // 12)][:12]:
        add("clear_name", f"Tell {s['name']} to {next(task)}.", {"action": "send", "session": s["id"]})
    for s in [s for s in sessions if s["shared"]]:
        add("clear_machine_name", f"Ask {s['name']} on {s['machine']} to {next(task)}.", {"action": "send", "session": s["id"]})
    for n, s in enumerate(single[5::max(1, len(single) // 12)][:12]):
        text = f"Tell the session working on the {s['topic']} to {next(task)}." if n % 2 == 0 else \
            f"Ask whoever has {s['files'][0]} to {next(task)}."
        add("clear_description", text, {"action": "send", "session": s["id"]})
    for name, on in SHARED.items():
        for verb in ("Tell", "Ask"):
            add("ambiguous_name", f"{verb} {name} to {next(task)}.",
                {"action": "ask", "fits": [s["id"] for s in sessions if s["name"] == name]}, this_mac_holds=0 in on)
    for s in [s for s in plain if s["twin"]][:2]:
        add("ambiguous_description", f"Tell the session working on the {s['topic']} to {next(task)}.",
            {"action": "ask", "fits": [o["id"] for o in sessions if o["topic"] == s["topic"]]})
    for text in ("Tell nimbus to {}.", "Ask drizzle to {}.", "Ask the session working on the passport scanner to {}.",
                 "Tell the session working on the elevator firmware to {}."):
        add("ambiguous_none", text.format(next(task)), {"action": "ask", "fits": []})
    return {"machines": machines, "voice_machine": machines[0], "shared_names": {n: [machines[i] for i in on if i < hosts] for n, on in SHARED.items()},
            "sessions": sessions}, turns


def load(size: str) -> tuple[dict, list[dict]]:
    """"5x20": the fleet made here. "frozen-5x20": the benchmark's own files, when this checkout has them. They are
    not on main yet: some of their names are also names in the conversational benchmark's fixtures, which
    tests/test_conversational_routing.py refuses under tests/ and bench/."""
    if not size.startswith("frozen-"):
        return made(*map(int, size.split("x")))
    size = size.removeprefix("frozen-")
    files = [DATASET / f"fleet-{size}.json", DATASET / f"turns-{size}.json"]
    if not all(f.exists() for f in files):
        pytest.skip(f"bench/fleet/dataset has no {size} files in this checkout")
    assert all(hashlib.sha256(f.read_bytes()).hexdigest() == FROZEN[f.name] for f in files), "not the frozen dataset"
    return json.loads(files[0].read_text()), json.loads(files[1].read_text())


def test_the_fleet_made_here_has_the_benchmarks_shape():
    described, turns = made(5, 20)
    assert len(described["sessions"]) == 100 and len({s["name"] for s in described["sessions"]}) == 100 - 10 + 3
    assert described["shared_names"]["shop"] == ["studio", "avi-box", "dana-rig", "omer-lab"]
    kinds = [t["kind"] for t in turns]
    assert {k: kinds.count(k) for k in sorted(set(kinds))} == {
        "ambiguous_description": 2, "ambiguous_name": 6, "ambiguous_none": 4, "clear_description": 12,
        "clear_machine_name": 10, "clear_name": 12}
    assert len(made(10, 30)[0]["sessions"]) == 300


class Rig:
    """The dataset's fleet in the daemon's registry, joined in the simulator's order (this machine's sessions first),
    and one user turn at a time through the code a call runs: the send without a model step when the words allow one,
    else the brain's send_to_claude_code with whatever session the brain named."""

    def __init__(self, d, node, monkeypatch, size: str):  # noqa: F811
        self.d, self.monkeypatch = d, monkeypatch
        self.described, self.turns = load(size)
        d.REGISTRY.sessions.clear()
        d.REGISTRY.active_id = None
        monkeypatch.setenv("POINTE_FLEET", "on")
        monkeypatch.setattr(d, "_add_worker", lambda s: asyncio.sleep(0))
        monkeypatch.setattr(d, "_refresh_brief", lambda s: asyncio.sleep(0))  # the reading model is never called here
        files: dict[str, list[str]] = {}
        monkeypatch.setattr(d, "_git_files", lambda cwd, timeout: "\0".join(files.get(cwd, [])))
        node.machines.clear()
        for i, m in enumerate(self.described["machines"][1:]):
            node.machines[m] = sessions_mod.Machine(name=m, id=f"n{i:07d}", os="linux", online=True, rtt_ms=20 + i)
        self.by_id = {}
        for s in self.described["sessions"]:
            if s["machine"] == self.described["voice_machine"]:
                one = add(d, s["id"], s["name"], f"/work/{s['id'][:8]}", named_by="user")
                files[one.cwd] = s["files"]
            else:
                body = {"id": s["id"], "name": s["name"], "cwd": f"/work/{s['id'][:8]}", "pid": 4242,
                        "harness": "claude-code", "files": s["files"]}
                one = asyncio.run(d.register_remote(node.machines[s["machine"]].id, s["machine"], body))
            one.joining = False
            assert scale.base_name(one.name, one.machine) == s["name"] or size.startswith("frozen-"), (s["name"], one.name)
            one.brief = {"goal": s["goal"], "state": "Idle."}
            self.by_id[s["id"]] = one
        self.sent = record_dispatch(d, monkeypatch)
        self.model: list[list[str]] = []  # the sessions each classifier call was shown
        self.answer = None  # what the classifier says; None is "unclear"

        async def classify(message, sessions, tie=False):
            self.model.append([s.name for s in sessions])
            return self.answer
        monkeypatch.setattr(d, "_classify_target", classify)

    def turn(self, text: str, brain: str | None = None, fast: bool = True, talking_with: str | None = None) -> dict:
        """One turn in a fresh call. `brain`: the session the brain names in its send. `talking_with`: the session of
        the conversation so far (the thread), as after an earlier send. Returns what happened."""
        d = self.d
        d.state = d.State()
        d.state.conn = fake_conn()
        self.sent.clear(), self.model.clear()
        if talking_with:
            d.state.thread = (talking_with, time.time())
        d.state.fleet_ask = (time.time(), list(d.REGISTRY.sessions))  # a "which machine?" from an earlier turn, still open
        open_gates(d, self.monkeypatch, text)
        quick = d._fast_send(text) if fast and d._may_fast_send() else None
        if quick is not None:
            return {"to": quick[0], "ask": None, "how": "no model step", "model": []}
        message = text.split(" to ", 1)[-1]
        p = Params(message=message[0].upper() + message[1:], **({"session": brain} if brain else {}))
        asyncio.run(d.send_to_claude_code(p))
        to = next((s for s in d.REGISTRY.sessions.values() if self.sent and s.name == self.sent[0][0]), None)
        return {"to": to, "ask": p.results[0].get("ask"), "error": p.results[0].get("error"), "model": list(self.model)}

    def named(self, name: str, machine: str):
        return next(s for s in self.by_id.values() if scale.base_name(s.name, s.machine) == name
                    and (s.machine or self.described["voice_machine"]) == machine)

    def elsewhere(self, *not_these):
        """A session to be talking with that the turn is not about: one with a name of its own, on another machine."""
        own = [s for s in self.by_id.values() if s not in not_these
               and scale.base_name(s.name, s.machine) not in self.described["shared_names"]]
        return next((s for s in own if s.machine), own[0])


@pytest.fixture
def rig(d, node, monkeypatch):  # noqa: F811
    return Rig(d, node, monkeypatch, "5x20")


# ---------- the failing rows of the paid runs, each with its cause ----------

def test_api_on_omer_lab_goes_to_omer_labs_api_on_every_path(rig):
    """clear_machine_name-02 (on-r2 order 14, on-r3 order 58): "Sent to api.", on avi-box, the first api to join."""
    for brain, fast in ((None, True), ("api", True), ("api", False), ("api dana-rig", False)):
        got = rig.turn("Tell api on omer-lab to say how long the test suite takes.", brain=brain, fast=fast)
        assert got["to"] is rig.named("api", "omer-lab") and got["model"] == [], (brain, fast)


def test_shop_on_avi_box_goes_to_avi_boxs_shop_whatever_the_brain_names(rig):
    """clear_machine_name-03 (on-r2 order 48, on-r3 order 19): "Sent to shop.", this machine's. The brain is told only
    the sessions in focus, so it names "shop", and its pick was taken although the words say avi-box."""
    for brain in (None, "shop", "shop dana-rig"):
        got = rig.turn("Ask shop on avi-box to add a timeout to the network call.", brain=brain, fast=False)
        assert got["to"] is rig.named("shop", "avi-box") and got["model"] == [], brain


def test_the_plain_api_named_with_its_own_machine_is_that_one_and_not_every_session_there(rig):
    """clear_machine_name-00 and -07 (asked in all three runs, and with the rules off): "Tell api on avi-box" tied
    every session on avi-box, each heard by the machine's two words against the plain "api"'s one."""
    everyone = list(rig.d.REGISTRY.sessions.values())
    api = rig.named("api", "avi-box")
    assert api.name == "api"  # the first to join kept the plain name
    assert sessions_mod.name_groups("Tell api on avi-box to add type hints to the public functions.", everyone) == [[api]]
    assert sessions_mod.name_groups("on avi-box, run the tests", everyone)[0].__len__() == 20  # the machine alone: all of it
    for fast in (True, False):
        got = rig.turn("Tell api on avi-box to add type hints to the public functions.", brain="api", fast=fast)
        assert got["to"] is api and got["model"] == []
    got = rig.turn("Ask web on dana-rig to show the size of the largest file.")
    assert got["to"] is rig.named("web", "dana-rig")


def test_api_with_no_machine_is_asked_by_code_on_every_path(rig):
    """ambiguous_name-00, -03 (on-r2 order 38; on-r3 orders 29, 31): "Sent to api." The send without a model step and
    the brain's pick both took the plain name for the one session of that name."""
    for brain, fast in ((None, True), (None, False), ("api", False), ("api omer-lab", False)):
        got = rig.turn("Tell api to check that the README matches the code.", brain=brain, fast=fast)
        assert got["to"] is None and got["model"] == [], (brain, fast)
        assert got["ask"] == "Api: on avi-box, on dana-rig or on omer-lab?"
    got = rig.turn("How many tests failed in api?")  # a question put to it with no model step: the same tie
    assert got["to"] is None


def test_my_own_shop_on_this_machine_still_keeps_the_plain_name(rig):
    """ambiguous_name-01, -04: the dataset labels them "ask", and its notes say the daemon's rule sends them to this
    machine's shop. The rule stands (a session of the user's on this machine keeps the plain name)."""
    got = rig.turn("Ask shop to print the last commit message.")
    assert got["to"] is rig.named("shop", "studio")


def test_words_for_a_session_that_does_not_exist_never_go_to_the_session_talked_with(rig):
    """ambiguous_none-00 (on-r1 order 32: "That went to oasis, not nimbus"), -02, -01, -03 (on-r3 orders 9, 23, 33, 34).
    No session matched, the classifier said unclear, and the request went to the thread. The thread is what flipped
    run to run: before the first send of a call there is none and the turn was asked."""
    other = rig.elsewhere()
    for text in ("Tell nimbus to count the failing tests.", "Tell drizzle to check the code coverage.",
                 "Ask the session working on the passport scanner to say which function is the longest."):
        for talking_with in (None, other.id):
            for brain in (None, other.name):
                got = rig.turn(text, brain=brain, talking_with=talking_with)
                assert got["to"] is None and got["model"] == [], (text, talking_with, brain)
                assert got["ask"] == "I found no session like that. Which machine is it on?"
    assert rig.d.state.fleet_route["matched"] is False and rig.d.state.fleet_route["who"]
    got = rig.turn("And bump the minor version too.", talking_with=other.id)  # words for nobody else: the conversation's session
    assert got["to"] is other


def test_a_description_two_sessions_fit_is_asked_when_the_model_is_not_sure(rig):
    """ambiguous_description-03 (on-r3 order 2: "That went to rye, not magpie"), -01, -02 (orders 26, 42): the
    classifier said unclear and the request went to the thread or the active session."""
    turn = next(t for t in rig.turns if t["id"] == "ambiguous_description-01")
    other = rig.elsewhere()
    got = rig.turn(turn["text"], talking_with=other.id)
    assert got["to"] is None and len(got["model"]) == 1
    assert {rig.by_id[i].name for i in turn["expect"]["fits"]} <= set(got["model"][0])  # both were shown to it


def test_a_machine_answer_left_open_by_one_turn_does_not_answer_another(rig):
    d = rig.d
    rig.turn("Tell api to check that the README matches the code.", fast=False)
    assert d.state.fleet_ask is not None
    assert asyncio.run(d._route("x", "Omer-lab."))[0] == [rig.named("api", "omer-lab")]
    assert d.state.fleet_ask is None  # answered once
    assert asyncio.run(d._route("x", "Omer-lab."))[1] != "answered"


def BIG(size: str):
    """A fleet size whose test takes 10 to 80 s on CI: slow, so tools/test-changed leaves it to CI (conftest.py)."""
    return pytest.param(size, marks=pytest.mark.slow)


# ---------- the whole frozen dataset: what code alone decides ----------

BY_CODE = ("clear_name", "clear_machine_name", "ambiguous_name", "ambiguous_none")


@pytest.mark.parametrize("size", ["1x4", BIG("5x20"), BIG("10x30"), "frozen-1x4", BIG("frozen-5x20"), BIG("frozen-10x30")])
def test_every_turn_code_alone_decides_comes_out_by_rule(d, node, monkeypatch, size):  # noqa: F811
    """Named, machine-named, one name on several machines, and nothing matches: the labelled outcome on every path (with
    and without a model step), whatever session the brain names (none, the bare name, a same-named session on another
    machine, the session talked with) and whatever the conversation was about. The classifier is never called."""
    rig = Rig(d, node, monkeypatch, size)
    here = rig.described["voice_machine"]
    checked, alike = 0, []
    for t in rig.turns:
        if t["kind"] not in BY_CODE:
            continue
        want = rig.by_id[t["expect"]["session"]] if t["expect"]["action"] == "send" else None
        heard = sessions_mod.name_groups(t["text"], list(d.REGISTRY.sessions.values()))
        if want is not None and any(len({scale.base_name(s.name, s.machine) for s in g}) > 1 for g in heard):
            alike.append(t["id"])  # two names the daemon hears as one word: its rule is to ask which, in any fleet
            want = None
        if t.get("this_mac_holds"):  # labelled "ask"; the daemon's rule is this machine's own session (turns.py says so)
            want = rig.named(t["text"].split()[1], here)
        # A description nobody fits, on a fleet small enough for the model to see every session: the model is asked
        # once ("the frontend one" may be a session no word of which says frontend), and its "unclear" is asked by
        # code. A name nobody has is asked with no model at every size.
        described = len(rig.by_id) <= scale.CANDIDATES_MAX and t["kind"] == "ambiguous_none" and " working on " in t["text"]
        other = rig.elsewhere(want)
        word = t["text"].split()[1]
        twins = [s.name for s in rig.by_id.values() if scale.base_name(s.name, s.machine) == word and s is not want]
        for talking_with in (None, other.id):
            for fast in (True, False):
                for brain in [None, word, other.name, *twins[:2]] if not fast else [None, word]:
                    got = rig.turn(t["text"], brain=brain, fast=fast, talking_with=talking_with)
                    assert got["to"] is want, (t["id"], t["text"], brain, fast, talking_with, got["to"] and got["to"].name)
                    if described:
                        assert len(got["model"]) <= 1, (t["id"], brain)
                    else:
                        assert got["model"] == ([] if t["id"] not in alike else [[s.name for s in heard[0]]]), (t["id"], brain)
                    assert want is not None or got["ask"], (t["id"], got)  # asked in the daemon's own words
                    checked += 1
    assert checked >= 8 * sum(t["kind"] in BY_CODE for t in rig.turns)  # each turn on eight or more paths
    # The frozen 10x30 has one pair the daemon hears alike (two names a letter apart, on one machine): asked, by rule.
    assert alike == (["clear_name-07"] if size == "frozen-10x30" else [])


@pytest.mark.parametrize("size", ["5x20", BIG("10x30"), "frozen-5x20", BIG("frozen-10x30")])
def test_a_description_narrows_to_its_session_and_the_models_pick_of_it_is_sent(d, node, monkeypatch, size):  # noqa: F811
    """clear_description is the model's to pick (stage two). Stage one is code's: the session is among the eight, in
    every turn, also in a conversation about another session. When the model picks it, it is sent: a file or a topic
    only that session has points at it, so it is not asked again because the talk was about another. When the model is
    not sure, the request is asked and never sent to the session talked with."""
    rig = Rig(d, node, monkeypatch, size)
    for t in rig.turns:
        if t["kind"] not in ("clear_description", "ambiguous_description"):
            continue
        clear = t["kind"] == "clear_description"
        fits = [rig.by_id[t["expect"]["session"]]] if clear else [rig.by_id[i] for i in t["expect"]["fits"]]
        other = rig.elsewhere(*fits)
        rig.answer = None
        got = rig.turn(t["text"], talking_with=other.id)
        assert len(got["model"]) == 1 and len(got["model"][0]) <= scale.CANDIDATES_MAX, t["id"]
        assert {s.name for s in fits} <= set(got["model"][0]), (t["id"], got["model"])
        assert got["to"] is None  # unclear: asked
        if clear:
            rig.answer = fits[0]
            assert rig.turn(t["text"], talking_with=other.id)["to"] is fits[0], t["id"]
        else:
            rig.answer = fits[0]  # the model guesses one of the two: the words fit the other as well, so it is asked
            assert rig.turn(t["text"], talking_with=other.id)["to"] is None, t["id"]
    rig.answer = None


@pytest.mark.parametrize("size", ["5x20", "10x30"])
def test_a_send_routed_by_its_description_is_acknowledged_in_code_on_a_big_fleet(d, node, monkeypatch, size):  # noqa: F811
    """The paid rows at 58af2eb7: clear_description took a second brain step 36 times at 5x20 against 12 at 1x4. On a
    big fleet the brain is not shown the sessions, so it sends with no name and the daemon picks by the words ("auto");
    the result then asked the brain to "tell the user it went to X", a whole model step for the words "Sent to X.".
    The quick acknowledgement says that name in code. With the rules off the result is as it was."""
    rig = Rig(d, node, monkeypatch, size)
    t = next(t for t in rig.turns if t["kind"] == "clear_description")
    target = rig.by_id[t["expect"]["session"]]
    message = t["text"].split(" to ", 1)[-1]

    def send() -> dict:
        d.state = d.State()
        d.state.conn = fake_conn()
        open_gates(d, monkeypatch, t["text"])
        p = Params(message=message[0].upper() + message[1:])
        asyncio.run(d.send_to_claude_code(p))
        return p.results[0]

    rig.answer = target
    result = send()
    assert result["sent_to"] == [target.name] and result["routing"] == "auto", result
    assert d._quick_ack({"message": message}, result, t["text"]) == f"Sent to {d._spoken_names(target.name).split('/')[0]}."
    monkeypatch.setenv("POINTE_FLEET", "off")
    result = send()
    assert result["sent_to"] == [target.name] and result["say"] == f"Tell the user it went to {target.name}.", result
    assert d._quick_ack({"message": message}, result, t["text"]) is None
    rig.answer = None


# ---------- the budget, in the vendor's tokens ----------

def test_the_block_stays_under_the_budget_at_the_vendors_worst_measured_rate(rig):
    """The paid rows: 1,811 tokens by the vendor's counter for a block the daemon estimated under 1,800 at 3.5
    characters a token. The vendor's rate for this text was 2.82 to 3.1."""
    d = rig.d
    for s in list(rig.by_id.values())[:40]:  # as in a run: sent to, with no report back, and a long request each
        d.state.unconfirmed[s.id] = ["Add a comment explaining the retry loop, and say which function is the longest. " * 3]
        s.open_questions = ["Should the importer keep the old column names, or move to the new ones now?"]
    block = d._needs_now()
    assert len(block) / 2.82 <= scale.BUDGET_TOKENS and scale.tokens(block) <= scale.BUDGET_TOKENS
    assert scale.CHARS_PER_TOKEN <= 2.82 * 0.93  # the margin under the worst row


def test_list_sessions_rows_are_slim_for_sessions_out_of_focus(rig):
    d = rig.d
    p = Params(machine="omer-lab")
    asyncio.run(d.list_sessions(p))
    rows = p.results[0]["sessions"]
    assert len(rows) == 20 and all("latest" not in r and "clocks" not in r for r in rows)
    assert all({"name", "machine", "where_it_stands"} <= set(r) <= {"name", "machine", "where_it_stands", "working"} for r in rows)
    assert len(json.dumps(p.results[0])) < 2400  # about 900 tokens; whole rows were about three times that
    p = Params()
    asyncio.run(d.list_sessions(p))
    assert "latest" in p.results[0]["sessions"][0]  # the active session, in focus: the whole row


# ---------- the brain's input does not grow with the fleet ----------

def _a_call(d, monkeypatch, rig, turns: int = 30, sent: list | None = None) -> list[int]:  # noqa: F811
    """A call of `turns` scripted turns of the benchmark's kinds, with a stub model that sends what is asked and then
    says a line. Returns the size of the brain's whole input at each turn's first step, in tokens by the budget's own
    estimate (characters over 2.6): the prompt, the tools and the history as assembled."""
    from pipecat.frames.frames import InputTextRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "FIRST_HELLO", Path("/dev/null"))
    monkeypatch.setattr(d, "_may_fast_send", lambda: False)  # every turn goes through the brain, as in the paid runs
    sizes: list[list[int]] = []

    async def step(choice, instructions, messages, decls, heard=None):
        chars = len(instructions) + len(json.dumps(decls, ensure_ascii=False)) + sum(map(d.Brain._chars, messages))
        sizes[-1].append(int(chars / scale.CHARS_PER_TOKEN))
        if sent is not None:  # what the vendor is handed, in its order: tools, the system prompt, then the history
            sent.append((json.dumps(decls, ensure_ascii=False), instructions,
                         [json.dumps(m, ensure_ascii=False, sort_keys=True, default=str) for m in messages]))
        last = messages[-1]
        asked = next((m["content"] for m in reversed(messages) if m["role"] == "user" and not m["content"].startswith("[")), "")
        if last["role"] != "tool" and d._FAST_SEND.match(asked) and len(sizes[-1]) == 1:
            calls = [{"id": f"c{len(sizes)}", "name": "send_to_claude_code", "args": {"message": asked.split(" to ", 1)[-1]}}]
        else:
            calls = [{"id": f"s{len(sizes)}-{len(sizes[-1])}", "name": "speak", "args": {"text": "Done."}}]
        return SimpleNamespace(calls=calls, said="", raw=None, vendor="fake", usage={})

    monkeypatch.setattr(d.vendors, "step", step)

    async def delivered(target, message, anyway=False):
        return True
    monkeypatch.setattr(d, "deliver", delivered)
    d.state = d.State()
    d.state.conn = fake_conn()
    d.state.conn.injector.queued_reports = lambda: {}
    front = d.BrainFront(d._opening_context())
    d.state.front = front
    tasks: list = []

    async def push(frame, direction=FrameDirection.DOWNSTREAM):
        pass
    front.push_frame = push
    front.create_task = lambda coro, name=None: tasks.append(asyncio.ensure_future(coro))
    kinds = ("clear_name", "clear_machine_name", "clear_description", "ambiguous_name", "ambiguous_none", "needs_me")
    by_kind = {k: [t for t in rig.turns if t["kind"] == k] for k in kinds}

    async def run():
        for i in range(turns):
            pool = by_kind[kinds[i % len(kinds)]] or by_kind["clear_name"]
            turn = pool[(i // len(kinds)) % len(pool)] if kinds[i % len(kinds)] != "needs_me" else {"text": "What needs me?", "expect": {}}
            rig.answer = rig.by_id.get(turn["expect"].get("session"))  # the classifier, when asked: the labelled session
            open_gates(d, monkeypatch, turn["text"])
            sizes.append([])
            await front.process_frame(InputTextRawFrame(text=turn["text"]), FrameDirection.DOWNSTREAM)
            while tasks:
                await asyncio.gather(tasks.pop(0))
    asyncio.run(run())
    d.state.front = None
    return [s[0] for s in sizes if s]


@pytest.mark.slow  # about 16 s on CI
def test_the_brains_input_at_5x20_is_within_a_twentieth_of_1x4(d, node, monkeypatch):  # noqa: F811
    """The paid rows: 31,253 tokens a turn at 5x20 against 25,941 at 1x4 (+20%), and a first step that carried 2,300
    tokens the cache had not seen against 113. Three things grew with the fleet: the opening listed every session
    (15,700 characters against 950), the block had a line for every session named lately so it changed on 49 of 59
    turns, and each copy of it was 4,700 characters against 1,900."""
    import statistics

    small = _a_call(d, monkeypatch, Rig(d, node, monkeypatch, "1x4"))
    big = _a_call(d, monkeypatch, Rig(d, node, monkeypatch, "5x20"))
    assert len(small) == len(big) == 30
    print(f"brain input, first step, tokens at 2.6 characters: 1x4 median {statistics.median(small)}, first {small[0]}, "
          f"last {small[-1]}; 5x20 median {statistics.median(big)}, first {big[0]}, last {big[-1]}")
    assert statistics.median(big) <= 1.05 * statistics.median(small)  # measured: 3.5% under
    assert big[0] <= 1.05 * small[0] and big[-1] <= 1.05 * small[-1]  # at the call's start and after thirty turns


@pytest.mark.parametrize("size", ["1x4", BIG("10x30")])
def test_what_the_brain_is_sent_keeps_its_prefix_from_step_to_step(d, node, monkeypatch, size):  # noqa: F811
    """The paid rows at 10x30 with the rules on: the vendor's time to first token was about 1.1 s against 0.76 s with
    the rules off right after. A prompt the vendor cannot cache is the classic cause: an early part that changes. It is
    not that here: over a scripted call the tools and the system prompt are the same bytes at every step, and each
    step's history begins with the whole history of the step before, unless the history was trimmed (brain._trim,
    over its budget). The cache then reads everything but what is new."""
    sent: list = []
    trims: list[int] = []
    trim = d.Brain._trim

    def counted(self):
        before = len(self.messages)
        trim(self)
        if len(self.messages) != before:
            trims.append(len(sent))
    monkeypatch.setattr(d.Brain, "_trim", counted)
    _a_call(d, monkeypatch, Rig(d, node, monkeypatch, size), sent=sent)
    assert len(sent) >= 30 and len({(tools, system) for tools, system, _ in sent}) == 1
    broke = [i for i in range(1, len(sent)) if sent[i][2][:len(sent[i - 1][2])] != sent[i - 1][2]]
    assert set(broke) <= set(trims), (broke, trims)


def test_the_block_of_a_big_fleet_does_not_change_when_a_session_is_only_named(rig):
    d = rig.d
    before = d._needs_now()
    for s in list(rig.by_id.values())[30:40]:
        d._fleet_touch(s)  # named, asked about: in focus for the reader and the routing
    d.state.thread = (list(rig.by_id.values())[50].id, time.time())
    assert d._fleet_tiers()[list(rig.by_id.values())[35].id] == scale.FOCUS
    assert d._needs_now() == before and scale.tokens(before) < 500  # the budget is a ceiling: little needs the user here


def test_sessions_sent_to_have_a_short_line_each_and_past_four_only_their_names(rig):
    d = rig.d
    sent = list(rig.by_id.values())[20:27]
    for n, s in enumerate(sent):
        d.state.unconfirmed[s.id] = [f"Rebase onto main and run the tests, round {n}."]
        s.last_delegation_at = 1000.0 + n
    block = d._needs_now()
    newest = sent[-1]
    assert (f"- {newest.name} (on {newest.machine}, not working). Sent to it, with no report back yet: Rebase onto main "
            f"and run the tests, round 6.") in block
    assert f"- And 3 more sent to, with no report back yet: {sent[2].name}, {sent[1].name}, {sent[0].name}." in block
    assert block.count("Sent to it, with no report back yet") == 4 and scale.tokens(block) < 800
    assert f"- {sent[0].machine} (Linux, 20 ms): 13 more, 0 working, none need you" in block  # the 7 are not counted twice


def test_the_opening_of_a_big_fleet_counts_the_other_sessions_and_the_machines_line_is_only_the_rule(rig):
    d = rig.d
    opening = json.dumps(d._opening_context())
    assert "99 other sessions are on the voice" in opening and len(opening) < 1500
    assert d._machines_line() is None and "avi-box (Linux, 20 ms)" in d._needs_now()
    assert "only when it tells two sessions apart" in scale.RULES and "no look-up first" in scale.RULES  # said once


# ---------- a small fleet is told what it is told with the rules off ----------

def test_up_to_twelve_sessions_the_brain_is_told_exactly_what_it_is_told_with_the_rules_off(d, node, monkeypatch):  # noqa: F811
    """The fleet benchmark at four sessions with the rules on: words for a session nobody has were sent 9 of 21 (asked
    20 of 21 before, and with the rules off). The big fleet's guidance had moved into every call's instructions."""
    rig = Rig(d, node, monkeypatch, "2x6")
    assert len(rig.by_id) == scale.SMALL_FLEET == 12 and not scale.big(12) and scale.big(13)

    def told() -> str:
        d.state = d.State()
        p = Params(machine="avi-box")
        asyncio.run(d.list_sessions(p))
        front = d.BrainFront(d._opening_context())
        return "\n".join([d._brain_context(), json.dumps(d._opening_context()), json.dumps(p.results[0], sort_keys=True),
                          front.brain.instructions])

    on = told()
    monkeypatch.setenv("POINTE_FLEET", "off")
    assert told() == on and scale.RULES not in on
    monkeypatch.setenv("POINTE_FLEET", "on")
    add(d, "one-more", "extra-" + _names(40)[-1], "/work/one-more")  # the thirteenth: the big fleet's form
    big = told()
    assert scale.RULES in big and "The other sessions, by machine:" in big and '"more": 0' in big


def test_a_call_that_began_small_and_grew_is_told_how_to_send_in_the_block(d, node, monkeypatch):  # noqa: F811
    rig = Rig(d, node, monkeypatch, "5x20")
    assert rig.d.state.fleet_rules_told is False  # no brain of this call has the guidance in its instructions
    assert "no look-up first" in d._needs_now()
    d.BrainFront(d._opening_context())
    assert d.state.fleet_rules_told is True and "no look-up first" not in d._needs_now()


def test_a_name_nobody_has_is_asked_by_code_on_four_sessions_too(d, node, monkeypatch):  # noqa: F811
    """1x4, rules on, ambiguous_none-00, -02, -04, -06 (r1 orders 32, 37, 47, 54; r2 orders 2, 11; r3 order 9): "There's
    no session called drizzle, so the coverage check went to harbor instead." The classifier said unclear and the
    request went to the session talked with."""
    rig = Rig(d, node, monkeypatch, "1x4")
    other = next(s for s in rig.by_id.values() if s.name != "shop")
    for text in ("Tell drizzle to check the code coverage.", "Tell nimbus to count the failing tests."):
        for brain in (None, other.name):
            got = rig.turn(text, brain=brain, talking_with=other.id)
            assert got["to"] is None and got["model"] == [] and got["ask"] == "I found no session like that. Which session is it?"
    # -01, -05 (r1 orders 1, 17): a description nobody fits. The model sees all four; its "unclear" is asked, not sent.
    got = rig.turn("Ask the session working on the passport scanner to say which function is the longest.", talking_with=other.id)
    assert got["to"] is None and len(got["model"]) == 1 and got["ask"]
    got = rig.turn("And bump the minor version too.", talking_with=other.id)  # words for nobody else: as before
    assert got["to"] is other


def test_a_description_two_sessions_share_is_asked_with_their_two_names(rig):
    """5x20, ambiguous_description-03 (r2 order 39): asked "I found no session like that", with two sessions on it."""
    turn = next(t for t in rig.turns if t["kind"] == "ambiguous_description")
    a, b = (rig.by_id[i] for i in turn["expect"]["fits"])
    got = rig.turn(turn["text"], talking_with=rig.elsewhere(a, b).id)
    assert got["to"] is None and a.name in got["ask"].lower() and b.name in got["ask"].lower() and "found no" not in got["ask"]


def test_the_same_task_for_another_session_some_turns_later_is_not_a_correction(rig, monkeypatch):
    """5x20, clear_name-04 (r2 order 42): "Tell outpost to write a changelog entry for today's change." Five turns
    before, the same task had gone to tide; tide was told "Drop my last request", as after "I meant outpost"."""
    d = rig.d
    first, second = [s for s in rig.by_id.values() if not s.machine and s.name != "shop"][:2]
    withdrawn: list[str] = []

    async def withdraw(session, message, since):
        withdrawn.append(session.name)
    monkeypatch.setattr(d, "_withdraw", withdraw)

    def say(text: str, send: bool = True) -> None:
        open_gates(d, monkeypatch, text)
        d.state.recent_said.append((time.time(), text))
        if send:
            asyncio.run(d.send_to_claude_code(Params(message="Write a changelog entry for today's change.")))
        time.sleep(0.12)

    for between in (True, False):
        d.state = d.State()
        d.state.conn = fake_conn()
        rig.sent.clear(), withdrawn.clear()
        say(f"Tell {first.name} to write a changelog entry for today's change.")
        if between:
            say("What is blocked on me?", send=False)
        say(f"Tell {second.name} to write a changelog entry for today's change.")
        assert [name for name, _ in rig.sent] == [first.name, second.name]
        assert withdrawn == ([] if between else [first.name])  # right after it, it is still "I meant the other one"


def test_sends_join_the_block_four_at_a_time_and_a_report_leaves_it_at_once(rig):
    d = rig.d
    sessions = list(rig.by_id.values())[40:50]

    def send(s) -> str:
        d.state.unconfirmed[s.id] = ["Run the tests."]
        s.last_delegation_at = time.time()
        return d._needs_now()

    first = send(sessions[0])
    assert f"- {sessions[0].name} (" in first
    assert send(sessions[1]) == send(sessions[2]) == send(sessions[3]) == first  # three sends: the same block
    fifth = send(sessions[4])
    assert fifth != first and all(f"{s.name}" in fifth for s in sessions[:5])
    d.state.unconfirmed.pop(sessions[0].id)  # it reported
    assert f"- {sessions[0].name} (" not in d._needs_now() and sessions[4].name in d._needs_now()
