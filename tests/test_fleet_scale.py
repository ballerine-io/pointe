"""A big fleet stays small for the voice (pointe/scale.py, docs/design/people-and-machines.md "Scale"): three tiers, a
fixed budget for "what needs me", routing narrowed in code before the model picks, list_sessions with arguments, quiet
sessions the reader does not read, and a speech queue that says one line per machine and holds the rest. Offline: the
models are faked at their seams, and every name, goal and file is invented.

uv run --locked pytest -q tests/test_fleet_scale.py
"""

import asyncio
import random
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scale  # noqa: E402
import sessions as sessions_mod  # noqa: E402
from sessions import Session  # noqa: E402
from test_mixed_harnesses import node  # noqa: E402,F401  (a fixture)
from test_no_silent_turn import _call  # noqa: E402
from test_orchestrator import Params, add, client_for, d, fake_conn, no_classifier  # noqa: E402,F401
from test_session_scope import Voice, _reports  # noqa: E402

NAMES = ("tide harbor skiff lantern gully pelican orchard pasture cinder alder juniper marble nettle beacon paprika "
         "anchor bramble copper drift ember fjord glacier heron islet jasper kelp lagoon mesa nectar otter prairie quill "
         "reef summit steppe umber valley wharf yarrow zephyr").split()
BOXES = "avi-box kestrel osprey falcon merlin condor harrier plover curlew dunlin".split()
TOPICS = ("invoice rounding", "webhook retries", "search reindex", "login throttle", "export queue", "avatar upload",
          "ledger audit", "fare table", "coupon stacking", "refund window")


@pytest.fixture
def fleet_on(monkeypatch):
    monkeypatch.setenv("POINTE_FLEET", "on")


def put(d, sid: str, name: str, machine: str = "", **fields) -> Session:
    """A session straight into the registry: no file is written per session, so a fleet of a thousand takes a moment."""
    brief = fields.pop("brief", {"goal": f"Work on {name}.", "state": f"{name} is mid-way."})
    files = fields.pop("files", [])
    s = Session(id=sid, name=name, cwd=f"/srv/{sid}", pid=4242, transcript="/tmp/none.jsonl", machine=machine,
                harness_data={"files": files} if machine else {}, **fields)
    s.brief = brief
    d.REGISTRY.sessions[sid] = s
    if d.REGISTRY.active_id is None:
        d.REGISTRY.active_id = sid
    return s


def machine(node, name: str, **facts) -> str:
    node.machines[name] = sessions_mod.Machine(name=name, id=f"n{abs(hash(name)) % 10**8:08d}", os="linux", online=True,
                                               rtt_ms=23, **facts)
    return name


def build(d, node, machines: int, per: int, here: int = 0) -> list[Session]:
    """`machines` machines with `per` sessions each, and `here` on this one. Each has its own goal and one own file."""
    out = []
    boxes = [""] * bool(here) + [machine(node, f"box-{i:02d}") for i in range(machines)]
    for b, box in enumerate(boxes):
        for i in range(here if not box else per):
            n = len(out)
            name = f"{NAMES[n % len(NAMES)]}-{n:03d}"
            out.append(put(d, f"s{n:03d}", name, box, files=[f"{name}_{TOPICS[n % len(TOPICS)].split()[0]}.py", "README.md"],
                           brief={"goal": f"Fix the {TOPICS[n % len(TOPICS)]} in {name}.", "state": "Tests are running."},
                           active_at=1000.0 + n))
    return out


# ---------- the tiers ----------

def rows(n: int, **each) -> list[scale.Row]:
    return [scale.Row(id=f"s{i}", name=f"n{i}", active_at=float(i), **each) for i in range(n)]


def test_every_session_is_in_exactly_one_tier_and_focus_holds_twelve_at_most():
    fleet_rows = rows(60, needs=True) + [scale.Row(id="a", name="a", active=True), scale.Row(id="t", name="t", thread=True)]
    tier = scale.tiers(fleet_rows, now=100.0)
    assert set(tier) == {r.id for r in fleet_rows} and set(tier.values()) <= {scale.FOCUS, scale.BACKGROUND, scale.QUIET}
    focus = [sid for sid, t in tier.items() if t == scale.FOCUS]
    assert len(focus) == scale.FOCUS_MAX and {"a", "t"} <= set(focus)  # the active session and the thread first
    assert scale.QUIET not in {tier[r.id] for r in fleet_rows if r.needs}  # one that needs the user is never quiet


