"""Scans an agent's transcript for any tool input that names a path outside the item repo (design 4.6).

A run with such a read is `invalid_out_of_tree`: excluded from the tables, counted per arm.
"""

import json
import re
from pathlib import Path

URL = re.compile(r"\w+://\S+")
# An absolute or home path: "/" or "~/" then a name that starts with a letter ("/.git/" in a grep pattern is not one).
PATH = re.compile(r"(?<![\w.\-/$}])(?:~/[\w.@+\-]*|/[A-Za-z][\w.@+\-]*)(?:/[\w.@+\-]+)*/?")
ALWAYS = ("/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/usr/bin/", "/bin/")


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def _inside(path: str, roots: list[str]) -> bool:
    return path in ALWAYS or path.startswith(ALWAYS[4:]) or any(path == r or path.startswith(r.rstrip("/") + "/")
                                                               for r in roots)


def tool_inputs(transcripts: list[Path]) -> list[dict]:
    out = []
    for t in transcripts:
        for line in t.read_text(errors="ignore").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            content = (rec.get("message") or {}).get("content")
            if rec.get("type") == "assistant" and isinstance(content, list):
                out += [{"tool": c.get("name"), "input": c.get("input")} for c in content if c.get("type") == "tool_use"]
    return out


def outside(transcripts: list[Path], allowed: list[Path]) -> list[str]:
    """Paths named in tool inputs that are outside every allowed root (the repo; the plugin, for the Pointe arm)."""
    roots = sorted({str(p) for a in allowed for p in (a, a.resolve())})
    roots += [r.replace("/private/tmp/", "/tmp/", 1) for r in roots if r.startswith("/private/tmp/")]
    found = []
    for use in tool_inputs(transcripts):
        for s in _strings(use["input"]):
            for m in PATH.finditer(URL.sub(" ", s)):
                p = m.group(0).rstrip("/") or "/"
                if p in ("/", "~") or len(p) < 3:
                    continue
                if not _inside(p, roots):
                    found.append(f"{use['tool']}: {p}")
    return found
