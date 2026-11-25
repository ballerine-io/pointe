"""Record one take of the demo: a real call with real Claude Code sessions, the page, the terminals and both voices.

Nothing is staged in the software. The user's side is synthesized speech fed to the page's microphone, and the take is
labeled that way. Everything else is what the daemon, the page, the iPhone app and Claude Code actually did.

    uv run --with pyte python -u -I tools/demo-video/capture.py [--take N] [--no-phone]

Writes tools/demo-video/out/take-N/. Then: uv run python -I tools/demo-video/compose.py tools/demo-video/out/take-N
Isolated from a voice you are using: its own state dir and ports (set below), never the daemon on 7860.
"""

import os

os.environ.setdefault("CLAUDE_VOICE_STATE", "/tmp/cv-state-demo")
os.environ.setdefault("CLAUDE_VOICE_DAEMON_PORT", "7873")
os.environ.setdefault("CLAUDE_VOICE_TLS_PORT", "7473")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import base64  # noqa: E402
import fcntl  # noqa: E402
import json  # noqa: E402
import runpy  # noqa: E402
import select  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import termios  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

import pyte  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
sys.path.insert(0, str(HERE))
from hook_session import JoinedSession  # noqa: E402
from rig import ANSI, DAEMON, LOG, STATE, fresh_state, log_lines, stop_daemon, synth  # noqa: E402

import repos  # noqa: E402  (tools/demo-video/repos.py: the two synthetic projects)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT = 9373
PAGE_W, PAGE_H = 1100, 940
TERM_COLS, TERM_ROWS = 110, 30
SIMULATOR = os.environ.get("POINTE_DEMO_SIMULATOR", "")
MODEL = os.environ.get("POINTE_DEMO_MODEL", "haiku")
# The recording machine's own status line (cluster names and such) stays out of the picture.
QUIET_SETTINGS = json.dumps({"statusLine": {"type": "command", "command": "printf ''"}})
ALLOWED = "Read,Edit,Write,Glob,Grep,Bash(git add:*),Bash(git commit:*),Bash(./run-tests.sh:*),Bash(git status:*),Bash(git diff:*),Bash(git log:*)"

# What the page's microphone hears: in the page, before any of its own scripts run.
PAGE_HOOKS = r"""(() => {
  const RATE = 48000; let ctx = null, dest = null, next = 0;
  navigator.mediaDevices.getUserMedia = async () => {
    ctx = new AudioContext({sampleRate: RATE}); dest = ctx.createMediaStreamDestination();
    const hum = ctx.createConstantSource(); hum.offset.value = 0; hum.connect(dest); hum.start();
    await ctx.resume(); return dest.stream;
  };
  window.__say = b64 => {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0)), pcm = new Int16Array(bytes.buffer);
    const buf = ctx.createBuffer(1, pcm.length, RATE);
    buf.getChannelData(0).set(Float32Array.from(pcm, v => v / 32768));
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest);
    const at = Math.max(ctx.currentTime + 0.05, next); src.start(at); next = at + buf.duration;
    return Date.now() + (at - ctx.currentTime) * 1000;
  };
  // The bot's voice as it reaches this page, so the take carries exactly what the user heard.
  const Native = window.WebSocket; window.__bot = []; window.__cut = [];
  window.WebSocket = class extends Native {
    constructor(...a) {
      super(...a);
      if (String(a[0]).includes('/voice/call')) this.addEventListener('message', e => {
        const t = Date.now();
        if (typeof e.data === 'string') { if (e.data.includes('interrupt')) window.__cut.push(t); return; }
        const u = new Uint8Array(e.data); let s = '';
        for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
        window.__bot.push([t, btoa(s)]);
      });
    }
  };
})();"""


class CDP:
    def __init__(self, socket):
        self.socket, self.n, self.waiting, self.handlers = socket, 0, {}, {}

    async def run(self):
        async for raw in self.socket:
            message = json.loads(raw)
            if "id" in message and message["id"] in self.waiting:
                self.waiting.pop(message["id"]).set_result(message)
            elif message.get("method") in self.handlers:
                asyncio.create_task(self.handlers[message["method"]](message["params"]))  # never block the reader

    async def call(self, method: str, **params):
        self.n += 1
        future = asyncio.get_running_loop().create_future()
        self.waiting[self.n] = future
        await self.socket.send(json.dumps({"id": self.n, "method": method, "params": params}))
        return (await asyncio.wait_for(future, 30)).get("result", {})

    async def js(self, expression: str):
        got = await self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        return got.get("result", {}).get("value")


