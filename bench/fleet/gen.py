"""The fleet a benchmark run is about: H machines with S coding-agent sessions each, every one invented, and the
same fleet from the same seed on any machine. Standard library only.

    python -I bench/fleet/gen.py 5x20 [--seed 20261126]      prints the fleet's description as JSON

A machine is a name; the first is the voice's own. A session is a name (a few collide across machines on purpose:
"shop", "api", "web"), a goal sentence about a topic of two words, the files it works on, its harness, and the state
it starts in: idle (its last turn ended), asks (its last turn ended with a question to its owner), permission (it
stands at a permission prompt), working (in the middle of a turn). `finish_at` is when a working session ends its turn
in the burst scenario, in seconds from the burst's start. Some topics are given to two sessions (twins): a request that
only describes that work fits both.
"""

import argparse
import hashlib
import json
import random
import uuid

SEED = 20261126
SIZES = {"1x4": (1, 4), "2x3": (2, 3), "5x20": (5, 20), "10x30": (10, 30)}  # 2x3 is the offline self-test's
MACHINES = ["studio", "avi-box", "dana-rig", "omer-lab", "noa-mini", "lior-tower", "maya-node", "eitan-rack",
            "tamar-nuc", "gil-cube"]
SHARED = ["shop", "api", "web", "docs"]  # the names several machines have a session of
# Session names: one plain word each, no two within an edit or two of each other (checked in fleet()).
NAMES = """tide lantern quarry orchard harbor falcon ember willow cobalt juniper meadow pebble raven saffron thistle
umber velvet walnut yonder zephyr anchor beacon cedar dahlia eagle fjord garnet heron indigo jasper kestrel lagoon
magnet nectar onyx pepper quill russet sable topaz ultra vortex wicker xenon yarrow zinnia acorn bramble cactus
dune elm fennel ginger hazel iris jade kelp lotus maple nutmeg olive poppy quince rowan sorrel tulip urchin violet
wasabi yucca alder birch clover daisy fern gorse holly ivy jonquil lupin mallow nettle orchid peony reed sedge
tansy vetch woad aspen basil chive dill endive flax garlic hops kale leek mint nori okra parsley radish sage
thyme agate basalt chalk dolomite flint gneiss granite marble obsidian pumice quartz schist shale slate tuff
zircon amber bronze copper nickel pewter silver titan zinc brass chrome argon boron carbon helium iodine krypton
lithium neon oxygen radon sodium atlas comet delta eclipse galaxy horizon jupiter meteor nebula orbit pulsar
quasar saturn umbra vega zenith badger cougar dingo ermine ferret gecko hyena ibex jackal koala lemur marmot
narwhal ocelot panda quokka rhino tapir vole walrus yak zebra albatross bittern condor dunlin egret finch gannet
harrier ibis jay kite linnet magpie osprey petrel robin shrike tern vireo wren avocet canyon estuary
glacier isthmus mesa oasis prairie ravine savanna tundra volcano wadi arroyo bayou cove dell fen glen knoll
moor plateau ridge scarp tarn vale weald bastion citadel dungeon gantry hangar jetty kiln lodge manor outpost
pavilion rampart silo turret viaduct wharf abacus bellows compass dynamo easel funnel gasket hammer inkwell
jigsaw keystone ladle mortar nozzle pulley ratchet sextant trowel valve winch zipper banjo cello drum fiddle
gong harp kazoo lute oboe piccolo sitar tuba ukulele viola zither almond brioche crumpet danish eclair fondue
gelato hummus kebab lasagna muffin noodle omelet pretzel ravioli sorbet tamale waffle bishop castle gambit
knight pawn rook checker domino puzzle riddle tangram yoyo cipher matrix pixel raster vector
widget gizmo sprocket cog flange grommet rivet shim spindle washer bobbin lathe loom shuttle spool treadle
barley millet quinoa rye sorghum wheat cocoa chicory mocha pekoe rooibos sencha""".split()
NAMES = [n for n in NAMES if n.isalpha() and n not in SHARED]
TOPIC_A = ["coupon", "invoice", "tariff", "refund", "payroll", "shipment", "roster", "voucher", "booking", "billing",
           "inventory", "catalog", "signup", "audit", "pricing", "loyalty", "warranty", "dispatch", "tenant", "quota",
           "ticket", "returns", "currency", "delivery", "receipt", "wishlist", "survey", "consent", "profile", "banner"]
TOPIC_B = ["ledger", "export", "cache", "parser", "queue", "scheduler", "importer", "webhook", "throttle", "digest",
           "migration", "indexer", "validator", "notifier", "archive", "dashboard", "resolver", "batcher", "sampler",
           "watchdog"]
GOALS = ["Migrate the {topic} to the new schema without downtime.",
         "Find why the {topic} drops records under load and fix it.",
         "Add retries with backoff to the {topic} and cover them with tests.",
         "Cut the {topic}'s cold start time by half.",
         "Make the {topic} safe to run twice with the same input.",
         "Move the {topic} off the deprecated client library.",
         "Add structured logging to the {topic} and remove the print calls.",
         "Split the {topic} into a reader and a writer with a clear interface."]
