"""The suite pages: docs/benchmarks/README.md, one docs page per benchmark (HLK writes its own, docs/benchmarks/hlk.md)
and site/pointe/benchmarks/index.html, all from the committed results of the five benchmarks. Nothing here imports a
benchmark's code: it reads the JSON each one's `run.py report` writes, the ledgers, and the Limits section of each
benchmark's README. tests/test_conversational_publish.py regenerates every page and fails on any difference.

    uv run --locked python bench/conversational/publish.py
"""

import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCS = ROOT / "docs" / "benchmarks"
PAGE = ROOT / "site" / "pointe" / "benchmarks" / "index.html"
GITHUB = "https://github.com/ballerine-io/pointe/blob/main/"

# The published run of each benchmark, as its own report names it, and the cap the design gave it (budget rules).
RUNS = {"identifiers": "identifiers-20261123-031106", "actions": "act-20261123-033255",
        "routing": "routing-20261123-0331-d17a", "bargein": "bargein-20261123-040244"}
CAP = {"hlk": 55, "identifiers": 12, "actions": 17, "routing": 9, "bargein": 14}
ORDER = ["hlk", "identifiers", "actions", "routing", "bargein"]
NAME = {"hlk": "Humanity's Last Keystroke (HLK)", "identifiers": "Spoken Identifiers",
        "actions": "Spoken Actions and False Approval", "routing": "Session Routing",
        "bargein": "Barge-in and Time to a Correct Answer"}
QUESTION = {
    "hlk": "Is a small scripted coding task finished by voice only, when the keyboard version is finished?",
    "identifiers": "When a symbol in the repository is spoken, does the agent change the right one and nothing else?",
    "actions": "Does speech become the right harness action, and how often does something that is not a yes approve a "
               "destructive prompt?",
    "routing": "With four live sessions, does a spoken request reach the right one, and is an ambiguous one asked about?",
    "bargein": "Can speech stop, undo or redirect a working agent, and how long until the first correct spoken answer?",
}
README = {"hlk": "hlk/hlk/README.md", "identifiers": "identifiers/identifiers/README.md",
          "actions": "actions/actions/README.md", "routing": "routing/routing/README.md",
          "bargein": "bargein/bargein/README.md"}
FULL = {"hlk": "docs/benchmarks/hlk.md", "identifiers": f"bench/conversational/identifiers/results/{RUNS['identifiers']}/summary.md",
        "actions": "bench/conversational/actions/actions/RESULTS.md", "routing": "bench/conversational/routing/routing/RESULTS.md",
        "bargein": "bench/conversational/bargein/bargein/RESULTS.md"}
SITE_DETAIL = {"hlk": "hlk/", "actions": "actions/"}
REGISTER = {"hlk": "core/runner.py: make_adapter", "identifiers": "identifiers/bench.py: make_adapter",
            "actions": "run.py: adapter_for", "routing": "run.py: make_arm", "bargein": "bargein/bench.py: make_adapter"}
LABEL = {"keyboard-canonical": "keyboard, canonical", "keyboard-transcript": "keyboard, transcript", "keyboard": "keyboard",
         "pointe": "Pointe", "pointe-text": "Pointe, typed text", "llm-router": "LLM router", "naive": "keyword rules, ours",
         "null": "null (does nothing)"}


# The run published before Pointe fixed what this suite found, kept as it was: its pages in docs/benchmarks/earlier/,
# its results in the files below. The rerun replaced only the Pointe arm.
EARLIER_DATE = "2026-11-23"
EARLIER = {"hlk": ("hlk/results/summary-2026-11-23-pointe-6544cdc.json", "6544cdc"),
           "identifiers": ("identifiers/results/identifiers-20261123-031106/summary.json", "6544cdc"),
           "actions": ("actions/results/act-20261123-033255/results.json", "6544cdc"),
           "routing": ("routing/results/routing-20261123-0331-d17a/results.json", "6544cdc"),
           "bargein": ("bargein/results/bargein-20261123-040244/results.json", "7113efa")}


def load_earlier() -> dict:
    return {k: json.loads((HERE / path).read_text()) for k, (path, _) in EARLIER.items()}


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    z, p_ = 1.959964, k / n
    mid, half = (p_ + z * z / (2 * n)), z * ((p_ * (1 - p_) + z * z / (4 * n)) / n) ** 0.5
    return (mid - half) / (1 + z * z / n), (mid + half) / (1 + z * z / n)


def pointe_measures(key: str, s: dict) -> list[tuple[str, int, int, float, float]]:
    """The Pointe arm's headline counts of one benchmark's results: (measure, k, n, low, high), 95% Wilson."""
    if key == "hlk":
        k, n = s["passes"]["pointe"]
        return [("tasks passed", k, n, *wilson(k, n))]
    if key == "identifiers":
        v = s["arms"]["pointe"]["right_symbol"]
        return [("right symbol", v["k"], v["n"], *v["wilson95"])]
    if key == "actions":
        P = s["scores"]["pointe"]
        return [(label, P[m]["k"], P[m]["n"], P[m]["lo"], P[m]["hi"]) for label, m in
                (("action accuracy", "accuracy"), ("false approval (lower is better)", "false_approval"),
                 ("false denial (lower is better)", "false_denial"), ("missed stop (lower is better)", "missed_stop"))]
    if key == "routing":
        P = s["summary"]["pointe"]
        return [("turns routed right", P["correct"], P["turns"], *P["correct_wilson"])]
    A, B = s["part_a"]["pointe"], s["part_b"]["pointe"]
    return [("A: job halted when told to stop", A["halt"]["k"], A["halt"]["n"], *A["halt"]["ci95"]),
            ("B: correct answer within 45 s", B["correct"]["k"], B["correct"]["n"], *B["correct"]["ci95"])]


def before_after(now: dict) -> list[list[str]]:
    then = load_earlier()
    rows = []
    for k in ORDER:
        old, new = pointe_measures(k, then[k]), pointe_measures(k, now[k])
        for (label, k0, n0, lo0, hi0), (_, k1, n1, lo1, hi1) in zip(old, new):
            rows.append([NAME[k], label, prop(k0, n0, lo0, hi0), prop(k1, n1, lo1, hi1)])
    return rows


def load() -> dict:
    d = {"hlk": json.loads((HERE / "hlk" / "results" / "summary.json").read_text())}
    d["identifiers"] = json.loads((HERE / "identifiers" / "results" / RUNS["identifiers"] / "summary.json").read_text())
    for k in ("actions", "routing", "bargein"):
        d[k] = json.loads((HERE / k / "results" / RUNS[k] / "results.json").read_text())
    d["routing_run"] = json.loads((HERE / "routing" / "results" / RUNS["routing"] / "run.json").read_text())
    return d


def spend() -> dict:
    """Every launch in each benchmark's ledger: paid runs, smoke, debug, aborted runs and verification reruns."""
    out = {}
    for k in ORDER:
        rows = [json.loads(line) for line in (HERE / k / "results" / "ledger.jsonl").read_text().splitlines() if line.strip()]
        out[k] = sum(r["usd"] for r in rows)
    return out


# ---------- numbers to words ----------

def p(x: float, dp: int = 0) -> str:
    return f"{100 * x:.{dp}f}"


def prop(k: int, n: int, lo: float | None, hi: float | None, dp: int = 0) -> str:
    if not n:
        return "n/a"
    if k == 0:
        return f"0/{n} (upper bound {p(hi, dp)}%)"
    return f"{k}/{n} = {p(k / n, dp)}% ({p(lo, dp)}-{p(hi, dp)}%)"


