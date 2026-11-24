"""pointe: Pointe at the frozen commit, on an isolated daemon (its own CLAUDE_VOICE_STATE under /tmp and its own ports),
four sessions joined with /pointe:voice, and the e2e rig's fake page (tests/e2e/rig.py) playing the same audio into
the call. Events come from the daemon's own log: `-> <session>: ...` (a delivery), `speak: ...` (what it said).

The daemon is started here rather than by `bin/voice-daemon ensure`, which would also rewrite ~/.local/bin/pointe
(bin/link-pointe) and resync the checkout's environment. `voice-daemon ensure`, as /pointe:voice calls it, then finds
this daemon healthy and returns at once. POINTE_LINK_DIR points into /tmp as a second guard.
"""

import ast
import asyncio
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

from ..core import detector, ledger
from ..core.adapter import AgentArm
from ..core.agent import clean_env

LOG_TIME = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(\.\d+)?")
SEND = re.compile(r" -> (.+?): (.*) \(routing: ([^)]*)\)\s*$")
BRAIN = re.compile(r"brain step: (\d+) ms, (\d+) tokens in(?:, (\d+) of them cached)?")


def log_time(line: str) -> float:
    m = LOG_TIME.match(line)
    if not m:
        return time.time()
    return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + float("0" + (m.group(2) or ""))


def _rig():
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests" / "e2e"))
    import rig  # noqa: E402

    return rig