class RecordedSession(JoinedSession):
    """A plain Claude Code session that joined the voice, with its terminal kept as a screen, not a byte log."""

    def __init__(self, cwd: Path, label: str, out: Path, *args: str):
        super().__init__(cwd, *args)
        self.label, self.out = label, out
        self.term = pyte.Screen(TERM_COLS, TERM_ROWS)
        self.stream = pyte.ByteStream(self.term)
        self.auto_yes = True  # only before the call: the pre-roll work is not part of the demo

    def _pump(self) -> None:
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", TERM_ROWS, TERM_COLS, 0, 0))
        handled: set[str] = set()
        last = answered = 0.0
        with open(self.out, "a") as log:
            while not self._stop:
                r, _, _ = select.select([self.fd], [], [], 0.1)
                if r:
                    try:
                        raw = os.read(self.fd, 65536)
                    except OSError:
                        return
                    self.stream.feed(raw)
                    self.screen = (self.screen + ANSI.sub("", raw.decode("utf-8", "replace")))[-200_000:]
                now = time.time()
                if self.term.dirty and now - last > 0.2:
                    self.term.dirty.clear()
                    last = now
                    log.write(json.dumps({"t": now, "rows": [_runs(self.term.buffer[y]) for y in range(TERM_ROWS)],
                                          "cursor": [self.term.cursor.x, self.term.cursor.y]}) + "\n")
                    log.flush()
                if self.auto_yes and now - answered > 2.5 and any("Do you want to proceed?" in row for row in self.term.display):
                    answered = now
                    os.write(self.fd, b"\r")
                flat = self.flat()[-8000:]
                if "trustthisfolder" in flat and "trust" not in handled:
                    handled.add("trust"), time.sleep(0.4), os.write(self.fd, b"\x1b[B"), time.sleep(0.2), os.write(self.fd, b"\r")


def _runs(line) -> list:
    out, run, style = [], "", None
    for x in range(TERM_COLS):
        ch = line[x]
        key = (ch.fg, ch.bg, ch.bold, ch.reverse)
        if key != style and run:
            out.append([run, *style])
            run = ""
        style = key
        run += ch.data or " "
    if run:
        out.append([run, *style])
    return out