def test_a_session_enters_focus_by_an_event_and_leaves_after_a_quiet_time():
    now = 10_000.0
    base = [scale.Row(id="a", name="a", active=True)]
    for event in ({"needs": True}, {"needs": True, "urgent": True}, {"awaiting": True}, {"thread": True},
                  {"touched_at": now - 5}):
        assert scale.tiers(base + [scale.Row(id="x", name="x", **event)], now)["x"] == scale.FOCUS, event
    assert scale.tiers(base + [scale.Row(id="x", name="x")], now)["x"] == scale.BACKGROUND  # no event: never in focus
    named_long_ago = scale.Row(id="x", name="x", touched_at=now - scale.FOCUS_SECS - 1)
    assert scale.tiers(base + [named_long_ago], now)["x"] == scale.BACKGROUND


def test_past_the_twenty_most_recent_on_a_machine_a_background_session_is_quiet_and_a_marked_one_always():
    on_box = [scale.Row(id=f"b{i}", name=f"b{i}", machine="box", active_at=float(i)) for i in range(30)]
    here = [scale.Row(id=f"h{i}", name=f"h{i}", active_at=float(i)) for i in range(5)]
    marked = scale.Row(id="m", name="m", active_at=999.0, marked_quiet=True)
    waiting = scale.Row(id="w", name="w", machine="box", active_at=-1.0, marked_quiet=True, needs=True)
    tier = scale.tiers(on_box + here + [marked, waiting], now=0.0)
    assert [tier[f"b{i}"] for i in range(30)] == [scale.QUIET] * 10 + [scale.BACKGROUND] * 20  # the 20 newest stay
    assert {tier[f"h{i}"] for i in range(5)} == {scale.BACKGROUND}  # counted per machine
    assert tier["m"] == scale.QUIET and tier["w"] == scale.FOCUS  # it needs the user: read, and in focus


# ---------- the budget ----------

def test_off_tells_the_brain_what_it_was_told_before_and_on_changes_nothing_for_a_small_registry(d, monkeypatch):
    lantern = add(d, "a", "lantern")
    gully = add(d, "b", "gully")
    lantern.brief = {"goal": "Ship the fare table.", "state": "Tests pass."}
    gully.brief, gully.open_questions = {"goal": "Fix the login throttle.", "state": "Blocked."}, ["Merge it now?"]
    monkeypatch.setenv("POINTE_FLEET", "off")
    off = d._needs_now()
    assert off == (
        "[orchestrator mode: you speak for every session. What each session needs right now, most urgent first; this is "
        "the truth, also over your own memory: answer from it, most urgent first, and include every clock. What you sent "
        "is listed here word for word. An item sent may have answered a question listed; anything else listed is still "
        "open]\n"
        "- gully (Claude, not working). Blocked. Waits on the user for: Merge it now?.\n"
        "- lantern (Claude, not working). Tests pass. Waits on the user for: nothing.")
    assert d.fleet_needs()["on"] is False
    monkeypatch.setenv("POINTE_FLEET", "on")
    assert d._needs_now() == off and d.fleet_needs() == {"text": off, "tokens": scale.tokens(off), "budget": 1800, "on": True}


def _random_fleet(d, node, rng: random.Random) -> list[Session]:
    d.REGISTRY.sessions.clear()
    d.REGISTRY.active_id = None
    boxes = [""] + [machine(node, f"{rng.choice(NAMES)}-{'x' * rng.randint(0, 30)}-{i}") for i in range(rng.randint(0, 30))]
    out = []
    for box in boxes:
        for _ in range(rng.randint(0, 40)):
            n = len(out)
            name = f"{rng.choice(NAMES)}{' ' + rng.choice(NAMES) * rng.randint(1, 12) if rng.random() < 0.3 else ''} {n}"
            s = put(d, f"s{n}", name, box, active_at=rng.random() * 1000, busy=rng.random() < 0.5,
                    owner=rng.choice(["", "", "Avi", "Noa"]) if box else "",
                    brief={"goal": "g", "state": "word " * rng.randint(0, 400)})
            roll = rng.random()
            if roll < 0.15:
                s.open_questions = [f"Should {name} " + "really " * rng.randint(0, 80) + "merge?"] * rng.randint(1, 4)
            elif roll < 0.25:
                s.permission_id, s.permission_text = f"p{n}", "Bash: rm -rf build"
            elif roll < 0.3:
                s.needs = {"need": "a yes to deploy", "unblock": "say yes"}
            if rng.random() < 0.1:
                s.urgency = "high"
            if rng.random() < 0.1:
                d.state.unconfirmed[s.id] = ["run the tests " * rng.randint(1, 40)]
            if rng.random() < 0.05:
                s.quiet = True
            out.append(s)
    if out and rng.random() < 0.7:
        d.state.thread = (rng.choice(out).id, time.time())
    return out


