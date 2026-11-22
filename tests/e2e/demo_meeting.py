"""Meeting mode, the demo path, live: Pointe listens in a meeting, the owner says "Pointe, join in", asks what billing's
session says about the retry limit and hears the answer from a read-only copy of that session, the room goes on while
Pointe stays quiet, "Pointe, end the meeting" writes the summary and the action items, and "send the action items to
billing" is read back and sent on the owner's yes. The page (headless Chrome) must show each step.

Real Claude Code sessions (billing, docs) in throwaway folders under /tmp; the room is three synthesized voices on the
test's own call (never a microphone). Every name, number and line is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-demo-meet CLAUDE_VOICE_DAEMON_PORT=7961 CLAUDE_VOICE_TLS_PORT=7561 \
     POINTE_CHROME_PORT=7964 uv run python -u -I tests/e2e/demo_meeting.py [runs]
About six minutes a run. Calls paid APIs (the brain, the reader, Soniox, the mouth, ElevenLabs, Gemini).
"""

import asyncio
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from demo_rig import (greeted, reply_audio, words, keep_log, owner_heard, PageWindow, call, cleanup, heard_reply, log_lines, owner_says, plain, room_says, spoke_since,  # noqa: E402
                      start_daemon, start_sessions, status, stop_daemon, stop_sessions, until, workspace)
from rig import GUEST_VOICES, Browser  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7964"))
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-demo-meeting-"))
DANA, SAM = GUEST_VOICES
FACT = ("Remember this for later questions: in this project the billing webhook retry limit is 5 attempts, with "
        "exponential backoff capped at 10 minutes. Reply with just OK.")
BEFORE = [
    (DANA, "Hi everyone, I'm Dana. The billing webhooks failed again last night during the retry storm."),
    (SAM, "Before we change anything we need to know the current retry limit in billing."),
    (DANA, "I don't remember the number, and nobody here does."),
]
AFTER = [
    (DANA, "Okay. Then Sam raises the retry limit to eight attempts by Friday."),
    (SAM, "Sure, I'll do it by Friday, and Dana updates the on-call runbook."),
]


def sent_to(name: str) -> list[str]:
    return log_lines(rf" -> {re.escape(name)}\b")


