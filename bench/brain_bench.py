"""Which model should decide what the voice says (the brain), and which should turn a long final message into a report (the reader).

    .venv/bin/python bench/brain_bench.py validate                  # counts, lengths, synthetic-data lint, format against the daemon
    .venv/bin/python bench/brain_bench.py run --role brain|reader   # resumable; raw rows in results/brain_raw.jsonl
    .venv/bin/python bench/brain_bench.py judge                     # blind 1-5 score of every distinct reply
    .venv/bin/python bench/brain_bench.py report                    # scores offline from the raw rows; writes results/brain.md

The brain path is the real one: brain.Brain with its speech gates, vendors.step, and the daemon's prompt; only the tools are
stubs that return canned results. The reader path is vendors.text with REPORT_SYSTEM, as the daemon calls it.

The prompts are frozen in results/brain_prompts.json at the first run, so an edit to the daemon during a run cannot make one
candidate see a different prompt. Delete that file to measure a new prompt. Calls are measured by wrapping the vendor client
in this process: vendors.py discards cached and thinking tokens, which are billed. Retries happen in the wrapper, are counted,
and are not part of any latency.
"""

import argparse
import asyncio
import contextvars
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

import brain_cases as bc  # noqa: E402
import brain as brain_module  # noqa: E402
from guards import ack_only  # noqa: E402
import brief  # noqa: E402
import vendors  # noqa: E402
from loguru import logger  # noqa: E402

OUT = HERE / "results"
RAW = OUT / "brain_raw.jsonl"
JUDGED = OUT / "brain_judged.jsonl"
SPEND = OUT / "brain_spend.jsonl"
PROMPTS = OUT / "brain_prompts.json"
REPORT = OUT / "brain.md"
FILES = ["brain.py", "vendors.py", "brief.py", "daemon.py", "bench/brain_cases.py"]

CANDIDATES = ["gemini:gemini-3.5-flash", "gemini:gemini-3.6-flash", "gemini:gemini-3.7-flash", "gemini:gemini-3.8-flash",
              "gemini:gemini-3.5-flash-lite", "anthropic:claude-haiku-5-5", "anthropic:claude-sonnet-5-5",
              "anthropic:claude-opus-5-5"]
ALIASES = {"gemini:gemini-3.5-flash": "gemini:gemini-3.6-flash", "gemini:gemini-3.7-flash": "gemini:gemini-3.8-flash"}
JUDGE = "anthropic:claude-sonnet-5-5"
SECOND_JUDGE = "gemini:gemini-3.8-flash"
SECOND_JUDGE_SHARE = 0.15
READER_TEMPERATURE = 0.1  # daemon._read_model
READER_THINKING = {"level": "low"}
REPORT_TIMEOUT_SECS = 10.0  # daemon.REPORT_TIMEOUT_SECS: past this the daemon falls back to an excerpt
SEED = 20261106
PARALLEL = {"gemini": 6, "anthropic": 4, "openai": 4, "local": 1}  # local: one model on one machine; parallel calls only queue
MAX_ATTEMPTS = 6

# USD per million tokens: input, cache read, cache write, output. Read 2026-11-06 from the vendors' public pages:
# https://aistudio.google.com/docs/pricing and https://platform.claude.com/docs/en/about-claude/pricing
# Gemini 3.6 and 3.8 Flash are at an introductory price through 2026-12-31; both double on 2027-01-01. Thinking tokens bill as output.
PRICES = {
    "gemini-3.6-flash": (0.75, 0.075, 0.75, 3.75),
    "gemini-3.8-flash": (0.75, 0.075, 0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 0.03, 0.30, 2.50),
    "claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50),
    "claude-sonnet-5-5": (2.00, 0.10, 2.50, 10.00),
    "claude-opus-5-5": (4.00, 0.20, 5.00, 20.00),
    "claude-fable-5-1": (10.00, 0.25, 12.50, 50.00),
    "gemini-4-argon": (2.00, 0.10, 2.00, 10.00),  # through 2026-11-30, then double
    "gemini-3.1-pro-preview": (2.00, 0.20, 2.00, 12.00),
    # https://developers.openai.com/api/docs/pricing, read 2026-11-06. OpenAI has no cache write charge.
    "gpt-5-mini": (0.25, 0.025, 0.25, 2.00),
    "gpt-5.4-mini": (0.75, 0.075, 0.75, 4.50),
    "gpt-5.5": (5.00, 0.50, 5.00, 30.00),
    "gpt-5.6-luna": (0.20, 0.02, 0.20, 1.20),
    "gpt-5.6-terra": (2.00, 0.20, 2.00, 12.00),
    "gpt-5.6-sol": (4.00, 0.40, 4.00, 20.00),
    "gpt-6-luna": (0.10, 0.01, 0.10, 0.50),
    "gpt-6-astra": (10.00, 1.00, 10.00, 50.00),
    "gpt-6-sol": (2.00, 0.20, 2.00, 10.00),
    "gpt-6.1-sol": (2.00, 0.10, 2.00, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, 1.00, 5.00),
}
PRICE_2027_FACTOR = {"gemini-3.6-flash": 2.0, "gemini-3.8-flash": 2.0, "gemini-4-argon": 2.0}

CURRENT: contextvars.ContextVar = contextvars.ContextVar("current")
SPENT = {"total": 0.0, "limit": 25.0, "phase": ""}


def scrub(text: str) -> str:
    """An error message goes into a file that may be published."""
    return re.sub(r"(AIza[\w-]{10,}|sk-[\w-]{10,}|key=[\w-]+|/Users/[^\s'\"]+)", "[removed]", str(text))[:300]


def cost_of(model: str, usage: dict) -> float | None:
    price = PRICES.get(model) or PRICES.get(re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model))  # OpenAI reports the dated name
    if not price:
        return None
    fresh = usage["input"] - usage["cached"]
    return (fresh * price[0] + usage["cached"] * price[1] + usage["cache_write"] * price[2]
            + (usage["output"] + usage["thoughts"]) * price[3]) / 1e6


def _usage_gemini(resp) -> dict:
    u = resp.usage_metadata
    return {"served": resp.model_version or "", "input": getattr(u, "prompt_token_count", 0) or 0,
            "cached": getattr(u, "cached_content_token_count", 0) or 0, "cache_write": 0,
            "output": getattr(u, "candidates_token_count", 0) or 0, "thoughts": getattr(u, "thoughts_token_count", 0) or 0}


def _usage_anthropic(resp) -> dict:
    u = resp.usage
    read, write = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
    return {"served": resp.model, "input": u.input_tokens + read, "cached": read, "cache_write": write,
            "output": u.output_tokens, "thoughts": 0}


def _usage_openai(resp) -> dict:
    u = resp.usage
    if hasattr(u, "input_tokens"):  # Responses API. output_tokens already includes reasoning, which bills as output.
        return {"served": resp.model, "input": u.input_tokens, "cached": u.input_tokens_details.cached_tokens or 0, "cache_write": 0,
                "output": u.output_tokens, "thoughts": 0}
    details = getattr(u, "prompt_tokens_details", None)
    return {"served": resp.model, "input": u.prompt_tokens, "cached": getattr(details, "cached_tokens", 0) or 0, "cache_write": 0,
            "output": u.completion_tokens, "thoughts": 0}


def _retriable(e: Exception) -> bool:
    if isinstance(e, asyncio.TimeoutError):
        return True
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return type(e).__name__ in ("APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout", "RemoteProtocolError",
                                "ServerDisconnectedError", "ReadError")


