"""The conversation itself, live: a stand-in user on a real call (synthetic speech) and the page in a real (headless)
Chrome, with two synthetic sessions (lantern, billing) that listen on inbox sockets and whose transcripts this test writes.

Checked, in order: the page shows the plugin's version; a short question gets a short answer and "in detail" gets a
longer one within its limit; a click on a session is announced with the owner's fixed words and pins the voice to it,
and a request then reaches that session only; back in orchestrator mode a request that names billing reaches billing
only; "hold on" keeps the voice quiet through pauses and "go ahead" sends all of it as one turn; a Hebrew sentence
paused after a conjunction is one turn; Settings saves Quick and Patient, and each waits its own time (0.4 s, 1.8 s of
quiet) before a turn is taken; two sessions that finish while the user talks are not spoken over them or told inside
their answer, and then come as one turn; a readable request is read out and a spoken yes approves it; one that cannot
be read out whole is not said, a spoken yes approves nothing and a tap approves it; a spoken no denies; a brain dump
takes "add more", is read back whole on request, and is still in review after the daemon restarts, where the voice
says so on the next call; "Challenge it" takes the plan; the voice model's history stays under its budget; dark and
light themes apply; nothing runs off a phone-width window; no page errors. The page's own Holding line is in
tests/test_turn_taking.py (this call is the test's, not the page's). Every session, path and thought here is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-conv CLAUDE_VOICE_DAEMON_PORT=7941 CLAUDE_VOICE_TLS_PORT=7541 POINTE_CHROME_PORT=7944 \
     uv run python -u -I tests/e2e/page_conversation.py [section,...]
Sections: basics, modes, hold, patience, updates, approvals, dump, page (default: all, in that order).
Takes about ten minutes. Calls paid APIs (the brain, the reader, Soniox, the mouth, ElevenLabs for the user's voice).
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7944"))
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-conv-shots-"))
SECTIONS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["basics", "modes", "hold", "patience", "updates", "approvals", "dump", "page"]
INBOX: dict[str, list[str]] = {}  # what reached each session's inbox socket
HISTORY_TOKENS = 24_000  # brain.HISTORY_TOKENS: the budget a long call is trimmed to


def status() -> dict:
    return call("/voice/status")


def dump() -> dict | None:
    return status()["brain_dump"]


def thoughts() -> str:
    return " ".join(t["text"] for t in (dump() or {}).get("thoughts", [])).lower()


def append(path: Path, record: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def finished(path: Path, asked: str, final: str) -> None:
    """One finished turn in Claude Code's transcript shape."""
    append(path, {"type": "user", "message": {"role": "user", "content": asked}})
    append(path, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": final}],
                                                   "stop_reason": "end_turn"}})


async def session(work: Path, name: str) -> tuple[str, Path]:
    sid = f"conv-{name}-{os.getpid()}"
    cwd = work / name
    cwd.mkdir()
    transcript = work / f"{sid}.jsonl"
    transcript.touch()
    path = f"/tmp/conv-inbox-{name}-{os.getpid()}.sock"
    Path(path).unlink(missing_ok=True)
    INBOX[name] = []

    async def take(reader, writer):
        INBOX[name] += [line.decode() for line in (await reader.read()).splitlines() if line.strip()]
        writer.close()

    await asyncio.start_unix_server(take, path)
    call("/voice/register", {"id": sid, "cwd": str(cwd), "pid": os.getpid(), "name": name, "name_given": True,
                             "transcript": str(transcript), "inbox_socket": path})
    return sid, transcript


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


def unsaid() -> bool:
    """Words handed to the mouth whose sound has not ended: the log says "speak:" at the hand-off and "bot said:" at the end."""
    spoke, said = log_lines(r" speak: "), log_lines(r"bot said: ")
    return bool(spoke) and bool(spoke[-1].split("speak: ", 1)[1].strip().strip("'\"")) and (not said or log_time(spoke[-1]) > log_time(said[-1]))


async def quiet(timeout: float = 45) -> None:
    """The voice has said all it was handed and stopped; then a breath, as a person leaves. A yes begun over the voice
    never counts, by design."""
    await asyncio.sleep(0.5)
    await until(lambda: not unsaid() and status()["speaking"] is None, timeout)
    await asyncio.sleep(1.5)


