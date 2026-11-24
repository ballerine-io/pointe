"""Conflict alarm in the page, in a real (headless) Chrome with its own call, against the real reading model.

Two sessions in one repository report outcomes that cannot both hold ("the migration passed", then "the test on the new
column failed"): the page shows one card with both claims, the voice says it within 60 s of the second report, "Ask"
puts one side's question as the user's typed words (it reaches no other session), and Dismiss removes the card. Then
two sessions in another repository both read the same file and report the same thing: the reader is asked and no card
appears. Settings saves "Card only". Every session, name and file here is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-cfl CLAUDE_VOICE_DAEMON_PORT=7965 CLAUDE_VOICE_TLS_PORT=7565 \
     uv run python -u -I tests/e2e/page_conflict.py
Takes about four minutes. Calls paid APIs (the configured reader, brain, ears and mouth). Screenshots go to $POINTE_SHOTS.
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
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "9365"))
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-conflict-shots-"))

LANTERN_FINAL = ("The migration that adds the refund_reason column to the refunds table ran on staging and passed. "
                 "All migration checks are green.")
BILLING_FINAL = ("The refunds API test that reads the new refund_reason column failed on staging: "
                 "column refund_reason does not exist. The migration did not reach the staging database.")
NORTH_FINAL = "I read ledger.py: refunds are rounded half up. I made no changes."
SOUTH_FINAL = "I read ledger.py as well. It rounds refunds half up, which matches the spec. I made no changes."


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def append(path: Path, *entries: dict) -> None:
    with path.open("a") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def turn(path: Path, asked: str, tools: list[dict], final: str) -> None:
    """One finished turn in Claude Code's transcript shape: the user's ask, its tool calls, its final message."""
    append(path, {"type": "user", "message": {"role": "user", "content": asked}})
    for t in tools:
        append(path, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", **t}]}})
    append(path, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": final}],
                                                   "stop_reason": "end_turn"}})


INBOX: dict[str, list[str]] = {}  # what reached each session's inbox socket, as Claude Code would get it


async def inbox(name: str) -> str:
    """A stand-in for the session's inbox socket: records each message the daemon sends to it."""
    path = f"/tmp/cfl-inbox-{name}-{os.getpid()}.sock"
    Path(path).unlink(missing_ok=True)
    INBOX[name] = []

    async def take(reader, writer):
        INBOX[name] += [json.loads(line)["message"]["content"] for line in (await reader.read()).decode().splitlines()
                        if line.strip() and json.loads(line).get("type") == "user"]
        writer.close()

    await asyncio.start_unix_server(take, path)
    return path


async def register(work: Path, sid: str, name: str, cwd: Path) -> Path:
    transcript = work / f"{sid}.jsonl"
    transcript.touch()
    call("/voice/register", {"id": sid, "cwd": str(cwd), "pid": os.getpid(), "name": name, "name_given": True,
                             "transcript": str(transcript), "inbox_socket": await inbox(name)})
    return transcript


def logged_at(line: str) -> float:
    """The daemon log's own timestamp on a line, as epoch seconds."""
    return time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S")) + float("0" + line[19:23])


def status() -> dict:
    return call("/voice/status")


