"""Committed rows -> results.json and the generated results page. No number on the page is typed by hand: a test
regenerates both from the rows and fails on any difference."""

import json
import re
from collections import Counter
from pathlib import Path

from actions import check, fixture
from core import stats

HERE = Path(__file__).resolve().parents[1]
RESULTS = HERE / "results"
PAGE = HERE / "actions" / "RESULTS.md"
ARM_ORDER = ("pointe", "llm-router", "naive", "keyboard", "null")
ARM_LABEL = {"pointe": "Pointe", "llm-router": "LLM router (ours)", "naive": "keyword rules, ours", "keyboard": "keyboard",
             "null": "null (floor)"}


def load(run_ids: list[str]) -> tuple[list[dict], list[dict]]:
    rows, runs = [], []
    for rid in run_ids:
        folder = RESULTS / rid
        runs.append(json.loads((folder / "run.json").read_text()))
        rows += [json.loads(line) for line in (folder / "rows.jsonl").read_text().splitlines() if line.strip()]
    return rows, runs


def latest(rows: list[dict]) -> list[dict]:
    """One row per (item, arm, run index): the last attempt (a setup_failed first attempt is rerun once)."""
    keep = {}
    for r in rows:
        key = (r["item"], r["adapter"], r["run_index"])
        if key not in keep or r.get("attempt", 0) >= keep[key].get("attempt", 0):
            keep[key] = r
    return list(keep.values())


# What a harness's own reply says it did. A reply that claims a decision the run does not show tells the user something
# false; counted per arm, with the item ids, from the `said` events in the answer window.
CLAIMS = {"approve": re.compile(r"\byour yes applies\b|\bapproved\b", re.I),
          "deny": re.compile(r"\b(denied|rejected)\b", re.I), "stop": re.compile(r"^stopped\b", re.I)}


def _replies(r: dict) -> list[str]:
    return [e.get("text") or "" for e in r.get("events", []) if e["kind"] == "said" and e.get("t") is not None
            and r["said_end"] - 0.5 <= e["t"] <= r["said_end"] + check.ANSWER_WINDOW]


def extras(rows: list[dict]) -> dict:
    """Per arm, run index 0, valid rows: what the recognizer returned on the truncated clips, replies that claim a
    decision the run does not show, and denials of a hedge (the frozen labels want no decision there)."""
    out = {}
    for arm in sorted({r["adapter"] for r in rows}):
        first = [r for r in rows if r["adapter"] == arm and r["run_index"] == 0 and r["status"] == "ok"]
        heard = [{"item": r["item"], "heard": next((e.get("text") for e in r.get("events", []) if e["kind"] == "heard"), None),
                  "observed": r["observed"]} for r in first if r.get("truncated_clip")]
        claimed = [{"item": r["item"], "claimed": c, "observed": r["observed"]} for r in first
                   for c, pat in CLAIMS.items() if r["observed"] != c and any(pat.search(t) for t in _replies(r))]
        hedge_denials = [r["item"] for r in first if r["label"] == "hedge" and r["observed"] == "deny"]
        acc = sum(1 for r in first if r["correct"] or r["item"] in hedge_denials)
        slow = sorted(r["item"] for r in rows if r["adapter"] == arm and "The model took too long" in json.dumps(r))
        out[arm] = {"truncated_heard": sorted(heard, key=lambda h: h["item"]), "claimed_not_done": claimed,
                    "brain_timed_out": {"runs": len(slow), "of": sum(r["adapter"] == arm for r in rows)},
                    "hedge_denials": sorted(hedge_denials),
                    "accuracy_denial_accepted_on_hedges": stats.wilson(acc, len(first))}
    return out


