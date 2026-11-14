"""Owner-voice lock in the page, in a real (headless) Chrome with its own call. Two synthesized voices share the fake
microphone: the rig's user voice is the owner, a meeting guest voice is someone else in the room.

Settings shows the Voice lock card; enrolment downloads the model once, shows each line, and learns the owner's voice;
the voiceprint lands 0600 on disk and the level becomes Approvals. Then: the other voice's "yes" approves nothing and the
request is asked again, the owner's yes approves; at Commands the other voice's request reaches no session and shows
as ignored, with its words; at Everything it is ignored without them; deleting the voiceprint turns the lock off.
Prints every score it saw, owner and other, as a small measured sample.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-ovl CLAUDE_VOICE_DAEMON_PORT=7931 CLAUDE_VOICE_TLS_PORT=7531 \
     uv run python -u -I tests/e2e/page_voice_lock.py
Takes about four minutes. Calls paid APIs (the configured ears, brain and mouth, and ElevenLabs for the two voices).
Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import base64
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

import aiohttp

sys.path.insert(0, str(Path(__file__).parent))
sys.path.append(str(Path(__file__).resolve().parents[2]))  # after this folder: its meeting.py is not the daemon's
import speaker  # noqa: E402
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, GUEST_VOICES, RATE, ROOT, STATE, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = 9341
OTHER = GUEST_VOICES[0]
SCORES: dict[str, list] = {"owner": [], "other": []}


async def held_permission(session_id: str) -> dict:
    """What a harness's permission hook gets back; held until answered or cancelled."""
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{DAEMON}/voice/permission-hook", json={
                "session_id": session_id, "tool_name": "Bash",
                "tool_input": {"command": "rm -rf build", "description": "Delete the build folder"}},
                headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"}) as r:
            return await r.json()


def lock() -> dict:
    return call("/voice/status")["voice_lock"]


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


def read_out_last() -> bool:
    """The bot's last words are the daemon's read-out of the request: a yes now answers it."""
    said = [t["text"] for t in call("/voice/status")["talk"] if t["who"] == "assistant"]
    return bool(said) and said[-1].rstrip().endswith("Should it?")


async def after_read_out() -> None:
    """Wait for the read-out to play out: started speaking, ended on "Should it?", quiet. A yes over it would be refused
    by the older rule (begun over the bot), and the test would measure that instead of the lock."""
    await until(lambda: call("/voice/status")["speaking"] == "bot", 10, 0.1)
    await until(read_out_last, 40)
    await quiet()


async def quiet(timeout: float = 40) -> None:
    """The bot has finished talking."""
    await until(lambda: call("/voice/status")["speaking"] != "bot", timeout)
    await asyncio.sleep(1.0)