QUESTIONS = ["I can keep the old column for one release or drop it now. Which do you want?",
             "The fix needs either a lock or a retry. A lock is simpler, a retry is faster. Which one?",
             "Two tests fail before my change as well. Should I fix them here or leave them?",
             "I can write this against the v2 interface or keep v1. Which should I target?"]
HARNESS = "claude-code"  # every stand-in writes a Claude Code record; other harnesses are not simulated
BURST = 30  # sessions that end their turn within the burst's minute
BURST_SECS = 60.0


def _apart(a: str, b: str) -> bool:
    """Two names a recognizer or a reader could not take for one another: no shared four-letter start, and neither
    inside the other."""
    return a[:4] != b[:4] and a not in b and b not in a


def fleet(size: str, seed: int = SEED) -> dict:
    hosts, per_host = SIZES[size]
    rng = random.Random(f"{seed}/{size}")
    machines = MACHINES[:hosts]
    total = hosts * per_host
    # which machines hold a shared name: the voice's own always, then the next ones
    shared: dict[str, list[str]] = {}
    if hosts > 1:
        for i, base in enumerate(SHARED[:1 if hosts < 3 else 3 if hosts < 8 else 4]):
            holders = min(hosts, 4 if i == 0 else 3)
            shared[base] = [machines[(i + k) % hosts] for k in range(holders)]
    pool: list[str] = []
    for name in rng.sample(NAMES, len(NAMES)):
        if all(_apart(name, kept) for kept in pool):
            pool.append(name)
    topics = [f"{a} {b}" for a in TOPIC_A for b in TOPIC_B]
    rng.shuffle(topics)
    twins = 1 if total < 20 else 4  # pairs of sessions with one topic
    sessions = []
    for m, machine in enumerate(machines):
        names = [base for base, holders in shared.items() if machine in holders]
        while len(names) < per_host:
            names.append(pool.pop())
        for name in names:
            sid = str(uuid.UUID(int=rng.getrandbits(128), version=4))
            sessions.append({"id": sid, "machine": machine, "name": name, "shared_name": name in shared,
                             "harness": HARNESS})
    assert len(sessions) == total and len({s["id"] for s in sessions}) == total
    # topics: the first 2*twins sessions that do not share a name, on different machines where there are several
    plain = [s for s in sessions if not s["shared_name"]]
    rng.shuffle(plain)
    paired: list[tuple[dict, dict]] = []
    rest = list(plain)
    while len(paired) < twins:
        a = rest.pop(0)
        b = next(s for s in rest if hosts == 1 or s["machine"] != a["machine"])
        rest.remove(b)
        paired.append((a, b))
    for a, b in paired:
        a["topic"] = b["topic"] = topics.pop()
        a["twin"], b["twin"] = b["id"], a["id"]
    for s in sessions:
        if "topic" not in s:
            s["topic"], s["twin"] = topics.pop(), None
        word_a, word_b = s["topic"].split()
        s["goal"] = rng.choice(GOALS).format(topic=s["topic"])
        s["files"] = [f"{word_a}_{word_b}.py", f"test_{word_a}_{word_b}.py", "README.md"]
    # states: who waits on the owner (a question, a permission prompt), who works, who is idle
    order = [s for s in sessions if not s["twin"] and not s["shared_name"]]  # named by one word nobody else has
    rng.shuffle(order)
    asks = 1 if total < 20 else max(2, round(total * 0.04))
    prompts = 1 if total < 20 else max(2, round(total * 0.01))
    for s in sessions:
        s["state"], s["finish_at"], s["question"] = "idle", None, ""
    for s in order[:asks]:
        s["state"], s["question"] = "asks", rng.choice(QUESTIONS)
    for s in order[asks:asks + prompts]:
        s["state"] = "permission"
    others = [s for s in sessions if s["state"] == "idle"]
    rng.shuffle(others)
    working = others[:len(others) // 2]
    for s in working:
        s["state"] = "working"
    for s in sorted(working, key=lambda s: s["id"])[:BURST]:
        s["finish_at"] = round(rng.uniform(0, BURST_SECS), 1)
    described = {"size": size, "seed": seed, "hosts": hosts, "per_host": per_host, "voice_machine": machines[0],
                 "machines": machines, "shared_names": shared, "sessions": sessions}
    described["sha256"] = sha(described)
    return described


def sha(described: dict) -> str:
    body = {k: v for k, v in described.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def waiting(described: dict) -> list[dict]:
    """The sessions that wait on their owner, from the description alone."""
    return [s for s in described["sessions"] if s["state"] in ("asks", "permission")]


def on_machine(described: dict, machine: str) -> list[dict]:
    return [s for s in described["sessions"] if s["machine"] == machine]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("size", choices=sorted(SIZES))
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    print(json.dumps(fleet(a.size, a.seed), indent=1, ensure_ascii=False))
