"""How soon could each brain say its first checked sentence, and is it right as often? And would a fast "opener"
model in front of the brain be safe?

  .venv/bin/python bench/first_word_bench.py brains [--models a,b] [--repeats 1]   # the real Brain, timed
  .venv/bin/python bench/first_word_bench.py openers [--models a,b]                # a 2-5 word opener by a fast model
  .venv/bin/python bench/first_word_bench.py report

`brains`: bench/brain_bench.py's cases, prompts, stub tools and rubric, through the real brain.Brain with the first
sentence said ahead as on a call (speak_first). Timed from the request: the first token (vendors that stream), the first
sentence that passed the speech checks and was handed to the mouth, and the first tool call. A vendor Pointe does not
read as it writes gives its first sentence when its whole reply is in: that is what a setup with it would do today.
Two calls at a time per vendor, so the times are a call's and not a queue's.

`openers`: the planner pattern. A small model is given the user's words and the session names, and nothing else, and
asked for an opener that is true whatever the answer turns out to be. Scored in code, never by a model: an opener
"claims" when it states a result, a number, a yes or a no, or that something was or will be done; and it "promises"
when it says an action is under way and the main brain (the current default's reply to the same case, from `brains`)
then called no tool. One claim is one too many: the opener is said before the brain has decided anything.

Synthetic cases (bench/brain_cases.py). Stub tools answer at once. One workstation, one network path."""

import argparse
import asyncio
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "pointe"), str(HERE.parent), str(HERE)]

import brain_bench as bb  # noqa: E402
import brain_cases as bc  # noqa: E402
import brain as brain_module  # noqa: E402
import conversation  # noqa: E402
import vendors  # noqa: E402

OUT = bb.OUT / "first_word.jsonl"
bb.FILES = [f if f.startswith("bench/") else f"pointe/{f}" for f in bb.FILES]  # the modules moved under pointe/
bb.PROMPTS = bb.OUT / "first_word_prompts.json"  # frozen here, apart from the brain bench's own
BRAINS = ["anthropic:claude-sonnet-5-5", "anthropic:claude-haiku-5-5", "gemini:gemini-3.8-flash",
          "gemini:gemini-3.5-flash-lite", "openai:gpt-6-sol", "openai:gpt-6-luna"]
OPENERS = ["anthropic:claude-haiku-5-5", "gemini:gemini-3.5-flash-lite", "openai:gpt-6-luna"]
DEFAULT = BRAINS[0]
PER_VENDOR = 2
OPENER_SYSTEM = """You write the first half second of a voice assistant's reply. A slower model writes the real answer \
after you, and you do not know what it will say or do.
Say one opener of two to five words that stays true whatever the answer turns out to be. It may only show that the \
request was heard. Never state a fact, a number, a result, a yes or a no. Never say what will be done, that anything \
was sent, asked, checked or started, and never name a session.
If the user's words are a thanks, an acknowledgment, a yes or a no, or an unfinished sentence, reply with the single \
word NONE.
Reply in the language of the user's words. Reply with the opener and nothing else."""
# What an opener may not say: it is spoken before anything is known or decided.
CLAIM = re.compile(r"\d|\b(yes|yeah|yep|no|nope|done|sent|passed|failed|fixed|finished|ready|correct|right|wrong|sure|"
                   r"absolutely|certainly|of course|it is|it's|there (is|are)|they|כן|לא|נשלח|בוצע|סיימתי|בטח|ברור)\b", re.I)
ACTION = re.compile(r"\b(on it|checking|asking|sending|looking|pulling|running|starting|let me|i'll|i will|i'm|i am|"
                    r"one (sec|second|moment)|בודק|שולח|שואל|מריץ|רגע|שנייה)\b", re.I)


def load() -> float:
    return float(subprocess.run(["uptime"], capture_output=True, text=True).stdout.split("load averages:")[-1].split()[0])


def rows(kind: str) -> list[dict]:
    if not OUT.exists():
        return []
    return [r for r in map(json.loads, OUT.read_text().splitlines()) if r["kind"] == kind and not r.get("error")]


def usd(model: str, usage: list[dict]) -> float:
    """From the tokens each step reported (vendors.Step.usage), at bench/brain_bench.py's list prices."""
    price = bb.PRICES.get(model.split(":", 1)[1])
    if not price:
        return 0.0
    total = 0.0
    for u in usage:
        cached = u.get("cached", 0)
        total += ((u.get("context", 0) - cached) * price[0] + cached * price[1] + u.get("reply", 0) * price[3]) / 1e6
    return total