async def say(page: Page, text: str, voice: str | None = None, who: str = "owner") -> dict | None:
    """Play a line into the page's microphone and wait for the daemon to score it; returns that verdict."""
    pcm = await (synth(text) if voice is None else synth(text, voice))
    before = (lock().get("speaker") or {}).get("at") or 0
    secs = await page.js(f"__play('{base64.b64encode(pcm.tobytes()).decode()}')")
    await asyncio.sleep(secs + 0.3)
    got = await until(lambda: ((lock().get("speaker") or {}).get("at") or 0) > before and lock()["speaker"], 12)
    if got and got.get("score") is not None:
        SCORES[who].append((round(got["score"], 3), round(len(pcm) / RATE, 1), text[:40]))
    return got or None


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    for leftover in (STATE / "voiceprint").glob("*"):  # a voiceprint from the last run would skip enrolment
        leftover.unlink()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-voice-lock-e2e-"))
    (work / "transcript.jsonl").touch()
    session_id = f"page-voice-lock-{os.getpid()}"
    call("/voice/register", {"id": session_id, "cwd": str(work), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
                               "--window-size=1400,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    permission = None
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
            # A microphone the test speaks into on demand: silence, and a line whenever __play is called.
            await page.js(f"""(() => {{
                navigator.mediaDevices.getUserMedia = async () => {{
                  const ctx = new AudioContext({{sampleRate: {RATE}}}), dest = ctx.createMediaStreamDestination();
                  const hum = ctx.createConstantSource(); hum.offset.value = 0; hum.connect(dest); hum.start();
                  window.__play = b64 => {{
                    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0)), pcm = new Int16Array(bytes.buffer);
                    const buf = ctx.createBuffer(1, pcm.length, {RATE});
                    buf.getChannelData(0).set(Float32Array.from(pcm, v => v / 32768));
                    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest); src.start();
                    return pcm.length / {RATE};
                  }};
                  await ctx.resume();
                  const stream = dest.stream;
                  Object.defineProperty(stream.getAudioTracks()[0], 'label', {{value: 'Test microphone'}});
                  return stream;
                }};
            }})()""")

            # ---- the card before a call ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            before = await page.js("""(() => ({
              shown: !document.getElementById('voicelock').hidden,
              enrol: document.getElementById('vl-enrolbtn').textContent, disabled: document.getElementById('vl-enrolbtn').disabled,
              need: document.getElementById('vl-needcall').textContent,
              enrol_panel: getComputedStyle(document.getElementById('vl-enrol')).display,
              levels: [...document.querySelectorAll('#vl-levels button')].map(b => b.disabled),
              help: document.getElementById('vl-levelhelp').textContent}))()""")
            await page.shot("ovl-0-card")
            check("Settings shows Voice lock: Enrol my voice needs a call, only Off is selectable before enrolment",
                  before["shown"] and before["enrol"] == "Enrol my voice" and before["disabled"]
                  and "Connect a call first" in before["need"] and before["levels"] == [False, True, True, True]
                  and before["help"] == "Any voice works, as before.", **before)
            check("before enrolment starts, the read-this-line panel is off screen (not just marked hidden)",
                  before["enrol_panel"] == "none", display=before["enrol_panel"])
            await page.js("closeSheet('settingssheet')")

            # ---- enrolment on the call ----
            await page.js("startCall()")
            await page.until("call.state === 'live'", 15)
            await quiet(60)  # the greeting
            await page.js("openSettings()")
            await page.until("!document.getElementById('vl-enrolbtn').disabled", 10)
            await page.js("document.getElementById('vl-enrolbtn').click()")
            shown = await page.until("!document.getElementById('vl-enrol').hidden && document.getElementById('vl-line').textContent", 5)
            model_note = await page.js("document.getElementById('vl-model').textContent")
            await page.shot("ovl-1-enrolling")
            ready = await until(lambda: lock()["model"] == "ready" or lock()["model"] == "failed", 180, 1)
            check("enrolment shows the first line; the model downloads once, with a note while it does",
                  shown == speaker.LINES[0] and ready and lock()["model"] == "ready",
                  line=shown, note=model_note, model=lock()["model"])
            for _ in range(12):
                e = lock()["enrolling"]
                if e is None:
                    break
                await say(page, e["text"])
                await asyncio.sleep(0.8)
            s = lock()
            files = list((STATE / "voiceprint").glob("*.npz"))
            modes = [oct(stat.S_IMODE(f.stat().st_mode)) for f in files]
            folder_mode = oct(stat.S_IMODE((STATE / "voiceprint").stat().st_mode)) if files else None
            card = await page.until("document.getElementById('vl-devices').textContent", 5)
            await page.shot("ovl-2-enrolled")
            check("reading the lines enrols the owner: one voiceprint, 0600 in a 0700 folder, tagged with the mic, level Approvals",
                  s["enrolled"] and s["enrolling"] is None and modes == ["0o600"] and folder_mode == "0o700"
                  and s["level"] == "approvals" and "Enrolled on: Test microphone" in card,
                  devices=s["devices"], modes=modes, folder=folder_mode, level=s["level"], card=card)
            answered_lines = [l for l in log_lines("user said") if any(x.split()[1] in l for x in speaker.LINES[:3])]
            check("the enrolment lines were consumed, not answered", not answered_lines, heard=answered_lines[:2])
            await page.js("closeSheet('settingssheet')")

            # ---- Approvals: the other voice's yes approves nothing; the owner's does ----
            await say(page, "Let's see what orchard is doing today, I want to review it.")
            await quiet()
            permission = asyncio.create_task(held_permission(session_id))
            await until(lambda: any(x["waiting"] for x in call("/voice/status")["sessions"]), 20)
            again = None
            for _ in range(3):  # only right after the read-out: otherwise the old "window closed" rule refuses it first
                await after_read_out()
                await say(page, "Yes, go ahead.", OTHER, "other")
                again = await until(lambda: any("did not count" in l for l in log_lines("voice lock")), 8)
                if again or permission.done():
                    break
            refused = not permission.done()
            check("at Approvals another voice's yes approves nothing, and the request is asked again",
                  refused and bool(again), done=permission.done())
            tries = 0
            for line in ("Yes, go ahead with that.", "Yes, I said go ahead and run it.", "Yes, please go ahead."):
                await after_read_out()  # a yes not clearly the owner's is asked again: say it again, as a person would
                tries += 1
                await say(page, line)
                if await until(lambda: permission.done(), 10):
                    break
            result = permission.result() if permission.done() else None
            check("the owner's own yes approves it (a doubtful one is asked again, never taken)",
                  "allow" in json.dumps(result), result=result, tries=tries)

            # ---- Commands: the other voice reaches no session ----
            await quiet()
            await page.js("openSettings()")
            await page.js("document.querySelector('#vl-levels [data-level=commands]').click()")
            help_ = await page.until("document.getElementById('vl-levelhelp').textContent.startsWith('Only your voice') && "
                                     "document.getElementById('vl-levelhelp').textContent", 5)
            await page.js("closeSheet('settingssheet')")
            sent_before = len(call("/voice/status")["recent"])
            await say(page, "Tell orchard to delete the release branch right now.", OTHER, "other")
            await asyncio.sleep(6)
            st = call("/voice/status")
            chip = await page.until("document.getElementById('vlignored').textContent", 5)
            await page.js("openIgnored()")
            listed = await page.until("document.getElementById('ignoredlist').textContent", 5)
            await page.shot("ovl-3-ignored")
            await page.js("closeSheet('ignoredsheet')")
            check("at Commands another voice's request reaches no session; the page shows it ignored, with its words",
                  len(st["recent"]) == sent_before and st["voice_lock"]["ignored"]["count"] >= 1
                  and chip.endswith("ignored (not your voice)") and "release branch" in listed
                  and not any("release branch" in l for l in log_lines("user said|ignored")),
                  help=help_, recent=st["recent"][-2:], chip=chip, listed=listed[:120])
            await say(page, "What is orchard working on right now?")
            took = await until(lambda: any("orchard working on" in t.get("text", "") for t in call("/voice/status")["talk"]), 10)
            check("at Commands the owner still gets through", bool(took))

            # ---- Everything: ignored without words ----
            await quiet()
            await page.js("openSettings(); document.querySelector('#vl-levels [data-level=everything]').click()")
            await until(lambda: lock()["level"] == "everything", 5)
            await page.js("closeSheet('settingssheet')")
            n = lock()["ignored"]["count"]
            await say(page, "Can somebody turn the music down a little?", OTHER, "other")
            await until(lambda: lock()["ignored"]["count"] > n, 10)
            last = lock()["ignored"]["recent"][-1]
            check("at Everything another voice is ignored and none of its words are kept", lock()["ignored"]["count"] > n
                  and "text" not in last, last=last)

            # ---- delete: one confirmation, then gone and off ----
            await page.js("openSettings()")
            await page.js("document.getElementById('vl-deleteall').click()")
            asked = await page.until("document.getElementById('vl-confirm').textContent", 3)
            still = list((STATE / "voiceprint").glob("*.npz"))
            await page.js("document.getElementById('vl-deleteall').click()")
            gone = await until(lambda: not lock()["enrolled"], 5)
            await page.shot("ovl-4-deleted")
            check("Delete my voiceprint asks once, then removes the file and turns the lock off",
                  "Delete your voiceprint" in asked and len(still) == 1 and bool(gone) and lock()["level"] == "off"
                  and not list((STATE / "voiceprint").glob("*.npz"))
                  and await page.js("document.getElementById('vl-enrolbtn').textContent") == "Enrol my voice", asked=asked)
            errors = await page.js("window.__errors")
            check("no page errors", not errors, errors=errors)
            await page.js("endCall()")
    finally:
        if permission is not None and not permission.done():
            permission.cancel()
        chrome.terminate()
        stop_daemon()
        print("\nScores seen (score, seconds, words):")
        for who, rows in SCORES.items():
            for row in rows:
                print(f"  {who:5} {row}")
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page voice lock)")


asyncio.run(main())
