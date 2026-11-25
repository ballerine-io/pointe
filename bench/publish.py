"""The public benchmark pages, written from one release's results: site/pointe/benchmarks/index.html,
docs/benchmarks/README.md, and the downloads in site/pointe/benchmarks/<release>/. Every number comes from
bench/results/<release>/summary.json (bench/release_report.py) or HLK's own results/summary.json; nothing is typed in.

  .venv/bin/python -I bench/release_report.py bench/results/2026-11-25-v0.8.5
  .venv/bin/python -I bench/publish.py bench/results/2026-11-25-v0.8.5

tests/test_bench_publish.py fails when a page differs from what this writes."""

import gzip
import html
import io
import json
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "pointe" / "benchmarks"
DOCS = ROOT / "docs" / "benchmarks"
GH = "https://github.com/ballerine-io/pointe"
HLK_SUMMARY = ROOT / "bench" / "conversational" / "hlk" / "results" / "summary.json"
ARM = {"pointe": "Pointe 0.8.5", "llm-router": "Plain router", "keyboard-canonical": "Keyboard", "null": "Does nothing"}


# ---------- numbers ----------

def secs(v) -> str:
    if v is None:
        return "n/a"
    if v == "silent":
        return "a silent turn"
    return f"{v:.1f} s"


def pc(v) -> str:
    return "n/a" if v is None else f"{100 * v:.0f}%"