async def brain_once(choice: str, case: bc.BrainCase, frozen: dict) -> dict:
    at: dict[str, float] = {}
    calls, spoken, usage = [], [], []
    t0 = 0.0

    def stamp(name: str, when: float | None = None) -> None:
        at.setdefault(name, round((when or time.time()) - t0, 3))

    async def speak(text: str) -> None:
        stamp("speech")
        spoken.append(text)

    async def speak_rest(rest: str, _whole: str) -> None:
        if rest:
            spoken.append(rest)

    block, needs = bb.daemon_context(case)
    has_open = lambda: needs if re.search(r"Waits on the user for: (?!nothing)", needs) else None  # noqa: E731
    b = brain_module.Brain(choice, frozen["brain_system"], bb.stub_tools(case, frozen, calls), lambda: block, speak,
                           has_open=has_open, sent_lately=lambda: case.sent_lately, on_usage=usage.append,
                           on_tool=lambda name, *_a: stamp("tool") if name != "speak" else None, **bb.daemon_gates(case))
    b.speak_first, b.speak_rest = speak, speak_rest
    b.limit = lambda trigger, asked: conversation.limit_for(trigger, asked)
    b.stage = lambda name, when=None: stamp(name, when)
    bb.seed_history(b, case)
    t0 = time.time()
    await b.turn(case.words)
    stamp("done")
    said = " ".join(spoken)
    refused = [r["result"]["error"] for m in b.messages if m["role"] == "tool" for r in m["results"]
               if r["name"] == "speak" and isinstance(r["result"], dict) and "Not spoken" in str(r["result"].get("error"))]
    row = {"spoken": said, "calls": calls, "refused": refused, "fallback": said.startswith(bb.FALLBACKS), "steps": usage,
           "at": at, "usd": round(usd(choice, usage), 5)}
    if row["fallback"]:
        row["error"] = "the brain said a fallback line: the vendor failed"
    return row


async def opener_once(choice: str, case: bc.BrainCase) -> dict:
    vendor, model = choice.split(":", 1)
    names = ", ".join(s["name"] if isinstance(s, dict) else getattr(s, "name", str(s)) for s in case.sessions)
    prompt = f"Sessions: {names}\nThe user said: {case.words}"
    t0, first, text = time.time(), None, ""
    if vendor == "anthropic":
        async with vendors._anthropic().messages.stream(model=model, max_tokens=30, system=OPENER_SYSTEM,
                                                        messages=[{"role": "user", "content": prompt}]) as stream:
            async for piece in stream.text_stream:
                first = first or time.time()
                text += piece
    elif vendor == "gemini":
        from google.genai import types

        config = types.GenerateContentConfig(system_instruction=OPENER_SYSTEM, max_output_tokens=30, temperature=0.0,
                                             thinking_config=types.ThinkingConfig(thinking_level="minimal"))
        async for chunk in await vendors._gemini().aio.models.generate_content_stream(model=model, contents=prompt, config=config):
            if chunk.text:
                first = first or time.time()
                text += chunk.text
    else:
        stream = await vendors._openai().responses.create(model=model, instructions=OPENER_SYSTEM, input=prompt, stream=True,
                                                          store=False, max_output_tokens=30, reasoning={"effort": "none"})
        async for event in stream:
            if event.type == "response.output_text.delta":
                first = first or time.time()
                text += event.delta
    return {"opener": text.strip(), "at": {"first_token": round((first or time.time()) - t0, 3), "done": round(time.time() - t0, 3)}}


async def collect(kind: str, models: list[str], repeats: int, max_load: float) -> None:
    frozen = bb.freeze_prompts() if kind == "brain" else {}
    done = {(r["model"], r["case"], r["rep"]) for r in rows(kind)}
    gates = {v: asyncio.Semaphore(PER_VENDOR) for v in {m.split(":")[0] for m in models}}
    lock = asyncio.Lock()
    work = [(m, c, r) for r in range(repeats) for c in bc.BRAIN_CASES for m in models if (m, c.name, r) not in done]
    print(f"{len(work)} to run ({len(done)} done), load {load()}", flush=True)

    async def one(model, case, rep):
        async with gates[model.split(":")[0]]:
            while load() > max_load:
                await asyncio.sleep(10)
            try:
                got = await asyncio.wait_for(brain_once(model, case, frozen) if kind == "brain" else opener_once(model, case), 90)
            except Exception as e:
                got = {"error": f"{type(e).__name__}: {bb.scrub(e)}"[:300]}
        row = {"kind": kind, "model": model, "case": case.name, "rep": rep, "load": load(), **got}
        async with lock:
            with OUT.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    await asyncio.gather(*(one(*w) for w in work))
    failed = [r for r in map(json.loads, OUT.read_text().splitlines()) if r["kind"] == kind and r.get("error")]
    print(f"done; {len(failed)} errors so far: {sorted({(r['model'], r['error'][:90]) for r in failed})[:6]}", flush=True)