class PointeArm(AgentArm):
    name = "pointe"
    kind = "audio"
    plugin = True
    capabilities = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})
    wait_after_say = 45.0

    def __init__(self, env, port: int):
        super().__init__(env)
        assert port not in (7860, 7443) and 9600 <= port <= 9698, f"port {port} is outside this run's range"
        self.port, self.tls_port = port, port + 1

    def session_env(self, name: str) -> dict:
        return self.daemon_env()

    def daemon_env(self) -> dict:
        return {"CLAUDE_VOICE_STATE": str(self.state), "CLAUDE_VOICE_DAEMON_PORT": str(self.port),
                "CLAUDE_VOICE_TLS_PORT": str(self.tls_port), "CLAUDE_VOICE_NO_BROWSER": "1",
                "POINTE_LINK_DIR": str(self.env.root / "link-guard"), "ORT_DISABLE_TELEMETRY": "1"}

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def status(self) -> dict:
        token = (self.state / "token").read_text().strip()
        req = urllib.request.Request(self.url("/voice/status"), headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)

    async def start(self, conv_id, repos):
        self.state = self.job_dir(repos) / "state"
        home = Path.home().resolve()
        assert not str(self.state.resolve()).startswith(str(home)), "the state folder must not be under the home folder"
        self.state.mkdir(parents=True, exist_ok=False)
        os.chmod(self.state, 0o700)
        (self.state / "token").write_text(secrets.token_hex(24))
        os.chmod(self.state / "token", 0o600)
        for marker in ("setup-done", "first-hello"):  # a set-up Pointe, as /pointe:setup leaves it: not a first call
            (self.state / marker).touch()
        self.log_path = self.state / "daemon.log"
        self._log_pos = 0
        self.daemon = subprocess.Popen(
            ["uv", "run", "--no-sync", "--project", str(self.env.checkout), "python", str(self.env.checkout / "pointe" / "daemon.py"),
             "--port", str(self.port)],
            env=clean_env(self.daemon_env()), stdout=self.log_path.open("w"), stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(self.state))
        (self.state / "daemon.pid").write_text(str(self.daemon.pid))
        deadline = time.time() + 150
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url("/voice/health"), timeout=2)
                break
            except Exception:
                if self.daemon.poll() is not None:
                    raise RuntimeError("the Pointe daemon exited at start: " + self.log_path.read_text()[-600:])
                await asyncio.sleep(1)
        else:
            raise TimeoutError("the Pointe daemon did not become healthy")
        await super().start(conv_id, repos)
        for s in self.sessions.values():
            s.type("/pointe:voice")
            await asyncio.sleep(1)
        deadline = time.time() + 180
        while time.time() < deadline and len(self.status().get("sessions", [])) < len(repos):
            await asyncio.sleep(1)
        names = [s["name"] for s in self.status().get("sessions", [])]
        if len(names) < len(repos):
            raise TimeoutError(f"only {names} joined Pointe")
        self.alias = {}
        for n in names:  # the name Pointe gives a session, back to its repo
            base = n.split("/")[0]
            self.alias[n] = base if base in repos else next((r for r in repos if base.startswith(r)), base)
        await self.settle(120)
        rig = _rig()
        rig.STATE, rig.LOG, rig.DAEMON = self.state, self.log_path, f"http://127.0.0.1:{self.port}"
        self.browser = rig.Browser()
        self.call_start = time.time()
        self.last_said = 0.0
        await self.browser.connect()
        deadline = time.time() + 30  # the opening line comes after the page connects; the first turn waits for it
        while time.time() < deadline and not any(e["kind"] == "said" for e in self._peek()):
            await asyncio.sleep(0.5)
        await self.after_speech()
        await asyncio.sleep(2)
        await self.after_speech()
        self.events()  # the greeting and the join lines are set-up, not a turn

    def _peek(self) -> list[dict]:
        """Read the log into the event queue without taking the events out."""
        self.events_into_queue()
        return list(self._events)

    def _new_lines(self) -> list[str]:
        with self.log_path.open("r", errors="ignore") as f:
            f.seek(self._log_pos)
            data = f.read()
            self._log_pos = f.tell()
        return data.splitlines()

    def events(self) -> list[dict]:
        self.events_into_queue()
        return super().events()

    def events_into_queue(self) -> None:
        for line in self._new_lines() if hasattr(self, "log_path") else []:
            t = log_time(line)
            m = SEND.search(line)
            if m:
                self.emit("delivered", t=t, session=self.alias.get(m.group(1), m.group(1)), text=m.group(2)[:300],
                          routing=m.group(3))
                continue
            if "speak: " in line:
                raw = line.split("speak: ", 1)[1].strip()
                try:
                    said = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(said, str):
                    self.last_said = max(self.last_said, t)
                    self.emit("said", t=t, text=said)
                    if detector.is_question(said):
                        self.emit("asked", t=t, text=said)
                continue
            if "finished its turn" in line and "[" not in line.split("finished its turn")[0][-60:]:
                self.emit("agent_turn_done", t=t, line=line[24:200])

    def speaking(self, within: float = 1.5) -> bool:
        spans = self.browser.speaker.speech_spans(since=time.time() - 30)
        return bool(spans) and time.time() - spans[-1][1] < within

    async def quiet(self, timeout: float = 40) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and self.speaking(2.0):
            await asyncio.sleep(0.4)

    async def idle(self) -> bool:
        return await super().idle() and not (hasattr(self, "browser") and self.speaking(2.0))

    async def after_speech(self) -> None:
        """A line is logged before its audio starts: wait for the audio of anything said in the last ten seconds to
        start, then for two seconds of quiet. The scripted user never talks over Pointe."""
        self.events_into_queue()
        if time.time() - self.last_said < 10:
            deadline = time.time() + 8
            while time.time() < deadline and not any(
                    a >= self.last_said - 0.3 for a, _ in self.browser.speaker.speech_spans(since=self.last_said - 0.3)):
                await asyncio.sleep(0.2)
        await self.quiet()

    async def utter(self, clip_id: str, pcm48):
        await self.after_speech()
        start, end = self.browser.mic.say(np.asarray(pcm48, dtype=np.int16))
        await asyncio.sleep(max(0.0, end - time.time()))
        return start, end

    def _all_log(self) -> list[str]:
        return self.log_path.read_text(errors="ignore").splitlines() if hasattr(self, "log_path") else []

    def versions(self) -> dict:
        setup = next((l.split("setup: ", 1)[1] for l in self._all_log() if " setup: Setup(" in l), "")
        return {"pointe_setup": setup[:300]}

    def spend(self) -> list[dict]:
        rows = super().spend()
        lines = self._all_log()
        p = ledger.PRICES
        sonnet = p["anthropic"]["claude-sonnet-5-5"]
        steps = [BRAIN.search(l) for l in lines]
        steps = [m for m in steps if m]
        brain = sum(((int(m.group(2)) - int(m.group(3) or 0)) * sonnet["cache_write"] + int(m.group(3) or 0)
                     * sonnet["cache_read"] + p["pointe_brain_reply_tokens_per_step"] * sonnet["out"]) / 1e6
                    for m in steps)
        chars = 0
        for l in lines:
            if "speak: " in l:
                try:
                    said = ast.literal_eval(l.split("speak: ", 1)[1].strip())
                    chars += len(said) if isinstance(said, str) else 0
                except (ValueError, SyntaxError):
                    pass
        finished = sum("finished its turn" in l for l in lines)
        sends = sum(bool(SEND.search(l)) for l in lines)
        call_s = time.time() - getattr(self, "call_start", time.time())
        rows += [
            {"vendor": "anthropic", "what": "pointe:brain", "model": "claude-sonnet-5-5", "how": "computed-estimate",
             "usd": round(brain, 6), "steps": len(steps), "note": "input tokens from the log; reply tokens assumed"},
            {"vendor": "elevenlabs", "what": "pointe:mouth", "how": "computed", "chars": chars,
             "usd": round(chars / 1000 * p["elevenlabs_per_1k_chars"], 6)},
            {"vendor": "soniox", "what": "pointe:ears", "how": "computed-estimate", "seconds": round(call_s, 1),
             "usd": round(2 * call_s / 3600 * p["soniox_stream_hour"], 6), "note": "two streams (ears and mirror)"},
            {"vendor": "anthropic", "what": "pointe:reader", "how": "computed-estimate", "reports": finished,
             "usd": round(finished * p["pointe_reader_per_report"], 6)},
            {"vendor": "gemini", "what": "pointe:checker", "how": "computed-estimate", "sends": sends,
             "usd": round(sends * p["pointe_checker_per_send"], 6)},
        ]
        return rows

    async def stop(self) -> None:
        if hasattr(self, "browser"):
            await self.browser.close()
        await super().stop()
        if getattr(self, "daemon", None) is not None:
            try:
                os.killpg(self.daemon.pid, signal.SIGTERM)
                for _ in range(40):
                    if self.daemon.poll() is not None:
                        break
                    await asyncio.sleep(0.25)
                os.killpg(self.daemon.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self.daemon.wait(timeout=10)
        for _ in range(40):  # the next conversation reuses the port
            if subprocess.run(["lsof", "-nP", f"-iTCP:{self.port}", "-sTCP:LISTEN"], capture_output=True).returncode:
                break
            await asyncio.sleep(0.5)
