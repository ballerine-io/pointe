"""Pointe on an isolated daemon: its own state folder under the run's /tmp folder and ports from the runner's range
(never 7860 or 7443, never ~/.claude-voice). Audio goes in over the page's WebSocket call, exactly where a microphone
would, and the call's audio out is recorded. The session is the shared launch line plus `--plugin-dir <this checkout>`,
joined with the product's own `/pointe:voice`.

Setup: none chosen, so each role takes the first vendor with a key, as on a Mac with every key (bench/results/
combinations.md calls this "(default)"); `--pointe-setup <id>` chooses one. The roles in use are read from the daemon
log and recorded in the row.
"""

import asyncio
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import aiohttp
import numpy as np

from core import agent as agent_mod
from core import audio, ledger
from core.adapter import Event, SpendRow, now
from adapters.base import PtyArm

ROOT = Path(__file__).resolve().parents[4]  # this checkout: the bench code
FRAME = 320  # 20 ms at 16 kHz, the page's send rate
OUT_RATE = 24000  # what the daemon sends the page


class Call:
    """The page's call (phone.py's protocol) on its own event loop: mic in at real-time pace, speaker out recorded with
    the runner's clock. An "interrupt" message empties what is still queued, as the page must."""

    def __init__(self, url: str, token: str):
        self.url, self.token = url, token
        self.queue: list[np.ndarray] = []
        self.frames: list[tuple[float, np.ndarray]] = []
        self.sent: list[tuple[float, float]] = []  # (first, last) send time of each utterance's voiced frames
        self.spoke_until = 0.0
        self.opened = self.closed = None
        self.interrupts = 0
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(20):
            raise RuntimeError("the call did not connect")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        from websockets.asyncio.client import connect

        async with connect(self.url, max_size=None, additional_headers={"Authorization": f"Bearer {self.token}"}) as ws:
            self.opened = now()
            self._ready.set()
            playback = {"pcm": np.zeros(0, dtype=np.int16)}

            async def send():
                start, pts, current, pos, first = now(), 0, None, 0, None
                while not self._stop:
                    wait = start + pts / audio.RATE - now()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    if current is None and self.queue:
                        current, pos, first = self.queue.pop(0), 0, None
                    if current is not None:
                        chunk = current[pos:pos + FRAME]
                        if first is None and np.abs(chunk.astype(np.int32)).max(initial=0) > 500:
                            first = now()
                        if np.abs(chunk.astype(np.int32)).max(initial=0) > 500:
                            last = now() + len(chunk) / audio.RATE
                        pos += FRAME
                        if pos >= len(current):
                            self.sent.append((first or now(), last if first else now()))
                            current = None
                        chunk = np.pad(chunk, (0, FRAME - len(chunk)))
                    else:
                        chunk = np.zeros(FRAME, dtype=np.int16)
                    pts += FRAME
                    try:
                        await ws.send(chunk.astype(np.int16).tobytes())
                    except Exception:
                        return

            async def receive():
                try:
                    async for message in ws:
                        if isinstance(message, str):
                            if json.loads(message).get("type") == "interrupt":
                                self.interrupts += 1
                                playback["pcm"] = np.zeros(0, dtype=np.int16)
                            continue
                        pcm = audio.to_int16(audio.resample(np.frombuffer(message, dtype=np.int16), OUT_RATE, audio.RATE))
                        playback["pcm"] = np.concatenate([playback["pcm"], pcm])
                except Exception:
                    return

            async def play():
                start, played = now(), 0
                while not self._stop:
                    wait = start + played / audio.RATE - now()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    chunk, playback["pcm"] = playback["pcm"][:FRAME], playback["pcm"][FRAME:]
                    at = start + played / audio.RATE
                    if len(chunk) and np.abs(chunk.astype(np.int32)).max(initial=0) > 0:
                        self.frames.append((at, chunk))
                    played += FRAME
                    if not len(chunk) and now() - at > 0.2:  # nothing queued: restart the clock so a reply plays now
                        start, played = now(), 0

            tasks = [asyncio.create_task(f()) for f in (send, receive, play)]
            while not self._stop:
                await asyncio.sleep(0.1)
            for t in tasks:
                t.cancel()
        self.closed = now()

    def say(self, pcm: np.ndarray) -> tuple[float, float]:
        """Queues one utterance; blocks until its last frame was sent. Returns the send times of its first and last
        voiced frames."""
        n = len(self.sent)
        self.queue.append(pcm)
        deadline = now() + len(pcm) / audio.RATE + 30
        while len(self.sent) <= n and now() < deadline:
            time.sleep(0.01)
        return self.sent[n] if len(self.sent) > n else (now(), now())

    def close(self) -> None:
        self._stop = True
        time.sleep(0.4)