def delta(d: float, lo: float, hi: float) -> str:
    return f"{100 * d:+.0f} points ({100 * lo:+.0f} to {100 * hi:+.0f})"


# ---------- each benchmark as data: setup, a table, findings, a chart, paired differences ----------

def hlk(s: dict) -> dict:
    arms = s["arms"]
    rows = [[LABEL[a], f"{s['passes'][a][0]}/{s['passes'][a][1]}", f"{p(s['passes'][a][0] / s['passes'][a][1])}%",
             f"{s['flips'][a][0]}/{s['flips'][a][1]}" if s["flips"][a][1] else "n/a",
             f"{s['unpublished'][a][0]}/{s['unpublished'][a][1]}" if a in s["unpublished"] else "not run"] for a in arms]
    g = s["gaps"]
    pf, pr, pe = s["pointe_failed"], s["pointe_failed_refused_yes"], s["pointe_failed_refused_yes_files_changed"]
    return {
        "unit": "task family (12 families, 36 tasks)", "n": "36 tasks in 12 families; two runs per paid arm",
        "setup": [f"Runs {', '.join(s['runs'])}, {', '.join(s['dates'])}",
                  f"Agent {', '.join(s['agent_model'])} in Claude Code {', '.join(s['claude_code'])}, {s['permission_mode']}",
                  f"Pointe {s['pointe_commit'][:7]} (frozen before the first paid row), default setup",
                  f"LLM router brain {', '.join(s['router_brain'])}"],
        "table": (["arm", "passes", "rate", "flips (tasks)", "unpublished seeds"], rows),
        "table_title": "Passes over runs (synthetic speech). Runs of one task are not independent: read the paired gaps.",
        "findings": [
            f"Keyboard, canonical minus Pointe: {delta(*g['keyboard-canonical minus pointe'])}, paired by family.",
            f"Keyboard, canonical minus LLM router: {delta(*g['keyboard-canonical minus llm-router'])}.",
            f"Pointe minus LLM router: {delta(*g['pointe minus llm-router'])}.",
            f"In {pr} of Pointe's {pf} failed runs a spoken yes did not take (Pointe asks for a tap on a request it cannot "
            f"read out) and the voice-only scripted user then said no. That counts runs, not causes: in {pr - pe} of them the "
            f"agent changed no file; in the other {pe} it had already written code that failed, often because Pointe "
            "passed on a wrong instruction.",
            "Known biases against Pointe: a timing race in the scripted user left some of its agents' follow-up questions "
            "unanswered, and one item (spelled-out seed 2) does not say the case it scores."],
        "chart": ("Passes per arm over its runs, synthetic speech",
                  [(LABEL[a], s["passes"][a][0], s["passes"][a][1], None, None, a == "pointe") for a in arms]),
        "families": s,
        "paired": [("HLK, tasks passed", *g["pointe minus llm-router"])],
        "glance": {"pointe": f"{s['passes']['pointe'][0]}/72 passes", "llm-router": f"{s['passes']['llm-router'][0]}/72",
                   "keyboard": f"{s['passes']['keyboard-canonical'][0]}/72"},
        "pointe_commit": s["pointe_commit"][:7],
    }


def identifiers(s: dict) -> dict:
    order = ["keyboard-canonical", "keyboard-transcript", "pointe", "pointe-text", "llm-router", "naive", "null"]
    A = s["arms"]

    def cell(a, m):
        v = A[a][m]
        return prop(v["k"], v["n"], *v["wilson95"])

    rows = [[LABEL[a], cell(a, "right_symbol"), cell(a, "wrong_symbol"), cell(a, "no_action")] for a in order]
    pr = s["paired"]
    c = s["conditions"]
    ex = s["excluded"]["llm-router"]["invalid_out_of_tree"]
    clean, babble = s["slices"]["pointe"]["noise=clean"]["right_symbol"], s["slices"]["pointe"]["noise=babble 12 dB"]["right_symbol"]
    rep = s["repeat"]

    def pd(key):
        v = pr[key]
        return delta(v["right_symbol_diff"], *v["bootstrap95_by_target"])

    return {
        "unit": "target symbol", "n": f"{A['keyboard-canonical']['n_targets']} targets, each spoken in a clean and a 12 dB babble clip",
        "setup": [f"Runs {', '.join(c['run_ids'])}: the Pointe arms from the last, run after the fixes; the LLM router "
                  f"from the second (rerun in full after a harness fix); the other arms from the first. {', '.join(c['dates'])}",
                  f"Agent {c['agent_model']} in Claude Code {', '.join(c['claude_code'])}, {c['permission_mode']}",
                  f"Pointe {c['pointe_commits'][-1][:7]}; one recognizer for every speech arm ({', '.join(c['recognizers'])})",
                  f"LLM router {', '.join(c['router_models'])}; voices {', '.join(c['voices'])}"],
        "table": (["arm", "right symbol", "wrong symbol (harmful)", "no action"], rows),
        "table_title": f"Outcomes per arm (synthetic speech). The LLM router has {A['llm-router']['n_runs']} valid runs: "
                       f"{ex} were excluded for reading outside the repository.",
        "findings": [
            f"Pointe minus LLM router: {pd('pointe - llm-router')}; Pointe minus keyword rules: {pd('pointe - naive')}. "
            "No speech arm is measurably better than another.",
            f"Pointe minus keyboard, canonical: {pd('pointe - keyboard-canonical')}; Pointe typed minus Pointe spoken: "
            f"{pd('pointe-text - pointe')}. Speech costs Pointe something; its text path does not.",
            f"Pointe right on {clean['k']}/{clean['n']} clean clips and {babble['k']}/{babble['n']} under 12 dB babble "
            "(the clean and babble clips use different voices).",
            f"Flip rate on repeated clips: Pointe {rep['pointe']['flips']}/{rep['pointe']['n_pairs']}, "
            f"LLM router {rep['llm-router']['flips']}/{rep['llm-router']['n_pairs']}.",
            "The write/right homophone (t08) is still wrong for Pointe: the recognizer hears the name as \"right column\" "
            "and the agent picks right_column although Pointe now says what the hint means. Code names built from "
            "misheard words now go to the agent with the words as heard; no Pointe row failed that way in this run.",
            "Two of Pointe's three no-action rows are one target (t07) whose speech never reached Pointe: the recognizer's "
            "connection dropped on a loaded machine (load average up to 517 during the run). They are counted as they "
            "came."],
        "chart": ("Right symbol, with 95% Wilson intervals, synthetic speech",
                  [(LABEL[a], A[a]["right_symbol"]["k"], A[a]["right_symbol"]["n"], *A[a]["right_symbol"]["wilson95"], a == "pointe")
                   for a in order]),
        "paired": [("Identifiers, right symbol", pr["pointe - llm-router"]["right_symbol_diff"],
                    *pr["pointe - llm-router"]["bootstrap95_by_target"])],
        "glance": {"pointe": f"{A['pointe']['right_symbol']['k']}/{A['pointe']['right_symbol']['n']} right",
                   "llm-router": f"{A['llm-router']['right_symbol']['k']}/{A['llm-router']['right_symbol']['n']}",
                   "keyboard": f"{A['keyboard-canonical']['right_symbol']['k']}/{A['keyboard-canonical']['right_symbol']['n']}"},
        "pointe_commit": c["pointe_commits"][-1][:7],
    }


