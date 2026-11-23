"""Nothing committed may hold a home path, a key-shaped string, or an absolute path outside /tmp. `clean()` rewrites the
run's own folders to placeholders; `check()` refuses whatever is left."""

import json
import re
from pathlib import Path

KEY_SHAPES = re.compile(r"sk-ant-[A-Za-z0-9_\-.]{4,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|xi-api-key|"
                        r"Bearer [A-Za-z0-9._\-]{16,}|[0-9a-f]{48}")
HOME = re.compile(r"/Users/[^/\s\"']+|/home/[^/\s\"']+")
ABS = re.compile(r"(?<![\w.:/])/(?!tmp/|private/tmp/)(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-]*")


class Unscrubbed(ValueError):
    pass


def clean(text: str, replacements: dict[str, str]) -> str:
    """Longest path first, so a folder inside another is named by its own placeholder."""
    for path in sorted(replacements, key=len, reverse=True):
        text = text.replace(path, replacements[path])
    return text


def problems(text: str) -> list[str]:
    found = []
    if m := KEY_SHAPES.search(text):
        found.append(f"key-shaped text at {m.start()}")
    if m := HOME.search(text):
        found.append(f"home path at {m.start()}")
    if m := ABS.search(text):
        found.append(f"absolute path outside /tmp: {m.group(0)[:40]}")
    return found


def check(obj) -> None:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    if found := problems(text):
        raise Unscrubbed("; ".join(found))


def check_file(path: Path) -> list[str]:
    return problems(Path(path).read_text(errors="replace"))
