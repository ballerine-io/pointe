"""Brain dump in the page, live: a stand-in user on a real call (synthetic speech over the page's own call socket) and the
page in a real (headless) Chrome, with one synthetic session (lantern) listening on an inbox socket. "Brain dump." opens the panel; three thoughts land on
it and the voice says nothing; "Okay, done." structures them and the review opens with the prompt; nothing reached lantern
yet; the To: picker defaults to Orchestrator (the call is in orchestrator mode); Send (two clicks) to lantern delivers the
text on screen, word for word, and the voice says it went. A second dump, sent to the orchestrator by default, becomes the
user's turn and the voice answers it. A third, started from the dock, is discarded by voice and reaches nothing. Every session, path and thought here is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-dump CLAUDE_VOICE_DAEMON_PORT=7996 CLAUDE_VOICE_TLS_PORT=7596 POINTE_CHROME_PORT=7999 \
     uv run python -u -I tests/e2e/page_brain_dump.py
Takes about three minutes. Calls paid APIs (ears, brain, mouth, the reading model, and ElevenLabs for the user's voice).
Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7999"))
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-dump-shots-"))
THOUGHTS = ["So the checkout keeps timing out for some customers.",
            "I think it's the retry loop around the payment provider, it retries five times with no backoff.",
            "We must not touch the tax service this sprint."]
INBOX: list[str] = []  # what reached lantern: its inbox socket, read by this test


def status() -> dict:
    return call("/voice/status")


def dump() -> dict | None:
    return status()["brain_dump"]


async def serve_inbox(path: str):
    async def take(reader, writer):
        INBOX.extend(line.decode() for line in (await reader.read()).splitlines() if line.strip())
        writer.close()
    return await asyncio.start_unix_server(take, path=path)


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


async def quiet(timeout: float = 40) -> None:
    await until(lambda: status()["speaking"] is None, timeout)
    await asyncio.sleep(1.5)


async def say(browser: Browser, text: str, settle: float = 1.5) -> None:
    """Speaks it at real-time pace, then a pause as a person leaves."""
    _, end = await browser.say(text)
    await asyncio.sleep(max(0.0, end - time.time()) + settle)


def spoke_since(t: float) -> list[str]:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
    return [line[-120:] for line in log_lines(r"speak: ") if line[:19] >= stamp]


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    (STATE / "brain_dump.json").unlink(missing_ok=True)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-dump-e2e-"))
    (work / "transcript.jsonl").touch()
    inbox_path = f"/tmp/dump-inbox-{os.getpid()}.sock"
    inbox = await serve_inbox(inbox_path)
    call("/voice/register", {"id": f"dump-lantern-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "lantern",
                             "name_given": True, "transcript": str(work / "transcript.jsonl"), "inbox_socket": inbox_path})
    browser = Browser(echo_gain=float(os.environ.get("POINTE_ECHO_GAIN", "0.3")))  # speakers into the mic, as in a room
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        calm = 0
        for _ in range(60):  # a cold daemon stalls its loop for seconds on its first vendor import: dial once it is past it
            t = time.time()
            status()
            calm = calm + 1 if time.time() - t < 0.3 else 0
            if calm >= 3:
                break
            await asyncio.sleep(1)
        await browser.connect()
        await until(lambda: status()["connected"], 15)
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as cdp:
            page = Page(cdp)
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('listen')", 10)
            await quiet(60)  # the greeting

            # ---- "Brain dump." opens it; the thoughts land; the voice stays quiet ----
            t0 = time.time()
            await say(browser, "Brain dump.")
            on = await until(lambda: (dump() or {}).get("state") == "dumping", 20)
            panel = await page.until("!document.getElementById('dump').hidden && document.getElementById('listen-label').textContent === 'Done'", 5)
            check("\"Brain dump.\" by voice starts it: the mode is brain-dump, the page shows the panel and the dock says Done",
                  bool(on) and bool(panel) and status()["mode_state"]["mode"] == "brain-dump" and bool(log_lines("brain dump started")),
                  mode=status()["mode_state"])
            for thought in THOUGHTS:
                await say(browser, thought, settle=4)
            landed = await until(lambda: len((dump() or {}).get("thoughts", [])) >= 3, 20)
            shown = await page.until("[...document.querySelectorAll('#dump-list li')].map(x => x.textContent)", 5)
            await page.shot("dump-1-dumping")
            said = " ".join(t["text"] for t in (dump() or {}).get("thoughts", [])).lower()
            heard = browser.speaker.speech_spans(since=t0 + 1)
            check("three thoughts land on the panel, word for word enough, and the voice says nothing",
                  bool(landed) and len(shown or []) >= 3 and "retry" in said and "tax" in said and not spoke_since(t0 + 1)
                  and not heard and not INBOX, thoughts=shown, spoke=spoke_since(t0 + 1), heard=heard)

            # ---- "Okay, done." structures it: the review opens; nothing has moved ----
            t1 = time.time()
            await say(browser, "Okay, done.")
            review = await until(lambda: (dump() or {}).get("state") == "review", 45)
            sheet = await page.until("document.getElementById('dumpsheet').classList.contains('open') && document.getElementById('dump-text').value", 10)
            spoke = await until(lambda: spoke_since(t1), 25)
            await page.shot("dump-2-review")
            prompt = (dump() or {}).get("prompt") or {}
            text = (prompt.get("text") or "").lower()
            check("\"done\" structures the thoughts: the review opens with a prompt in the user's words, the voice says it is ready, nothing was sent",
                  bool(review) and bool(sheet) and any(h in "\n" + text for h in ("\ngoal\n", "\ncontext\n"))
                  and "nothing added" not in text and "(not stated)" not in text and ("retry" in text or "backoff" in text) and "tax" in text
                  and not prompt.get("fallback") and bool(spoke) and not INBOX and status()["mode_state"]["mode"] == "conversation",
                  prompt=text[:300], spoke=spoke[-1:] if spoke else [], sections={k: prompt.get(k) for k in ("goal", "constraints")})
            await quiet()

            # ---- Send to lantern, two clicks: the text on screen, word for word ----
            on_screen = await page.js("document.getElementById('dump-text').value")
            picker = await page.js("({picked: $('dump-session').value, first: $('dump-session').options[0].textContent, "
                                   "label: $('dump-send').getAttribute('aria-label')})")
            check("the To: picker lists Orchestrator first and defaults to it: the dump started in orchestrator mode",
                  picker == {"picked": "", "first": "Orchestrator", "label": "Send to Orchestrator"}
                  and (dump() or {}).get("send_to", {}).get("orchestrator") is True, picker=picker, mode=status()["mode"])
            await page.js("$('dump-session').value = 'lantern'; $('dump-session').dispatchEvent(new Event('change'))")
            await page.js("document.getElementById('dump-send').click()")
            asks = await page.js("document.getElementById('dump-send').textContent")
            await page.shot("dump-2b-armed")
            await page.js("document.getElementById('dump-send').click()")
            arrived = await until(lambda: INBOX, 20)
            gone = await until(lambda: dump() is None and not (STATE / "brain_dump.json").exists(), 10)
            told = await until(lambda: log_lines(r"-> lantern: brain dump"), 5)
            await page.shot("dump-3-sent")
            body = "\n".join(INBOX)
            check("Send asks first, then delivers exactly the text on screen to lantern, framed at send time only, and the dump is gone",
                  asks == "Tap again to send" and bool(arrived) and on_screen.strip() in body.replace("\\n", "\n") and "nothing added" in body
                  and "nothing added" not in on_screen and bool(gone) and bool(told),
                  asks=asks, inbox=body[:300])
            await quiet()

            # ---- a second dump, sent to the orchestrator by default: the user's turn, and the voice answers ----
            await page.js("document.getElementById('listen').click()")
            await until(lambda: (dump() or {}).get("state") == "dumping", 10)
            await say(browser, "What do you think makes a good name for a cache that lives per merchant?", settle=3)
            await until(lambda: (dump() or {}).get("thoughts"), 15)
            await page.js("document.getElementById('dump-done').click()")
            await until(lambda: (dump() or {}).get("state") == "review", 45)
            await page.until("document.getElementById('dumpsheet').classList.contains('open') && document.getElementById('dump-text').value", 10)
            await quiet()
            t2 = time.time()
            await page.js("document.getElementById('dump-send').click()")
            await page.js("document.getElementById('dump-send').click()")
            handed = await until(lambda: dump() is None and any(t["who"] == "user" and t["text"].startswith("My brain dump, structured")
                                                                for t in status().get("talk", [])), 15)
            answered = await until(lambda: spoke_since(t2), 30)
            await page.shot("dump-4-orchestrator")
            check("Send with the default hands the dump to the orchestrator as the user's turn, and the voice answers it",
                  bool(handed) and bool(answered) and bool(log_lines(r"-> orchestrator: brain dump")),
                  talk=status().get("talk", [])[-2:], spoke=answered[-1:] if answered else [])
            await quiet()

            # ---- a third dump from the dock, discarded by voice ----
            before = len(INBOX)
            await page.js("document.getElementById('listen').click()")
            again = await until(lambda: (dump() or {}).get("state") == "dumping", 10)
            await say(browser, "Maybe the cache should live per merchant.", settle=3)
            kept = await until(lambda: (dump() or {}).get("thoughts"), 15)
            await say(browser, "Discard.")
            dropped = await until(lambda: dump() is None, 15)
            back = await page.until("document.getElementById('dump').hidden && document.getElementById('listen-label').textContent === 'Brain dump'", 5)
            check("the dock starts a dump, and \"discard\" by voice ends it with nothing sent",
                  bool(again) and bool(kept) and bool(dropped) and bool(back) and len(INBOX) == before and bool(log_lines("brain dump discarded")))
            errors = await page.js("window.__errors")
            check("no page errors", not errors, errors=errors)
    finally:
        inbox.close()
        Path(inbox_path).unlink(missing_ok=True)
        chrome.terminate()
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page brain dump)")


asyncio.run(main())