class Take:
    def __init__(self, out: Path):
        self.out = out
        self.events = open(out / "events.jsonl", "a")
        self.bot = open(out / "bot.pcm", "ab")
        self.bot_index = open(out / "bot_index.jsonl", "a")
        self.offset = 0
        self.played_until = 0.0  # wall time the page's queued bot audio runs out, as the page plays it
        self.page = None

    def note(self, kind: str, **info) -> None:
        self.events.write(json.dumps({"t": time.time(), "kind": kind, **info}) + "\n")
        self.events.flush()
        print(f"  {time.strftime('%H:%M:%S')} {kind} {json.dumps(info)[:140]}", flush=True)

    async def drain(self) -> None:
        got = await self.page.js("(() => { const b = window.__bot || [], c = window.__cut || []; window.__bot = []; "
                                 "window.__cut = []; return JSON.stringify([b, c]); })()")
        if not got:
            return
        chunks, cuts = json.loads(got)
        for t, b64 in chunks:
            pcm = base64.b64decode(b64)
            self.bot.write(pcm)
            self.bot_index.write(json.dumps({"t": t / 1000, "offset": self.offset, "bytes": len(pcm)}) + "\n")
            self.offset += len(pcm)
            self.played_until = max(self.played_until, t / 1000) + len(pcm) / 2 / 24000
        for t in cuts:
            self.note("interrupt", at=t / 1000)
            self.played_until = t / 1000
        self.bot.flush(), self.bot_index.flush()

    async def drain_forever(self) -> None:
        while True:
            try:
                await self.drain()
            except Exception:
                pass
            await asyncio.sleep(0.4)

    async def say(self, text: str) -> float:
        """Speak into the page's mic; returns when the words have been said."""
        pcm = await synth(text)
        start = await self.page.js(f"window.__say('{base64.b64encode(pcm.tobytes()).decode()}')") / 1000
        end = start + len(pcm) / 48000
        self.note("user", text=text, start=start, end=end, cache=str(abs(hash(text)) % 10**12))
        await asyncio.sleep(max(0, end - time.time()))
        return end

    async def quiet(self, settle: float = 2.2, first: float = 20, timeout: float = 90) -> None:
        """Wait until the bot has started (within `first` seconds) and then gone quiet for `settle` seconds."""
        start = time.time()
        while time.time() - start < first and self.played_until < start:
            await asyncio.sleep(0.2)
        deadline = time.time() + timeout
        while time.time() < deadline and time.time() - max(self.played_until, start) < settle:
            await asyncio.sleep(0.2)

    async def click(self, selector: str) -> bool:
        box = await self.page.js(f"(() => {{ const b = document.querySelector({json.dumps(selector)}); if (!b) return null; "
                                 "const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        if not box:
            return False
        self.note("click", x=box[0], y=box[1], selector=selector)
        for kind in ("mousePressed", "mouseReleased"):
            await self.page.call("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)
        return True


def status() -> dict:
    request = urllib.request.Request(f"{DAEMON}/voice/status",
                                     headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})
    return json.loads(urllib.request.urlopen(request, timeout=5).read())


async def wait_log(pattern: str, after: int, timeout: float) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = log_lines(pattern)
        if len(found) > after:
            return found[after]
        await asyncio.sleep(0.3)
    return None


async def until(test, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if test():
            return True
        await asyncio.sleep(0.5)
    return False


def beat(take: Take, name: str) -> None:
    take.note("beat", name=name)


async def run(out: Path, phone: bool) -> None:
    fresh_state()
    import pair

    pair.STATE = STATE
    pair.setup("localhost", "127.0.0.1")
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True,
                          env=dict(os.environ)).returncode == 0, "the daemon did not start"
    checkout, billing = repos.make()

    builder = None
    if phone:  # the app builds while the sessions work
        builder = subprocess.Popen(["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe",
                                    "-destination", f"id={SIMULATOR}", "-derivedDataPath", "/tmp/pointe-dd",
                                    "build-for-testing"], stdout=open(out / "xcodebuild.log", "w"), stderr=subprocess.STDOUT)

    take = Take(out)
    a = RecordedSession(checkout, "checkout", out / "term-checkout.jsonl", "--model", MODEL, "--permission-mode", "default",
                        "--allowedTools", ALLOWED, "--settings", QUIET_SETTINGS)
    b = RecordedSession(billing, "billing", out / "term-billing.jsonl", "--model", MODEL, "--permission-mode", "default",
                        "--allowedTools", ALLOWED, "--settings", QUIET_SETTINGS)
    a.start(), b.start()
    take.note("sessions", names=[s["name"] for s in status()["sessions"]])
    done = len(log_lines("finished its turn"))
    a.type(repos.CHECKOUT_TASK)
    b.type(repos.BILLING_TASK)
    take.note("pre-roll", checkout=repos.CHECKOUT_TASK, billing=repos.BILLING_TASK)
    await asyncio.sleep(15)
    await until(lambda: not any(x["working"] for x in status()["sessions"]), 300)
    take.note("pre-roll done", working=[x["name"] for x in status()["sessions"] if x["working"]])
    await asyncio.sleep(12)  # the reader writes its notes on each session
    a.auto_yes = b.auto_yes = False

    profile = tempfile.mkdtemp(prefix="pointe-demo-chrome-")
    url = f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"
    chrome = subprocess.Popen([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                               "--autoplay-policy=no-user-gesture-required", f"--window-size={PAGE_W},{PAGE_H}",
                               "--hide-scrollbars", "--no-first-run", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sim_video = None
    try:
        from websockets.asyncio.client import connect

        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as socket:
            page = CDP(socket)
            take.page = page
            pump = asyncio.create_task(page.run())
            frames = out / "page"
            frames.mkdir(exist_ok=True)
            index = open(out / "page_index.jsonl", "a")

            count = iter(range(10**7))

            async def frame(params):
                name = f"{next(count):06d}.jpg"
                (frames / name).write_bytes(base64.b64decode(params["data"]))
                index.write(json.dumps({"t": time.time(), "file": name}) + "\n")
                index.flush()
                await page.call("Page.screencastFrameAck", sessionId=params["sessionId"])

            page.handlers["Page.screencastFrame"] = frame
            await page.call("Page.enable")
            await page.call("Emulation.setDeviceMetricsOverride", width=PAGE_W, height=PAGE_H, deviceScaleFactor=1, mobile=False)
            await page.call("Page.addScriptToEvaluateOnNewDocument", source=PAGE_HOOKS)
            await page.call("Page.navigate", url=url)
            await asyncio.sleep(3)
            await page.call("Page.startScreencast", format="jpeg", quality=82, maxWidth=PAGE_W, maxHeight=PAGE_H, everyNthFrame=1)
            drainer = asyncio.create_task(take.drain_forever())
            await asyncio.sleep(2)

            beat(take, "connect")
            await take.click("#hero .ring")
            await take.quiet(first=25)

            beat(take, "a: what did they do, switch by name")
            await take.say("What did checkout and billing just do?")
            await take.quiet(first=25)
            await take.say("Switch to billing.")
            await take.quiet()

            beat(take, "b: a read-out approval by voice")
            n_perm = len(log_lines(r"permission request\]"))
            await take.say("Ask it to push to origin.")
            if await wait_log(r"permission request\]", n_perm, timeout=60):
                await take.quiet(settle=1.5, first=15)
                await take.say("Yes.")
            await asyncio.sleep(5)
            await until(lambda: not any(x["working"] for x in status()["sessions"]), 120)
            await take.quiet(first=20)

            beat(take, "b: a complex command, approved on the page")
            n_perm = len(log_lines(r"permission request\]|permission from .* not active"))
            await take.say("Tell checkout to delete every pycache folder in the repo, using find.")
            if await wait_log(r"permission request\]|permission from .* not active", n_perm, timeout=90):
                await take.quiet(settle=2.0, first=15)
                waiting = next((s for s in status()["sessions"] if s.get("waiting")), {})
                take.note("request", name=waiting.get("name"), request=waiting.get("request"),
                          voice_can_approve=waiting.get("voice_can_approve"))
                await asyncio.sleep(2.5)  # long enough to read it on screen
                if not await take.click("#attention button.allow"):
                    await take.say("Yes.")
            await asyncio.sleep(5)
            await until(lambda: not any(x["working"] for x in status()["sessions"]), 120)
            await take.quiet(first=15)

            beat(take, "c: just listen")
            await take.say("Just listen.")
            await take.quiet(settle=1.0, first=4)
            for thought in repos.THOUGHTS:
                await take.say(thought)
                await asyncio.sleep(6)  # a real thinking pause: the bot must stay silent
            await take.say("Okay, what do you think?")
            await take.quiet(first=25)

            beat(take, "d: by the way, while it works")
            await take.say("Tell checkout to run the slow test suite.")
            await take.quiet(first=15)
            n_copy = len(log_lines(r"copy of .* answered in"))
            await take.say("By the way, why did checkout use exponential backoff instead of a fixed delay?")
            await take.quiet(first=15)  # "asking it now"
            await wait_log(r"copy of .* answered in", n_copy, timeout=90)
            await take.quiet(first=20)
            await until(lambda: not any(x["working"] for x in status()["sessions"]), 150)
            await take.quiet(first=20)

            if phone:
                beat(take, "e: the same call on the iPhone")
                await take.click("#hangup")
                await asyncio.sleep(3)
                builder.wait(timeout=600)
                for override in (["--time", "9:41", "--batteryState", "charged", "--batteryLevel", "100",
                                  "--cellularBars", "4", "--wifiBars", "3"],):
                    subprocess.run(["xcrun", "simctl", "status_bar", SIMULATOR, "override", *override], capture_output=True)
                subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"],
                               capture_output=True)
                sim_video = subprocess.Popen(["xcrun", "simctl", "io", SIMULATOR, "recordVideo", "--codec=h264", "--force",
                                              str(out / "phone.mp4")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                await asyncio.sleep(1.5)
                take.note("phone-video", started=time.time())
                tester = subprocess.Popen(
                    ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe",
                     "-destination", f"id={SIMULATOR}", "-derivedDataPath", "/tmp/pointe-dd", "-only-testing:PointeUITests",
                     "test-without-building"],
                    env={**os.environ, "TEST_RUNNER_POINTE_PAIR": pair.pairing_link()},
                    stdout=open(out / "uitest.log", "w"), stderr=subprocess.STDOUT)
                await until(lambda: bool(log_lines("phone connected")), 120)
                take.note("phone", connected=bool(log_lines("phone connected")))
                await asyncio.sleep(6)
                a.type("Run exactly this command and nothing else: touch phone-check.txt")
                take.note("typed", session="checkout", text="touch phone-check.txt")
                await until(lambda: tester.poll() is not None, 180)
                await asyncio.sleep(2)
                take.note("phone-done", uitest=tester.returncode)
            beat(take, "end")
            await asyncio.sleep(2)
            await page.call("Page.stopScreencast")
            drainer.cancel()
            await take.drain()
            pump.cancel()
    finally:
        if sim_video and sim_video.poll() is None:
            sim_video.send_signal(signal.SIGINT)
            try:
                sim_video.wait(timeout=20)
            except subprocess.TimeoutExpired:
                sim_video.kill()
        chrome.terminate()
        a.stop(), b.stop()
        shutil.copy(LOG, out / "daemon.log")
        stop_daemon()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--take", type=int, default=0)
    parser.add_argument("--no-phone", action="store_true")
    args = parser.parse_args()
    take = args.take or 1 + max([int(p.name.split("-")[1]) for p in (HERE / "out").glob("take-*")] or [0])
    out = HERE / "out" / f"take-{take}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    phone = not args.no_phone
    if phone:
        runpy.run_path(str(ROOT / "tools" / "ui_guard.py"))["require"]("tools/demo-video/capture.py with the iPhone (not --no-phone)")
        global SIMULATOR
        if not SIMULATOR:
            booted = subprocess.run(["xcrun", "simctl", "list", "devices", "booted", "-j"], capture_output=True, text=True).stdout
            devices = [d for group in json.loads(booted)["devices"].values() for d in group]
            assert devices, "boot an iPhone simulator, or pass --no-phone"
            SIMULATOR = devices[0]["udid"]
    print(f"take {take} -> {out}", flush=True)
    asyncio.run(run(out, phone))
    os._exit(0)


main()
