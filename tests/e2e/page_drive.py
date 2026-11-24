"""Drive & walk mode, live: a stand-in phone on a real call (synthetic speech), and the page in a real (headless) Chrome.

The phone says "Drive mode."; the page shows the drive bar and no typing box (the page has no Drive button: drive mode is
the phone's to start; `POST /voice/drive` stands in for it here, and the bar's "I've stopped" ends it). A session asks to
run `rm -rf build`: the voice says it waits until the user stops, the page's card has no buttons, a spoken yes approves
nothing and a no denies it. `git status` is read out and a spoken yes approves it. A request carrying a credential is
never said; a yes does nothing; "I've stopped" on the page leaves drive mode and its normal card approves it with a
click. Hanging up leaves drive mode. Every session, path and command here is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-drv CLAUDE_VOICE_DAEMON_PORT=7986 CLAUDE_VOICE_TLS_PORT=7586 POINTE_CHROME_PORT=7989 \
     uv run python -u -I tests/e2e/page_drive.py
Takes about three minutes. Calls paid APIs (ears, brain, mouth, and ElevenLabs for the user's voice). Screenshots go to
$POINTE_SHOTS.
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
from phone_socket import IN_RATE, Phone, resample  # noqa: E402
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, log_lines, phone_key, stop_daemon, synth  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7989"))
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-drive-shots-"))
URL = DAEMON.replace("http", "ws", 1) + "/voice/phone"


def status() -> dict:
    return call("/voice/status")


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


async def quiet(phone: Phone, timeout: float = 40) -> None:
    """The bot finished talking, then a breath: a yes begun over the bot never counts, by design."""
    await until(lambda: status()["speaking"] != "bot", timeout)
    await phone.silence(1.6)


async def say(phone: Phone, text: str) -> None:
    await phone.send(resample(await synth(text), RATE, IN_RATE))
    await phone.silence(1.5)


def ask(session_id: str, tool: str, tool_input: dict) -> asyncio.Task:
    """The session's PermissionRequest hook: held by the daemon until the user answers."""
    return asyncio.create_task(asyncio.to_thread(call, "/voice/permission-hook",
                                                 {"session_id": session_id, "tool_name": tool, "tool_input": tool_input}))