def pct(values: list, q: float):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))] if ordered else None


def cell(values: list) -> str:
    return f"{statistics.median(values):5.2f} {pct(values, 0.9):5.2f}" if values else "    -     -"


def report() -> None:
    cases = {c.name: c for c in bc.BRAIN_CASES}
    brains = rows("brain")
    print(f"Brains: {len(brains)} replies, load median {statistics.median(r['load'] for r in brains):.1f}\n" if brains else "no brain rows")
    print(f"{'brain':30s} {'n':>3s} {'right':>6s}  {'first token':>11s}  {'first sentence':>14s}  {'spoken replies':>14s}  "
          f"{'first tool':>11s}  {'$/reply':>7s}")
    print(f"{'':30s} {'':>3s} {'':>6s}  {'med   p90':>11s}  {'med   p90':>14s}  {'med   p90':>14s}  {'med   p90':>11s}")
    passed: dict[str, dict] = {}
    for model in dict.fromkeys(r["model"] for r in brains):
        rs = [r for r in brains if r["model"] == model]
        ok = {(r["case"], r["rep"]): not bb.score_brain(cases[r["case"]], r) for r in rs}
        passed[model] = ok
        speech = [r["at"]["speech"] for r in rs if "speech" in r["at"]]
        only_speech = [r["at"]["speech"] for r in rs if "speech" in r["at"] and "tool" not in r["at"]]
        print(f"{model:30s} {len(rs):3d} {sum(ok.values()) / len(ok):6.1%}  {cell([r['at']['first_token'] for r in rs if 'first_token' in r['at']]):>11s}  "
              f"{cell(speech):>14s}  {cell(only_speech):>14s}  {cell([r['at']['tool'] for r in rs if 'tool' in r['at']]):>11s}  "
              f"{statistics.mean(r['usd'] for r in rs):7.4f}")
    if DEFAULT in passed:
        print(f"\nAgainst {DEFAULT} on the same cases (right there and wrong here / wrong there and right here):")
        for model, ok in passed.items():
            both = [k for k in ok if k in passed[DEFAULT]]
            if model != DEFAULT and both:
                worse = sum(passed[DEFAULT][k] and not ok[k] for k in both)
                better = sum(ok[k] and not passed[DEFAULT][k] for k in both)
                print(f"  {model:30s} {worse:3d} / {better:3d} of {len(both)}")
    openers = rows("opener")
    if not openers:
        return
    acted = {r["case"]: any(c["name"] != "speak" for c in r["calls"]) for r in brains if r["model"] == DEFAULT}
    print(f"\nOpeners: {len(openers)}; the main brain is {DEFAULT}")
    print(f"{'opener model':30s} {'n':>3s} {'said one':>8s}  {'first token':>11s}  {'whole opener':>12s}  {'claims':>6s}  "
          f"{'promises an action the brain did not take':>42s}")
    for model in dict.fromkeys(r["model"] for r in openers):
        rs = [r for r in openers if r["model"] == model]
        said = [r for r in rs if r["opener"] and r["opener"].strip(". ").upper() != "NONE"]
        claims = [r for r in said if CLAIM.search(r["opener"]) or len(r["opener"].split()) > 6]
        promises = [r for r in said if ACTION.search(r["opener"]) and acted.get(r["case"]) is False]
        print(f"{model:30s} {len(rs):3d} {len(said):8d}  {cell([r['at']['first_token'] for r in said]):>11s}  "
              f"{cell([r['at']['done'] for r in said]):>12s}  {len(claims):6d}  {len(promises):42d}")
        for r in (claims + promises)[:6]:
            print(f"      {r['case']:28s} {r['opener']!r}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["brains", "openers", "report"])
    p.add_argument("--models", default="")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--max-load", type=float, default=20.0)
    a = p.parse_args()
    bb.OUT.mkdir(exist_ok=True)
    if a.cmd == "report":
        report()
    else:
        kind = "brain" if a.cmd == "brains" else "opener"
        models = a.models.split(",") if a.models else (BRAINS if kind == "brain" else OPENERS)
        asyncio.run(collect(kind, models, a.repeats, a.max_load))


if __name__ == "__main__":
    main()
