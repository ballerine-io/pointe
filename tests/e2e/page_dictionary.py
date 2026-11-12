"""The dictionary in the page, in a real (headless) Chrome against a real daemon.

Part 1, no call (the daemon's reader writes the session's notes, as at any register): Settings → Dictionary opens the sheet; add a name; a consent word is refused with the
reason; edit a spelling; change its language; a session's names are suggested (never a consent word), Add and Ignore
work; Learn from my fixes turns learning and suggestions off and on; delete; the file is 0600; no page errors.

Part 2, with --live (Soniox, the brain and the mouth; flaky by nature, as speech is): a fake microphone says a line with an
invented name the ears mishear; you fix it in the page; "Learned: …" shows with Undo, and Undo takes it out; the fix put
back and made again teaches only the name; hang up, call again, and the name is heard right.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-voc CLAUDE_VOICE_DAEMON_PORT=7975 CLAUDE_VOICE_TLS_PORT=7575 POINTE_CHROME_PORT=7978 \
     uv run python -u -I tests/e2e/page_dictionary.py [--live]
Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import base64
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check as _check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7978"))
LINE = "Is Pellucine still on the preview environment?"  # an invented name: Soniox wrote "Pelusine" 4 of 4 (bench/vocab_bench.py)
NAME = "Pellucine"


def check(name: str, got, want) -> None:
    _check(name, got == want, got=got, want=want)


def status_of(method: str, path: str, body: dict | None = None) -> int:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                              "content-type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=10)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def entries() -> list[dict]:
    return call("/voice/dictionary")["entries"]


async def open_page(socket) -> Page:
    page = Page(socket)
    await page.cdp("Page.enable")
    await page.cdp("Page.navigate", {"url": f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"})
    await page.until("document.getElementById('settingsbtn') && window.openDictionary", 15)
    await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                  "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
    return page


async def sheet(page: Page) -> None:
    await page.js("openSettings()")
    await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
    await page.js("document.getElementById('dict-open').click()")
    await page.until("document.getElementById('dictsheet').classList.contains('open')", 5)


async def type_add(page: Page, term: str) -> None:
    await page.js(f"document.getElementById('dict-new').value = {json.dumps(term)}; "
                  "document.querySelector('#dictsheet form.addrow').requestSubmit()")
    await asyncio.sleep(0.6)


async def part_one(page: Page, session_id: str) -> None:
    await sheet(page)
    check("the sheet opens from Settings, empty, with the next-call note",
          await page.js("[document.querySelector('#dict-list .empty')?.textContent, document.getElementById('dict-applies').textContent,"
                        " !document.getElementById('dict-apply')]"),
          ["No names yet. Fix a word Pointe misheard, or add one here.", "Applies on the next call.", True])
    await type_add(page, "Quillfeather")
    check("Add puts the name in the dictionary, marked as yours",
          [(e["term"], e["source"]) for e in entries()], [("Quillfeather", "manual")])
    check("the sheet shows it with its source", await page.js(
        "[...document.querySelectorAll('#dict-list li')].map(li => li.querySelector('.term').textContent + ' · ' + li.querySelector('.src').textContent)"),
        ["Quillfeather · you added it"])
    await type_add(page, "okay")
    check("a consent word is refused, with the reason", await page.js("document.getElementById('dict-err').textContent"),
          "a yes, no or stop word: it would bias what counts as an answer")
    check("and not added", [e["term"] for e in entries()], ["Quillfeather"])
    await page.shot("dictionary-refused")

    await page.js("document.querySelector('#dict-list li .term').click()")
    await page.until("document.querySelector('#dict-list li input.term')", 3)
    await page.js("const b = document.querySelector('#dict-list li input.term'); b.value = 'QuillFeather'; "
                  "b.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")
    await asyncio.sleep(0.6)
    check("clicking a name edits its spelling", [e["term"] for e in entries()], ["QuillFeather"])
    await page.js("const s = document.querySelector('#dict-list li select'); s.value = 'both'; s.dispatchEvent(new Event('change'))")
    await asyncio.sleep(0.6)
    check("its language can be changed", [e["lang"] for e in entries()], ["both"])

    await page.js("closeSheet('dictsheet')")
    deadline = time.time() + 60  # the reader's notes on the session's synthetic transcript
    while time.time() < deadline and not {"Kestrelbay", "Zentrak"} <= {x["term"] for x in call("/voice/dictionary")["suggestions"]}:
        await asyncio.sleep(1)
    await page.js("openDictionary()")
    await page.until("document.getElementById('dictsheet').classList.contains('open')", 5)
    await page.until("document.querySelectorAll('#dict-sugg li').length", 5)
    shown = await page.js("[...document.querySelectorAll('#dict-sugg li')].map(li => li.querySelector('.term').textContent + ' · ' + "
                          "li.querySelector('.src').textContent)")
    _check("the names in a session's notes are suggested, from that session",
           {"Kestrelbay · river-lantern", "Zentrak · river-lantern"} <= set(shown or []), shown=shown)
    _check("never a consent word, a remark in brackets, or the session's own name",
           not any(re.search(r"\(|^river-lantern |^(okay|yes|sure) ", x, re.I) for x in shown or []), shown=shown)
    await page.shot("dictionary-sheet")
    await page.js("document.querySelector('#dict-sugg button[aria-label=\"Add Kestrelbay\"]').click()")
    await asyncio.sleep(0.6)
    await page.js("document.querySelector('#dict-sugg button[aria-label=\"Ignore Zentrak\"]').click()")
    await asyncio.sleep(0.6)
    got = call("/voice/dictionary")
    check("Add takes a suggestion in, marked as from a session", [(e["term"], e["source"]) for e in got["entries"]],
          [("QuillFeather", "manual"), ("Kestrelbay", "session")])
    check("Ignore keeps it from being suggested again",
          ("Zentrak" in {x["term"] for x in got["suggestions"]}, got["ignored"]), (False, ["Zentrak"]))

    await page.js("document.getElementById('dict-learn').click()")
    await asyncio.sleep(0.6)
    check("Learn from my fixes turns learning off on the Mac", call("/voice/prefs")["dictionary.learn"], False)
    await page.js("document.getElementById('dict-learn').click()")
    await asyncio.sleep(0.6)
    check("and on again", call("/voice/prefs")["dictionary.learn"], True)

    await page.js("document.querySelector('#dict-list button[aria-label=\"Delete Kestrelbay\"]').click()")
    await asyncio.sleep(0.6)
    check("Delete takes a name out", [e["term"] for e in entries()], ["QuillFeather"])
    check("the file is private (0600)", oct(stat.S_IMODE((STATE / "dictionary.json").stat().st_mode)), "0o600")
    await page.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    await asyncio.sleep(0.3)
    check("Escape closes the sheet", await page.js("document.getElementById('dictsheet').classList.contains('open')"), False)
    check("no page errors", await page.js("window.__errors"), [])


async def said_after(n: int, timeout: float) -> str | None:
    """The next final transcript of the user's after the first n."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        heard = log_lines(r"user said: ")
        if len(heard) > n:
            return re.sub(r"^.*user said: ", "", heard[n])
        await asyncio.sleep(0.5)
    return None