async def say(browser: Browser, text: str, settle: float = 1.5) -> float:
    """Speaks it at real-time pace, then a pause; returns when the words ended."""
    _, end = await browser.say(text)
    await asyncio.sleep(max(0.0, end - time.time()) + settle)
    return end


def stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def spoke_since(t: float) -> list[str]:
    return [line.split("speak: ", 1)[1].strip().strip("'\"") for line in log_lines(r"speak: ") if line[:19] >= stamp(t)]


def heard_since(t: float) -> list[str]:
    return [line.split("user said: ", 1)[1].strip() for line in log_lines(r"user said: ") if line[:19] >= stamp(t)]


def log_time(line: str) -> float:
    """A log line's own time, to the millisecond."""
    whole = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
    ms = re.match(r"[,.](\d{3})", line[19:23])
    return whole + (int(ms.group(1)) / 1000 if ms else 0.0)


def words(text: str) -> int:
    return len(text.split())


def ask(session_id: str, tool: str, tool_input: dict) -> asyncio.Task:
    """The session's PermissionRequest hook: held by the daemon until the user answers."""
    return asyncio.create_task(asyncio.to_thread(call, "/voice/permission-hook",
                                                 {"session_id": session_id, "tool_name": tool, "tool_input": tool_input}))


def decision(reply: dict) -> str | None:
    return ((reply or {}).get("hookSpecificOutput") or {}).get("decision", {}).get("behavior")


async def answered(task: asyncio.Task, timeout: float) -> str | None:
    try:
        return decision(await asyncio.wait_for(asyncio.shield(task), timeout))
    except asyncio.TimeoutError:
        return None


async def set_patience(page: Page, value: str) -> list[str]:
    """Settings → Turn taking → the choice → Done, as a person does it; returns the choices offered."""
    await page.js("openSettings().then(() => true)")  # what the Settings button calls; resolved once the sheet holds the Mac's prefs
    await page.until("document.getElementById('settingssheet').classList.contains('open') && document.getElementById('pref-patience')", 10)
    shown = await page.js("[...document.getElementById('pref-patience').options].map(o => o.textContent.trim())")
    await page.js(f"document.getElementById('pref-patience').value = '{value}'; document.querySelector('#settingssheet .done').click()")
    await until(lambda: call("/voice/prefs").get("turns.patience") == value, 5)
    return shown


async def open_page(chrome_port: int):
    for _ in range(40):
        try:
            pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json", timeout=1).read())
            return next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("the page did not open")


async def calm() -> None:
    """A cold daemon stalls its loop for seconds on its first vendor import: dial once it is past it."""
    steady = 0
    for _ in range(60):
        t = time.time()
        status()
        steady = steady + 1 if time.time() - t < 0.3 else 0
        if steady >= 3:
            return
        await asyncio.sleep(1)


async def basics(browser: Browser, page: Page) -> None:
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    shown = await page.until("document.getElementById('ver').textContent", 10)
    check("the page shows the plugin's version", version in (shown or "") and status()["version"] == version, shown=shown, version=version)

    t0 = time.time()
    await say(browser, "What is a mutex, in programming?")
    short = await until(lambda: spoke_since(t0), 30)
    await quiet()
    short = " ".join(spoke_since(t0))
    check("a short question gets a short answer: at most 30 words", 0 < words(short) <= 30 and "mutex" in " ".join(heard_since(t0)).lower(),
          words=words(short), said=short, heard=heard_since(t0))
    t1 = time.time()
    await say(browser, "Explain that in detail, with an example.")
    await until(lambda: spoke_since(t1), 30)
    await quiet(60)
    long = " ".join(spoke_since(t1))
    check("asked for detail, the answer is longer, and still within 120 words", words(short) < words(long) <= 120,
          words=words(long), said=long[:300])


