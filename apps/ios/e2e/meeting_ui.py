"""Meeting mode in the iPhone app, end to end. Three parts:

1. A real test daemon. A fake browser holds the call and plays a synthetic room (three synthesized voices); the app, a
   second screen on the same daemon, does everything a meeting offers (MeetingUITests.testMeetingEndToEnd). The two
   hand each other cue files in the screenshot folder; this side plays the room on cue and checks the daemon's state.
2. apps/ios/e2e/fake_mac.py in the daemon's place: an older Pointe, a Mac with no Soniox key, a Mac that stops answering.
3. Nothing else: the demo-screen audit is MeetingUITests.testDemoScreens, run on its own.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-meetios CLAUDE_VOICE_DAEMON_PORT=7907 CLAUDE_VOICE_TLS_PORT=7507 \
     uv run python -u -I apps/ios/e2e/meeting_ui.py <simulator id> [screenshot folder] [--only real|fake]
Builds in parallel each need POINTE_DERIVED_DATA (default /tmp/pointe-dd); DEVELOPMENT_TEAM, when set, signs the build.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR / "tests" / "e2e"))
sys.path.insert(0, str(ROOT_DIR))
from rig import DAEMON, GUEST_VOICES, LOG, ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SIMULATOR = args[0]
SHOTS = Path(args[1] if len(args) > 1 else "/tmp/pointe-meeting-shots")
ONLY = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
TLS_PORT = int(os.environ["CLAUDE_VOICE_TLS_PORT"])
results: list[tuple[str, bool | None]] = []
# Parallel builds each need their own derived data; a signing team, when given, goes to xcodebuild.
DERIVED = os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd")
TEAM = [f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []

# Made-up people and words. (tests/e2e/meeting.py runs on import, so its room is not imported.)
DANA, SAM = GUEST_VOICES
ROOM = [  # (voice, or None for the owner; line)
    (DANA, "Hi everyone, I'm Dana. The new pricing page goes live on Thursday."),
    (SAM, "Do we know what the conversion rate of the old checkout page was last quarter?"),
    (DANA, "No idea. Nobody here has that number."),
    (None, "Okay, let's move on."),
    (SAM, "Who is writing the release note for the pricing launch?"),
    (DANA, "I'll write the release note by Wednesday."),
]
INTRO = [(SAM, "Sorry, I didn't introduce myself. I'm Sam, I run finance."),
         (SAM, "From finance, we need the new prices in the invoices before Thursday.")]
RISKY = [  # each round a new risk, so the hand is not a repeat of the last
    [(SAM, "To save time we will skip the payment tests and ship Thursday anyway."),
     (DANA, "Right, nobody runs those tests, and refunds were never tested either.")],
    [(DANA, "We will also turn off the error alerts during the launch so nobody gets paged."),
     (SAM, "Yes, and nobody will be on call that night.")],
    [(SAM, "And we will copy the production customer database to my laptop to test the prices."),
     (DANA, "Fine, with the real card numbers in it, it is faster.")],
    [(DANA, "There is no rollback plan. If the prices are wrong we just fix them by hand in the database."),
     (SAM, "Agreed, no rollback plan.")],
]


def check(name: str, ok: bool | None, **detail) -> None:
    """ok None: not covered this run (the model did not produce what the step needs); reported, not passed."""
    results.append((name, ok))
    tag = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    print(f"{tag}  {name}  {json.dumps(detail, default=str)[:300]}", flush=True)


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET", headers={
                                         "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                         "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=120).read())


def meeting() -> dict:
    return call("/voice/status").get("meeting") or {}


def notes(kind: str = "") -> list[dict]:
    return [n for n in call("/voice/notes?since=0")["notes"] if not kind or n["kind"] == kind]


def turns() -> list[dict]:
    return call("/voice/meeting/transcript").get("turns", [])


def owner_label() -> str | None:
    return next((s["label"] for s in meeting().get("speakers") or [] if s.get("is_owner")), None)


def label_of(fragment: str) -> str | None:
    return next((t["speaker"] for t in turns() if fragment.lower() in t["text"].lower()), None)


async def room(browser: Browser, lines, pause: float = 1.0) -> None:
    for voice, line in lines:
        _, end = await (browser.say(line) if voice is None else browser.say(line, voice))
        await asyncio.sleep(end - time.time() + pause)


async def until(what, timeout: float, every: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = what()
        if value:
            return value
        await asyncio.sleep(every)
    return what()


# Said only in the room: the test session's transcript shares "conversion rate" with it, and its text is logged
# (opening context, notes) as it should be. "release note" also reaches the session once the owner sends the action
# items, after the meeting, so only lines logged while a meeting is on count.
ROOM_ONLY = ("Nobody here has that number", "release note", "payment tests", "invoices before Thursday")


VOICE_STEPS = 12  # fake_mac.voice_status's steps, and MeetingUITests.testFollowsWhatTheVoiceDoes's


def meeting_lines() -> list[str]:
    """The daemon log's lines from while a meeting was on (between "meeting started" and "meeting ended")."""
    lines, on = [], False
    for line in (LOG.read_text().splitlines() if LOG.exists() else []):
        if "meeting started (" in line:
            on = True
        elif "meeting ended after" in line:
            on = False
        elif on:
            lines.append(line)
    return lines


