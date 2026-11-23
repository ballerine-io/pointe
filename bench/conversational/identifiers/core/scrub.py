"""Nothing committed may hold a home path, a key-shaped string, or an absolute path outside /tmp (design 4.9)."""

import re

KEY = re.compile(r"(sk-ant-[\w\-]{6,}|sk-[A-Za-z0-9]{20,}|AIza[\w\-]{20,}|xi-api-key|Bearer [\w\-.]{12,})")
HOME = re.compile(r"(/Users/[^\s'\"]+|/home/[^\s'\"]+|~/[^\s'\"]*)")
ABS = re.compile(r"(?<![\w.:/])/(?!tmp/|private/tmp/|dev/null)(?:Users|home|Volumes|opt|var|etc|Library|Applications)/[^\s'\"]*")


def text(s: str) -> str:
    s = KEY.sub("[key removed]", s)
    s = HOME.sub("[path removed]", s)
    return ABS.sub("[path removed]", s)


def problems(s: str) -> list[str]:
    return [m.group(0)[:40] for rx in (KEY, HOME, ABS) for m in rx.finditer(s)]


def check(s: str) -> None:
    found = problems(s)
    if found:
        raise ValueError(f"refused: {len(found)} home path, key or non-/tmp path shapes, first {found[0]!r}")