def many(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def kn(k: int, n: int, ci=None) -> str:
    out = f"{k} of {n}"
    if ci and ci[0] is not None:
        out += f" ({100 * ci[0]:.0f} to {100 * ci[1]:.0f}%)"
    return out


def ci_s(ci) -> str:
    return f"{secs(ci[0])} to {secs(ci[1])}" if ci else "n/a"


def ci_p(ci) -> str:
    return f"{pc(ci[0])} to {pc(ci[1])}" if ci else "n/a"


def spread(reps: list, key: str, fmt) -> str:
    vals = [r.get(key) for r in reps if r.get(key) is not None]
    if len(vals) < 2:
        return ""
    num = [v for v in vals if v != "silent"]
    lo = fmt(min(num)) if num else "n/a"
    hi = "a silent turn" if "silent" in vals else fmt(max(num))
    return f"runs: {lo} to {hi}"


def wilson(k: int, n: int):
    if not n:
        return None
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return ((c - h) / d, (c + h) / d)


def sign(d: dict, lower_better: bool = False, unit: str = "pts") -> str:
    """Pointe minus the router, with its interval and what it says."""
    if not d or d.get("ci95") is None or d["diff"] is None:
        return "n/a"
    lo, hi = d["ci95"]
    f = (lambda x: f"{x:+.1f} s") if unit == "s" else (lambda x: f"{100 * x:+.0f} points")
    if lo is None or hi is None or "silent" in (lo, hi):
        return f"{f(d['diff'])}"
    verdict = "no difference shown" if lo <= 0 <= hi else (
        ("Pointe better" if (hi < 0) == lower_better else "Pointe worse"))
    return f"{f(d['diff'])} ({f(lo)} to {f(hi)}): {verdict}"


# ---------- the page as blocks ----------

def blocks(S: dict, M: dict, H: dict | None) -> list:
    D, Hu, T = S.get("dialogues"), S.get("human"), S.get("turns")
    rel = S["release"]
    B = []
    B.append(("h1", f"Pointe {rel[1:]}, measured"))
    count = sum(1 for x in (D, H, Hu, T) if x)
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
    B.append(("lead", f"{words[count]} benchmarks of Pointe {rel[1:]} (commit {M['commit'][:8]}), run on {M['date']} against a plain "
                      "router we wrote as the baseline. Every number on this page is computed from raw rows in the "
                      "repository; the rows, the commands and the manifest are linked at the end."))
    B.append(("ul", [
        "**A self-evaluation.** Pointe's team wrote the benchmarks, the scripted users and the baseline. Nobody outside "
        "the team has run them yet.",
        "**Synthetic or recorded, per row.** Most speech is synthetic (Kokoro and OpenAI voices). Two benchmarks use "
        "recorded people: one-word yes and no answers (Speech Commands) and pauses in meetings (AMI).",
        "**n and spread on every number.** Each benchmark ran more than once; the tables give every run. Intervals "
        "are 95%. Where an interval crosses zero, no difference is claimed.",
        "**Model judges are named.** The only subjective score (naturalness) is two models' reading of transcripts, "
        "not people's ratings.",
    ] + ([f"**Measured on {rel[1:]}, not on {S['newer']}.** The current version was released after these runs; it was "
          "not measured, and its changes may move these numbers either way."] if S.get("newer") else [])))

    # headline
    rows = []
    if D:
        p, r = D["arms"]["pointe"], D["arms"]["llm-router"]
        pp, rp = p["pooled"], r["pooled"]
        rows.append(["First word after you stop speaking, median", f"{secs(pp['ttfw_median'])} (p90 {secs(pp['ttfw_p90'])})",
                     "not comparable (see Baseline)", "synthetic",
                     f"{pp['speech_turns']} turns, {many(len(p['repeats']), 'run')}; {spread(p['repeats'], 'ttfw_median', secs)}"])
        rows.append(["Turns that got no spoken reply", f"{pp['silent_turns']} of {pp['speech_turns']}",
                     f"{rp['silent_turns']} of {rp['speech_turns']}", "synthetic", many(len(p['repeats']), 'run')])
        rows.append(["Time to a useful answer, median", f"{secs(pp['ttua_median'])} ({ci_s(pp['ci95'].get('ttua_median'))})",
                     f"{secs(rp['ttua_median'])} ({ci_s(rp['ci95'].get('ttua_median'))})", "synthetic",
                     f"Pointe minus router: {sign(D['paired']['ttua_median'], lower_better=True, unit='s')}"])
        rows.append(["Right action", kn(*pp["right_action_k_n"], pp["ci95"].get("right_action")),
                     kn(*rp["right_action_k_n"], rp["ci95"].get("right_action")), "synthetic",
                     f"Pointe minus router: {sign(D['paired']['right_action'])}"])
        rows.append(["Sent to the wrong session / approved what it should not (a no, a hedge, or a yes before the "
                     "request was read in full)",
                     f"{sum(x['wrong_sends'] for x in p['repeats'])} / {sum(x['false_approvals'] for x in p['repeats'])}",
                     f"{sum(x['wrong_sends'] for x in r['repeats'])} / {sum(x['false_approvals'] for x in r['repeats'])}",
                     "synthetic", f"counts over {many(len(p['repeats']), 'run')}"])
    if H:
        pa, ra = H["passes"].get("pointe"), H["passes"].get("llm-router")
        kb = H["passes"].get("keyboard-canonical")
        g = H["gaps"].get("pointe minus llm-router")
        rows.append(["HLK: small coding task finished by voice only", kn(*pa, wilson(*pa)), kn(*ra, wilson(*ra)), "synthetic",
                     f"keyboard {kn(*kb)}; Pointe minus router {100 * g[0]:+.0f} points ({100 * g[1]:+.0f} to "
                     f"{100 * g[2]:+.0f}), paired by family" if g else ""])
    if Hu:
        hp, hr = Hu["arms"]["pointe"]["repeats"], Hu["arms"].get("llm-router", {}).get("repeats", [])

        def tot(reps, key):
            k = sum(x[key]["k"] for x in reps)
            n = sum(x[key]["n"] for x in reps)
            return kn(k, n, wilson(k, n)) if n else "n/a"
        rows.append(["Recorded \"yes\" after a read-out approves", tot(hp, "yes_approved"), tot(hr, "yes_approved"),
                     "recorded people", f"20 speakers, {len(hp)} runs"])
        rows.append(["Recorded \"no\" after a read-out denies", tot(hp, "no_denied"), tot(hr, "no_denied"),
                     "recorded people", f"20 speakers, {len(hp)} runs"])
    if T:
        t = T["runs"][T["headline"]]
        rows.append(["Turn taken in the middle of a real pause (Normal, 1.3 s)",
                     f"{pc(t['test']['rate'])} ({ci_p(t['test']['ci95_by_speaker'])})", "not measurable (see Baseline)",
                     "recorded people", f"{t['test']['pauses']} pauses, {t['test']['speakers']} speakers not used for tuning"])
    B.append(("h2", "Headline", "headline"))
    B.append(("table", ["Measure", "Pointe 0.8.5", "Plain router", "Speech", "n and spread"], rows,
              "Intervals are 95%: Wilson for counts, resampling dialogues (or families, or speakers) for the rest."))

    # where Pointe loses: computed
    loses, ties, wins = [], [], []
    if D:
        for key, name, lower in (("right_action", "right action", False), ("right_session", "right session", False),
                                 ("ttua_median", "time to a useful answer", True),
                                 ("ttua_session_answer_median", "time to a session's answer", True),
                                 ("words_over_need_median", "words beyond what was needed", True)):
            d = D["paired"].get(key)
            if not d or d.get("ci95") is None or "silent" in d["ci95"]:
                continue
            lo, hi = d["ci95"]
            (ties if lo <= 0 <= hi else wins if (hi < 0) == lower else loses).append(name)
    if H and H["gaps"].get("pointe minus llm-router"):
        g = H["gaps"]["pointe minus llm-router"]
        (ties if g[1] <= 0 <= g[2] else wins if g[1] > 0 else loses).append("HLK tasks finished")
    kbgap = H["gaps"].get("keyboard-canonical minus pointe") if H else None
    B.append(("h2", "Where Pointe loses, and what is not shown", "loses"))
    items = []
    if loses:
        items.append("**Pointe is worse than the plain router on:** " + ", ".join(loses) + ".")
    if ties:
        items.append("**No difference shown on:** " + ", ".join(ties) + " (the interval crosses zero).")
    if wins:
        items.append("**Pointe is better on:** " + ", ".join(wins) + ".")
    if kbgap and kbgap[1] > 0:
        items.append(f"**Typing still beats Pointe on HLK.** The same tasks typed finish {100 * kbgap[0]:.0f} points more "
                     f"often ({100 * kbgap[1]:+.1f} to {100 * kbgap[2]:+.0f}), paired by family: voice costs Pointe tasks.")
    if D:
        items.append(f"**The first word is slow.** A median of {secs(D['arms']['pointe']['pooled']['ttfw_median'])} and a "
                     f"p90 of {secs(D['arms']['pointe']['pooled']['ttfw_p90'])} after the user stops, against people's "
                     "gap of about 0.2 s between turns and the 0.6 to 0.8 s that voice-agent vendors aim for "
                     f"([sources]({GH}/blob/main/bench/conversational/dialogues/RUBRIC.md)).")
    if T:
        t = T["runs"][T["headline"]]
        items.append(f"**It still cuts people off.** At Normal it takes the turn inside {pc(t['test']['rate'])} of real "
                     f"mid-sentence pauses of 0.5 s or more, and answers {secs(t['test']['end_taken_median'])} after a "
                     "real end of turn.")
    items.append("**Not measured here:** a recorded person saying a whole request, Hebrew spoken by people, a person "
                 "rating the conversation, any outside product (Codex voice, Happy, Antigravity), or anyone outside the "
                 "team running this.")
    B.append(("ul", items))
    return B + sections(S, M, H)


def sections(S, M, H) -> list:
    D, Hu, T = S.get("dialogues"), S.get("human"), S.get("turns")
    B = []
    if D:
        B.append(("h2", "The conversation suite", "suite"))
        n_dlg = max(x["dialogues"] for x in D["arms"]["pointe"]["repeats"])
        B.append(("p", f"{n_dlg} scripted dialogues of one to six turns against real throwaway Claude Code sessions (agent "
                       f"{M['agent']}), spoken by synthetic voices: four native Kokoro voices, four accented ones, and an "
                       "OpenAI voice for Hebrew and mixed speech. The scripted user waits for quiet before it speaks and "
                       f"does not adapt. Each dialogue ran on both arms, in one launch, {len(D['arms']['pointe']['repeats'])} times. "
                       "Items changed during the quality work before this run, so earlier rounds of the suite are not "
                       "comparable with these numbers."))
        cols = ["Measure"] + [f"{ARM[a]}, run {i + 1}" for a in ("pointe", "llm-router") for i in range(len(D["arms"][a]["repeats"]))]
        keys = [("First word, median", "ttfw_median", secs), ("First word, p90", "ttfw_p90", secs),
                ("Turns with no reply", "silent_turns", str), ("Time to a useful answer, median", "ttua_median", secs),
                ("A session's answer, median", "ttua_session_answer_median", secs), ("Right session", "right_session", pc),
                ("Right action", "right_action", pc), ("Code names exact", "code_names_exact", pc),
                ("Hebrew and mixed: right action", "hebrew_right_action", pc),
                ("Words beyond what was needed, median", "words_over_need_median", lambda v: f"{v:+.0f}"),
                ("Needless confirmations per 10 turns", "confirmations_per_10", lambda v: f"{v:.1f}")]
        body = []
        for name, k, f in keys:
            row = [name]
            for a in ("pointe", "llm-router"):
                for rep in D["arms"][a]["repeats"]:
                    v = rep.get(k)
                    row.append("n/a" if v is None else f(v))
            body.append(row)
        for model in sorted({m for a in D["arms"].values() for rep in a["repeats"] for m in rep["judges"]}):
            row = [f"Naturalness 1 to 5, model judge {model}"]
            for a in ("pointe", "llm-router"):
                for rep in D["arms"][a]["repeats"]:
                    v = rep["judges"].get(model)
                    row.append("n/a" if v is None else f"{v:.2f}")
            body.append(row)
        B.append(("table", cols, body, "Per run, synthetic speech."))
        ag = []
        for a in ("pointe", "llm-router"):
            for name, x in (D["arms"][a].get("agreement") or {}).items():
                ag.append(f"{ARM[a]}: {name}, {x['n']} dialogues, same score {pc(x['exact'])}, within one point "
                          f"{pc(x['within_one'])}, Spearman {x['spearman']}, mean difference {x['mean_difference']:+.2f}")
        B.append(("ul", [
            "**First word** is from the end of the user's last voiced frame to the first span of the arm's audio in "
            "which a recognizer hears a word; Pointe's waiting sound is not a word, but a word from another session's "
            "news is. A turn that got no word counts as the slowest, not left out (an audit found the earlier scorer "
            "left it out).",
            "**Time to a useful answer** is until the turn's goal is met: the expected fact spoken, the request "
            "delivered to the right session, or the question asked; a turn whose goal is never met counts as 30 s.",
            "**Naturalness** is read by two models from a timed transcript with the arm's name removed, one dialogue "
            "at a time: Claude Fable (the same vendor as both arms' brain) and OpenAI gpt-6-sol. It is a model's "
            "reading, not a person's rating. " + ("Judge agreement: " + "; ".join(ag) + "." if ag else ""),
            "**Not published from the suite:** its talk-over, barge-in and backchannel measures (each rests on one or "
            "two items, and the router cannot be compared on them), and the composite score of our rubric.",
        ]))
        if D.get("dropped"):
            B.append(("p", f"{len(D['dropped'])} dialogue rows were dropped by the rule written before the run (load over "
                           "20 at the start or end, or an error) and run again: listed in summary.json."))
    if H:
        B.append(("h2", "Humanity's Last Keystroke (HLK)", "hlk"))
        B.append(("p", "36 small coding tasks in 12 families, each finished by voice only and graded by hidden tests on "
                       "the repository's final state, three runs each. The same agent works in every arm, so a score "
                       "is what the interface costs, not the agent's strength. Keyboard is the same task typed; Does "
                       "nothing is the floor. Seeds only change names and numbers, so the sample is close to 12 "
                       "families, and the intervals are wide."))
        body = []
        for a in ("keyboard-canonical", "llm-router", "pointe", "null"):
            if a in H["passes"]:
                k, n = H["passes"][a]
                body.append([ARM[a], kn(k, n, wilson(k, n))])
        B.append(("table", ["Arm", "Tasks finished"], body, "Synthetic speech, Kokoro voices."))
        hrows = [json.loads(line) for run in M["benchmarks"]["hlk"]["runs"]
                 for line in (HLK_SUMMARY.parent / run / "rows.jsonl").read_text().splitlines() if line.strip()]
        bad = {a: sum(1 for r in hrows if r["adapter"] == a and r.get("outcome") == "invalid_out_of_tree") for a in H["passes"]}
        if any(bad.values()):
            B.append(("p", "Runs in which the agent wrote outside the task's folder are invalid by HLK's rule and left out "
                           "of the counts above: " + ", ".join(f"{ARM[a]} {n}" for a, n in bad.items() if n) + ". Counted as "
                           "failures instead: " + ", ".join(f"{ARM[a]} {H['passes'][a][0]} of {H['passes'][a][1] + n}"
                                                            for a, n in bad.items() if n) + "."))
        B.append(("p", "By family, and how each failure happened: [the HLK page](hlk/)."))
    if Hu:
        B.append(("h2", "Recorded people: yes, no, stop, mm-hm", "human"))
        B.append(("p", "The one word that answers a permission request is said by a recorded person: 20 speakers of "
                       "Speech Commands v0.02 (Warden, 2018, CC BY 4.0), one clip each, on their own microphones. The "
                       "request before it is still a synthetic voice. \"Stop\" and a listener's \"yeah\", \"okay\" or "
                       "\"mm-hmm\" over a long answer come from Speech Commands and from the AMI Meeting Corpus "
                       "(Carletta et al., 2005, CC BY 4.0). The router has no barge-in, so it ran the yes and no "
                       "dialogues only. The yes and no dialogues ran twice; \"stop\" and \"mm-hm\" once."))
        body = []
        for a, rec in Hu["arms"].items():
            for i, x in enumerate(rec["repeats"]):
                row = [f"{ARM[a]}, run {i + 1}", kn(x['yes_approved']['k'], x['yes_approved']['n']),
                       kn(x['no_denied']['k'], x['no_denied']['n']), str(x["false_approvals"])]
                st = x.get("stop")
                row.append(f"median {secs(st['median'])}, p90 {secs(st['p90'])} ({st['measured']} of {st['n']} measured)"
                           if st and st["measured"] else "n/a")
                bc = x.get("backchannel")
                row.append(f"{bc['false_stop']} of {bc['over_speech']}; sent something {bc['sent_something']}" if bc else "n/a")
                body.append(row)
        B.append(("table", ["Arm, run", "\"Yes\" approved", "\"No\" denied", "Approved after a no",
                            "\"Stop\" over an answer: voice stopped after", "\"Mm-hm\" over an answer: stopped the voice"],
                  body, "Recorded people for the one word; synthetic voices for the rest. A yes or no is counted only "
                        "where the session asked for approval."))
        missed = sorted({(ARM[a], d) for a, rec in Hu["arms"].items() for x in rec["repeats"]
                         for k in ("yes_approved", "no_denied") for d in x[k]["missed"]})
        if missed:
            B.append(("p", "Missed: " + ", ".join(f"{d} ({a})" for a, d in missed) + ". Their rows say what was heard."))
    if T:
        t = T["runs"][T["headline"]]
        B.append(("h2", "Recorded people: when is a turn over?", "turns"))
        B.append(("p", f"{t['clips']} clips of people in AMI meetings, each speaker on their own headset: mid-sentence "
                       "pauses of 0.5 to 2.0 s, where taking the turn cuts the person off, and real ends of turn, where "
                       "what counts is how long Pointe waits. Each clip is streamed to Soniox in real time as the "
                       "daemon does, and the shipped Normal rule (wait 1.3 s after words that read whole) is replayed on "
                       "what Soniox returned. That rule was tuned on these clips, so the speakers are split in two by a "
                       "hash of their name: the rule was chosen on one half and the headline is the other half."))
        body = []
        for name, run in T["runs"].items():
            for split, label in (("test", "speakers not used for tuning"), ("train", "speakers used for tuning"),
                                 ("all", "all")):
                x = run[split]
                body.append([f"{name}: {label}", f"{x['speakers']}", kn(x["cut_ins"], x["pauses"]),
                             f"{pc(x['rate'])} ({ci_p(x['ci95_by_speaker'])})",
                             f"{secs(x['end_taken_median'])} / {secs(x['end_taken_p90'])}"])
        B.append(("table", ["Run and speakers", "Speakers", "Cut-ins on pauses", "Rate (by speaker)",
                            "Real end: turn taken after, median / p90"], body,
                  f"Recorded people. Load median {t['load_median']}, rows over load 20 dropped: "
                  f"{t['dropped_load_or_error']}."))
        B.append(("ul", [
            "These people talk to each other in a meeting, in English, not to a machine and not in Hebrew.",
            "The ends of turn are followed by digital silence in the corpus copy used, which makes an end easier to "
            "detect than on a call.",
        ]))
    B.append(("h2", "The baseline", "baseline"))
    B.append(("ul", [
        "**What it is.** The same recognizer as Pointe (Soniox stt-rt-v6), one call per utterance to the same brain "
        "model (claude-sonnet-5-5, effort low) with a published prompt, and the same ElevenLabs voice. It reads each "
        "permission request aloud and the end of each agent turn. Pointe's team wrote it; a better prompt is welcome.",
        "**Where it has an edge.** It is handed each utterance whole after it ends, so it never decides when a turn is "
        "over and cannot cut anyone off: its turn-taking is not measured, and its times skip the wait Pointe takes "
        "before answering (1.3 s at Normal). In HLK its recognizer call is retried on a dropped connection; Pointe's "
        "live call is not.",
        "**Where it is handicapped.** It says nothing until its agent finishes, then reads the agent's last message; "
        "it has no memory of sessions beyond names and its last action. Its first-word time measures a different "
        "thing from Pointe's, so it is not compared.",
    ]))
    B.append(("h2", "Withdrawn", "withdrawn"))
    B.append(("p", "The five benchmarks published here on 2026-11-23 (HLK, Spoken Identifiers, Spoken Actions, Session "
                   "Routing, Barge-in) were withdrawn on 2026-11-25 after an integrity audit: they measured a Pointe "
                   "build that is not public, the reruns heard different audio from the reference arms, the arms ran "
                   "hours apart, and each had scorer faults (one passed tasks that never reached the agent; one scored "
                   "a false \"approved\" as correct; one left unanswered items out of its median). The audit's fixes "
                   f"are in the harness, and the pages are [kept, marked withdrawn]({GH}/tree/main/docs/benchmarks/withdrawn/2026-11-23). "
                   "HLK was run again for this release."))
    B.append(("h2", "Raw results and how to run them", "raw"))
    B.append(("p", f"Everything above comes from [the release folder]({GH}/tree/main/bench/results/{S['dir']}) in the "
                   f"repository: the manifest (commits, versions, machine, load, commands), the summary, every row and "
                   f"the spend ledger. Downloads: [manifest.json]({S['dir']}/manifest.json), "
                   f"[summary.json]({S['dir']}/summary.json), [all rows, .tar.gz]({S['dir']}/rows.tar.gz)."))
    B.append(("code", "\n".join(M["commands"])))
    B.append(("p", f"Machine: {M['machine']}. Keys come from the macOS Keychain or the environment; the runs call "
                   "paid APIs."))
    B.append(("h2", "Spend", "spend"))
    B.append(("table", ["Benchmark", "Spend"], [[k, f"${v:.2f}"] for k, v in M["spend"].items()],
              "Computed from usage and list prices, not metered; smoke runs and reruns included."))
    B.append(("p", "The speech components (recognizers, brains, voices) were benchmarked one at a time, on synthetic "
                   "speech, before 0.8.5: [speech component benchmarks](https://eng.ballerine.com/pointe/docs/benchmarks/)."))
    return B


# ---------- writers ----------

def md_inline(t: str) -> str:
    return t


def html_inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', t)


def markdown(B: list) -> str:
    out = ["<!-- Written by bench/publish.py from the release's results. Do not edit by hand. -->", ""]
    for b in B:
        k = b[0]
        if k == "h1":
            out += [f"# {b[1]}", ""]
        elif k == "h2":
            out += [f"## {b[1]}", ""]
        elif k in ("p", "lead"):
            out += [b[1].replace("](hlk/)", "](hlk.md)"), ""]
        elif k == "ul":
            out += [f"- {x}" for x in b[1]] + [""]
        elif k == "table":
            out += ["| " + " | ".join(b[1]) + " |", "|" + "---|" * len(b[1])]
            out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in b[2]]
            out += ["", f"{b[3]}", ""]
        elif k == "code":
            out += ["```", b[1], "```", ""]
    text = "\n".join(out).rstrip() + "\n"
    return re.sub(r"\]\((20\d\d-[^)]+)\)", lambda m: f"](https://eng.ballerine.com/pointe/benchmarks/{m.group(1)})", text)


