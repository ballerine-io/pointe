"""The page (ui.html) as a document: what the e2e suites assume about it, checked without a daemon.

The render checks run the page in a headless Chrome from a file:// URL with a stubbed /voice/status, over the same
DevTools protocol the e2e rig uses; they are skipped where that Chrome is not installed (CI on Linux).
"""

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "ui.html").read_text()
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Every id the page tests (tests/e2e/page_*.py) and the iPhone parity tests look up. Renaming one breaks them silently
# until the e2e runs; here it fails at once.
IDS = """settingsbtn settingssheet set-h pref-mode pref-lookups pref-lang pref-consent pref-consent-again pref-local pref-mic pref-key
pref-conflicts pref-conflicts-spoken pref-desktop pref-desktop-note pref-watch pref-showphone setok seterr brf-sched brf-time brf-days
brf-deflen brf-connect brf-skipempty dict-open voicelock vl-h vl-intro vl-problem vl-enrol vl-line vl-bar vl-fill vl-pct vl-why vl-model
vl-cancel vl-devices vl-needcall vl-actions vl-enrolbtn vl-deleteall vl-confirm vl-levels vl-levelhelp vl-err machines mach-h mach-list
mach-invite mach-code mach-link mach-left mach-invitebtn mach-cancel mach-err phone ph-h ph-list ph-pick ph-routes ph-hostform ph-host
ph-check ph-advice ph-cert ph-show ph-qr ph-svg ph-link ph-left ph-cancel ph-done ph-actions ph-connect ph-unpair ph-rule ph-err
mic hangup listen listen-label meetbtn meet-label briefbtn drivebtn chlbtn chl-label whisperbtn whisper-label typebtn sessbtn keyhint
state sub problem vlproblem vlignored polish talk newpill compose typed typed-send caption caption-text attention conflicts briefalert
whispercard drivebar drive-line drive-stop brainstorm mono-text back bs-challenge challenge chl-h chl-plan chl-items chl-end chl-close
chl-hint chl-err meetbar meetwhat meetsub speakers mm-listening mm-participating meetredial meetend notes endbar closenotes hand handline
handspeak notelist meetsay meetsheet meet-h meetstep1 meetstep2 meetbrief meetsessions meetlookups meeterr1 meetvendors meetconsent
meeterr2 meetback meetstart endsheet end-h endbody endsession endsend endok enderr enddiscard briefsheet brf-h brf-since brf-length brf-why
brf-go brf-skip brf-continue brf-stop brf-state brf-err brf-list ignoredsheet ign-h ignoredlist ctx ctxpanel ctx-total ctx-rows cf-talk
cf-all ctx-msgs ctxmodal cm-kind cm-text side list mchips renameproblem recent modehelp m-orchestrator m-session show show-title
show-when show-summary show-pin show-fold show-arts show-tabs show-where show-body show-earlier show-earlier-list show-say""".split()


def test_every_id_the_suites_use_is_in_the_page():
    present = set(re.findall(r'\bid="([^"]+)"', PAGE))
    missing = [i for i in IDS if i not in present]
    assert missing == []


def test_ids_are_unique():
    ids = re.findall(r'\bid="([^"]+)"', PAGE)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert dupes == []


def test_hidden_attribute_always_hides():
    """`el.hidden = true` must beat an id rule with its own display (the enrol panel showed with `hidden` set)."""
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", PAGE)
    for i in ("vl-enrol", "vl-actions", "voicelock", "mach-invite", "ph-pick", "ph-qr", "pref-consent", "drivebar", "brainstorm", "challenge"):
        assert f'id="{i}"' in PAGE


def test_microphone_mode_is_in_the_main_page_and_in_settings():
    """Push to talk is reachable without opening Settings; both controls name the same preference."""
    assert 'id="pref-mic"' in PAGE
    assert 'id="micmode-ptt"' in PAGE and 'id="micmode-always"' in PAGE
    assert "setMicMode(" in PAGE
    assert 'id="keyhint"' in PAGE


def test_user_text_elements_keep_their_direction():
    for i in ("typed", "meetbrief", "caption-text", "chl-plan", "problem"):
        assert re.search(rf'id="{i}"[^>]*dir="auto"|dir="auto"[^>]*id="{i}"', PAGE), i


# ---------- rendered, in a headless Chrome ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