def cue(*names: str):
    """The first of these cues the UI test has written, or None."""
    return lambda: next((n for n in names if (SHOTS / f"cue-{n}").exists()), None)


def go(name: str) -> None:
    (SHOTS / f"go-{name}").touch()


def xcodebuild(case: str, test: str, link: str) -> subprocess.Popen:
    log = SHOTS / f"xcode-{case}.log"
    xcode = subprocess.Popen(
        ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination",
         f"id={SIMULATOR}", "-derivedDataPath", DERIVED, f"-only-testing:PointeUITests/MeetingUITests/{test}",
         *TEAM, "test"],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_MEETING_SHOTS": str(SHOTS),
             "TEST_RUNNER_MEETING_CASE": case}, stdout=open(log, "w"), stderr=subprocess.STDOUT, text=True)
    xcode.stdout_path = str(log)
    return xcode


def finish(xcode: subprocess.Popen, name: str) -> None:
    xcode.wait(timeout=600)
    out = _log_of(xcode)
    tail = [line.strip()[-160:] for line in out.splitlines()
            if "error:" in line or "XCTAssert" in line or "failed" in line.lower()]
    check(name, "** TEST SUCCEEDED **" in out, tail=tail[-5:])


def _log_of(xcode: subprocess.Popen) -> str:
    return Path(xcode.stdout_path).read_text() if Path(xcode.stdout_path).exists() else ""


class Hands:
    """Every hand the daemon raises, seen by polling; a hand's whole point is what "Type it instead" writes down."""

    def __init__(self) -> None:
        self.seen: list[dict] = []

    async def watch(self) -> None:
        while True:
            try:
                hand = meeting().get("hand")
                if hand and (not self.seen or self.seen[-1]["at"] != hand["at"]):
                    self.seen.append(hand)
            except Exception:
                pass
            await asyncio.sleep(0.5)


