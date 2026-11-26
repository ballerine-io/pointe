"""The agents proof (docs/design/agents.md): a real voice daemon (bench/agents/voice.py: the real brain, no microphone)
talks to a real OpenClaw and a real Hermes Agent, text turn by text turn, and the whole conversation is written down.

    python3 bench/agents/live.py <evidence folder> [--openclaw URL] [--hermes URL]

The agents run outside this script (the agents lab: official images, loopback ports). Their credentials are named here
by Keychain item and read by the voice process only. The daemon runs on a throwaway /tmp state folder and free ports,
never the live Pointe's. The scenario:

  1 orchestrated: "ask openclaw ..." -> its reply is reported
  2 async: "ask hermes ..." and the call hangs up before the reply; the reply waits in "what needs me"; the next call
    hears it, and "what did hermes say?" is answered
  3 1:1: "talk to hermes", two turns go there, "orchestrator mode"
  4 relay with a spoken yes: "give hermes's answer to openclaw" -> read back -> "yes" -> openclaw gets it, marked
  5 relay refused: "send openclaw's answer to hermes" -> read back -> "no" -> nothing reaches hermes
  6 an approval: openclaw asks to run a command -> read out -> "no" -> denied
"""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[0:0] = [str(ROOT / "tests")]
from fleet import LIVE_PORTS, Daemon, until  # noqa: E402

VOICE = Path(__file__).resolve().parent / "voice.py"


