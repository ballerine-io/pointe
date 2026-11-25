"""The naturalness judge: Fable reads one dialogue run at a time as a timed transcript (what the user said, what the
voice said, when, and where the user's words were delivered), with the arm's name removed, and scores it 1 to 5 on the
rubric below. Runs are judged one by one in a shuffled order, so a score is absolute, not a ranking against the arm
beside it. Spend goes into the suite's ledger."""

import json
import os
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
# DLG_JUDGE_MODEL picks another judge when Fable is unavailable; its scores are not comparable with Fable rounds.
MODEL = os.environ.get("DLG_JUDGE_MODEL", "claude-fable-5-1")

RUBRIC = """You judge how natural a spoken conversation with a voice assistant felt to the developer. The assistant sits in
front of one or more coding-agent sessions (named after their projects): it answers questions about them, passes
instructions to them, reads their permission requests, and reports back. You get one conversation as a timed
transcript: USER lines are what the developer said, VOICE lines what the assistant said aloud (as heard back by a
recognizer, so small word errors are not the assistant's), and -> lines where the developer's words were delivered.
Times are seconds from the start of the call: each line starts at its time and runs "until" the time given. The
silence the developer sat through is from the end of their line to the start of the next VOICE line.

Score 1 to 5:
5  Like a sharp human assistant: answers start within about a second or two, are as short as the question needs, say
   the useful thing first, no needless "should I?" or read-back, asks only when the request was really unclear, and
   never talks over the developer.
4  Natural with one small flaw (one long-ish pause, one extra sentence, one needless check).
3  Usable but clearly a machine: several pauses of 4+ seconds, padding, or a needless confirmation.
2  Tiring: long silences (8+ s) before answers, rambling replies, repeated questions, talking over the developer,
   or the answer arriving only after unrelated chatter.
1  Broken: the developer gets no useful answer, is misunderstood repeatedly, or is left with silence.
Judge only the conversation as experienced; do not reward or punish which tool was used.
Reply with one JSON object and nothing else: {"score": <1-5>, "evidence": "<two short sentences citing times>"}"""


def transcript(row: dict) -> str:
    t0 = row.get("call_ready") or (row["turns"][0]["start"] - 5 if row["turns"] else 0)
    items = [(t["start"], f"USER (until {t['end'] - t0:.1f}): {t['say'].replace('|', '...')}") for t in row["turns"]]
    items += [(s, f"VOICE (until {e - t0:.1f}): {x}") for s, e, x in row.get("said") or [] if x.strip() and s >= t0]
    for name, s in (row.get("sessions") or {}).items():
        for t, p in s.get("prompts", []):
            if t >= t0 and "Read NOTES.md now" not in p:
                items.append((t, f"-> delivered to {name}: {p[:200]}"))
    items.sort()
    return "\n".join(f"[{t - t0:6.1f}] {line}" for t, line in items)


def judge_one(client, text: str) -> tuple[dict, dict]:
    resp = client.messages.create(model=MODEL, max_tokens=3000, system=RUBRIC, output_config={"effort": "low"},
                                  messages=[{"role": "user", "content": text}])
    out = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", out, re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
    except ValueError:
        got = {}
    u = resp.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
             "cache_read_input_tokens": u.cache_read_input_tokens or 0,
             "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}
    return got, usage


def main(run_ids: list, arms: str) -> int:
    import anthropic
    from core import ledger
    from run import key, load_rows
    client = anthropic.Anthropic(api_key=key("ANTHROPIC_API_KEY", "anthropic-api-key"), max_retries=3)
    for rid in run_ids:
        rows = load_rows([rid])
        latest = {}
        for r in rows:
            latest[(r["dialogue"], r["arm"])] = r
        items = list(latest.items())
        random.Random(20261124).shuffle(items)
        out: dict = {}
        usd = 0.0
        for (dlg, arm), row in items:
            if arm not in arms.split(","):
                continue
            got, usage = judge_one(client, transcript(row))
            usd += ledger.token_cost(MODEL, usage)
            out.setdefault(arm, {})[dlg] = got
            print(dlg, arm, got.get("score"), flush=True)
        for arm, scores in out.items():
            vals = [v.get("score") for v in scores.values() if isinstance(v.get("score"), (int, float))]
            (HERE / "results" / rid / f"judge-{arm}.json").write_text(json.dumps(
                {"model": MODEL, "mean": round(sum(vals) / len(vals), 2) if vals else None, "n": len(vals),
                 "runs": scores}, indent=1, ensure_ascii=False) + "\n")
        ledger.append({"benchmark": "dialogues", "run_id": rid, "item": "judge", "arm": arms, "kind": "judge", "usd": round(usd, 4)})
        print(f"judge spend ${usd:.3f}")
    return 0