async def real(link: str) -> None:
    work = Path(tempfile.mkdtemp(prefix="meeting-ios-"))
    # A session with something to look up: what it found about the old checkout's conversion (made-up numbers).
    lines = [{"type": "user", "message": {"role": "user", "content": "Pull last quarter's conversion rate for the old checkout page from the analytics export."}},
             {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text":
              "Done. From analytics/export-q3.csv: the old checkout page converted at 2.8% last quarter (41,200 sessions, 1,154 orders). Saved to notes/conversion.md."}]}}]
    (work / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    call("/voice/register", {"id": f"meeting-ios-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "pricing",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    browser = Browser(echo_gain=0.5)
    await browser.connect()
    await asyncio.sleep(8)  # the greeting
    xcode = xcodebuild("real", "testMeetingEndToEnd", link)
    hands = Hands()
    watcher = asyncio.create_task(hands.watch())
    try:
        if not await until(cue("prefs-set"), 600):
            check("the UI test reaches the meeting settings", False, log=_log_of(xcode)[-600:])
            return
        prefs = call("/voice/prefs")
        check("settings: a change is saved on the Mac", prefs.get("meeting.notes_language") == "en", prefs=prefs)
        go("prefs-checked")

        if not await until(cue("started"), 180):
            check("the app starts the meeting through its consent step", False)
            return
        m = meeting()
        check("start: consent step, then on, with the linked session and the brief",
              m.get("on") is True and m.get("sessions") == ["pricing"] and any("pricing launch" in n["text"] for n in notes("brief")),
              mode=m.get("mode"), sessions=m.get("sessions"), vendors=m.get("vendors"))
        await room(browser, [(None, "Pointe, that's me.")])
        await room(browser, ROOM)

        first = await until(cue("ignored", "no-suggestion"), 200)
        if first == "ignored":
            dismissed = [n for n in notes("speaker") if n["state"] == "dismissed"]
            check("Ignore: the suggestion is dismissed and the name not applied",
                  bool(dismissed) and not any(s.get("name") == dismissed[0]["meta"].get("name")
                                              for s in meeting().get("speakers") or []), dismissed=dismissed[:1])
            await room(browser, INTRO)
            second = await until(cue("accepted", "no-second-suggestion"), 200)
            named = [s for s in meeting().get("speakers") or [] if s.get("name")]
            check("Use this name: the speaker is named on the Mac", bool(named) if second == "accepted" else None,
                  speakers=meeting().get("speakers"),
                  suggestions=[(n["id"], n["state"], n["text"]) for n in notes("speaker")])
        else:
            check("Ignore / Use this name", None, why="the notes model suggested no speaker name this run")
        go("room-done")

        await until(cue("me-dana"), 200)
        dana = label_of("goes live on Thursday")
        await until(lambda: owner_label() == dana, 15)
        check("That was me: the owner moves to the speaker you pressed", dana is not None and owner_label() == dana,
              dana=dana, owner=owner_label())
        go("me-dana-checked")
        await until(cue("me-back"), 60)
        mine = label_of("move on")
        await until(lambda: owner_label() == mine, 15)  # the cue is written as the tap lands, before the Mac answers
        check("That was me, back: the owner returns", mine is not None and owner_label() == mine, mine=mine, owner=owner_label())
        go("me-back-checked")

        asked_at = time.time()
        await until(cue("asked"), 120)
        check("typed Ask: answered in the notes, not aloud",
              any("waiting on you" in n["text"].lower() for n in notes("thought"))
              and not browser.speaker.speech_spans(since=asked_at))

        lookup = await until(cue("lookup-ready", "no-lookup"), 200)
        if lookup == "lookup-ready":
            before = notes("answer")
            go("lookup-go")
            await until(cue("lookup-tapped"), 60)
            answer = await until(lambda: notes("answer"), 240, every=2)
            check("Look up: nothing until the tap, then the answer arrives as a note", not before and bool(answer),
                  answer=[a["text"][:100] for a in answer][:1])
        else:
            check("Look up", None, why="no open question named a linked session this run")

        await until(cue("participating"), 120)
        part_at = time.time()
        check("mode switch: listening to participating", meeting().get("mode") == "participating")
        outcomes, quiet_until = {}, None
        for i, wanted in enumerate([("later", "no-hand-later"), ("typed", "no-hand-type"), ("spoke", "no-hand-speak")]):
            raised = len(hands.seen)
            for _ in range(2):  # the hand is the model's call: a second round if the first raised none
                await room(browser, RISKY[(i + _) % len(RISKY)], pause=1.5)
                if await until(lambda: len(hands.seen) > raised, 60):
                    break
            outcomes[wanted[0]] = await until(cue(*wanted), 200)
            if wanted[0] == "typed":
                quiet_until = time.time()
        check("a hand is raised in participating mode, and Not now puts it down", outcomes["later"] == "later",
              hands=[h.get("line") for h in hands.seen][:1])
        if outcomes["typed"] == "typed":
            full = [h.get("line") for h in hands.seen]
            check("Type it instead: its point becomes a note", len(notes("thought")) > 0, hands=full[-2:])
        else:
            check("Type it instead", None, why="no second hand this run")
        spans = [sp for sp in browser.speaker.speech_spans(since=part_at) if quiet_until and sp[0] < quiet_until]
        check("participating: nothing said before you let it (Not now, Type it instead)", not spans, spans=len(spans))
        if outcomes["spoke"] == "spoke":
            check("Let it speak: it speaks", bool(await until(lambda: browser.speaker.speech_spans(since=part_at), 20)))
        else:
            check("Let it speak", None, why="no third hand this run")

        # The call drops and comes back: the meeting goes on and its notes keep coming.
        before_turns, before_version = meeting().get("turns", 0), call("/voice/status")["notes"]["version"]
        await browser.close()
        await asyncio.sleep(3)
        browser = Browser(echo_gain=0.5)
        await browser.connect()
        await asyncio.sleep(6)
        still = meeting()
        await room(browser, [(DANA, "Back on the pricing page: the annual plan gets a twenty percent discount, decided.")])
        grew = await until(lambda: meeting().get("turns", 0) > before_turns, 40)
        newer = await until(lambda: call("/voice/status")["notes"]["version"] > before_version, 60)
        check("reconnecting mid-meeting: the meeting goes on and the notes catch up",
              still.get("on") is True and bool(grew) and bool(newer), turns=meeting().get("turns"))
        go("modes")

        await until(cue("listening"), 60)
        m = meeting()
        check("mode switch: participating to listening (a raised hand is put down)",
              m.get("mode") == "listening" and not m.get("hand"), mode=m.get("mode"))
        go("listening-checked")
        await until(cue("participating-again"), 60)
        raised = len(hands.seen)
        for lines in (RISKY[3], RISKY[0]):
            await room(browser, lines, pause=1.5)
            if await until(lambda: len(hands.seen) > raised, 60):
                break
        how = await until(cue("end-with-hand", "end-no-hand"), 200)
        await until(cue("ended"), 240)
        status = call("/voice/status")
        result = (status.get("meeting") or {}).get("result") or {}
        check("End (confirmed in the app): ended on the Mac, with a summary",
              (status.get("meeting") or {}).get("ended") is True and bool(result.get("summary")),
              summary=(result.get("summary") or "")[:160], items=result.get("action_items"))
        check("ending while a hand is raised", True if how == "end-with-hand" else None,
              why=None if how == "end-with-hand" else "no hand was up at the end this run")

        await until(cue("saved"), 120)
        files = sorted((STATE / "meetings").glob("*.md")) if (STATE / "meetings").exists() else []
        text = files[-1].read_text() if files else ""
        check("Save on the Mac: a Markdown file, with the transcript when asked, private to the user",
              bool(files) and "Transcript" in text and oct(files[-1].stat().st_mode & 0o777) == "0o600",
              file=str(files[-1]) if files else None)
        sent_at = time.time()
        sent = await until(cue("sent", "no-action-items"), 120)
        if sent == "sent":
            await asyncio.sleep(15)
            lines = [line for line in log_lines("pricing") if line[:19] >= time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sent_at - 2))]
            check("Send action items: confirmed in the app, then sent to the session (daemon log)",
                  any("send" in line.lower() or "pricing" in line for line in lines), log=[line[-140:] for line in lines][-4:])
        else:
            check("Send action items", None, why="the meeting had no action items")

        await until(cue("discarded"), 120)
        check("Discard (confirmed): the meeting is forgotten on the Mac", call("/voice/status").get("meeting") is None)
        await until(cue("second-done"), 400)
        check("a second meeting gets its own end sheet, and is discarded", call("/voice/status").get("meeting") is None)
        words = [line for line in meeting_lines() if any(w in line for w in ROOM_ONLY)]
        check("no room words in the daemon log", not words, leaked=[w[-100:] for w in words][:2])
        finish(xcode, "MeetingUITests.testMeetingEndToEnd passes")
    finally:
        watcher.cancel()
        if xcode.poll() is None:
            xcode.kill()
        await browser.close()


async def fake(link: str) -> None:
    stop_daemon()
    script = Path(__file__).parent / "fake_mac.py"
    (STATE / "fake-caught-up").unlink(missing_ok=True)

    def serve(case: str) -> subprocess.Popen:
        mac = subprocess.Popen([sys.executable, "-I", str(script), str(STATE), str(TLS_PORT), case, str(SHOTS / "fake-step")],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert "fake mac up" in mac.stdout.readline()
        return mac

    for case, test, name in [("old", "testOlderMac", "an older Mac without meeting routes: says why, no dead ends"),
                             ("nosoniox", "testNoSonioxKey", "no Soniox key: Start stays off, with the reason")]:
        mac = serve(case)
        try:
            finish(xcodebuild(case, test, link), name)
        finally:
            mac.kill()
            mac.wait()

    # What the owner's voice does on the Mac, step by step: the app shows each one with nothing tapped on the phone.
    (SHOTS / "fake-step").write_text("0")
    mac = serve("voice")
    xcode = xcodebuild("voice", "testFollowsWhatTheVoiceDoes", link)
    try:
        for n in range(VOICE_STEPS):
            (SHOTS / "fake-step").write_text(str(n))
            go(f"step-{n}")
            if not await until(cue(f"step-{n}"), 240 if n == 0 else 60):
                break
        finish(xcode, "the app follows the voice: a start, a rename, a focus, two closes, the meeting's mode, the end, the send")
    finally:
        if xcode.poll() is None:
            xcode.kill()
        mac.kill()
        mac.wait()

    mac = serve("meeting")
    xcode = xcodebuild("meeting", "testMacUnreachable", link)
    try:
        await until(cue("seen"), 400)
        mac.kill()
        mac.wait()
        await until(cue("unreachable-seen"), 60)
        (STATE / "fake-caught-up").touch()
        mac = serve("meeting")
        finish(xcode, "Mac not reachable mid-meeting: says so, then catches up")
    finally:
        if xcode.poll() is None:
            xcode.kill()
        mac.kill()


async def main() -> None:
    fresh_state()
    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True)
    import pair

    pair.STATE = STATE
    pair.setup(os.environ.get("IOS_E2E_HOST", "pointe.localtest.me"), "127.0.0.1")  # a real name: see tests/e2e/ios_app.py
    config = json.loads((STATE / "remote.json").read_text())
    (STATE / "remote.json").write_text(json.dumps({**config, "listen": ["127.0.0.1", "::1"]}))
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-400:]
    link = pair.pairing_link()
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    try:
        if ONLY in (None, "real"):
            await real(link)
        if ONLY in (None, "fake"):
            await fake(link)
    finally:
        stop_daemon()
        passed = sum(ok is True for _, ok in results)
        skipped = [name for name, ok in results if ok is None]
        print(f"\nscreenshots: {SHOTS}")
        print(f"{passed}/{len(results) - len(skipped)} passed (iOS meeting), {len(skipped)} not covered: {skipped}")


asyncio.run(main())