STATUS = {"connected": False, "mode": "orchestrator", "active": "shop", "sessions": [], "attention": [], "recent": [], "talk": [],
          "machines": [{"id": "hub", "name": "studio", "here": True, "os": "macos", "online": True, "sessions": 0, "need": 0}],
          "ptt": {"mode": "always", "open": False, "sent_bytes": 0, "room_heard": False},
          "voice_lock": {"level": "off", "enrolled": False, "devices": [], "enrolling": None, "lines": [], "model": "ready", "problem": None,
                         "ignored": {"count": 0, "last_at": None, "recent": []}, "speaker": None, "unsure_streak": 0}}

STUB = """
  window.__status = %s;
  window.fetch = async (url, opts) => new Response(JSON.stringify(
    String(url).startsWith('/voice/status') ? window.__status
    : String(url).startsWith('/voice/briefings') ? {schedule: {time: '', days: [0,1,2,3,4,5,6], length: 'normal', speak_on_connect: true, skip_empty: false}, briefings: []}
    : String(url).startsWith('/voice/prefs') ? {microphone: 'always'} : {ok: true}));
"""


async def _render(checks: str, sizes: tuple[int, ...] = ()):
    """Evaluate `checks` in the page; with `sizes`, evaluate it once per viewport width and return {width: value}."""
    from websockets.asyncio.client import connect

    html = PAGE.replace("{{BALLERINE}}", "").replace("{{LOGO}}", "").replace("{{DICTIONARY}}", (ROOT / "ui_dictionary.html").read_text()) \
        .replace("{{WHISPER}}", (ROOT / "ui_whisper.html").read_text())
    work = Path(tempfile.mkdtemp(prefix="pointe-page-test-"))
    (work / "page.html").write_text(html)
    port = _free_port()
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={work / 'profile'}",
                               "--no-first-run", "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import urllib.request
        target = None
        for _ in range(60):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read())
                target = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                await asyncio.sleep(0.25)
        assert target, "Chrome did not open a page"
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
            n = 0

            async def cdp(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == n:
                        return r.get("result", {})

            await cdp("Page.enable")
            await cdp("Page.addScriptToEvaluateOnNewDocument", {"source": STUB % json.dumps(STATUS)})
            await cdp("Page.navigate", {"url": (work / "page.html").as_uri()})
            for _ in range(40):
                r = await cdp("Runtime.evaluate", {"expression": "!!window.status && !!window.status.voice_lock", "returnByValue": True})
                if r.get("result", {}).get("value"):
                    break
                await asyncio.sleep(0.25)
            if not sizes:
                r = await cdp("Runtime.evaluate", {"expression": checks, "awaitPromise": True, "returnByValue": True})
                assert "exceptionDetails" not in r, r["exceptionDetails"]
                return r["result"]["value"]
            out = {}
            for w in sizes:
                await cdp("Emulation.setDeviceMetricsOverride", {"width": w, "height": 844, "deviceScaleFactor": 1, "mobile": w < 500})
                await asyncio.sleep(0.4)
                r = await cdp("Runtime.evaluate", {"expression": checks, "awaitPromise": True, "returnByValue": True})
                assert "exceptionDetails" not in r, r["exceptionDetails"]
                out[w] = r["result"]["value"]
            return out
    finally:
        chrome.terminate()
        shutil.rmtree(work, ignore_errors=True)


needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")


@needs_chrome
def test_enrol_panel_is_off_screen_until_enrolment_starts():
    got = asyncio.run(_render("""(async () => {
        const vis = id => getComputedStyle(document.getElementById(id)).display !== 'none';
        openSettings(); await new Promise(r => setTimeout(r, 400));
        const idle = {panel: vis('vl-enrol'), actions: vis('vl-actions'), button: document.getElementById('vl-enrolbtn').disabled,
                      need: document.getElementById('vl-needcall').textContent, section: vis('voicelock')};
        window.__status = {...window.__status, connected: true, voice_lock: {...window.__status.voice_lock,
          enrolling: {device: 'Mic', progress: 0.5, line: 0, text: 'Read me', seconds: 4, segments: 2, rejected: 0, last_reason: null}}};
        await refresh();
        const enrolling = {panel: vis('vl-enrol'), actions: vis('vl-actions'), line: document.getElementById('vl-line').textContent,
                           pct: document.getElementById('vl-pct').textContent};
        return {idle, enrolling};
    })()"""))
    assert got["idle"] == {"panel": False, "actions": True, "button": True, "need": "Connect a call first: enrolment listens on the call.", "section": True}
    assert got["enrolling"] == {"panel": True, "actions": False, "line": "Read me", "pct": "50%"}


@needs_chrome
def test_settings_reopens_at_the_top_with_the_first_section_marked():
    """A jump to Phone, close, reopen: the panel is back at the top (a scrollTop set while display:none is lost)."""
    got = asyncio.run(_render("""(async () => {
        const marked = () => document.querySelector('#set-nav button.on').dataset.section;
        openSettings(); await new Promise(r => setTimeout(r, 400));
        settingsJump('phone'); await new Promise(r => setTimeout(r, 900));
        const jumped = {top: document.getElementById('set-panel').scrollTop, marked: marked()};
        closeSheet('settingssheet');
        openSettings(); await new Promise(r => setTimeout(r, 400));
        return {jumped, reopened: {top: document.getElementById('set-panel').scrollTop, marked: marked()}};
    })()"""))
    assert got["jumped"]["top"] > 0 and got["jumped"]["marked"] == "phone"
    assert got["reopened"] == {"top": 0, "marked": "voicelock"}


@needs_chrome
def test_mic_mode_toggle_follows_the_daemon_and_sets_the_preference():
    got = asyncio.run(_render("""(async () => {
        const on = id => document.getElementById(id).getAttribute('aria-checked');
        const before = [on('micmode-always'), on('micmode-ptt'), document.getElementById('keyhint').textContent];
        window.__posts = []; const real = window.fetch;
        window.fetch = async (u, o) => { if (o && o.method === 'POST') window.__posts.push([String(u), JSON.parse(o.body)]); return real(u, o); };
        window.__status = {...window.__status, connected: true, ptt: {...window.__status.ptt, mode: 'ptt'}};
        call.state = 'live'; call.heard = Date.now();
        await refresh();
        const after = [on('micmode-always'), on('micmode-ptt'), document.getElementById('keyhint').textContent,
                       document.getElementById('miclabel').textContent, document.body.dataset.state];
        await setMicMode('always');
        return {before, after, posts: window.__posts, prefmic: document.getElementById('pref-mic').value};
    })()"""))
    assert got["before"][:2] == ["true", "false"]
    assert got["after"][:2] == ["false", "true"]
    assert got["after"][2].startswith("Hold ") and "Caps Lock" in got["after"][2]
    assert got["after"][3] == "Hold to talk" and got["after"][4] == "ptt"
    assert ["/voice/prefs", {"microphone": "always"}] in got["posts"]
    assert got["prefmic"] == "always"


@needs_chrome
def test_dock_keeps_the_mic_centred_and_fits_at_every_width():
    got = asyncio.run(_render("""(() => {
        const mic = document.getElementById('mic').getBoundingClientRect(), dock = document.querySelector('.dock').getBoundingClientRect();
        const main = document.querySelector('main').getBoundingClientRect();
        const ids = [...document.querySelectorAll('.dock button')].map(b => b.id).filter(Boolean);
        return {centred: Math.abs((mic.left + mic.right) / 2 - (main.left + main.right) / 2) < 3,
                fits: dock.right <= main.right + 1 && dock.left >= main.left - 1 && document.documentElement.scrollWidth <= innerWidth + 1,
                more: !document.getElementById('morebtn').hidden, inMore: [...document.getElementById('more-list').children].map(b => b.id),
                inDock: ids, hangupHidden: getComputedStyle(document.getElementById('hangup')).visibility === 'hidden',
                labelsShown: getComputedStyle(document.querySelector('#typebtn .lb')).position !== 'absolute'};
    })()""", sizes=(1440, 1280, 1024, 760, 390)))
    for w, r in got.items():
        assert r["centred"] and r["fits"] and r["hangupHidden"], (w, r)
    assert got[1440]["inMore"] == [] and not got[1440]["more"] and got[1440]["labelsShown"]
    assert not got[1024]["labelsShown"]
    for w in (760, 390):
        assert got[w]["more"] and got[w]["inMore"] == ["listen", "meetbtn", "briefbtn", "drivebtn", "chlbtn", "whisperbtn"], (w, got[w])
        assert "sessbtn" in got[w]["inDock"] and "typebtn" in got[w]["inDock"] and "mic" in got[w]["inDock"]
    wide = [i for i in got[1440]["inDock"] if i]
    assert wide.index("listen") < wide.index("mic") < wide.index("chlbtn") < wide.index("sessbtn")
