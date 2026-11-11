"""Audio briefings in the page, live: three synthetic sessions did work overnight (lantern waits on a permission whose
command holds a password, billing failed with a key in its output, docs is done). The test's own call asks "brief me
on the night"; the voice says it, most urgent first, without the password or the key, and a yes after it approves
nothing. In the page: the Briefing sheet (start, Skip, Stop, Go on, the history), a question pauses it, push to talk
pauses it, a meeting stops it and refuses a new one, the schedule in Settings raises a "ready" card, and "Hear it"
plays the one that waits without reading the sessions again.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-brf CLAUDE_VOICE_DAEMON_PORT=7955 CLAUDE_VOICE_TLS_PORT=7555 \
     uv run python -u -I tests/e2e/page_briefing.py
Takes about six minutes. Calls paid APIs (the reader, the voice, Soniox, ElevenLabs for the user's voice). Screenshots go
to $POINTE_SHOTS.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon, transcribe  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7956"))  # inside this suite's own port range
PASSWORD, KEY = "hunter2-orchard", "sk-proj-TESTONLYa1b2c3d4e5f6g7h8i9j0"
NIGHT = time.time() - 3 * 3600


def stamp(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seed(work: Path, name: str, lines: list[tuple[str, str]]) -> Path:
    """A synthetic Claude Code transcript, stamped three hours ago."""
    path = work / f"{name}.jsonl"
    entries = []
    for i, (who, text) in enumerate(lines):
        t = stamp(NIGHT + i * 60)
        if who == "user":
            entries.append({"type": "user", "message": {"role": "user", "content": text}, "timestamp": t})
        else:
            entries.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                                                             "stop_reason": "end_turn"}, "timestamp": t})
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


SESSIONS = {
    "lantern": [("user", "Write the migration that adds the invoice_due column, and run it on staging."),
                ("assistant", "The migration is written and tested locally. Running it on staging needs your approval.")],
    "billing": [("user", "Run the checkout test suite."),
                ("assistant", f"3 of 42 checkout tests failed: rounding in the ledger total. The run used OPENAI key {KEY}. "
                              "I have not fixed them yet.")],
    "docs": [("user", "Publish the onboarding guide."),
             ("assistant", "The onboarding guide is published. All links checked.")],
}


def register(work: Path) -> dict[str, str]:
    ids = {}
    for name, lines in SESSIONS.items():
        sid = f"brf-{name}-{os.getpid()}"
        folder = work / name
        folder.mkdir()
        path = seed(folder, name, lines)
        call("/voice/register", {"id": sid, "cwd": str(folder), "pid": os.getpid(), "name": name, "name_given": True,
                                 "transcript": str(path)})
        ids[name] = sid
    return ids


def hold_permission(session_id: str, out: dict) -> None:
    """lantern's harness asks to run a command whose text holds a password; held until answered."""
    body = json.dumps({"session_id": session_id, "tool_name": "Bash", "tool_input": {
        "command": f"psql postgres://admin:{PASSWORD}@db.example.test/staging -f add_invoice_due.sql",
        "description": "Run the migration on staging"}}).encode()
    request = urllib.request.Request(f"{DAEMON}/voice/permission-hook", data=body, method="POST", headers={
        "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}", "Content-Type": "application/json"})
    try:
        out["answer"] = json.loads(urllib.request.urlopen(request, timeout=900).read())
    except Exception as e:
        out["error"] = type(e).__name__


def brf() -> dict:
    return call("/voice/status")["briefing"]


def said_since(_t: float) -> str:
    """What the bot said since t, from the daemon's own conversation record (the talk pane)."""
    turns = call("/voice/status")["talk"]
    return " ".join(x["text"] for x in turns if x["who"] == "assistant")


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


