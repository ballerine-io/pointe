"""Push to talk in the page, in a real (headless) Chrome with its own call: a fake microphone keeps asking a question.

Settings switches the microphone to push to talk and picks a hold key; closed, the page sends nothing and the daemon
hears nothing; the hold key, Caps Lock (a toggle, both the macOS and the other keyboards' event shapes) and a mouse hold
on the ring each open it; `pointe talk` from a shell (a system-wide shortcut, the page in the background) opens it and
the page shows Talking and sends; leaving the window lets go; a press held 90 s is closed by the daemon and the page says
so; back to always on, Space mutes again.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-ptt CLAUDE_VOICE_DAEMON_PORT=7921 CLAUDE_VOICE_TLS_PORT=7521 \
     uv run python -u -I tests/e2e/page_ptt.py
Takes about three minutes (one press is held past the 90 s limit). Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = 9337
KEYS = {"f": ("KeyF", 70, "f"), "Space": ("Space", 32, " "), "CapsLock": ("CapsLock", 20, "CapsLock")}


async def key(page: Page, name: str, kind: str) -> None:
    code, vk, k = KEYS[name]
    await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": code, "windowsVirtualKeyCode": vk})


async def mouse(page: Page, kind: str) -> None:
    box = await page.js("(() => { const r = document.getElementById('mic').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    await page.cdp("Input.dispatchMouseEvent", {"type": kind, "x": box[0], "y": box[1], "button": "left", "clickCount": 1})


def gate() -> dict:
    return call("/voice/status")["ptt"]


async def until(test, timeout: float, every: float = 0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


DRAFT = ("!document.getElementById('caption').hidden && document.getElementById('caption').classList.contains('draft') "
         "&& document.getElementById('caption-draft').textContent")


def heard(word: str) -> int:
    return sum(word.lower() in line.lower() for line in log_lines(r"user said: "))


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-ptt-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"page-ptt-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    question = await synth("What time zone is Lisbon in?")
    loop = np.concatenate([np.zeros(RATE * 2, np.int16), question, np.zeros(RATE * 2, np.int16)])
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
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
            await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('settingsbtn')", 10)
            pcm = base64.b64encode(loop.tobytes()).decode()
            await page.js(f"""(() => {{
                const bytes = Uint8Array.from(atob('{pcm}'), c => c.charCodeAt(0)), pcm = new Int16Array(bytes.buffer);
                navigator.mediaDevices.getUserMedia = async () => {{
                  const ctx = new AudioContext({{sampleRate: {RATE}}}), buf = ctx.createBuffer(1, pcm.length, {RATE});
                  buf.getChannelData(0).set(Float32Array.from(pcm, v => v / 32768));
                  const src = ctx.createBufferSource(); src.buffer = buf; src.loop = true;
                  const dest = ctx.createMediaStreamDestination(); src.connect(dest); src.start(); await ctx.resume();
                  return dest.stream;
                }};
            }})()""")

            # ---- Settings: microphone and hold key ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open') && document.getElementById('pref-key').textContent", 5)
            before = await page.js("document.getElementById('pref-key').textContent")
            await page.js("document.getElementById('pref-mic').value = 'ptt'; captureKey()")
            await key(page, "f", "keyDown")
            await key(page, "f", "keyUp")
            label = await page.js("document.getElementById('pref-key').textContent")
            await page.shot("ptt-0-settings")
            await page.js("saveSettings()")
            saved = await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            check("Settings → Microphone sets push to talk for the daemon, and the hold key is captured (Space by default)",
                  bool(saved) and call("/voice/prefs")["microphone"] == "ptt" and before == "Space" and label == "F",
                  before=before, label=label, prefs=call("/voice/prefs").get("microphone"))

            # ---- the call, closed: nothing sent, nothing heard ----
            await page.js("startCall()")
            live = await page.until("call.state === 'live'", 15)
            idle = await page.until("document.body.dataset.state === 'ptt' && document.getElementById('state').textContent", 40)
            hint = await page.js("document.getElementById('keyhint').textContent")
            await page.shot("ptt-1-closed")
            check("in push to talk the ring is outlined and the state line says Hold to talk", bool(live) and idle == "Hold to talk"
                  and "Hold F to talk" in hint, state=idle, hint=hint)
            sent = await page.js("call.sent || 0")
            await asyncio.sleep(12)  # the question plays twice into the microphone meanwhile
            sent_after = await page.js("call.sent || 0")
            check("closed, the page sends no audio and the daemon passes none and hears nothing",
                  sent_after == sent and gate()["sent_bytes"] == 0 and heard("Lisbon") == 0,
                  page_chunks=[sent, sent_after], gate=gate(), heard=heard("Lisbon"))

            # ---- the hold key ----
            turns_before = len(log_lines(r"user said: "))
            await key(page, "f", "keyDown")
            opened = await until(lambda: gate()["open"], 3)
            talking = await page.until("document.body.dataset.state === 'talking' && document.getElementById('state').textContent", 3)
            await page.shot("ptt-2-talking")
            draft = await page.until(DRAFT, 10)
            await page.shot("ptt-2a-draft")
            await asyncio.sleep(6)  # the question again, and the pauses between
            mid_press = len(log_lines(r"user said: ")) - turns_before
            await key(page, "f", "keyUp")
            closed = await until(lambda: not gate()["open"], 3)
            got = await until(lambda: heard("Lisbon"), 15)
            await asyncio.sleep(1)
            tail = await page.js("call.sent || 0")
            await asyncio.sleep(3)
            check("holding the key opens the gate (ring filled, Talking), the words are heard, and letting go closes it",
                  bool(opened) and talking == "Talking" and bool(closed) and bool(got) and await page.js("call.sent || 0") == tail,
                  talking=talking, heard=got, gate=gate())
            turns = len(log_lines(r"user said: ")) - turns_before
            check("held, the words show as a draft and none is a turn, pauses included; letting go sends all of it as one turn",
                  draft == "Draft · not sent yet" and mid_press == 0 and turns == 1,
                  draft=draft, turns_while_held=mid_press, turns_after=turns)
            await until(lambda: call("/voice/status")["speaking"] != "bot", 30)

            # ---- Caps Lock is a toggle, in both event shapes ----
            await key(page, "CapsLock", "keyDown")  # macOS: a keydown when it turns on...
            on = await until(lambda: gate()["open"], 3)
            await asyncio.sleep(1.2)
            still = gate()["open"]
            await key(page, "CapsLock", "keyUp")  # ...and a keyup when it turns off
            off = await until(lambda: not gate()["open"], 3)
            await key(page, "CapsLock", "keyDown")  # other keyboards: a keydown and a keyup on each press
            await key(page, "CapsLock", "keyUp")
            on2 = await until(lambda: gate()["open"], 3)
            await asyncio.sleep(1)
            await key(page, "CapsLock", "keyDown")
            await key(page, "CapsLock", "keyUp")
            off2 = await until(lambda: not gate()["open"], 3)
            check("Caps Lock opens and closes talking as a toggle, in both keyboard event shapes",
                  bool(on) and still and bool(off) and bool(on2) and bool(off2), on=on, held_open=still, off=off, on2=on2, off2=off2)

            # ---- pointe talk, as a system-wide shortcut runs it: the page is told, shows Talking and sends ----
            await until(lambda: call("/voice/status")["speaking"] != "bot", 30)
            await page.js("document.activeElement.blur()")
            before_bytes, before_chunks = gate()["sent_bytes"], await page.js("call.sent || 0")
            cli = subprocess.run([str(ROOT / "bin" / "pointe"), "talk"], env=dict(os.environ), capture_output=True, text=True)
            remote_on = await until(lambda: gate()["open"], 3)
            remote_talking = await page.until("document.body.dataset.state === 'talking' && document.getElementById('state').textContent", 3)
            await asyncio.sleep(3)
            grew = gate()["sent_bytes"] > before_bytes and await page.js("call.sent || 0") > before_chunks
            await page.shot("ptt-2b-shortcut")
            cli_off = subprocess.run([str(ROOT / "bin" / "pointe"), "talk"], env=dict(os.environ), capture_output=True, text=True)
            remote_off = await until(lambda: not gate()["open"], 3)
            idle_again = await page.until("document.body.dataset.state !== 'talking' && document.getElementById('state').textContent", 5)
            await asyncio.sleep(1)
            quiet = await page.js("call.sent || 0")
            await asyncio.sleep(2)
            check("pointe talk from outside the page opens the gate, the page shows Talking and its audio passes; again closes it and the page stops",
                  cli.returncode == 0 and cli.stdout.strip() == "Talking." and bool(remote_on) and remote_talking == "Talking" and grew
                  and cli_off.returncode == 0 and cli_off.stdout.strip() == "Not talking." and bool(remote_off)
                  and not idle_again.startswith("Talk closed") and await page.js("call.sent || 0") == quiet,
                  cli=[cli.stdout.strip(), cli.stderr.strip()[-200:]], cli_off=cli_off.stdout.strip(), talking=remote_talking,
                  after=idle_again, gate=gate())
            await until(lambda: call("/voice/status")["speaking"] != "bot", 30)

            # ---- a mouse hold on the ring; a click is not a mute ----
            await mouse(page, "mousePressed")
            ring_on = await until(lambda: gate()["open"], 3)
            await asyncio.sleep(1)
            await mouse(page, "mouseReleased")
            ring_off = await until(lambda: not gate()["open"], 3)
            muted = await page.js("muted")
            check("holding the ring with the mouse talks, letting go stops, and it never mutes", bool(ring_on) and bool(ring_off) and not muted,
                  muted=muted)

            # ---- leaving the window lets go of a held key ----
            await key(page, "f", "keyDown")
            await until(lambda: gate()["open"], 3)
            await page.js("dispatchEvent(new Event('blur'))")
            let_go = await until(lambda: not gate()["open"], 3)
            await key(page, "f", "keyUp")
            check("leaving the window while holding the key closes the gate (its key-up never comes)", bool(let_go))

            # ---- held for 90 s: the daemon closes it, and the page says so and stops sending ----
            await until(lambda: call("/voice/status")["speaking"] != "bot", 30)
            await key(page, "f", "keyDown")
            await until(lambda: gate()["open"], 3)
            why = await until(lambda: gate()["closed_why"] if not gate()["open"] else "", 100, 1)
            line = await page.until("document.getElementById('state').textContent.startsWith('Talk closed') && document.getElementById('state').textContent", 5)
            await page.shot("ptt-3-held-too-long")
            await asyncio.sleep(1)
            n = await page.js("call.sent || 0")
            await asyncio.sleep(3)
            check("a press held 90 s is closed by the daemon; the page says why and stops sending",
                  why == "held too long" and bool(line) and await page.js("call.sent || 0") == n
                  and await page.js("document.body.dataset.state") in ("ptt", "bot", "user"), why=why, line=line)
            await key(page, "f", "keyUp")

            # ---- back to always on: Space mutes again ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            await page.js("document.getElementById('pref-mic').value = 'always'; saveSettings()")
            await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            await page.until("document.body.dataset.state !== 'ptt'", 5)
            await page.js("document.activeElement.blur()")
            await key(page, "Space", "keyDown")
            await key(page, "Space", "keyUp")
            muted = await page.until("muted && document.getElementById('state').textContent", 3)
            check("back to always on, Space mutes as before", muted == "Muted" and call("/voice/prefs")["microphone"] == "always",
                  state=muted)
            errors = await page.js("window.__errors")
            check("no page errors", not errors, errors=errors)
            await page.js("endCall()")
    finally:
        chrome.terminate()
        try:
            call("/voice/prefs", {"microphone": "always"})
        except Exception:
            pass
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page push to talk)")


asyncio.run(main())