def actions(s: dict) -> dict:
    S, m = s["scores"], s["meta"]
    order = ["pointe", "llm-router", "naive", "keyboard", "null"]

    def c(a, key):
        v = S[a][key]
        return prop(v["k"], v["n"], v["lo"], v["hi"], 1)

    rows = [[LABEL[a], c(a, "false_approval"), c(a, "false_denial"), c(a, "accuracy"), c(a, "missed_stop")] for a in order]
    P, R = S["pointe"], S["llm-router"]
    return {
        "unit": "utterance", "n": f"{P['n_items']} utterances; 60 adversarial non-yes on destructive prompts, 20 clear yes",
        "setup": [f"Run {', '.join(m['run_ids'])}, {', '.join(m['dates'])}, {m['rows']} rows",
                  f"Agent {', '.join(m['agent_model'])} in Claude Code {', '.join(m['claude_code'])}, permission mode default",
                  f"Pointe {', '.join(m['pointe_commit'])}, default setup",
                  f"LLM router {', '.join(m['router_model'])}, with a prompt we wrote that names the adversarial types"],
        "table": (["arm", "false approval", "false denial", "action accuracy", "missed stop"], rows),
        "table_title": "Harmful rates beside their opposites (synthetic speech, 95% Wilson intervals)",
        "findings": [
            f"Outside the 8 truncated clips, Pointe and the LLM router both approved "
            f"{P['false_approval_without_truncated']['k']}/{P['false_approval_without_truncated']['n']} and "
            f"{R['false_approval_without_truncated']['k']}/{R['false_approval_without_truncated']['n']} non-yes utterances. "
            "Every approval of either came from a clip cut after its first, yes-like word, and a rerun of those clips "
            "gave different counts: no false-approval ranking between them is claimed.",
            (f"Pointe's false denials: {P['false_denial_voice_readable']['k']}/{P['false_denial_voice_readable']['n']} on "
             f"voice-readable prompts; the rest are commands Pointe never approves by voice and asks a tap for."
             if m.get("tap_only_kinds") else
             "Every command of this benchmark is voice-readable at this Pointe commit: its false denials are yeses it "
             "did not take as a yes (it takes only a plain yes) or did not hear."),
            f"Missed stop: Pointe {P['missed_stop']['k']}/{P['missed_stop']['n']}. A spoken stop ends a Claude Code turn "
            "at its next tool step, through Claude Code's hooks: Claude Code offers another process no supported way to "
            "interrupt a running turn, and the job here is one command, which runs to its end first.",
            f"Pointe's accuracy is {P['accuracy_denial_accepted_on_hedges']['k']}/{P['accuracy_denial_accepted_on_hedges']['n']} "
            "if denying a hedge counted as correct.",
            f"In {len(P['claimed_not_done'])} runs Pointe's spoken reply claimed an approval, rejection or stop that did "
            "not happen."],
        "chart": ("False approval on non-yes utterances, with 95% Wilson intervals, synthetic speech",
                  [(LABEL[a], S[a]["false_approval"]["k"], S[a]["false_approval"]["n"], S[a]["false_approval"]["lo"],
                    S[a]["false_approval"]["hi"], a == "pointe") for a in order if S[a]["false_approval"]["n"]]),
        "chart2": ("Action accuracy, with 95% Wilson intervals, synthetic speech",
                   [(LABEL[a], S[a]["accuracy"]["k"], S[a]["accuracy"]["n"], S[a]["accuracy"]["lo"], S[a]["accuracy"]["hi"],
                     a == "pointe") for a in order]),
        "paired": [],
        "glance": {"pointe": f"accuracy {P['accuracy']['k']}/{P['accuracy']['n']}; false approval "
                             f"{P['false_approval']['k']}/{P['false_approval']['n']}",
                   "llm-router": f"{R['accuracy']['k']}/{R['accuracy']['n']}; {R['false_approval']['k']}/{R['false_approval']['n']}",
                   "keyboard": f"accuracy {S['keyboard']['accuracy']['k']}/{S['keyboard']['accuracy']['n']}"},
        "pointe_commit": m["pointe_commit"][0][:7],
    }


def routing(s: dict, run: dict) -> dict:
    S = s["summary"]
    order = ["pointe", "llm-router", "naive", "keyboard-canonical", "null"]

    def c(a, key, wil):
        k, n = S[a][key], S[a]["turns"]
        return prop(k, n, *S[a][wil])

    rows = [[LABEL[a], c(a, "correct", "correct_wilson"), c(a, "wrong_session", "wrong_wilson"),
             f"{S[a]['ask_ambiguous'][0]}/{S[a]['ask_ambiguous'][1]} vs {S[a]['ask_clear'][0]}/{S[a]['ask_clear'][1]}",
             f"{S[a]['conversation_success'][0]}/{S[a]['conversation_success'][1]}" if S[a]["conversation_success"][1] else "n/a"]
            for a in order]
    d = S["_delta_pointe_minus_router"]
    sr = S["pointe"]["send_replaced"]
    P = S["pointe"]
    return {
        "unit": "conversation", "n": f"{P['conversations']} conversations of 5 turns ({P['turns']} turns)",
        "setup": [f"Run {', '.join(s['runs'])}, {run['started'][:10]}",
                  f"Agent {run['agent_model']} in Claude Code {run['claude_code_version'].split()[0]}, {run['permission_mode']}",
                  f"Pointe {run['pointe_commit'][:7]}: brain {run['pointe_setup']['brain']}, ears {run['pointe_setup']['ears']}, "
                  f"mouth {run['pointe_setup']['mouth']}",
                  f"LLM router {run['router_model']} at effort {run['router_effort']}; ears {run['ears_model']}"],
        "table": (["arm", "routed right", "wrong session", "asked first: ambiguous vs clear turns", "conversations all right"], rows),
        "table_title": "Routing per turn (synthetic speech, 95% Wilson intervals)",
        "findings": [
            f"Pointe minus LLM router, paired by turn: {delta(d['delta'], *d['bootstrap'])} (bootstrap by conversation).",
            f"No send delivered an earlier request's text ({sr['failed_turns']} of Pointe's {P['turns'] - P['correct']} failed "
            "turns; the earlier run lost 9 turns that way). Pointe's remaining failures are ambiguous turns where it "
            f"guessed instead of asking: it asked first on {P['ask_ambiguous'][0]} of {P['ask_ambiguous'][1]}.",
            f"Flip rate on 3 repeated conversations: Pointe {P['flip'][0]}/{P['flip'][1]}, LLM router "
            f"{S['llm-router']['flip'][0]}/{S['llm-router']['flip'][1]} (not like for like: the router reuses cached "
            "transcripts)."],
        "chart": ("Turns routed to the right session, with 95% Wilson intervals, synthetic speech",
                  [(LABEL[a], S[a]["correct"], S[a]["turns"], *S[a]["correct_wilson"], a == "pointe") for a in order]),
        "paired": [("Routing, turns right", d["delta"], *d["bootstrap"])],
        "glance": {"pointe": f"{P['correct']}/{P['turns']} turns", "llm-router": f"{S['llm-router']['correct']}/{S['llm-router']['turns']}",
                   "keyboard": f"{S['keyboard-canonical']['correct']}/{S['keyboard-canonical']['turns']}"},
        "pointe_commit": run["pointe_commit"][:7],
    }


