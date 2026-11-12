"""Show while it says, in the page: a real (headless) Chrome on a live call, the real reader, brain and mouth.

A synthetic project (pricing.py and its tests, committed) is registered as a session; its transcript then gets a turn
that edits pricing.py at lines 40-42 and runs a failing pytest. While the voice speaks the report, the Showing pane must
list the failing test and the edit, open the test output at the failing assertion, show the edited lines highlighted
and the diff, and the spoken words must name no path or code. Then: the voice's "pricing" moves the pane, a pin holds
it across a second report, an earlier set opens from "Shown earlier", a secret in a shown file is masked, a hidden file
shows its name only, folding hides the pane, a narrow window turns it into a bottom sheet, and the phone key reads
nothing until "Also show on the phone" is on.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-sws CLAUDE_VOICE_DAEMON_PORT=7950 CLAUDE_VOICE_TLS_PORT=7550 \
     uv run python -u -I tests/e2e/page_show.py
Takes about three minutes. Calls paid APIs (the configured ears, reader, brain and mouth). Screenshots: $POINTE_SHOTS.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = 9350
PRICING = "".join(f"def rule_{n}(price):\n    return price  # rule {n}\n\n" for n in range(1, 35))
FAILING = ("tests/test_pricing.py::test_gold_discount FAILED\n"
           "    def test_gold_discount():\n"
           ">       assert rule_14(100) == 80\n"
           "E       AssertionError: assert 100 == 80\n"
           "=========== 1 failed, 6 passed in 0.12s ===========")
SECRET = "sk-synthetic-e2e-0123456789abcdef"


def phone(path: str, body: dict | None = None) -> tuple[int, dict]:
    """The phone app's key, from this machine (LocalAuth accepts it on localhost as on the TLS listener)."""
    key = (STATE / "phone_key").read_text().strip()
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def project() -> Path:
    root = Path(tempfile.mkdtemp(prefix="pointe-show-e2e-")) / "shop"
    (root / "tests").mkdir(parents=True)
    (root / "pricing.py").write_text(PRICING)
    (root / "settings.py").write_text('DEBUG = True\nTIMEOUT = 30\n')
    (root / "tests" / "test_pricing.py").write_text("from pricing import rule_14\n\n\ndef test_gold_discount():\n"
                                                   "    assert rule_14(100) == 80\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "e2e", "GIT_AUTHOR_EMAIL": "e2e@example.com", "GIT_COMMITTER_NAME": "e2e",
           "GIT_COMMITTER_EMAIL": "e2e@example.com"}
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "start"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True)
    return root