def _measured(call, usage_of):
    async def run(*a, **k):
        rec = CURRENT.get(None)
        for attempt in range(MAX_ATTEMPTS):
            started = time.perf_counter()
            try:
                resp = await asyncio.wait_for(call(*a, **k), 120)
            except Exception as e:
                if rec is not None:
                    rec["errors"].append(f"{type(e).__name__}: {scrub(e)}")
                if not _retriable(e) or attempt == MAX_ATTEMPTS - 1:
                    raise
                if rec is not None:
                    rec["retries"] += 1
                await asyncio.sleep(min(60, 2 ** attempt * 2) + random.random() * 2)
                continue
            ms = int((time.perf_counter() - started) * 1000)
            usage = usage_of(resp)
            model = usage["served"]
            usd = cost_of(model, usage)
            SPENT["total"] += usd or 0
            with SPEND.open("a") as f:
                f.write(json.dumps({"phase": SPENT["phase"], "model": model, "usd": usd or 0}) + "\n")
            if rec is not None:
                rec["steps"].append({**usage, "ms": ms, "usd": usd})
            return resp
    return run


def instrument(vendor_list: set[str]) -> None:
    """Measure every real call; our retry replaces the SDK's, whose hidden retries would count as latency."""
    if "anthropic" in vendor_list:
        import anthropic
        client = vendors._clients.setdefault("anthropic", anthropic.AsyncAnthropic(api_key=vendors.key("anthropic"), max_retries=0))
        client.messages.create = _measured(client.messages.create, _usage_anthropic)
    if "gemini" in vendor_list:
        models = vendors._gemini().aio.models
        models.generate_content = _measured(models.generate_content, _usage_gemini)
    if "openai" in vendor_list:
        from openai import AsyncOpenAI
        client = vendors._clients.setdefault("openai", AsyncOpenAI(api_key=vendors.key("openai"), max_retries=0))
        client.chat.completions.create = _measured(client.chat.completions.create, _usage_openai)
        client.responses.create = _measured(client.responses.create, _usage_openai)
    if "local" in vendor_list:
        client = vendors._local()
        client.chat.completions.create = _measured(client.chat.completions.create, _usage_openai)


# ---------- the frozen prompts ----------

def load_daemon():
    """Read-only: its import needs a state dir with a token, and it starts nothing."""
    tmp = tempfile.mkdtemp(prefix="brain-bench-")
    Path(tmp, "token").write_text("bench")
    os.environ["CLAUDE_VOICE_STATE"] = tmp
    import daemon
    return daemon


def freeze_prompts() -> dict:
    if PROMPTS.exists():
        return json.loads(PROMPTS.read_text())
    d = load_daemon()
    frozen = {"brain_system": d.INSTRUCTIONS + d.BRAIN_RULES, "report_system": brief.REPORT_SYSTEM,
              "brief_system": brief.BRIEF_SYSTEM,
              "tools": [{"name": t.name, "description": t.description, "properties": t.properties, "required": t.required}
                        for t in d.TOOLS.standard_tools],
              "frozen_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
              "git_head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
              "file_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()[:16] for f in FILES}}
    OUT.mkdir(exist_ok=True)
    PROMPTS.write_text(json.dumps(frozen, ensure_ascii=False, indent=1))
    return frozen


# ---------- one reply ----------

def default_tool_result(case: bc.BrainCase, name: str, args: dict):
    active = case.sessions[case.active]
    if name == "send_to_claude_code":
        return {"sent_to": [active.name], "routing": "active", "note": "Sent is not done: say you asked Claude, not that it happened."}
    if name == "list_sessions":
        return {"sessions": [{"name": s.name, "active": s is active, "working": s.busy, "waiting_for_permission": s.permission,
                              "needs_from_user": list(s.waits) or None, "clocks": list(s.clocks), "urgent": s.urgent,
                              "where_it_stands": (s.notes or {}).get("state") or s.state, "latest": ""} for s in case.sessions]}
    if name == "ask_about_session":
        return {"session": active.name, "answer": "not in the transcript",
                "say": "Say you do not know from what you have, and offer to ask Claude."}
    if name == "switch_session":
        return {"active": next((s.name for s in case.sessions if str(args.get("name", "")).split("/")[0].split("-")[0].lower() in s.name.lower()),
                               case.sessions[-1].name)}
    if name == "set_mode":
        return {"mode": args.get("mode", "orchestrator")}
    if name == "rename_session":
        return {"renamed": active.name, "to": args.get("new_name") or "pricing"}
    return {"error": f"No tool named {name}."}


def stub_tools(case: bc.BrainCase, frozen: dict, calls: list) -> list:
    used: dict[str, int] = {}

    def make(decl: dict):
        async def handler(params):
            name = decl["name"]
            canned = case.tools.get(name)
            if isinstance(canned, list):
                result = canned[min(used.get(name, 0), len(canned) - 1)]
            else:
                result = canned if canned is not None else default_tool_result(case, name, params.arguments)
            used[name] = used.get(name, 0) + 1
            calls.append({"name": name, "args": params.arguments, "result": result})
            await params.result_callback(result)

        return SimpleNamespace(**decl, handler=handler)

    return [make(d) for d in frozen["tools"]]


def seed_history(b, case: bc.BrainCase) -> None:
    """Earlier turns in the shape brain.py leaves them: speech is a speak call with a "spoken" result."""
    for i, (who, text) in enumerate(case.history):
        if who == "bot":
            call = {"id": f"past{i}", "name": "speak", "args": {"text": text}}
            b.messages.append({"role": "assistant", "calls": [call]})
            b.messages.append({"role": "tool", "results": [{"id": call["id"], "name": "speak", "result": "spoken"}]})
        else:
            b.append(text)


FALLBACKS = ("I lost my connection to the model", "Sorry, I lost that", "That took too many steps")


def daemon_gates(case: bc.BrainCase) -> dict:
    """The hooks daemon.make_brain gives Brain that read the user's words: without them the gates judge a different call."""
    return {"may_stay_silent": lambda: ack_only(case.words),
            "language_problem": lambda said: _language_problem(said, case.words)}


def _language_problem(said: str, words: str) -> str | None:
    """daemon._language_problem, for these words and not the daemon's shared state: replies run in parallel."""
    hebrew, latin = len(re.findall(r"[\u0590-\u05ff]", said)), len(re.findall(r"[a-zA-Z]", said))
    if re.search(r"[\u0590-\u05ff]", words):
        return "Their latest words are in Hebrew: say it in Hebrew, keeping technical terms in English." if not hebrew and latin else None
    return "Their latest words are in English: say it in English." if words and hebrew > latin else None


async def brain_reply(choice: str, case: bc.BrainCase, frozen: dict) -> dict:
    rec = {"steps": [], "retries": 0, "errors": []}
    CURRENT.set(rec)
    calls, spoken = [], []

    async def speak(text: str) -> None:
        spoken.append(text)

    block = bc.right_now(case, brief.render_brief)
    needs = bc.needs_block(case)
    has_open = lambda: needs if re.search(r"Waits on the user for: (?!nothing)", needs) else None  # noqa: E731 daemon._open_items
    b = brain_module.Brain(choice, frozen["brain_system"], stub_tools(case, frozen, calls), lambda: block, speak,
                           has_open=has_open, sent_lately=lambda: case.sent_lately, **daemon_gates(case))
    seed_history(b, case)
    await b.turn(case.words)
    refused = [r["result"]["error"] for m in b.messages if m["role"] == "tool" for r in m["results"]
               if r["name"] == "speak" and isinstance(r["result"], dict) and "Not spoken" in str(r["result"].get("error"))]
    said = " ".join(spoken)
    out = {**rec, "spoken": said, "calls": calls, "refused": refused, "fallback": said.startswith(FALLBACKS)}
    if said.startswith(FALLBACKS[0]):  # Brain caught a vendor error: the vendor failed, the model did not answer badly
        out["error"] = rec["errors"][-1] if rec["errors"] else "brain step failed"
    return out


async def reader_reply(choice: str, case: bc.ReaderCase, frozen: dict) -> dict:
    rec = {"steps": [], "retries": 0, "errors": []}
    CURRENT.set(rec)
    prompt = brief.report_prompt(case.session, case.final, case.brief, list(case.asked), list(case.still_open), list(case.clocks))
    text = await vendors.text(choice, prompt, frozen["report_system"], json_reply=True, thinking=READER_THINKING["level"], temperature=READER_TEMPERATURE)
    return {**rec, "reply": text}


async def run_one(role: str, choice: str, case, rep: int, frozen: dict, gate: asyncio.Semaphore, out, tag: str) -> None:
    if SPENT["total"] >= SPENT["limit"]:
        return
    async with gate:
        if SPENT["total"] >= SPENT["limit"]:
            return
        row = {"role": role, "model": choice, "case": case.name, "rep": rep, "tag": tag, "at": time.strftime("%H:%M:%S")}
        started = time.perf_counter()
        try:
            got = await (brain_reply if role == "brain" else reader_reply)(choice, case, frozen)
        except Exception as e:  # after the retries, or refused outright: an error, reported, not a silent drop
            rec = CURRENT.get()
            got = {**rec, "error": f"{type(e).__name__}: {scrub(e)}"}
        row.update(got)
        row["wall_ms"] = int((time.perf_counter() - started) * 1000)
        row["reply_ms"] = sum(s["ms"] for s in row["steps"])
        row["usd"] = sum(s["usd"] or 0 for s in row["steps"])
        out.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        out.flush()


def done_keys(path: Path) -> set:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if not r.get("error") and not r.get("fallback_error"):
            keys.add((r["role"], r["model"], r["case"], r["rep"]))
    return keys


async def run(args) -> None:
    frozen = freeze_prompts()
    # A slow model is measured instead of being cut off; `substance` reports how often it passes the daemon's limit.
    brain_module.STEP_TIMEOUT_SECS = args.step_timeout
    READER_THINKING["level"] = args.reader_thinking
    SPENT["limit"], SPENT["phase"] = args.budget, f"{args.role}:{args.tag}"
    SPENT["total"] = spent_so_far()
    print(f"spent so far ${SPENT['total']:.2f} of ${SPENT['limit']:.2f}", flush=True)
    models = args.models.split(",") if args.models else CANDIDATES
    pool = bc.BRAIN_CASES if args.role == "brain" else bc.READER_CASES
    if args.cases:
        wanted = set(args.cases.split(","))
        pool = [c for c in pool if c.name in wanted]
    instrument({m.split(":")[0] for m in models})
    path = RAW if args.tag == "main" else OUT / f"brain_raw_{args.tag}.jsonl"
    done = set() if args.rerun else done_keys(path)
    work = [(m, c, r) for m in models for c in pool for r in range(args.repeats) if (args.role, m, c.name, r) not in done]
    random.Random(SEED).shuffle(work)  # the time of day falls evenly on every candidate
    print(f"{len(work)} replies to run ({len(done)} already done)", flush=True)
    gates = {v: asyncio.Semaphore(n) for v, n in PARALLEL.items()}
    with path.open("a") as out:
        tasks = [asyncio.create_task(run_one(args.role, m, c, r, frozen, gates[m.split(":")[0]], out, args.tag)) for m, c, r in work]
        finished = 0
        for t in asyncio.as_completed(tasks):
            await t
            finished += 1
            if finished % 50 == 0:
                print(f"{finished}/{len(work)} spent ${SPENT['total']:.2f}", flush=True)
    print(f"done; spent ${SPENT['total']:.2f}", flush=True)


def spent_so_far() -> float:
    if not SPEND.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in SPEND.read_text().splitlines())