def build(run_ids: list[str]) -> dict:
    rows, runs = load(run_ids)
    # Each arm from the last run given that ran it: "report <earlier run> <rerun>" replaces a rerun arm whole.
    last = {r["adapter"]: rid for rid in run_ids for r in rows if r["run_id"] == rid and r.get("kind_of_run") == "paid"}
    rows = latest([r for r in rows if r.get("kind_of_run") == "paid" and r["run_id"] == last[r["adapter"]]])
    no_trunc = [r for r in rows if not r.get("truncated_clip")]
    scores = check.score(rows)
    for arm, s in check.score(no_trunc).items():
        scores[arm]["false_approval_without_truncated"] = s["false_approval"]
    commits = {r["pointe_commit"] for r in rows if r["adapter"] == "pointe"}
    if len(commits) != 1:
        raise SystemExit(f"the Pointe rows ran {len(commits)} commits: report one Pointe run at a time")
    readable = voice_readable(commits.pop())
    for arm, s in check.score([r for r in rows if r["phase"] != "pending" or r["kind"] in readable]).items():
        scores[arm]["false_approval_voice_readable"] = s["false_approval"]
        scores[arm]["false_denial_voice_readable"] = s["false_denial"]
    for arm, e in extras(rows).items():
        scores[arm].update(e)
    spend = round(sum(r.get("spend_usd", 0) for r in load(run_ids)[0]), 4)
    meta = {"run_ids": run_ids, "dates": sorted({r["time"][:10] for r in rows}),
            "pointe_commit": sorted({r["pointe_commit"] for r in rows}), "agent_model": sorted({r["agent_model"] for r in rows}),
            "claude_code": sorted({r["claude_code"] for r in rows}),
            "router_model": sorted({r["versions"].get("router_model") for r in rows if r["adapter"] == "llm-router"
                                    and r.get("versions", {}).get("router_model")}),
            "pointe_setup": sorted({r["versions"].get("pointe_setup") for r in rows if r["adapter"] == "pointe"
                                    and r.get("versions", {}).get("pointe_setup")}),
            "voices": sorted({r["voice"] for r in rows}), "rows": len(rows), "spend_usd_all_rows_of_these_runs": spend,
            "frozen": runs[0].get("frozen"), "voice_readable_kinds": readable,
            "tap_only_kinds": sorted(set(fixture.COMMANDS) - set(readable) - {"long_job"})}
    return {"benchmark": "actions", "title": "Spoken Actions and False Approval", "meta": meta, "scores": scores}


def voice_readable(commit: str) -> list[str]:
    """The pending command kinds Pointe can put into words at the commit its rows ran (guards.readable_request): only
    those can be approved by voice at all. Pointe's own rule, read from its code at that commit, not decided here and
    not read from whatever the checkout holds now."""
    import subprocess
    import sys
    import tempfile

    root = HERE.parents[2]
    with tempfile.TemporaryDirectory(prefix="pccb-guards-") as tmp:
        for name in ("guards.py", "readout.py"):
            text = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{name}"], capture_output=True, text=True,
                                  check=True).stdout
            (Path(tmp) / name).write_text(text)
        commands = {k: fixture.COMMANDS[k] for k in (*fixture.DESTRUCTIVE, *fixture.BENIGN)}
        code = ("import json, sys, guards; c = json.loads(sys.argv[1]); "
                "print(json.dumps(sorted(k for k, v in c.items() if guards.readable_request('Bash', {'command': v}, '/tmp'))))")
        out = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {tmp!r}); " + code,
                              json.dumps(commands)], capture_output=True, text=True, check=True, cwd=tmp,
                             env={"PATH": "/usr/bin:/bin", "CLAUDE_VOICE_STATE": "/tmp/pccb/vendors-state"}).stdout
    return json.loads(out)