def product(commit: str) -> Path:
    """Pointe under test: a pristine export of the frozen commit under /tmp with its own environment, so the daemon's
    own `uv sync` never touches the bench's environment and no bench file is in the plugin folder."""
    target = Path("/tmp/pccb") / f"pointe-{commit[:12]}"
    if not (target / ".ready").exists():
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", commit], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)
        subprocess.run(["uv", "sync", "--locked", "--quiet", "--project", str(target)], check=True,
                       env=agent_mod.clean_env(), capture_output=True, timeout=600)
        (target / ".ready").write_text(commit + "\n")
    return target


def ours(pid: str, run_folder: Path) -> bool:
    """The process is this run's: its folder in its command line or environment. Another benchmark's daemon under
    /tmp/pccb on a port in this range is not ours to kill (the actions runner's rule)."""
    cmd = subprocess.run(["ps", "eww", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
    return bool(str(run_folder)) and str(run_folder) in cmd


def free_ports(ports, run_folder: Path) -> int:
    """Kills a Pointe daemon of this run still listening on its ports: a start that timed out on a loaded machine can
    leave one behind. Never touches another process, another benchmark's Pointe included."""
    killed = 0
    for port in ports:
        pids = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            if ours(pid, run_folder):
                subprocess.run(["kill", "-9", pid])
                killed += 1
    if killed:
        time.sleep(1.0)
    return killed


class Pointe(PtyArm):
    name = "pointe"
    capabilities = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})

    def env_extra(self, env):
        return self.daemon_env

    def start(self, sessions, env):
        port = env.port_base
        assert port not in (7860, 7443) and port + 1 not in (7860, 7443), "the owner's ports"
        state = env.root / "ps"
        assert str(state).startswith("/tmp/") and ".claude-voice" not in str(state), "an isolated state folder only"
        state.mkdir(parents=True, exist_ok=True)
        (env.root / "linkbin").mkdir(exist_ok=True)
        self.state, self.port, self.run_folder = state, port, env.root.parent
        self.daemon_env = {"CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(port),
                           "CLAUDE_VOICE_TLS_PORT": str(port + 1), "CLAUDE_VOICE_NO_BROWSER": "1",
                           "POINTE_LINK_DIR": str(env.root / "linkbin")}  # never rewrite the owner's ~/.local/bin/pointe
        # A Mac where Pointe has answered before: no first-call "say hello" flow takes the user's first words.
        (state / "first-hello").write_text("")
        (state / "setup-done").write_text("")
        if env.setup:
            (state / "config.json").write_text(json.dumps({"setup": env.setup}) + "\n")
        from core import runner

        self.commit = runner.product_commit()
        self.dir = product(self.commit)
        self.extra_args = ("--plugin-dir", str(self.dir))
        self.freed = free_ports((port, port + 1), env.root.parent)
        for attempt in range(2):  # the launcher waits 60 s for health; a loaded machine can miss that once
            out = subprocess.run([str(self.dir / "bin" / "voice-daemon"), "ensure"], env=agent_mod.clean_env(self.daemon_env),
                                 capture_output=True, text=True, timeout=240)
            if out.returncode == 0:
                break
            subprocess.run([str(self.dir / "bin" / "voice-daemon"), "stop"], env=agent_mod.clean_env(self.daemon_env),
                           capture_output=True, timeout=60)
            self.freed += free_ports((port, port + 1), env.root.parent)
        if out.returncode != 0:
            raise RuntimeError(f"the isolated daemon did not start: {out.stderr[-400:]}")
        self.call = Call(f"ws://127.0.0.1:{port}/voice/call", (state / "token").read_text().strip())
        self._quiet(first=12, settle=2.0, cap=25)  # the greeting
        self.session = next(iter(sessions))
        super().start(sessions, env)
        t = self.agent.type(f"/pointe:voice --name {self.session}")
        deadline = now() + 120
        while now() < deadline and not re.search(rf"registered {re.escape(self.session)} \(pid", self.log()):
            time.sleep(0.3)
        if not re.search(rf"registered {re.escape(self.session)} \(pid", self.log()):
            raise RuntimeError("the session did not join the isolated daemon")
        while now() < deadline and self.agent.turn_done_at(t) is None:
            time.sleep(0.3)
        self._quiet(first=4, settle=2.5, cap=20)
        self._events.append(Event(now(), "delivered", self.session, "joined", {"how": "/pointe:voice"}))

    def _quiet(self, first: float, settle: float, cap: float) -> None:
        """Waits up to `first` s for Pointe to start speaking, then until it has been silent `settle` s (at most `cap`)."""
        began = now()
        while now() - began < first and not audio.spans(self.call.frames, since=began):
            time.sleep(0.1)
        while now() - began < cap:
            last = audio.spans(self.call.frames, since=began)
            if not last or now() - last[-1][1] >= settle:
                return
            time.sleep(0.1)

    def say(self, pcm, rate):
        arr = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, bytes) else pcm
        return self.call.say(audio.to_int16(audio.resample(arr, rate, audio.RATE)))

    def speech(self):
        return [(a, b, audio.cut(self.call.frames, a, b).tobytes()) for a, b in audio.spans(self.call.frames)]

    def frames(self):
        return self.call.frames

    def speaking(self) -> bool:
        s = audio.spans(self.call.frames, since=now() - 3)
        return bool(s) and now() - s[-1][1] < 1.0

    def log(self) -> str:
        try:
            return (self.state / "daemon.log").read_text(errors="ignore")
        except OSError:
            return ""

    def roles(self) -> dict:
        """The roles in use, from the daemon's own `setup: Setup(brain='...', ...)` line."""
        m = re.search(r"setup: Setup\(([^)]*)\)", self.log())
        return dict(re.findall(r"(\w+)='([^']*)'", m.group(1))) if m else {}

    def versions(self):
        return {**super().versions(), "pointe_commit": getattr(self, "commit", ""),
                "stray_daemons_freed": str(getattr(self, "freed", 0)), "pointe_setup": self.env.setup or "(default)",
                "pointe_roles": json.dumps(self.roles())}

    def spend(self):
        log = self.log()
        p = ledger.PRICES
        brain = 0.0
        steps = re.findall(r"brain step: \d+ ms, (\d+) tokens in(?:, (\d+) of them cached)?", log)
        for total, cached in steps:
            total, cached = int(total), int(cached or 0)
            brain += ledger.anthropic_usd("claude-sonnet-5-5", {"input_tokens": total - cached, "cache_read_input_tokens": cached,
                                                                "output_tokens": p["pointe_output_tokens_per_brain_step_assumed"]})
        spoken = sum(len(m) for m in re.findall(r"speak(?: first)?: '(.*?)'$", log, re.M))
        mouth = spoken / 1000 * p["elevenlabs_per_1k_chars"]
        secs = ((self.call.closed or now()) - (self.call.opened or now())) if getattr(self, "call", None) else 0.0
        ears = ledger.soniox_usd(2 * secs)  # up to two streams: the ears and the echo guard's mirror
        return super().spend() + [
            SpendRow("pointe:brain", round(brain, 6), "computed", f"{len(steps)} steps, Sonnet list price, "
                     f"{p['pointe_output_tokens_per_brain_step_assumed']} output tokens a step assumed"),
            SpendRow("pointe:mouth", round(mouth, 6), "computed", f"{spoken} characters"),
            SpendRow("pointe:ears", round(ears, 6), "computed", f"{secs:.0f} s call, two streams"),
            SpendRow("pointe:other", p["pointe_unlogged_per_item_assumed"], "computed", "reader, checker, greeting: assumed")]

    def stop(self):
        if getattr(self, "call", None):
            self.call.close()
        super().stop()
        if getattr(self, "daemon_env", None):
            subprocess.run([str(self.dir / "bin" / "voice-daemon"), "stop"], env=agent_mod.clean_env(self.daemon_env),
                           capture_output=True, timeout=60)
            free_ports((self.port, self.port + 1), self.run_folder)
