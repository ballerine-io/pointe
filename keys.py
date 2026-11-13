"""Save a model key in the macOS Keychain without it ever touching a command line, a chat, a file or a log.

    pointe key gemini|anthropic|openai|soniox|elevenlabs

A native dialog with hidden input asks for the key; `security` receives it through its own password prompt (a pty), so it
is never an argument. Made for people who do not use a terminal: Claude Code can run this for them.
"""

import os
import pty
import select
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
from vendors import KEYS  # noqa: E402

WHERE = {
    "gemini": "aistudio.google.com/apikey",
    "anthropic": "console.anthropic.com/settings/keys",
    "openai": "platform.openai.com/api-keys",
    "soniox": "console.soniox.com",
    "elevenlabs": "elevenlabs.io/app/settings/api-keys",
}


def ask(vendor: str) -> str | None:
    """A macOS dialog with hidden typing. None if the user cancelled."""
    script = (f'display dialog "Paste your {vendor.capitalize()} API key.\\n\\nGet one at {WHERE[vendor]}\\n\\n'
              f'It is saved in your Mac\'s Keychain, nowhere else." default answer "" with hidden answer '
              f'with title "Pointe" buttons {{"Cancel", "Save"}} default button "Save"\n'
              f'text returned of result')
    got = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else None


def save(item: str, secret: str) -> bool:
    """`security` asks for the password on its terminal: answer it there, twice, so the key never is an argument."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("security", ["security", "add-generic-password", "-U", "-s", item, "-a", os.environ.get("USER", "pointe"), "-w"])
    answered, deadline = 0, time.time() + 15
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(fd, 256)
                except OSError:
                    chunk = b""
                if chunk.rstrip().endswith(b":") and answered < 2:  # "password data for new item:", then "retype ...:"
                    os.write(fd, secret.encode() + b"\n")
                    answered += 1
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status) == 0
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        return False
    finally:
        os.close(fd)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in KEYS:
        print(f"usage: pointe key {'|'.join(KEYS)}")
        return 2
    vendor = argv[0]
    secret = ask(vendor)
    if not secret:
        print("Cancelled: nothing saved.")
        return 1
    item = KEYS[vendor][1]
    if not save(item, secret):
        print(f"Could not save it in the Keychain (item {item}).")
        return 1
    print(f"Saved your {vendor} key in the Keychain as {item}. If the voice is running, restart it to use it: /pointe:stop, then /pointe:voice.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
