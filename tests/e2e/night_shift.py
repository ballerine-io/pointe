"""A short, accelerated night on real sessions (docs/design/night-shift.md). Paid: real Claude Code sessions, the voice
models and synthesized speech for the user. Run with an isolated state dir and port, never the live daemon:

  CLAUDE_VOICE_STATE=/tmp/pointe-night-state CLAUDE_VOICE_DAEMON_PORT=7931 POINTE_NIGHT_TICK_SECS=3 \
    POINTE_NIGHT_STALL_SECS=120 uv run --locked python -u -I tests/e2e/night_shift.py

Evening: three sessions join; the user says tonight's tasks; the plan is read back; a yes starts the shift; the call
ends. Night, with no call: two sessions finish (one must take a decision by itself), the third needs an approval, which
must be held, unanswered, past the five minutes a request used to be held, and written down word for word. The shift
ends at its hours. Morning: a new call; "brief me on the night" leads with the decisions; "approve billing's request"
reads the request out, and only the yes after that approves it.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hook_session import JoinedSession  # noqa: E402
from rig import STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import TEST_MODEL, _daemon, check, daemon_status, results, tap, wait_log  # noqa: E402

HOME = Path("/tmp/pointe-night")
VOICE = os.environ.get("POINTE_E2E_VOICE", "1") != "0"  # 0: the screens' routes stand in for speech (the ears' vendor is down)
HELD_PAST_SECS = 320  # a request used to go back to the terminal after 280 s (the hook's timeout was 300)
FILES = {
    "billing": {"retry.py": "def retry_delay(attempt):\n    return min(30, 2 ** attempt)\n"},
    "docs": {"CHANGELOG.md": "# Changelog\n\n## 1.4.0\n- Retries back off.\n", "README.md": "# Billing\n\nCurrent version: 1.3.9\n"},
    "shop": {"NOTES.md": "# Notes\n\nThe checkout timeout is 30 seconds in config.py.\nThe support page says 60 seconds.\n"
                         "Nobody has decided which one the support page should state.\n",
             "config.py": "CHECKOUT_TIMEOUT_SECS = 30\n"},
}
PLAN = ("Tonight: billing adds an empty file called marker to its folder with the touch command. "
        "Docs checks which version the changelog and the readme each state, and reports both, without editing anything. "
        "Shop decides which checkout timeout the support page should state, and says why, without editing anything.")


def repo(name: str) -> Path:
    path = HOME / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    for file, body in FILES[name].items():
        (path / file).write_text(body)
    subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                   shell=True, cwd=path, check=True)
    return path


def night() -> dict:
    return _daemon("/voice/night-shift")


def spoken(since: int) -> str:
    return "\n".join(log_lines(r" - speak: ")[since:])


async def until(what, timeout: float, every: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = what()
        if got:
            return got
        await asyncio.sleep(every)
    return what()


async def bot_quiet(browser, started: float, need: float = 2.5, timeout: float = 90) -> None:
    """Until the voice has spoken since `started` and then been quiet: a person answers after it finishes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = browser.speaker.speech_spans(since=started)
        if spans and time.time() - spans[-1][1] > need:
            return
        await asyncio.sleep(0.3)


async def evening_by_the_sheet(names: list[str]) -> None:
    """The start sheet's Start, with the tasks the user would have said."""
    tasks = {"billing": "Add an empty file called marker to your folder with the touch command.",
             "docs": "Check which version the changelog and the readme each state, and report both, without editing anything.",
             "shop": "Decide which checkout timeout the support page should state, and say why, without editing anything."}
    started = _daemon("/voice/night-shift", {"action": "start", "hours": 0.15, "messages": 12, "items": [
        {"session": n, "task": tasks[n.split("/")[0]]} for n in names]})
    check("Start on the sheet starts the shift", bool(started.get("started")), shift=started.get("shift", {}).get("tasks"))


