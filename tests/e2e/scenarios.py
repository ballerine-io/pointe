"""Scenario suite against a real Claude Code session. Run: uv run python -I tests/e2e/scenarios.py

Each check prints PASS/FAIL with the measured numbers and the transcript, and the
run ends with a summary. The sample repo is reset before the run.
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
from rig import Browser, ClaudeSession, fresh_state, log_lines, stop_daemon, transcribe  # noqa: E402
from hook_session import JoinedSession  # noqa: E402

REPO = Path(os.environ.get("CLAUDE_VOICE_TEST_REPO", "/tmp/cv-repo"))
# These suites test the voice layer, not Claude Code: a fast model keeps them quick.
TEST_MODEL = os.environ.get("CLAUDE_VOICE_TEST_MODEL", "haiku")
FRONT = sys.argv[1] if len(sys.argv) > 1 else "gemini"
ECHO_GAIN = float(os.environ.get("POINTE_ECHO_GAIN", "0"))  # > 0: the speakers leak into the mic, as on a laptop
results: list[dict] = []


def check(name: str, ok: bool, **info) -> None:
    results.append({"name": name, "ok": bool(ok), **info})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(info, ensure_ascii=False)[:400]}", flush=True)


async def reply_after(b: Browser, t: float, timeout: float = 20, quiet: float = 1.8) -> tuple[float | None, str]:
    """Wait for the bot to speak after time t and finish; returns (first audio time, transcript)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = b.speaker.speech_spans(since=t)
        if spans and time.time() - spans[-1][1] > quiet:
            return spans[0][0], await transcribe(b.speaker.audio(spans[0][0], spans[-1][1]))
        await asyncio.sleep(0.2)
    spans = b.speaker.speech_spans(since=t)
    if spans:
        return spans[0][0], await transcribe(b.speaker.audio(spans[0][0], spans[-1][1]))
    return None, ""


async def wait_log(pattern: str, after: int, timeout: float) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        lines = log_lines(pattern)
        if len(lines) > after:
            return lines[after]
        await asyncio.sleep(0.5)
    return None


async def ask(b: Browser, text: str, timeout: float = 20) -> tuple[float | None, float, str]:
    _, end = await b.say(text)
    await asyncio.sleep(max(0, end - time.time()))
    first, said = await reply_after(b, end, timeout)
    return first, end, said


def log_time(line: str) -> float:
    return time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S")) + float("0" + line[19:23])


async def spoken_after(b: Browser, t: float, timeout: float = 20) -> str:
    """Transcript of the first thing the bot says after wall time t."""
    first, said = await reply_after(b, t, timeout)
    return said


def _daemon(path: str, body: dict | None = None) -> dict:
    import urllib.request
    from rig import DAEMON, STATE
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                              "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=10).read())
    except Exception:
        return {}


def daemon_status() -> dict:
    return _daemon("/voice/status") or {"sessions": []}


def tap(session: dict, decision: str) -> None:
    """What a person does on the page for a request the voice cannot read out."""
    _daemon("/voice/approve", {"session": session["name"], "request_id": session["request_id"], "decision": decision})


async def drive_permissions(b: Browser, answer: str, n_perm: int, n_stop: int, timeout: float = 180) -> list[str]:
    """Answer every permission prompt by voice until Claude Code ends its turn. Returns what the bot said."""
    spoken: list[str] = []
    deadline = time.time() + timeout
    n_read = None  # a request is read out again after anything else was said: a person answers that too
    while time.time() < deadline:
        if len(log_lines("finished its turn")) > n_stop:
            return spoken
        perms, reads = log_lines("permission request"), log_lines(r"speak:.*(Should it\?|לבצע\?)")
        asked = None
        if len(perms) > n_perm:
            asked = log_time(perms[n_perm])
            n_perm += 1
        elif n_read is not None and len(reads) > n_read:
            asked = log_time(reads[n_read])
        if asked:
            spoken.append(await spoken_after(b, asked, timeout=25))
            n_read = len(log_lines(r"speak:.*(Should it\?|לבצע\?)"))  # before the answer: it may bring another read-out
            waiting = [x for x in daemon_status()["sessions"] if x.get("request_id")]
            if waiting and not waiting[0].get("voice_can_approve"):  # too complex to read out: a person taps, as the bot asks
                tap(waiting[0], "deny" if re.match(r"\s*no\b", answer, re.I) else "allow")
            else:
                await b.say(answer)
            await asyncio.sleep(3)
        await asyncio.sleep(0.5)
    return spoken