HEAD = ROOT / "bench" / "publish_template.html"  # the page around the blocks: head, nav, footer


def page(B: list, version: str) -> str:
    body, open_section, in_hero = [], False, False
    for b in B:
        k = b[0]
        if k == "h1":
            body.append(f'  <section class="pg-hero">\n    <p class="pg-kicker">Benchmarks</p>\n'
                        f'    <h1 class="pg-h1">{html.escape(b[1])}</h1>')
            in_hero = True
        elif k == "lead":
            body.append(f'    <p class="pg-lead">{html_inline(b[1])}</p>\n  </section>')
            in_hero = False
        elif k == "h2":
            if open_section:
                body.append("  </section>")
            body.append(f'  <section class="pg-section" id="{b[2]}" aria-labelledby="h-{b[2]}">\n'
                        f'    <div class="pg-section-head"><h2 class="pg-h2" id="h-{b[2]}">{html.escape(b[1])}</h2></div>')
            open_section = True
        elif k == "p":
            body.append(f'    <p class="bm-q">{html_inline(b[1])}</p>')
        elif k == "ul":
            cls = "bm-findings" if open_section else "pg-how"
            body.append(f'  <ul class="{cls}">\n' + "\n".join(f"    <li>{html_inline(x)}</li>" for x in b[1]) + "\n  </ul>")
        elif k == "table":
            head = "".join(f'<th scope="col">{html_inline(c)}</th>' for c in b[1])
            rows = "".join('<tr><th scope="row">' + html_inline(str(r[0])) + "</th>" +
                           "".join(f"<td>{html_inline(str(c))}</td>" for c in r[1:]) + "</tr>" for r in b[2])
            body.append(f'    <p class="pg-small bm-cap">{html_inline(b[3])}</p><div class="bm-scroll"><table class="bm-table">'
                        f"<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>")
        elif k == "code":
            body.append(f'    <pre class="bm-code"><code>{html.escape(b[1])}</code></pre>')
    assert not in_hero
    if open_section:
        body.append("  </section>")
    return HEAD.read_text().replace("{{MAIN}}", "\n".join(body)).replace("{{VERSION}}", version)