def decision(reply: dict) -> str | None:
    return ((reply or {}).get("hookSpecificOutput") or {}).get("decision", {}).get("behavior")


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-drive-e2e-"))
    shop = work / "acme-shop"
    shop.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(shop)], check=True)
    (work / "transcript.jsonl").touch()
    sid = f"page-drive-{os.getpid()}"
    call("/voice/register", {"id": sid, "cwd": str(shop), "pid": os.getpid(), "name": "orchard", "name_given": True,
                             "transcript": str(work / "transcript.jsonl")})
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key = phone_key()
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as cdp, \
                connect(URL, additional_headers={"Authorization": f"Bearer {key}"}, max_size=None) as socket:
            page = Page(cdp)
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('drivebar')", 10)
            no_button = await page.js("!document.getElementById('drivebtn') && !window.toggleDrive && !DOCK_MORE.includes('drivebtn')")
            check("the page has no Drive button: drive mode is the phone's to start", bool(no_button))
            phone = Phone(socket)
            listening = asyncio.create_task(phone.listen())
            await phone.silence(6)
            await quiet(phone, 30)  # the greeting

            # ---- entering by voice, and from the phone's button (POST /voice/drive) ----
            call("/voice/drive", {"on": True})
            by_post = await page.until("!document.getElementById('drivebar').hidden && document.body.classList.contains('driving')", 5)
            call("/voice/drive", {"on": False})
            off_again = await page.until("document.getElementById('drivebar').hidden", 5)
            check("the phone's Drive switch (POST /voice/drive) shows the bar on the page, and off hides it", bool(by_post) and bool(off_again))
            await phone.silence(1.5)  # the daemon is about to say "Back to normal.", after "Drive mode. …": the same words
            await quiet(phone, 30)    # said over it are its own echo, by the echo rule, and are dropped
            await phone.silence(2)
            await say(phone, "Drive mode.")
            on = await until(lambda: status()["drive"]["on"], 20)
            shown = await page.until("!document.getElementById('drivebar').hidden && document.body.classList.contains('driving')"
                                     " && getComputedStyle(document.getElementById('compose')).display === 'none'", 5)
            spoke = await until(lambda: log_lines(r"speak: [\"']Drive mode\. Short answers"), 10)
            await page.shot("drv-1-on")
            check("\"Drive mode.\" by voice turns it on: the daemon says so, the page shows the bar and hides typing",
                  bool(on) and bool(shown) and bool(spoke) and status()["mode_state"]["mode"] == "drive",
                  drive=status()["drive"], mode=status()["mode_state"])
            await quiet(phone)

            # ---- a destructive request waits ----
            rm = ask(sid, "Bash", {"command": "rm -rf build", "description": "Clean the build"})
            waited = await until(lambda: log_lines(r"speak: .*won't approve that while you drive"), 30)
            card = await page.until("document.querySelector('#attention .ask.drive') && document.querySelector('#attention').innerText", 10)
            buttons = await page.js("document.querySelectorAll('#attention button').length")
            await page.shot("drv-2-not-for-the-road")
            check("rm -rf build: the voice says it waits; the card says so and has no buttons",
                  bool(waited) and bool(card) and "Not for the road" in (card or "") and buttons == 0,
                  card=card, buttons=buttons, said=(waited or [""])[-1][-200:])
            await quiet(phone)
            await say(phone, "Yes, go ahead.")
            await asyncio.sleep(4)
            check("a spoken yes approves nothing that is not safe from the road",
                  not rm.done() and not log_lines(r"permission orchard/\w+ -> allow"),
                  pending=status()["drive"]["pending"], log=log_lines(r"permission orchard|drive mode")[-4:])
            await quiet(phone)
            await say(phone, "No, don't.")
            denied = await until(lambda: rm.done(), 20)
            check("a no denies it", bool(denied) and decision(rm.result()) == "deny", reply=rm.result() if rm.done() else None)
            await quiet(phone)

            # ---- a readable, safe request: a yes approves it ----
            gs = ask(sid, "Bash", {"command": "git status", "description": "Show the working tree"})
            read = await until(lambda: log_lines(r"speak: 'orchard wants to run: git status\. Should it\?'"), 30)
            hint = await page.until("document.querySelector('#attention .ask.drive') && document.querySelector('#attention').innerText", 10)
            await page.shot("drv-3-say-yes")
            await quiet(phone)
            await say(phone, "Yes, go ahead.")
            approved = await until(lambda: gs.done(), 20)
            check("git status is read out and a spoken yes approves it",
                  bool(read) and "Say yes or no" in (hint or "") and bool(approved) and decision(gs.result()) == "allow",
                  hint=hint, reply=gs.result() if gs.done() else None)
            await quiet(phone)

            # ---- a credential is never said; a tap answers it after "I've stopped" ----
            secret = ask(sid, "Bash", {"command": "echo password=hunter2222 >> notes.txt", "description": "Note it"})
            withheld = await until(lambda: log_lines(r"speak: .*can't read out\. It waits until you stop"), 30)
            await quiet(phone)
            await say(phone, "Yes, go ahead.")
            await asyncio.sleep(4)
            leaked = [l for l in log_lines(r"speak: ") if "hunter2222" in l]
            check("a request with a credential is never said, and a spoken yes does nothing",
                  bool(withheld) and not secret.done() and not leaked, leaked=leaked)
            await page.js("document.getElementById('drive-stop').click()")
            off = await until(lambda: not status()["drive"]["on"], 10)
            approve = await page.until("!![...document.querySelectorAll('#attention button')].find(b => b.textContent === 'Approve')", 10)
            await page.shot("drv-4-stopped")
            await page.js("[...document.querySelectorAll('#attention button')].find(b => b.textContent === 'Approve').click()")
            tapped = await until(lambda: secret.done(), 15)
            check("\"I've stopped\" leaves drive mode, and the normal card's Approve answers it",
                  bool(off) and bool(approve) and bool(tapped) and decision(secret.result()) == "allow",
                  reply=secret.result() if secret.done() else None)
            await quiet(phone)

            # ---- the call ending ends the mode ----
            await say(phone, "Drive mode.")
            again = await until(lambda: status()["drive"]["on"], 20)
            call("/voice/hung-up", {})
            listening.cancel()
        ended = await until(lambda: not status()["drive"]["on"] and not status()["connected"], 20)
        bar = await page_hidden(target)
        check("hanging up leaves drive mode", bool(again) and bool(ended) and bar, drive=status()["drive"])
    finally:
        chrome.terminate()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page drive mode)")


async def page_hidden(target: dict) -> bool:
    async with connect(target["webSocketDebuggerUrl"], max_size=None) as cdp:
        page = Page(cdp)
        hidden = await page.until("document.getElementById('drivebar').hidden && !document.body.classList.contains('driving')", 5)
        errors = await page.js("window.__errors")
        check("no page errors", not errors, errors=errors)
        return bool(hidden)


asyncio.run(main())
