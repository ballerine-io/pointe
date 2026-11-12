"""Challenge me in the page, live: one synthetic session (lantern) dropped a Redis retry queue because it lost retries on a
restart, and its record holds a key. The test's own call lays out a plan that brings the queue back, then says
"challenge this": the voice argues against it, grounded in lantern's record, without the key; "fine, do it, send that to
lantern" sends nothing; a rebuttal gets the next objection; "End challenge" on the page gets a one-sentence verdict, and
only a fresh "send that to lantern" afterwards is dispatched. Then: the page's Challenge button, Close, typed start and
end, push to talk (unpressed words do not reach it), a meeting ends it with no verdict and refuses a new one.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-chl CLAUDE_VOICE_DAEMON_PORT=7981 CLAUDE_VOICE_TLS_PORT=7581 POINTE_CHROME_PORT=7984 \
     uv run python -u -I tests/e2e/page_challenge.py
Calls paid APIs (the brain, the reader, the voice, Soniox, ElevenLabs for the user's voice, Gemini to transcribe the bot).
Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, Browser, fresh_state, stop_daemon, transcribe  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7984"))  # inside this suite's own port range
KEY = "sk-proj-TESTONLYc9h8l7e6n5g4e3m2e1a0b9c8"
GROUNDED = r"restart|lost|lose|losing|41|forty|outbox|drop|in-flight|in flight"


def seed(folder: Path) -> Path:
    stamp = datetime.fromtimestamp(time.time() - 600, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    lines = [
        ("user", "Can we keep the webhook retries for Velloria Freight on the Redis queue?"),
        ("assistant", "No: on the restart test the Redis retry queue lost 41 in-flight webhook retries, so I removed it and "
                      f"moved retries into the transactional outbox. The test run used OPENAI key {KEY}."),
        ("user", "Ok, keep the outbox. Zero lost webhooks during cutover is the bar."),
        ("assistant", "Understood. The outbox poller is built; three integration tests still fail."),
    ]
    entries = []
    for who, text in lines:
        content = text if who == "user" else [{"type": "text", "text": text}]
        message = {"role": who, "content": content, **({} if who == "user" else {"stop_reason": "end_turn"})}
        entries.append({"type": who, "message": message, "timestamp": stamp})
    path = folder / "lantern.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


def chl() -> dict | None:
    return call("/voice/status")["challenge"]


def items(kind: str) -> list[str]:
    c = chl() or {"items": []}
    return [i["text"] for i in c["items"] if i["kind"] == kind]


INBOX: list[str] = []  # what reached lantern: its inbox socket, read by this test


async def serve_inbox(path: str):
    async def take(reader, writer):
        INBOX.extend(line.decode() for line in (await reader.read()).splitlines() if b'"user"' in line)
        writer.close()
    return await asyncio.start_unix_server(take, path=path)


def bot_turns() -> int:
    return sum(1 for x in call("/voice/status")["talk"] if x["who"] == "assistant")


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


def post(path: str, body: dict) -> int:
    try:
        call(path, body)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    (STATE / "prefs.json").unlink(missing_ok=True)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-challenge-e2e-"))
    folder = work / "velloria-webhooks"
    folder.mkdir()
    inbox_path = f"/tmp/chl-inbox-{os.getpid()}.sock"
    inbox = await serve_inbox(inbox_path)
    call("/voice/register", {"id": f"chl-lantern-{os.getpid()}", "cwd": str(folder), "pid": os.getpid(), "name": "lantern",
                             "name_given": True, "transcript": str(seed(folder)), "inbox_socket": inbox_path})
    browser = Browser(echo_gain=float(os.environ.get("POINTE_ECHO_GAIN", "0.3")))  # speakers into the mic, as in a room
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    url = f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        calm = 0
        for _ in range(60):  # a cold daemon stalls its loop for seconds on its first vendor import: dial once it is past it
            t = time.time()
            call("/voice/status")
            calm = calm + 1 if time.time() - t < 0.3 else 0
            if calm >= 3:
                break
            await asyncio.sleep(1)
        await browser.connect()
        await until(lambda: call("/voice/status")["connected"], 15)
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as socket:
            page = Page(socket)
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('chlbtn')", 10)
            await quiet(60)  # the greeting

            # ---- by voice: a plan, then "challenge this" ----
            turns = bot_turns()
            await browser.say("Don't send anything yet. Here's my plan: we put the webhook retries back on a Redis queue, so Velloria ships on Thursday.")
            await until(lambda: bot_turns() > turns, 30)  # its reply, heard to the end: "challenge this" is not a barge-in
            await until(lambda: call("/voice/status")["speaking"] == "bot", 8, 0.1)
            await quiet()
            await asyncio.sleep(2)
            t0 = time.time()
            await browser.say("Challenge this.")
            on = await until(lambda: (chl() or {}).get("on"), 25)
            first = await until(lambda: items("objection"), 40)
            await quiet()
            panel = await page.until("!document.getElementById('challenge').hidden && document.getElementById('chl-plan').textContent", 10)
            label = await page.js("document.getElementById('chl-label').textContent")
            mode = call("/voice/status")["mode_state"]["mode"]
            await page.shot("chl-1-objection")
            check("\"challenge this\" starts it: the mode is challenge, the page shows the plan and End challenge",
                  bool(on) and mode == "challenge" and "Redis" in str(panel) and label == "End challenge", plan=panel, mode=mode)
            await asyncio.sleep(4)  # the rig's speaker echo can reach the ears as words: the voice may answer that first
            objection = " ".join(items("objection"))
            spans = browser.speaker.speech_spans(since=t0)
            heard = " ".join(await asyncio.gather(*[transcribe(browser.speaker.audio(a, b)) for a, b in spans])).lower()
            check("the objections are spoken and grounded in lantern's record (the retries lost on restart)",
                  bool(re.search(GROUNDED, objection.lower())) and bool(heard.strip()), objection=objection, heard=heard[:300])

            # ---- a send during it reaches nothing ----
            turns, before = bot_turns(), len(INBOX)  # the plan itself may have been sent before the challenge
            await browser.say("Fine, do it. Send that to lantern.")
            await until(lambda: bot_turns() > turns, 30)
            await quiet()
            blocked = [r for r in call("/voice/status")["recent"] if "challenge" in r["how"]]
            check("\"fine, do it, send that to lantern\" sends nothing while it is on (nothing reaches lantern's inbox)",
                  len(INBOX) == before and (chl() or {}).get("on"), blocked=blocked[-2:], said=call("/voice/status")["talk"][-1:])

            # ---- a rebuttal gets the next point ----
            n = len(items("objection"))
            await browser.say("We'd persist the Redis queue to disk with append-only mode, so a restart keeps every retry.")
            got = await until(lambda: len(items("objection")) > n and items("rebuttal"), 40)
            await quiet()
            rendered = await page.until("[...document.querySelectorAll('#chl-items .who')].map(w => w.textContent).join(',')", 5)
            check("a rebuttal is recorded and answered, and the page lists Objection and You",
                  bool(got) and "You" in str(rendered) and "Objection" in str(rendered), rendered=rendered)

            # ---- End challenge on the page: a verdict; then only a fresh send goes ----
            await page.js("document.getElementById('chl-end').click()")
            verdict = await until(lambda: (chl() or {}).get("verdict"), 40)
            await quiet()
            ended = await page.until("document.getElementById('chl-h').textContent === 'Challenge ended' && "
                                     "!document.getElementById('chl-close').hidden", 10)
            await page.shot("chl-2-verdict")
            check("End challenge gets a short verdict, shown as Challenge ended with Close",
                  bool(verdict) and len(str(verdict).split()) <= 45 and bool(ended), verdict=verdict)
            everything = json.dumps(call("/voice/status")) + json.dumps(call("/voice/notes?since=0")) + heard
            check("the key in lantern's record is never said, shown or stored", KEY not in everything and "TESTONLY" not in everything)
            before = len(INBOX)
            await browser.say("Now send that to lantern: persist the retry queue before moving it.")
            dispatched = await until(lambda: len(INBOX) > before, 30)
            await asyncio.sleep(3)
            await quiet()
            check("after the end, a fresh \"send that to lantern\" reaches lantern's inbox once", bool(dispatched) and len(INBOX) == before + 1,
                  inbox=[x[:160] for x in INBOX])
            await page.js("document.getElementById('chl-close').click()")
            closed = await page.until("document.getElementById('challenge').hidden", 5)
            check("Close hides the ended challenge", bool(closed))

            # ---- the dock button starts one; typed words end it ----
            await page.js("document.getElementById('chlbtn').click()")
            tapped = await until(lambda: (chl() or {}).get("on"), 20)
            await until(lambda: items("objection"), 40)
            await quiet()
            await page.js("document.getElementById('typed').disabled = false; document.getElementById('typed').value = 'end challenge'; "
                          "document.getElementById('compose').requestSubmit()")
            typed_end = await until(lambda: chl() and not chl()["on"], 15)
            await until(lambda: (chl() or {}).get("verdict"), 40)
            await quiet()
            check("the Challenge button starts one, and typed \"end challenge\" ends it", bool(tapped) and bool(typed_end))

            # ---- push to talk: words without a press never reach it ----
            call("/voice/prefs", {"microphone": "ptt"})
            assert post("/voice/challenge", {"action": "start"}) == 200
            await until(lambda: items("objection"), 40)
            await quiet()
            rebuttals = len(items("rebuttal"))
            await browser.say("That risk does not apply because we have a second region.")
            await asyncio.sleep(8)
            unpressed = len(items("rebuttal")) == rebuttals
            await browser.control({"type": "ptt", "open": True, "at": int(time.time() * 1000)})
            _, end = await browser.say("That risk does not apply because we have a second region.")
            await asyncio.sleep(end - time.time() + 0.6)
            await browser.control({"type": "ptt", "open": False, "at": int(time.time() * 1000)})
            pressed = await until(lambda: len(items("rebuttal")) > rebuttals, 20)
            await quiet()
            check("in push to talk, words without a press do not reach the challenge; with a press they do",
                  unpressed and bool(pressed), rebuttals=items("rebuttal"))
            call("/voice/prefs", {"microphone": "always"})

            # ---- a meeting ends it with no verdict, and refuses a new one ----
            call("/voice/meeting", {"action": "start", "mode": "listening", "consent": True})
            stopped = await until(lambda: chl() and not chl()["on"], 15)
            no_verdict = (chl() or {}).get("verdict") is None
            refused = post("/voice/challenge", {"action": "start"}) == 409
            disabled = await page.until("document.getElementById('chlbtn').disabled", 5)
            await page.shot("chl-3-meeting")
            check("a meeting ends the challenge without a verdict; the button is disabled and the daemon refuses one (409)",
                  bool(stopped) and no_verdict and refused and bool(disabled), status=chl())
            call("/voice/meeting", {"action": "end"})
            await asyncio.sleep(2)
            call("/voice/meeting", {"action": "discard"})

            errors = await page.js("window.__errors")
            check("no page errors", not errors, errors=errors)
    finally:
        inbox.close()
        Path(inbox_path).unlink(missing_ok=True)
        chrome.terminate()
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page challenge)")


asyncio.run(main())