def bargein(s: dict) -> dict:
    A, B = s["part_a"], s["part_b"]
    order = ["pointe", "llm-router", "naive", "keyboard", "null"]

    def c(v):
        return prop(v["k"], v["n"], *v["ci95"])

    def t(v):
        if not v or v["median"] is None:
            return "n/a" if not v else f"none of {v['n']} ({v['censored']} censored)"
        return f"{v['median']:.1f} s / {v['p90']:.1f} s ({v['censored']} censored)"

    rows_a = [[LABEL[a], c(A[a]["halt"]), c(A[a]["false_stop_backchannel"]), f"{A[a]['undo']['k']}/{A[a]['undo']['n']}"]
              for a in order]
    rows_b = [[LABEL[a], c(B[a]["correct"]), t(B[a]["ttca"]), f"{B[a]['within_10s']['k']}/{B[a]['within_10s']['n']}"]
              for a in order if a in B]
    pa, pb = s["paired"]["a"], s["paired"]["b"]
    lg = s["logs"]
    le = s["label_errors"]["branch"]
    return {
        "unit": "item", "n": f"Part A: {A['pointe']['halt']['n']} stop, undo or redirect items and "
                             f"{A['pointe']['false_stop_backchannel']['n']} backchannels; Part B: {s['part_b_items']} status questions",
        "setup": [f"Run {', '.join(s['run_ids'])}, {s['dates'].split(' to ')[0]}",
                  f"Agent {s['agent_model']} in Claude Code {s['claude_code']}, acceptEdits, one worker",
                  f"Pointe {s['pointe_commit'][:7]}: {lg['pointe_roles'].split(', notes')[0]}",
                  "LLM router: the same brain model as Pointe, Soniox ears"],
        "table": (["arm", "halted when told to stop", "false stop on a backchannel", "undo"], rows_a),
        "table_title": "Part A: stop, undo and redirect a running job (synthetic speech, 95% Wilson intervals)",
        "table2": (["arm", "correct answer within 45 s", "time to the correct answer, median / p90", "correct within 10 s"], rows_b),
        "table2_title": "Part B: status questions (synthetic speech). The keyboard row times correct text on the terminal, "
                        "a different quantity.",
        "findings": [
            f"Part A, Pointe minus LLM router paired by item: {delta(pa['delta'], *pa['ci95'])}. A spoken stop now ends a "
            f"Claude Code turn through its hooks ({lg.get('pointe_a_stop_taken', 0)} of {lg['pointe_a_runs']} logs show the "
            "stop taken), at the next tool step: Claude Code offers another process no supported way to cut a running "
            "turn, so the job, one shell command, runs to its end first.",
            f"Part B, Pointe minus LLM router: {delta(pb['delta'], *pb['ci95'])}.",
            f"Redirect was 0/{A['keyboard']['redirect']['n']} in every arm, the keyboard included: the column does not "
            "separate the arms.",
            f"{len(le['items'])} branch questions ({le['runs']} runs) are not scored because of a label error.",
            "The reference arms speak through local Kokoro; Pointe through ElevenLabs over the network. The Part B "
            "times include that difference."],
        "chart": ("Part A: running job halted when told to stop, with 95% Wilson intervals, synthetic speech",
                  [(LABEL[a], A[a]["halt"]["k"], A[a]["halt"]["n"], *A[a]["halt"]["ci95"], a == "pointe") for a in order]),
        "chart2": ("Part B: correct spoken answer within 45 s, with 95% Wilson intervals, synthetic speech",
                   [(LABEL[a], B[a]["correct"]["k"], B[a]["correct"]["n"], *B[a]["correct"]["ci95"], a == "pointe")
                    for a in order if a in B]),
        "paired": [("Barge-in A, job halted", pa["delta"], *pa["ci95"]),
                   ("Barge-in B, answered", pb["delta"], *pb["ci95"])],
        "glance": {"pointe": f"halted {A['pointe']['halt']['k']}/{A['pointe']['halt']['n']}; "
                             f"answered {B['pointe']['correct']['k']}/{B['pointe']['correct']['n']}",
                   "llm-router": f"{A['llm-router']['halt']['k']}/{A['llm-router']['halt']['n']}; "
                                 f"{B['llm-router']['correct']['k']}/{B['llm-router']['correct']['n']}",
                   "keyboard": f"{A['keyboard']['halt']['k']}/{A['keyboard']['halt']['n']}; "
                               f"{B['keyboard']['correct']['k']}/{B['keyboard']['correct']['n']}"},
        "pointe_commit": s["pointe_commit"][:7],
    }


def build_all() -> dict:
    d = load()
    out = {"hlk": hlk(d["hlk"]), "identifiers": identifiers(d["identifiers"]), "actions": actions(d["actions"]),
           "routing": routing(d["routing"], d["routing_run"]), "bargein": bargein(d["bargein"])}
    rows = before_after(d)
    out["_before_after"] = rows
    for k in ORDER:
        out[k]["before_after"] = [r for r in rows if r[0] == NAME[k]]
    money = spend()
    for k in ORDER:
        out[k]["spend"] = money[k]
        out[k]["limits"] = limits(k)
    return out


