"""Sessions by voice alone, the demo path, live: "start a new Codex session in shop" (read back, then yes), "rename it to
shop-tests", "switch to billing", "close docs", "close all except billing and shop" (read back, then yes), and "go back
to orchestrator mode". Each step must do exactly what was said, with its read-back, and show on the page (headless
Chrome) at once.

Real Claude Code sessions (billing, docs, shop) in throwaway folders under /tmp, and a real Codex thread on the user's
Codex daemon, started in the throwaway shop folder and archived at the end. The user's words are synthesized speech on
the test's own call (never a microphone).

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-demo-vc CLAUDE_VOICE_DAEMON_PORT=7971 CLAUDE_VOICE_TLS_PORT=7571 \
     POINTE_CHROME_PORT=7974 uv run python -u -I tests/e2e/demo_voice_control.py [runs]
About five minutes a run. Calls paid APIs (the brain, the checker, Soniox, the mouth, ElevenLabs, Gemini).
"""

import asyncio
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from demo_rig import (greeted, ROWS, PageWindow, cleanup, heard_reply, names, owner_says, plain, start_daemon,  # noqa: E402
                      start_sessions, status, stop_daemon, stop_sessions, until, workspace)
from rig import Browser  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7974"))
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-demo-vc-"))
FOLDERS = ["billing", "docs", "shop"]


def codex_sessions() -> list[dict]:
    return [s for s in status().get("sessions") or [] if s["harness"] == "codex"]


def codex_ids() -> list[str]:
    """From this run's own state file: the status names sessions, never their ids."""
    import json

    from rig import STATE

    data = json.loads((STATE / "sessions.json").read_text())
    return [s["id"] for s in data.get("sessions", []) if s.get("harness") == "codex"]


async def archive(thread_ids: list[str]) -> None:
    """The Codex threads this run started: archived, so the user's Codex keeps no test thread."""
    from harnesses.codex import Connection

    link = Connection()
    try:
        await link.ensure()
        for tid in thread_ids:
            try:
                await link.request("thread/archive", {"threadId": tid}, timeout=10)
            except Exception:
                pass
    finally:
        await link.close()