async def modes(browser: Browser, page: Page) -> None:
    await quiet()
    t0 = time.time()
    await page.js("[...document.querySelectorAll('#list .nm')]"
                  ".find(x => x.textContent.includes('lantern')).click()")
    line = await until(lambda: [s for s in spoke_since(t0) if "session lantern" in s.lower()], 20)
    pinned = await until(lambda: status()["mode"] == "session" and status()["active"] == "lantern", 5)
    lit = await page.until("document.getElementById('m-session').getAttribute('aria-pressed') === 'true' "
                           "|| document.getElementById('m-session').classList.contains('on')", 5)
    check("a click on a session is announced (\"I'm now in session lantern.\") and pins the voice to it",
          bool(line) and line[0].startswith("I'm now in session lantern.") and bool(pinned) and bool(lit),
          said=spoke_since(t0), mode=status()["mode"], active=status()["active"], lit=lit)
    await quiet()

    await say(browser, "Run the unit tests and tell me what fails.")
    sent = await until(lambda: INBOX["lantern"], 40)
    check("in session mode a request with no name goes to the pinned session, and to no other",
          bool(sent) and "test" in "\n".join(INBOX["lantern"]).lower() and not INBOX["billing"],
          lantern=INBOX["lantern"][-1:][:1], billing=INBOX["billing"])
    await quiet()

    await page.js("document.getElementById('m-orchestrator').click()")
    back = await until(lambda: status()["mode"] == "orchestrator", 5)
    before = len(INBOX["lantern"])
    await say(browser, "Ask billing to check the invoice totals for March.")
    routed = await until(lambda: INBOX["billing"], 40)
    check("in orchestrator mode a request that names billing reaches billing only",
          bool(back) and bool(routed) and "invoice" in "\n".join(INBOX["billing"]).lower() and len(INBOX["lantern"]) == before,
          billing=INBOX["billing"][-1:], lantern_new=INBOX["lantern"][before:])
    await quiet()


async def hold(browser: Browser, page: Page) -> None:
    await quiet()
    await say(browser, "Hold on.")
    held = await until(lambda: status()["hold"], 10)
    t0 = time.time()
    await say(browser, "I think the cache should live per merchant.", settle=4)
    await say(browser, "And every entry should expire after one hour.", settle=3)
    during = spoke_since(t0)
    still = status()["hold"]
    t1 = time.time()
    await say(browser, "Go ahead.")
    released = await until(lambda: status()["hold"] is None, 10)
    reply = await until(lambda: spoke_since(t1), 30)
    turn = " ".join(heard_since(t0)).lower()
    check("\"hold on\" starts a hold, and the voice stays quiet through two pauses",
          bool(held) and bool(still) and not during, during=during, hold=still)
    check("\"go ahead\" sends everything said as one turn, and the voice answers it",
          bool(released) and bool(reply) and len(heard_since(t0)) == 1 and "merchant" in turn and "hour" in turn,
          heard=heard_since(t0), reply=reply[-1:] if reply else [])
    await quiet()

    # Hebrew: a pause after "but" (אבל) is not the end of the sentence.
    first, second = "אני רוצה לבדוק את הקוד, אבל", "קודם תסביר לי בקצרה מה זה סמפור."
    await synth(first), await synth(second)  # made before the pause is timed
    await asyncio.sleep(1)
    _, first_end = await browser.say(first)
    await asyncio.sleep(max(0.0, first_end + 1.5 - time.time()))
    cut_in = browser.speaker.speech_spans(since=first_end)
    _, end = await browser.say(second)
    await asyncio.sleep(max(0.0, end - time.time()))
    await until(lambda: spoke_since(end), 30)
    heard = heard_since(first_end - 4)
    check("a Hebrew sentence paused after a conjunction is one turn, and nothing is said in the pause",
          not cut_in and len(heard) == 1 and "סמפור" in heard[0], cut_in=[round(a - first_end, 1) for a, _ in cut_in], heard=heard)
    await quiet()