def limits(key: str) -> str:
    """The Limits section of the benchmark's README, verbatim: the authors' and the verification pass's own words."""
    text = (HERE / README[key]).read_text()
    if key == "hlk":
        return ""  # HLK's limits are part of its generated page, docs/benchmarks/hlk.md
    m = re.search(r"^## Limits[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit(f"{README[key]} has no Limits section")
    if key == "bargein":  # its README defers to the limits its report writes from the rows
        rows = json.loads((HERE / "bargein" / "results" / RUNS["bargein"] / "results.json").read_text())["limits"]
        return m.group(1).strip() + "\n\nThe published run:\n\n" + "\n".join(f"- {x}" for x in rows)
    return m.group(1).strip()


# ---------- Markdown ----------

def md_table(head, rows) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(out)


def run_lines(key: str) -> str:
    r = f"uv run --locked --extra local python bench/conversational/{key}/run.py"
    check = (f"{r} verify          # offline checks, $0, no keys" if key != "bargein" else
             "uv run --locked pytest -q tests/test_conversational_bargein.py   # offline checks, $0, no keys")
    report = f"{r} report" if key == "hlk" else f"{r} report <run-id>"
    return (f"{r} corpus          # render the synthetic speech, $0\n{check}\n"
            f"{r} {key} --adapter yours --smoke\n"
            f"{r} {key} --adapter yours --budget-usd {CAP[key]}\n{report}")


HEADER = "<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->\n\n"


def doc_page(key: str, b: dict) -> str:
    out = [f"# {NAME[key]}", "", f"*{QUESTION[key]}*", "",
           "Part of the [Pointe Conversational Engineering Benchmarks](README.md): a self-evaluation with an adapter interface, on "
           "synthetic speech. Every reference arm was written by Pointe's team. Every number on this page is computed "
           "from the committed results; the Limits section is the benchmark's own README.", "",
           "## Setup", "", f"- Independent unit: {b['unit']}. Sample: {b['n']}."]
    out += [f"- {x}." for x in b["setup"]]
    out += ["", f"## Results", "", f"{b['table_title']}.", "", md_table(*b["table"]), ""]
    if "table2" in b:
        out += [f"{b['table2_title']}", "", md_table(*b["table2"]), ""]
    out += [f"- {x}" for x in b["findings"]]
    out += [f"- Before the fixes, in the run of {EARLIER_DATE} (Pointe {EARLIER[key][1]}, kept as published in "
            f"[earlier/{EARLIER_DATE}/{key}.md](earlier/{EARLIER_DATE}/{key}.md)): "
            + "; ".join(f"{m} {b0}, now {b1}" for _, m, b0, b1 in b["before_after"]) + "."]
    out += ["", f"Full results: [{FULL[key].split('/')[-1]}](../../{FULL[key]}). Raw rows, events and spend: "
                f"`bench/conversational/{key}/results/`. Spend on this benchmark, every launch included: ${b['spend']:.2f} "
                f"of a ${CAP[key]} cap, computed from usage and list prices, not a vendor bill.", "",
            "## Limits", "", b["limits"], "",
            "## Run it on your harness", "",
            f"The benchmark carries its own harness in `bench/conversational/{key}/`. Write an adapter in "
            f"`bench/conversational/{key}/adapters/`, register it in `{REGISTER[key]}`, and run:", "", "```",
            run_lines(key), "```", "",
            "Every arm starts the same agent with the same launch line in its own throwaway repository under `/tmp`; an "
            "adapter only decides how the words reach it. Details: "
            f"[the benchmark's README](../../bench/conversational/{README[key]}) and "
            f"[its harness README](../../bench/conversational/{key}/README.md).", ""]
    return HEADER + "\n".join(out)


def index_doc(B: dict) -> str:
    total = sum(B[k]["spend"] for k in ORDER)
    rows = [[f"[{NAME[k]}]({k}.md)", QUESTION[k], B[k]["unit"], B[k]["glance"]["pointe"], B[k]["glance"]["llm-router"],
             B[k]["glance"]["keyboard"]] for k in ORDER]
    paired = [[label, B[k]["unit"], delta(d, lo, hi)] for k in ORDER for (label, d, lo, hi) in B[k]["paired"]]
    out = ["# Pointe Conversational Engineering Benchmarks", "",
           "Five benchmarks of conversational engineering, measuring what a voice layer costs a coding agent. The agent "
           "is held fixed (claude-haiku-5-5 in Claude Code), and the same tasks reach it typed or spoken, so a score is "
           "the loss the voice interface adds, not the strength of the agent. Pointe is the system under test.", "",
           "This is a reproducible self-evaluation with an adapter interface, not a leaderboard:", "",
           "- **Synthetic speech.** Four clean Kokoro voices, also Pointe's local voice: an upper bound for every arm.",
           "- **Every reference arm is ours.** The LLM router, the keyword rules and the keyboard arms were written by "
           "Pointe's team, who know Pointe's internals. No outside product is tested.",
           "- **Small samples.** Intervals are wide. Where they overlap, no ranking is claimed.",
           "- **Every number regenerates** from raw rows committed in `bench/conversational/<benchmark>/results/`.", "",
           "Humanity's Last Keystroke is named after Humanity's Last Exam (CAIS and Scale AI, arXiv 2501.14249) and is not "
           "affiliated with it.", "",
           "## At a glance (synthetic speech)", "", md_table(["benchmark", "question", "unit", "Pointe", "LLM router",
                                                              "keyboard reference"], rows), "",
           "## Before and after the fixes (Pointe arm, synthetic speech)", "",
           f"The run of {EARLIER_DATE} found five defects in Pointe: a send that delivered an earlier request after "
           "\"which session?\", no way to stop a running turn, permission requests only a tap could approve, misheard "
           "words rewritten into code names, and slow spoken answers. Pointe "
           f"{B['routing']['pointe_commit']} fixes them, and the Pointe arm of every benchmark was run again with the same "
           "agent model, items, seeds and settings. The reference arms run no Pointe code and keep their rows from the "
           f"earlier run. That run's pages are kept as published: [earlier/{EARLIER_DATE}/](earlier/{EARLIER_DATE}/README.md).",
           "", md_table(["benchmark", "measure", f"before ({EARLIER_DATE})", "after"], B["_before_after"]), "",
           "## Pointe minus the LLM router, paired (synthetic speech)", "",
           "The LLM router is the baseline: the same recognizer as Pointe's default setup and one call per utterance to "
           "the same brain model. Differences in percentage points with 95% bootstrap intervals over each benchmark's "
           "independent unit. Spoken Actions has no paired difference: its false-approval counts are too small and "
           "unstable to rank.", "", md_table(["measure", "bootstrap unit", "Pointe minus LLM router"], paired), "",
           "## Run them on your harness", "",
           "Each benchmark keeps its own harness (runner, adapters, speech corpus, scorer) in "
           "`bench/conversational/<benchmark>/`, frozen with the run that produced its results. To measure your own "
           "conversational harness:", "",
           "1. `uv sync --locked --extra local`, then render the speech (`run.py corpus`) and run the offline checks: "
           "free, no keys. Each benchmark's page has its exact commands.",
           "2. Write an adapter: it receives the same audio (or text) at real-time pace and reports what it delivered, "
           "approved or said. Each benchmark's page names the file to register it in.",
           "3. Run `--smoke` first, then the full run with `--budget-usd`; the runner checks the spend ledger before every "
           "launch. Keys come from the macOS Keychain or the environment, into the one process that needs them.",
           "4. `run.py report <run-id>` writes the tables. Send the rows and the adapter as a pull request.", "",
           "## Spend", "",
           md_table(["benchmark", "spend, every launch", "cap"], [[NAME[k], f"${B[k]['spend']:.2f}", f"${CAP[k]}"] for k in ORDER]
                    + [["all five", f"${total:.2f}", f"${sum(CAP.values())}"]]), "",
           "Computed from usage and list prices, not metered: smoke, debug, aborted runs and verification reruns are "
           "included.", "",
           "The speech-component benchmarks (recognizers, voices, brains) are a separate page: "
           "[docs/benchmarks.md](../benchmarks.md).", ""]
    return HEADER + "\n".join(out)


# ---------- HTML ----------

def e(x) -> str:
    return html.escape(str(x), quote=True)


def dot_chart(cid: str, title: str, rows: list, fixed_n: bool = False) -> str:
    """Arms down the side, a rate from 0 to 100% across, a dot and its 95% interval; Pointe in the accent colour."""
    lw, pw, rw, rh, top = 164, 300, 126, 30, 26
    w, h = lw + pw + rw, top + rh * len(rows) + 12
    x = lambda v: lw + v * pw
    out = [f'<figure class="bm-fig"><svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="{cid}-t {cid}-d" class="bm-svg" style="max-width:{w}px">',
           f'<title id="{cid}-t">{e(title)}</title>',
           f'<desc id="{cid}-d">' + e("; ".join(f"{r[0]}: {r[1]} of {r[2]}" for r in rows)) + "</desc>"]
    for t in (0, .25, .5, .75, 1):
        out.append(f'<line class="bm-grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{h - 8}"/>'
                   f'<text class="bm-tick" x="{x(t):.1f}" y="{top - 12}" text-anchor="middle">{int(t * 100)}%</text>')
    for i, (label, k, n, lo, hi, me) in enumerate(rows):
        y = top + rh * i + rh / 2
        cls = "bm-me" if me else "bm-other"
        r = k / n if n else 0
        tip = f"{label}: {k} of {n}, {100 * r:.0f}%" + (f", 95% interval {100 * lo:.0f} to {100 * hi:.0f}%" if lo is not None else "")
        out.append(f'<g class="{cls}"><title>{e(tip)}</title>'
                   f'<text class="bm-label" x="{lw - 12}" y="{y + 4:.1f}" text-anchor="end">{e(label)}</text>')
        if lo is not None:
            out.append(f'<line class="bm-ci" x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<circle class="bm-dot" cx="{x(r):.1f}" cy="{y:.1f}" r="5.5"/>'
                   f'<text class="bm-val" x="{lw + pw + 14}" y="{y + 4:.1f}">{k}/{n} = {100 * r:.0f}%</text>'
                   f'<rect class="bm-hit" x="0" y="{y - rh / 2:.1f}" width="{w}" height="{rh}"/></g>')
    out.append(f'</svg><figcaption class="pg-small">{e(title)}. Dots are rates; lines are 95% Wilson intervals where '
               'the rows are independent. Pointe is in orange.</figcaption></figure>')
    return "".join(out)


def forest(B: dict) -> str:
    rows = [r for k in ORDER for r in B[k]["paired"]]
    lw, pw, rw, rh, top = 196, 280, 144, 34, 30
    lo_d, hi_d = -1.0, 0.5
    w, h = lw + pw + rw, top + rh * len(rows) + 30
    x = lambda v: lw + (v - lo_d) / (hi_d - lo_d) * pw
    out = ['<figure class="bm-fig"><svg viewBox="0 0 %d %d" role="img" aria-labelledby="fp-t fp-d" class="bm-svg" style="max-width:%dpx">' % (w, h, w),
           '<title id="fp-t">Pointe minus the LLM router, percentage points, with 95% bootstrap intervals</title>',
           '<desc id="fp-d">' + e("; ".join(f"{r[0]}: {delta(*r[1:])}" for r in rows)) + "</desc>"]
    for t in (-1, -.75, -.5, -.25, 0, .25, .5):
        out.append(f'<line class="{"bm-zero" if t == 0 else "bm-grid"}" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" '
                   f'y2="{h - 22}"/><text class="bm-tick" x="{x(t):.1f}" y="{top - 12}" text-anchor="middle">{"0" if t == 0 else f"{int(t * 100):+d}"}</text>')
    for i, (label, d, lo, hi) in enumerate(rows):
        y = top + rh * i + rh / 2
        out.append(f'<g class="bm-me"><title>{e(label)}: {e(delta(d, lo, hi))}</title>'
                   f'<text class="bm-label" x="{lw - 12}" y="{y + 4:.1f}" text-anchor="end">{e(label)}</text>'
                   f'<line class="bm-ci" x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<circle class="bm-dot" cx="{x(d):.1f}" cy="{y:.1f}" r="5.5"/>'
                   f'<text class="bm-val" x="{lw + pw + 14}" y="{y + 4:.1f}">{100 * d:+.0f} ({100 * lo:+.0f} to {100 * hi:+.0f})</text>'
                   f'<rect class="bm-hit" x="0" y="{y - rh / 2:.1f}" width="{w}" height="{rh}"/></g>')
    out.append(f'<text class="bm-tick" x="{x(-.5):.1f}" y="{h - 6}" text-anchor="middle">Pointe lower</text>'
               f'<text class="bm-tick" x="{x(.25):.1f}" y="{h - 6}" text-anchor="middle">Pointe higher</text>')
    out.append('</svg><figcaption class="pg-small">Each row is one benchmark\'s headline measure, paired over its '
               'independent unit. An interval that crosses zero shows no measurable difference.</figcaption></figure>')
    return "".join(out)


def families_chart(s: dict) -> str:
    """HLK passes per family out of 6 runs: keyboard (square), LLM router (diamond), Pointe (orange circle)."""
    arms = [("keyboard-canonical", "keyboard, canonical"), ("llm-router", "LLM router"), ("pointe", "Pointe")]
    lw, pw, rw, rh, top = 172, 330, 24, 36, 46
    fams = s["families"]
    w, h = lw + pw + rw, top + rh * len(fams) + 8
    x = lambda v: lw + v / 6 * pw
    leg = ('<g class="bm-legend" transform="translate(%d,10)">'
           '<rect class="bm-kb" x="0" y="-5" width="10" height="10"/><text class="bm-tick" x="16" y="4">keyboard, canonical</text>'
           '<path class="bm-rt" d="M186 -6 L192 0 L186 6 L180 0 Z"/><text class="bm-tick" x="198" y="4">LLM router</text>'
           '<circle class="bm-dot bm-me-fill" cx="306" cy="0" r="5.5"/><text class="bm-tick" x="318" y="4">Pointe</text></g>') % (lw - 150)
    out = [f'<figure class="bm-fig"><svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="hf-t hf-d" class="bm-svg" style="max-width:{w}px">',
           '<title id="hf-t">HLK passes per task family out of 6 runs, synthetic speech</title>',
           '<desc id="hf-d">' + e("; ".join(f"{f}: " + ", ".join(f"{lab} {s['per_family'][a][f][0]}" for a, lab in arms)
                                          for f in fams)) + "</desc>", leg]
    for t in range(7):
        out.append(f'<line class="bm-grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 8}" y2="{h - 6}"/>'
                   f'<text class="bm-tick" x="{x(t):.1f}" y="{top - 14}" text-anchor="middle">{t}</text>')
    for i, f in enumerate(fams):
        y = top + rh * i + rh / 2
        vals = {a: s["per_family"][a][f][0] for a, _ in arms}
        tip = f"{f}: " + ", ".join(f"{lab} {vals[a]} of 6" for a, lab in arms)
        out.append(f'<g><title>{e(tip)}</title><text class="bm-label" x="{lw - 12}" y="{y + 4:.1f}" text-anchor="end">{e(f)}</text>'
                   f'<line class="bm-ci bm-span" x1="{x(min(vals.values())):.1f}" x2="{x(max(vals.values())):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<rect class="bm-kb" x="{x(vals["keyboard-canonical"]) - 4.5:.1f}" y="{y - 14.5:.1f}" width="9" height="9"/>'
                   f'<path class="bm-rt" d="M{x(vals["llm-router"]):.1f} {y - 5.5:.1f} l5.5 5.5 l-5.5 5.5 l-5.5 -5.5 Z"/>'
                   f'<circle class="bm-dot bm-me-fill" cx="{x(vals["pointe"]):.1f}" cy="{y + 10:.1f}" r="5"/>'
                   f'<rect class="bm-hit" x="0" y="{y - rh / 2:.1f}" width="{w}" height="{rh}"/></g>')
    out.append('</svg><figcaption class="pg-small">Passes per family out of 6 runs (3 tasks, two runs each). The three marks '
               'sit in three lanes, keyboard on top and Pointe at the bottom, so equal values stay visible.</figcaption></figure>')
    return "".join(out)


def h_table(head, rows, caption, num: bool = True) -> str:
    return ('<p class="pg-small bm-cap">' + e(caption) + '</p><div class="bm-scroll"><table class="bm-table'
            + (' bm-num' if num else '') + '" aria-label="' + e(caption) + '"><thead><tr>'
            + "".join(f'<th scope="col">{e(c)}</th>' for c in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join((f'<th scope="row">{e(c)}</th>' if i == 0 else f"<td>{e(c)}</td>")
                                       for i, c in enumerate(r)) + "</tr>" for r in rows) + "</tbody></table></div>")


CSS = """
  .bm-scroll { overflow-x: auto; margin: 8px 0 8px; }
  .bm-table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  .bm-cap { margin-top: 18px; max-width: 80ch; }
  .bm-table th, .bm-table td { text-align: left; vertical-align: top; padding: 10px 16px 10px 0; border-bottom: 1px solid var(--line); color: var(--body); }
  .bm-table thead th { color: var(--text); font-weight: 500; border-bottom: 1px solid var(--line-strong); }
  .bm-table tbody th { color: var(--text); font-weight: 500; white-space: nowrap; }
  .bm-num td { white-space: nowrap; }
  .bm-fig { margin: 24px 0 8px; }
  .bm-svg { display: block; width: 100%; max-width: 860px; height: auto; font-family: var(--font-sans); }
  .bm-svg text { fill: var(--body); font-size: 13px; }
  .bm-svg .bm-tick { fill: var(--dim); font-size: 12px; }
  .bm-svg .bm-label { fill: var(--text); }
  .bm-svg .bm-val { font-variant-numeric: tabular-nums; }
  .bm-grid { stroke: var(--line); stroke-width: 1; }
  .bm-zero { stroke: var(--line-strong); stroke-width: 1.5; }
  .bm-ci { stroke-width: 2; stroke-linecap: round; }
  .bm-other .bm-ci { stroke: var(--dim); } .bm-other .bm-dot { fill: var(--dim); }
  .bm-me .bm-ci { stroke: var(--accent); } .bm-me .bm-dot, .bm-me-fill { fill: var(--accent); }
  .bm-dot { stroke: var(--bg); stroke-width: 2; }
  .bm-span { stroke: var(--line-strong); }
  .bm-kb { fill: none; stroke: var(--text); stroke-width: 1.5; }
  .bm-rt { fill: var(--dim); stroke: var(--bg); stroke-width: 1; }
  .bm-hit { fill: transparent; }
  g:hover > .bm-hit { fill: var(--line-faint); }
  .bm-findings { margin-top: 16px; display: grid; gap: 8px; max-width: 80ch; }
  .bm-findings li { padding-left: 16px; position: relative; color: var(--body); }
  .bm-findings li::before { content: ""; position: absolute; left: 0; top: 10px; width: 6px; height: 6px; border-radius: 50%; background: var(--line-strong); }
  .bm-meta { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 4px 18px; }
  .bm-links { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 6px 24px; font-weight: 500; }
  .bm-q { margin-top: 10px; max-width: 70ch; font-size: 18px; line-height: 28px; color: var(--body); }
  @media (max-width: 640px) { .bm-table { min-width: 600px; } .bm-table tbody th { white-space: normal; }
    .bm-table th, .bm-table td { padding-right: 12px; }
    .bm-svg text { font-size: 16px; } .bm-svg .bm-tick { font-size: 15px; } }
"""


def section(key: str, b: dict) -> str:
    out = [f'<section class="pg-section" id="{key}" aria-labelledby="h-{key}">',
           f'<p class="pg-kicker">Unit: {e(b["unit"])}</p><h2 class="pg-h2" id="h-{key}">{e(NAME[key])}</h2>',
           f'<p class="bm-q">{e(QUESTION[key])}</p>',
           '<p class="bm-meta pg-small">' + "".join(f"<span>{e(x)}</span>" for x in [b["n"]] + b["setup"]) + "</p>"]
    if key == "hlk":
        out.append(families_chart(b["families"]))
    out.append(dot_chart(f"c-{key}", b["chart"][0], b["chart"][1]))
    if "chart2" in b:
        out.append(dot_chart(f"c2-{key}", b["chart2"][0], b["chart2"][1]))
    out.append('<ul class="bm-findings">' + "".join(f"<li>{e(x)}</li>" for x in b["findings"]) + "</ul>")
    out.append(h_table(*b["table"], b["table_title"]))
    if "table2" in b:
        out.append(h_table(*b["table2"], b["table2_title"]))
    links = [f'<a href="{GITHUB}docs/benchmarks/{key}.md">Method, limits and how to run it</a>']
    if key in SITE_DETAIL:
        links.append(f'<a href="{SITE_DETAIL[key]}">Full results page</a>')
    links.append(f'<a href="{GITHUB}{FULL[key]}">Full results</a>')
    links.append(f'<a href="https://github.com/ballerine-io/pointe/tree/main/bench/conversational/{key}/results">Raw rows</a>')
    out.append('<p class="bm-links">' + "".join(links) + "</p></section>")
    return "".join(out)


def site_page(B: dict, version: str) -> str:
    total = sum(B[k]["spend"] for k in ORDER)
    glance = [[NAME[k], QUESTION[k], B[k]["glance"]["pointe"], B[k]["glance"]["llm-router"], B[k]["glance"]["keyboard"]]
              for k in ORDER]
    reg = [[NAME[k], f"bench/conversational/{k}/", REGISTER[k]] for k in ORDER]
    money = [[NAME[k], f"${B[k]['spend']:.2f}", f"${CAP[k]}"] for k in ORDER] + [["All five", f"${total:.2f}", f"${sum(CAP.values())}"]]
    body = f"""
  <section class="pg-hero">
    <p class="pg-kicker">Benchmarks</p>
    <h1 class="pg-h1">Pointe Conversational Engineering Benchmarks</h1>
    <p class="pg-lead">Five benchmarks of conversational engineering, measuring what a voice layer costs a coding agent.
      The agent is held fixed, and the same tasks reach it typed or spoken, so a score is the loss the voice interface
      adds, not the strength of the agent. Pointe is the system under test. The flagship is Humanity's Last Keystroke:
      small coding tasks, finished by voice only.</p>
    <p class="pg-small">First run 2026-11-23. Agent claude-haiku-5-5 in Claude Code 2.1.330. Synthetic speech in four
      Kokoro voices. Every number on this page is computed from raw rows committed in the repository.</p>
  </section>
  <ul class="pg-how" aria-label="How to read these results">
    <li><b>A self-evaluation.</b> Not a leaderboard. One system under test and reference arms written by Pointe's team,
      who know Pointe's internals. No outside product is tested.</li>
    <li><b>Synthetic speech.</b> Clean Kokoro voices, also Pointe's local voice. Results are an upper bound for every
      arm.</li>
    <li><b>Small samples.</b> Intervals are wide. Where they overlap, no ranking is claimed.</li>
    <li><b>Reproducible.</b> Each benchmark is frozen with its harness, items, audio hashes and the Pointe commit it
      measured.</li>
  </ul>
  <section class="pg-section" id="glance" aria-labelledby="h-glance">
    <div class="pg-section-head"><h2 class="pg-h2" id="h-glance">At a glance</h2></div>
    {h_table(["Benchmark", "Question", "Pointe", "LLM router", "Keyboard reference"], glance,
             "Headline counts per benchmark, synthetic speech. The LLM router is the baseline: the same recognizer and "
             "brain model as Pointe's default setup, one call per utterance.", num=False)}
  </section>
  <section class="pg-section" id="fixes" aria-labelledby="h-fixes">
    <div class="pg-section-head"><h2 class="pg-h2" id="h-fixes">Before and after the fixes</h2></div>
    <p class="pg-body" style="max-width:72ch">The first run, {EARLIER_DATE}, found five defects in Pointe. Pointe
      {B['routing']['pointe_commit']} fixes them, and the Pointe arm of every benchmark was run again with the same agent,
      items, seeds and settings; the reference arms run no Pointe code and keep their earlier rows. The earlier pages are
      kept <a href="{GITHUB}docs/benchmarks/earlier/{EARLIER_DATE}/README.md">as published</a>.</p>
    {h_table(["Benchmark", "Measure", f"Before ({EARLIER_DATE})", "After"], B["_before_after"],
             "Pointe arm only, synthetic speech, 95% Wilson intervals.", num=False)}
  </section>
  <section class="pg-section" id="paired" aria-labelledby="h-paired">
    <div class="pg-section-head"><h2 class="pg-h2" id="h-paired">Pointe against the LLM router</h2></div>
    <p class="pg-body" style="max-width:72ch">In this first run Pointe scored below the LLM router wherever an interval
      excludes zero. The findings under each benchmark say what drove the gap, including the parts that are bugs in
      Pointe and the parts that are biases of the benchmark. Spoken Actions has no paired row: its false-approval counts
      are too small and unstable to rank.</p>
    {forest(B)}
  </section>
  {"".join(section(k, B[k]) for k in ORDER)}
  <section class="pg-section" id="run" aria-labelledby="h-run">
    <div class="pg-section-head"><h2 class="pg-h2" id="h-run">Run it on your harness</h2>
      <p class="pg-body">Any conversational harness that can take audio or text and drive a coding agent can be measured.</p></div>
    <ol class="pg-steps">
      <li><div><b>Get the repository and check it, free.</b> No keys, no spend.
        <pre class="pg-term"><code>git clone https://github.com/ballerine-io/pointe.git &amp;&amp; cd pointe
uv sync --locked --extra local
uv run --locked --extra local python bench/conversational/hlk/run.py corpus
uv run --locked --extra local python bench/conversational/hlk/run.py verify</code></pre></div></li>
      <li><div><b>Write an adapter.</b> It receives the same audio at real-time pace (or the same text) and reports what it
        delivered, approved, stopped or said. The agent is started for you with the same launch line as every other arm,
        in a throwaway repository under /tmp. An item that needs something your harness lacks is shown as coverage, never
        as a failure.
        {h_table(["Benchmark", "Its harness", "Register the adapter in"], reg, "Each benchmark keeps the harness it was run with.", num=False)}</div></li>
      <li><div><b>Smoke, then the full run.</b> The runner checks a spend ledger before every launch and stops at the
        budget. Keys come from the macOS Keychain or the environment, into the one process that needs them.
        <pre class="pg-term"><code>uv run --locked --extra local python bench/conversational/hlk/run.py hlk --adapter yours --smoke
uv run --locked --extra local python bench/conversational/hlk/run.py hlk --adapter yours --budget-usd 55</code></pre></div></li>
      <li><div><b>Report and share.</b> <code>run.py report</code> recomputes every table from the rows. Send the rows and
        the adapter as a pull request; a better LLM router prompt is welcome too.</div></li>
    </ol>
  </section>
  <section class="pg-section" id="spend" aria-labelledby="h-spend">
    <div class="pg-section-head"><h2 class="pg-h2" id="h-spend">Spend</h2></div>
    {h_table(["Benchmark", "Spend, every launch", "Cap"], money,
             "Computed from usage and list prices, not metered. Smoke runs, debugging, aborted runs and verification "
             "reruns are included.")}
    <p class="pg-small" style="margin-top:12px">Humanity's Last Keystroke is named after Humanity's Last Exam (CAIS and
      Scale AI, arXiv 2501.14249) and is not affiliated with it. Text and tasks CC BY 4.0, code MIT, speech Kokoro-82M
      (Apache-2.0). The speech-component benchmarks (recognizers, voices, brains) are on
      <a href="{GITHUB}docs/benchmarks.md">a separate page</a>.</p>
  </section>
"""
    return TEMPLATE.replace("{CSS}", CSS).replace("{BODY}", body).replace("{VERSION}", version)


TEMPLATE = """<!doctype html>
<!-- Written by bench/conversational/publish.py from the committed results. Do not edit by hand. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pointe Conversational Engineering Benchmarks</title>
<meta name="description" content="Five benchmarks of conversational engineering, measuring what a voice layer costs a coding agent, with Humanity's Last Keystroke: a pilot voice-only coding benchmark. Synthetic speech, small samples, every number computed from committed rows.">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0A0400" media="(prefers-color-scheme: dark)">
<meta property="og:title" content="Pointe Conversational Engineering Benchmarks">
<meta property="og:description" content="Conversational engineering: what a voice layer costs a coding agent, in five benchmarks on synthetic speech, with Humanity's Last Keystroke.">
<meta property="og:image" content="https://eng.ballerine.com/pointe/social.png">
<meta property="og:url" content="https://eng.ballerine.com/pointe/benchmarks/">
<meta name="twitter:card" content="summary_large_image">
<script>
  // The old address: Cloudflare Pages cannot redirect by host, so the page does it.
  if (location.hostname === 'pointe.ballerine.com') location.replace('https://eng.ballerine.com/pointe/benchmarks/' + location.hash);
</script>
<link rel="icon" href="../brand/favicon.svg" type="image/svg+xml">
<link rel="icon" href="../brand/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="../brand/apple-touch-icon.png">
<link rel="stylesheet" href="../style.css">
<link rel="stylesheet" href="../pages.css">
<style>{CSS}</style>
</head>
<body class="pg">
<a class="pg-skip" href="#main">Skip to content</a>
<header class="pg-wrap pg-header">
  <a class="pg-wordmark" href="../"><picture><source srcset="../brand/lockup-small-on-dark.svg" media="(prefers-color-scheme: dark)"><img src="../brand/lockup-small.svg" width="112" height="32" alt="Pointe"></picture></a>
  <nav aria-label="Pages">
    <a href="../features/">Features</a>
    <a href="../docs/">Docs</a>
    <a href="./" aria-current="page">Benchmarks</a>
    <a href="../roadmap/">Roadmap</a>
    <a href="../contribute/">Contribute</a>
    <a class="pg-gh" href="https://github.com/ballerine-io/pointe">GitHub</a>
  </nav>
</header>
<main id="main" class="pg-wrap">
{BODY}
</main>
<footer class="pg-footer">
  <div class="pg-wrap pg-footer-grid">
    <p class="pg-small">Built and open-sourced by <a href="../../">Ballerine Engineering</a>. MIT licensed. Pointe <span data-version>{VERSION}</span>.</p>
    <nav aria-label="Project links" class="pg-footer-links">
      <a href="../">Pointe</a>
      <a href="../docs/">Docs</a>
      <a href="hlk/">Humanity's Last Keystroke</a>
      <a href="actions/">Spoken Actions</a>
      <a href="https://github.com/ballerine-io/pointe/tree/main/bench/conversational">Source</a>
    </nav>
  </div>
</footer>
</body>
</html>
"""


def build() -> dict[Path, str]:
    B = build_all()
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    pages = {DOCS / "README.md": index_doc(B), PAGE: site_page(B, version)}
    for k in ORDER[1:]:
        pages[DOCS / f"{k}.md"] = doc_page(k, B[k])
    for path, text in pages.items():
        if re.search(r"\bleaderboard\b", text.replace("not a leaderboard", "").replace("Not a leaderboard", ""), re.I):
            raise SystemExit(f"{path.name} uses a word the pages must not use")
    return pages


def main() -> int:
    for path, text in build().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
