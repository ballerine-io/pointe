"""pointe setup, in a terminal: the same one-question flow as /pointe:setup in Claude Code, for someone who installed
Pointe without it (install.sh), then Codex and OpenCode.

    pointe setup [--no-open]     this Mac, one question (Start with Free start?), your key, your first call; then Codex
                                 and OpenCode, if this Mac has them
    pointe setup codex           Codex's shared app-server, the `codex` alias (asked; the exact line is shown first)
    pointe setup opencode        /voice in OpenCode (pointe join opencode --install-command)

--no-open runs no window and no browser: it prints the commands that would open them (tests use it). Keys go only
through the Mac window `pointe key` opens, never through this terminal.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the checkout
sys.path.insert(0, str(ROOT / "pointe"))  # run with python -I
import setups  # noqa: E402

BIN = ROOT / "bin"
RC_MARK = "# Pointe: codex runs on Codex's shared app-server, so pointe join codex reaches it (pointe uninstall removes this)"
CODEX_ALIAS = """alias codex='command codex app-server daemon start >/dev/null 2>&1; command codex --remote unix:// -C "$PWD"'"""
FREE_START = ("Pointe needs its own model key: your coding agent's subscription cannot be used by other apps. The quickest "
              "start is Free start: one Google key, no card, $0 until the free quota ends. Google may review what you "
              "send on the free tier, so try it on work that is not confidential.")


def say(text: str = "") -> None:
    print(text, flush=True)


def ask(question: str, default: bool = False) -> bool:
    try:
        answer = input(f"{question} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer in ("y", "yes")


def run(*args: str) -> int:
    return subprocess.run([str(BIN / args[0]), *args[1:]]).returncode


def state() -> Path:
    return Path(os.environ.get("CLAUDE_VOICE_STATE") or Path.home() / ".claude-voice")


def missing(s: setups.Setup) -> list[str]:
    return setups._missing_keys(s)


def chrome() -> bool:
    return any((d / "Google Chrome.app").exists() for d in (Path("/Applications"), Path.home() / "Applications"))


def pick_setup() -> setups.Setup | None:
    """Step 2: the setup in use when its keys are there, else one the saved keys fill, else the one question."""
    try:
        current = setups.chosen(json.loads((state() / "config.json").read_text()))
    except (OSError, ValueError):
        current = None
    if current and (current.local or not missing(current)):
        say(f"Using your {current.name} setup.")
        return current
    filled = [s for s in setups.SETUPS if s.keys and not s.local and not missing(s)]
    if filled:
        s = max(filled, key=lambda s: len(s.keys))
        names = " and ".join(setups.NAMES[k] for k in s.keys)
        say(f"Your {names} {'keys fill' if len(s.keys) > 1 else 'key fills'} the {s.name} setup. Using it.")
        return s
    say(FREE_START)
    if ask("Start with Free start?", default=True):
        return setups.BY_ID[setups.DEFAULT]
    say(f"\n{setups.text_table()}\n\n{setups.BUSY_HOUR}\n")
    while True:
        try:
            choice = input(f"Which setup? ({', '.join(setups.BY_ID)}, or Enter to stop) ").strip()
        except EOFError:
            choice = ""
        if not choice:
            return None
        if choice in setups.BY_ID:
            return setups.BY_ID[choice]


def first_setup(no_open: bool) -> int:
    say("Step 1 of 4: this Mac.")
    if platform.system() != "Darwin":
        say("Pointe's voice needs macOS. On this machine it can run as a node of a Mac: pointe node join (docs/multi-machine.md).")
        return 1
    if not chrome():
        say("Pointe's page needs Google Chrome. Install it from google.com/chrome, then run pointe setup again.")
        return 1
    say("ok       macOS, Chrome")

    say("\nStep 2 of 4: your setup.")
    chosen = pick_setup()
    if chosen is None:
        say("Nothing chosen. pointe setup asks again.")
        return 1
    if chosen.local:  # the two local setups download their models through `pointe local`
        if run("pointe", "setup", chosen.id):
            return 1
    else:
        setups.choose(chosen.id)
        say(f"Setup: {chosen.name}.")

    say("\nStep 3 of 4: your key.")
    for vendor in missing(chosen):
        name = setups.NAMES[vendor]
        if no_open:
            say(f"Save the {name} key: pointe key {vendor} (opens its page and a Mac window; the key goes to your Keychain).")
            continue
        say(f"Opening {name}'s key page in your browser, and a small Mac window. Create a key there, copy it, paste it "
            "in the window and press Save. It goes straight into your Mac's Keychain, never into a file or this terminal.")
        run("pointe", "key", vendor, "--no-restart")
        if vendor in missing(chosen):
            say(f"No {name} key was saved. pointe key {vendor} opens the window again; then pointe setup.")
            return 1
    if missing(chosen):  # --no-open: the windows were not opened, so there is no call to start yet
        say("Then run pointe setup again: it starts your first call.")
        return 0
    say("ok       keys saved" if chosen.keys else "ok       no key needed")
    if chosen.id == "free":
        say("On the free tier: when replies start to fail, the free quota is used up. Turn on billing for the same key.")

    say("\nStep 4 of 4: your first call.")
    say("Starting Pointe (the first start takes up to a minute)...")
    if run("voice-daemon", "ensure"):
        say("Pointe did not start: pointe doctor says why.")
        return 1
    if no_open:
        say("The page: pointe open. Then press Connect and say hello.")
    else:
        run("voice-open")
        say("Put on headphones, allow the microphone, press Connect, and say hello.")
        run("claude-voice-attach", "heard", "180")  # waits for Pointe's answer to the first words: daemon.py writes first-hello
    state().mkdir(parents=True, exist_ok=True)
    (state() / "setup-done").touch()

    say(f"\nDone. Setup: {chosen.name}. pointe doctor shows what runs; pointe stop ends the call; pointe open opens the page.")
    for harness, there in (("codex", shutil.which("codex")), ("opencode", shutil.which("opencode"))):
        if there and ask(f"\n{'Codex' if harness == 'codex' else 'OpenCode'} is on this Mac. Set it up for the voice?", default=True):
            (codex if harness == "codex" else opencode)()
    if not shutil.which("claude"):
        say("\nClaude Code sessions join with /pointe:voice once the Claude Code plugin is installed (docs/install.md).")
    return 0


def rc_file() -> Path | None:
    shell = os.path.basename(os.environ.get("SHELL", ""))
    return {"zsh": Path.home() / ".zshrc", "bash": Path.home() / ".bash_profile"}.get(shell)


def codex() -> int:
    if not shutil.which("codex"):
        say("Codex is not on this Mac. Install it (github.com/openai/codex), then pointe setup codex.")
        return 1
    say("Pointe joins a Codex session through Codex's shared app-server: a codex started with --remote unix:// uses it, "
        "and Pointe can then see and send to the same thread you type in.")
    say("Starting Codex's shared app-server: codex app-server daemon start")
    if subprocess.run(["codex", "app-server", "daemon", "start"]).returncode:
        say("It did not start: run codex app-server daemon start and read what it says.")
        return 1
    rc = rc_file()
    say(f"\nSo every codex uses it, this line makes codex start it and connect (it also starts it after a restart):\n\n  {CODEX_ALIAS}\n")
    if rc is None:
        say("Add it to your shell's startup file yourself.")
    elif RC_MARK in (rc.read_text() if rc.exists() else ""):
        say(f"ok       {rc} has it already")
    elif ask(f"Add it to {rc}?"):
        with rc.open("a") as f:
            f.write(f"\n{RC_MARK}\n{CODEX_ALIAS}\n")
        say(f"ok       added to {rc}. Open a new terminal for it to take effect.")
    else:
        say("Not added. Without it, start Codex as: codex --remote unix:// -C \"$PWD\"")
    say("\nThen, for each Codex session: start codex in the project's folder, and in that folder, in another terminal:"
        "\n\n  pointe join codex\n")
    return 0


def opencode() -> int:
    if not shutil.which("opencode"):
        say("OpenCode is not on this Mac. Install it (opencode.ai), then pointe setup opencode.")
        return 1
    if run("pointe", "join", "opencode", "--install-command"):
        return 1
    say("Then, in an OpenCode session: /voice joins it. Or, in the session's folder: pointe join opencode")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["codex"]:
        return codex()
    if argv[:1] == ["opencode"]:
        return opencode()
    if set(argv) - {"--no-open"}:
        say(__doc__)
        return 2
    return first_setup("--no-open" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