# ---------- the rubric ----------

HEBREW = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[A-Za-z]")
PATH = re.compile(r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z]{1,5}\b|/Users/|~/|\b\w+\.(?:ts|py|js|tsx|json|sql|md)\b")
CODE = re.compile(r"`|\*\*|^#|\w+\(\)|=>|\bawait \w+|\bSELECT\b.*\bFROM\b|\bFOR UPDATE\b|\w+\.\w+\(", re.M)
LEAK = re.compile(r"send_to_claude_code|list_sessions|ask_about_session|switch_session|\[right now\]|\b(my|the|your) notes\b|"
                  r"\bthe feed\b|\bthe transcript\b|\bspeak tool\b", re.I)
PROMISE = re.compile(r"(?<!and )\bi(?:'ll| will|'m going to| am going to) (?:pause|stop|tell|send|have|run|check|kick|get|make|start|merge|delete|ask)\b"
                     r"(?!.{0,25}\b(?:once|if|when|after) )|"
                     r"\bon it\b|\bi(?:'ve| have) (?:asked|told|sent)\b|\bi (?:asked|told|sent)\b|\bi'm (?:pausing|stopping)\b|(?<!לא )שלחתי|(?<!לא )ביקשתי", re.I)
WORD = re.compile(r"[\w֐-׿][\w֐-׿'’.,\-/]*")


def words_in(text: str) -> int:
    return len(WORD.findall(text))


def language_problem(text: str, lang: str) -> str | None:
    he, latin = len(HEBREW.findall(text)), len(LATIN.findall(text))
    if lang == "en" and he:
        return "language: Hebrew in an English reply"
    if lang == "he" and (not he or he < latin):  # technical terms stay in English, the sentence does not
        return "language: not Hebrew"
    return None


def has(rx: str, text: str) -> bool:
    return re.search(rx, text, re.I | re.M) is not None


def speech_failures(text: str, session_names: list[str]) -> list[str]:
    plain = text
    for name in session_names:
        plain = plain.replace(name, "session")
    out = []
    if PATH.search(plain):
        out.append("spoken: a path")
    if CODE.search(plain):
        out.append("spoken: code or markdown")
    return out


def score_brain(case: bc.BrainCase, row: dict) -> list[str]:
    r, said = case.rubric, row.get("spoken") or ""
    if row.get("error") or row.get("fallback") or (not said and not r.silence_ok):
        return ["no usable reply"]
    called = [c["name"] for c in row["calls"]]
    sends = [str(c["args"].get("message", "")) for c in row["calls"] if c["name"] == bc.SEND]
    fails = []
    if r.tool and not set(r.tool) & set(called):
        fails.append(f"tool: did not call {'/'.join(r.tool)}")
    for name in r.banned:
        if name in called:
            fails.append(f"tool: called {name}")
    for name, most in r.max_calls.items():
        if called.count(name) > most:
            fails.append(f"tool: called {name} {called.count(name)} times")
    for name, least in r.min_calls.items():
        if called.count(name) < least:
            fails.append(f"tool: called {name} {called.count(name)} times, needed {least}")
    for i, group in enumerate(r.groups):
        if not any(has(rx, said) for rx in group):
            fails.append(f"missing: {group[0][:50]}")
    for rx in r.forbid:
        if has(rx, said):
            fails.append(f"forbidden: {rx[:50]}")
    for group in r.send_groups:
        if not any(has(rx, m) for rx in group for m in sends):
            fails.append(f"send lacks: {group[0][:50]}")
    problem = language_problem(said, r.lang) if said else None  # silence has no language
    if problem:
        fails.append(problem)
    n, limit = words_in(said), math.ceil(r.max_words * 1.1)  # 10 percent slack, the same as the reader's
    if n > limit:
        fails.append(f"length: {n} words, limit {limit}")
    if r.question and "?" not in said:
        fails.append("no question asked")
    if r.order:
        a, b = re.search(r.order[0], said, re.I), re.search(r.order[1], said, re.I)
        if a and b and a.start() > b.start():
            fails.append(f"order: {r.order[1][:30]} came before {r.order[0][:30]}")
    if r.starts and not has(r.starts, " ".join(said.split()[:8])):
        fails.append(f"start: {r.starts[:30]}")
    if LEAK.search(said):
        fails.append("leak: named a tool or the notes")
    if PROMISE.search(said) and not any("sent_to" in (c["result"] or {}) for c in row["calls"] if c["name"] == bc.SEND):
        fails.append("promise: claims an action with nothing sent")
    fails += speech_failures(said, [s.name for s in case.sessions])
    return fails


