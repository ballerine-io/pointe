"""What the two demo suites share (demo_meeting.py, demo_voice_control.py): an isolated daemon, real Claude Code
sessions in throwaway folders under /tmp, the stand-in user's call (synthesized speech, never a microphone), and the
page in a headless Chrome to check that each step shows.

Keys come from the Keychain into the one process that needs them: the daemon reads its own (vendors.key), the rig reads
ElevenLabs (the user's voice) and Gemini (what the bot said). None is printed.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

from page_meeting import CHROME, Page, call  # noqa: F401  (re-exported)
from rig import DAEMON, LOG, ROOT, STATE, Browser, ClaudeSession, fresh_state, log_lines, stop_daemon, transcribe  # noqa: F401

TEST_MODEL = os.environ.get("CLAUDE_VOICE_TEST_MODEL", "haiku")


def isolated() -> None:
    """Never the live daemon or the user's state."""
    assert os.environ.get("CLAUDE_VOICE_STATE"), "set CLAUDE_VOICE_STATE to a throwaway folder"
    assert STATE != Path.home() / ".claude-voice", "set CLAUDE_VOICE_STATE for tests"
    port = os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860")
    tls = os.environ.get("CLAUDE_VOICE_TLS_PORT", "7443")
    assert port != "7860" and tls != "7443", "set CLAUDE_VOICE_DAEMON_PORT and CLAUDE_VOICE_TLS_PORT to other ports"
    os.environ.setdefault("CLAUDE_VOICE_FRONT", "brain")


def start_daemon() -> None:
    isolated()
    fresh_state()
    got = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert got.returncode == 0, got.stderr[-400:]


def status() -> dict:
    return call("/voice/status")


def base(name: str) -> str:
    """A session in a git folder joins as "<folder>/<branch>" ("billing/main"); the folder part is what the user says."""
    return name.split("/")[0]


def session_named(name: str) -> dict | None:
    return next((s for s in status().get("sessions") or [] if base(s["name"]) == name), None)


def names() -> set[str]:
    return {base(s["name"]) for s in status().get("sessions") or []}


class LiveSession(ClaudeSession):
    """A real Claude Code session in its own folder, joined through `claude-voice` (the launch mode, with its channel)."""

    def type(self, text: str) -> None:
        os.write(self.fd, text.encode())
        time.sleep(0.6)
        os.write(self.fd, b"\r")

    def start(self, timeout: float = 120) -> None:  # waits for its own name, not any registration in the log
        name = self.cwd.name
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID")}
        env.update(CLAUDE_VOICE_NO_BROWSER="1", CLAUDE_VOICE_FRONT=self.front)
        import fcntl
        import pty
        import struct
        import termios
        import threading

        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.cwd)
            os.execvpe(str(ROOT / "bin" / "claude-voice"), ["claude-voice", *self.args], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if session_named(name):
                time.sleep(2)
                return
            time.sleep(0.5)
        raise TimeoutError(f"{name} did not join the voice:\n{self.flat()[-600:]}")


def workspace(tag: str, folders: list[str]) -> Path:
    """Throwaway folders, each a tiny git repository (Claude Code's trust prompt is answered by the rig)."""
    root = Path(tempfile.mkdtemp(prefix=f"pointe-{tag}-", dir="/tmp"))
    for name in folders:
        d = root / name
        d.mkdir()
        (d / "README.md").write_text(f"# {name}\nA throwaway project for a Pointe test.\n")
        subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                       shell=True, cwd=d, check=True)
    return root


def start_sessions(root: Path, folders: list[str]) -> dict[str, LiveSession]:
    out = {}
    for name in folders:
        s = LiveSession(root / name, "--model", TEST_MODEL)
        s.start()
        joined = session_named(name)["name"]
        if joined != name:  # named as the owner would: a title from its first turn must not rename it mid-test
            call("/voice/rename", {"name": joined, "new_name": name})
        out[name] = s
    return out


def stop_sessions(sessions: dict) -> None:
    for s in sessions.values():
        try:
            s.stop()
        except Exception:
            pass


def transcript_of(name: str) -> Path | None:
    s = session_named(name)
    path = s and (s.get("transcript") or "")
    return Path(path) if path else None


async def until(test, timeout: float, every: float = 0.4):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


# ---------- the stand-in user ----------

async def owner_says(browser: Browser, text: str, settle: float = 0.3) -> float:
    """The owner's words at real-time pace; returns when they ended."""
    _, end = await browser.say(text)
    await asyncio.sleep(max(0.0, end - time.time()) + settle)
    return end