def test_what_needs_me_fits_the_budget_at_any_fleet_size_and_names_or_counts_everyone_who_needs_the_user(d, node, fleet_on):
    rng = random.Random(7)
    for round_ in range(14):
        everyone = _random_fleet(d, node, rng)
        if round_ == 0:  # the largest case, always: 30 machines of 40
            d.REGISTRY.sessions.clear()
            everyone = build(d, node, 30, 40, here=40)
            for s in everyone[::3]:
                s.open_questions = ["Merge it?"]
        block = d._needs_now()
        assert scale.tokens(block) <= scale.BUDGET_TOKENS, (round_, len(everyone), scale.tokens(block))
        assert block == d._needs_now() == d.fleet_needs()["text"]  # nothing changed: byte for byte the same
        needing = [s for s in everyone if d._waiting_items(s)]
        tier = d._fleet_tiers()
        overflow = [s for s in needing if tier[s.id] != scale.FOCUS]
        for s in needing:
            if tier[s.id] == scale.FOCUS:
                assert f"- {scale.clip(s.name, 40)[:-1]}" in block, (round_, s.name)  # its own line
        if overflow:
            found = scale.re.search(r"And (\d+) more needs? you: (.*)", block)
            assert found and int(found[1]) == len(overflow), (round_, len(overflow))  # none dropped: named or counted
            named = sum(scale.clip(s.name, 40) in found[2] for s in overflow)
            others = scale.re.search(r"(\d+) others?\.", found[2])
            assert named >= 1 and named + (int(others[1]) if others else 0) >= len(overflow)
        else:
            assert "more need" not in block


def test_the_budget_holds_at_the_plans_sizes_and_the_block_grows_by_machines_not_by_sessions(d, node, fleet_on, monkeypatch):
    sizes = {}
    for label, (machines, per) in {"1x4": (1, 4), "5x20": (5, 20), "10x30": (10, 30), "30x40": (30, 40)}.items():
        d.REGISTRY.sessions.clear()
        d.REGISTRY.active_id = None
        build(d, node, machines, per)
        sizes[label] = scale.tokens(d._needs_now())
        monkeypatch.setenv("POINTE_FLEET", "off")
        sizes[label + " off"] = scale.tokens(d._needs_now())
        monkeypatch.setenv("POINTE_FLEET", "on")
    print("what needs me, tokens:", sizes)
    assert all(sizes[k] <= 1800 for k in ("1x4", "5x20", "10x30", "30x40"))
    assert sizes["30x40 off"] > 20 * sizes["30x40"]  # without the tiers it is a line per session
    lines = d._needs_now().split("\n")
    assert "- box-01 (Linux, 23 ms): 40 sessions, 0 working, 40 idle, none need you" in lines
    assert lines[-1] == "- and 1 more machine: 39 sessions, 0 working, none need you"  # past a third of the budget: a count
    d.REGISTRY.sessions.clear()
    build(d, node, 2, 7)
    assert "- box-00 (Linux, 23 ms): 6 more, 0 working, 6 idle, none need you" in d._needs_now()  # the active one is above"


def test_a_machines_latency_does_not_change_the_block_turn_to_turn(d, node, fleet_on):
    build(d, node, 3, 15)
    before = d._needs_now()
    for m in node.machines.values():
        m.rtt_ms = 29  # jitter
    assert d._needs_now() == before
    node.machines["box-00"].rtt_ms = 400  # a real change is told
    assert "box-00 (Linux, 400 ms)" in d._needs_now()


def test_a_line_over_its_share_loses_its_notes_before_what_it_waits_on(d, node, fleet_on):
    for i in range(12):
        s = put(d, f"s{i}", f"{NAMES[i]}", brief={"goal": "g", "state": "Long notes. " * 300})
        s.open_questions = [f"Ship {NAMES[i]} on Friday?"]
    block = d._needs_now()
    assert scale.tokens(block) <= 1800
    assert all(f"Ship {NAMES[i]} on Friday?" in block for i in range(12))  # every question whole


# ---------- routing: narrowed in code ----------