async def part_two(page: Page) -> None:
    pcm = await synth(LINE)
    silence = np.zeros(RATE * 6, np.int16)
    audio = base64.b64encode(np.concatenate([silence, pcm, np.zeros(RATE * 9, np.int16)]).tobytes()).decode()
    await page.js(f"""(() => {{
        const bytes = Uint8Array.from(atob('{audio}'), c => c.charCodeAt(0)), pcm = new Int16Array(bytes.buffer);
        navigator.mediaDevices.getUserMedia = async () => {{
          const ctx = new AudioContext({{sampleRate: {RATE}}}), buf = ctx.createBuffer(1, pcm.length, {RATE});
          buf.getChannelData(0).set(Float32Array.from(pcm, v => v / 32768));
          const src = ctx.createBufferSource(); src.buffer = buf; src.loop = true;
          const dest = ctx.createMediaStreamDestination(); src.connect(dest); src.start(); await ctx.resume();
          return dest.stream;
        }};
    }})()""")
    n = len(log_lines(r"user said: "))
    await page.js("startCall()")
    first = await said_after(n, 45)
    check("the line is heard", bool(first and "preview" in first.lower()), True)
    heard_first = re.sub(r"^.*user said: '?|'?$", "", first or "")
    print(f"  heard without the term: {heard_first!r}")
    _check("before learning, the ears miss the name (else the test proves nothing)", NAME.lower() not in heard_first.lower(),
           heard=heard_first)
    await asyncio.sleep(1.5)

    async def fix(text: str) -> None:
        await page.js(f"""(() => {{ const li = [...document.querySelectorAll('#talk li.you.fixable')].reverse()
                                  .find(x => /preview/i.test(x.dataset.text));
                                li.click(); const box = li.querySelector('textarea'); box.value = {json.dumps(text)};
                                box.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}})); }})()""")

    await fix(LINE)
    toast = await page.until("document.getElementById('dicttoast').classList.contains('on') && document.getElementById('dicttoast-text').textContent", 8)
    check("fixing the transcript shows the toast", toast, f"Learned: {NAME}")
    check("the name is learned, marked as your fix", [(e["term"], e["source"]) for e in entries()], [(NAME, "correction")])
    await page.shot("dictionary-toast")
    await page.js("document.getElementById('dicttoast-undo').click()")
    await asyncio.sleep(1.0)
    check("Undo takes it out and closes the toast",
          ([e["term"] for e in entries()], await page.js("document.getElementById('dicttoast').classList.contains('on')")), ([], False))

    await fix(heard_first)
    await asyncio.sleep(1.5)
    await fix(LINE)
    await page.until("document.getElementById('dicttoast').classList.contains('on')", 8)
    check("put back and fixed again, only the name is learned", [e["term"] for e in entries()], [NAME])

    await page.js("endCall()")
    await asyncio.sleep(4)
    n = len(log_lines(r"user said: "))
    await page.js("startCall()")
    again = await said_after(n, 45)
    print(f"  heard on the next call: {again!r}")
    _check("on the next call the name is heard right", bool(again and NAME in again), heard=again)
    await page.js("endCall()")
    check("no page errors in the call", await page.js("window.__errors"), [])


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    live = "--live" in sys.argv
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    for name in ("dictionary.json", "dictionary.json.bad", "prefs.json"):
        (STATE / name).unlink(missing_ok=True)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-dictionary-e2e-"))
    (work / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "message": {"role": "user", "content": "Ask Kestrelbay to rebase on dev, then send the build logs to Zentrak."}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text":
            "Kestrelbay rebased on dev cleanly. I sent the build logs to Zentrak; they will look at the flaky test."}]}}]) + "\n")
    session_id = f"page-dictionary-{os.getpid()}"
    call("/voice/register", {"id": session_id, "cwd": str(work), "pid": os.getpid(), "name": "river-lantern", "name_given": True,
                             "transcript": str(work / "transcript.jsonl")})
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
                               "--window-size=1400,900", "--no-first-run", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as socket:
            page = await open_page(socket)
            await part_one(page, session_id)
            if live:
                call("/voice/disconnect", {"name": "river-lantern"})  # no session to send to: the line only has to be heard
                for e in entries():
                    status_of("DELETE", f"/voice/dictionary?term={urllib.parse.quote(e['term'])}")
                await part_two(page)
    finally:
        chrome.terminate()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page dictionary{', live' if live else ''})")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    import urllib.parse
    asyncio.run(main())
