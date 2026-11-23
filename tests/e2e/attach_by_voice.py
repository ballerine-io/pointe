"""Add sessions by voice, end to end (docs/design/attach-by-voice.md): throwaway Claude Code sessions in /tmp repos,
started here under a Claude config dir of their own, an isolated daemon (its own state dir and ports), and synthetic
speech. Nothing here lists, joins or touches any other session on this machine: the daemon reads only the throwaway
account (CLAUDE_VOICE_CLAUDE_HOMES), a Codex home with no daemon and an OpenCode service file that does not exist, and a
reopened session runs in this test's own tmux server, never in a window on the screen.

  uv run --locked python -I tests/e2e/attach_by_voice.py

Paid: ElevenLabs (the user's voice, cached), the daemon's vendors, Gemini (what the bot said), Claude Haiku (the
sessions, a few turns). The Anthropic key reaches the sessions through an apiKeyHelper that reads the Keychain.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/tmp/pv-attach-e2e")
ROOT = Path(__file__).resolve().parents[2]
TMUX = ["tmux", "-L", "pv-attach-e2e", "-f", "/dev/null"]
ENV = {
    "CLAUDE_VOICE_STATE": str(BASE / "state"), "CLAUDE_VOICE_DAEMON_PORT": "9531", "CLAUDE_VOICE_TLS_PORT": "9543",
    "CLAUDE_VOICE_CLAUDE_HOMES": str(BASE / "cfg"), "CODEX_HOME": str(BASE / "codex-home"),
    "CODEX_CONTROL_SOCKET": str(BASE / "codex-home" / "none.sock"), "OPENCODE_SERVICE_FILE": str(BASE / "no-opencode.json"),
    "CLAUDE_VOICE_OPEN_WITH": str(BASE / "bin" / "open-in-tmux"), "CLAUDE_VOICE_NO_BROWSER": "1",
}
for role in ("EARS", "BRAIN", "CHECKER"):  # another vendor when one is down or slow: CLAUDE_VOICE_EARS=openai
    if os.environ.get(f"CLAUDE_VOICE_{role}"):
        ENV[f"CLAUDE_VOICE_{role}"] = os.environ[f"CLAUDE_VOICE_{role}"]
os.environ.update(ENV)  # before rig reads them

sys.path.insert(0, str(Path(__file__).parent))
from rig import Browser, log_lines  # noqa: E402
from scenarios import ask, check, daemon_status, reply_after, results, wait_log  # noqa: E402

REPOS = {"pentest-notes": "We are planning a pentest of the login service. Reply with only the word OK.",
         "docs-site": "We are rewriting the docs landing page. Reply with only the word OK.",
         "billing": "We are writing the billing migration that moves invoices to a new table. Reply with only the word OK."}
NAMES = {"pentest-notes": "pentest-recon", "docs-site": "docs", "billing": "billing-migration"}


def clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CONFIG_DIR")}
    env.update(extra)
    return env


def setup() -> None:
    subprocess.run([*TMUX, "kill-server"], capture_output=True, env=clean_env())
    subprocess.run([str(ROOT / "bin" / "voice-daemon"), "stop"], env=clean_env(), capture_output=True, timeout=60)
    shutil.rmtree(BASE, ignore_errors=True)
    for d in ("cfg", "state", "codex-home", "bin", "repos"):
        (BASE / d).mkdir(parents=True)
    (BASE / "state" / "first-hello").write_text("")
    helper = BASE / "bin" / "key-helper"  # the key is read when Claude Code asks, by this one process: never stored
    helper.write_text("#!/bin/sh\nsecurity find-generic-password -s pointe.anthropic-api-key -w 2>/dev/null || "
                      "security find-generic-password -s anthropic-api-key -w\n")
    helper.chmod(0o700)
    opener = BASE / "bin" / "open-in-tmux"
    opener.write_text(f"#!/bin/sh\nexec {' '.join(TMUX)} new-window -d -n reopened \"/bin/sh $1\"\n")
    opener.chmod(0o700)
    trusted = {}
    for repo in REPOS:
        path = BASE / "repos" / repo
        path.mkdir()
        subprocess.run("git init -q -b main && echo '# notes' > README.md && git add -A && "
                       "git -c user.email=t@example.com -c user.name=t commit -qm init", shell=True, cwd=path, check=True)
        trusted[os.path.realpath(path)] = {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}
    (BASE / "cfg" / "settings.json").write_text(json.dumps({"apiKeyHelper": str(helper), "model": "haiku"}))
    (BASE / "cfg" / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True, "theme": "dark", "projects": trusted}))


def session_env() -> list[str]:
    path = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if "/.claude/plugins/" not in p)  # no installed Pointe
    keep = {"HOME": os.environ["HOME"], "PATH": path, "USER": os.environ.get("USER", ""), "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8", "CLAUDE_CONFIG_DIR": str(BASE / "cfg"), "CLAUDE_VOICE_STATE": ENV["CLAUDE_VOICE_STATE"],
            "CLAUDE_VOICE_DAEMON_PORT": ENV["CLAUDE_VOICE_DAEMON_PORT"]}
    return ["env", "-i", *[f"{k}={v}" for k, v in keep.items()]]


def start_session(repo: str, first: bool) -> None:
    command = [*session_env(), "claude", "--plugin-dir", str(ROOT), "--permission-mode", "default", "--name", NAMES[repo]]
    tmux = [*TMUX, "new-session" if first else "new-window", "-d", *(["-s", "pv", "-x", "200", "-y", "50"] if first else []),
            "-n", repo, "-c", str(BASE / "repos" / repo), " ".join(f"'{c}'" for c in command)]
    subprocess.run(tmux, check=True, env=clean_env())  # the tmux server's own environment: a reopened window gets it


def pane(window: str) -> str:
    return subprocess.run([*TMUX, "capture-pane", "-p", "-t", f"pv:{window}"], capture_output=True, text=True).stdout


def type_into(window: str, text: str) -> None:
    subprocess.run([*TMUX, "send-keys", "-t", f"pv:{window}", "-l", text], check=True)
    time.sleep(0.5)
    subprocess.run([*TMUX, "send-keys", "-t", f"pv:{window}", "Enter"], check=True)


def roster() -> list:
    out = subprocess.run(["claude", "agents", "--json"], env=clean_env(CLAUDE_CONFIG_DIR=str(BASE / "cfg")),
                         capture_output=True, text=True, timeout=15).stdout
    try:
        return json.loads(out)
    except ValueError:
        return []


def wait(what, timeout: float, every: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = what()
        if got:
            return got
        time.sleep(every)
    return None


async def until(what, timeout: float, every: float = 1.0):
    """wait(), without blocking the event loop: the fake call keeps sending audio and answering pings meanwhile (a
    blocked loop dropped the call in an early run)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = await asyncio.to_thread(what)
        if got:
            return got
        await asyncio.sleep(every)
    return None