def classifier(d, monkeypatch, answer: str = "unclear") -> list[str]:
    prompts: list[str] = []

    async def text(model, prompt, *a, **k):
        prompts.append(prompt)
        return answer
    monkeypatch.setattr(d.vendors, "text", text)
    return prompts


def route(d, said: str):
    d.state.last_utterance = said
    return asyncio.run(d._route(said, said))


def test_the_classifier_reads_eight_sessions_whatever_the_fleets_size(d, node, fleet_on, monkeypatch):
    prompts = classifier(d, monkeypatch)
    build(d, node, 1, 8)
    route(d, "fix the invoice rounding")
    small = len(prompts[-1])
    d.REGISTRY.sessions.clear()
    d.REGISTRY.active_id = None
    build(d, node, 10, 30)
    route(d, "fix the invoice rounding")
    big = len(prompts[-1])
    print(f"classifier prompt: {small} characters with 8 sessions, {big} with 300")
    assert prompts[-1].count("\n- ") == scale.CANDIDATES_MAX and abs(big - small) <= 0.10 * small
    monkeypatch.setenv("POINTE_FLEET", "off")
    route(d, "fix the invoice rounding")
    assert len(prompts[-1]) > 20 * small  # before: every session, in one prompt


def test_the_right_session_is_a_candidate_by_its_goal_its_file_or_its_machine_and_the_record_says_how(d, node, fleet_on, monkeypatch):
    seen = no_classifier(d, monkeypatch)
    everyone = build(d, node, 10, 30)
    target = everyone[217]
    target.brief = {"goal": "Rebuild the zeppelin docking planner.", "state": "Drafting."}
    route(d, "how far along is the zeppelin docking work")
    assert target.name in seen[-1] and len(seen[-1]) <= 8
    picked = {c["id"]: c for c in d.state.fleet_route["candidates"]}
    assert picked[target.id]["how"] == "lexical" and picked[target.id]["score"] >= scale.SCORE_FLOOR
    assert picked["s000"]["how"] == "active" and d.state.fleet_route["of"] == 300
    other = everyone[133]
    other.harness_data["files"] = ["gondola_ballast.py"]
    d.state.fleet_files.clear()
    route(d, "open gondola_ballast.py and check the units")
    assert other.name in seen[-1]
    route(d, "on box-07, look at the search reindex")  # a machine where the words say whom they are for
    assert {s.machine for s in everyone if s.name in seen[-1]} == {"box-07"} and len(seen[-1]) <= 8
    assert {c["how"] for c in d.state.fleet_route["candidates"]} == {"lexical"} and d.state.fleet_route["of"] == 30
    assert client_for(d).get("/voice/context").json()["fleet"]["route"]["of"] == 30
    asked = len(seen)
    assert route(d, "on box-07, do the thing") == ([], "ambiguous") and len(seen) == asked  # thirty there, none fits
    assert d._which_question("ambiguous", "on box-07, do the thing") == "Which session on box-07 is it for?"
    assert "juniper-210, marble-211, nettle-212 and 27 more" in d._unrouted("ambiguous", "on box-07, do the thing")


def test_a_request_that_matches_nothing_asks_and_the_model_is_not_called(d, node, fleet_on, monkeypatch):
    seen = no_classifier(d, monkeypatch)
    build(d, node, 10, 30)
    assert route(d, "do the thing we talked about") == ([], "unmatched")
    assert seen == []
    assert d._which_question("unmatched", "do the thing we talked about") == "Which machine is it for?"
    assert "Not sent" in d._unrouted("unmatched", "x") and d._unrouted_note("unmatched").startswith("blocked:")
    d.state.thread = ("s005", time.time())  # a conversation to go on: the classifier decides, then the thread
    targets, how = route(d, "do the thing we talked about")
    assert ([s.id for s in targets], how) == (["s005"], "thread") and seen[-1] == ["pelican-005", "tide-000"]


def test_few_sessions_are_routed_as_before(d, fleet_on, monkeypatch):
    seen = no_classifier(d, monkeypatch)
    for i in range(4):
        add(d, f"s{i}", NAMES[i])
    targets, how = route(d, "do the thing we talked about")
    assert seen[-1] == NAMES[:4] and (targets[0].id, how) == ("s0", "active")  # everyone seen, nothing asked