class Voice(Daemon):
    def __init__(self, root: Path, secrets: dict[str, str], calls: Path):
        super().__init__(root, "studio", "Dana")
        self.secrets, self.calls = secrets, calls

    def env(self) -> dict:
        env = super().env()
        env.pop("GOOGLE_API_KEY", None)
        env.update(CLAUDE_VOICE_FRONT="brain", CLAUDE_VOICE_NO_BROWSER="1", POINTE_AGENTS="on",
                   POINTE_AGENTS_KEY_HOME=str(Path.home()), POINTE_AGENTS_CALLS=str(self.calls),
                   POINTE_AGENTS_SECRETS=",".join(f"{k}={v}" for k, v in self.secrets.items()))
        return env

    def launch(self) -> None:
        assert not {self.port, self.tls_port} & LIVE_PORTS
        log = (self.state.parent / f"{self.name}.log").open("a")
        import subprocess

        self.proc = subprocess.Popen([sys.executable, "-I", str(VOICE), str(self.port)], env=self.env(),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


class Call:
    """The page's side of a call with no audio, in reading mode: replies are shown, never synthesised."""

    def __init__(self, voice: Voice):
        self.voice, self.connected, self.failed = voice, threading.Event(), None
        self._stop = self._loop = None
        self._thread = threading.Thread(target=lambda: asyncio.run(self._hold()), daemon=True)

    async def _hold(self) -> None:
        from websockets.asyncio.client import connect

        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        try:
            async with connect(f"ws://127.0.0.1:{self.voice.port}/voice/call?reading=1", max_size=None,
                               additional_headers={"Authorization": f"Bearer {self.voice.token}"}) as ws:
                self.connected.set()
                reader = asyncio.ensure_future(self._drain(ws))
                await self._stop.wait()
                reader.cancel()
        except Exception as e:
            self.failed = f"{type(e).__name__}: {e}"
            self.connected.set()

    @staticmethod
    async def _drain(ws) -> None:
        async for _ in ws:
            pass

    def open(self) -> "Call":
        self._thread.start()
        assert self.connected.wait(30) and not self.failed, self.failed
        until("the voice has the call", lambda: self.voice.status().get("connected"), 30)
        return self

    def close(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(10)
        until("the call is down", lambda: not self.voice.status().get("connected"), 30)


class Transcript:
    """Every turn the daemon shows (/voice/status talk), by id, with when it was first seen; and the events of the run."""

    def __init__(self, voice: Voice, out: Path):
        self.voice, self.out = voice, out
        self.turns: dict[int, dict] = {}
        self.lines: list[str] = []
        self.marks: list[tuple[float, str]] = []

    def poll(self) -> list[dict]:
        new = []
        for t in self.voice.status().get("talk") or []:
            if t["id"] not in self.turns or self.turns[t["id"]]["text"] != t["text"]:
                fresh = t["id"] not in self.turns
                self.turns[t["id"]] = {**t, "seen": self.turns.get(t["id"], {}).get("seen", time.time())}
                if fresh:
                    new.append(t)
        return new

    def mark(self, what: str) -> None:
        self.poll()
        self.marks.append((time.time(), what))
        print(f"== {what}", flush=True)

    def wait_bot(self, since_id: int, pattern=None, secs: float = 120, quiet: float = 6.0) -> str:
        """Until the bot has said something after `since_id` (matching `pattern` if given) and then stayed quiet."""
        end, last_change = time.time() + secs, time.time()
        while time.time() < end:
            if self.poll():
                last_change = time.time()
            said = [t for i, t in sorted(self.turns.items()) if i > since_id and t["who"] == "assistant"]
            text = " ".join(t["text"] for t in said)
            if said and (pattern is None or pattern(text)) and time.time() - last_change > quiet:
                return text
            time.sleep(0.5)
        return " ".join(t["text"] for i, t in sorted(self.turns.items()) if i > since_id and t["who"] == "assistant")

    def last_id(self) -> int:
        self.poll()
        return max(self.turns, default=-1)

    def say(self, text: str, typed: bool = False) -> int:
        before = self.last_id()
        self.marks.append((time.time(), f"user ({'typed' if typed else 'spoken'}): {text}"))
        print(f">> {text}", flush=True)
        if typed:
            self.voice.post("/voice/say", {"text": text})
        else:
            self.voice.post("/bench/heard", {"text": text})
        return before

    def write(self) -> None:
        """The turns in the daemon's own order (their ids); each note of the run before the first turn seen after it."""
        lines, marks = [], [(at, what) for at, what in self.marks if not what.startswith("user (")]
        for _, t in sorted(self.turns.items()):
            while marks and marks[0][0] <= t["seen"]:
                lines.append(f"_[{marks.pop(0)[1]}]_")
            lines.append(f"**{'You' if t['who'] == 'user' else 'Pointe'}:** {t['text']}")
        lines += [f"_[{what}]_" for _, what in marks]
        self.out.write_text("\n\n".join(lines) + "\n")


def mirror(state: Path, sid: str) -> list[dict]:
    path = state / "harness" / "agents" / f"{sid}.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def replies(state: Path, sid: str) -> list[str]:
    out = []
    for e in mirror(state, sid):
        if e.get("pointeAgentReply"):
            out.append(" ".join(b.get("text", "") for b in e["message"]["content"]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence")
    parser.add_argument("--openclaw", default="http://127.0.0.1:18789")
    parser.add_argument("--hermes", default="http://127.0.0.1:18642")
    args = parser.parse_args()
    out = Path(args.evidence)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="pointe-agents-proof-", dir="/tmp"))
    voice = Voice(root, {"openclaw": "pointe-lab.openclaw-gateway-token", "hermes": "pointe-lab.hermes-api-key"},
                  out / "calls.jsonl")
    (voice.state / "agents.json").write_text(json.dumps({"agents": [
        {"name": "openclaw", "kind": "openclaw", "url": args.openclaw, "agent": "", "added": time.time()},
        {"name": "hermes", "kind": "hermes", "url": args.hermes, "agent": "", "added": time.time() + 1}]}))
    (voice.state / "agents.json").chmod(0o600)
    tr = Transcript(voice, out / "transcript.md")
    results: dict[str, object] = {"state": str(voice.state), "port": voice.port}
    call = None
    try:
        voice.start()
        until("both agents are sessions", lambda: {"openclaw", "hermes"} <= {s["name"] for s in voice.status()["sessions"]}, 60)
        call = Call(voice).open()
        tr.mark("call 1 opens")
        tr.wait_bot(-1, secs=60)

        # 1. orchestrated
        tr.mark("1. orchestrated request to openclaw")
        since = tr.say("Ask openclaw what the capital of Portugal is. One sentence.")
        until("openclaw replied", lambda: replies(voice.state, "agent-openclaw"), 180)
        results["1_openclaw_reply"] = replies(voice.state, "agent-openclaw")[-1]
        results["1_said"] = tr.wait_bot(since, lambda t: "lisbon" in t.lower(), secs=120)

        # 2. async: the reply arrives with no call up
        tr.mark("2. a request to hermes, then the call hangs up before the reply")
        since = tr.say("Ask hermes to name three moons of Jupiter, one line.")
        until("the request reached hermes", lambda: len(mirror(voice.state, "agent-hermes")) >= 1, 60)
        call.close()
        tr.mark("call 1 is down")
        until("hermes replied with no call up", lambda: replies(voice.state, "agent-hermes"), 180)
        hermes = next(s for s in voice.status()["sessions"] if s["name"] == "hermes")
        results["2_hermes_reply"] = replies(voice.state, "agent-hermes")[-1]
        results["2_status_while_away"] = {k: hermes.get(k) for k in ("needs", "working", "waiting")}
        call = Call(voice).open()
        tr.mark("call 2 opens")
        since = tr.last_id()
        results["2_greeting"] = tr.wait_bot(since - 1, secs=90)
        since = tr.say("What needs me?")
        results["2_what_needs_me"] = tr.wait_bot(since, secs=90)
        since = tr.say("What did hermes say?")
        results["2_what_did_hermes_say"] = tr.wait_bot(since, secs=90)

        # 3. 1:1
        tr.mark("3. one to one with hermes")
        since = tr.say("Talk to hermes.")
        results["3_switch"] = tr.wait_bot(since, secs=60)
        results["3_mode"] = voice.status().get("mode")
        n = len(replies(voice.state, "agent-hermes"))
        since = tr.say("What is the largest planet in the solar system? One sentence.")
        until("hermes answered the 1:1 turn", lambda: len(replies(voice.state, "agent-hermes")) > n, 180)
        results["3_hermes_1to1"] = replies(voice.state, "agent-hermes")[-1]
        results["3_said"] = tr.wait_bot(since, lambda t: "jupiter" in t.lower(), secs=120)
        since = tr.say("Orchestrator mode.")
        tr.wait_bot(since, secs=60)
        results["3_mode_after"] = voice.status().get("mode")

        # 4. relay with a spoken yes
        tr.mark("4. relay, confirmed")
        n_oc = len(mirror(voice.state, "agent-openclaw"))
        since = tr.say("Give hermes's answer to openclaw.")
        results["4_readback"] = tr.wait_bot(since, lambda t: "send hermes" in t.lower(), secs=60)
        assert len(mirror(voice.state, "agent-openclaw")) == n_oc, "nothing goes before the yes"
        since = tr.say("Yes.")
        until("the relay reached openclaw", lambda: len(mirror(voice.state, "agent-openclaw")) > n_oc, 60)
        relayed = mirror(voice.state, "agent-openclaw")[n_oc]
        results["4_relayed_message"] = relayed["message"]["content"]
        results["4_relay_depth"] = relayed.get("pointeRelay")
        until("openclaw answered the relay", lambda: len(replies(voice.state, "agent-openclaw")) > 1, 180)
        results["4_openclaw_on_relay"] = replies(voice.state, "agent-openclaw")[-1]
        results["4_said"] = tr.wait_bot(since, secs=120)

        # 5. relay refused
        tr.mark("5. relay, refused")
        n_he = len(mirror(voice.state, "agent-hermes"))
        since = tr.say("Send openclaw's answer to hermes.")
        results["5_readback"] = tr.wait_bot(since, lambda t: "send openclaw" in t.lower(), secs=60)
        since = tr.say("No, don't.")
        results["5_said"] = tr.wait_bot(since, secs=60)
        time.sleep(5)
        results["5_hermes_untouched"] = len(mirror(voice.state, "agent-hermes")) == n_he

        # 6. an approval, denied by voice
        tr.mark("6. openclaw asks to run a command")
        n = len(replies(voice.state, "agent-openclaw"))
        since = tr.say("Ask openclaw to use its exec tool to run ls on its workspace folder, and tell me what is there.")
        results["6_readout"] = tr.wait_bot(since, lambda t: "ls" in t.lower() and ("approve" in t.lower() or "run" in t.lower()
                                                                                    or "allow" in t.lower()), secs=120, quiet=3)
        since = tr.say("No.")
        until("openclaw finished after the answer", lambda: len(replies(voice.state, "agent-openclaw")) > n, 180)
        results["6_openclaw_after_no"] = replies(voice.state, "agent-openclaw")[-1]
        results["6_said"] = tr.wait_bot(since, secs=90)
        tr.mark("done")
    finally:
        try:
            tr.poll()
            tr.write()
        except Exception as e:
            print(f"transcript not written: {e}")
        if call is not None:
            try:
                call.close()
            except Exception:
                pass
        voice.stop()
        (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
        log = (voice.state.parent / "studio.log")
        if log.exists():
            shutil.copy(log, out / "daemon.log")
        for sid in ("agent-openclaw", "agent-hermes"):
            src = voice.state / "harness" / "agents" / f"{sid}.jsonl"
            if src.exists():
                shutil.copy(src, out / f"{sid}.mirror.jsonl")
        shutil.rmtree(root, ignore_errors=True)
    print(json.dumps(results, indent=1, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
