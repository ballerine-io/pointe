"""The scripted user turns of the fleet benchmark, and what each should lead to, labelled by rule from the fleet's
description: never by a model, and never by looking at a run. Standard library only.

    python -I bench/fleet/turns.py write      writes dataset/fleet-<size>.json and dataset/turns-<size>.json
    python -I bench/fleet/turns.py freeze     writes FROZEN.json with their hashes (before any paid row)
    python -I bench/fleet/turns.py check      the files on disk are what the generator writes, and what FROZEN.json names

60 turns a size, in eight kinds (six at 1x4, where one machine has no shared names). The same slots at every size: slot n of a kind takes its task and its
wording from the same place, and its session from the fleet by the rule below.

  clear_name           "Tell tide to <task>."                 one session has that name            -> that session
  clear_machine_name   "Tell shop on avi-box to <task>."      a shared name, with its machine      -> that session
  clear_description    "Tell the session working on the coupon ledger to <task>." or "Ask whoever has
                       coupon_ledger.py to <task>."           one session has that topic and file  -> that session
  ambiguous_name       "Tell shop to <task>."                 several machines have a "shop"       -> ask, send nothing
  ambiguous_description  the topic two sessions share                                              -> ask, send nothing
  ambiguous_none       a name or a topic no session has                                            -> ask, send nothing
  needs_me             "What needs me?"                       -> the sessions whose state is asks or permission
  on_machine           "What's on avi-box?"                   -> the sessions on that machine

At 1x4 there is one machine, so no name is shared: a clear_machine_name slot becomes a clear_name turn, and an
ambiguous_name slot becomes an ambiguous_description or ambiguous_none turn (`mapped_from` says which slot it was).
A send is labelled with one session id. "Ask" is the label of every ambiguous turn; the daemon's own design answers
"tell shop" with this Mac's shop when this Mac has one (daemon._tell_apart), and the label does not follow it:
`this_mac_holds` marks those turns so the report can show them apart.
"""

import hashlib
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen  # noqa: E402

DATASET = HERE / "dataset"
FROZEN = HERE / "FROZEN.json"
SIZES = ("1x4", "5x20", "10x30")  # the benchmark's; gen.SIZES also has the self-test's 2x3
VERSION = "fleet-0.1"
TASKS = ["rebase onto main", "run the tests", "add a docstring to the main function", "bump the patch version",
         "write a changelog entry for today's change", "list the open TODO comments",
         "run the linter and fix what it reports", "summarize what changed since yesterday",
         "add a unit test for the empty input case", "rename the helper to something clearer",
         "check that the README matches the code", "print the last commit message",
         "add type hints to the public functions", "look for a flaky test and say which one",
         "say how long the test suite takes", "add a timeout to the network call",
         "check for a newer version of its main dependency", "sort the imports",
         "add a comment explaining the retry loop", "show the size of the largest file", "count the failing tests",
         "say which function is the longest", "check the code coverage", "list the files changed today"]
ABSENT_NAMES = ["nimbus", "drizzle", "mirage", "bonfire"]  # no fleet has a session of these names
ABSENT_TOPICS = ["passport scanner", "elevator firmware", "telescope mount", "greenhouse sensor"]
NEEDS = ["What needs me?", "What needs me right now?", "Is anything waiting on me?",
         "Which sessions are waiting for me?", "Does any session need an answer from me?", "What is blocked on me?"]
ON_MACHINE = ["What's on {machine}?", "What is running on {machine}?", "Which sessions are on {machine}?",
              "What's going on on {machine}?", "List the sessions on {machine}.", "What do I have on {machine}?"]
COUNTS = {"clear_name": 12, "clear_machine_name": 10, "clear_description": 12, "ambiguous_name": 6,
          "ambiguous_description": 4, "ambiguous_none": 4, "needs_me": 6, "on_machine": 6}
CLEAR = ("clear_name", "clear_machine_name", "clear_description")
AMBIGUOUS = ("ambiguous_name", "ambiguous_description", "ambiguous_none")


def _verb(n: int) -> str:
    return "Tell" if n % 2 == 0 else "Ask"