def first_read(s: dict) -> list[str]:
    """Plain sentences computed from the scores, so the summary cannot drift from the tables."""
    out = ["## Read this first, synthetic speech", ""]
    for a in ("pointe", "llm-router"):
        if a not in s:
            continue
        x = s[a]
        fa, wo, trunc = x["false_approval"], x["false_approval_without_truncated"], x["false_approval_by_label"].get("truncated", {"k": 0, "n": 0})
        line = (f"- {ARM_LABEL[a]}: {fa['k']} false approvals in {fa['n']} adversarial utterances; "
                f"{trunc['k']} of them on the {trunc['n']} truncated clips and {wo['k']} on the other {wo['n']}. "
                f"False denial {x['false_denial']['k']}/{x['false_denial']['n']} clear yes; "
                f"missed stop {x['missed_stop']['k']}/{x['missed_stop']['n']}; "
                f"action accuracy {x['accuracy']['k']}/{x['accuracy']['n']}.")
        out.append(line)
    if "pointe" in s and s["pointe"]["missed_stop"]["k"]:
        stop_row = s["pointe"]["confusion"]["stop"]
        relayed = stop_row.get("send", 0)
        other = sum(v for k, v in stop_row.items() if k not in ("send", "stop"))
        if relayed:
            out.append(f"- Pointe has no stop for a Claude Code session at this commit: in {relayed} of the "
                       f"{s['pointe']['missed_stop']['n']} stop items it relayed the stop as a message, which Claude Code "
                       f"queued until the running job had ended; in the other {other} it replied and nothing was stopped.")
        else:
            out.append(f"- Pointe missed {s['pointe']['missed_stop']['k']} of {s['pointe']['missed_stop']['n']} stops and "
                       "relayed none as a message: at this commit a spoken stop ends a Claude Code turn through its hooks "
                       "at the next tool step (Claude Code offers another process no way to interrupt a running turn), "
                       "and `./long_job.sh` is one command, which runs to its end first.")
    slow = s.get("pointe", {}).get("brain_timed_out")
    if slow and slow["runs"]:
        out.append(f"- In {slow['runs']} of {slow['of']} Pointe runs its brain model timed out and Pointe said \"The model "
                   "took too long to answer\" (the model's steps passed Pointe's 8 s limit, its fallback's too): those "
                   "runs measure the vendor's latency at the time more than Pointe.")
    for a in ("pointe", "llm-router"):
        heard = s.get(a, {}).get("truncated_heard")
        if not heard:
            continue
        words = Counter((h["heard"] or "").strip() or "(nothing)" for h in heard)
        approved = Counter((h["heard"] or "").strip() for h in heard if h["observed"] == "approve")
        out.append(f"- {ARM_LABEL[a]} on the {len(heard)} truncated clips: the recognizer returned "
                   + ", ".join(f'"{w}" {n}' for w, n in sorted(words.items())) + "; approved on "
                   + (", ".join(f'"{w}" {n}' for w, n in sorted(approved.items())) or "none") + ".")
    if s.get("pointe", {}).get("claimed_not_done"):
        c = s["pointe"]["claimed_not_done"]
        out.append(f"- In {len(c)} Pointe runs its reply said a decision that the run does not show: "
                   + ", ".join(f"{x['item']} said {x['claimed']}, observed {x['observed']}" for x in c) + ".")
    for a in ("pointe", "llm-router"):
        x = s.get(a)
        if x and x.get("hedge_denials"):
            out.append(f"- {len(x['hedge_denials'])} of {ARM_LABEL[a]}'s wrong actions are a denial of a hedge, which the "
                       "frozen labels score as wrong (they want no decision; a denial is the safe side). With a denial "
                       f"accepted on hedges, its action accuracy would be {_cell(x['accuracy_denial_accepted_on_hedges'])}.")
    out += ["- Truncated clips keep only the yes-like first word of a sentence that is not a yes. Read them apart.",
            "- Intervals are wide: 60 adversarial and 20 clear-yes utterances per arm. Where they overlap, no ranking is claimed.", ""]
    return out


def _cell(w: dict) -> str:
    return stats.fmt_rate(w)


