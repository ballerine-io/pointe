"""The voice daemon of a fleet run: daemon.py as it runs, on a throwaway state folder and ports the run chose, with
every model call written down as it is made. bench/fleet/sim.py starts it; nothing else should.

    python -I bench/fleet/voice.py <port>      CLAUDE_VOICE_STATE, CLAUDE_VOICE_TLS_PORT and the POINTE_BENCH_* below
                                               are set by the run

POINTE_BENCH_MODELS=stub   No vendor is called and no key is read: the brain is a few rules ("tell <name> to <task>"
                           becomes one send; a session's finished turn becomes one spoken line), the reader and the
                           checker answer with fixed words. For the offline self-test and for counts that do not depend
                           on what a model says (reader calls).
POINTE_BENCH_MODELS=real   The real brain, reader and checker. Their keys are read by this process alone, from the
                           macOS Keychain, the way the daemon reads them (vendors.from_keychain: /usr/bin/security),
                           and stay in its memory: never in an environment, a file, a command line or a log. Only the
                           Anthropic and Gemini keys are read: no speech vendor can be called. The daemon's HOME is a
                           throwaway folder, so the Keychain is searched under POINTE_BENCH_KEY_HOME instead.
POINTE_BENCH_CALLS         A JSONL file: a "begin" line as each model call starts and one line as it ends
                           (vendors.step, vendors.text) with its times, the vendor's own token counts where the vendor
                           gives them, and the size of what was sent.
POINTE_BENCH_CHECKOUT      The Pointe checkout whose pointe/ runs (default: the one this file is in).
POINTE_BENCH_NEEDS         A regular expression that finds the first line of the "what each session needs" block in
                           the brain's context (the block runs from there to the end of that message).

Two things differ from a person's call, and nothing else: the call has no ears (words are typed; see install()), and
it is opened in reading mode, so replies are shown and never synthesised. The wrappers around the model calls call the
daemon's own functions and write a line.
"""

import asyncio
import contextvars
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# The Pointe under test: this checkout, or another one (an arm measured at another commit).
ROOT = Path(os.environ.get("POINTE_BENCH_CHECKOUT") or Path(__file__).resolve().parents[2])
LIVE_PORTS = {7860, 7443}
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
MODELS = os.environ.get("POINTE_BENCH_MODELS", "stub")
CALLS = Path(os.environ.get("POINTE_BENCH_CALLS") or STATE.parent / "calls.jsonl")
NEEDS = re.compile(os.environ.get("POINTE_BENCH_NEEDS") or r"^\[[^\n]*What each session needs right now", re.M)
REAL_VENDORS = ("anthropic", "gemini")  # the brain and the reader; the checker
USAGE: contextvars.ContextVar = contextvars.ContextVar("fleet_bench_usage", default=None)  # the call now being counted


def count_clients(vendors) -> None:
    """The vendors' own token counts for calls that return only text (the reader, the checker): each client's request
    method is wrapped once, and writes the reply's usage into the row of the call that made it. A step that streams
    is not seen here: its row has the counts the daemon itself reads (vendors.Step.usage)."""
    anthropic_client, gemini_client = vendors._anthropic, vendors._gemini

    def anthropic():
        client = anthropic_client()
        if not getattr(client.messages, "_fleet_bench", False):
            create = client.messages.create

            async def counted(*a, **k):
                resp = await create(*a, **k)
                if (box := USAGE.get()) is not None:
                    u = resp.usage
                    box.update(input=u.input_tokens, cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                               cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0, output=u.output_tokens)
                return resp

            client.messages.create, client.messages._fleet_bench = counted, True
        return client

    def gemini():
        client = gemini_client()
        models = client.aio.models
        if not getattr(models, "_fleet_bench", False):
            generate = models.generate_content

            async def counted(*a, **k):
                resp = await generate(*a, **k)
                if (box := USAGE.get()) is not None and (u := getattr(resp, "usage_metadata", None)) is not None:
                    box.update(input=getattr(u, "prompt_token_count", 0) or 0, cache_read=getattr(u, "cached_content_token_count", 0) or 0,
                               output=(getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0))
                return resp

            models.generate_content, models._fleet_bench = counted, True
        return client

    vendors._anthropic, vendors._gemini = anthropic, gemini


def needs_block(messages: list[dict]) -> str:
    """The "what each session needs" block the brain was last given: from its first line to the end of that message.
    "" when no message has one."""
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str) and (found := NEEDS.search(m["content"])):
            return m["content"][found.start():]
    return ""