def test_a_machine_named_never_falls_back_to_a_session_on_another_machine(d, node, fleet_on, monkeypatch):
    no_classifier(d, monkeypatch)
    build(d, node, 2, 3, here=2)
    assert d.REGISTRY.active.machine == ""
    assert route(d, "on box-01, run the tests") == ([], "ambiguous")  # asked among the three there, as before
    assert d._which_question("ambiguous", "on box-01, run the tests") == "pelican 005, orchard 006 or pasture 007?"
    d.state.fleet_ask = (time.time(), list(d.REGISTRY.sessions))  # "Which machine is it for?" was asked
    assert route(d, "box-01") == ([], "unmatched")  # the machine alone: its sessions, never the active one elsewhere
    assert d.state.fleet_route["machines"] == ["box-01"] and len(d.state.fleet_route["candidates"]) == 3
    assert d._which_question("unmatched", "box-01") == "pelican 005, orchard 006 or pasture 007?"


# ---------- "which session?" ----------

def test_which_session_is_three_options_at_most_grouped_by_machine_and_past_that_the_machine_first():
    assert scale.which_question([("shop", "avi-box"), ("billing", "avi-box"), ("shop", "")]) == "On avi-box: shop or billing; here: shop?"
    assert scale.which_question([("shop", ""), ("billing", "")]) == "shop or billing?"
    assert scale.which_question([("shop", "avi-box"), ("shop", "devbox")]) == "Shop: on avi-box or on devbox?"
    ten = [("shop", f"box-{i}") for i in range(10)]
    assert scale.which_question(ten) == "Which machine? shop is on box-0, box-1 and 8 more."
    assert scale.which_question([(n, f"box-{i}") for i, n in enumerate(NAMES[:5])]) == "Which machine is it for?"
    assert scale.which_question([(n, "") for n in NAMES[:5]]) == "Which session is it for?"


# ---------- one name on many machines ----------

@pytest.fixture
def shops(d, node, fleet_on, monkeypatch):
    """Ten machines, each with a session called shop. The first to join kept the plain name."""
    monkeypatch.setattr(d, "_add_worker", lambda s: asyncio.sleep(0))
    boxes = [machine(node, n) for n in BOXES]
    out = []
    for box in boxes:
        body = {"id": "r1", "name": "shop", "cwd": "/srv/shop", "pid": 4242, "harness": "claude-code"}
        out.append(asyncio.run(d.register_remote(node.machines[box].id, box, body)))
    assert [s.name for s in out[:3]] == ["shop", "shop kestrel", "shop osprey"]
    return out


def test_shop_on_ten_machines_asks_which_machine_and_shop_on_one_of_them_routes(d, shops, monkeypatch):
    seen = no_classifier(d, monkeypatch)
    said = "tell shop to run the tests"
    assert route(d, said) == ([], "ambiguous") and seen == []  # the first to join does not win by coming first
    assert d._which_question("ambiguous", said) == "Which machine? shop is on avi-box, kestrel and 8 more."
    assert "shop, shop kestrel, shop osprey and 7 more. Ask which one" in d._unrouted("ambiguous", said)
    for box, s in (("merlin", shops[4]), ("avi-box", shops[0])):
        targets, how = route(d, f"tell shop on {box} to run the tests")
        assert (targets, how) == ([s], "named")
    targets, how = route(d, "Curlew.")  # the answer to "which machine?"
    assert (targets, how) == ([shops[8]], "answered")
    d.state.fleet_ask = (time.time() - d.PENDING_ROUTE_SECS - 1, d.state.fleet_ask[1])
    assert route(d, "Curlew.")[1] != "answered"  # the question is long over: a machine's name alone picks nothing


def test_my_own_shop_on_this_machine_keeps_the_plain_name(d, shops, monkeypatch):
    seen = no_classifier(d, monkeypatch)
    d.REGISTRY.sessions.clear()
    mine = put(d, "cc1", "shop")  # mine, here, joined first: the others are "shop <machine>"
    for box in BOXES:
        body = {"id": "r1", "name": "shop", "cwd": "/srv/shop", "pid": 4242, "harness": "claude-code"}
        asyncio.run(d.register_remote(sessions_mod.MACHINES[box].id, box, body))
    assert sorted(s.name for s in d.REGISTRY.sessions.values())[:3] == ["shop", "shop avi-box", "shop condor"]
    assert route(d, "tell shop to run the tests") == ([mine], "named") and seen == []
    assert route(d, "tell shop on avi-box to run the tests")[0][0].machine == "avi-box"


