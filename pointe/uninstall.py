"""pointe uninstall: remove what installing and using Pointe added to this Mac, after showing the list and asking.

    pointe uninstall                  show what is there, ask, remove
    pointe uninstall --dry-run        show it only
    pointe uninstall --yes            remove Pointe's own files, the plugin and the standalone install without asking
    pointe uninstall --delete-keys    also Pointe's keys in the Keychain (never without this or a yes to its own question)

Three groups, each with its own question: Pointe's own files, the plugin and the standalone install (~/.pointe); Pointe's keys in the Keychain; and things
another tool may share (the Keychain items under the plain names pre-release builds of Pointe used, and the model downloads in the
shared Hugging Face cache). uv stays: other tools use it. Standard library only, so it runs whatever state the plugin's
Python is in. docs/install.md, "What this does to your Mac", is the same list.
"""
from __future__ import annotations  # macOS's own python3 (3.9) runs this: `bin/pointe uninstall` needs no uv

import os
import plistlib
import pwd
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the checkout
LINK_MARK = "# Written by Pointe (bin/link-pointe)"
RC_MARK = "# Pointe: codex runs on Codex's shared app-server"  # terminal_setup.RC_MARK starts so (tests/test_install.py)
KEY_VENDORS = ("gemini", "openai", "anthropic", "soniox", "elevenlabs")  # vendors.KEYS (tests/test_uninstall.py)
MAC_APP_ID = "io.ballerine.pointe.mac"  # apps/macos/tools/make_project.py, PRODUCT_BUNDLE_IDENTIFIER (tests/test_uninstall.py)


@dataclass
class Item:
    what: str
    path: Path | None = None  # a file or folder to delete
    keychain: str = ""  # a Keychain item to delete
    command: tuple = ()  # a command to run
    rc: Path | None = None  # a shell startup file to take Pointe's codex alias out of


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def state() -> Path:
    return Path(os.environ.get("CLAUDE_VOICE_STATE") or home() / ".claude-voice")


def _size(path: Path) -> str:
    total = 0
    for p in [path, *path.rglob("*")] if path.is_dir() else [path]:
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return f"{total / 1e9:.1f} GB" if total >= 1e9 else f"{total / 1e6:.0f} MB" if total >= 1e6 else f"{total / 1e3:.0f} KB"