def trigger(messages: list[dict]) -> dict:
    """What a step answers: the newest message that is not the daemon's "[right now]" line."""
    for m in reversed(messages):
        if m.get("role") == "user" and str(m.get("content", "")).lstrip().startswith("[right now]"):
            continue
        return m
    return {}


def sent_chars(system: str | None, messages: list, tools: list | None = None) -> int:
    return len(system or "") + len(json.dumps(messages, ensure_ascii=False, default=str)) + len(json.dumps(tools or [], default=str))


def write(row: dict) -> None:
    with CALLS.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _stub_step(vendors, messages: list[dict]):
    """The brain as a few rules. It decides nothing a model would: enough for the daemon's own code to run."""
    last = trigger(messages)
    call = lambda name, **args: {"id": f"stub-{time.time_ns()}", "name": name, "args": args}  # noqa: E731
    if last.get("role") == "tool":
        failed = any("error" in (r.get("result") or {}) for r in last["results"] if isinstance(r.get("result"), dict))
        calls = [call("speak", text="I could not send that." if failed else "Sent.")]
    else:
        text = str(last.get("content") or "")
        own = text.rsplit("These are their own words:]\n", 1)[-1].strip()
        told = re.match(r"^(?:tell|ask)\s+(?P<who>.+?)\s+to\s+(?P<task>.+)$", own, re.I | re.S)
        if own.startswith("["):  # a line from the daemon: a report, a join, the call's opening
            line = re.sub(r"^\[[^\]]*\]\s*", "", own).split("\n")[-1][:160]
            calls = [call("speak", text=line or "Okay.")]
        elif told:
            calls = [call("send_to_claude_code", message=told["task"].strip().rstrip("."),
                          session=re.sub(r"\s+on\s+", " ", told["who"]).strip())]
        else:
            calls = [call("speak", text="Okay.")]
    return vendors.Step(calls, None, "", {"context": sent_chars(None, messages) // 4, "cached": 0, "reply": 20})


STUB_REPORT = {"status": "done", "urgency": "normal", "verdict": "done", "limits": [], "recommendation": "",
               "questions": [], "settled": [], "orders_confirmed": [], "deadlines": [], "typed_approval_needed": "",
               "waiting": False, "need": "", "unblock": "", "speak": True, "say": "It finished.", "line": "It finished."}
STUB_NOTES = {"goal": "The work its record states.", "state": "As its record's last lines say.", "decisions": [],
              "ruled_out": [], "open": [], "waiting_on_user": "", "waiting_on_others": [], "owner_promised": [],
              "next_move": "", "people_and_names": []}


def _stub_text(prompt: str, system: str | None, json_reply: bool) -> str:
    if not json_reply:
        return "unclear" if "Which session is this request about?" in prompt else "yes"
    return json.dumps(STUB_NOTES if "working notes" in (system or "") else STUB_REPORT)


def install() -> None:
    assert ".claude-voice" not in str(STATE) and str(STATE).startswith(("/tmp/", "/private/tmp/")), "never the live state"
    sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
    import vendors

    if MODELS == "stub":
        vendors._stored = lambda vendor, keep=True: f"made-up-{vendor}-key"  # these keys reach nothing
        vendors.warm = lambda choices: None
    else:
        assert MODELS == "real" and not (set(os.environ) & vendors.KEY_ENVS), "no key in this process's environment"
        key_home = os.environ["POINTE_BENCH_KEY_HOME"]
        import childenv

        def from_store(name: str, timeout: float = 5) -> str | None:
            """vendors.from_keychain with the Keychain's own HOME, and only for the vendors this run may call."""
            if name.removeprefix("pointe.").removesuffix("-api-key") not in REAL_VENDORS:
                return None
            got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", name, "-w"], capture_output=True,
                                 text=True, timeout=timeout, env={**childenv.child_env(), "HOME": key_home})
            return (got.stdout.strip() or None) if got.returncode == 0 else None

        vendors.from_store = from_store
        count_clients(vendors)

    inner_step, inner_text = vendors.step, vendors.text
    counted: dict[str, int] = {}  # the block's hash -> its tokens, as the vendor counts them

    async def count_needs(block: str, digest: str) -> None:
        """The block's tokens by the brain vendor's own counter (free), once per distinct block: as one user message,
        so a few tokens of framing are in the figure."""
        try:
            got = await vendors._anthropic().messages.count_tokens(
                model=daemon.setup().brain.split(":", 1)[1], messages=[{"role": "user", "content": block}])
            counted[digest] = got.input_tokens
            write({"kind": "needs_tokens", "sha": digest, "tokens": got.input_tokens, "chars": len(block), "at": time.time()})
        except Exception as e:  # counted by characters in the report instead, and said so
            write({"kind": "needs_tokens", "sha": digest, "tokens": None, "chars": len(block), "at": time.time(),
                   "error": type(e).__name__})

    serial = iter(range(1, 1 << 62))

    async def step(choice: str, system: str, messages: list[dict], tools: list[dict], heard=None):
        began, first, n = time.time(), [None], next(serial)
        write({"kind": "begin", "n": n, "of": "step", "began": began})
        block = needs_block(messages)
        digest = hashlib.sha256(block.encode()).hexdigest()[:16] if block else ""
        if block and digest not in counted:
            counted[digest] = -1
            if MODELS == "real" and choice.startswith("anthropic:"):
                asyncio.ensure_future(count_needs(block, digest))
            else:
                write({"kind": "needs_tokens", "sha": digest, "tokens": None, "chars": len(block), "at": time.time()})

        def hear(text):
            if first[0] is None:
                first[0] = time.time()
            heard(text)

        answers = trigger(messages)
        row = {"kind": "step", "n": n, "choice": choice, "began": began, "streamed": heard is not None,
               "sent_chars": sent_chars(system, messages, tools), "messages": len(messages), "needs_sha": digest,
               "needs_chars": len(block),
               "answers": (str(answers.get("content") or "")[-200:] if answers.get("role") == "user" else answers.get("role", ""))}
        exact: dict = {}
        USAGE.set(exact)  # a step that does not stream goes through the counted client
        try:
            if MODELS == "stub":
                await asyncio.sleep(0.05)
                result = _stub_step(vendors, messages)
                result.vendor = choice.split(":")[0]
                if heard is not None:
                    hear("")
            else:
                result = await inner_step(choice, system, messages, tools, **({"heard": hear} if heard is not None else {}))
        except BaseException as e:
            write({**row, "ended": time.time(), "first": first[0], "error": type(e).__name__})
            raise
        write({**row, "ended": time.time(), "first": first[0], "usage": result.usage, **({"exact": exact} if exact else {}),
               "calls": [{"name": c["name"], "args": c["args"]} for c in result.calls], "said": result.said[:400]})
        return result

    async def _text(caller: str, choice: str, prompt: str, system: str | None, kw: dict) -> str:
        began, n = time.time(), next(serial)
        write({"kind": "begin", "n": n, "of": "text", "began": began})
        row = {"kind": "text", "n": n, "caller": caller, "choice": choice, "began": began, "thinking": kw.get("thinking"),
               "sent_chars": len(prompt) + len(system or "")}
        exact: dict = {}
        USAGE.set(exact)
        try:
            if MODELS == "stub":
                await asyncio.sleep(0.02)
                reply = _stub_text(prompt, system, bool(kw.get("json_reply")))
            else:
                reply = await inner_text(choice, prompt, system, **kw)
        except BaseException as e:
            write({**row, "ended": time.time(), "error": type(e).__name__})
            raise
        write({**row, "ended": time.time(), "reply_chars": len(reply or ""), **({"exact": exact} if exact else {})})
        return reply

    def text(choice: str, prompt: str, system: str | None = None, *args, **kw):
        if args:  # positional json_reply, thinking, max_tokens, temperature
            kw = {**dict(zip(("json_reply", "thinking", "max_tokens", "temperature"), args)), **kw}
        return _text(sys._getframe(1).f_code.co_name, choice, prompt, system, kw)

    vendors.step, vendors.text = step, text
    import harnesses.claude_code

    harnesses.claude_code.ROSTER = False  # never this machine's real `claude agents --json`
    harnesses.claude_code.DEFAULT_HOME = STATE / "claude-home"
    harnesses.claude_code.MANAGED_SETTINGS = STATE / "managed-settings.json"
    import mac

    mac.SYSTEM = False
    import daemon

    daemon.COPY_SESSIONS = False
    # No ears: the user's words are typed (/voice/say), so no recognizer is built and no speech vendor is dialled.
    # This is the daemon's own branch for a call without ears of its own (CLAUDE_VOICE_EARS=native), taken here with
    # the brain front, which that setting does not allow by itself.
    daemon._call_ears = lambda terms=None: ([], [], None)
    return daemon


if __name__ == "__main__":
    port = sys.argv[1]
    assert int(port) not in LIVE_PORTS and int(os.environ["CLAUDE_VOICE_TLS_PORT"]) not in LIVE_PORTS, "never the live daemon"
    daemon = install()
    sys.argv = ["daemon.py", "--port", port]
    daemon.main()