def test_two_or_three_twins_are_asked_by_machine(d, node, fleet_on, monkeypatch):
    monkeypatch.setattr(d, "_add_worker", lambda s: asyncio.sleep(0))
    no_classifier(d, monkeypatch)
    for box in (machine(node, "avi-box"), "devbox"):
        asyncio.run(d.register_remote(node.machines[box].id, box, {"id": "r1", "name": "shop", "cwd": "/srv/shop",
                                                                   "pid": 4242, "harness": "claude-code"}))
    said = "tell shop to run the tests"
    assert route(d, said) == ([], "ambiguous")
    assert d._which_question("ambiguous", said) == "Shop: on avi-box or on devbox?"
    assert [s.machine for s in route(d, "the one on devbox")[0]] == ["devbox"]


# ---------- list_sessions ----------

def listed(d, **arguments) -> dict:
    p = Params(**arguments)
    asyncio.run(d.list_sessions(p))
    return p.results[0]


def test_list_sessions_returns_twenty_rows_a_count_of_the_rest_and_the_machines(d, node, fleet_on):
    everyone = build(d, node, 5, 20, here=3)
    everyone[60].open_questions = ["Deploy now?"]
    out = listed(d)
    assert len(out["sessions"]) == 20 and out["more"] == 83 and "narrow" in out["note"]
    assert {r["name"] for r in out["sessions"][:2]} == {everyone[0].name, everyone[60].name}  # in focus first
    assert any(line.startswith("box-00 (Linux, 23 ms): 20 sessions") for line in out["machines"])
    on_box = listed(d, machine="box-02")
    assert len(on_box["sessions"]) == 20 and on_box["more"] == 0 and {r["machine"] for r in on_box["sessions"]} == {"box-02"}
    assert [r["name"] for r in listed(d, state="needs_you")["sessions"]] == [everyone[60].name]
    assert [r["name"] for r in listed(d, query="the fare table on wharf")["sessions"]][0].startswith("wharf")
    everyone[70].owner = "Avi"
    assert [r["name"] for r in listed(d, owner="avi")["sessions"]] == [everyone[70].name]
    assert listed(d, owner="me", machine="box-03")["more"] == 0
    assert listed(d, machine="no-such-box") == {"sessions": [], "more": 0, "machines": out["machines"]}


def test_list_sessions_with_the_rules_off_is_every_session_as_before(d, node, monkeypatch):
    monkeypatch.setenv("POINTE_FLEET", "off")
    build(d, node, 2, 15)
    out = listed(d, machine="box-00")
    assert set(out) == {"sessions"} and len(out["sessions"]) == 30


def test_everywhere_is_answered_machine_by_machine_from_the_counts_in_code(d, node, fleet_on):
    everyone = build(d, node, 5, 20, here=3)
    everyone[30].open_questions = ["Deploy now?"]
    everyone[4].busy = True
    line = d._fleet_overview("what's going on everywhere?")
    assert line == (f"On box-01: 20 sessions, 0 working, {everyone[30].name.replace('-', ' ')} needs you. "
                    "On box-00: 20 sessions, 1 working, none need you. On box-02: 20 sessions, 0 working, none need you. "
                    "And 3 more machines with 43 sessions, none need you.")
    assert d._fleet_overview("tell every session to give me a status update") is None  # work for them, not a question
    assert d._fleet_overview(f"what's going on with {everyone[4].name}?") is None
    d.REGISTRY.sessions.clear()
    for i in range(4):
        add(d, f"s{i}", NAMES[i])
    assert d._fleet_overview("what's going on everywhere?") is None  # two to five: the sessions themselves answer


def test_everywhere_on_a_big_fleet_is_said_by_the_daemon_and_the_model_takes_no_step(d, node, fleet_on, monkeypatch):
    front, spoken, asked, say = _call(d, monkeypatch, ["never said"])
    build(d, node, 2, 10)
    asyncio.run(say("What's going on everywhere?"))
    assert asked == [] and len(spoken) == 1
    assert spoken[0] == ("On box-00: 10 sessions, 0 working, none need you. On box-01: 10 sessions, 0 working, none "
                         "need you. Here: 1 session, 0 working, none need you.")
    assert front.brain.messages[-1] == {"role": "assistant", "calls": [], "said": spoken[0]}


def test_the_tool_takes_a_machine_an_owner_a_state_and_a_query(d):
    tool = next(t for t in d.TOOLS.standard_tools if t.name == "list_sessions")
    assert set(tool.properties) == {"machine", "owner", "state", "query"} and tool.required == []
    assert tool.properties["state"]["enum"] == list(scale.STATES)


# ---------- quiet sessions ----------