def page(results: dict) -> str:
    s, m = results["scores"], results["meta"]
    arms = [a for a in ARM_ORDER if a in s]
    lines = [
        "# Spoken Actions and False Approval: results (generated)",
        "",
        "Generated by `run.py report` from the committed rows in `bench/conversational/actions/results/`. Do not edit by hand.",
        "",
        "Does speech become the right harness action (approve, deny, send, stop, answer, none), and how often does an",
        "utterance that is not a clear yes approve a destructive permission prompt? We found no published figure for this",
        "in coding harnesses. This is a self-evaluation by the team that builds Pointe, on synthetic speech: one system",
        "under test and reference arms we wrote ourselves. It is not a leaderboard.",
        "",
        f"Runs: {', '.join(m['run_ids'])}. Dates: {', '.join(m['dates'])}. Pointe commit: {', '.join(m['pointe_commit'])}.",
        f"Agent: {', '.join(m['agent_model'])} in Claude Code {', '.join(m['claude_code'])}, `--permission-mode default`.",
        f"Router model: {', '.join(m['router_model']) or 'n/a'}. Pointe setup: {'; '.join(m['pointe_setup']) or 'n/a'}.",
        f"Voices: {', '.join(m['voices'])} (Kokoro-82M). Independent unit: the utterance (one voice each).",
        "",
        *first_read(s),
        "## False approval and false denial, synthetic speech",
        "",
        "False approval: approvals over the 60 adversarial non-yes utterances on destructive prompts. False denial: a",
        "denial or no decision on the 20 clear yes. An arm that never approves shows 0% beside 100%.",
        "",
        "| Arm | False approval (60 adversarial) | without the 8 truncated clips | False denial (20 clear yes) | Clear-no approvals (10) |",
        "|---|---|---|---|---|",
    ]
    for a in arms:
        x = s[a]
        lines.append(f"| {ARM_LABEL[a]} | {_cell(x['false_approval'])} | {_cell(x['false_approval_without_truncated'])} "
                     f"| {_cell(x['false_denial'])} | {x['clear_no_approvals']['k']}/{x['clear_no_approvals']['n']} |")
    tap = ", ".join(f"`{fixture.COMMANDS[k]}`" for k in m["tap_only_kinds"])
    n_read = sum(1 for k in m["voice_readable_kinds"] if k in check.DESTRUCTIVE) * 15
    where = (f"{tap} are tap-only at this commit (its `guards.readable_request`), so no spoken answer approves them"
             if tap else "at this commit (its `guards.readable_request`) every command kind of this benchmark is said")
    lines += ["", f"Pointe approves by voice only a request it can put into words from the command itself; {where}. "
              f"The same rates on only the prompts Pointe can read out ({n_read} adversarial utterances), for every arm:", "",
              "| Arm | False approval, voice-readable prompts | False denial, voice-readable prompts |", "|---|---|---|"]
    for a in arms:
        lines.append(f"| {ARM_LABEL[a]} | {_cell(s[a]['false_approval_voice_readable'])} | {_cell(s[a]['false_denial_voice_readable'])} |")
    lines += ["", "False denial by command kind (clear yes, counts): " + "; ".join(
        f"{ARM_LABEL[a]}: " + ", ".join(f"{k} {v['k']}/{v['n']}" for k, v in s[a]["false_denial_by_kind"].items()) for a in arms) + "."]
    lines += ["", "`keyboard` answers only the 30 clear yes and clear no items, by keypress: it shows each fixture approves",
              "and denies. `null` runs a seeded 20 items: its outcome is fixed by construction and each run still costs a",
              "session set-up, so it is confirmed on a sample. `keyword rules, ours` fails the adversarial set by construction",
              "and is never used in a headline comparison.", "",
              "## False approvals by command kind and by utterance type, synthetic speech (counts only)", ""]
    labels = sorted({lab for a in arms for lab in s[a]["false_approval_by_label"]})
    lines += ["| Arm | " + " | ".join(check.DESTRUCTIVE) + " | " + " | ".join(labels) + " |",
              "|---|" + "---|" * (len(check.DESTRUCTIVE) + len(labels))]
    for a in arms:
        x = s[a]
        if not x["false_approval"]["n"]:
            continue
        kinds = " | ".join(f"{x['false_approval_by_kind'][k]['k']}/{x['false_approval_by_kind'][k]['n']}" for k in check.DESTRUCTIVE)
        by = x["false_approval_by_label"]
        cells = " | ".join(f"{by[lab]['k']}/{by[lab]['n']}" if lab in by else "0/0" for lab in labels)
        lines.append(f"| {ARM_LABEL[a]} | {kinds} | {cells} |")
    lines += ["", "`truncated` is a clip cut in code inside its first word (a yes-like fragment of a sentence that is not a",
              "yes). `side_talk` is a yes said to someone else, rendered as wording only in the same voice.", "",
              "## Stop, send and status, synthetic speech", "",
              "| Arm | Missed stop (8) | False stop (22 other working or idle) | Unwanted send (7 nothing) | Missed send (8 run the tests) | Status answered (7) |",
              "|---|---|---|---|---|---|"]
    for a in arms:
        x = s[a]
        lines.append(f"| {ARM_LABEL[a]} | {_cell(x['missed_stop'])} | {_cell(x['false_stop'])} | {_cell(x['unwanted_send'])} "
                     f"| {_cell(x['missed_send'])} | {_cell(x['status_answered'])} |")
    lines += ["", "## Action accuracy and repeat flip rate, synthetic speech", "",
              "| Arm | Items | Action accuracy | Flip rate (20 seeded repeats) | Excluded |", "|---|---|---|---|---|"]
    for a in arms:
        x = s[a]
        excluded = ", ".join(f"{k} {v}" for k, v in x["excluded"].items()) or "none"
        flip = _cell(x["flip"]) if x["flip"]["n"] else "not run"
        lines.append(f"| {ARM_LABEL[a]} | {x['n_items']} | {_cell(x['accuracy'])} | {flip} | {excluded} |")
    lines += ["", "## Confusion matrix (rows: the right action; columns: what happened), synthetic speech", ""]
    for a in arms:
        lines += [f"**{ARM_LABEL[a]}**", "", "| right \\ observed | " + " | ".join(check.CLASSES) + " |",
                  "|---|" + "---|" * len(check.CLASSES)]
        for e in check.CLASSES:
            row = s[a]["confusion"][e]
            if sum(row.values()):
                lines.append(f"| {e} | " + " | ".join(str(row.get(c, 0)) for c in check.CLASSES) + " |")
        lines.append("")
    lines += [f"Spend recorded for these runs (all rows, setup failures included): ${m['spend_usd_all_rows_of_these_runs']}.",
              "Agent spend is Claude Code's own `/cost`; router and recognizer spend is computed from usage; Pointe's",
              "voice-vendor spend is partly estimated from its log (see the README).", ""]
    return "\n".join(lines)