async def all_speech_since(b: Browser, t: float, settle: float = 12) -> str:
    """Everything the bot said after t, once it has been quiet for a while."""
    await asyncio.sleep(settle)
    spans = b.speaker.speech_spans(since=t)
    return await transcribe(b.speaker.audio(spans[0][0], spans[-1][1])) if spans else ""


def latency(first: float | None, end: float) -> float | None:
    return round(first - end, 2) if first else None


SAMPLE = {
    "pricing.py": 'def apply_discount(price: float, percent: float) -> float:\n'
                  '    """Return price after a percentage discount."""\n'
                  '    return price - price * percent\n\n\n'
                  'def total(items: list[tuple[float, int]]) -> float:\n'
                  '    return sum(p * q for p, q in items)\n',
    "test_pricing.py": 'from pricing import apply_discount, total\n\n'
                       'def test_discount():\n    assert apply_discount(100, 10) == 90\n\n'
                       'def test_total():\n    assert total([(2.5, 2), (1, 3)]) == 8\n',
    "README.md": "# Shop\nTiny pricing module used by the checkout service.\n",
}


def reset_repo(repo: Path = REPO) -> None:
    """A tiny repo with one planted bug, back at its initial commit."""
    if (repo / ".git").exists() and subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True).returncode:
        shutil.rmtree(repo)  # macOS clears old files from /tmp: a repo missing its HEAD is rebuilt, not reset
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        for name, body in SAMPLE.items():
            (repo / name).write_text(body)
        subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                       shell=True, cwd=repo, check=True)
    subprocess.run("git reset -q --hard $(git rev-list --max-parents=0 HEAD) && git clean -qfd",
                   shell=True, cwd=repo, check=True)


