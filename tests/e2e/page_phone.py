"""Settings → Phone in the page, in a real (headless) Chrome against a real daemon, with no terminal step.

An upgrade: `pointe pair` set up old.localtest.me before, and the iPhone holds the shared key. The page lists it as one
phone, "Paired phone", until the app names itself; its key keeps working. Connect another phone lists the routes this Mac has, in plain words, one recommended;
a typed name is checked. Show the code: a QR made by the Mac, the link as text, a countdown. Meanwhile the status and
the log carry no code, and neither the phone key nor a page opened over the TLS listener reaches the owner routes. The
app's side (the TLS listener started now, from the page's choice, without a daemon restart): the certificate matches
the link's fingerprint, the code buys the phone key once. The page turns to "Connected: <phone>" by itself; the phone
shows online. A second phone gets its own key. Unpair one, two clicks: its key is refused at once and the others
keep working. Unpair all: every key, the old shared one included, is refused.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-pc1 CLAUDE_VOICE_DAEMON_PORT=7970 CLAUDE_VOICE_TLS_PORT=7570 POINTE_CHROME_PORT=7973 \
     POINTE_SHOTS=/tmp/pc-shots uv run python -u -I tests/e2e/page_phone.py
"""

import asyncio
import hashlib
import http.client
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
sys.path[0:0] = [str(Path(__file__).resolve().parents[2] / "pointe"), str(Path(__file__).resolve().parents[2])]
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, LOG, ROOT, STATE, fresh_state, stop_daemon  # noqa: E402
from scenarios import check as _check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7973"))
TLS_PORT = int(os.environ["CLAUDE_VOICE_TLS_PORT"])
NAME = "pointe.localtest.me"  # public DNS for 127.0.0.1: the "host" route, served on loopback as for a connector
OLD = "old.localtest.me"  # the route `pointe pair host` set up before the upgrade


def check(name: str, got, want) -> None:
    _check(name, got == want, got=got, want=want)


def tls(method: str, path: str, body: dict | None = None, headers: dict | None = None, host: str = NAME) -> tuple[int, str, str, dict]:
    """As the app: TLS to the listener under its name; (status, text, the served certificate's SHA-256, cookies)."""
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE  # pinned by fingerprint below, as the app does
    conn = http.client.HTTPSConnection(host, TLS_PORT, context=context, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"content-type": "application/json", **(headers or {})})
    response = conn.getresponse()
    der = conn.sock.getpeercert(binary_form=True)
    text = response.read().decode(errors="replace")
    cookies = dict(c.split(";")[0].split("=", 1) for c in response.headers.get_all("set-cookie") or [])
    conn.close()
    return response.status, text, hashlib.sha256(der).hexdigest(), cookies