def _in_keychain(name: str) -> bool:
    """Asked by name only: no secret is printed. On Linux, the login keyring through the Secret Service (secret-tool
    has no lookup by name that leaves the value out: it is read into this process and dropped)."""
    command = (["security", "find-generic-password", "-s", name] if sys.platform == "darwin"
               else ["secret-tool", "lookup", "service", name])
    try:
        return subprocess.run(command, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _hf_models() -> list[str]:
    text = (ROOT / "pointe" / "assets.py").read_text()
    block = text[text.index("HF_MODELS = {"):]
    return re.findall(r'^\s+"([^"]+/[^"]+)":', block[:block.index("\n}")], re.M)


def _claude() -> str | None:
    """The claude CLI: on the PATH, else where Claude Code's own installers put it. A desktop-app install or a shell
    alias has none on the PATH, and the plugin was then never listed, yet "Pointe is removed" was said."""
    found = shutil.which("claude")
    if found:
        return found
    for path in (home() / ".claude" / "local" / "claude", home() / ".local" / "bin" / "claude"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def system_apps() -> Path | None:
    """Where the disk image's Pointe.app is dragged: /Applications, outside the home folder, so only for this account's
    real home (a test's throwaway HOME never reaches it). POINTE_SYSTEM_APPLICATIONS names another folder (tests)."""
    if os.environ.get("POINTE_SYSTEM_APPLICATIONS"):
        return Path(os.environ["POINTE_SYSTEM_APPLICATIONS"])
    return Path("/Applications") if home() == Path(pwd.getpwuid(os.getuid()).pw_dir) else None


def _ours(app: Path) -> bool:
    """A Pointe.app in /Applications is removed only when it is this one: another app may have the same name."""
    try:
        return plistlib.loads((app / "Contents" / "Info.plist").read_bytes()).get("CFBundleIdentifier") == MAC_APP_ID
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def pointe_home() -> Path:
    return Path(os.environ.get("POINTE_HOME") or home() / ".pointe")


def _rc_files() -> list[Path]:
    found = []
    for rc in (home() / ".zshrc", home() / ".bash_profile", home() / ".bashrc"):
        try:
            if RC_MARK in rc.read_text(errors="replace"):
                found.append(rc)
        except OSError:
            pass
    return found


def _without_alias(text: str) -> str:
    """The file without the two lines `pointe setup codex` added: the mark and the alias under it."""
    lines, out, skip = text.splitlines(keepends=True), [], False
    for line in lines:
        if line.startswith(RC_MARK):
            skip = True
            if out and out[-1].strip() == "":
                out.pop()  # the blank line written before the mark
            continue
        if skip and line.startswith("alias codex="):
            skip = False
            continue
        skip = False
        out.append(line)
    return "".join(out)


def plugin_left() -> bool:
    """The plugin is installed and no claude CLI can remove it here."""
    return _claude() is None and ((home() / ".claude" / "plugins" / "cache" / "pointe").exists()
                                  or "/.claude/plugins/" in str(ROOT))


PLUGIN_BY_HAND = ("The Claude Code plugin is still installed, with its two hooks and its Python: no claude command was "
                  "found. In Claude Code, run /plugin uninstall pointe@pointe, then /plugin marketplace remove pointe.")


def plan() -> dict[str, list[Item]]:
    own: list[Item] = [Item("Stop Pointe (the voice daemon and, in fully local mode, its text model)",
                            command=(str(ROOT / "bin" / "voice-daemon"), "stop"))]
    link = home() / ".local" / "bin" / "pointe"
    try:
        if LINK_MARK in link.read_text(errors="replace"):
            own.append(Item(f"{link} (the pointe command)", path=link))
    except OSError:
        pass
    if state().exists():
        own.append(Item(f"{state()} ({_size(state())}: settings, call journal, phone pairings, voiceprint, logs)",
                        path=state()))
    app = home() / "Applications" / "Pointe.app"
    if app.exists():
        own.append(Item(f"{app} (the Mac app)", path=app))
    app = system_apps() / "Pointe.app" if system_apps() else None
    if app and _ours(app):
        own.append(Item(f"{app} (the Mac app, from Pointe.dmg)", path=app))
    prefs = home() / "Library" / "Preferences" / f"{MAC_APP_ID}.plist"
    if prefs.exists() and shutil.which("defaults"):  # through defaults: macOS caches a domain, and a deleted file comes back
        own.append(Item(f"{prefs} (the Mac app's settings)", command=(shutil.which("defaults"), "delete", MAC_APP_ID)))
    opencode = home() / ".config" / "opencode" / "plugins" / "pointe-voice.ts"
    if opencode.exists():
        own.append(Item(f"{opencode} (/voice in OpenCode)", path=opencode))
    for rc in _rc_files():
        own.append(Item(f"The codex alias in {rc} (two lines, from pointe setup codex)", rc=rc))
    kokoro = home() / ".cache" / "pipecat" / "kokoro-onnx"
    if kokoro.exists():
        own.append(Item(f"{kokoro} ({_size(kokoro)}: the local voice)", path=kokoro))
    if pointe_home().exists():
        own.append(Item(f"{pointe_home()} ({_size(pointe_home())}: the standalone install, with its Python)",
                        path=pointe_home()))
    claude = _claude()
    if claude:
        own.append(Item("The Claude Code plugin pointe@pointe, with its two hooks and its Python (claude plugin uninstall)",
                        command=(claude, "plugin", "uninstall", "pointe@pointe")))
        own.append(Item("The plugin's marketplace, pointe (claude plugin marketplace remove)",
                        command=(claude, "plugin", "marketplace", "remove", "pointe")))
    store = "Keychain item" if sys.platform == "darwin" else "Keyring item"
    keys = [Item(f"{store} pointe.{v}-api-key", keychain=f"pointe.{v}-api-key") for v in KEY_VENDORS
            if _in_keychain(f"pointe.{v}-api-key")]
    shared = [Item(f"Keychain item {v}-api-key (the name pre-release builds of Pointe used; another tool may use the same name)",
                   keychain=f"{v}-api-key") for v in KEY_VENDORS
              if sys.platform == "darwin" and _in_keychain(f"{v}-api-key")]  # no pre-release build ran on Linux
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or home() / ".cache" / "huggingface") / "hub")
    for repo in _hf_models():
        folder = hub / f"models--{repo.replace('/', '--')}"
        if folder.exists():
            shared.append(Item(f"{folder} ({_size(folder)}: a model Pointe downloaded; another app may use it)", path=folder))
    return {"own": own, "keys": keys, "shared": shared}


