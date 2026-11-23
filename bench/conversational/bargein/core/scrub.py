"""Nothing committed may hold a home path, a key-shaped string, or a path outside /tmp."""

import functools
import getpass
import re
import subprocess
from pathlib import Path

HOME = str(Path.home())
CHECKOUT = str(Path(__file__).resolve().parents[4])


@functools.cache
def owner_names() -> tuple[str, ...]:
    """The machine owner's names, as the daemon or a tool may print them: read at run time, never stored."""
    found = set()
    for cmd in (["git", "config", "user.name"], ["git", "config", "user.email"], ["id", "-F"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        if len(out) >= 3:
            found.add(out)
            found.update(w for w in out.replace("@", " ").split() if len(w) >= 4 and w[0].isupper())
    try:
        found.add(getpass.getuser())
    except Exception:
        pass
    return tuple(sorted(found, key=len, reverse=True))


KEY_SHAPES = re.compile(r"sk-ant-[A-Za-z0-9_\-.]{6,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|xi-api-key|"
                        r"\b[a-f0-9]{48}\b|Bearer [A-Za-z0-9._\-]{12,}")
HOME_SHAPES = re.compile(r"/Users/[^/\s\"']+|/home/[^/\s\"']+")


def clean(text: str) -> str:
    """The text with keys, tokens and home folders replaced; /tmp paths are kept."""
    text = text.replace(CHECKOUT, "<pointe-checkout>").replace(HOME, "~")
    text = KEY_SHAPES.sub("<redacted>", text)
    text = HOME_SHAPES.sub("~", text)
    text = re.sub(r"~/[^\s\"'\\]+", "<home-path>", text)
    for name in owner_names():
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "<owner>", text, flags=re.I)
    return text


def problems(text: str) -> list[str]:
    """Why this text must not be committed; empty when it may."""
    found = []
    if HOME in text or HOME_SHAPES.search(text):
        found.append("home path")
    if KEY_SHAPES.search(text):
        found.append("key-shaped text")
    if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.I) for n in owner_names()):
        found.append("the owner's name")
    return found
