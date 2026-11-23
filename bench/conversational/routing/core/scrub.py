"""Refuses committed text with a home path, a key shape, or a filesystem path outside /tmp."""

import getpass
import re
from pathlib import Path

USER = getpass.getuser()

KEY = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{32,}|AIza[0-9A-Za-z_-]{30,}|xi-api-key|\b[A-Fa-f0-9]{48}\b")
PATH = re.compile(r"(?<![\w.])/(?:Users|home|private/var|var/folders|Volumes)/[^\s'\"]*")


def problems(text: str) -> list[str]:
    found = []
    home = str(Path.home())
    if home in text:
        found.append("home path")
    if len(USER) > 2 and re.search(rf"\b{re.escape(USER)}\b", text):
        found.append("the account name")
    if KEY.search(text):
        found.append("key-shaped text")
    if PATH.search(text):
        found.append(f"non-/tmp path: {PATH.search(text).group(0)[:40]}")
    return found


def clean(text: str, root: Path) -> str:
    """Replaces the checkout path and the home folder with placeholders, before `problems` is asked."""
    text = text.replace(str(root), "<pointe>").replace(str(Path.home()), "~")
    return re.sub(rf"\b{re.escape(USER)}\b", "<user>", text) if len(USER) > 2 else text
