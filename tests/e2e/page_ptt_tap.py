"""Tap to talk in the page (docs/design/push-to-talk-modes.md), in a real (headless) Chrome with its own call: a fake
microphone keeps asking a question.

Settings switches the microphone to push to talk and the talk button to Tap to talk (kept in this browser); one click on
the ring opens the gate and the page says "Talking · tap to send", the words are heard while nothing holds the button,
the next click sends (the gate closes, the page says Sent, then Tap to talk); the talk key taps the same way, its key-up
is nothing; `pointe talk` from a shell still toggles; back on Hold to talk a quick click heard no word and the page points
at Tap to talk.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-ptt-tap CLAUDE_VOICE_DAEMON_PORT=7923 CLAUDE_VOICE_TLS_PORT=7523 \\
     uv run python -u -I tests/e2e/page_ptt_tap.py
Takes about a minute. Screenshots go to $POINTE_SHOTS.
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

DEBUG_PORT = 9339  # page_ptt.py has 9337; parallel runs each need their own
STATE_LINE = "document.getElementById('state').textContent"


async def key(page: Page, kind: str) -> None:
    await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})


async def click(page: Page) -> None:
    box = await page.js("(() => { const r = document.getElementById('mic').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    for kind in ("mousePressed", "mouseReleased"):
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


async def bot_quiet() -> None:
    await until(lambda: call("/voice/status")["speaking"] != "bot", 30)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-ptt-tap-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"page-ptt-tap-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    question = await synth("What time zone is Lisbon in?")
    loop = np.concatenate([np.zeros(RATE * 2, np.int16), question, np.zeros(RATE * 2, np.int16)])
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

            # ---- Settings: push to talk, tapped ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open') && document.getElementById('pref-key').textContent", 5)
            before = await page.js("document.getElementById('pref-style').value")
            await page.js("document.getElementById('pref-mic').value = 'ptt'; document.getElementById('pref-style').value = 'tap'; saveSettings()")
            saved = await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            kept = await page.js("[ptt.style, localStorage.getItem('pointe.pttStyle')]")
            await page.shot("ptt-tap-0-settings")
            check("Settings → Microphone sets push to talk for the daemon and Tap to talk for this browser (Hold by default)",
                  bool(saved) and call("/voice/prefs")["microphone"] == "ptt" and before == "hold" and kept == ["tap", "tap"],
                  before=before, kept=kept, prefs=call("/voice/prefs").get("microphone"))

            # ---- the call, closed ----
            await page.js("startCall()")
            live = await page.until("call.state === 'live'", 15)
            idle = await page.until(f"document.body.dataset.state === 'ptt' && {STATE_LINE}", 40)
            hint = await page.js("document.getElementById('keyhint').textContent")
            label = await page.js("document.getElementById('mic').getAttribute('aria-label')")
            await page.shot("ptt-tap-1-closed")
            check("closed, the line, the ring and the hint say tap", bool(live) and idle == "Tap to talk" and label == "Tap to talk"
                  and hint == "Tap Space to talk, again to send · Caps Lock toggles", state=idle, label=label, hint=hint)

            # ---- one click opens, the words are heard with nothing held, the next click sends ----
            await until(lambda: call("/voice/status")["speaking"] == "bot", 12)  # the greeting on connect
            await bot_quiet()
            await asyncio.sleep(1)
            turns_before = len(log_lines(r"user said: "))
            await click(page)
            opened = await until(lambda: gate()["open"], 3)
            talking = await page.until(f"document.body.dataset.state === 'talking' && {STATE_LINE}", 3)
            await page.shot("ptt-tap-2-talking")
            draft = await page.until(DRAFT, 10)  # the words show as a draft while the press is open
            await page.shot("ptt-tap-2b-draft")
            await asyncio.sleep(6)  # the question again, and its pauses, with nothing held
            still = gate()["open"] and await page.js("pttOpen()")
            mid_press = len(log_lines(r"user said: ")) - turns_before
            kept = len(log_lines(r"ptt: heard "))
            await click(page)
            sent = await page.js(STATE_LINE)  # "Sent" for 0.6 s, unless the answer already began
            closed = await until(lambda: not gate()["open"], 3)
            got = await until(lambda: heard("Lisbon"), 15)
            settled = await page.until(f"{STATE_LINE} !== 'Sent' && {STATE_LINE}", 3)
            check("one click opens the gate (Talking · tap to send), the question is heard with nothing held, the next click sends",
                  bool(opened) and talking == "Talking · tap to send" and bool(still) and bool(closed) and bool(got)
                  and sent in ("Sent", "Speaking", "Hearing you") and settled in ("Tap to talk", "Speaking", "Hearing you"),
                  talking=talking, still_open=still, sent=sent, heard=got, settled=settled, gate=gate())
            await asyncio.sleep(2)
            turns = len(log_lines(r"user said: ")) - turns_before
            check("a press is one message: nothing said while open is a turn, pauses included; the second tap sends it all as one",
                  draft == "Draft · not sent yet" and mid_press == 0 and kept >= 1 and turns == 1
                  and len(log_lines(r"ptt: sent as one turn")) >= 1,
                  draft=draft, turns_while_open=mid_press, finals_kept=kept, turns_after=turns)
            await bot_quiet()

            # ---- the key taps too: the key-up is nothing ----
            await page.js("document.activeElement.blur()")
            await key(page, "keyDown")
            await key(page, "keyUp")
            key_on = await until(lambda: gate()["open"], 3)
            await asyncio.sleep(1.5)
            key_still = gate()["open"]
            await key(page, "keyDown")
            await key(page, "keyUp")
            key_off = await until(lambda: not gate()["open"], 3)
            check("the talk key taps the same way: down and up opens, down and up again sends", bool(key_on) and key_still and bool(key_off),
                  on=key_on, still=key_still, off=key_off)

            # ---- pointe talk still toggles ----
            await bot_quiet()
            cli = subprocess.run([str(ROOT / "bin" / "pointe"), "talk"], env=dict(os.environ), capture_output=True, text=True)
            remote_on = await until(lambda: gate()["open"], 3)
            remote_talking = await page.until(f"document.body.dataset.state === 'talking' && {STATE_LINE}", 3)
            cli_off = subprocess.run([str(ROOT / "bin" / "pointe"), "talk"], env=dict(os.environ), capture_output=True, text=True)
            remote_off = await until(lambda: not gate()["open"], 3)
            check("pointe talk from outside the page toggles as before, and the page shows the tap wording",
                  cli.returncode == 0 and bool(remote_on) and remote_talking == "Talking · tap to send" and cli_off.returncode == 0 and bool(remote_off),
                  cli=[cli.stdout.strip(), cli.stderr.strip()[-200:]], talking=remote_talking)
            await bot_quiet()

            # ---- back on Hold to talk: a quick click hears no word and points at Tap to talk ----
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            await page.js("document.getElementById('pref-style').value = 'hold'; saveSettings()")
            await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            await bot_quiet()
            hold_idle = await page.until(f"{STATE_LINE} === 'Hold to talk' && {STATE_LINE}", 10)
            await click(page)
            hinted = await page.until(f"{STATE_LINE}.startsWith('Hold to talk · or choose Tap to talk') && {STATE_LINE}", 3)
            await page.shot("ptt-tap-3-short-press")
            quick_closed = await until(lambda: not gate()["open"], 3)
            back = await page.until(f"{STATE_LINE} === 'Hold to talk' && {STATE_LINE}", 5)
            check("on Hold to talk a quick click closes at once and the line says where Tap to talk is, for two seconds",
                  hold_idle == "Hold to talk" and bool(hinted) and bool(quick_closed) and back == "Hold to talk",
                  idle=hold_idle, hinted=hinted, closed=quick_closed, back=back)

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
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page tap to talk)")


asyncio.run(main())