async def quiet(timeout: float = 40) -> None:
    await until(lambda: call("/voice/status")["speaking"] is None, timeout)
    await asyncio.sleep(1.5)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    for stale in ("briefings.json", "prefs.json"):
        (STATE / stale).unlink(missing_ok=True)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-briefing-e2e-"))
    ids = register(work)
    verdict: dict = {}
    browser = Browser()  # no simulated speaker echo: an echoed "or say no" read-out once denied the request before the briefing
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    url = f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await browser.connect()  # a permission is held for the voice only while a call is up
        await until(lambda: call("/voice/status")["connected"], 15)
        threading.Thread(target=hold_permission, args=(ids["lantern"], verdict), daemon=True).start()
        held = await until(lambda: any(s["waiting"] for s in call("/voice/status")["sessions"]), 15)
        check("lantern's permission is held for the voice", bool(held))
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as socket:
            page = Page(socket)
            await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('briefbtn')", 10)
            await quiet(60)  # the greeting and the permission read-out

            # ---- the sheet, before any briefing ----
            await page.js("document.getElementById('briefbtn').focus()")
            await page.js("document.getElementById('briefbtn').click()")
            opened = await page.until("document.getElementById('briefsheet').classList.contains('open') && document.activeElement.id", 5)
            empty = await page.until("document.getElementById('brf-list').textContent", 5)
            enabled = await page.js("!document.getElementById('brf-go').disabled")
            await page.shot("brf-0-sheet")
            check("the Briefing button opens the sheet with Brief me focused, enabled on a live call, and no history yet",
                  opened == "brf-go" and empty == "No briefings yet." and bool(enabled), focus=opened, history=empty)
            await page.js("closeSheet('briefsheet')")

            # ---- by voice: brief me on the night ----
            t0 = time.time()
            await browser.say("Brief me on the night.")
            building = await until(lambda: brf()["building"] or brf()["playing"], 25)
            playing = await until(lambda: brf()["playing"], 60)
            await page.js("document.getElementById('briefbtn').click()")
            line = await page.until("document.getElementById('brf-state').textContent", 10)
            controls = await page.js("!document.getElementById('brf-skip').hidden && !document.getElementById('brf-stop').hidden "
                                     "&& document.getElementById('brf-go').hidden")
            await page.shot("brf-1-playing")
            check("\"brief me on the night\" reads the sessions and plays; the sheet shows the part and Skip and Stop",
                  bool(building) and bool(playing) and str(line).startswith("Part ") and not str(line).startswith("Part 0") and bool(controls), line=line)
            done = await until(lambda: not brf()["playing"] and not brf()["paused"] and not brf()["building"], 150, 1)
            await quiet()
            spoken = said_since(t0).lower()
            spans = browser.speaker.speech_spans(since=t0)
            heard = (await transcribe(browser.speaker.audio(spans[0][0], spans[-1][1]))).lower() if spans else ""
            order = [spoken.find(n) for n in ("lantern", "billing", "docs")]
            check("the voice says it most urgent first: lantern (waits on you), then billing (failed), then docs (done)",
                  bool(done) and all(i >= 0 for i in order) and order == sorted(order), order=order, said=spoken[-600:])
            check("it is heard as audio, and the audio names the sessions", "lantern" in heard and "billing" in heard,
                  heard=heard[:400])
            latest = call("/voice/briefings/latest")["briefing"]
            everything = spoken + heard + json.dumps(call("/voice/briefings")) + (STATE / "briefings.json").read_text() \
                + json.dumps(call("/voice/notes?since=0"))
            check("no secret and no hidden permission text is said, stored or shown (password, key, the command)",
                  PASSWORD not in everything and KEY not in everything and "TESTONLY" not in everything
                  and "add_invoice_due.sql" not in everything and "db.example.test" not in everything,
                  sections=[s["session"] for s in latest["sections"]])
            check("the written briefing has the three sessions in order, with lantern waiting",
                  [s["session"] for s in latest["sections"]] == ["lantern", "billing", "docs"]
                  and latest["sections"][0]["status"] == "waiting", sections=[(s["session"], s["status"]) for s in latest["sections"]])

            # ---- a yes after it approves nothing ----
            before = call("/voice/status")
            pending = next(s for s in before["sessions"] if s["name"] == "lantern")["request_id"]
            await browser.say("Yes.")
            await asyncio.sleep(6)
            after = next(s for s in call("/voice/status")["sessions"] if s["name"] == "lantern")
            check("a yes right after the briefing approves nothing: the request is still pending (read out again instead)",
                  after["waiting"] and after["request_id"] == pending and "answer" not in verdict, verdict=verdict)
            await quiet()

            # ---- history in the sheet ----
            items = await page.until("document.querySelectorAll('#brf-list > li .sec').length", 10)
            chips = await page.js("[...document.querySelectorAll('#brf-list .chip')].map(c => c.textContent)")
            await page.shot("brf-2-history")
            check("the sheet's history writes the briefing out per session with its chip", items == 3
                  and chips[:3] == ["Needs you", "Failed", "Done"], chips=chips)

            # ---- by tap; a question pauses it; Go on continues ----
            await page.js("document.getElementById('brf-since').value = 'the night'; document.getElementById('brf-length').value = 'short'; "
                          "document.getElementById('brf-go').click()")
            await until(lambda: brf()["playing"], 60)
            await until(lambda: brf()["part"] >= 1, 20)
            await quiet(30)
            await browser.say("Wait, how many tests failed in billing?")
            paused = await until(lambda: brf()["paused"] == "question", 20)
            go_on = await page.until("!document.getElementById('brf-continue').hidden && document.getElementById('brf-state').textContent", 5)
            await page.shot("brf-3-paused")
            check("a question while it plays pauses it, and the sheet offers Go on", bool(paused) and str(go_on).startswith("Paused"),
                  state=go_on)
            await quiet()
            await page.js("document.getElementById('brf-continue').click()")
            resumed = await until(lambda: brf()["playing"] or not brf()["id"], 10)
            await until(lambda: not brf()["playing"] and not brf()["paused"], 120, 1)
            check("Go on resumes it, and it plays to the end", bool(resumed))
            await quiet()

            # ---- Skip by tap, Stop by voice ----
            await page.js("document.getElementById('brf-since').value = 'the night'; document.getElementById('brf-go').click()")
            await until(lambda: brf()["playing"] and brf()["part"] >= 1, 60)
            part = brf()["part"]
            await page.js("document.getElementById('brf-skip').click()")
            skipped = await until(lambda: brf()["part"] > part or not brf()["id"], 15)
            check("Skip goes on to the next session", bool(skipped), part_before=part, now=brf())
            await browser.say("Stop.")
            stopped = await until(lambda: not brf()["id"], 15)
            check("\"stop\" ends it", bool(stopped), status=brf())
            await quiet()

            # ---- push to talk: a press pauses it ----
            call("/voice/prefs", {"microphone": "ptt"})
            await page.js("document.getElementById('brf-since').value = 'the night'; document.getElementById('brf-go').click()")
            await until(lambda: brf()["playing"] and brf()["part"] >= 1, 60)
            await browser.control({"type": "ptt", "open": True, "at": int(time.time() * 1000)})
            pressed = await until(lambda: brf()["paused"] == "press", 10)
            await browser.control({"type": "ptt", "open": False, "at": int(time.time() * 1000)})
            again = await until(lambda: brf()["playing"] or not brf()["id"], 20)
            check("a push-to-talk press pauses it, and with no words it goes on after a few seconds", bool(pressed) and bool(again),
                  status=brf())
            await browser.control({"type": "ptt", "open": True, "at": int(time.time() * 1000)})
            await browser.say("Stop.")
            await asyncio.sleep(3)
            await browser.control({"type": "ptt", "open": False, "at": int(time.time() * 1000)})
            await until(lambda: not brf()["id"], 15)
            call("/voice/prefs", {"microphone": "always"})
            await quiet()

            # ---- a meeting stops it and refuses a new one ----
            await page.js("document.getElementById('brf-since').value = 'the night'; document.getElementById('brf-go').click()")
            await until(lambda: brf()["playing"], 60)
            call("/voice/meeting", {"action": "start", "mode": "listening", "consent": True})
            ended = await until(lambda: not brf()["id"], 15)
            blocked = await page.until("document.getElementById('brf-go').disabled && document.getElementById('brf-why').textContent", 5)
            try:
                call("/voice/briefings", {"action": "start"})
                refused = False
            except urllib.error.HTTPError as e:
                refused = e.code == 409
            await page.shot("brf-4-meeting")
            check("a meeting stops the briefing; Brief me is disabled and the daemon refuses one (409)",
                  bool(ended) and blocked == "Not during a meeting." and refused, why=blocked)
            call("/voice/meeting", {"action": "end"})
            await asyncio.sleep(2)
            call("/voice/meeting", {"action": "discard"})
            await page.js("closeSheet('briefsheet')")
            await quiet()

            # ---- the schedule: Settings, then a "ready" card, then Hear it ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open') && document.querySelectorAll('#brf-days button').length", 5)
            now = time.strftime("%H:%M")
            await page.js(f"document.getElementById('brf-sched').click(); document.getElementById('brf-time').value = '{now}'; "
                          "document.getElementById('brf-deflen').value = 'short'")
            await page.shot("brf-5-settings")
            await page.js("saveSettings()")
            await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            schedule = call("/voice/briefings")["schedule"]
            check("Settings → Briefings saves the time, the days and the length", schedule["time"] == now
                  and schedule["days"] == [0, 1, 2, 3, 4, 5, 6] and schedule["length"] == "short", schedule=schedule)
            reads = len(log_lines(r"job briefing/"))
            card = await page.until("document.getElementById('briefalert').textContent", 45, 1)
            await page.shot("brf-6-ready")
            check("at the time, the briefing is read with no ask and a ready card shows", f"Your {now} briefing is ready." in (card or ""),
                  card=card)
            reads_after_build = len(log_lines(r"job briefing/"))
            await page.js("[...document.querySelectorAll('#briefalert button')].find(b => b.textContent === 'Hear it').click()")
            heard_it = await until(lambda: brf()["playing"], 20)
            await until(lambda: not brf()["playing"] and not brf()["paused"], 120, 1)
            gone = await page.until("!document.getElementById('briefalert').textContent", 5)
            check("Hear it plays the waiting briefing without reading the sessions again, and the card goes",
                  bool(heard_it) and len(log_lines(r"job briefing/")) == reads_after_build > reads and bool(gone))
            call("/voice/briefings/schedule", {"time": ""})

            errors = await page.js("window.__errors")
            check("no page errors", not errors, errors=errors)
    finally:
        chrome.terminate()
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page briefings)")


asyncio.run(main())