LANDING = ROOT / "site" / "pointe" / "index.html"
EVIDENCE = re.compile(r"(<!-- bench:begin[^>]*-->\n)(.*?)(      <!-- bench:end -->)", re.S)


def evidence(S: dict) -> str:
    """The landing page's measured figures, from the same summary as the benchmark page."""
    D, Hu, T = S.get("dialogues"), S.get("human"), S.get("turns")
    rel = S["release"][1:]
    cells = []
    if D:
        p = D["arms"]["pointe"]["pooled"]
        n = len(D["arms"]["pointe"]["repeats"])
        cells.append((secs(p["ttfw_median"]), "to the first word after you stop, median",
                      f"p90 {secs(p['ttfw_p90'])}. {p['speech_turns']} turns of scripted dialogues, synthetic voices, "
                      f"{many(n, 'run')}; {many(p['silent_turns'], 'turn')} got no reply."))
    if Hu:
        reps = Hu["arms"]["pointe"]["repeats"]
        yk, yn = sum(x["yes_approved"]["k"] for x in reps), sum(x["yes_approved"]["n"] for x in reps)
        nk, nn = sum(x["no_denied"]["k"] for x in reps), sum(x["no_denied"]["n"] for x in reps)
        cells.append((f"{yk} of {yn}", "recorded \"yes\" answers approved",
                      f"20 people (Speech Commands), {many(len(reps), 'run')}; \"no\" denied {nk} of {nn}."))
    if T:
        t = T["runs"][T["headline"]]["test"]
        cells.append((pc(t["rate"]), "of real mid-sentence pauses cut in on",
                      f"At Normal. {t['pauses']} pauses by {t['speakers']} people in meetings (AMI), not used for tuning."))
    cells.append(("$1", "about, for a busy hour",
                  "60 replies, by arithmetic from list prices. Not counting your agents' own spend."))
    out = [f'      <h3 class="h3 block">Measured in Pointe {rel}</h3>', '      <div class="cells" style="margin-top:16px">']
    for i, (fig, title, small) in enumerate(cells):
        key = " figure--key" if i == 0 else ""
        out.append(f'        <div><p class="figure{key}">{html.escape(fig)}</p><p class="title">{html.escape(title)}</p>\n'
                   f'          <p class="small">{html.escape(small)}</p></div>')
    out.append("      </div>")
    out.append('      <p class="small" style="margin-top:12px">Measured on '
               f'{html.escape(S["date"])} against a plain router we wrote. Where Pointe loses, how each number was made, '
               'and the raw rows: <a href="benchmarks/">Benchmarks</a>.</p>')
    return "\n".join(out) + "\n"