async def main():
    reset_repo()
    fresh_state()
    n_allow = 0
    session = JoinedSession(REPO, "--model", TEST_MODEL, "--permission-mode", "default", front=FRONT)
    session.start()
    b = Browser(echo_gain=ECHO_GAIN)
    try:
        t0 = time.time()
        await b.connect()
        first, greeting = await reply_after(b, t0, timeout=20)
        check("greeting on connect", first is not None, latency_s=latency(first, t0), said=greeting)

        n_deleg = len(log_lines(" - -> "))
        first, end, said = await ask(b, "Quick one. What's the difference between a mutex and a semaphore?")
        check("concept question answered directly, fast",
              first is not None and latency(first, end) < 3.5 and len(log_lines(" - -> ")) == n_deleg,
              latency_s=latency(first, end), said=said)

        # Barge-in: interrupt a long answer and switch topic.
        _, end = await b.say("Explain in detail how TCP congestion control works, slow start, everything.")
        await asyncio.sleep(max(0, end - time.time()))
        started, _ = await reply_after(b, end, timeout=10, quiet=0.0)
        await asyncio.sleep(2.5)
        cut_start, cut = await b.say("Stop. Different question: what time zone is Tel Aviv in?")
        await asyncio.sleep(max(0, cut - time.time()))
        spans_during = [s for s in b.speaker.speech_spans(since=started or end) if s[0] < cut_start]
        stopped_at = spans_during[-1][1] if spans_during else None
        was_talking = stopped_at is not None and stopped_at > cut_start
        first, said = await reply_after(b, cut, timeout=15)
        check("barge-in stops playback and follows the new topic",
              was_talking and stopped_at - cut_start < 1.5
              and re.search(r"israel|IST|GMT\s*\+\s*2|UTC\s*\+\s*2|IDT|jerusalem", said, re.I) is not None,
              was_talking=was_talking, stop_delay_s=round(stopped_at - cut_start, 2) if stopped_at else None, said=said)

        # Delegation with a voice-approved permission, and a side question while Claude works.
        n_deleg = len(log_lines(" - -> "))
        n_perm = len(log_lines("permission request"))
        n_stop = len(log_lines("finished its turn"))
        first, end, said = await ask(b, "Run the tests in this repo and tell me what fails.")
        delegated = await wait_log(" - -> ", n_deleg, timeout=10)
        check("repo task is delegated to Claude Code", delegated is not None, delegated=delegated and delegated[-160:], said=said)

        first, end, said = await ask(b, "While that runs, suggest a good name for a pricing microservice.")
        check("side question answered while Claude Code works",
              first is not None and latency(first, end) < 4.0, latency_s=latency(first, end), said=said)

        spoken = await drive_permissions(b, "Yes, go ahead.", n_perm, n_stop)
        check("permission requests are spoken and approved by voice",
              bool(spoken) and all(spoken) and len(log_lines("finished its turn")) > n_stop, said=spoken)
        report = await spoken_after(b, log_time(log_lines("finished its turn")[-1]) if len(log_lines("finished its turn")) > n_stop else time.time(), timeout=30)
        check("result is reported back in a short summary",
              bool(report) and re.search(r"discount|fail|pass", report, re.I) is not None and len(report) < 600,
              said=report)

        # Deny path.
        n_perm = len(log_lines("permission request"))
        n_stop = len(log_lines("finished its turn"))
        await ask(b, "Ask Claude Code to delete the README file.")
        spoken = await drive_permissions(b, "No. Deny that.", n_perm, n_stop, timeout=90)
        # Claude Code itself may refuse a delete that came by voice and ask for it to be typed: then nothing is asked here.
        check("a delete asked by voice does not happen without the user", (REPO / "README.md").exists(), said=spoken)
        await reply_after(b, time.time(), timeout=20)

        # Silence never approves.
        n_allow = len(log_lines(r"-> allow"))
        n_perm = len(log_lines("permission request"))
        n_stop = len(log_lines("finished its turn"))
        await ask(b, "Ask Claude Code to create an empty file called scratch.txt.")
        perm = await wait_log("permission request", n_perm, timeout=60)
        await asyncio.sleep(20)
        check("silence never approves a permission",
              perm is not None and not (REPO / "scratch.txt").exists() and len(log_lines(r"-> allow")) == n_allow,
              refused=len(log_lines("answer_permission refused")))
        await drive_permissions(b, "Yes, go ahead.", n_perm, n_stop, timeout=60)
        check("a spoken yes then approves it", (REPO / "scratch.txt").exists())
        # A denial by voice. Asked last: after a denial Claude Code checks in conversation before writing again.
        n_perm = len(log_lines("permission request"))
        n_stop = len(log_lines("finished its turn"))
        before = {p.name for p in REPO.iterdir()}
        await ask(b, "Ask Claude Code to create a file called notes two dot text with the word hello in it.")
        spoken = await drive_permissions(b, "No. Deny that.", n_perm, n_stop, timeout=90)
        created = sorted({p.name for p in REPO.iterdir()} - before)  # any name: speech-to-text may spell it differently
        check("deny by voice stops the change", bool(spoken) and not created, said=spoken, created=created)

        # Research in the background while the conversation moves on.
        n_deleg = len(log_lines(" - -> "))
        n_stop = len(log_lines("finished its turn"))
        await ask(b, "Have Claude Code look through the repo and explain how pricing works and what "
                     "edge cases the discount function misses. I don't want any changes.")
        delegated = await wait_log(" - -> ", n_deleg, timeout=10)
        chat = []
        for q in ["Meanwhile, what's your take on Postgres versus MySQL for a small team?",
                  "And should we use feature flags for a change like this?"]:
            first, end, said = await ask(b, q)
            chat.append((latency(first, end), said))
        check("keeps chatting while research runs",
              delegated is not None and all(l is not None and l < 4.0 for l, _ in chat),
              chat=chat, research_done_early=len(log_lines("finished its turn")) > n_stop)
        await drive_permissions(b, "Yes, go ahead.", len(log_lines("permission request")), n_stop, timeout=240)
        stop_line = log_lines("finished its turn")[-1] if len(log_lines("finished its turn")) > n_stop else None
        cut_end = None
        if stop_line:
            # Talk over the report as it starts: it must come back once the user is answered.
            started, _ = await reply_after(b, log_time(stop_line), timeout=20, quiet=0.0)
            if started and time.time() - started < 6:
                await asyncio.sleep(1.2)
                _, cut_end = await b.say("Sorry, quick one first: what is two plus two?")
        report = await all_speech_since(b, log_time(stop_line), settle=25) if stop_line else ""
        check("research result is picked up and reported",
              bool(report) and re.search(r"negative|over 100|100|percent|zero|edge|validat", report, re.I) is not None,
              said=report)
        if cut_end is None:
            print("SKIP  a report the user talked over still gets delivered  (report finished before it could be "
                  "talked over)", flush=True)
        else:
            after_cut = await all_speech_since(b, cut_end, settle=0)
            check("a report the user talked over still gets delivered",
                  re.search(r"discount|percent|negative|fraction", after_cut, re.I) is not None,
                  resumed=len(log_lines(r"\[resume\]")), said=after_cut)
        n_deleg = len(log_lines(" - -> "))
        first, end, said = await ask(b, "Which of those edge cases worries you most?")
        check("follow-up is answered from the report without asking Claude Code again",
              bool(report) and first is not None and len(log_lines(" - -> ")) == n_deleg
              and re.search(r"negative|over 100|100|percent|zero|validat|round|float", said, re.I) is not None,
              latency_s=latency(first, end), said=said)

        # Hebrew.
        first, end, said = await ask(b, "מה ההבדל בין unit test לבין integration test? בקצרה.")
        check("Hebrew question gets a Hebrew answer",
              first is not None and re.search(r"[֐-׿]", said) is not None,
              latency_s=latency(first, end), said=said)

        n_deleg = len(log_lines(" - -> "))
        n_perm = len(log_lines("permission request"))
        n_stop_he = len(log_lines("finished its turn"))
        await ask(b, "תבקש מקלוד קוד לתקן את הבאג בפונקציית ההנחה, כך שעשר זה עשרה אחוז, ולהריץ את הבדיקות.")
        delegated = await wait_log(" - -> ", n_deleg, timeout=10)
        check("Hebrew request is delegated as a clear instruction", delegated is not None, delegated=delegated and delegated[-200:])
        await drive_permissions(b, "כן, תאשר.", n_perm, n_stop_he)
        fixed = subprocess.run(
            ["python3", "-c", "import test_pricing as t; t.test_discount(); t.test_total()"],
            cwd=REPO, capture_output=True, text=True,
        )
        stops = log_lines("finished its turn")
        report = await spoken_after(b, log_time(stops[-1]), timeout=30) if len(stops) > n_stop_he else ""
        check("Hebrew-requested fix lands and tests pass", fixed.returncode == 0,
              error=fixed.stderr.strip()[-200:], said=report)

        # Reconnect keeps context.
        await b.close()
        await asyncio.sleep(2)
        b = Browser(echo_gain=ECHO_GAIN)
        t0 = time.time()
        await b.connect()
        await reply_after(b, t0, timeout=20)
        n_deleg = len(log_lines(" - -> "))
        first, end, said = await ask(b, "What did Claude Code just fix?")
        check("reconnect never replays old requests", len(log_lines(" - -> ")) == n_deleg,
              refused=len(log_lines("send_to_claude_code refused")))
        check("after reconnect it still knows the session",
              re.search(r"discount|percent|pricing", said, re.I) is not None, said=said)
    finally:
        await b.close()
        session.stop()
        stop_daemon()
        passed = sum(r["ok"] for r in results)
        print(f"\n{passed}/{len(results)} passed ({FRONT})")
        Path("/tmp/cv-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