async def main():
    assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_DAEMON_PORT") not in (None, "7860"), \
        "use an isolated CLAUDE_VOICE_STATE and port"
    fresh_state()
    (STATE / "night-shifts.json").unlink(missing_ok=True)
    sessions = {name: JoinedSession(repo(name), "--model", TEST_MODEL, "--permission-mode", "default") for name in FILES}
    browser = Browser()
    try:
        for s in sessions.values():
            s.start()
        await until(lambda: len(daemon_status().get("sessions", [])) == 3, 40)
        names = sorted(s["name"] for s in daemon_status()["sessions"])
        check("three real sessions are on the voice", [n.split("/")[0] for n in names] == ["billing", "docs", "shop"], names=names)
        _daemon("/voice/prefs", {"nightshift.hours": 0.15, "nightshift.messages": 12})  # a nine-minute night

        if not VOICE:
            await evening_by_the_sheet(names)
        # ----- evening: the plan by voice, the read-back, the yes -----
        await browser.connect()
        if VOICE:
            await asyncio.sleep(8)  # the greeting
            marks = len(log_lines("night shift read back"))
            said_from = len(log_lines(r" - speak: "))
            _, end = await browser.say(PLAN)
            line = await wait_log("night shift read back", marks, 60)
            check("the plan is read back from the user's words", bool(line) and all(n in (line or "") for n in ("billing", "docs", "shop")),
                  line=(line or "")[-400:])
            check("the read-back says the caps and the approval rule",
                  bool(line) and "9 minutes and 12 messages" in line and "I approve nothing" in line)
            check("nothing was sent before the yes", not log_lines("night shift -> ") and night()["shift"] is None)
            await until(lambda: "Start?" in spoken(said_from) or "Say yes or tap" in spoken(said_from), 30, 0.5)
            await asyncio.sleep(len((line or "").split("read back: ")[-1].split()) / 2.6)  # about as long as it takes to say
            await bot_quiet(browser, started=time.time() - 10, need=3.5)  # the read-back is spoken to its end before the yes
            await browser.say("Yes.")
            began = await wait_log(r"night shift \w+ started \(voice\)", 0, 40)
            check("a spoken yes starts the shift", bool(began), log=(began or "")[-160:])
        sent = await until(lambda: len(log_lines("night shift -> .*: task")) == 3 and log_lines("night shift -> .*: task"), 30)
        check("each session got its task in the night brief", bool(sent) and len(sent) == 3, sent=[s[-60:] for s in sent or []])
        await asyncio.sleep(4)
        await browser.close()
        await until(lambda: not daemon_status().get("connected"), 20)
        check("the call is over: the night runs with nobody listening", not daemon_status().get("connected"))

        # ----- night: two finish, one waits for an approval that nobody gives -----
        parked = await until(lambda: [e for e in (night()["shift"] or {}).get("ledger", {}).get("blocked", [])
                                      if e["request_id"] and e["session"].startswith("billing")], 240)
        check("billing's request is on the ledger as Blocked", bool(parked),
              blocked=[(e["session"], e["text"]) for e in parked or []])
        request = parked[0]["request"] if parked else ""
        parked_at = time.time()
        check("the exact request is written down", "touch" in request and "marker" in request, request=request)
        check("with no call the request is held, not answered", bool(log_lines("held, not answered"))
              and not log_lines(r"permission billing\S* -> "))
        attention = [a for a in daemon_status()["attention"] if str(a.get("session")).startswith("billing")]
        check("its alert is quiet: nothing notifies overnight", bool(attention) and all(a["quiet"] for a in attention),
              attention=[(a["kind"], a["quiet"]) for a in attention])
        def others() -> bool:  # each of the other two finished, or (an agent may reach for a shell) waits on an approval too
            ledger = night()["shift"]["ledger"]
            settled = {e["session"].split("/")[0] for e in ledger["done"]} | {e["session"].split("/")[0] for e in ledger["blocked"] if e["request_id"]}
            return settled >= {"docs", "shop"} and bool(ledger["done"])
        done = await until(others, 300)
        ledger = night()["shift"]["ledger"]
        check("the other sessions finished with a proof line, or wait on an approval of their own", bool(done),
              done=[(e["session"], e["proof"][:120]) for e in ledger["done"]])
        check("a decision taken without the user is on the ledger with what changes otherwise",
              any(e["choice"] for e in ledger["decided"]),
              decided=[(e["session"], e["question"][:80], e["choice"][:80], e["otherwise"][:80]) for e in ledger["decided"]])
        templates = log_lines("night shift -> ")
        check("the shift stayed inside its message budget", night()["shift"]["sent"] <= 12, sent=night()["shift"]["sent"],
              kinds=[t.split("night shift -> ")[1][:40] for t in templates])
        ended = await until(lambda: not night()["shift"]["on"], 600, 5)
        check("the shift ended at its hours", bool(ended) and night()["shift"]["why"] == "hours", why=night()["shift"]["why"])
        wait = HELD_PAST_SECS - (time.time() - parked_at)
        if wait > 0:
            print(f"… holding billing's request for {wait:.0f} more seconds, past the old five-minute limit", flush=True)
            await asyncio.sleep(wait)
        status = {s["name"].split("/")[0]: s for s in daemon_status()["sessions"]}
        held_for = time.time() - parked_at
        check(f"after {held_for:.0f} s the request is still held and still unanswered",
              bool(status["billing"]["request_id"]) and not log_lines(r"permission billing\S* -> ")
              and not log_lines("handed back to the terminal") and not (HOME / "billing" / "marker").exists(),
              waiting=status["billing"]["waiting"])
        screen = sessions["billing"].flat()
        print("    billing's terminal shows its own dialog too:", "doyouwant" in screen, flush=True)
        saved = json.loads((STATE / "night-shifts.json").read_text())["items"][-1]
        check("the ledger is on disk, 0600", oct((STATE / "night-shifts.json").stat().st_mode)[-3:] == "600"
              and len(saved["entries"]) >= 3, entries=len(saved["entries"]))

        # ----- morning: the briefing leads with the night, and the user releases the blocker -----
        browser = Browser()
        await browser.connect()
        await asyncio.sleep(10)
        led_from, said_from = len(log_lines("led by night shift")), len(log_lines(r" - speak: "))
        if VOICE:
            await browser.say("Brief me on the night.")
        else:
            _daemon("/voice/briefings", {"action": "start", "since": "the night"})  # the Briefing sheet's button
        await wait_log("led by night shift", led_from, 90)
        latest = _daemon("/voice/briefings/latest")["briefing"] or {}
        parts = latest.get("lead") or []
        order = [next((k for k, w in (("headline", "Night shift,"), ("decided", "Decisions made without you"),
                                      ("asked", "Questions waiting on you"), ("done", "Done."), ("blocked", "Blocked."),
                                      ("in_flight", "Still in flight")) if p.startswith(w)), "?") for p in parts]
        expected = [k for k in ("headline", "decided", "asked", "done", "blocked", "in_flight") if k in order]
        check("the briefing leads with the night: decisions, then questions, then done, then blocked",
              order == expected and order[:2] == ["headline", "decided"] and "done" in order and "blocked" in order, order=order)
        check("the night's sessions are not read a second time", not latest.get("sections"),
              sections=[x["session"] for x in latest.get("sections") or []])
        blocked_part = next((p for p in parts if p.startswith("Blocked.")), "")
        check("the briefing names the approval and does not quote it", re.search(r"billing\S* waits for your approval", blocked_part) is not None
              and "touch" not in blocked_part, said=blocked_part[:200])
        if VOICE:
            await asyncio.sleep(45)  # the briefing is spoken
            heard = spoken(said_from)
            check("the voice said the night first: a decision before anything done or blocked",
                  bool(re.search(r"decision", heard, re.I)) and re.search(r"decision", heard, re.I).start() < len(heard) // 2,
                  said=heard[:500])
            print("    what the voice said:\n      " + "\n      ".join(ln.split(" - speak: ", 1)[-1][:300] for ln in heard.splitlines()), flush=True)
            check("the briefing approved nothing", not log_lines(r"permission billing\S* -> "))
            await wait_log(r"briefing \w+: done", 0, 120)  # a person lets the briefing end, then answers what it left
            await bot_quiet(browser, started=time.time() - 5, timeout=20)
            asked_from, said_from = len(log_lines("reading it out")), len(log_lines(r" - speak: "))
            await browser.say("Approve billing's request.")
            await wait_log("reading it out", asked_from, 40)
            read_out = await until(lambda: [ln for ln in log_lines(r" - speak: ")[said_from:] if "Should it?" in ln], 40, 0.5)
            check("\"approve billing's request\" reads the exact request out", bool(read_out) and "touch" in read_out[-1],
                  said=(read_out or [""])[-1][-160:])
            check("those words approved nothing", not log_lines(r"permission billing\S* -> ")
                  and not (HOME / "billing" / "marker").exists())
            verdict = None
            for _ in range(3):  # a yes that lands a beat early is asked for again: a person says it once more
                await bot_quiet(browser, started=time.time() - 4, timeout=30)
                await browser.say("Yes.")
                verdict = await wait_log(r"permission billing\S* -> allow \(user said", 0, 25)
                if verdict:
                    break
            check("the yes after the read-out approves it, through the normal flow", bool(verdict), log=(verdict or "")[-120:])
        else:
            await asyncio.sleep(20)
            check("the briefing approved nothing", not log_lines(r"permission billing\S* -> "))
            waiting = next(x for x in daemon_status()["sessions"] if x["name"].startswith("billing"))
            check("the request is still the one on the ledger", waiting["request"] == request, request=waiting["request"])
            tap(waiting, "allow")  # the approval card's Approve: the user's own answer, through /voice/approve
            verdict = await wait_log(r"permission billing\S* -> allow \(tapped\)", 0, 20)
            check("the user's tap approves it, through the normal route", bool(verdict), log=(verdict or "")[-100:])
        made = await until(lambda: (HOME / "billing" / "marker").exists(), 60)
        check("billing went on and did the work", bool(made))
        entry = next((e for e in night()["shift"]["ledger"]["blocked"] if e["request_id"]), {})
        check("the ledger says who answered it", entry.get("resolved") == "approved by you", resolved=entry.get("resolved"))

        # ----- a second shift, stopped by a tap -----
        _daemon("/voice/night-shift", {"action": "start", "hours": 1, "messages": 4,
                                       "items": [{"session": next(n for n in names if n.startswith("docs")), "task": "List the files in this folder and report."}]})
        await asyncio.sleep(3)
        stopped = _daemon("/voice/night-shift", {"action": "stop"})
        check("Stop ends a running shift at once", bool(stopped.get("stopped")) and night()["shift"]["why"] == "stopped")
        sent_at_stop = len(log_lines("night shift -> "))
        await asyncio.sleep(45)
        check("after the stop nothing more is sent", len(log_lines("night shift -> ")) == sent_at_stop)

        first = _daemon(f"/voice/night-shift?id={saved['id']}")["shift"]
        print("\n--- the morning report, as built from the ledger ---")
        for part in first["morning"]:
            print(f"[{part['kind']}] {part['text']}")
        print("\n--- the blocked entry ---")
        print(json.dumps({k: entry.get(k) for k in ("session", "task", "text", "request", "resolved")}, indent=1))
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        for s in sessions.values():
            s.stop()
        stop_daemon()
    passed = sum(r["ok"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
