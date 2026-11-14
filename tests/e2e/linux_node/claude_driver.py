"""Inside the container: pair with the hub on the Mac (POINTE_INVITE), then run real Claude Code with the plugin and
join it with /pointe:voice. The hub drives it by voice; this only keeps the terminal answered and prints its tail."""

import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")
REPO = Path("/work/penguin")


def main() -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    assert key, "ANTHROPIC_API_KEY must be injected with docker run -e"
    # Claude Code's first-run questions: onboarding done, this key approved (it stores only the key's last 20 characters)
    Path("/root/.claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark", "customApiKeyResponses": {"approved": [key[-20:]], "rejected": []},
        "projects": {str(REPO): {"hasTrustDialogAccepted": True}}}))
    joined = subprocess.run(["/pointe/bin/pointe", "node", "join", os.environ["POINTE_INVITE"]],
                            capture_output=True, text=True, timeout=300)
    print("JOIN", joined.returncode, (joined.stdout + joined.stderr).strip()[-400:], flush=True)
    if joined.returncode:
        sys.exit(1)
    REPO.mkdir(parents=True, exist_ok=True)
    (REPO / "fact.md").write_text("# Facts\nThe penguin build number is 7731.\n")
    subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                   shell=True, cwd=REPO, check=True)
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(REPO)
        os.execvp("claude", ["claude", "--plugin-dir", "/pointe", "--model", os.environ.get("TEST_MODEL", "haiku"),
                             "--permission-mode", "default"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
    screen, handled, typed, last = "", set(), False, 0.0
    started = time.time()
    while True:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try:
                screen = (screen + ANSI.sub("", os.read(fd, 65536).decode("utf-8", "replace")))[-200_000:]
            except OSError:
                print("claude exited", flush=True)
                return
        flat = re.sub(r"\s+", "", screen).lower()[-8000:]
        if "trustthisfolder" in flat and "trust" not in handled:
            handled.add("trust"), time.sleep(0.4), os.write(fd, b"\x1b[B"), time.sleep(0.2), os.write(fd, b"\r")  # "No, exit" is first
        if not typed and time.time() - started > 12:
            os.write(fd, b"/pointe:voice"), time.sleep(0.6), os.write(fd, b"\r")
            typed = True
            print("TYPED /pointe:voice", flush=True)
        if time.time() - last > 20:
            last = time.time()
            print("SCREEN", flat[-300:], flush=True)


if __name__ == "__main__":
    main()
