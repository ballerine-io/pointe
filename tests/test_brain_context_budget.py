"""The brain's input stays bounded on a long call. From a live run: the history grew to 350k tokens (62 copies of the
[right now] block and twenty full final messages made three quarters of it), each step slowed with it until both models
passed the 8 s timeout, and the user heard "I lost my connection to the model" four times in two minutes. Synthetic text
throughout."""

import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brain as brain_mod  # noqa: E402
import vendors  # noqa: E402
from brain import Brain  # noqa: E402

random.seed(11)
WORDS = "the poller retry window ledger index queue option staging friday webhook drill cutover schema branch suite".split()


def prose(chars: int) -> str:
    out = []
    while sum(len(s) + 1 for s in out) < chars:
        out.append(" ".join(random.choice(WORDS) for _ in range(random.randint(8, 18))).capitalize() + ".")
    return " ".join(out)[:chars]


class Tool:
    def __init__(self, name, result):
        self.name, self.description, self.properties, self.required, self.result = name, "", {}, [], result

    async def handler(self, params):
        await params.result_callback(self.result)


def _valid(messages: list[dict]) -> bool:
    """What every vendor requires of a replay: it starts with the user, and each call has its results right after it."""
    if not messages or messages[0]["role"] != "user":
        return False
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("calls"):
            nxt = messages[i + 1] if i + 1 < len(messages) else None
            if not nxt or nxt["role"] != "tool" or {r["id"] for r in nxt["results"]} != {c["id"] for c in m["calls"]}:
                return False
        if m["role"] == "tool" and (i == 0 or messages[i - 1]["role"] != "assistant"):
            return False
    return True


def _long_call(monkeypatch, turns: int, usage=None):
    """A call of `turns` turns: a changing [right now] block, a full final message every third turn, a tool call on most
    turns, big results. Returns the brain and the history every step was sent."""
    blocks = [f"[right now] The user's latest words are in English.\nActive session: lantern.\n{prose(1800)}" for _ in range(6)]
    now = {"i": 0}
    seen, plan, spoken = [], [], []

    async def step(_choice, _system, messages, _tools):
        seen.append([{k: v for k, v in m.items()} for m in messages])
        tokens = usage(len(_system) + len(json.dumps(_tools)) + sum(map(Brain._chars, messages))) if usage else {}
        return vendors.Step(plan.pop(0), raw={"vendor": "state"}, vendor="gemini", usage=tokens)

    async def speak(text):
        spoken.append(text)

    monkeypatch.setattr(vendors, "step", step)
    tools = [Tool("list_sessions", {"sessions": [{"name": f"s{i}", "latest": prose(300)} for i in range(4)]}),
             Tool("ask_about_session", {"session": "lantern", "answer": prose(700)}),
             Tool("send_to_claude_code", {"sent_to": ["lantern"]})]
    b = Brain("gemini:x", prose(13_000), tools, lambda: blocks[now["i"] % len(blocks)], speak, may_stay_silent=lambda: False)

    async def run():
        for i in range(turns):
            now["i"] = i
            if i % 3 == 0:
                b.add_news("[lantern: claude-code's full final message: the source for any follow-up. Do not read it out]\n" + prose(7800))
                plan.append([{"id": f"s{i}", "name": "speak", "args": {"text": prose(60)}}])
                await b.turn("[lantern: claude-code finished its turn. Tell the user this:]\n" + prose(600))
            tool = ("list_sessions", "ask_about_session", "send_to_claude_code", None)[i % 4]
            if tool:
                plan.append([{"id": f"t{i}", "name": tool, "args": {"question": "why"}}])
            plan.append([{"id": f"s{i}b", "name": "speak", "args": {"text": prose(70)}}])
            await b.turn(prose(60))

    asyncio.run(run())
    return b, seen, spoken


