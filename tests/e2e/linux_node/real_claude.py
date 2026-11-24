"""A Linux node in Docker running real Claude Code, driven from the hub on this Mac by voice: pair, /pointe:voice in
the container, one request with its report, one voice approval of `git status`.

The Anthropic key goes into the container only at `docker run -e` (from the Keychain, by the shell that runs this):
  ANTHROPIC_API_KEY="$(security find-generic-password -s anthropic-api-key -w)" \
  GOOGLE_API_KEY="$(security find-generic-password -s gemini-api-key-paid -w)" \
  CLAUDE_VOICE_STATE=/tmp/cv-state-mmw-dhub CLAUDE_VOICE_DAEMON_PORT=7985 CLAUDE_VOICE_TLS_PORT=7585 \
    uv run python -u -I tests/e2e/linux_node/real_claude.py
Build the image first: docker build -t pointe-linux-node:claude -f tests/e2e/linux_node/claude.Dockerfile .
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path[0:0] = [str(Path(__file__).resolve().parents[3] / "pointe"), str(Path(__file__).resolve().parents[3])]
from rig import ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import _daemon, check, log_time, results  # noqa: E402

assert str(STATE).startswith("/tmp/cv-state-mmw"), "use CLAUDE_VOICE_STATE=/tmp/cv-state-mmw-dhub"
assert os.environ.get("ANTHROPIC_API_KEY"), "inject ANTHROPIC_API_KEY from the Keychain for docker run -e"
TLS_PORT = int(os.environ["CLAUDE_VOICE_TLS_PORT"])
HUB_ENV = {**os.environ, "CLAUDE_VOICE_FRONT": "brain"}
HUB_ENV.pop("ANTHROPIC_API_KEY")  # the hub reads its keys from the Keychain itself; this one is for the container only
CONTAINER = "pointe-mmw-claude-node"


def said_since(t: float) -> list[str]:
    return [line.split("speak: ", 1)[1] for line in log_lines(r"speak: ") if log_time(line) >= t]


async def until(test, timeout: float, step: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if got := test():
            return got
        await asyncio.sleep(step)
    return test()


async def spoken_with(t: float, needle: str, timeout: float = 150) -> str:
    pattern = re.compile(needle, re.I)
    return await until(lambda: next((s for s in said_since(t) if pattern.search(s)), ""), timeout, 2) or ""


async def say(b: Browser, text: str) -> float:
    for _ in range(80):
        spans = b.speaker.speech_spans(since=time.time() - 30)
        if not spans or time.time() - spans[-1][1] > 2:
            break
        await asyncio.sleep(0.5)
    _, end = await b.say(text)
    await asyncio.sleep(max(0, end - time.time()))
    return end


def penguin() -> dict | None:
    return next((s for s in (_daemon("/voice/status") or {}).get("sessions", []) if s.get("machine") == "penguin"), None)


async def main() -> None:
    fresh_state()
    for p in STATE.glob("*"):
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    (STATE / "config.json").write_text(json.dumps({"machine": "studio"}))
    subprocess.run(["uv", "run", "--project", str(ROOT), "python", "-c", "import pair; pair.setup('127.0.0.1', '127.0.0.1')"],
                   env=HUB_ENV, cwd=ROOT / "pointe", capture_output=True, timeout=60)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], env=HUB_ENV, capture_output=True).returncode == 0
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    inviter = subprocess.Popen([str(ROOT / "bin" / "pointe"), "hub", "invite", "--name", "penguin"], env=HUB_ENV,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = inviter.stdout.readline().strip().replace("host=127.0.0.1", "host=host.docker.internal")
    b = Browser()
    await b.connect()
    try:
        # -e NAME with no value: docker takes it from this process's environment, so the key is never in argv
        run = subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "-e", "ANTHROPIC_API_KEY", "-e",
                              f"POINTE_INVITE={line}", "-v", f"{ROOT}:/pointe:ro", "pointe-linux-node:claude"],
                             env={**os.environ}, capture_output=True, text=True)
        check("docker node container starts", run.returncode == 0, err=run.stderr[-200:])
        paired = await asyncio.to_thread(lambda: [inviter.stdout.readline() for _ in range(2)][-1])
        check("the hub shows who paired (penguin, its address and key)", "penguin paired from" in paired, said=paired.strip())
        joined = await until(penguin, 180, 2)
        check("real Claude Code in the container joins the hub's voice with /pointe:voice", bool(joined),
              session=joined, logs=subprocess.run(["docker", "logs", "--tail", "8", CONTAINER], capture_output=True,
                                                  text=True).stdout[-600:])
        if not joined:
            return
        _daemon("/voice/switch", {"name": joined["name"]})
        await asyncio.sleep(4)
        t = await say(b, f"Ask {joined['name'].split('/')[0]} to read FACT.md and tell me the penguin build number.")

        async def tap_through():  # a person tapping prompts this check is not about (a shell command to find a file)
            while True:
                s = penguin()
                if s and s.get("request_id"):
                    _daemon("/voice/approve", {"session": s["name"], "request_id": s["request_id"], "decision": "allow"})
                await asyncio.sleep(2)
        tapping = asyncio.create_task(tap_through())
        got = await spoken_with(t, "7731", 180)
        tapping.cancel()
        check("a request reaches the container's session and its report is spoken", bool(got), said=got[:200])
        # git status runs without a prompt (Claude Code allows read-only git): a touch asks, and is readable. Not
        # "approved.txt": a read-out holding a consent word is never voice-approvable, by design
        name = joined["name"].split("/")[0]
        t = await say(b, f"Ask {name} to run exactly one command, touch penguin-notes.txt, with nothing chained to it.")
        asked = await until(lambda: (lambda s: s if s and s.get("request_id") else None)(penguin()), 150, 1)
        read = await spoken_with(t, r"should it|touch", 60) if asked else ""
        for _ in range(3):
            if not asked or not asked.get("voice_can_approve"):
                break
            await say(b, "Yes.")
            if await until(lambda: not (penguin() or {}).get("request_id"), 20):
                break

        def made_in_container():
            out = subprocess.run(["docker", "exec", CONTAINER, "sh", "-c", "ls /work/penguin"], capture_output=True, text=True)
            return "penguin-notes" in out.stdout.lower()
        done = await until(made_in_container, 60, 2)
        check("a voice yes approves a readable prompt in the container (the node re-checked the spoken line)",
              bool(asked) and asked.get("voice_can_approve") and bool(done), read=read[:100], request=(asked or {}).get("request"))
    finally:
        await b.close()
        inviter.kill()
        print(subprocess.run(["docker", "logs", "--tail", "6", CONTAINER], capture_output=True, text=True).stdout[-800:])
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (Docker node, real Claude Code)")


asyncio.run(main())