async def taken_after(browser: Browser, text: str) -> dict:
    """How the daemon took these words as a turn: the settle it chose, and the silence there had been when it took them
    (from the voice detector's stop) and since the transcript came. The transcript's own lag varies by a second or two,
    so the end of the audio is not the clock to judge the setting by."""
    await quiet()
    await synth(text)
    _, end = await browser.say(text)
    await asyncio.sleep(max(0.0, end - time.time()))
    key = text.split()[1].lower()  # "parser", "exporter"
    took = await until(lambda: [line for line in log_lines(r"user said: ") if key in line.lower()], 20, every=0.1)
    await until(lambda: spoke_since(end), 30)
    settle = [line for line in log_lines(r"settling ") if key in line.lower()]
    if not took or not settle:
        return {}
    at = log_time(took[-1])
    stops = [log_time(line) for line in log_lines("User stopped speaking") if log_time(line) <= at]
    return {"settle": float(re.search(r"settling ([\d.]+) s", settle[-1]).group(1)), "after_stop": round(at - stops[-1], 2) if stops else None,
            "after_transcript": round(at - log_time(settle[-1]), 2)}


async def patience(browser: Browser, page: Page) -> None:
    shown = await set_patience(page, "quick")
    saved_quick = call("/voice/prefs").get("turns.patience") == "quick"
    quick = await taken_after(browser, "The parser reads the whole file before it starts.")
    await set_patience(page, "patient")
    saved_patient = call("/voice/prefs").get("turns.patience") == "patient"
    patient = await taken_after(browser, "The exporter writes the whole file before it stops.")
    await set_patience(page, "normal")
    check("Settings offers Quick, Normal and Patient, and Done saves the choice",
          shown == ["Quick", "Normal", "Patient"] and saved_quick and saved_patient, shown=shown, prefs=call("/voice/prefs").get("turns.patience"))
    check("Quick takes a whole sentence after 0.4 s of quiet and Patient only after 1.8 s",
          quick.get("settle") == 0.4 and quick["after_transcript"] < 0.8 and patient.get("settle") == 1.8 and patient["after_stop"] >= 1.7,
          quick=quick, patient=patient)
    await quiet()


async def updates(browser: Browser, page: Page, transcripts: dict[str, Path]) -> None:
    await quiet()
    await asyncio.sleep(6)  # past the gap after the last answer: the floor is free
    question = ("Let me think about the release plan out loud: first we freeze the branch, then we run the whole "
                "regression suite, and after that we tag it. What is a good name for that tag?")
    start, end = await browser.say(question)
    await asyncio.sleep(1.5)  # mid-sentence: both sessions finish now
    finished(transcripts["lantern"], "Run the unit tests.", "All 212 unit tests pass. Nothing else is needed from you.")
    finished(transcripts["billing"], "Check the invoice totals for March.",
             "The March invoice totals match the ledger: 1,480 invoices, no differences.")
    await asyncio.sleep(max(0.0, end - time.time()))
    over = [round(a - start, 1) for a, b in browser.speaker.speech_spans(since=start) if a < end]
    await until(lambda: spoke_since(end), 30)
    await quiet()
    first = spoke_since(start)
    news = lambda s: any(w in s.lower() for w in ("lantern", "billing", "invoice", "unit test"))  # noqa: E731
    came = await until(lambda: [s for s in spoke_since(start) if news(s)], 75)
    await quiet()
    await asyncio.sleep(8)  # a second update turn would start here
    told = [s for s in spoke_since(start) if news(s)]
    both = " ".join(told).lower()
    check("two sessions finish while the user talks: nothing is said over them, and their answer comes first",
          not over and bool(first) and not news(first[0]), over=over, first=first[:1])
    check("the two updates then come as one turn that names both sessions",
          bool(came) and len(told) == 1 and "lantern" in both and "billing" in both and words(told[0]) <= 45, told=told)
    await quiet()


