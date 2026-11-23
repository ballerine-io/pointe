"""Whisper mode in the page, in a real (headless) Chrome against a real daemon, with a call up (a quiet fake microphone).

The Whisper button turns the daemon's setting on; the card shows what it does and suggests push to talk; typing comes
forward with the box focused; the live caption is larger; "Not now" hides the suggestion and "Turn on" sets push to
talk; a change made elsewhere (the phone posts the same pref) shows here; the voice-lock note renders; "Back to
normal" turns it off; no page errors.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-wsp CLAUDE_VOICE_DAEMON_PORT=7993 CLAUDE_VOICE_TLS_PORT=7593 POINTE_CHROME_PORT=7994 \
     uv run python -u -I tests/e2e/page_whisper.py
Screenshots go to $POINTE_SHOTS.
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
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, stop_daemon  # noqa: E402
from scenarios import check as _check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7994"))


def check(name: str, got, want) -> None:
    _check(name, got == want, got=got, want=want)


def whisper() -> dict:
    return call("/voice/status")["whisper"]


CARD = "document.getElementById('whispercard').innerText"


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-whisper-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"page-whisper-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    hush = (np.random.default_rng(1).standard_normal(RATE * 4) * 20).astype(np.int16)  # a quiet room, no words
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
            hook = ("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                    "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.cdp("Page.enable")
            await page.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": hook})  # survives the key's redirect
            await page.cdp("Page.reload")
            hooked = await page.until("document.getElementById('whisperbtn') && Array.isArray(window.__errors)", 15)
            assert hooked, "the page error hook is not in place"
            pcm = base64.b64encode(hush.tobytes()).decode()
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
            check("off by default: the button says Whisper, not pressed, and no card",
                  await page.js("[document.getElementById('whisper-label').textContent, document.getElementById('whisperbtn').getAttribute('aria-pressed'), "
                                + CARD + "]"), ["Whisper", "false", ""])

            await page.js("startCall()")
            await page.until("call.state === 'live' && !document.getElementById('typed').disabled", 20)
            await page.js("document.getElementById('compose').classList.add('folded'); document.activeElement && document.activeElement.blur()")

            # ---- the button ----
            await page.js("document.getElementById('whisperbtn').click()")
            on = await page.until("document.getElementById('whisperbtn').getAttribute('aria-pressed') === 'true'", 5)
            card = await page.until(CARD, 5) or ""
            check("the Whisper button turns the daemon's setting on, and the button shows it (Whispering)",
                  [bool(on), whisper()["on"], await page.js("document.getElementById('whisper-label').textContent")],
                  [True, True, "Whispering"])
            check("the card says what it does, that recognition is limited, and suggests push to talk",
                  ["short, quiet replies" in card, "type when it matters" in card, "Push to talk. Turn it on?" in card],
                  [True, True, True])
            check("typing comes forward: the box is unfolded and focused",
                  await page.js("[document.getElementById('compose').classList.contains('folded'), document.activeElement.id]"),
                  [False, "typed"])
            await page.js("showHearing('ask billing whether the retry fix landed')")
            check("the live caption is larger while whispering",
                  await page.js("getComputedStyle(document.getElementById('caption')).fontSize"), "30px")
            await page.shot("whisper-1-on")
            await page.js("showHearing(null)")

            # ---- the push-to-talk suggestion ----
            await page.js("[...document.querySelectorAll('#whispercard button')].find(b => b.textContent === 'Not now').click()")
            gone = await page.until("!" + CARD + ".includes('Push to talk')", 3)
            check("Not now hides the suggestion while whisper mode stays on", [bool(gone), whisper()["on"]], [True, True])
            call("/voice/prefs", {"whisper": False})
            await page.until("!document.body.classList.contains('whisper')", 5)
            call("/voice/prefs", {"whisper": True})
            back = await page.until(CARD + ".includes('Push to talk')", 5)
            check("the next whisper mode asks again", bool(back), True)
            await page.js("[...document.querySelectorAll('#whispercard button')].find(b => b.textContent === 'Turn on').click()")
            ptt = await page.until("!" + CARD + ".includes('Push to talk')", 5)
            check("Turn on sets push to talk on the daemon and the suggestion goes",
                  [bool(ptt), call("/voice/prefs")["microphone"], whisper()["suggest_ptt"]], [True, "ptt", False])
            call("/voice/prefs", {"microphone": "always"})

            # ---- the same setting the phone changes ----
            call("/voice/prefs", {"whisper": False})
            off = await page.until("document.getElementById('whisperbtn').getAttribute('aria-pressed') === 'false' && "
                                   + CARD + " === ''", 5)
            await page.js("document.activeElement && document.activeElement.blur()")
            call("/voice/prefs", {"whisper": True})
            on2 = await page.until("document.body.classList.contains('whisper') && document.activeElement.id === 'typed'", 5)
            check("a change made from the phone (the same pref) shows here at once, both ways, and focuses typing",
                  [bool(off), bool(on2)], [True, True])

            # ---- the voice-lock note (the lock needs a voiceprint, so the status is given to the renderer) ----
            note = "Your voiceprint was learned from your normal voice. A whispered yes may not match it: then tap to approve."
            await page.js(f"wsp.key = ''; whisperFollow({{whisper: {{on: true, suggest_ptt: false, lock_note: {json.dumps(note)}}}}})")
            check("the voice-lock note shows in the card", note in (await page.js(CARD)), True)
            await page.shot("whisper-2-lock-note")
            await page.js("wsp.key = ''; refresh()")

            # ---- back to normal ----
            await page.until("document.getElementById('whisper-off')", 5)
            await page.js("document.getElementById('whisper-off').click()")
            done = await page.until("document.getElementById('whisperbtn').getAttribute('aria-pressed') === 'false' && "
                                    + CARD + " === ''", 5)
            check("Back to normal turns it off on the daemon and the card goes", [bool(done), whisper()["on"]], [True, False])
            await page.shot("whisper-3-off")
            check("no page errors", await page.js("window.__errors"), [])
            await page.js("endCall()")
    finally:
        chrome.terminate()
        stop_daemon()
    print(json.dumps({"passed": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results),
                      "shots": str(SHOTS)}))
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