def score_reader(case: bc.ReaderCase, row: dict) -> list[str]:
    r = case.rubric
    if row.get("error"):
        return ["no usable reply"]
    report = brief.parse(row.get("reply"))
    if not report:
        return ["report: not JSON"]
    say = str(report.get("say") or "")
    fails = []
    if r.speak is not None and bool(report.get("speak")) != r.speak:
        fails.append(f"speak: expected {r.speak}")
    if r.speak is False:  # a holding line: what it would say matters less than staying quiet
        pass
    elif not say:
        return fails + ["report: no say"]
    for group in r.groups:
        if not any(has(rx, say) for rx in group):
            fails.append(f"missing: {group[0][:50]}")
    for rx in r.forbid:
        if has(rx, say):
            fails.append(f"forbidden: {rx[:50]}")
    if r.status and report.get("status") not in r.status:
        fails.append(f"status: {report.get('status')}")
    if r.waiting is not None and bool(report.get("waiting")) != r.waiting:
        fails.append(f"waiting: expected {r.waiting}")
    if r.urgency and report.get("urgency") != r.urgency:
        fails.append(f"urgency: expected {r.urgency}")
    if r.typed and not report.get("typed_approval_needed"):
        fails.append("typed_approval_needed: empty")
    questions = [str(q) for q in report.get("questions") or []]
    if len(questions) < r.min_questions:
        fails.append(f"questions: {len(questions)}, needed {r.min_questions}")
    joined = " ".join(questions)
    for group in r.question_groups:
        if not any(has(rx, joined) for rx in group):
            fails.append(f"questions lack: {group[0][:40]}")
    clocks = " ".join(str(q) for q in report.get("deadlines") or [])
    for group in r.deadline_groups:
        if not any(has(rx, clocks) for rx in group):
            fails.append(f"deadlines lack: {group[0][:40]}")
    for item in r.settled:
        if item not in [str(q) for q in report.get("settled") or []]:
            fails.append("settled: earlier item not copied")
    if r.early and say and not has(r.early, " ".join(say.split()[:20])):
        fails.append(f"early: {r.early[:30]}")
    limit = 99 if report.get("urgency") == "high" else 66  # the prompt's 90 and 60, with 10 percent slack
    if words_in(say) > limit:
        fails.append(f"length: {words_in(say)} words, limit {limit}")
    fails += speech_failures(say, [])
    return fails


# ---------- the blind judge ----------

JUDGE_SYSTEM = """You judge one spoken reply from a voice assistant to its user, a CTO who is hands-free and works through coding \
agents. You see what the assistant knew, what the user said, what the assistant did, and what it said aloud. You do not know \
who or what wrote it. Score only this question: is this what a sharp chief of staff would say at this moment?

5: exactly right. Correct, committed, short, moves the work forward, and it is what the moment needs.
4: right, with one small weakness in focus or wording.
3: acceptable, not sharp: it hedges, pads, misses the emphasis, or needs a follow-up question.
2: wrong emphasis, an important omission, or an action that was not wanted.
1: wrong or harmful: false, hides bad news, or does what the user did not ask.

Length is judged for speech: a long answer is a fault unless the user asked for detail. Reply with JSON only: \
{"score": 1 to 5, "why": "under 15 words"}"""


def reader_view(case: bc.ReaderCase) -> str:
    asked = "\n".join(f"- {a}" for a in case.asked) or "(nothing on this call)"
    return f"The owner's recent words:\n{asked}\n\nClaude Code's final message, complete:\n{case.final}"


def brain_view(case: bc.BrainCase) -> str:
    past = "\n".join(f"{who}: {text}" for who, text in case.history) or "(no earlier turns)"
    return (f"What the assistant knew:\n{bc.right_now(case, brief.render_brief)}\n\nEarlier in the call:\n{past}\n\n"
            f"The user now says: {case.words}")


def judge_prompt(role: str, case, row: dict) -> str | None:
    if row.get("error") or row.get("fallback"):
        return None
    if role == "brain":
        actions = "\n".join(f"- {c['name']}({json.dumps(c['args'], ensure_ascii=False)}) returned {json.dumps(c['result'], ensure_ascii=False)}"
                            for c in row["calls"]) or "(none)"
        return f"{brain_view(case)}\n\nWhat the assistant did:\n{actions}\n\nWhat it said aloud:\n{row['spoken'] or '(silence: it said nothing)'}"
    report = brief.parse(row.get("reply"))
    if not report:
        return None
    heard = str(report.get("say") or "") if report.get("speak", True) else "(it decided to say nothing)"
    return (f"The assistant turned a long report into speech for the owner.\n\n{reader_view(case)}\n\nWhat it said aloud:\n{heard}\n\n"
            f"Whether it told the system the owner is needed: {bool(report.get('waiting'))}")


def reply_key(role: str, case: str, prompt: str) -> str:
    return hashlib.sha256(f"{role}|{case}|{prompt}".encode()).hexdigest()[:20]


def load_rows(path: Path = RAW) -> list[dict]:
    """The last row per key wins: a rerun after an error replaces the error."""
    last = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        last[(r["role"], r["model"], r["case"], r["rep"])] = r
    return list(last.values())


def case_maps():
    return {"brain": {c.name: c for c in bc.BRAIN_CASES}, "reader": {c.name: c for c in bc.READER_CASES}}


async def judge(args) -> None:
    SPENT["limit"], SPENT["phase"] = args.budget, "judge"
    SPENT["total"] = spent_so_far()
    second_judge = args.second
    instrument({JUDGE.split(":")[0], second_judge.split(":")[0]})
    cases = case_maps()
    work: dict[str, tuple] = {}
    rows = [r for tag in args.tags.split(",") for r in load_rows(OUT / f"brain_raw_{tag}.jsonl")] if args.tags else load_rows()
    for row in rows:
        prompt = judge_prompt(row["role"], cases[row["role"]][row["case"]], row)
        if prompt:
            work[reply_key(row["role"], row["case"], prompt)] = prompt
    seen = set()
    if JUDGED.exists():
        for line in JUDGED.read_text().splitlines():
            r = json.loads(line)
            if r.get("score") is not None:
                seen.add((r["judge"], r["key"]))
    keys = sorted(work)
    rnd = random.Random(SEED)
    rnd.shuffle(keys)  # the judge meets replies in an order unrelated to who wrote them
    second = set(keys[:int(len(keys) * SECOND_JUDGE_SHARE)])
    todo = [(JUDGE, k) for k in keys if (JUDGE, k) not in seen] + [(second_judge, k) for k in keys if k in second and (second_judge, k) not in seen]
    print(f"{len(keys)} distinct replies; {len(todo)} judgments to make; spent ${SPENT['total']:.2f}", flush=True)
    gates = {v: asyncio.Semaphore(n) for v, n in PARALLEL.items()}

    async def one(who: str, key: str, out) -> None:
        if SPENT["total"] >= SPENT["limit"]:
            return
        async with gates[who.split(":")[0]]:
            CURRENT.set({"steps": [], "retries": 0, "errors": []})
            score, why = None, ""
            try:
                reply = await vendors.text(who, work[key], JUDGE_SYSTEM, json_reply=True, thinking="low", temperature=0.0)
                parsed = brief.parse(reply)
                score, why = parsed.get("score"), str(parsed.get("why", ""))[:120]
                score = float(score) if isinstance(score, (int, float)) and 1 <= score <= 5 else None
            except Exception as e:
                why = f"error {type(e).__name__}"
            out.write(json.dumps({"judge": who, "key": key, "score": score, "why": why}, ensure_ascii=False) + "\n")
            out.flush()

    with JUDGED.open("a") as out:
        await asyncio.gather(*(one(w, k, out) for w, k in todo))
    print(f"judged; spent ${SPENT['total']:.2f}", flush=True)