async def owner_heard(browser: Browser, text: str, heard: str = r"user said: ", timeout: float = 15,
                      tries: int = 2) -> tuple[float, int]:
    """The owner's words, said again only when the daemon never got them (no `heard` line in its log): on a congested
    uplink the speech stream stalls and drops what was said, which is the network, not what Pointe does with words it
    hears. Returns when the words ended, and how many tries it took (each retry is reported)."""
    for n in range(1, tries + 1):
        before = len(log_lines(heard))
        end = await owner_says(browser, text)
        if await until(lambda: len(log_lines(heard)) > before, timeout, 0.3):
            return end, n
    return end, tries


async def room_says(browser: Browser, voice: str, text: str, pause: float = 1.0) -> None:
    _, end = await browser.say(text, voice)
    await asyncio.sleep(max(0.0, end - time.time()) + pause)


async def reply_audio(browser: Browser, since: float, timeout: float = 40, quiet: float = 2.5):
    """The bot's audio after `since`, once it has been quiet a moment (None when it said nothing). A person answers a
    read-back as soon as it ends: transcribe it afterwards, not before the answer (on a slow link that takes long)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = browser.speaker.speech_spans(since=since)
        # "One sec." alone is the filler for a slow model step, not the reply: wait on for the words after it
        if spans and time.time() - spans[-1][1] > quiet and sum(b - a for a, b in spans) > 1.2:
            return browser.speaker.audio(spans[0][0], spans[-1][1])
        await asyncio.sleep(0.3)
    spans = browser.speaker.speech_spans(since=since)
    return browser.speaker.audio(spans[0][0], spans[-1][1]) if spans else None


async def words(pcm) -> str:
    return await transcribe(pcm) if pcm is not None else ""


async def heard_reply(browser: Browser, since: float, timeout: float = 40, quiet: float = 2.5) -> str:
    """What the bot said after `since`, once it has been quiet a moment; '' when it said nothing."""
    return await words(await reply_audio(browser, since, timeout, quiet))


async def greeted(browser: Browser, timeout: float = 60) -> None:
    """The greeting was said to the end (its journal line), and the bot has gone quiet: a person waits for it. On a slow
    network the greeting comes many seconds after the call is up, and words said before it reach nobody."""
    await until(lambda: log_lines(r"bot said: "), timeout, 0.5)
    await quiet(browser)


async def quiet(browser: Browser, need: float = 3.0, timeout: float = 45) -> None:
    """The bot has been silent `need` seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = browser.speaker.speech_spans(since=time.time() - 60)
        if (not spans or time.time() - spans[-1][1] > need) and status().get("speaking") != "bot":
            return
        await asyncio.sleep(0.3)


def spoke_since(browser: Browser, since: float) -> bool:
    return bool(browser.speaker.speech_spans(since=since))


def tools_since(n: int, name: str = r"\w+") -> list[str]:
    return [l for l in log_lines(rf" tool {name}\(")][n:]


def mark() -> int:
    return len(log_lines(r" tool \w+\("))


# ---------- the page ----------

class PageWindow:
    """The page in a headless Chrome, its own profile and debug port."""

    def __init__(self, port: int, shots: Path):
        self.port, self.shots = port, shots
        self.proc = None
        self.socket = None
        self.page: Page | None = None

    async def open(self) -> Page:
        self.shots.mkdir(parents=True, exist_ok=True)
        profile = tempfile.mkdtemp(prefix="pointe-chrome-")
        url = f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"
        self.proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
                                      f"--user-data-dir={profile}", "--window-size=1400,900", "--no-first-run",
                                      "--lang=en-US",
                                      # a headless page counts as hidden: Chrome would slow its 0.7 s poll to once a
                                      # minute, and the checks would time the throttle, not the page
                                      "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                                      "--disable-backgrounding-occluded-windows", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(60):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                await asyncio.sleep(0.5)
        assert target, "the page did not open"
        self.socket = await connect(target["webSocketDebuggerUrl"], max_size=None)
        self.page = Page(self.socket)
        await self.page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                           "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
        return self.page

    async def shot(self, name: str) -> None:
        import base64

        await asyncio.sleep(0.8)
        data = (await self.page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
        (self.shots / f"{name}.png").write_bytes(base64.b64decode(data))

    async def close(self) -> None:
        if self.socket is not None:
            await self.socket.close()
        if self.proc is not None:
            self.proc.terminate()


ROWS = "[...document.querySelectorAll('#list .s:not(.starting) .nm')].map(x => x.textContent.split('/')[0]).sort().join(',')"


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", text.lower())).strip()


def keep_log(folder: Path) -> None:
    """The run's daemon log beside its screenshots: the next run starts a fresh one."""
    folder.mkdir(parents=True, exist_ok=True)
    if LOG.exists():
        shutil.copy(LOG, folder / "daemon.log")


def cleanup(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