async def approvals(browser: Browser, page: Page, ids: dict[str, str]) -> None:
    await quiet()
    await page.js("[...document.querySelectorAll('#list .nm')]"
                  ".find(x => x.textContent.includes('lantern')).click()")
    await until(lambda: status()["active"] == "lantern", 5)
    await quiet()
    await asyncio.sleep(6)  # the floor is free: a read-out waits for it like any update

    t0 = time.time()
    status_ask = ask(ids["lantern"], "Bash", {"command": "git status", "description": "Show the working tree status"})
    read = await until(lambda: [s for s in spoke_since(t0) if "status" in s.lower()], 40)
    card = await page.until("document.querySelector('#attention .ask') && document.querySelector('#attention').innerText", 10)
    await quiet()
    await say(browser, "Yes.")
    verdict = await answered(status_ask, 20)
    check("a readable request is read out, shown word for word on its card, and a spoken yes approves it",
          bool(read) and "git status" in (card or "") and verdict == "allow", read=read[:1], card=(card or "")[:160], verdict=verdict)
    await quiet()
    await asyncio.sleep(6)

    t1 = time.time()
    unreadable = "sudo rm -rf $BUILD_DIR/*"  # sudo, a variable and a glob: it cannot be read out whole
    delete_ask = ask(ids["lantern"], "Bash", {"command": unreadable, "description": "Delete the build folder"})
    told = await until(lambda: spoke_since(t1), 40)
    await page.until("(document.querySelector('#attention')?.innerText || '').includes('BUILD_DIR')", 10)
    await quiet()
    await say(browser, "Yes.")
    by_voice = await answered(delete_ask, 10)
    await quiet()
    await page.shot("conv-unreadable")
    await page.js("[...document.querySelectorAll('#attention button')].find(b => b.textContent === 'Approve').click()")
    by_tap = await answered(delete_ask, 15)
    check("a request that cannot be read out whole is not said, a spoken yes approves nothing, and the tap on its card approves it",
          bool(told) and not any("rm -rf" in s or "BUILD_DIR" in s for s in spoke_since(t1)) and by_voice is None and by_tap == "allow",
          told=spoke_since(t1)[:3], by_voice=by_voice, by_tap=by_tap)
    await quiet()
    await asyncio.sleep(6)

    t2 = time.time()
    diff_ask = ask(ids["lantern"], "Bash", {"command": "git diff --stat", "description": "Show a summary of the changes"})
    await until(lambda: [s for s in spoke_since(t2) if "diff" in s.lower() or "change" in s.lower()], 40)
    await quiet()
    await say(browser, "No.")
    denied = await answered(diff_ask, 20)
    check("a spoken no denies a request", denied == "deny", verdict=denied)
    await quiet()
    await page.js("document.getElementById('m-orchestrator').click()")
    await until(lambda: status()["mode"] == "orchestrator", 5)


