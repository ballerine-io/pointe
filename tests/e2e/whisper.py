"""Whisper mode, live: a fake laptop (its speaker leaks back into the mic) whispers to the real daemon, ears, brain and mouth.

The whispers are synthetic (bench/whisper_bench.py's "unvoiced": an ElevenLabs line re-synthesised over noise, no voice
tone at all) at -18 dB under the normal voice, over office noise. Checked: "whisper mode" said in a whisper turns it on;
a whispered question is heard and answered in one short sentence at half the volume; the bot's own echo is never taken
as the user; a whispered yes approves and a whispered no denies a read-out request, through the same rule as a spoken
one; "back to normal" turns it off.

Run (isolated ports; the test transcriber needs a Gemini key in the environment):
  CLAUDE_VOICE_STATE=/tmp/cv-state-wsp CLAUDE_VOICE_DAEMON_PORT=7991 CLAUDE_VOICE_TLS_PORT=7591 POINTE_CHANNEL_PORT=7992 \
    uv run python -u -I tests/e2e/whisper.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))
from page_meeting import call  # noqa: E402
from rig import ROOT, Browser, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check, reply_after, results  # noqa: E402
from whisper_bench import pink, unvoice  # noqa: E402

CHANNEL_PORT = int(os.environ.get("POINTE_CHANNEL_PORT", "7992"))
ECHO_GAIN = float(os.environ.get("ECHO_GAIN", "0.3"))
WHISPER_DB = -18.0
NOISE_RMS = 32768 * 10 ** (-55 / 20)
VERDICTS: list[dict] = []
QUESTION = "What time zone is Lisbon in?"
SENTENCE = "the quick brown fox jumps over the lazy dog"


class Channel(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if self.path == "/verdict":
            VERDICTS.append(body)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_):
        pass


async def whispered(text: str, seed: int) -> np.ndarray:
    """The line, unvoiced at 16 kHz, -18 dB under the normal voice, over office noise; back at the rig's 48 kHz."""
    normal = await synth(text)
    low = normal[: len(normal) // 3 * 3].reshape(-1, 3).mean(axis=1).astype(np.int16)
    quiet = unvoice(low, seed=seed).astype(np.float64) * 10 ** (WHISPER_DB / 20)
    quiet = np.concatenate([np.zeros(8000), quiet, np.zeros(8000)])
    quiet += pink(len(quiet), seed) * NOISE_RMS
    return np.repeat(np.clip(quiet, -32768, 32767).astype(np.int16), 3)


def users() -> list[str]:
    return [line.split("user said: ", 1)[1] for line in log_lines(r"user said: ")]


def level(browser: Browser, start: float, end: float) -> float:
    """The 95th percentile of the bot's sample amplitude between two times: robust to quiet tails and one loud word."""
    parts = [np.abs(pcm.astype(np.float64)) for t, pcm in browser.speaker.chunks if start <= t <= end and pcm.any()]
    x = np.concatenate(parts) if parts else np.zeros(1)
    return float(np.percentile(x[x > 0], 95)) if (x > 0).any() else 0.0


def whisper_on() -> bool:
    return call("/voice/status")["whisper"]["on"]


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if value := test():
            return value
        await asyncio.sleep(every)
    return test()


async def settle(browser: Browser, quiet: float = 3.0, timeout: float = 40) -> None:
    """Until the bot has said nothing for `quiet` seconds: a whisper said over the bot's own turn is a test of barge-in,
    not of hearing."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = browser.speaker.speech_spans(since=time.time() - quiet - 1, threshold=150)
        if call("/voice/status")["speaking"] != "bot" and not (spans and time.time() - spans[-1][1] < quiet):
            return
        await asyncio.sleep(0.3)


async def say(browser: Browser, pcm: np.ndarray, settled: bool = True) -> float:
    if settled:
        await settle(browser)
    _, end = browser.mic.say(pcm)
    await asyncio.sleep(max(0.0, end - time.time()))
    return end


def ask(request_id: str, command: str) -> None:
    call("/voice/permission", {"channel_url": f"http://127.0.0.1:{CHANNEL_PORT}", "request_id": request_id, "tool_name": "Bash",
                               "description": "Clear the build folder", "input_preview": json.dumps({"command": command})})


async def answer_by_whisper(browser: Browser, request_id: str, command: str, word: str, seed: int) -> list[dict]:
    t = time.time()
    ask(request_id, command)
    # The read-out itself, to its end: the first thing said after the request can be "Approved." for the one before it,
    # and the read-out then waits for the gap after that, as any update does.
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
    await until(lambda: [line for line in log_lines(r"speak: ") if line[:19] >= stamp and command in line], 45)
    await asyncio.sleep(1.0)  # its sound starts
    await settle(browser, quiet=2.5)
    await say(browser, await whispered(word, seed))
    await until(lambda: any(v.get("request_id") == request_id for v in VERDICTS), 20)
    await settle(browser)
    return [v for v in VERDICTS if v.get("request_id") == request_id]


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    server = ThreadingHTTPServer(("127.0.0.1", CHANNEL_PORT), Channel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="whisper-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"whisper-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "river-lantern",
                             "name_given": True, "transcript": str(work / "transcript.jsonl"),
                             "channel_url": f"http://127.0.0.1:{CHANNEL_PORT}"})
    browser = Browser(echo_gain=ECHO_GAIN)
    try:
        t0 = time.time()
        await browser.connect()
        await reply_after(browser, t0, timeout=25)

        # ---- normal voice: the loudness the bot has without whisper mode ----
        end = await say(browser, await synth(QUESTION))
        first, normal_said = await reply_after(browser, end, timeout=40, quiet=2.5)

        # ---- "whisper mode", whispered ----
        n_users = len(users())
        end = await say(browser, await whispered("Whisper mode.", 1))
        on = await until(whisper_on, 20)
        await reply_after(browser, end, timeout=20, quiet=2.0)
        check("\"whisper mode\" said in a whisper turns whisper mode on, in code", bool(on),
              heard=users()[n_users:], status=call("/voice/status")["whisper"])

        # ---- a whispered question: heard, answered short and at half the volume ----
        n_users = len(users())
        end = await say(browser, await whispered(QUESTION, 2))
        first, said = await reply_after(browser, end, timeout=40, quiet=2.5)
        heard = users()[n_users:]
        words = said.split()
        check("the whispered question is heard", any("lisbon" in h.lower() for h in heard), heard=heard)
        check("the answer is one short sentence (at most 20 words, as the brain is told)", 0 < len(words) <= 22,
              words=len(words), said=said, normal=normal_said)

        # ---- echo: the speaker leaks into the mic the whole time ----
        bots = [h for h in users() if "lisbon" not in h.lower() and "whisper" not in h.lower()]
        check("the bot's own (quieter) voice coming back is never taken as the user", not bots, extra_turns=bots,
              echo_dropped=len(log_lines("echo dropped")), echo_gain=ECHO_GAIN)

        # ---- a whispered yes and a whispered no to a read-out request ----
        yes = await answer_by_whisper(browser, "a1b2c3d4", "rm -rf build", "Yes.", 3)
        check("a whispered yes after the read-out approves, as a spoken one does", yes == [{"request_id": "a1b2c3d4", "behavior": "allow"}],
              verdicts=yes, heard=users()[-2:])
        no = await answer_by_whisper(browser, "b2c3d4e5", "rm -rf dist", "No.", 4)
        check("a whispered no denies", no == [{"request_id": "b2c3d4e5", "behavior": "deny"}], verdicts=no, heard=users()[-2:])
        early = time.time()
        ask("c3d4e5f6", "rm -rf cache")
        await say(browser, await whispered("Yes.", 5), settled=False)  # over the read-out, before it ends: never a yes
        await reply_after(browser, early, timeout=40, quiet=3.0)
        await asyncio.sleep(2)
        check("a whispered yes said over the read-out does not approve (the bound-yes rule is unchanged)",
              not any(v.get("request_id") == "c3d4e5f6" and v.get("behavior") == "allow" for v in VERDICTS),
              verdicts=[v for v in VERDICTS if v.get("request_id") == "c3d4e5f6"])
        call("/voice/approve", {"session": "river-lantern", "request_id": "c3d4e5f6", "decision": "deny"})

        # ---- "back to normal", whispered ----
        await until(lambda: call("/voice/status")["speaking"] != "bot", 30)
        was_on = whisper_on()
        tries = []
        for seed in (6, 7):  # a person says it again when it was misheard; each miss is reported
            await say(browser, await whispered("Back to normal.", seed))
            off = await until(lambda: not whisper_on(), 15)
            tries.append(users()[-1:] if not off else "ok")
            if off:
                break
        check("\"back to normal\" whispered turns it off (one repeat allowed)", was_on and bool(off), was_on=was_on, tries=tries)

        # ---- the same sentence, whisper mode off and on: how loud the bot plays (different sentences differ by 6 dB) ----
        levels = {}
        for on in (False, True, False, True):
            call("/voice/prefs", {"whisper": on})
            await settle(browser)
            t = time.time()
            call("/voice/say", {"text": f"Say exactly these words and nothing else: {SENTENCE}"})
            await reply_after(browser, t, timeout=30, quiet=2.0)
            levels.setdefault(on, []).append(level(browser, t, time.time()))
        ratio = float(np.mean(levels[True]) / np.mean(levels[False])) if all(levels[False]) else 0.0
        check("the bot plays at half amplitude while whispering (the same sentence, twice each way)", 0.4 <= ratio <= 0.6,
              ratio=round(ratio, 2), p95={str(k): [round(v) for v in vs] for k, vs in levels.items()})
        call("/voice/prefs", {"whisper": False})
    finally:
        await browser.close()
        stop_daemon()
        server.shutdown()
    print(json.dumps({"passed": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results)}))
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