def landing(S: dict) -> str:
    text = LANDING.read_text()
    if not EVIDENCE.search(text):
        raise SystemExit("site/pointe/index.html has no bench:begin / bench:end block")
    return EVIDENCE.sub(lambda m: m.group(1) + evidence(S) + m.group(3), text, count=1)


def tarball(release: Path) -> bytes:
    """Every file of the release folder, and HLK's runs with its freeze, in a fixed order with fixed times, so the same
    rows give the same bytes."""
    M = json.loads((release / "manifest.json").read_text())
    hlk = ROOT / "bench" / "conversational" / "hlk"
    files = [(p, f"{release.name}/{p.relative_to(release)}") for p in sorted(release.rglob("*")) if p.is_file()]
    for run in M["benchmarks"].get("hlk", {}).get("runs", []):
        files += [(p, f"{release.name}/hlk/{p.relative_to(hlk / 'results')}") for p in sorted((hlk / "results" / run).rglob("*"))
                  if p.is_file()]
    if M["benchmarks"].get("hlk"):
        files += [(hlk / "FROZEN.json", f"{release.name}/hlk/FROZEN.json")]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p, name in files:
            info = tarfile.TarInfo(name)
            data = p.read_bytes()
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as g:
        g.write(raw.getvalue())
    return out.getvalue()