async def until(test, timeout: float, every: float = 0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


async def quiet(timeout: float = 40) -> None:
    await until(lambda: status()["speaking"] != "bot", timeout)
    await asyncio.sleep(1.0)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-conflict-e2e-"))
    shop = git_repo(work / "shop")
    (shop / "db").mkdir()
    (shop / "api").mkdir()
    books = git_repo(work / "books")
    pid = os.getpid()
    lantern = await register(work, f"cfl-lantern-{pid}", "lantern", shop / "db")
    billing = await register(work, f"cfl-billing-{pid}", "billing", shop / "api")
    north = await register(work, f"cfl-north-{pid}", "north", books)
    south = await register(work, f"cfl-south-{pid}", "south", books)
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
                               "--window-size=1400,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
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
            await page.until("document.getElementById('settingsbtn')", 10)
            # A silent microphone: this test never talks; the sessions do.
            await page.js(f"""(() => {{
                navigator.mediaDevices.getUserMedia = async () => {{
                  const ctx = new AudioContext({{sampleRate: {RATE}}}), dest = ctx.createMediaStreamDestination();
                  const hum = ctx.createConstantSource(); hum.offset.value = 0; hum.connect(dest); hum.start();
                  await ctx.resume();
                  return dest.stream;
                }};
            }})()""")

            # ---- settings: the section exists, and Card only saves ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            shown = await page.js("({on: document.getElementById('pref-conflicts').checked, "
                                  "spoken: document.getElementById('pref-conflicts-spoken').value})")
            await page.js("document.getElementById('pref-conflicts-spoken').value = 'card'; saveSettings()")
            saved = await until(lambda: call("/voice/prefs").get("conflicts.spoken") is False, 5)
            check("Settings shows the conflict alarm on and spoken by default, and saves Card only",
                  shown == {"on": True, "spoken": "spoken"} and bool(saved), shown=shown, prefs=call("/voice/prefs"))
            call("/voice/prefs", {"conflicts.spoken": True})

            await page.js("startCall()")
            await page.until("call.state === 'live'", 15)
            await quiet(60)  # the greeting
            for path, name in ((lantern, "lantern"), (billing, "billing"), (north, "north"), (south, "south")):
                turn(path, "/pointe:voice", [], "Joined the voice.")  # the turn that joined: never a report
            await until(lambda: len(log_lines("the join itself")) >= 4, 20)

            # ---- two sessions that disagree ----
            turn(lantern, "Run the refund_reason migration on staging.",
                 [{"name": "Edit", "input": {"file_path": str(shop / "db" / "add_refund_reason.sql")}}], LANTERN_FINAL)
            await until(lambda: log_lines("report for lantern|feed.*lantern finished"), 40)
            await quiet()
            turn(billing, "Run the refunds API tests on staging.",
                 [{"name": "Bash", "input": {"command": "pytest tests/test_refunds_api.py"}}], BILLING_FINAL)
            reported = time.time()
            card = await page.until("document.querySelector('#conflicts .clash') && document.querySelector('#conflicts .clash').innerText", 60)
            st = status()
            await page.shot("cfl-1-card")
            check("the page shows one card with both sessions and both claims",
                  bool(card) and len(st["conflicts"]) == 1 and "lantern" in card and "billing" in card
                  and "Ask lantern" in card and "Ask billing" in card and "Dismiss" in card,
                  card=(card or "")[:400], conflicts=st["conflicts"])
            alarm = await until(lambda: next((l for l in log_lines(r"conflict alarm: saying lantern / billing")), None), 60)
            spoke = await until(lambda: next((l for l in log_lines(r"_speak:\d+ - speak: ") if alarm and logged_at(l) > logged_at(alarm)
                                              and "lantern" in l.lower() and "billing" in l.lower()), None),
                                max(1, 60 - (time.time() - reported)))
            started = round(logged_at(spoke) - reported, 1) if spoke else None
            check("the voice starts saying both claims within 60 s of the second report",
                  bool(spoke) and started is not None and started <= 60, secs=started, said=(spoke or "")[-300:])
            alert = [a for a in status()["attention"] if a["kind"] == "conflict"]
            check("an attention entry for alerts", len(alert) == 1, attention=alert)
            # Ask at once, while the reports and the alarm may still be queued: the user's words must come first.

            # ---- Ask: the user's typed words, nothing else ----
            before = len(status()["recent"])
            await page.js("[...document.querySelectorAll('#conflicts .clash button')].find(b => b.textContent === 'Ask lantern').click()")
            typed = await until(lambda: next((t for t in status()["talk"] if t["who"] == "user"
                                              and t["text"].startswith("Send lantern this question:")), None), 10)
            asked = await page.until("[...document.querySelectorAll('#conflicts .clash button')].some(b => b.textContent === 'Asked lantern')", 5)
            await until(lambda: INBOX["lantern"], 30)  # the brain sends it, through the usual checks
            await asyncio.sleep(3)
            routed = status()["recent"][before:]
            await page.shot("cfl-2-asked")
            check("Ask lantern is a typed turn from the user; the question reaches lantern's inbox, and nothing reaches billing",
                  bool(typed) and typed.get("typed") is True and bool(asked) and len(INBOX["lantern"]) == 1
                  and INBOX["billing"] == [] and not any("billing" in r["to"] for r in routed),
                  typed=typed, lantern=INBOX["lantern"], billing=INBOX["billing"], routed=routed)

            # ---- Dismiss ----
            await quiet()
            await page.js("[...document.querySelectorAll('#conflicts .clash button')].find(b => b.textContent === 'Dismiss').click()")
            gone = await page.until("!document.querySelector('#conflicts .clash')", 5)
            check("Dismiss removes the card", bool(gone) and status()["conflicts"] == [], conflicts=status()["conflicts"])

            # ---- no false alarm: two sessions reading the same file ----
            checks_before = len(log_lines(r"job conflict-check/"))
            turn(north, "Read ledger.py and tell me how refunds are rounded.",
                 [{"name": "Read", "input": {"file_path": str(books / "ledger.py")}}], NORTH_FINAL)
            await until(lambda: log_lines("report for north|feed.*north finished"), 40)
            await quiet()
            turn(south, "Check how ledger.py rounds refunds against the spec.",
                 [{"name": "Read", "input": {"file_path": str(books / "ledger.py")}}], SOUTH_FINAL)
            await until(lambda: len(log_lines(r"job conflict-check/south")) >= 1, 60)
            await asyncio.sleep(10)
            asked_reader = len(log_lines(r"job conflict-check/")) > checks_before
            await page.shot("cfl-3-same-file")
            check("two sessions reading the same file: the reader is asked, and no card",
                  asked_reader and status()["conflicts"] == [] and not await page.js("!!document.querySelector('#conflicts .clash')"),
                  checks=log_lines(r"job conflict-check/|conflict:")[-6:], conflicts=status()["conflicts"])

            check("no session got anything it was not asked for: only the one question, to lantern",
                  len(INBOX["lantern"]) == 1 and not (INBOX["billing"] or INBOX["north"] or INBOX["south"]),
                  inboxes={k: len(v) for k, v in INBOX.items()})
            errors = await page.js("window.__errors")
            check("no page errors", not errors, errors=errors)
            await page.js("endCall()")
    finally:
        chrome.terminate()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page conflict alarm)")


asyncio.run(main())