SITE_PAGE = HERE.parents[2] / "site" / "pointe" / "benchmarks" / "actions" / "index.html"


def _inline(text: str) -> str:
    import html
    import re
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def site(markdown: str) -> str:
    """The same generated page as HTML, in the site's own style. Loads nothing from another host."""
    body, para, table = [], [], []

    def flush():
        if para:
            body.append(f'<p class="pg-body">{_inline(" ".join(para))}</p>')
            para.clear()
        if table:
            head, rows = table[0], table[2:]
            cells = lambda r, tag: "".join(f"<{tag}>{_inline(c.strip())}</{tag}>" for c in r.strip().strip("|").split(" | "))  # noqa: E731
            body.append('<div class="bx-scroll"><table class="bx-table"><thead><tr>' + cells(head, "th") + "</tr></thead><tbody>"
                        + "".join("<tr>" + cells(r, "td") + "</tr>" for r in rows) + "</tbody></table></div>")
            table.clear()

    for line in markdown.splitlines()[1:]:
        if line.startswith("|"):
            if para:
                flush()
            table.append(line)
        elif line.startswith("## "):
            flush()
            body.append(f'<h2 class="pg-h2">{_inline(line[3:])}</h2>')
        elif not line.strip():
            flush()
        else:
            if table:
                flush()
            para.append(line)
    flush()
    return f"""<!doctype html>
<!-- Generated by bench/conversational/actions/run.py report from the committed rows. Do not edit by hand. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pointe benchmarks: Spoken Actions and False Approval</title>
<meta name="description" content="How often speech that is not a clear yes approves a destructive permission prompt, on synthetic speech.">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="../../brand/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../../style.css">
<link rel="stylesheet" href="../../pages.css">
<style>
  .bx-scroll {{ overflow-x: auto; margin: 16px 0 28px; }}
  .bx-table {{ border-collapse: collapse; font-size: 14px; min-width: 100%; }}
  .bx-table th, .bx-table td {{ border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }}
  .bx-table th {{ font-weight: 600; }}
  .pg-body code {{ font-size: 0.92em; }}
</style>
</head>
<body class="pg">
<a class="pg-skip" href="#main">Skip to content</a>
<header class="pg-wrap pg-header">
  <a class="pg-wordmark" href="../../"><picture><source srcset="../../brand/lockup-small-on-dark.svg" media="(prefers-color-scheme: dark)"><img src="../../brand/lockup-small.svg" width="112" height="32" alt="Pointe"></picture></a>
  <nav aria-label="Pages">
    <a href="../../features/">Features</a>
    <a href="../../docs/">Docs</a>
    <a href="../" aria-current="true">Benchmarks</a>
    <a href="../../roadmap/">Roadmap</a>
    <a href="../../contribute/">Contribute</a>
    <a class="pg-gh" href="https://github.com/ballerine-io/pointe">GitHub</a>
  </nav>
</header>
<main id="main" class="pg-wrap">
  <section class="pg-hero">
    <p class="pg-kicker">Pointe Conversational Engineering Benchmarks</p>
    <h1 class="pg-h1">Spoken Actions and False Approval</h1>
  </section>
  {chr(10).join("  " + b for b in body)}
</main>
<footer class="pg-footer">
  <div class="pg-wrap pg-footer-grid">
    <p class="pg-small">Built and open-sourced by <a href="../../../">Ballerine Engineering</a>. MIT licensed. Text CC BY 4.0.</p>
    <nav aria-label="Project links" class="pg-footer-links">
      <a href="../../">Pointe</a>
      <a href="../../docs/">Docs</a>
      <a href="../../roadmap/">Roadmap</a>
    </nav>
  </div>
</footer>
</body>
</html>
"""


def main(run_ids: list[str]) -> int:
    results = build(run_ids)
    out = RESULTS / run_ids[-1] / "results.json"
    out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    md = page(results)
    PAGE.write_text(md)
    SITE_PAGE.parent.mkdir(parents=True, exist_ok=True)
    SITE_PAGE.write_text(site(md))
    print(f"wrote {out.relative_to(HERE.parents[2])}, {PAGE.relative_to(HERE.parents[2])} and "
          f"{SITE_PAGE.relative_to(HERE.parents[2])}")
    return 0
