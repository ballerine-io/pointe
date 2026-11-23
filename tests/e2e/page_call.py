"""The page's own call client in a real (headless) Chrome: a fake microphone plays a question, the daemon answers.

Run with an isolated state: CLAUDE_VOICE_STATE=/tmp/cv-state-page CLAUDE_VOICE_DAEMON_PORT=7868 uv run python -u -I tests/e2e/page_call.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check, results  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "9333"))
ECHO_GAIN = float(os.environ.get("POINTE_ECHO_GAIN", "0"))  # > 0: the page's speaker leaks into its microphone


async def evaluate(socket, expression: str, ids=iter(range(1, 10**6))):
    n = next(ids)
    await socket.send(json.dumps({"id": n, "method": "Runtime.evaluate",
                                  "params": {"expression": expression, "awaitPromise": True, "returnByValue": True}}))
    while True:
        reply = json.loads(await socket.recv())
        if reply.get("id") == n:
            return reply.get("result", {}).get("result", {}).get("value")


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    question = await synth("What time zone is Tel Aviv in?")
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    url = f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"
    chrome = subprocess.Popen([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
                               "--no-first-run", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import urllib.request
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                page = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                time.sleep(0.5)
        async with connect(page["webSocketDebuggerUrl"], max_size=None) as socket:
            await asyncio.sleep(3)
            # The page's microphone: the recorded question, looped, handed to the page's own getUserMedia call.
            import base64
            pcm = base64.b64encode(np.concatenate([np.zeros(RATE * 6, np.int16), question, np.zeros(RATE * 7, np.int16)]).tobytes()).decode()
            await evaluate(socket, f"""(() => {{
                const bytes = Uint8Array.from(atob('{pcm}'), c => c.charCodeAt(0)), pcm = new Int16Array(bytes.buffer);
                navigator.mediaDevices.getUserMedia = async () => {{
                  const ctx = new AudioContext({{sampleRate: {RATE}}}), buf = ctx.createBuffer(1, pcm.length, {RATE});
                  buf.getChannelData(0).set(Float32Array.from(pcm, v => v / 32768));
                  const src = ctx.createBufferSource(); src.buffer = buf; src.loop = true;
                  const dest = ctx.createMediaStreamDestination(); src.connect(dest); src.start(); await ctx.resume();
                  window.__mic = {{ctx, dest}};
                  return dest.stream;
                }};
            }})()""")
            await evaluate(socket, "startCall()")
            if ECHO_GAIN:  # the page's own playback, into the microphone it sends: speakers, no headphones
                await evaluate(socket, f"""(() => {{
                    const tap = call.ctx.createMediaStreamDestination(); call.player.connect(tap);
                    const leak = __mic.ctx.createMediaStreamSource(tap.stream), gain = __mic.ctx.createGain();
                    gain.gain.value = {ECHO_GAIN}; leak.connect(gain).connect(__mic.dest);
                }})()""")
            await asyncio.sleep(4)

            state = await evaluate(socket, "call.state")
            check("the page's own call connects", state == "live", state=state,
                  connected=bool(log_lines("page connected")))
            deadline = time.time() + 40
            live_seen = []
            while time.time() < deadline and not log_lines(r"user said: .*(Tel Aviv|time zone)"):
                live = await evaluate(socket, "document.getElementById('caption').hidden ? '' : document.getElementById('caption-text').textContent")
                if live:
                    live_seen.append(live)
                await asyncio.sleep(0.3)
            check("the page shows the user's words while they speak", bool(live_seen), seen=live_seen[-2:])
            once, waited = None, time.time()
            while time.time() - waited < 6 and not (once and once["bubbles"]):
                await asyncio.sleep(0.5)
                once = await evaluate(socket, """(() => ({caption: !document.getElementById('caption').hidden,
                    bubbles: [...document.querySelectorAll('#talk li.you')].filter(x => /Tel Aviv/.test(x.textContent)).length}))()""")
            if once:
                once["after_s"] = round(time.time() - waited, 1)
            check("once final, the caption clears and the words show once, as a bubble",
                  once and not once["caption"] and once["bubbles"] == 1, shown=once)
            heard = log_lines(r"user said: ")
            check("the daemon hears the page's microphone", any("Tel Aviv" in h or "time zone" in h for h in heard),
                  heard=[h[-80:] for h in heard][-2:], sent=await evaluate(socket, "call.sent || 0"))
            deadline = time.time() + 30  # a slow model step must not read as a broken page
            while time.time() < deadline and not any("UTC" in s or "Israel" in s for s in log_lines(r"speak: ")):
                await asyncio.sleep(1)
            await asyncio.sleep(4)
            received = await evaluate(socket, "call.received || 0")
            spoke = log_lines(r"speak: ")
            check("the bot's answer reaches the page", received > 50 and any("UTC" in s or "Israel" in s for s in spoke),
                  chunks=received, said=[s[-90:] for s in spoke][-1:])
            # Typing instead of talking: the same voice answers it.
            n_spoke = len(log_lines(r"speak: "))
            await evaluate(socket, """(() => { const box = document.getElementById('typed'); box.value = 'What is two plus two?';
                                         document.getElementById('compose').requestSubmit(); })()""")
            deadline = time.time() + 30
            while time.time() < deadline and len(log_lines(r"speak: ")) <= n_spoke:
                await asyncio.sleep(1)
            typed_answer = log_lines(r"speak: ")[n_spoke:]
            check("typing in the page gets an answer", any(w in " ".join(typed_answer).lower() for w in ("four", " 4")),
                  said=[s[-80:] for s in typed_answer][-1:], typed=bool(log_lines(r"user said: 'What is two plus two\?'")))
            # Fixing what it heard: click your bubble, edit, Enter.
            await asyncio.sleep(2)
            await evaluate(socket, """(() => { const li = [...document.querySelectorAll('#talk li.you.fixable')]
                                         .find(x => x.dataset.text.includes('Tel Aviv'));
                                       li.click(); const box = li.querySelector('textarea');
                                       box.value = 'What time zone is Jerusalem in?';
                                       box.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); })()""")
            await asyncio.sleep(3)
            fixed = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"{DAEMON}/voice/status", headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})).read())["talk"]
            shown = await evaluate(socket, "[...document.querySelectorAll('#talk li.you')].map(x => x.textContent).join(' | ')")
            check("fixing a transcript in the page corrects the turn and shows it",
                  any(t["corrected"] and "Jerusalem" in t["text"] for t in fixed) and "Jerusalem" in shown,
                  corrected=bool(log_lines("user corrected")), shown=shown[-160:])
            # Brain dump: the voice stays quiet; Done with nothing said goes back to the conversation with no model turn.
            # The looped question must not land in the dump as a thought: the microphone goes quiet first.
            await evaluate(socket, "window.__mic.ctx.suspend(); true")
            await asyncio.sleep(8)  # words cut off by that are still finalized (2.5 s), settled and answered: all before the dump
            await evaluate(socket, "document.getElementById('listen').click()")
            await asyncio.sleep(1.5)
            opened = await evaluate(socket, "!document.getElementById('dump').hidden")
            await evaluate(socket, "document.getElementById('dump-done').click()")
            await asyncio.sleep(1.5)
            closed = await evaluate(socket, "document.getElementById('dump').hidden")
            check("Brain dump opens and Done with nothing said closes it", opened and closed and bool(log_lines("brain dump started"))
                  and bool(log_lines("brain dump ended with nothing said")), opened=opened, closed=closed)
            await evaluate(socket, "endCall()")
            await asyncio.sleep(3)
            status = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"{DAEMON}/voice/status", headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})).read())
            check("Hang up ends the call", not status["connected"] and bool(log_lines("page connected")))
    finally:
        chrome.terminate()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page call)")


asyncio.run(main())