def build(release: Path) -> dict:
    S = json.loads((release / "summary.json").read_text())
    S["dir"] = release.name
    M = json.loads((release / "manifest.json").read_text())
    H = json.loads(HLK_SUMMARY.read_text()) if (HLK_SUMMARY.exists() and "hlk" in M["benchmarks"]) else None
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    if version != S["release"][1:]:
        S["newer"] = version
    B = blocks(S, M, H)
    S["date"] = M["date"]
    files = {DOCS / "README.md": markdown(B), SITE / "index.html": page(B, version), LANDING: landing(S),
             SITE / release.name / "manifest.json": (release / "manifest.json").read_text(),
             SITE / release.name / "summary.json": (release / "summary.json").read_text()}
    for path, text in files.items():
        if path.suffix in (".md", ".html") and re.search(r"\b(leaderboard|state[- ]of[- ]the[- ]art|best-in-class|"
                                                          r"blazing|seamless|revolutionary)\b", text, re.I):
            raise SystemExit(f"{path.name} uses a word the pages must not use")
    return files


def main(release: Path) -> int:
    for path, text in build(release).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    tgz = SITE / release.name / "rows.tar.gz"
    tgz.write_bytes(tarball(release))
    print(f"wrote {tgz.relative_to(ROOT)} ({tgz.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