async def brain_dump(browser: Browser, page: Page) -> Browser:
    await quiet()
    # ---- pinned to lantern: Send defaults to lantern; sent to the orchestrator instead, that one turn may reach billing ----
    await page.js("[...document.querySelectorAll('#list .nm')].find(x => x.textContent.includes('lantern')).click()")
    await until(lambda: status()["mode"] == "session" and status()["active"] == "lantern", 5)
    await quiet()
    await page.js("document.getElementById('listen').click()")
    await until(lambda: (dump() or {}).get("state") == "dumping", 10)
    await say(browser, "Ask billing to rerun the invoice check for April.", settle=3)
    await until(lambda: "april" in thoughts(), 25)
    await page.js("document.getElementById('dump-done').click()")
    await until(lambda: (dump() or {}).get("state") == "review", 45)
    await page.until("document.getElementById('dumpsheet').classList.contains('open') && document.getElementById('dump-text').value", 10)
    default = (dump() or {}).get("send_to") or {}
    picked = await page.js("document.getElementById('dump-session').value")
    check("a dump started while pinned to a session defaults its Send to that session",
          default.get("session") == "lantern" and not default.get("orchestrator") and picked == "lantern", send_to=default, picked=picked)
    await quiet()
    before = {name: len(got) for name, got in INBOX.items()}
    await page.js("document.getElementById('dump-session').value = ''; document.getElementById('dump-session').dispatchEvent(new Event('change'))")
    await page.js("document.getElementById('dump-send').click()")
    await page.js("document.getElementById('dump-send').click()")
    routed = await until(lambda: len(INBOX["billing"]) > before["billing"], 45)
    check("sent to the orchestrator from session mode, that one turn is routed by name (billing gets it, lantern does not), and the pin stays",
          bool(routed) and "april" in "\n".join(INBOX["billing"][before["billing"]:]).lower() and len(INBOX["lantern"]) == before["lantern"]
          and status()["mode"] == "session" and status()["active"] in ("lantern", "billing"),
          billing=INBOX["billing"][before["billing"]:], lantern_new=INBOX["lantern"][before["lantern"]:], mode=status()["mode"], active=status()["active"])
    await quiet()
    await page.js("document.getElementById('m-orchestrator').click()")
    await until(lambda: status()["mode"] == "orchestrator", 5)
    await quiet()

    await page.js("document.getElementById('listen').click()")
    await until(lambda: (dump() or {}).get("state") == "dumping", 10)
    await say(browser, "The checkout keeps timing out for some customers.", settle=3)
    await say(browser, "I think the retry loop around the payment provider has no backoff.", settle=3)
    await until(lambda: "backoff" in thoughts() or "back off" in thoughts(), 25)  # the words, not a count: an echo can land as one
    await page.js("document.getElementById('dump-done').click()")
    await until(lambda: (dump() or {}).get("state") == "review", 45)
    await page.until("document.getElementById('dumpsheet').classList.contains('open') && document.getElementById('dump-text').value", 10)
    await quiet()

    await page.js("document.getElementById('dump-more').click()")
    more = await until(lambda: (dump() or {}).get("state") == "dumping", 10)
    await say(browser, "Also, we must not touch the tax service this sprint.", settle=3)
    await until(lambda: "tax" in thoughts(), 25)
    await page.js("document.getElementById('dump-done').click()")
    await until(lambda: (dump() or {}).get("state") == "review" and "tax" in ((dump() or {}).get("prompt") or {}).get("text", "").lower(), 45)
    text = ((dump() or {}).get("prompt") or {}).get("text", "")
    check("\"Add more\" goes back to dumping, and the next Done folds the new thought into the same prompt",
          bool(more) and "tax" in text.lower() and ("retry" in text.lower() or "backoff" in text.lower()), prompt=text[:300])
    await page.until("document.getElementById('dumpsheet').classList.contains('open') && document.getElementById('dump-text').value.toLowerCase().includes('tax')", 10)
    await quiet()

    t0 = time.time()
    await page.js("document.getElementById('dump-read').click()")
    await until(lambda: [s for s in spoke_since(t0) if "tax" in s.lower()], 40)
    await quiet(90)
    read = " ".join(spoke_since(t0)).lower()
    check("\"Read it back\" has the voice read the prompt aloud, and the dump stays in review",
          "tax" in read and ("retry" in read or "backoff" in read or "back off" in read) and (dump() or {}).get("state") == "review",
          read=read[:300])

    # ---- the daemon restarts: the dump is still in review, and the next call says so ----
    await browser.close()
    shutil.copy(STATE / "daemon.log", STATE / "daemon.before-restart.log")  # the new daemon starts its log afresh
    stop_daemon()
    on_disk = (STATE / "brain_dump.json").exists()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    await calm()
    kept = dump() or {}
    again = Browser(echo_gain=browser.mic.echo_gain)
    t1 = time.time()
    await again.connect()
    await until(lambda: status()["connected"], 15)
    line = await until(lambda: [s for s in spoke_since(t1) if "brain dump" in s.lower()], 40)
    sheet = await page.until("document.getElementById('dumpsheet').classList.contains('open') && document.getElementById('dump-text').value.toLowerCase().includes('tax')", 20)
    check("a daemon restart keeps the dump: still in review with the same prompt, on the page, and the next call says it is there",
          on_disk and kept.get("state") == "review" and (kept.get("prompt") or {}).get("text") == text and bool(line) and bool(sheet),
          state=kept.get("state"), line=line[:1] if line else [], on_disk=on_disk)
    await quiet()

    t2 = time.time()
    await page.js("document.getElementById('dump-challenge').click()")
    on = await until(lambda: (status().get("challenge") or {}).get("on") and dump() is None, 20)
    objection = await until(lambda: spoke_since(t2), 45)
    await page.shot("conv-challenge")
    check("\"Challenge it\" takes the dump as the plan: the challenge is on, the dump is gone, and the voice objects",
          bool(on) and bool(objection), challenge=status().get("challenge"), said=objection[:1] if objection else [])
    await quiet(60)
    call("/voice/challenge", {"action": "end"})
    await until(lambda: not (status().get("challenge") or {}).get("on"), 20)
    await quiet(60)
    return again