@pytest.fixture
def call(d, node, fleet_on, monkeypatch):
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "_night_report", lambda s, r: asyncio.sleep(0))
    monkeypatch.setattr(d, "_add_worker", lambda s: asyncio.sleep(0))
    refreshed: list[str] = []

    async def refresh(s):
        refreshed.append(s.name)
    monkeypatch.setattr(d, "_refresh_brief", refresh)
    voice = Voice(d)
    conn = fake_conn()
    conn.injector = voice.injector
    d.state.conn, d.state.front, d.state.meeting = conn, None, None
    d.HELD.take()
    yield voice, refreshed
    d.HELD.take()
    d.state.conn = None


def finished(d, name: str, final: str = "All 12 tests pass.") -> str:
    return f"[{name} {d.FINISHED_MARK} {d.FINAL_MARK}{final}"


def reader(d, monkeypatch) -> list[str]:
    """The reading model, faked at its one seam: which sessions it was called for."""
    read: list[str] = []

    async def model(system, prompt, thinking=None):
        d.state.fleet_stats["reader_calls"] += 1
        read.append(prompt)
        return {"line": "done", "say": "done", "speak": True}
    monkeypatch.setattr(d, "_read_model", model)
    return read


def test_a_quiet_sessions_finished_turn_is_not_read_until_it_asks_or_is_named(d, node, call, monkeypatch):
    voice, refreshed = call
    read = reader(d, monkeypatch)
    everyone = build(d, node, 1, 30)
    tier = d._fleet_tiers()
    quiet = next(s for s in everyone if tier[s.id] == scale.QUIET)
    background = next(s for s in everyone if tier[s.id] == scale.BACKGROUND)

    async def run():
        await d.feed(quiet, finished(d, quiet.name), True)
        assert read == [] and d.state.fleet_stats["reader_skipped"] == 1 and quiet.name not in voice.told()
        await d.feed(background, finished(d, background.name), True)
        assert len(read) == 1  # the 20 most recent are read as before
        await d.feed(quiet, finished(d, quiet.name, "Both pass. Which one should I merge?"), True)
        assert len(read) == 2  # its last words ask something: read, so it can need the user
        quiet.active_at = time.time()  # its own work does not make it one of the twenty: only the user's words do
        await d.feed(quiet, finished(d, quiet.name), True)
        assert len(read) == 2 and quiet.id in d.state.fleet_unread
        refreshed.clear()
        d._fleet_heard(f"what did {quiet.name} do?")  # named: in focus, and its notes are read now
        await asyncio.sleep(0)
        assert refreshed == [quiet.name] and d._fleet_tiers()[quiet.id] == scale.FOCUS
        await d.feed(quiet, finished(d, quiet.name), True)
        assert len(read) == 3
    asyncio.run(run())
    view = client_for(d).get("/voice/context").json()["fleet"]
    assert view["stats"]["reader_skipped"] == 2 and view["stats"]["reader_calls"] == 3
    assert view["tiers"] == {"focus": 3, "background": 20, "quiet": 7}  # the active one, the thread, the one named


def test_with_the_rules_off_every_finished_turn_is_read(d, node, call, monkeypatch):
    monkeypatch.setenv("POINTE_FLEET", "off")
    read = reader(d, monkeypatch)
    everyone = build(d, node, 1, 30)
    asyncio.run(d.feed(everyone[1], finished(d, everyone[1].name), True))  # the least recent: quiet with the rules on
    assert len(read) == 1 and d.state.fleet_stats["reader_skipped"] == 0


def test_keep_tide_quiet_marks_it_by_the_name_said_and_stop_keeping_it_quiet_lifts_it(d, fleet_on):
    tide, harbor = add(d, "a", "tide"), add(d, "b", "harbor")
    add(d, "c", "lantern")
    d._fleet_heard("keep harbor quiet")
    assert (tide.quiet, harbor.quiet) == (False, True) and d._fleet_tiers()["b"] == scale.QUIET
    d._fleet_heard("tell harbor to keep quiet about the release")  # a request to it, not a mark on it
    d._fleet_heard("keep it quiet")  # no name said: nothing is marked by a guess
    assert (tide.quiet, harbor.quiet) == (False, True)
    d._fleet_heard("stop keeping harbor quiet")
    assert harbor.quiet is False and d._fleet_tiers()["b"] != scale.QUIET
    assert scale.quiet_intent("keep tide quiet") == (True, "tide") and scale.quiet_intent("be quiet") is None
    assert "quiet" in sessions_mod.PERSISTED


# ---------- speech ----------