async def one_run(n: int) -> None:
    tries = 1

    def step(name: str, ok: bool, **info) -> None:
        check(f"[run {n}] {name}", ok, **info, **({"retried_unheard": tries} if tries > 1 else {}))

    start_daemon()
    call("/voice/prefs", {"meeting.consented": True, "meeting.notes_language": "en"})  # the consent step, accepted once before
    root = workspace("demo-meet", ["billing", "docs"])
    sessions = start_sessions(root, ["billing", "docs"])
    browser, window = Browser(echo_gain=float(os.environ.get("POINTE_ECHO_GAIN", "0.4"))), PageWindow(DEBUG_PORT, SHOTS / f"run{n}")
    try:
        sessions["billing"].type(FACT)
        await asyncio.sleep(20)  # haiku answers OK; the copy a lookup forks then holds the number
        page = await window.open()
        await browser.connect()
        await until(lambda: status().get("connected"), 20)
        await greeted(browser)

        t, tries = await owner_heard(browser, "Pointe, meeting mode, listening.", r"meeting started \(")
        on = await until(lambda: (status().get("meeting") or {}).get("on"), 15)
        seen_from = time.time()
        banner = await page.until("document.body.classList.contains('meeting') && document.getElementById('meetwhat').textContent", 20)
        step("A1 listening: the meeting starts by voice, and the page shows it", bool(on) and banner == "Meeting · Listening",
             banner=banner, mode=(status().get("meeting") or {}).get("mode"), page_after_s=round(time.time() - seen_from, 1))
        await window.shot("a1-listening")

        quiet_from = time.time()
        for voice, line in BEFORE:
            await room_says(browser, voice, line)
        await asyncio.sleep(4)
        step("A2 listening: the room talks and Pointe says nothing", not spoke_since(browser, quiet_from))

        t, tries = await owner_heard(browser, "Pointe, join in.", r"meeting command: ")
        joined = await until(lambda: (status().get("meeting") or {}).get("mode") == "participating", 10)
        banner = await page.until("document.getElementById('meetwhat').textContent === 'Meeting · Participating' && "
                                  "document.getElementById('meetwhat').textContent", 8)
        ack = await heard_reply(browser, t, timeout=10, quiet=1.5)
        step("A3 “Pointe, join in” switches to participating, and the page shows it", bool(joined) and bool(banner),
             mode=(status().get("meeting") or {}).get("mode"), banner=banner, said=ack)
        await window.shot("a3-participating")

        sent_before = len(sent_to("billing"))
        t, tries = await owner_heard(browser, "Pointe, what does billing's session say about the retry limit?", r"meeting command: ")
        answer = await heard_reply(browser, t, timeout=90, quiet=3)
        heard = plain(answer)
        step("A4 the lookup: Pointe answers from billing's session, aloud and briefly",
             bool(re.search(r"\b(5|five)\b", heard)) and len(heard.split()) <= 60, said=answer)
        step("A4 the lookup is read-only: nothing was sent to billing", len(sent_to("billing")) == sent_before)
        await window.shot("a4-answer")

        quiet_from = time.time()
        for voice, line in AFTER:
            await room_says(browser, voice, line)
        await asyncio.sleep(10)
        step("A5 participating: the room goes on, and Pointe stays quiet", not spoke_since(browser, quiet_from))

        t, tries = await owner_heard(browser, "Pointe, end the meeting.", r"meeting command: ")
        ended = await until(lambda: (status().get("meeting") or {}).get("ended"), 90, 1)
        result = (status().get("meeting") or {}).get("result") or {}
        body = await page.until("document.getElementById('endsheet').classList.contains('open') && "
                                "document.getElementById('endbody').textContent", 20, 1)
        step("A6 “Pointe, end the meeting”: a summary and action items, shown on the page",
             bool(ended) and bool(result.get("summary")) and bool(result.get("action_items")) and bool(body)
             and "Action items" in (body or ""), items=result.get("action_items"), body=(body or "")[:200])
        await window.shot("a6-ended")
        await asyncio.sleep(4)

        sent_before = len(sent_to("billing"))
        t, tries = await owner_heard(browser, "Send the action items to billing.", r"action items read back|user said: ")
        audio = await reply_audio(browser, t, timeout=40, quiet=2.5)
        held = len(sent_to("billing")) == sent_before
        shown = await page.until("document.getElementById('endok').textContent.startsWith('Pointe asked') && "
                                 "document.getElementById('endok').textContent", 8)
        await window.shot("a7-readback")
        t, tries_yes = await owner_heard(browser, "Yes.", r"action items: the owner said yes|user said: ")
        readback = await words(audio)
        step("A7 “send the action items to billing” is read back first, nothing is sent yet, and the end sheet shows the ask",
             "billing" in plain(readback) and held and bool(shown), said=readback, shown=shown)
        tries = max(tries, tries_yes)
        got = await until(lambda: len(sent_to("billing")) > sent_before, 60, 1)
        line = (sent_to("billing") or [""])[-1]
        confirm = await heard_reply(browser, t, timeout=30, quiet=2)
        shown = await page.until("document.getElementById('endok').textContent.startsWith('Asked to send') && "
                                 "document.getElementById('endok').textContent", 8)
        step("A7 on the owner's yes the action items reach billing, and the end sheet says so",
             bool(got) and "meeting action items" in line and bool(shown), sent=line[-240:], said=confirm,
             shown=shown)
        errors = await page.js("window.__errors || []")
        step("no page errors", not errors, errors=errors)
    finally:
        await window.close()
        await browser.close()
        stop_sessions(sessions)
        keep_log(window.shots)
        stop_daemon()
        cleanup(root)


async def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for n in range(1, runs + 1):
        try:
            await one_run(n)
        except Exception as e:  # a run that breaks is a failed run, and the next one still runs
            check(f"[run {n}] the run finished", False, error=f"{type(e).__name__}: {e}"[:400])
    tally = defaultdict(lambda: [0, 0])
    for r in results:
        name = re.sub(r"^\[run \d+\] ", "", r["name"])
        tally[name][0] += r["ok"]
        tally[name][1] += 1
    print("\nper step:")
    for name, (ok, total) in tally.items():
        print(f"  {ok}/{total}  {name}")
    print(f"\nscreenshots: {SHOTS}")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} passed (demo meeting, {runs} runs)")


if __name__ == "__main__":
    asyncio.run(main())