async def the_page(browser: Browser, page: Page) -> None:
    tokens = status().get("tokens") or {}
    context = call("/voice/context")
    held = sum(row["est_tokens"] for row in context["breakdown"] if row["kind"] not in ("instructions", "tool definitions"))
    check("after the whole call the voice model's history is under its budget, and no turn timed out",
          0 < held <= HISTORY_TOKENS and not log_lines("took too long") and not log_lines("lost my connection"),
          held=held, tokens=tokens)

    for theme in ("dark", "light"):
        await page.js("document.getElementById('settingsbtn').click()")
        await page.until(f"document.getElementById('theme-{theme}')", 10)
        await page.js(f"document.getElementById('theme-{theme}').click()")
        applied = await page.until(f"document.documentElement.dataset.theme === '{theme}'", 5)
        ground = await page.js("getComputedStyle(document.body).backgroundColor")
        await page.shot(f"conv-theme-{theme}")
        check(f"Settings → Appearance → {theme.title()} applies at once", bool(applied), ground=ground)
        await page.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    await page.js("document.getElementById('settingsbtn').click(); document.getElementById('theme-system').click(); "
                  "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")

    for width in (1400, 390):
        await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": width < 600})
        await asyncio.sleep(1.5)
        fit = await page.js("({wide: document.documentElement.scrollWidth, view: innerWidth, "
                            "off: [...document.querySelectorAll('button, select, input, textarea')].filter(e => { const r = e.getBoundingClientRect(); "
                            "return r.width && r.height && getComputedStyle(e).visibility !== 'hidden' && (r.right > innerWidth + 1 || r.left < -1) "
                            "&& !e.closest('[hidden], .sheet:not(.open), #side:not(.open)'); }).map(e => e.id || e.textContent.trim().slice(0, 20))})")
        await page.shot(f"conv-width-{width}")
        check(f"at {width} px nothing runs off the screen and the talk controls are there",
              fit["wide"] <= fit["view"] + 1 and not fit["off"]
              and await page.js("['mic', 'listen', 'typed'].every(id => document.getElementById(id))"), fit=fit)
    await page.cdp("Emulation.clearDeviceMetricsOverride")
    errors = await page.js("window.__errors")
    check("no page errors", not errors, errors=errors)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    (STATE / "brain_dump.json").unlink(missing_ok=True)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-conv-e2e-"))
    ids, transcripts = {}, {}
    for name in ("lantern", "billing"):
        ids[name], transcripts[name] = await session(work, name)
    browser = Browser(echo_gain=float(os.environ.get("POINTE_ECHO_GAIN", "0.3")))  # speakers into the mic, as in a room
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await calm()
        await browser.connect()
        await until(lambda: status()["connected"], 15)
        target = await open_page(DEBUG_PORT)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as cdp:
            page = Page(cdp)
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('listen')", 10)
            await quiet(60)  # the greeting
            # A session's first finished turn is its join (not read out): each has one behind it before the checks, so a
            # later report is news whether or not a request reached that session first.
            for transcript in transcripts.values():
                finished(transcript, "/pointe:voice", "Joined the voice call.")
            await until(lambda: len(log_lines("the join itself, not read out")) >= len(transcripts), 40)
            if "basics" in SECTIONS:
                await basics(browser, page)
            if "modes" in SECTIONS:
                await modes(browser, page)
            if "hold" in SECTIONS:
                await hold(browser, page)
            if "patience" in SECTIONS:
                await patience(browser, page)
            if "updates" in SECTIONS:
                await updates(browser, page, transcripts)
            if "approvals" in SECTIONS:
                await approvals(browser, page, ids)
            if "dump" in SECTIONS:
                browser = await brain_dump(browser, page)
            if "page" in SECTIONS:
                await the_page(browser, page)
    finally:
        for name in INBOX:
            Path(f"/tmp/conv-inbox-{name}-{os.getpid()}.sock").unlink(missing_ok=True)
        chrome.terminate()
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page conversation)")


asyncio.run(main())