def local_status(path: str, headers: dict) -> int:
    request = urllib.request.Request(f"{DAEMON}{path}", headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code


async def open_page(socket) -> Page:
    page = Page(socket)
    await page.cdp("Page.enable")
    await page.cdp("Page.navigate", {"url": f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"})
    await page.until("document.getElementById('settingsbtn') && window.phoneConnect", 15)
    await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                  "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
    return page


async def show_section(page: Page) -> None:
    await page.js("openSettings()")
    await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
    await page.js("document.getElementById('phone').scrollIntoView({block: 'start'})")


def routes_shown(page: Page):
    return page.js("[...document.querySelectorAll('#ph-routes label')].map(l => ({title: l.querySelector('.pl').textContent, "
                   "words: l.querySelector('.pw').textContent, problem: l.querySelector('.pp')?.textContent || '', "
                   "on: l.querySelector('input').checked, off: l.querySelector('input').disabled}))")


def key_works(key: str, host: str = NAME) -> int:
    return tls("GET", "/voice/status", headers={"authorization": f"Bearer {key}"}, host=host)[0]


async def unpair(page: Page, name: str) -> None:
    """Click a phone's Unpair twice, as the owner does."""
    row = f"[...document.querySelectorAll('#ph-list li')].find(li => li.querySelector('.mn')?.textContent === {json.dumps(name)})"
    await page.js(f"{row}.querySelector('button').click()")
    await asyncio.sleep(0.3)
    check(f"Unpair {name} asks once more", await page.js(f"{row}.querySelector('button').textContent"), f"Unpair {name}?")
    await page.js(f"{row}.querySelector('button').click()")
    await page.until(f"!{row}", 5)


async def pair_one(page: Page, device: str, device_id: str) -> tuple[str, dict]:
    """Connect a phone through the page with the route already picked; (its key, the link's fields)."""
    await page.js("phoneConnect()")
    await page.until("document.querySelectorAll('#ph-routes label input:checked').length", 20)
    await page.js("phoneCode()")
    await page.until("!document.getElementById('ph-qr').hidden && document.querySelector('#ph-svg svg')", 15)
    link = await page.js("document.getElementById('ph-link').textContent")
    query = {k: v[0] for k, v in parse_qs(urlparse(link).query).items()}
    got = tls("POST", "/voice/phone/pair", {"code": query["code"], "device": device, "id": device_id})
    await page.until(f"document.getElementById('ph-done').textContent === 'Connected: {device}'", 5)
    return json.loads(got[1])["key"], query


async def run(page: Page, legacy: str) -> None:
    await show_section(page)
    await page.until("document.querySelector('#ph-list .mn')", 5)
    check("after the upgrade the phone paired before is listed, not signed out", await page.js(
        "[document.querySelector('#ph-list .mn').textContent, document.querySelector('#ph-list .mmeta').textContent, "
        "document.getElementById('ph-connect').textContent]"),
        ["Paired phone", "not seen yet · paired before this Mac gave each phone its own key", "Connect another phone"])
    await page.shot("phone-1-legacy")
    check("its shared key still works", tls("GET", "/voice/status", headers={"authorization": f"Bearer {legacy}",
                                                                             "x-pointe-device": "Old%20iPhone"}, host=OLD)[0], 200)
    await page.until("document.querySelector('#ph-list .mn').textContent === 'Old iPhone'", 5)
    check("and it takes the name the app reports, online", await page.js("document.querySelector('#ph-list .mmeta').textContent"
                                                                         ".startsWith('online now')"), True)
    await page.shot("phone-2-legacy-named")

    await page.js("phoneConnect()")
    await page.until("document.querySelectorAll('#ph-routes label').length >= 2", 20)
    shown = await routes_shown(page)
    titles = [r["title"] for r in shown]
    _check("the Mac's routes are listed in plain words (Tailscale and the Wi-Fi at least)",
           any(t.startswith("Tailscale") for t in titles) and any(t.startswith("Same Wi-Fi") for t in titles)
           and all(r["words"] for r in shown), shown=shown)
    old_route = next((r for r in shown if r["title"].startswith(OLD)), {})
    _check("the route set up before is offered, recommended and picked", old_route.get("on")
           and "Recommended" in old_route.get("title", "") and "in use" in old_route.get("title", ""), route=old_route)
    await page.shot("phone-3-routes")

    await page.js(f"document.getElementById('ph-host').value = {json.dumps(NAME)}; "
                  "document.getElementById('ph-hostform').requestSubmit()")
    await page.until(f"[...document.querySelectorAll('#ph-routes label .pl')].some(x => x.textContent.startsWith({json.dumps(NAME)}))", 10)
    typed = next(r for r in await routes_shown(page) if r["title"].startswith(NAME))
    _check("a typed name is checked and said plainly: this one points at the Mac itself", typed["on"] and not typed["off"]
           and "this Mac itself" in typed["problem"] and "127.0.0.1" in typed["words"], typed=typed)
    check("switching warns that what is paired must pair again", await page.js("document.getElementById('ph-cert').textContent"),
          "Choosing this makes a new certificate for this Mac: a phone or machine paired now must connect again.")
    await page.shot("phone-4-typed")

    await page.js("phoneCode()")
    await page.until("!document.getElementById('ph-qr').hidden && document.querySelector('#ph-svg svg')", 15)
    link = await page.js("document.getElementById('ph-link').textContent")
    query = {k: v[0] for k, v in parse_qs(urlparse(link).query).items()}
    check("the QR's link: version 2, the typed name, this TLS port, a one-time code, no key",
          (link.startswith("pointe://pair?"), query.get("v"), query.get("host"), query.get("port"), "key" in query,
           len(query.get("code", "")) == 9), (True, "2", NAME, str(TLS_PORT), False, True))
    left = await page.js("document.getElementById('ph-left').textContent")
    _check("a countdown shows", left.startswith("Waiting for your phone · expires in 4:") or "5:00" in left, left=left)
    _check("the QR is an SVG made on the Mac, with nothing loaded from elsewhere", await page.js(
        "(() => { const s = document.querySelector('#ph-svg svg'); return !!s.querySelector('path') && !s.querySelector('image') "
        "&& !performance.getEntriesByType('resource').some(e => !e.name.startsWith(location.origin)); })()"), link=link)
    await page.shot("phone-5-qr")

    code = query["code"]
    status_text = json.dumps(call("/voice/status"))
    check("the status carries no code, link or key while the QR shows",
          (code in status_text, "pointe://pair" in status_text, legacy in status_text), (False, False, False))
    log = LOG.read_text() if LOG.exists() else ""
    check("the log carries no code and no link", (code in log, code.replace("-", "") in log, link in log), (False, False, False))
    invite_state = await page.js("fetch('/voice/phone/invite').then(r => r.text())")
    check("the page's own poll of the code carries no code either", code in invite_state, False)

    key_header = {"authorization": f"Bearer {legacy}"}
    refused = [tls("GET", "/voice/phone/routes", headers=key_header)[0], tls("POST", "/voice/phone/invite", {"kind": "host"}, key_header)[0],
               tls("POST", "/voice/phone/unpair", {"all": True}, key_header)[0],
               local_status("/voice/phone/routes", key_header), local_status("/voice/phone/invite", key_header)]
    check("a phone key reaches none of the owner routes, over the listener or here", refused, [403] * 5)
    token = (STATE / "remote_token").read_text().strip()
    paired_browser = tls("GET", f"/voice?pair={token}")
    cookie = "; ".join(f"{k}={v}" for k, v in paired_browser[3].items())
    over_tls = [tls("GET", "/voice/status", headers={"cookie": cookie})[0],
                tls("GET", "/voice/phone/routes", headers={"cookie": cookie})[0],
                tls("POST", "/voice/phone/invite", {"kind": "host", "host": NAME}, {"cookie": cookie})[0],
                tls("GET", "/voice/phone/invite", headers={"cookie": cookie})[0],
                tls("POST", "/voice/phone/unpair", {"all": True}, {"cookie": cookie})[0]]
    check("a page opened over the TLS listener is let in, but refused every owner route", over_tls, [200, 403, 403, 403, 403])

    wrong = tls("POST", "/voice/phone/pair", {"code": "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB"})
    check("a wrong code is refused", (wrong[0], wrong[1]), (403, "wrong code"))
    got = tls("POST", "/voice/phone/pair", {"code": code, "device": "E2E iPhone", "id": "e2e-1"})
    check("the listener restarted now, from the page's choice, with the certificate the link names", got[2], query["fp"])
    phone_key = json.loads(got[1]).get("key", "")
    check("the code buys this phone its own key", (got[0], len(phone_key) >= 40, phone_key != legacy), (200, True, True))
    check("once", tls("POST", "/voice/phone/pair", {"code": code, "device": "Other"})[0], 403)

    done = await page.until("document.getElementById('ph-done').textContent", 5)
    check("the page turns to Connected by itself, and the QR is gone",
          (done, await page.js("[document.getElementById('ph-qr').hidden, document.querySelector('#ph-svg svg')]")),
          ("Connected: E2E iPhone", [True, None]))
    check("its key works over the listener", key_works(phone_key), 200)
    await page.until("[...document.querySelectorAll('#ph-list li')].some(li => li.textContent.includes('E2E iPhone') && li.textContent.includes('online now'))", 5)
    await page.shot("phone-6-connected")

    ipad_key, again = await pair_one(page, "E2E iPad", "e2e-2")
    check("connect another phone: the route set up now is reused, and the new phone gets a key of its own",
          (again["host"], again["fp"] == query["fp"], ipad_key not in (phone_key, legacy)), (NAME, True, True))
    key_works(ipad_key)
    await page.until("document.querySelectorAll('#ph-list li').length === 3 && !document.getElementById('ph-unpair').hidden", 5)
    check("three phones listed by name, each with Unpair, and Unpair all", await page.js(
        "[[...document.querySelectorAll('#ph-list .mn')].map(x => x.textContent).sort(), "
        "document.querySelectorAll('#ph-list button').length, document.getElementById('ph-unpair').textContent, "
        "document.getElementById('ph-rule').textContent.includes('signs out only that phone')]"),
        [["E2E iPad", "E2E iPhone", "Old iPhone"], 3, "Unpair all", True])
    await page.shot("phone-7-three")

    await unpair(page, "E2E iPhone")
    check("unpair one: its key is refused at once, the others keep working",
          [key_works(phone_key), key_works(ipad_key), key_works(legacy)], [403, 200, 200])
    check("and the page says which", await page.js("document.getElementById('ph-done').textContent"), "E2E iPhone unpaired.")
    await page.shot("phone-8-unpaired-one")

    await page.js("phoneUnpair('all')")
    check("Unpair all asks once more", await page.js("document.getElementById('ph-unpair').textContent"), "Unpair every phone?")
    await page.js("phoneUnpair('all')")
    await page.until("document.getElementById('ph-list').textContent === 'No phone paired yet.'", 5)
    check("Unpair all: every key, the shared one included, is refused", [key_works(ipad_key), key_works(legacy)], [403, 403])
    check("and the page says so", await page.js("document.getElementById('ph-done').textContent"),
          "Every phone unpaired. Each must connect again.")
    await page.shot("phone-9-unpaired-all")
    check("no page errors", await page.js("window.__errors"), [])


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    for name in ("remote.json", "remote_token", "phone_key", "phones.json"):
        (STATE / name).unlink(missing_ok=True)
    shutil.rmtree(STATE / "tls", ignore_errors=True)
    import pair
    from phone import phone_key

    pair.STATE = STATE
    pair.setup(OLD, "127.0.0.1")  # before the upgrade: `pointe pair host`, and the iPhone scanned the old link
    legacy = phone_key(STATE)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,1000", "--no-first-run", "about:blank"],
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
            await run(await open_page(socket), legacy)
    finally:
        chrome.terminate()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page phone)")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    import urllib.error
    asyncio.run(main())