def line(kind: str, content, stop: str | None = None) -> str:
    message = {"role": kind, "content": content, **({"stop_reason": stop} if stop else {})}
    return json.dumps({"type": kind, "message": message, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n"


def turn(transcript: Path, n: int, edits: list[tuple[Path, str, str]], test: str | None, final: str) -> None:
    """A finished Claude Code turn, written the way Claude Code writes it: tool uses, their results, the final text."""
    lines = [line("user", f"Fix the gold discount, round {n}.")]
    for i, (path, old, new) in enumerate(edits):
        path.write_text(path.read_text().replace(old, new))
        lines += [line("assistant", [{"type": "tool_use", "id": f"e{n}{i}", "name": "Edit",
                                      "input": {"file_path": str(path), "old_string": old, "new_string": new}}]),
                  line("user", [{"type": "tool_result", "tool_use_id": f"e{n}{i}", "content": "The file was updated."}])]
    if test:
        lines += [line("assistant", [{"type": "tool_use", "id": f"b{n}", "name": "Bash", "input": {"command": "uv run pytest -q tests"}}]),
                  line("user", [{"type": "tool_result", "tool_use_id": f"b{n}", "content": "Exit code 1\n" + test, "is_error": True}])]
    lines.append(line("assistant", [{"type": "text", "text": final}], "end_turn"))
    with transcript.open("a") as f:
        f.writelines(lines)


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


async def quiet(timeout: float = 60) -> None:
    await until(lambda: call("/voice/status")["speaking"] != "bot", timeout)
    await asyncio.sleep(1.5)


async def watch_report(timeout: float = 90) -> dict:
    """Samples status until a report was spoken and the voice went quiet: did `showing` overlap the speech?"""
    seen = {"overlap": False, "showing": None, "spoke": False}
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = call("/voice/status")
        if s["speaking"] == "bot":
            seen["spoke"] = True
            if s["showing"]:
                seen["overlap"], seen["showing"] = True, s["showing"]
        elif seen["spoke"] and seen["overlap"]:
            break
        await asyncio.sleep(0.2)
    return seen


def bot_words(since: int) -> str:
    """Everything the voice said after the first `since` speak lines (the daemon logs each one whole)."""
    return " ".join(log_lines(r"speak: ")[since:])


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    (STATE / "prefs.json").unlink(missing_ok=True)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    root = project()
    transcript = root.parent / "transcript.jsonl"
    # Registration happens inside the turn that ran /pointe:voice; that turn's end is the join, never read out.
    transcript.write_text(line("user", "<command-name>/pointe:voice</command-name>"))
    call("/voice/register", {"id": f"page-show-{os.getpid()}", "cwd": str(root), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(transcript)})
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                               "--autoplay-policy=no-user-gesture-required", "--window-size=1500,900", "--no-first-run",
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
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("document.getElementById('settingsbtn')", 10)
            check("before any report the pane is not there", not await page.js("document.body.classList.contains('showing')"))

            await page.js("startCall()")
            await page.until("call.state === 'live'", 20)
            await until(lambda: call("/voice/status")["speaking"] == "bot", 20)
            await quiet()  # the greeting
            with transcript.open("a") as f:  # the join turn ends
                f.write(line("assistant", [{"type": "text", "text": "Joined the voice."}], "end_turn"))
            await asyncio.sleep(2.0)

            # ---- a report with a failing test and an edit ----
            first_turn = len(log_lines(r"speak: "))  # a report joins the greeting's turn in `talk`: count speech instead
            turn(transcript, 1, [(root / "pricing.py", "    return price  # rule 14\n",
                                  "    return price * 0.8  # rule 14: gold pays 80%\n")], FAILING,
                 "I changed rule_14 in pricing.py so gold customers pay 80%. tests/test_pricing.py still fails: "
                 "test_gold_discount gets 100 instead of 80.")
            seen = await watch_report()
            shown = seen["showing"] or {}
            kinds = [(a["kind"], a["name"], a.get("failed")) for a in shown.get("artifacts", [])]
            check("while the voice speaks the report, status shows the failing test and the edited file",
                  seen["overlap"] and kinds[:2] == [("test", "test output", True), ("edit", "pricing.py", False)],
                  spoke=seen["spoke"], kinds=kinds)
            edit = next((a for a in shown.get("artifacts", []) if a["kind"] == "edit"), {})
            check("the edit's range is the edited line", edit.get("range") == [41, 41], range=edit.get("range"))
            said = bot_words(first_turn)
            check("the voice names no path or code; it may point at the screen",
                  bool(said) and not re.search(r"\.py\b|`|rule_14|assert ", said.split("speak: ", 1)[-1]), said=said[-400:])
            await page.until("document.body.classList.contains('showing')", 5)
            pane = await page.until("""(() => { const b = document.getElementById('show-body');
              const f = b.querySelector('.ln.focus'); return f && {focus: f.textContent, title: document.getElementById('show-title').textContent,
              arts: [...document.querySelectorAll('#show-arts button')].map(x => x.textContent),
              tabs: [...document.querySelectorAll('#show-tabs button')].map(x => x.textContent)}; })()""", 10)
            await page.shot("show-1-test")
            check("the pane opens on the failing test, scrolled to the failing assertion",
                  bool(pane) and "assert rule_14(100) == 80" in pane["focus"] and pane["tabs"] == ["Test"]
                  and pane["arts"][:2] == ["Failing test", "pricing.py"], **(pane or {}))

            await page.js("[...document.querySelectorAll('#show-arts button')].find(b => b.textContent === 'pricing.py').click()")
            file_view = await page.until("""(() => { const hl = [...document.querySelectorAll('#show-body .ln.hl')];
              return hl.length && {hl: hl.map(x => x.textContent), first: document.querySelector('#show-body .ln .n').textContent,
              tabs: [...document.querySelectorAll('#show-tabs button')].map(x => x.textContent),
              where: document.getElementById('show-where').textContent}; })()""", 10)
            await page.shot("show-2-file")
            check("File shows the edited line highlighted, twenty lines of context above it",
                  bool(file_view) and len(file_view["hl"]) == 1 and "gold pays 80%" in file_view["hl"][0]
                  and file_view["first"] == "21" and file_view["tabs"] == ["File", "Diff"] and "pricing.py" in file_view["where"] and "line 41" in file_view["where"],
                  **(file_view or {}))
            await page.js("[...document.querySelectorAll('#show-tabs button')].find(b => b.textContent === 'Diff').click()")
            diff = await page.until("""(() => { const a = [...document.querySelectorAll('#show-body .ln.add')].map(x => x.textContent),
              d = [...document.querySelectorAll('#show-body .ln.del')].map(x => x.textContent); return a.length && {add: a, del: d}; })()""", 10)
            await page.shot("show-3-diff")
            check("Diff shows the change against the last commit", bool(diff)
                  and any("price * 0.8" in x for x in diff["add"]) and any("# rule 14" in x for x in diff["del"]), **(diff or {}))

            # ---- the phone sees nothing until it is enabled ----
            code, status = phone("/voice/status")
            art_code, _ = phone(f"/voice/artifact?id={edit.get('id')}")
            check("the phone key gets no showing and no artifact while the setting is off",
                  code == 200 and status.get("showing") is None and status.get("shown_earlier") == [] and art_code == 403,
                  code=code, artifact=art_code, show_on_phone=status.get("show_on_phone"))
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            await page.js("document.getElementById('pref-showphone').checked = true; saveSettings()")
            await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            code, status = phone("/voice/status")
            art_code, art = phone(f"/voice/artifact?id={edit.get('id')}")
            check("after 'Also show on the phone', the phone key reads the same artifact",
                  status.get("show_on_phone") is True and art_code == 200 and "price * 0.8" in json.dumps(art),
                  artifact=art_code)
            phone("/voice/prefs", {"show.on_phone": False})
            check("turning it off closes it again", phone(f"/voice/artifact?id={edit.get('id')}")[0] == 403)

            # ---- pin, then a second report: a secret masked, a hidden file named only ----
            await page.js("[...document.querySelectorAll('#show-arts button')].find(b => b.textContent === 'pricing.py').click(); pinArtifact()")
            await quiet()
            env_file = root / ".env.local"
            env_file.write_text("PAYMENTS_TOKEN=old\n")
            turn(transcript, 2, [(root / "settings.py", "TIMEOUT = 30\n", f'TIMEOUT = 45\nPAYMENTS_KEY = "{SECRET}"\n'),
                                 (env_file, "PAYMENTS_TOKEN=old", "PAYMENTS_TOKEN=synthetic-new-value")], None,
                 "I raised TIMEOUT to 45 in settings.py and updated the payments token in .env.local.")
            seen2 = await watch_report()
            second = seen2["showing"] or {}
            pinned = await page.js("""(() => ({title: document.getElementById('show-title').textContent,
              arts: [...document.querySelectorAll('#show-arts button')].map(x => x.textContent)}))()""")
            check("a pinned artifact stays on screen when the next report comes",
                  seen2["overlap"] and pinned["title"].startswith("Pinned") and pinned["arts"] == ["pricing.py"], **pinned)
            await page.js("pinArtifact()")
            followed = await page.until("""(() => { const a = [...document.querySelectorAll('#show-arts button')].map(x => x.textContent);
              return a.includes('settings.py') && a; })()""", 10)
            await page.js("[...document.querySelectorAll('#show-arts button')].find(b => b.textContent === 'settings.py').click()")
            masked = await page.until("""(() => { const t = document.getElementById('show-body').textContent;
              return t.includes('TIMEOUT = 45') && t; })()""", 10)
            check("unpinned, the pane follows the new report; a key in a shown file is masked",
                  bool(followed) and bool(masked) and SECRET not in masked and "PAYMENTS_KEY" in masked, arts=followed)
            await page.js("[...document.querySelectorAll('#show-arts button')].find(b => b.textContent === '.env.local').click()")
            hidden = await page.until("""(() => { const t = document.getElementById('show-body').textContent;
              return t.includes('not shown') && t; })()""", 10)
            await page.shot("show-4-hidden")
            check("a hidden file shows its name only", bool(hidden) and "synthetic-new-value" not in hidden, text=hidden)
            all_said = bot_words(first_turn)
            check("nothing secret was said aloud", bool(all_said) and SECRET not in all_said and "synthetic-new-value" not in all_said)

            # ---- shown earlier, fold, narrow ----
            await page.js("document.getElementById('show-earlier').open = true")
            earlier = await page.js("[...document.querySelectorAll('#show-earlier-list button')].map(b => b.textContent)")
            await page.js("document.querySelector('#show-earlier-list li:last-child button').click()")
            back = await page.until("""(() => { const a = [...document.querySelectorAll('#show-arts button')].map(x => x.textContent);
              return a.includes('Failing test') && {arts: a, title: document.getElementById('show-title').textContent}; })()""", 10)
            check("Shown earlier lists both reports and reopens the first", len(earlier) == 2 and bool(back)
                  and back["title"].startswith("Last shown"), earlier=earlier, back=back)
            await page.js("foldShow()")
            folded = await page.js("getComputedStyle(document.getElementById('show-body')).display")
            await page.shot("show-5-folded")
            await page.js("foldShow()")
            check("folding hides the pane's content (screen sharing) and unfolding brings it back", folded == "none")
            await page.cdp("Emulation.setDeviceMetricsOverride", {"width": 600, "height": 900, "deviceScaleFactor": 1, "mobile": False})
            await asyncio.sleep(0.8)
            narrow = await page.js("getComputedStyle(document.getElementById('show')).position")
            await page.shot("show-6-narrow")
            await page.cdp("Emulation.clearDeviceMetricsOverride")
            check("on a narrow window the pane is a bottom sheet", narrow == "fixed", position=narrow)
            check("no script errors", not await page.js("window.__errors"), errors=await page.js("window.__errors"))
            await page.js("endCall()")
    finally:
        chrome.terminate()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page show while it says)")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