def turns(described: dict) -> list[dict]:
    sessions = described["sessions"]
    rng = random.Random(f"{described['sha256']}/turns")
    hosts = described["hosts"]
    plain = [s for s in sessions if not s["shared_name"]]
    unique = [s for s in plain if not s["twin"]]  # one name and one topic: nobody else has either
    shared = [s for s in sessions if s["shared_name"]]
    twins: dict[str, list[dict]] = {}
    for s in sessions:
        if s["twin"]:
            twins.setdefault(s["topic"], []).append(s)
    assert all(a not in {s["name"] for s in sessions} for a in ABSENT_NAMES)
    assert all(a not in {s["topic"] for s in sessions} for a in ABSENT_TOPICS)

    def spread(pool: list[dict], n: int) -> list[dict]:
        """n sessions from the pool, machine by machine in turn, each once before any twice."""
        by_machine = {m: [s for s in rng.sample(pool, len(pool)) if s["machine"] == m] for m in described["machines"]}
        picked, round_ = [], 0
        while len(picked) < n:
            took = False
            for m in described["machines"]:
                if round_ < len(by_machine[m]) and len(picked) < n:
                    picked.append(by_machine[m][round_])
                    took = True
            round_ = round_ + 1 if took else 0  # a pool smaller than n: around again
        return picked

    out: list[dict] = []
    task = iter(TASKS * 4)

    def add(kind: str, slot: int, text: str, expect: dict, why: str, **more) -> None:
        out.append({"id": f"{kind}-{slot:02d}", "kind": kind, "slot": slot, "text": text, "expect": expect, "label": why, **more})

    def clear_name(kind_slot: tuple[str, int], s: dict, **more) -> None:
        kind, slot = kind_slot
        add("clear_name", slot, f"{_verb(slot)} {s['name']} to {next(task)}.", {"action": "send", "session": s["id"]},
            f"the only session named {s['name']}", **more)

    def by_topic(slot: int, topic: str) -> str:
        return f"{_verb(slot)} the session working on the {topic} to {next(task)}."

    def ambiguous_description(slot: int, n: int, **more) -> None:
        topic = sorted(twins)[n % len(twins)]
        add("ambiguous_description", slot, by_topic(slot, topic), {"action": "ask", "fits": [s["id"] for s in twins[topic]]},
            f"two sessions work on the {topic}", **more)

    def ambiguous_none(slot: int, n: int, **more) -> None:
        if n % 2 == 0:
            name = ABSENT_NAMES[(n // 2) % len(ABSENT_NAMES)]
            add("ambiguous_none", slot, f"{_verb(slot)} {name} to {next(task)}.", {"action": "ask", "fits": []},
                f"no session is named {name}", **more)
        else:
            topic = ABSENT_TOPICS[(n // 2) % len(ABSENT_TOPICS)]
            add("ambiguous_none", slot, by_topic(slot, topic), {"action": "ask", "fits": []}, f"no session works on the {topic}", **more)

    named = spread(plain, COUNTS["clear_name"] + (COUNTS["clear_machine_name"] if hosts == 1 else 0))
    for slot in range(COUNTS["clear_name"]):
        clear_name(("clear_name", slot), named[slot])
    for slot in range(COUNTS["clear_machine_name"]):
        if hosts == 1:
            clear_name(("clear_name", COUNTS["clear_name"] + slot), named[COUNTS["clear_name"] + slot],
                       mapped_from=f"clear_machine_name-{slot:02d}")
            continue
        s = sorted(shared, key=lambda s: (s["name"], s["machine"]))[slot % len(shared)]
        add("clear_machine_name", slot, f"{_verb(slot)} {s['name']} on {s['machine']} to {next(task)}.",
            {"action": "send", "session": s["id"]}, f"the session named {s['name']} on {s['machine']}")
    described_ = spread([s for s in unique if s not in named] or unique, COUNTS["clear_description"])
    for slot, s in enumerate(described_):
        if slot % 2 == 0:
            text, why = by_topic(slot, s["topic"]), f"the only session whose goal is about the {s['topic']}"
        else:
            text, why = f"{_verb(slot)} whoever has {s['files'][0]} to {next(task)}.", f"the only session with {s['files'][0]}"
        add("clear_description", slot, text, {"action": "send", "session": s["id"]}, why)
    extra_e = extra_f = 0
    for slot in range(COUNTS["ambiguous_name"]):
        if hosts == 1:  # no shared names on one machine: the slot goes to the two other ambiguous kinds in turn
            if slot % 2 == 0:
                ambiguous_description(COUNTS["ambiguous_description"] + extra_e, COUNTS["ambiguous_description"] + extra_e,
                                      mapped_from=f"ambiguous_name-{slot:02d}")
                extra_e += 1
            else:
                ambiguous_none(COUNTS["ambiguous_none"] + extra_f, COUNTS["ambiguous_none"] + extra_f,
                               mapped_from=f"ambiguous_name-{slot:02d}")
                extra_f += 1
            continue
        base = sorted(described["shared_names"])[slot % len(described["shared_names"])]
        holders = described["shared_names"][base]
        add("ambiguous_name", slot, f"{_verb(slot)} {base} to {next(task)}.",
            {"action": "ask", "fits": [s["id"] for s in shared if s["name"] == base]},
            f"{len(holders)} machines have a session named {base}", this_mac_holds=described["voice_machine"] in holders)
    for slot in range(COUNTS["ambiguous_description"]):
        ambiguous_description(slot, slot)
    for slot in range(COUNTS["ambiguous_none"]):
        ambiguous_none(slot, slot)
    waiting = [s["id"] for s in gen.waiting(described)]
    for slot, text in enumerate(NEEDS):
        add("needs_me", slot, text, {"action": "answer", "sessions": waiting},
            "the sessions whose state is asks or permission in the fleet's description")
    for slot, wording in enumerate(ON_MACHINE):
        machine = described["machines"][slot % hosts]
        add("on_machine", slot, wording.format(machine=machine),
            {"action": "answer", "machine": machine, "sessions": [s["id"] for s in gen.on_machine(described, machine)]},
            f"the sessions on {machine} in the fleet's description")
    assert len({t["id"] for t in out}) == len(out) and len({t["text"] for t in out}) == len(out), "two turns alike"
    return out


def built() -> dict[str, str]:
    """Every dataset file as the generator writes it now: name -> text."""
    files = {}
    for size in SIZES:
        described = gen.fleet(size)
        files[f"fleet-{size}.json"] = json.dumps(described, indent=1, ensure_ascii=False) + "\n"
        files[f"turns-{size}.json"] = json.dumps(turns(described), indent=1, ensure_ascii=False) + "\n"
    return files


def dataset_sha() -> str:
    """One hash over the dataset files on disk, names and bytes in order."""
    h = hashlib.sha256()
    for path in sorted(DATASET.glob("*.json")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def frozen() -> dict:
    return json.loads(FROZEN.read_text()) if FROZEN.exists() else {}


def load(size: str) -> tuple[dict, list[dict]]:
    return (json.loads((DATASET / f"fleet-{size}.json").read_text()), json.loads((DATASET / f"turns-{size}.json").read_text()))


def check() -> list[str]:
    """What is wrong with the dataset on disk; [] when it is the generator's and the frozen one."""
    problems = []
    for name, text in built().items():
        path = DATASET / name
        if not path.exists() or path.read_text() != text:
            problems.append(f"{name} is not what the generator writes")
    if not FROZEN.exists():
        problems.append("FROZEN.json is missing: freeze the dataset before any paid row")
    elif frozen().get("dataset_sha256") != dataset_sha():
        problems.append("the dataset's hash is not the one in FROZEN.json")
    return problems


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "write":
        assert not FROZEN.exists(), "the dataset is frozen: a new one is a new version, with FROZEN.json's `earlier`"
        DATASET.mkdir(exist_ok=True)
        for name, text in built().items():
            (DATASET / name).write_text(text)
        for size in SIZES:
            kinds: dict[str, int] = {}
            for t in turns(gen.fleet(size)):
                kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
            print(size, sum(kinds.values()), kinds)
    elif command == "freeze":
        assert not FROZEN.exists(), "already frozen"
        assert not [p for p in check() if "FROZEN" not in p], check()
        FROZEN.write_text(json.dumps({
            "benchmark": "fleet", "dataset_version": VERSION, "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dataset_sha256": dataset_sha(), "fleet_seed": gen.SEED,
            "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATASET.glob("*.json"))},
            "note": "Frozen before any paid row. Expected outcomes are labelled by rule from the fleet's description "
                    "(bench/fleet/turns.py), never by a model. Reader notes made by a paid pass are not part of this "
                    "hash: each run's manifest names the notes it used."}, indent=1) + "\n")
        print("frozen:", dataset_sha())
    else:
        problems = check()
        print("\n".join(problems) or f"ok: {dataset_sha()}")
        sys.exit(1 if problems else 0)
