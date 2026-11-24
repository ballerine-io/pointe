"""Meeting mode on a real call: the owner and two other people (three synthesized voices) talk in one room; the bot
listens, writes notes, raises a hand, speaks only when let, stops when talked over, and approves nothing it hears.
The laptop speaker leaks the bot's voice back into the mic (echo_gain), as in a real room. Then a second meeting after a
discard: none of the first one's notes, a question that mentions closing the meeting, a Hebrew question, the audio
stream reconnecting, and the owner ending it right after their own words.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-meeting CLAUDE_VOICE_DAEMON_PORT=7873 uv run python -u -I tests/e2e/meeting.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import urllib.request

import aiohttp

sys.path.insert(0, str(Path(__file__).parent))
from rig import DAEMON, GUEST_VOICES, ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DANA, SAM = GUEST_VOICES
ROOM = [  # (voice or None for the owner, line)
    (DANA, "Hi everyone, I'm Dana. The new pricing page goes live on Thursday."),
    (SAM, "Do we know what the conversion rate of the old checkout page was last quarter?"),
    (DANA, "No idea. Nobody here has that number."),
    (None, "Okay, let's move on."),
    (SAM, "Who is writing the release note for the pricing launch?"),
    (DANA, "I'll write the release note by Wednesday."),
    (SAM, "Yes, go ahead."),  # a stray yes while an approval is pending
    (None, "Yeah, yes."),
    (DANA, "Also, the refunds flow still uses the old prices."),
]
RISKY = [
    (SAM, "To save time we will skip the payment tests and ship Thursday anyway."),
    (DANA, "Right, nobody runs those tests, and refunds were never tested either."),
    (SAM, "And we will turn off the error alerts during the launch so nobody gets paged."),
]


async def room(browser: Browser, lines, pause: float = 1.0) -> None:
    for voice, line in lines:
        _, end = await (browser.say(line) if voice is None else browser.say(line, voice))
        await asyncio.sleep(end - time.time() + pause)


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET", headers={
                                         "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                         "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=120).read())


def bot_spoke(browser: Browser, since: float) -> list:
    return browser.speaker.speech_spans(since=since)


async def poll(what, timeout: float, every: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = what()
        if value:
            return value
        await asyncio.sleep(every)
    return what()


def said_by_bot() -> list[str]:
    return [t["text"] for t in call("/voice/status")["talk"] if t["who"] == "assistant"]


def notes(kinds: str = "") -> list[dict]:
    return call(f"/voice/notes?since=0{'&kinds=' + kinds if kinds else ''}")["notes"]


async def held_permission(session_id: str) -> dict:
    """What Claude Code's PermissionRequest hook gets back; held until answered or cancelled."""
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{DAEMON}/voice/permission-hook", json={
                "session_id": session_id, "tool_name": "Bash",
                "tool_input": {"command": "rm -rf build", "description": "Delete the build folder"}},
                headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"}) as r:
            return await r.json()


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="meeting-e2e-"))
    session_id = f"meeting-e2e-{os.getpid()}"
    (work / "transcript.jsonl").touch()  # an empty transcript string crashes the call's opening (sessions.py, pre-existing)
    call("/voice/register", {"id": session_id, "cwd": str(work), "pid": os.getpid(), "name": "pricing", "name_given": True,
                             "transcript": str(work / "transcript.jsonl")})
    browser = Browser(echo_gain=0.5)
    permission = None
    try:
        await browser.connect()
        await asyncio.sleep(8)  # the greeting
        started = call("/voice/meeting", {"action": "start", "mode": "listening", "consent": True,
                                         "brief": "Weekly sync on the checkout pricing launch."})["meeting"]
        check("the consent step names who receives the room's audio, and status shows recording",
              started["recording"] and started["vendors"].get("room_audio") == "soniox", vendors=started["vendors"])
        start = time.time()
        await room(browser, [(None, "Pointe, that's me.")])
        owner = await poll(lambda: call("/voice/status")["meeting"].get("owner_known"), 15)
        check("the owner is bound by saying “that's me”", bool(owner))

        permission = asyncio.create_task(held_permission(session_id))
        await asyncio.sleep(2)
        await room(browser, ROOM)
        await asyncio.sleep(4)
        check("listening mode says nothing, the whole time", not bot_spoke(browser, start),
              spans=len(bot_spoke(browser, start)))
        check("a stray “yes” in the room approves nothing", not permission.done(),
              result=permission.result() if permission.done() else None)
        attention = call("/voice/status")["attention"]
        check("the pending approval waits for a tap instead", any(a["kind"] == "permission" for a in attention),
              attention=attention)

        written = await poll(lambda: [n for n in notes() if n["kind"] in ("thought", "action", "decision")], 60)
        check("notes appear without the bot saying anything", bool(written) and not bot_spoke(browser, start),
              notes=[(n["kind"], n["text"][:70]) for n in written])
        question = await poll(lambda: [n for n in notes("question") if "conversion" in n["text"].lower()], 30)
        check("a question nobody could answer becomes an open question", bool(question),
              questions=[n["text"][:80] for n in notes("question")])
        actions = [n["text"].lower() for n in notes("action")]
        check("the release note is an action item", any("release note" in a for a in actions), actions=actions)

        call("/voice/meeting", {"action": "mode", "mode": "participating"})
        risky_at = time.time()
        await room(browser, RISKY, pause=1.5)
        hand = await poll(lambda: call("/voice/status")["meeting"].get("hand"), 90)
        check("participating: the bot raises a hand with a one-line summary, and stays quiet",
              bool(hand) and not bot_spoke(browser, risky_at), hand=hand, spans=len(bot_spoke(browser, risky_at)))

        let_at = time.time()
        call("/voice/meeting", {"action": "hand", "decision": "speak"})
        spoke = await poll(lambda: bot_spoke(browser, let_at), 20, every=0.5)
        check("let it speak: the bot says its point", bool(spoke))
        interrupts = browser.interrupts
        await asyncio.sleep(1.5)
        await room(browser, [(DANA, "Wait, hold on, let me finish that thought first.")], pause=0.5)
        stopped = await poll(lambda: browser.interrupts > interrupts, 6, every=0.3)
        check("talking over the bot stops it", bool(stopped), interrupts=browser.interrupts,
              barge_ins=len(log_lines("meeting: barge-in")))
        await asyncio.sleep(4)
        people = call("/voice/status")["meeting"]["speakers"]
        check("its own voice through the speakers is not taken for a fourth person",
              len(people) <= 3 and sum(p["is_owner"] for p in people) == 1, speakers=people)

        ended = call("/voice/meeting", {"action": "end"})
        check("the end gives a summary and action items", bool(ended.get("summary")) and bool(ended.get("action_items")),
              summary=(ended.get("summary") or "")[:200], items=ended.get("action_items"))
        status = call("/voice/status")
        check("after the end nothing records", not status["meeting"].get("on") and status["mode_state"]["mode"] == "conversation",
              meeting=status["meeting"].get("on"), mode=status["mode_state"])
        transcript_routes = call("/voice/meeting/transcript")
        for turn in transcript_routes.get("turns", []):  # synthetic speech: for reading a failure
            print(f"    {turn.get('who', '?'):>10} [{turn.get('speaker')}] {turn.get('text', '')[:90]}")
        check("no storage by default: nothing on disk until an export",
              not (STATE / "meetings").exists() and bool(transcript_routes.get("turns")))
        words = [line for line in log_lines(".") if any(w in line for w in ("conversion rate", "release note", "payment tests"))]
        check("no participant words in the log", not words, leaked=[w[-100:] for w in words][:3])

        # ---- a second meeting, after a discard ----
        first_notes = {n["text"] for n in notes()}
        call("/voice/meeting", {"action": "discard"})
        second = call("/voice/meeting", {"action": "start", "mode": "participating", "consent": True})["meeting"]
        leaked = [n["text"][:60] for n in notes() if n["text"] in first_notes]
        check("a second meeting after a discard shows none of the first meeting's notes",
              not leaked and second["id"] != started.get("id"), leaked=leaked[:3])
        await room(browser, [(None, "Pointe, that's me.")])
        check("the owner is bound again in the second meeting",
              bool(await poll(lambda: call("/voice/status")["meeting"].get("owner_known"), 15)))

        asked_at = time.time()
        await room(browser, [(None, "Pointe, do you think we should close the meeting now, or keep going?")])
        spoke = await poll(lambda: bot_spoke(browser, asked_at), 30, every=0.5)
        still_on = call("/voice/status")["meeting"].get("on")
        check("a question that mentions closing the meeting is answered, and the meeting stays on",
              bool(spoke) and bool(still_on), spoke=bool(spoke), on=still_on)
        await asyncio.sleep(10)  # let it finish its answer

        before = set(said_by_bot())  # the status keeps only the last turns: look for a new one
        hebrew_at = time.time()
        await room(browser, [(None, "פוינט, מה דעתך על מועד ההשקה ביום חמישי?")])
        spoke = await poll(lambda: bot_spoke(browser, hebrew_at), 30, every=0.5)
        answer = await poll(lambda: [t for t in said_by_bot() if t not in before], 15, every=0.5)
        hebrew = bool(answer) and any("\u0590" <= ch <= "\u05ff" for t in answer for ch in t)
        refused = log_lines("speech refused")
        check("a Hebrew question in participating gets a spoken Hebrew answer", bool(spoke) and hebrew,
              answer=[t[:80] for t in answer or []], refusals=len(refused))
        await asyncio.sleep(10)

        turns_before = call("/voice/status")["meeting"]["turns"]
        call("/voice/meeting", {"action": "reconnect"})
        await asyncio.sleep(2)
        after = call("/voice/status")["meeting"]
        relabelled = any("reconnected" in n["text"] for n in notes("thought"))
        check("after the audio stream reconnects, the meeting goes on and the owner must claim the seat again",
              after.get("on") and not after.get("owner_known") and relabelled, meeting=after.get("owner_known"),
              note=relabelled)
        await room(browser, [(None, "Pointe, that's me.")])
        rebound = await poll(lambda: call("/voice/status")["meeting"].get("owner_known"), 20)
        check("the room is heard on the new stream", bool(rebound) and call("/voice/status")["meeting"]["turns"] > turns_before,
              turns=call("/voice/status")["meeting"]["turns"], before=turns_before)

        await room(browser, [(None, "Good, I think we covered the launch plan for Thursday."),
                             (None, "Pointe, end the meeting.")], pause=0.3)  # one speaker, no one between: one merged turn
        ended = await poll(lambda: not (call("/voice/status")["meeting"] or {}).get("on", True), 60)
        check("the owner's words then “Pointe, end the meeting”, with nobody between, end it", bool(ended),
              meeting=call("/voice/status")["meeting"])
        words = [line for line in log_lines(".") if any(w in line for w in ("launch plan", "מועד ההשקה", "keep going"))]
        check("no words from the second meeting in the log", not words, leaked=[w[-100:] for w in words][:3])
    finally:
        if permission is not None and not permission.done():
            permission.cancel()
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (meeting)")


asyncio.run(main())