def _ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def remove(item: Item) -> str:
    try:
        if item.command:
            got = subprocess.run(list(item.command), capture_output=True, text=True, timeout=120)
            return "done" if got.returncode == 0 else f"failed: {(got.stderr or got.stdout).strip()[:200]}"
        if item.rc:
            item.rc.write_text(_without_alias(item.rc.read_text()))
            return "done"
        if item.keychain:
            command = (["security", "delete-generic-password", "-s", item.keychain] if sys.platform == "darwin"
                       else ["secret-tool", "clear", "service", item.keychain])
            got = subprocess.run(command, capture_output=True, timeout=10)
            return "done" if got.returncode == 0 else "not found"
        if item.path.is_dir() and not item.path.is_symlink():
            shutil.rmtree(item.path)
        else:
            item.path.unlink()
        return "done"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"failed: {type(e).__name__}"


def main(argv: list[str]) -> int:
    known = {"--dry-run", "--yes", "--delete-keys"}
    if not set(argv) <= known:
        print("usage: pointe uninstall [--dry-run] [--yes] [--delete-keys]")
        return 2
    groups = plan()
    titles = {"own": "Pointe's own files, the plugin and the standalone install", "keys": "Pointe's keys in the Keychain",
              "shared": "Things another tool may share (asked separately; kept unless you say yes)"}
    print("Pointe added these to this Mac:\n")
    for name, items in groups.items():
        if items:
            print(f"{titles[name]}:")
            print("\n".join(f"  - {i.what}" for i in items) + "\n")
    if plugin_left():
        print(f"{PLUGIN_BY_HAND}\n")
    print("Kept: uv, which other tools use (remove it with: uv cache clean, then rm -r ~/.local/bin/uv ~/.local/bin/uvx "
          "~/.local/share/uv).\n")
    if "--dry-run" in argv:
        print("Dry run: nothing removed.")
        return 0
    interactive = sys.stdin.isatty()
    if not interactive and "--yes" not in argv:
        print("Nothing removed: run pointe uninstall in a terminal to answer, or pass --yes.")
        return 1
    chosen = []
    if groups["own"] and ("--yes" in argv or _ask("Remove Pointe's own files, the plugin and the standalone install?")):
        chosen += groups["own"]
    if groups["keys"] and ("--delete-keys" in argv or (interactive and _ask("Delete Pointe's keys from the Keychain?"))):
        chosen += groups["keys"]
    if groups["shared"] and interactive and _ask("Also remove the shared items listed above?"):
        chosen += groups["shared"]
    if not chosen:
        print("Nothing removed.")
        return 0
    # last: the plugin and the standalone install hold the code running this
    plugin = [i for i in chosen if (i.command and "plugin" in i.command) or i.path == pointe_home()]
    failed = 0
    for item in [i for i in chosen if i not in plugin] + plugin:
        result = remove(item)
        failed += result.startswith("failed")
        print(f"  {result:9} {item.what}")
    if failed:
        print("\nSome items were not removed: see above.")
    elif plugin_left():
        print(f"\nRemoved what you chose. {PLUGIN_BY_HAND}")
    elif groups["own"] and not set(map(id, groups["own"])) <= set(map(id, chosen)):
        print("\nRemoved what you chose. Pointe itself is still installed: pointe uninstall again removes it.")
    else:
        print("\nPointe is removed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