def listing() -> dict:
    import urllib.request

    from rig import DAEMON, STATE

    request = urllib.request.Request(f"{DAEMON}/voice/add-sessions",
                                     headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})
    return json.loads(urllib.request.urlopen(request, timeout=60).read())


def names_on_voice() -> list[str]:
    return sorted(s["name"] for s in daemon_status().get("sessions", []))


async def quiet(b, need: float = 2.5, timeout: float = 45) -> None:
    """Speak only once the bot has stopped: a yes said over its own "say yes" is dropped as its echo, as it should be."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = b.speaker.speech_spans(since=time.time() - 15)
        if not spans or time.time() - spans[-1][1] > need:
            return
        await asyncio.sleep(0.3)


async def say_and_log(b, text: str, pattern: str, timeout: float = 40, tries: int = 2) -> str | None:
    """Say it once the bot is quiet, and wait for the daemon's log line; said once more if the ears missed it."""
    for _ in range(tries):
        await quiet(b)
        before = len(log_lines(pattern))
        await ask(b, text, timeout=25)
        line = await wait_log(pattern, before, timeout)
        if line:
            return line
    return None


async def scenario() -> None:
    # Three throwaway sessions: two stay open, one is closed after its first turn.
    for i, repo in enumerate(REPOS):
        start_session(repo, first=i == 0)
    check("throwaway sessions are up", bool(wait(lambda: len(roster()) >= 3, 90)), roster=len(roster()))
    time.sleep(3)
    for repo, prompt in REPOS.items():
        type_into(repo, prompt)
    wait(lambda: all("OK" in pane(r) for r in REPOS), 90, 2)
    billing_id = next(e["sessionId"] for e in roster() if e["cwd"].endswith("/billing"))
    type_into("billing", "/exit")
    check("the billing session closed", bool(wait(lambda: not any(e["cwd"].endswith("/billing") for e in roster()), 30)))

    for attempt in (1, 2):  # a port the last run's daemon just let go of can still be busy for a moment
        up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], env=clean_env(), capture_output=True, text=True, timeout=180)
        if up.returncode == 0:
            break
        print(f"daemon did not start ({up.returncode}): {up.stderr[-400:]}", flush=True)
        time.sleep(5)
    found = listing()
    open_names = sorted(x["name"] for x in found["open"])
    recent_names = sorted(x["name"] for x in found["recent"])
    paths = [x["path"] for x in found["open"] + found["recent"]]
    check("discovery lists the two open throwaway sessions", open_names == ["docs", "pentest-recon"], open=open_names)
    check("discovery lists the closed one as recent", "billing-migration" in recent_names, recent=recent_names)
    check("discovery lists nothing outside the throwaway account",
          all(os.path.realpath(p).startswith(os.path.realpath(BASE)) for p in paths), paths=len(paths))
    check("the plugin's hook applies to a session started with it",
          all(x["approvals"] for x in found["open"]), approvals=[x["approvals"] for x in found["open"]])

    b = Browser()
    await b.connect()
    await reply_after(b, time.time(), timeout=30, quiet=3)  # the greeting, heard out before anything is said
    try:
        line = await say_and_log(b, "Hey Pointe connect to the session about the recent pentest.", r"add read back: ")
        check("a description is read back", bool(line and "Join pentest-recon, the Claude Code session in pentest-notes" in line),
              line=line)
        joined = await say_and_log(b, "Yes.", r"pentest-recon added from outside", tries=2)
        check("a yes joins it from outside", bool(joined) and "pentest-recon" in names_on_voice(), on_voice=names_on_voice())
        caps = next((s["capabilities"] for s in daemon_status()["sessions"] if s["name"] == "pentest-recon"), {})
        check("its approvals reach the voice", caps.get("approvals") is True, caps=caps)

        await quiet(b)
        await ask(b, "Tell pentest-recon to reply with just the word pineapple.")
        check("a send reaches the attached session", bool(await until(lambda: "pineapple" in pane("pentest-notes").lower(), 90, 2)))

        repo = BASE / "repos" / "pentest-notes"
        await quiet(b)
        await ask(b, "Tell pentest-recon to create a file called scope.txt containing the word login.")
        held = await until(lambda: any(s["name"] == "pentest-recon" and s.get("request_id") for s in daemon_status()["sessions"]), 120, 2)
        check("its permission prompt is held by the voice", bool(held))
        if held:
            read_out = await until(lambda: log_lines(r"bot said: .*pentest-recon wants"), 120, 1)  # the read-out first
            await quiet(b)
            await ask(b, "Yes, allow it.")
            check("a spoken yes approves it", bool(read_out) and bool(await until(lambda: (repo / "scope.txt").exists(), 90, 2)))

        line = await say_and_log(b, "Connect to all open Claude Code sessions.", r"add read back: ")
        check("all open ones are read back by count and name",
              bool(line and "Join the one open Claude Code session on" in line and "docs?" in line), line=line)
        await say_and_log(b, "Yes.", r"docs added from outside", tries=2)
        check("they join on yes", "docs" in names_on_voice(), on_voice=names_on_voice())

        line = await say_and_log(b, "Reopen the session about the billing migration.", r"add read back: ")
        check("a reopen is read back with its terminal window",
              bool(line and "Reopen billing-migration" in line and "in a new terminal window" in line), line=line)
        await say_and_log(b, "Yes.", r"reopening the claude-code session")
        rejoined = await until(lambda: any(s["name"] == "billing-migration" for s in daemon_status()["sessions"]), 120, 2)
        resumed = [e for e in (await asyncio.to_thread(roster)) if e.get("sessionId") == billing_id]
        check("the reopened session resumes with its own id and joins", bool(rejoined) and bool(resumed),
              on_voice=names_on_voice(), resumed=len(resumed))

        await say_and_log(b, "Leave the pentest session.", r"pentest-recon disconnected")
        gone = await until(lambda: "pentest-recon" not in names_on_voice(), 30)
        still = any(e["cwd"].endswith("/pentest-notes") for e in (await asyncio.to_thread(roster)))
        check("leave takes it off the voice and it keeps running", bool(gone) and still, on_voice=names_on_voice())
    finally:
        await b.close()


def teardown() -> None:
    subprocess.run([str(ROOT / "bin" / "voice-daemon"), "stop"], env=clean_env(), capture_output=True, timeout=60)
    subprocess.run([*TMUX, "kill-server"], capture_output=True)
    left = subprocess.run(["pgrep", "-f", str(BASE)], capture_output=True, text=True).stdout.split()
    for pid in left:
        subprocess.run(["kill", pid], capture_output=True)


def main() -> int:
    setup()
    try:
        asyncio.run(scenario())
    finally:
        teardown()
    failed = [r["name"] for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