def spoken_lines(d, voice) -> list[str]:
    """Each line the voice was asked to say: a turn of several updates counts each of them."""
    out = []
    for f in voice.frames:
        if isinstance(f, d.InputTextRawFrame):
            parts = scale.re.split(r"\n\d+\. ", f.text)
            out += parts[1:] if f.text.startswith("[updates:") else [f.text]
    return out


def test_thirty_sessions_finish_in_a_minute_four_lines_are_spoken_and_the_rest_are_held(d, node, call, monkeypatch):
    voice, _ = call
    _reports(d, monkeypatch)
    everyone = build(d, node, 3, 10, here=1)[1:]  # one here is the active session; thirty others finish
    assert len(everyone) == 30

    async def run():
        for s in everyone:
            await d.feed(s, finished(d, s.name), True)
        for _ in range(3):  # the gaps in the conversation that follow
            voice.injector._asked_at = 0.0
            await voice.injector._deliver_if_free()
    asyncio.run(run())
    lines = spoken_lines(d, voice)
    assert 1 <= len(lines) <= 4, lines
    assert any(scale.re.search(r"(Nine|Ten) on box-0\d finished: \S+, \S+, \S+ and \d more\.$", x) for x in lines), lines
    said = {s.name for s in everyone if any(s.name in x or s.name.replace("-", " ") in x for x in lines)}
    held = {i.session for i in d.HELD.items}
    assert said | held == {s.name for s in everyone} and not said & held  # nothing lost, nothing twice
    stats = d.state.fleet_stats
    assert stats["report_lines_spoken"] == len(lines) and stats["reports_spoken"] == len(said)
    assert stats["reports_held"] == len(held) == client_for(d).get("/voice/status").json()["held"]["count"]

    async def ask():
        assert await d._asked_for_held("anything from the others?") is True
    asyncio.run(ask())  # "anything else?": told from the held list
    assert len(d.HELD) == 0


def test_the_speech_plan_coalesces_per_machine_names_a_question_and_never_holds_one():
    r = scale.Report
    lines, held = scale.plan_speech([r("tide", "avi-box"), r("harbor", "avi-box"), r("skiff", "avi-box", True)], 0)
    assert [x.text for x in lines] == ["Three on avi-box finished: skiff, tide and harbor; skiff has a question."] and not held
    lines, held = scale.plan_speech([r("tide", "avi-box"), r("harbor")], 0)
    assert [x.text for x in lines] == ["", ""] and not held  # two: each as it came
    many = [r(f"n{i}", f"box-{i % 6}", question=(i == 5)) for i in range(18)]
    lines, held = scale.plan_speech(many, spoken_lately=3)
    assert len([x for x in lines if x.text]) == 1 and lines[0].text.startswith("Three on box-5 finished: n5,")
    assert {s for x in lines for s in x.sessions} | {h.session for h in held} == {x.session for x in many}
    lines, held = scale.plan_speech(many, spoken_lately=4)  # the minute is full: only the question is said
    assert [x.sessions for x in lines] == [("n5",)] and len(held) == 17
    assert scale.coalesced("", [r("a"), r("b"), r("c")], several=False).text == "Three finished: a, b and c."


def test_approvals_then_sessions_that_need_the_user_then_the_thread_then_the_rest(d, node, call):
    voice, _ = call
    here = build(d, node, 1, 6, here=1)
    needs, thread, rest = here[1], here[2], here[3]
    needs.open_questions = ["Merge?"]
    thread.last_delegation_at = time.time()
    d.state.thread = (thread.id, time.time())
    items = [f"[{rest.name} finished its turn, not the active session] Say one short line:\nrest",
             f"[{thread.name} finished its turn, not the active session] Say one short line:\nthread",
             f"[{needs.name} finished its turn, not the active session] Say one short line:\nneeds",
             f"[{here[4].name} is waiting for a permission, not the active session] Tell the user in one line."]
    order = [x.rsplit("\n", 1)[-1][-6:] for x in d._fleet_speech(items)]
    assert order == [" line.", "needs", "thread", "rest"]


def test_the_fleet_rules_are_off_until_somebody_switches_them_on(monkeypatch):
    """Released off: nothing about routing, the brain's context or what is spoken changes before the benchmark has
    measured the rules."""
    monkeypatch.delenv("POINTE_FLEET", raising=False)
    assert not scale.enabled()
    monkeypatch.setenv("POINTE_FLEET", "on")
    assert scale.enabled()
    monkeypatch.setenv("POINTE_FLEET", "off")
    assert not scale.enabled()