def test_a_long_call_with_big_results_stays_under_the_budget(monkeypatch):
    b, seen, spoken = _long_call(monkeypatch, turns=300)
    assert len(spoken) >= 390 and len(seen) > 600  # a few replies lose a sentence to the repeat filter
    # A step inside a turn adds one result to a history trimmed at the turn's start: that is the most any step sees.
    slack = (brain_mod.MAX_RESULT_CHARS + 2000) / brain_mod.CHARS_PER_TOKEN
    worst = max(sum(map(Brain._chars, h)) / brain_mod.CHARS_PER_TOKEN for h in seen)
    assert worst <= brain_mod.HISTORY_TOKENS + slack, worst
    assert b.history_tokens() <= brain_mod.HISTORY_TOKENS
    assert len(b.messages) < brain_mod.MAX_MESSAGES
    b.append("and now?")
    monkeypatch.setattr(brain_mod, "HISTORY_TOKENS", 1000)
    b._trim()  # a trim: every replaced [right now] block before the newest turns goes, whatever the total
    blocks = [m["content"] for m in b.messages if m["role"] == "user" and m["content"].startswith("[right now]")]
    assert blocks and len(blocks) <= 4, len(blocks)
    assert blocks[-1] == b._given, "the newest block stays: it is the truth until the next"
    assert all(len(m["content"]) < 2000 for m in b.messages if m["role"] == "user" and m["content"].startswith("[right now]"))
    finals = [m["content"] for m in b.messages if m["role"] == "user" and "full final message" in m["content"]]
    assert len(finals[-1]) > 7000, "the latest report stays whole, for follow-up questions"
    assert all(len(f) < 400 and f.endswith(brain_mod.OLD_NEWS) for f in finals[:-2]), "older reports keep their first line"
    old = [r["result"] for m in b.messages[:len(b.messages) // 2] if m["role"] == "tool" for r in m["results"] if r["name"] == "list_sessions"]
    assert old and all(r == brain_mod.OLD_RESULT for r in old)


def test_the_history_every_step_sees_is_valid_after_trimming(monkeypatch):
    b, seen, _ = _long_call(monkeypatch, turns=120)
    assert all(_valid(h) for h in seen)
    assert _valid(b.messages)
    assert any("raw" in m for m in b.messages), "turns since the last trim keep their vendor state"
    monkeypatch.setattr(brain_mod, "HISTORY_TOKENS", 1000)
    b.append("and now?")  # a turn's start: the trim runs only there
    b._trim()
    assert _valid(b.messages) and len(b.messages) > 2
    assert not any("raw" in m for m in b.messages), "an edited replay carries no vendor state"


def test_without_a_trim_the_same_call_grows_past_the_budget(monkeypatch):
    monkeypatch.setattr(brain_mod, "HISTORY_TOKENS", 10**9)
    monkeypatch.setattr(brain_mod, "MAX_MESSAGES", 10**9)
    b, _, _ = _long_call(monkeypatch, turns=120)
    assert b.history_tokens() > 3 * 24_000, "the fixture is heavy enough to make the budget do the work"


def test_the_trim_waits_for_a_pending_result(monkeypatch):
    steps = [vendors.Step([{"id": "a", "name": "list_sessions", "args": {}}], raw={"keep": 1}, vendor="gemini"),
             vendors.Step([{"id": "b", "name": "speak", "args": {"text": "Four sessions."}}], vendor="gemini")]
    seen = []

    async def step(_c, _s, messages, _t):
        seen.append([dict(m) for m in messages])
        return steps.pop(0)

    async def speak(_t):
        pass

    monkeypatch.setattr(vendors, "step", step)
    monkeypatch.setattr(brain_mod, "HISTORY_TOKENS", 300)
    monkeypatch.setattr(brain_mod, "HISTORY_AFTER_TRIM", 200)
    monkeypatch.setattr(brain_mod, "RECENT_TOKENS", 100)
    b = Brain("gemini:x", "s", [Tool("list_sessions", {"sessions": prose(3000)})], lambda: "[right now] x", speak)
    for _ in range(4):
        b.append("[news] " + prose(400))
    asyncio.run(b.turn("who is waiting"))
    assert "raw" in seen[1][-2] and seen[1][-2]["role"] == "assistant", "the pending call keeps its vendor state"
    assert sum(map(Brain._chars, seen[1])) > sum(map(Brain._chars, seen[0])), "no trim between a call and its result"
    assert len(seen[1]) == len(seen[0]) + 2


def test_the_vendors_own_count_corrects_the_budget(monkeypatch):
    """A vendor that counts two characters per token (Hebrew, roughly) must see the same token budget, not twice it."""
    dense, seen, _ = _long_call(monkeypatch, turns=90, usage=lambda chars: {"context": chars // 2})
    assert 1.9 < dense._chars_per_token < 2.1
    slack = (brain_mod.MAX_RESULT_CHARS + 2000) / 2
    assert max(sum(map(Brain._chars, h)) / 2 for h in seen) <= brain_mod.HISTORY_TOKENS + slack
    guessed = brain_mod.HISTORY_TOKENS * brain_mod.CHARS_PER_TOKEN / 2
    assert any(sum(map(Brain._chars, h)) / 2 > 0.8 * guessed for h in seen) is False, \
        "with the 3.5 guess alone the history would have reached the vendor's budget 1.75 times over"


def test_one_oversized_item_or_result_is_capped(monkeypatch):
    steps = [vendors.Step([{"id": "a", "name": "list_sessions", "args": {}}]), vendors.Step([{"id": "b", "name": "speak", "args": {"text": "Done."}}])]

    async def step(_c, _s, _m, _t):
        return steps.pop(0)

    async def speak(_t):
        pass

    monkeypatch.setattr(vendors, "step", step)
    b = Brain("gemini:x", "s", [Tool("list_sessions", {"sessions": prose(30_000)})], lambda: "[right now] x", speak)
    b.append("[a report] " + prose(40_000))
    assert len(b.messages[0]["content"]) <= brain_mod.MAX_ITEM_CHARS + 10 and b.messages[0]["content"].endswith("[…cut]")
    asyncio.run(b.turn("list them"))
    result = next(r["result"] for m in b.messages if m["role"] == "tool" for r in m["results"] if r["name"] == "list_sessions")
    assert result["cut"] and len(result["result"]) <= brain_mod.MAX_RESULT_CHARS + 1


def test_a_slow_model_is_not_called_a_lost_connection(monkeypatch):
    said = []

    async def speak(text):
        said.append(text)

    async def slow(*_a):
        raise TimeoutError("gemini:x timed out")

    async def gone(*_a):
        raise ConnectionError("connection reset")

    monkeypatch.setattr(vendors, "step", slow)
    asyncio.run(Brain("gemini:x", "s", [], lambda: "[right now] x", speak).turn("hello"))
    monkeypatch.setattr(vendors, "step", gone)
    asyncio.run(Brain("gemini:x", "s", [], lambda: "[right now] x", speak).turn("hello"))
    assert said == [brain_mod.SLOW_LINE, brain_mod.LOST_LINE]
    assert "connection" not in brain_mod.SLOW_LINE


def test_anthropic_steps_carry_the_two_cache_markers_and_count_the_whole_prompt(monkeypatch):
    sent = {}

    class Messages:
        async def create(self, **kwargs):
            sent.update(kwargs)
            block = SimpleNamespace(type="tool_use", id="c1", name="speak", input={"text": "hi"})
            return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=120, cache_read_input_tokens=9000,
                                                                          cache_creation_input_tokens=700, output_tokens=30))

    monkeypatch.setattr(vendors, "_anthropic", lambda: SimpleNamespace(messages=Messages()))
    history = [{"role": "user", "content": "[right now] x"},
               {"role": "assistant", "calls": [{"id": "c0", "name": "speak", "args": {"text": "yes"}}], "vendor": "anthropic"},
               {"role": "tool", "results": [{"id": "c0", "name": "speak", "result": "spoken"}]},
               {"role": "user", "content": "go on"}]
    step = asyncio.run(vendors.step("anthropic:claude-sonnet-5-5", "system", history, [brain_mod.SPEAK]))
    assert sent["cache_control"] == {"type": "ephemeral"}, "the automatic marker: each step reads the steps before it"
    assert sent["system"][-1]["cache_control"] == {"type": "ephemeral"}, "tools and prompt stay cached whatever the history does"
    assert "cache_control" not in json.dumps(sent["messages"]), "no fixed marker in the history: the automatic one moves"
    assert step.usage == {"context": 120 + 9000 + 700, "cached": 9000, "reply": 30}


def test_alive_never_runs_ps_on_the_loop_and_probe_runs_it_in_a_thread(monkeypatch):
    from harnesses import claude_code

    calls = []

    def slow_ps(pid):
        calls.append(pid)
        time.sleep(0.3)
        return "Z\n"

    monkeypatch.setattr(claude_code, "_stat_of", slow_ps)
    cc = claude_code.ClaudeCode()
    me = SimpleNamespace(pid=os.getpid())
    started = time.monotonic()
    assert cc.alive(me) and time.monotonic() - started < 0.05 and not calls, "alive() answers from the last probe, never ps"
    assert not cc.alive(SimpleNamespace(pid=0))

    async def probe_while_ticking():
        ticks = []

        async def tick():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        ticker = asyncio.ensure_future(tick())
        await cc.probe(me)
        ticker.cancel()
        return ticks

    ticks = asyncio.run(probe_while_ticking())
    assert len(ticks) >= 10 and max(b - a for a, b in zip(ticks, ticks[1:])) < 0.15, "the loop kept turning while ps ran"
    assert calls == [me.pid] and not cc.alive(me), "a zombie per the probe is gone"
    monkeypatch.setattr(claude_code, "_stat_of", lambda pid: "S+\n")
    asyncio.run(cc.probe(me))
    assert cc.alive(me)
