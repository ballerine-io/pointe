"""Each conversational benchmark keeps its own harness in bench/conversational/<key>/, and four of them import it by the
same top-level names (core, adapters, run). One pytest process collects all their tests, so a test module enters its
benchmark: that folder goes first on sys.path, and the other benchmarks' modules leave sys.modules while it is collected
and while its tests run (tests/conftest.py enters the module's CONV_SUITE before each test)."""

import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1] / "bench" / "conversational"
KEYS = ("hlk", "identifiers", "actions", "bargein")
NAMES = frozenset({"core", "adapters", "run", *KEYS})
_kept: dict[str, dict] = {}
_active: str | None = None


def _ours(name: str) -> bool:
    return name.split(".", 1)[0] in NAMES


def enter(key: str) -> Path:
    global _active
    assert key in KEYS, key
    if _active != key:
        if _active is not None:
            _kept[_active] = {n: m for n, m in sys.modules.items() if _ours(n)}
        for n in [n for n in sys.modules if _ours(n)]:
            del sys.modules[n]
        sys.modules.update(_kept.get(key, {}))
        _active = key
    folders = {str(BENCH / k) for k in KEYS}
    sys.path[:] = [str(BENCH / key)] + [p for p in sys.path if p not in folders]
    return BENCH / key
