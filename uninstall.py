"""pointe uninstall: remove what installing and using Pointe added to this Mac, after showing the list and asking.

    pointe uninstall                  show what is there, ask, remove
    pointe uninstall --dry-run        show it only
    pointe uninstall --yes            remove Pointe's own files and the plugin without asking
    pointe uninstall --delete-keys    also Pointe's keys in the Keychain (never without this or a yes to its own question)

Three groups, each with its own question: Pointe's own files and the plugin; Pointe's keys in the Keychain; and things
another tool may share (the Keychain items under the plain names Pointe used before 1.20.0, and the model downloads in the
shared Hugging Face cache). uv stays: other tools use it. Standard library only, so it runs whatever state the plugin's
Python is in. docs/install.md, "What this does to your Mac", is the same list.
"""
from __future__ import annotations  # macOS's own python3 (3.9) runs this: `bin/pointe uninstall` needs no uv

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINK_MARK = "# Written by Pointe (bin/link-pointe)"
KEY_VENDORS = ("gemini", "openai", "anthropic", "soniox", "elevenlabs")  # vendors.KEYS (tests/test_uninstall.py)
MAC_APP_ID = "io.ballerine.pointe.mac"  # macos/tools/make_project.py, PRODUCT_BUNDLE_IDENTIFIER (tests/test_uninstall.py)


@dataclass
class Item:
    what: str
    path: Path | None = None  # a file or folder to delete
    keychain: str = ""  # a Keychain item to delete
    command: tuple = ()  # a command to run


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
    """Asked by name only: no secret is read or printed."""
    try:
        return subprocess.run(["security", "find-generic-password", "-s", name], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _hf_models() -> list[str]:
    text = (ROOT / "assets.py").read_text()
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
    prefs = home() / "Library" / "Preferences" / f"{MAC_APP_ID}.plist"
    if prefs.exists() and shutil.which("defaults"):  # through defaults: macOS caches a domain, and a deleted file comes back
        own.append(Item(f"{prefs} (the Mac app's settings)", command=(shutil.which("defaults"), "delete", MAC_APP_ID)))
    kokoro = home() / ".cache" / "pipecat" / "kokoro-onnx"
    if kokoro.exists():
        own.append(Item(f"{kokoro} ({_size(kokoro)}: the local voice)", path=kokoro))
    claude = _claude()
    if claude:
        own.append(Item("The Claude Code plugin pointe@pointe, with its two hooks and its Python (claude plugin uninstall)",
                        command=(claude, "plugin", "uninstall", "pointe@pointe")))
        own.append(Item("The plugin's marketplace, pointe (claude plugin marketplace remove)",
                        command=(claude, "plugin", "marketplace", "remove", "pointe")))
    keys = [Item(f"Keychain item pointe.{v}-api-key", keychain=f"pointe.{v}-api-key") for v in KEY_VENDORS
            if _in_keychain(f"pointe.{v}-api-key")]
    shared = [Item(f"Keychain item {v}-api-key (Pointe's name before 1.20.0; another tool may use the same name)",
                   keychain=f"{v}-api-key") for v in KEY_VENDORS if _in_keychain(f"{v}-api-key")]
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
        if item.keychain:
            got = subprocess.run(["security", "delete-generic-password", "-s", item.keychain], capture_output=True, timeout=10)
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
    titles = {"own": "Pointe's own files, and the plugin", "keys": "Pointe's keys in the Keychain",
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
    if groups["own"] and ("--yes" in argv or _ask("Remove Pointe's own files and the plugin?")):
        chosen += groups["own"]
    if groups["keys"] and ("--delete-keys" in argv or (interactive and _ask("Delete Pointe's keys from the Keychain?"))):
        chosen += groups["keys"]
    if groups["shared"] and interactive and _ask("Also remove the shared items listed above?"):
        chosen += groups["shared"]
    if not chosen:
        print("Nothing removed.")
        return 0
    plugin = [i for i in chosen if i.command and "plugin" in i.command]  # last: it deletes the code running this
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
