"""The Mac app against a real daemon, end to end, with nothing of the room recorded: a call placed by the app, words
typed in its window, a request denied in the window and one approved through the app's client, a brain dump, the
Settings and Phone sheets. Run by hand:

    uv run --locked python -I macos/e2e/live.py

It starts its own daemon (its own state folder and port: never 7860, 7443 or ~/.claude-voice), registers a made-up
session, opens the app from its build folder on that daemon (never the installed app), and presses its controls through
the Accessibility API (macos/e2e/axdrive.swift: the terminal needs the Accessibility permission). It uses the model keys
in your Keychain (a few cents); the daemon reads them itself, and nothing here sees one.

No room audio leaves the Mac: before the app connects, the daemon's microphone setting is Push to talk, and the script
never presses the talk button, so the call's gate stays closed and the app sends none of what its microphone hears
(the last moments are held in memory only, and dropped). What is said to Pointe is typed in the window. The bot's voice
does play through the speaker. The Approve button's Touch ID cannot be pressed by a script: Approve goes through the
app's own loopback client (LiveDaemonTests), Deny through the window. The daemon's state (journal, log) is deleted when
the run ends.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("POINTE_E2E_DIR", "/tmp/pointe-mac-e2e"))
STATE, PORT = WORK / "state", int(os.environ.get("POINTE_E2E_PORT", "7873"))
assert PORT not in (7860, 7443) and ".claude-voice" not in str(STATE), "never the live daemon"
ENV = {**os.environ, "CLAUDE_VOICE_STATE": str(STATE), "CLAUDE_VOICE_DAEMON_PORT": str(PORT)}
SESSION = "e2e-docs-session"
REQUEST = {"command": "git status", "description": "Show the working tree status"}
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}"[:240], flush=True)


def api(path: str, body: dict | None = None, timeout: float = 10):
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}", "content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read() or b"{}")


def status() -> dict:
    return api("/voice/status")


def until(what: str, check_: callable, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if check_():
                return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    print(f"      (timed out after {timeout:.0f} s: {what})", flush=True)
    return False


def say(text: str) -> None:
    subprocess.run(["say", "-r", "165", text], check=False)


def hold_request(out: dict) -> None:
    """What Claude Code's PermissionRequest hook does: ask, and wait for the answer."""
    try:
        reply = api("/voice/permission-hook", {"session_id": SESSION, "tool_name": "Bash", "tool_input": REQUEST}, timeout=200)
        out["verdict"] = (reply.get("hookSpecificOutput") or {}).get("decision", {}).get("behavior")
    except Exception as e:  # noqa: BLE001: the reason is the result
        out["verdict"] = f"error: {e}"


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    STATE.mkdir(parents=True)
    project = WORK / "docs"
    project.mkdir()
    transcript = WORK / f"{SESSION}.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "Update the changelog for the retry fix."}}) + "\n")
    sleeper = subprocess.Popen(["sleep", "900"])  # the made-up session's process
    ui = None
    try:
        started = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], env=ENV, capture_output=True, text=True, timeout=600)
        check("the isolated daemon started", started.returncode == 0, started.stdout.strip() or started.stderr.strip()[-200:])
        if started.returncode:
            return 1
        api("/voice/register", {"id": SESSION, "name": "docs", "cwd": str(project), "pid": sleeper.pid, "transcript": str(transcript),
                                "inbox_socket": None, "inbox_token": None, "channel_url": None, "name_given": True,
                                "config_dir": str(WORK / "claude")})
        check("a made-up session is on the voice", [s["name"] for s in status()["sessions"]] == ["docs"])

        live = subprocess.run(["swift", "test", "--filter", "theDaemonIsFoundVerifiedAndOpenedByThePageKey"], cwd=ROOT / "apple" / "PointeKit",
                              env={**ENV, "POINTE_E2E_STATE": str(STATE), "POINTE_E2E_PORT": str(PORT)}, capture_output=True, text=True)
        check("the app's locator and client: found, listener verified, opened by the page key, refused without it",
              live.returncode == 0 and "passed" in live.stdout, live.stdout.strip().splitlines()[-1] if live.stdout.strip() else live.stderr[-200:])

        api("/voice/prefs", {"microphone": "ptt"})  # the gate is closed until a press: nothing of the room is sent
        check("the microphone is Push to talk before the app connects (no room audio is sent)", api("/voice/prefs").get("microphone") == "ptt")

        built = subprocess.run([str(ROOT / "macos" / "build.sh")], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        binary = WORK / "axdrive"
        tool = subprocess.run(["swiftc", "-O", str(ROOT / "macos" / "e2e" / "axdrive.swift"), "-o", str(binary)], capture_output=True, text=True)
        check("the app and the driver built", built.returncode == 0 and tool.returncode == 0, (built.stderr or tool.stderr)[-300:])
        if built.returncode or tool.returncode:
            return 1
        bundle = built.stdout.strip().splitlines()[-1]
        assert "/build/" in bundle, "the app under test is the one in the build folder, never an installed one"
        subprocess.run(["open", "-n", bundle, "--env", f"CLAUDE_VOICE_STATE={STATE}", "--env", f"CLAUDE_VOICE_DAEMON_PORT={PORT}",
                        "--args", "-PointeOpenWindow", "YES", "-ApplePersistenceIgnoreState", "YES"], check=True)
        until("the app's process", lambda: subprocess.run(["pgrep", "-nf", f"{bundle}/Contents/MacOS/Pointe"], capture_output=True).returncode == 0, 20)
        app = subprocess.run(["pgrep", "-nf", f"{bundle}/Contents/MacOS/Pointe"], capture_output=True, text=True).stdout.strip()

        def ax(*words: str) -> subprocess.CompletedProcess:
            return subprocess.run([str(binary), app, *words], capture_output=True, text=True)

        def shot(name: str) -> None:
            window = ax("window").stdout.strip()
            subprocess.run(["caffeinate", "-u", "-t", "1"], check=False)  # a sleeping display draws no window
            if window:
                Path("/tmp/macos-app-shots").mkdir(exist_ok=True)
                subprocess.run(["screencapture", "-x", "-o", "-l", window, f"/tmp/macos-app-shots/{name}.png"], check=False)

        check("the app found the daemon, checked it, and lists its session in the sessions column",
              until("session", lambda: ax("exists", "session.docs").returncode == 0, 40), ax("label", "session.docs").stdout.strip())
        shot("live-01-found")
        ui = app
        check("the switch over the mic says Push to talk, as the daemon has it", ax("exists", "micModeSwitch").returncode == 0)
        check("Connect was pressed", ax("press", "connectButton").returncode == 0)
        for _ in range(16):  # macOS asks for the microphone the first time: allow it
            if status()["connected"]:
                break
            for owner in subprocess.run(["pgrep", "-f", "UserNotificationCenter|CoreServicesUIAgent"], capture_output=True, text=True).stdout.split():
                subprocess.run([str(binary), owner, "button", "Allow"], capture_output=True)
            time.sleep(0.5)

        up = until("the app's call", lambda: status()["connected"], 120)
        check("the app placed the call (the daemon says a call is up)", up)
        if not up:
            return 1
        check("the call is the Mac app's on the page's socket", until("hello", lambda: "page connected" in (STATE / "daemon.log").read_text(), 10))
        greeted = until("the greeting", lambda: any(t["who"] != "user" for t in status().get("talk") or []), 60)
        check("the bot greeted (its voice went down the app's socket)", greeted)
        check("the gate stayed closed: nothing the microphone heard became a turn",
              not any(t["who"] == "user" for t in status().get("talk") or []) and not (status().get("ptt") or {}).get("open"))
        check("the state line says Hold to talk", until("state", lambda: "talk" in ax("label", "statusLine").stdout.lower(), 20), ax("label", "statusLine").stdout.strip())

        check("Type opened the type bar", ax("press", "typeButton").returncode == 0 and until("field", lambda: ax("exists", "typeField").returncode == 0, 10))
        typed = ax("type", "typeField", "Which sessions are on the voice right now?")
        if typed.returncode:  # the field took the words and not the Return: the Send button does the same
            ax("press", "typeSend")
        said = until("the typed turn", lambda: any(t["who"] == "user" and "sessions" in t["text"].lower() for t in status().get("talk") or []), 30)
        check("words typed in the window became a turn", said)
        check("and the voice answered them", until("answer", lambda: sum(t["who"] != "user" for t in status().get("talk") or []) >= 2, 60))
        shot("live-02-call")

        first: dict = {}
        threading.Thread(target=hold_request, args=(first,), daemon=True).start()
        shown = until("the card", lambda: ax("exists", "requestDeny").returncode == 0, 40)
        card = ax("texts", "requestCommand").stdout.strip()
        check("the request is on the card: the command, word for word", shown and "git status" in card, repr(card)[:120])
        shot("live-03-request")
        ax("press", "requestDeny")
        denied = until("deny", lambda: "verdict" in first, 60)
        check("Deny in the window reached the session, with no Touch ID", denied and first.get("verdict") == "deny", str(first))

        second: dict = {}
        threading.Thread(target=hold_request, args=(second,), daemon=True).start()
        check("a second request is on the card with Approve", until("the card", lambda: ax("exists", "requestApprove").returncode == 0, 40))
        approve = subprocess.run(["swift", "test", "--filter", "aClicksApproveReachesTheWaitingSession"], cwd=ROOT / "apple" / "PointeKit",
                                 env={**ENV, "POINTE_E2E_STATE": str(STATE), "POINTE_E2E_PORT": str(PORT), "POINTE_E2E_APPROVE": "1"},
                                 capture_output=True, text=True)
        until("approve", lambda: "verdict" in second, 30)
        check("Approve through the app's client reached the session, and a second click was refused as no longer pending",
              approve.returncode == 0 and second.get("verdict") == "allow", f"{second} {approve.stdout.strip().splitlines()[-1:]}")
        check("answered elsewhere: the card left the window", until("card gone", lambda: ax("exists", "requestApprove").returncode != 0, 20))

        check("Settings opened from the ••• button, with this Mac's own sections after the shared ones",
              ax("press", "settingsButton").returncode == 0 and until("sheet", lambda: ax("exists", "microphoneSetting").returncode == 0, 10)
              and ax("exists", "settings.daemon").returncode == 0 and ax("exists", "settings.shortcut").returncode == 0)
        shot("live-04-settings")
        check("Phone opened from Settings: the page's Settings → Phone, in the app",
              ax("press", "phoneItem").returncode == 0 and until("phone", lambda: ax("exists", "phoneConnect").returncode == 0, 15))
        shot("live-05-phone")
        ax("button", "Done")
        time.sleep(1)

        check("Brain dump was pressed", ax("press", "dumpButton").returncode == 0)
        dumping = until("the dump", lambda: (status().get("brain_dump") or {}).get("state") == "dumping", 60)
        check("the brain dump started from the window", dumping, ax("label", "statusLine").stdout.strip())
        if dumping:
            check("the brain dump's panel replaced the conversation", until("panel", lambda: ax("exists", "dump.panel").returncode == 0, 10))
            shot("live-06-dump")
            ax("press", "dump.discard")
            time.sleep(0.5)
            if status().get("brain_dump") is not None:
                ax("press", "dump.discard")  # the second click, where Discard asks twice
            check("Discard ended it and nothing was sent", until("discard", lambda: status().get("brain_dump") is None, 60)
                  and not any("(brain dump)" in str(d.get("said")) for d in status().get("recent") or []))
        check("the call is still up after all of that", status()["connected"], ax("label", "statusLine").stdout.strip())
        pressed = ax("press", "hangUp").returncode == 0  # the button goes with the call: the press can report that it vanished
        check("Hang up was pressed", pressed or until("the button gone", lambda: ax("exists", "hangUp").returncode != 0, 5))
        check("Hang up ended the call", until("hang up", lambda: not status()["connected"], 60))
        check("the window says so", until("state", lambda: ax("label", "connectTitle").stdout.strip() == "Not connected"
                                          or ax("label", "statusLine").stdout.strip().startswith("Not connected"), 15),
              f"{ax('label', 'connectTitle').stdout.strip()!r} {ax('label', 'statusLine').stdout.strip()!r}")
        check("no room audio was ever sent: no spoken turn in the whole call",
              all(t.get("typed") or t["who"] != "user" for t in status().get("talk") or []))
    finally:
        if os.environ.get("POINTE_E2E_TRACE"):  # how the call came and went, without what was said
            for line in (STATE / "daemon.log").read_text().splitlines():
                if any(word in line for word in ("connected", "disconnect", "hung", "idle", "closing", "ERROR", "Traceback", "hang")):
                    print("      log:", line[:200])
        if ui:
            subprocess.run(["kill", str(ui)], capture_output=True)
        subprocess.run([str(ROOT / "bin" / "voice-daemon"), "stop"], env=ENV, capture_output=True, timeout=60)
        sleeper.kill()
        shutil.rmtree(WORK, ignore_errors=True)  # the journal and the log hold what the room said
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