# ---------- statistics ----------

def bootstrap_mean(per_case: np.ndarray, rounds: int = 10000, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(per_case), size=(rounds, len(per_case)))
    means = per_case[picks].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired(a: dict, b: dict, rounds: int = 10000) -> dict:
    """a and b: case -> pass fraction. Cases are the unit: repeats of one case are not independent."""
    names = sorted(set(a) & set(b))
    diff = np.array([a[n] - b[n] for n in names])
    low, high = bootstrap_mean(diff, rounds)
    rng = np.random.default_rng(SEED + 1)
    picks = rng.integers(0, len(diff), size=(rounds, len(diff)))
    means = (diff - diff.mean())[picks].mean(axis=1)
    p_boot = float(((np.abs(means) >= abs(diff.mean()) - 1e-12).sum() + 1) / (rounds + 1))
    only_a = sum(a[n] > 0.5 >= b[n] for n in names)
    only_b = sum(b[n] > 0.5 >= a[n] for n in names)
    n = only_a + only_b
    p_mcnemar = min(1.0, 2 * sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2 ** n) if n else 1.0
    return {"diff": float(diff.mean()), "low": low, "high": high, "p_boot": p_boot, "only_a": only_a, "only_b": only_b, "p_mcnemar": p_mcnemar}


def percentile(values: list, q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")


def spearman(a: list, b: list) -> float:
    def ranks(x):
        order = np.argsort(np.argsort(x, kind="stable"), kind="stable").astype(float)
        for value in set(x):  # ties share their mean rank
            where = [i for i, v in enumerate(x) if v == value]
            order[where] = order[where].mean()
        return order
    return float(np.corrcoef(ranks(a), ranks(b))[0, 1])


def summarise(role: str, rows: list[dict], scores: dict) -> dict:
    cases = case_maps()[role]
    score_fn = score_brain if role == "brain" else score_reader
    table = {}
    for model in sorted({r["model"] for r in rows if r["role"] == role}):
        mine = [r for r in rows if r["role"] == role and r["model"] == model]
        per_case: dict[str, list] = {}
        per_case_nolen: dict[str, list] = {}
        judged, gate_trips = [], 0
        classes: dict[str, int] = {}
        for r in mine:
            case = cases[r["case"]]
            fails = score_fn(case, r)
            r["fails"] = fails
            for f in fails:
                name = "no question" if f.startswith("no question") else f.split(":")[0].split(" ")[0]
                classes[name] = classes.get(name, 0) + 1
            if not r.get("error"):
                per_case.setdefault(r["case"], []).append(not fails)
                per_case_nolen.setdefault(r["case"], []).append(not [f for f in fails if not f.startswith("length:")])
            if role == "reader" and not r.get("error"):
                report = brief.parse(r.get("reply"))
                gate_trips += bool(brief.unsupported(f"{report.get('say', '')} {report.get('line', '')}", case.final))
            prompt = judge_prompt(role, case, r)
            s = scores.get(reply_key(role, r["case"], prompt)) if prompt else None
            r["judge"] = s
            if s is not None:
                judged.append((r["case"], s))
        fractions = {c: sum(v) / len(v) for c, v in per_case.items()}
        nolen = {c: sum(v) / len(v) for c, v in per_case_nolen.items()}
        arr = np.array(list(fractions.values()), dtype=float)
        ok = [r for r in mine if not r.get("error") and r["steps"]]
        step_ms = [s["ms"] for r in ok for s in r["steps"]]
        reply_ms = [r["reply_ms"] for r in ok]
        by_case_judge: dict[str, list] = {}
        for c, s in judged:
            by_case_judge.setdefault(c, []).append(s)
        judge_case = np.array([np.mean(v) for v in by_case_judge.values()]) if by_case_judge else np.array([])
        steps = [s for r in ok for s in r["steps"]]
        table[model] = {
            "n": len(mine), "cases": len(fractions), "errors": sum(1 for r in mine if r.get("error")),
            "fallbacks": sum(1 for r in mine if r.get("fallback")), "retries": sum(r["retries"] for r in mine),
            "pass": float(arr.mean()) if len(arr) else float("nan"), "ci": bootstrap_mean(arr) if len(arr) else (float("nan"),) * 2,
            "classes": classes, "nolen_fractions": nolen, "judge_fractions": {c: float(np.mean(v)) for c, v in by_case_judge.items()},
            "unwanted_sends": sum(1 for r in mine if role == "brain" and bc.SEND in cases[r["case"]].rubric.banned and any(c["name"] == bc.SEND for c in r["calls"])),
            "fractions": fractions, "pass_nolen": float(np.mean(list(nolen.values()))) if nolen else float("nan"),
            "nolen_ci": bootstrap_mean(np.array(list(nolen.values()), dtype=float)) if nolen else (float("nan"),) * 2, "gate_trips": gate_trips,
            "words_p50": percentile([words_in(_spoken(role, r)) for r in ok], 50),
            "usd_cold": float(np.mean([sum(_cold(s) for s in r["steps"]) for r in ok])) if ok else float("nan"), "judge": float(judge_case.mean()) if len(judge_case) else float("nan"),
            "judge_ci": bootstrap_mean(judge_case) if len(judge_case) else (float("nan"),) * 2, "judged": len(judged),
            "step_p50": percentile(step_ms, 50), "step_p95": percentile(step_ms, 95),
            "reply_p50": percentile(reply_ms, 50), "reply_p95": percentile(reply_ms, 95),
            "over_10s": float(np.mean([m > REPORT_TIMEOUT_SECS * 1000 for m in reply_ms])) if reply_ms else float("nan"),
            "usd": float(np.mean([r["usd"] for r in ok])) if ok else float("nan"),
            "input": float(np.mean([s["input"] for s in steps])) if steps else 0, "cached": float(np.mean([s["cached"] for s in steps])) if steps else 0,
            "output": float(np.mean([s["output"] for s in steps])) if steps else 0, "thoughts": float(np.mean([s["thoughts"] for s in steps])) if steps else 0,
            "steps_per": len(steps) / len(ok) if ok else float("nan"), "served": sorted({s["served"] for s in steps}),
            "refused": sum(len(r.get("refused") or []) for r in ok),
            "usd_2027": float(np.mean([r["usd"] for r in ok])) * PRICE_2027_FACTOR.get(steps[0]["served"] if steps else "", 1.0) if ok else float("nan"),
            "error_text": sorted({e[:90] for r in mine for e in r.get("errors", [])})[:4],
        }
    return table


def _spoken(role: str, row: dict) -> str:
    if role == "brain":
        return row.get("spoken") or ""
    return str(brief.parse(row.get("reply")).get("say") or "")


def _cold(step: dict) -> float:
    """The step's price with no cache hit at all: what a turn costs after a pause longer than the cache lives."""
    price = PRICES.get(step["served"])
    return (step["input"] * price[0] + (step["output"] + step["thoughts"]) * price[3]) / 1e6 if price else 0.0


def short(model: str) -> str:
    return model.split(":")[1]


def fmt_model(model: str, row: dict) -> str:
    return short(model) + (f" (served {row['served'][0]})" if row["served"] and row["served"][0] != short(model) else "")


def results_table(table: dict) -> list[str]:
    head = ["| Model | Pass (95% CI) | Pass ignoring word limits | Words p50 | Judge 1-5 (95% CI) | Step p50 / p95 s | Reply p50 / p95 s | $ per reply | Steps | Tokens in / cached / out / thinking | Errors | Retries |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for m, r in sorted(table.items(), key=lambda kv: -kv[1]["pass"]):
        rows.append(f"| {fmt_model(m, r)} | {r['pass']:.1%} ({r['ci'][0]:.1%} to {r['ci'][1]:.1%}) | {r['pass_nolen']:.1%} | {r['words_p50']:.0f} | {r['judge']:.2f} ({r['judge_ci'][0]:.2f} to {r['judge_ci'][1]:.2f}) | "
                    f"{r['step_p50'] / 1000:.2f} / {r['step_p95'] / 1000:.2f} | {r['reply_p50'] / 1000:.2f} / {r['reply_p95'] / 1000:.2f} | ${r['usd']:.5f} | {r['steps_per']:.2f} | "
                    f"{r['input']:.0f} / {r['cached']:.0f} / {r['output']:.0f} / {r['thoughts']:.0f} | {r['errors']} | {r['retries']} |")
    return head + rows


def cost_table(table: dict) -> list[str]:
    out = ["| Model | Today (cache as measured) | From 2027-01-01 | No cache hits, today's price |", "|---|---|---|---|"]
    for m, r in sorted(table.items(), key=lambda kv: kv[1]["usd"]):
        out.append(f"| {short(m)} | ${r['usd']:.5f} | ${r['usd_2027']:.5f} | ${r['usd_cold']:.5f} |")
    return out


def category_table(role: str, table: dict) -> list[str]:
    cases = case_maps()[role]
    key = (lambda c: c.cat) if role == "brain" else (lambda c: c.name)
    cats = list(dict.fromkeys(key(c) for c in cases.values()))
    models = sorted(table, key=lambda m: -table[m]["pass"])
    out = ["| " + ("Category" if role == "brain" else "Case") + " | " + " | ".join(short(m) for m in models) + " |", "|---|" + "---|" * len(models)]
    for cat in cats:
        names = [n for n, c in cases.items() if key(c) == cat]
        cells = []
        for m in models:
            vals = [table[m]["fractions"][n] for n in names if n in table[m]["fractions"]]
            cells.append(f"{np.mean(vals):.0%}" if vals else "n/a")
        out.append(f"| {cat} | " + " | ".join(cells) + " |")
    return out


def failure_table(table: dict) -> list[str]:
    names = ["tool", "missing", "forbidden", "language", "length", "spoken", "leak", "promise", "no question", "order", "start", "early", "status", "waiting", "urgency", "questions", "deadlines", "settled", "report", "typed_approval_needed", "send"]
    used = [n for n in names if any(r["classes"].get(n) for r in table.values())]
    out = ["| Model | Replies | " + " | ".join(used) + " | Unwanted sends |", "|---|---|" + "---|" * len(used) + "---|"]
    for m, r in sorted(table.items(), key=lambda kv: -kv[1]["pass"]):
        out.append(f"| {short(m)} | {r['n']} | " + " | ".join(str(r["classes"].get(n, 0)) for n in used) + f" | {r['unwanted_sends']} |")
    return out


def judge_table(rows: list[dict], role: str, scores: dict, second: dict) -> list[str]:
    cases = case_maps()[role]
    pairs: dict[str, list] = {}
    for r in rows:
        if r["role"] != role:
            continue
        prompt = judge_prompt(role, cases[r["case"]], r)
        key = reply_key(role, r["case"], prompt) if prompt else None
        if key in scores and key in second:
            pairs.setdefault(r["model"], []).append((scores[key], second[key]))
    out = [f"| Model | Rows in shared sample | {short(JUDGE)} | {short(SECOND_JUDGE)} |", "|---|---|---|---|"]
    for m, p in sorted(pairs.items()):
        out.append(f"| {short(m)} | {len(p)} | {np.mean([x[0] for x in p]):.2f} | {np.mean([x[1] for x in p]):.2f} |")
    return out


def brain_rule_lines(rows: list[dict]) -> list[str]:
    mine = [r for r in rows if r["role"] == "brain" and not r.get("error")]
    empty: dict[str, int] = {}
    for r in mine:
        if not r.get("spoken"):
            empty[r["case"]] = empty.get(r["case"], 0) + 1
    leaks = [m.group(0).lower() for r in mine for m in LEAK.finditer(r.get("spoken") or "")]
    asked = {"open_decision", "open_background_urgent", "open_clock", "open_permission", "really_nothing", "multi_who_needs", "multi_urgent_first"}
    who = [r for r in mine if r["case"] in asked]
    called = sum(any(c["name"] == "list_sessions" for c in r["calls"]) for r in who)
    refused: dict[str, int] = {}
    for r in mine:
        for reason in r.get("refused") or []:
            head = reason.split(". ", 1)[1][:45] if ". " in reason else reason[:45]
            refused[head] = refused.get(head, 0) + 1
    return [f"- A speak call with empty text, by case: {empty}. Scored as a pass where silence is acceptable; the daemon pushes that empty text to speech.",
            f"- Spoken mentions of internals: {len(leaks)} ({', '.join(sorted(set(leaks)))}).",
            f"- `list_sessions` called before answering who needs the user: {called} of {len(who)} replies.",
            f"- Speech refused by Brain's gates, by reason: {refused}."]


def reader_gate_line(rows: list[dict]) -> str:
    cases = case_maps()["reader"]
    words: dict[str, int] = {}
    for r in rows:
        if r["role"] == "reader" and not r.get("error"):
            report = brief.parse(r.get("reply"))
            for w in brief.unsupported(f"{report.get('say', '')} {report.get('line', '')}", cases[r["case"]].final):
                words[w] = words.get(w, 0) + 1
    top = sorted(words.items(), key=lambda kv: -kv[1])[:10]
    return "Words that trip it most: " + ", ".join(f"{k} ({v})" for k, v in top) + "."


def compare_named(label: str, a: str, b: str, fa: dict, fb: dict, unit: str = "points", scale: float = 100) -> str:
    p = paired(fa, fb)
    return (f"- {label}: {short(a)} minus {short(b)} is {p['diff'] * scale:+.2f} {unit} (95% CI {p['low'] * scale:+.2f} to {p['high'] * scale:+.2f}), paired bootstrap p = {p['p_boot']:.3f}.")


def compare_lines(label: str, table: dict, a: str, b: str) -> str:
    p = paired(table[a]["fractions"], table[b]["fractions"])
    return (f"- {label}: {short(a)} minus {short(b)} is {p['diff'] * 100:+.1f} points (95% CI {p['low'] * 100:+.1f} to {p['high'] * 100:+.1f}), "
            f"paired bootstrap p = {p['p_boot']:.3f}. McNemar on case majority: {p['only_a']} cases only {short(a)}, {p['only_b']} only {short(b)}, exact p = {p['p_mcnemar']:.3f}.")


def distinct(table: dict) -> dict:
    return {m: r for m, r in table.items() if m not in ALIASES}


def shared_failures(role: str, rows: list[dict], table: dict, share: float = 1.0) -> list[dict]:
    """Cases that most distinct models fail: more likely the prompt or the context than any one model."""
    models = list(distinct(table))
    cases = case_maps()[role]
    out = []
    for name in cases:
        rates = {m: table[m]["fractions"].get(name) for m in models}
        known = [v for v in rates.values() if v is not None]
        if not known:
            continue
        failing = sum(v < 0.5 for v in known)
        if len(known) >= 2 and failing >= (len(known) - 1 if share >= 1.0 else math.ceil(len(known) * share)):
            mine = [r for r in rows if r["role"] == role and r["case"] == name and r["model"] in models and r.get("fails")]
            reasons: dict[str, int] = {}
            for r in mine:
                for f in r["fails"]:
                    reasons[f] = reasons.get(f, 0) + 1
            sample = max(mine, key=lambda r: bool(r.get("spoken") or r.get("reply"))) if mine else {}
            out.append({"case": name, "failing": failing, "of": len(known), "mean": float(np.mean(known)),
                        "reasons": sorted(reasons.items(), key=lambda kv: -kv[1])[:3],
                        "sample": sample.get("spoken") or (brief.parse(sample.get("reply")).get("say") if sample.get("reply") else ""),
                        "sample_model": short(sample["model"]) if sample else ""})
    return sorted(out, key=lambda x: x["mean"])


def report(args) -> None:
    rows = load_rows()
    frozen = json.loads(PROMPTS.read_text())
    scores, second = {}, {}
    if JUDGED.exists():
        for line in JUDGED.read_text().splitlines():
            r = json.loads(line)
            if r.get("score") is None:
                continue
            (scores if r["judge"] == JUDGE else second)[r["key"]] = r["score"]
    both = sorted(set(scores) & set(second))
    agreement = (spearman([scores[k] for k in both], [second[k] for k in both]), float(np.mean([abs(scores[k] - second[k]) for k in both])), len(both)) if len(both) > 2 else None
    spend = {}
    if SPEND.exists():
        for line in SPEND.read_text().splitlines():
            r = json.loads(line)
            phase = r["phase"].split(":")[0] if r["phase"].endswith(":main") or r["phase"] == "judge" else "pilot"
            spend[phase] = spend.get(phase, 0) + r["usd"]
    out = [f"# Brain and reader model benchmark, {time.strftime('%Y-%m-%d')}", ""]
    prose = Path(args.prose).read_text() if args.prose else ""
    head, _, tail = prose.partition("<!-- tables -->")
    out += [head.strip(), ""] if head else []
    blocks = {}
    for role in ("brain", "reader"):
        if not any(r["role"] == role for r in rows):
            continue
        table = summarise(role, rows, scores)
        blocks[role] = table
        out += [f"## {role.capitalize()} results", ""]
        out += results_table(table) + [""]
        out += ["Cost per reply, by assumption:", ""] + cost_table(table) + [""]
        if role == "reader":
            out += ["Share of reports slower than the daemon's 10 second limit, past which it speaks an excerpt instead:", ""]
            out += ["- " + ", ".join(f"{short(m)} {r['over_10s']:.1%}" for m, r in sorted(table.items(), key=lambda kv: kv[1]["over_10s"])), ""]
            out += ["Reports that trip `brief.unsupported`, which makes the daemon ask again (a second call): " + ", ".join(f"{short(m)} {r['gate_trips']} of {r['n']}" for m, r in table.items()) + ".", ""]
        else:
            out += ["Speech refused by Brain's own gates and re-asked, per model: " + ", ".join(f"{short(m)} {r['refused']}" for m, r in table.items()) + ".", ""]
        ranked = sorted(distinct(table), key=lambda m: -table[m]["pass"])
        out += ["### Failed checks by kind", ""] + failure_table(table) + [""]
        out += ["### Paired comparisons (cases are the unit)", ""]
        if len(ranked) > 1:
            out.append(compare_lines("Top two on pass rate", table, ranked[0], ranked[1]))
        for alias, target in ALIASES.items():
            if alias in table and target in table:
                out.append(compare_lines("Same model under two names, the noise floor", table, alias, target))
                out.append(compare_named("Same model, judge score", alias, target, table[alias]["judge_fractions"], table[target]["judge_fractions"], "judge points", 1))
        by_nolen = sorted(distinct(table), key=lambda m: -table[m]["pass_nolen"])
        by_judge = sorted(distinct(table), key=lambda m: -table[m]["judge"])
        out.append(compare_named("Top two ignoring word limits", by_nolen[0], by_nolen[1], table[by_nolen[0]]["nolen_fractions"], table[by_nolen[1]]["nolen_fractions"]))
        out.append(compare_named("Top two on judge score", by_judge[0], by_judge[1], table[by_judge[0]]["judge_fractions"], table[by_judge[1]]["judge_fractions"], "judge points", 1))
        if "gemini:gemini-3.8-flash" in table and "anthropic:claude-opus-5-5" in table:
            g, o = "gemini:gemini-3.8-flash", "anthropic:claude-opus-5-5"
            out.append(compare_lines("Fastest-talking against longest-talking leader", table, g, o).replace("Fastest-talking against longest-talking leader", "Gemini 3.8 Flash against Claude Opus 5.5"))
            out.append(compare_named("The same pair ignoring word limits", g, o, table[g]["nolen_fractions"], table[o]["nolen_fractions"]))
        for a, b in (("anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5-5"), ("anthropic:claude-sonnet-5-5", "anthropic:claude-haiku-5-5")):
            if a in table and b in table:
                out.append(compare_lines("Within Anthropic", table, a, b))
        if role == "brain":
            out += ["", "### Rules seen across models", ""] + brain_rule_lines(rows)
        else:
            out += ["", reader_gate_line(rows)]
        out += ["", f"### By {'category' if role == 'brain' else 'case'}", ""] + category_table(role, table) + [""]
        fails = shared_failures(role, rows, table)
        out += ["### Failures shared by at least all but one distinct model", ""]
        for f in fails:
            reasons = "; ".join(f"{k} ({v})" for k, v in f["reasons"])
            out.append(f"- **{f['case']}** ({f['failing']} of {f['of']} models fail, mean pass {f['mean']:.0%}): {reasons}. Example, {f['sample_model']}: \"{(f['sample'] or '')[:220]}\"")
        out += ["" if fails else "None.", ""]
        wider = [f for f in shared_failures(role, rows, table, 0.5) if f["case"] not in {x["case"] for x in fails}]
        if wider:
            out += ["### Failures shared by at least half of the distinct models", ""]
            for f in wider:
                reasons = "; ".join(f"{k} ({v})" for k, v in f["reasons"])
                out.append(f"- **{f['case']}** ({f['failing']} of {f['of']} models fail, mean pass {f['mean']:.0%}): {reasons}. Example, {f['sample_model']}: \"{(f['sample'] or '')[:220]}\"")
            out.append("")
        errors = {m: r["error_text"] for m, r in table.items() if r["error_text"]}
        if errors:
            out += ["### Errors and rate limits seen, including those retried", ""]
            out += [f"- {short(m)}: " + " | ".join(e) for m, e in errors.items()] + [""]
    out += ["## Judge agreement", ""]
    for role in blocks:
        out += [f"Scores on the replies both judges scored, {role}:", ""] + judge_table(rows, role, scores, second) + [""]
    if agreement:
        out += [f"Primary judge {short(JUDGE)}, second judge {short(SECOND_JUDGE)} on a random {SECOND_JUDGE_SHARE:.0%} of distinct replies (n = {agreement[2]}): Spearman {agreement[0]:.2f}, mean absolute difference {agreement[1]:.2f} points.", ""]
    out += ["## Spend", "", "| Phase | USD |", "|---|---|"] + [f"| {k} | ${v:.2f} |" for k, v in sorted(spend.items())] + [f"| total | ${sum(spend.values()):.2f} |", ""]
    out += ["## Reproduce", "", f"Prompts frozen {frozen['frozen_at']} at commit {frozen['git_head']} with uncommitted changes. SHA-256 prefixes: "
            + ", ".join(f"{k} {v}" for k, v in frozen["file_sha256"].items()) + ". Cases as scored: bench/brain_cases.py "
            + hashlib.sha256((ROOT / "bench/brain_cases.py").read_bytes()).hexdigest()[:16] + ".", "",
            "`.venv/bin/python bench/brain_bench.py validate`, then `run --role brain`, `run --role reader`, `judge`, `report`. Raw replies are in `bench/results/brain_raw.jsonl`, scores in `brain_judged.jsonl`, the prompts in `brain_prompts.json`.", ""]
    out += [tail.strip(), ""] if tail else []
    REPORT.write_text("\n".join(out))
    (OUT / "brain_summary.json").write_text(json.dumps(
        {role: {m: {k: v for k, v in r.items() if k != "fractions"} for m, r in t.items()} for role, t in blocks.items()}, indent=1, default=str))
    (OUT / "brain_fractions.json").write_text(json.dumps({role: {m: r["fractions"] for m, r in t.items()} for role, t in blocks.items()}, indent=1))
    print(f"wrote {REPORT.relative_to(ROOT)}")


# ---------- checks on the cases themselves ----------

DENY = re.compile(r"/Users/|\bpointe\b|AIza|\bsk-[a-z0-9]|github\.com|@[a-z]+\.[a-z]+", re.I)


def validate(_args) -> None:
    problems = []
    brain_names = [c.name for c in bc.BRAIN_CASES]
    reader_names = [c.name for c in bc.READER_CASES]
    for names in (brain_names, reader_names):
        if len(set(names)) != len(names):
            problems.append("duplicate names")
    for c in bc.READER_CASES:
        n = len(c.final)
        if not 2000 <= n <= 7000:
            problems.append(f"{c.name}: {n} characters")
    for c in bc.BRAIN_CASES + bc.READER_CASES:
        text = repr(c)
        hit = DENY.search(text)
        if hit:
            problems.append(f"{c.name}: synthetic-data lint hit {hit.group(0)!r}")
    for c in bc.BRAIN_CASES:
        for group in c.rubric.groups + c.rubric.send_groups:
            for rx in group:
                re.compile(rx)
        for rx in c.rubric.forbid:
            re.compile(rx)
    d = load_daemon()
    frozen_system = d.INSTRUCTIONS + d.BRAIN_RULES + brief.REPORT_SYSTEM
    hit = DENY.search(frozen_system)
    if hit:
        print(f"note: the prompt contains {hit.group(0)!r}, and it would be published in brain_prompts.json")
    from sessions import REGISTRY, Session
    mismatches = 0
    for c in bc.BRAIN_CASES:
        REGISTRY.path = None
        REGISTRY.sessions = {}
        REGISTRY.mode = c.mode
        d.state.unconfirmed = {}
        for i, s in enumerate(c.sessions):
            sid = f"s{i}"
            REGISTRY.sessions[sid] = Session(id=sid, name=s.name, cwd="/tmp", pid=1, transcript="", busy=s.busy, brief=s.notes,
                                             open_questions=list(s.waits), deadlines=list(s.clocks), urgency="high" if s.urgent else "normal",
                                             typed_approval=s.typed, permission_id="p" if s.permission else None)
            if s.sent:
                d.state.unconfirmed[sid] = list(s.sent)
        REGISTRY.active_id = f"s{c.active}"
        d.state.last_utterance = c.words
        ours, theirs = bc.right_now(c, brief.render_brief), d._brain_context()
        if ours != theirs:
            mismatches += 1
            if mismatches == 1:
                print("first format mismatch:\n--- ours\n" + ours + "\n--- daemon\n" + theirs)
    print(f"{len(bc.BRAIN_CASES)} brain cases, {len(bc.READER_CASES)} reader cases, "
          f"reader lengths {min(len(c.final) for c in bc.READER_CASES)} to {max(len(c.final) for c in bc.READER_CASES)} characters")
    print(f"categories: {sorted(set(c.cat for c in bc.BRAIN_CASES))}")
    print(f"format against daemon._brain_context: {mismatches} mismatches")
    print("problems: " + ("; ".join(problems) if problems else "none"))
    if problems or mismatches:
        raise SystemExit(1)


def substance(args) -> None:
    """Ranks by what was said and done, then by the judge; speed is reported and does not rank."""
    scores, second = {}, {}
    for line in JUDGED.read_text().splitlines():
        r = json.loads(line)
        if r.get("score") is not None:
            (scores if r["judge"] == JUDGE else second if r["judge"] == args.second else {})[r["key"]] = r["score"]
    both = sorted(set(scores) & set(second))
    lines = []
    for role in ("brain", "reader"):
        table = []
        for tag in args.tags.split(","):
            rows = [r for r in load_rows(OUT / f"brain_raw_{tag}.jsonl") if r["role"] == role]
            for model, s in summarise(role, rows, scores).items():
                mine = [r for r in rows if r["model"] == model]
                steps = [st["ms"] for r in mine for st in r["steps"]]
                substance_fails = sum(n for k, n in s["classes"].items() if k != "length")
                table.append((s["pass_nolen"], s["judge"], f"{model.split(':')[1]} ({tag})", s, substance_fails,
                              sum(m > 8000 for m in steps) / max(len(steps), 1)))
        table.sort(key=lambda t: (-t[0], -(t[1] if t[1] == t[1] else 0)))
        lines += [f"### {role.capitalize()}", "",
                  "| Model (run) | Pass ignoring length (95% CI) | Failures of substance | Unwanted sends | Judge 1-5 (95% CI) | Pass with length | Reply p50 / p95 s | Steps over 8 s | $ per reply | Errors |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for nolen, judged, name, s, fails, slow in table:
            lines.append(f"| {name} | {nolen:.1%} ({s['nolen_ci'][0]:.1%} to {s['nolen_ci'][1]:.1%}) | {fails} of {s['n']} | {s['unwanted_sends']} | "
                         f"{judged:.2f} ({s['judge_ci'][0]:.2f} to {s['judge_ci'][1]:.2f}) | {s['pass']:.1%} | {s['reply_p50'] / 1000:.1f} / {s['reply_p95'] / 1000:.1f} | "
                         f"{slow:.1%} | ${s['usd']:.4f} | {s['errors']} |")
        lines.append("")
    if len(both) > 2:
        lines.append(f"Judges: {JUDGE} on every distinct reply, {args.second} on a sample (n = {len(both)}): Spearman "
                     f"{spearman([scores[k] for k in both], [second[k] for k in both]):.2f}.")
    Path(args.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> None:
    logger.remove()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    run_p = sub.add_parser("run")
    run_p.add_argument("--role", choices=["brain", "reader"], required=True)
    run_p.add_argument("--models", default="")
    run_p.add_argument("--cases", default="")
    run_p.add_argument("--repeats", type=int, default=3)
    run_p.add_argument("--tag", default="main")
    run_p.add_argument("--rerun", action="store_true", help="replace existing rows for these cases: the last row per key wins")
    run_p.add_argument("--budget", type=float, default=25.0)
    run_p.add_argument("--step-timeout", type=float, default=60.0)
    run_p.add_argument("--reader-thinking", default="low")
    judge_p = sub.add_parser("judge")
    judge_p.add_argument("--budget", type=float, default=25.0)
    judge_p.add_argument("--tags", default="", help="judge these runs instead of the main one")
    judge_p.add_argument("--second", default=SECOND_JUDGE)
    substance_p = sub.add_parser("substance")
    substance_p.add_argument("--tags", required=True)
    substance_p.add_argument("--second", default=SECOND_JUDGE)
    substance_p.add_argument("--out", default=str(OUT / "brain_substance.md"))
    report_p = sub.add_parser("report")
    report_p.add_argument("--prose", default=str(OUT / "brain_prose.md"))
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.command == "validate":
        validate(args)
    elif args.command == "run":
        asyncio.run(run(args))
    elif args.command == "judge":
        asyncio.run(judge(args))
    elif args.command == "substance":
        substance(args)
    else:
        if args.prose and not Path(args.prose).exists():
            args.prose = ""
        report(args)


if __name__ == "__main__":
    main()