async def one_run(n: int) -> None:
    def step(name: str, ok: bool, **info) -> None:
        check(f"[run {n}] {name}", ok, **info)

    start_daemon()
    root = workspace("demo-vc", FOLDERS)
    sessions = start_sessions(root, FOLDERS)
    browser, window = Browser(echo_gain=float(os.environ.get("POINTE_ECHO_GAIN", "0"))), PageWindow(DEBUG_PORT, SHOTS / f"run{n}")
    started: list[str] = []
    try:
        page = await window.open()
        await browser.connect()
        await until(lambda: status().get("connected"), 20)
        await greeted(browser)
        rows = await page.until(f"{ROWS} === 'billing,docs,shop' && {ROWS}", 10)
        step("B0 the page lists the three sessions", bool(rows), rows=rows)

        t = await owner_says(browser, "Start a new Codex session in shop.")
        readback = await heard_reply(browser, t, timeout=30)
        pending = await until(lambda: status().get("start_pending"), 5)
        card = await page.until("document.getElementById('startask').textContent", 5)
        step("B1 “start a new Codex session in shop” is read back, nothing starts yet, and the page shows the ask",
             "codex" in plain(readback) and "shop" in plain(readback) and bool(pending) and not codex_sessions() and bool(card),
             said=readback, pending=pending, card=card)
        await window.shot("b1-readback")
        t = await owner_says(browser, "Yes.")
        joined = await until(lambda: codex_sessions(), 90, 1)
        new = joined[0]["name"] if joined else ""
        started = codex_ids()
        shown = await page.until(f"{ROWS}.split(',').includes({new!r})", 8) if new else False
        said = await heard_reply(browser, t, timeout=20)
        step("B1 on yes the Codex session starts, joins, and shows on the page", bool(joined) and bool(shown),
             session=new, said=said)
        await window.shot("b1-joined")

        before = names() - {new}
        t = await owner_says(browser, "Rename it to shop-tests.")
        renamed = await until(lambda: any(s["name"] == "shop-tests" for s in codex_sessions()), 30)
        said = await heard_reply(browser, t, timeout=20)
        shown = await page.until(f"{ROWS}.split(',').includes('shop-tests')", 8)
        step("B2 “rename it to shop-tests” renames the new Codex session, no other, and the page shows it",
             bool(renamed) and before <= names() and bool(shown), names=sorted(names()), said=said)

        t = await owner_says(browser, "Switch to billing.")
        active = await until(lambda: (status().get("active") or "").split("/")[0] == "billing", 20)
        said = await heard_reply(browser, t, timeout=20)
        shown = await page.until("document.getElementById('list').textContent && "
                                 "[...document.querySelectorAll('#list .s.on .nm')].map(x => x.textContent.split('/')[0]).join(',')", 8)
        focused = await page.until("document.getElementById('m-session').classList.contains('on')", 5)
        step("B3 “switch to billing” focuses on billing (session mode, as a tap does), and the page shows it",
             bool(active) and status().get("mode") == "session" and shown == "billing" and bool(focused),
             active=status().get("active"), shown=shown, mode=status().get("mode"), said=said)
        await window.shot("b3-switched")

        t = await owner_says(browser, "Close docs.")
        gone = await until(lambda: "docs" not in names(), 30)
        said = await heard_reply(browser, t, timeout=20)
        shown = await page.until(f"!{ROWS}.split(',').includes('docs')", 8)
        step("B4 “close docs” takes docs off the voice at once, and the page drops it",
             bool(gone) and bool(shown) and {"billing", "shop", "shop-tests"} <= names(), names=sorted(names()), said=said)

        t = await owner_says(browser, "Close all except billing and shop.")
        readback = await heard_reply(browser, t, timeout=30)
        held = {"billing", "shop", "shop-tests"} <= names()
        step("B5 “close all except billing and shop” is read back, and nothing closes yet",
             held and "go ahead" in plain(readback) and re.search(r"shop[ -]?tests", plain(readback)) is not None,
             said=readback, names=sorted(names()))
        await window.shot("b5-readback")
        t = await owner_says(browser, "Yes.")
        closed = await until(lambda: names() == {"billing", "shop"}, 30)
        said = await heard_reply(browser, t, timeout=20)
        shown = await page.until(f"{ROWS} === 'billing,shop'", 8)
        step("B5 on yes only shop-tests closes, billing and shop stay, and the page shows it",
             bool(closed) and bool(shown), names=sorted(names()), said=said)

        t = await owner_says(browser, "Go back to orchestrator mode.")
        mode = await until(lambda: status().get("mode") == "orchestrator", 20)
        said = await heard_reply(browser, t, timeout=20)
        shown = await page.until("document.getElementById('m-orchestrator').classList.contains('on') && "
                                 "!document.querySelector('#list .s.on')", 8)
        step("B6 “go back to orchestrator mode” leaves the focus, and the page shows orchestrator mode",
             bool(mode) and bool(shown), mode=status().get("mode"), said=said)
        await window.shot("b6-orchestrator")
        errors = await page.js("window.__errors || []")
        step("no page errors", not errors, errors=errors)
    finally:
        await window.close()
        await browser.close()
        stop_sessions(sessions)
        stop_daemon()
        if started:
            await archive(started)
        cleanup(root)


async def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for n in range(1, runs + 1):
        try:
            await one_run(n)
        except Exception as e:
            check(f"[run {n}] the run finished", False, error=f"{type(e).__name__}: {e}"[:400])
    tally = defaultdict(lambda: [0, 0])
    for r in results:
        name = re.sub(r"^\[run \d+\] ", "", r["name"])
        tally[name][0] += r["ok"]
        tally[name][1] += 1
    print("\nper step:")
    for name, (ok, total) in tally.items():
        print(f"  {ok}/{total}  {name}")
    print(f"\nscreenshots: {SHOTS}")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} passed (demo voice control, {runs} runs)")


if __name__ == "__main__":
    asyncio.run(main())
