"""bench/fleet's own modules for its tests. Their short names are taken elsewhere (pointe/turns.py,
bench/conversational/*/run.py): an xdist worker that imported one of those first would hand it to `import turns` here,
and these modules put bench/fleet first on sys.path, which would hand ours to the other tests. So they are imported
with none of those names cached, and sys.modules and sys.path are put back afterwards."""

import importlib
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parents[1] / "bench" / "fleet"
NAMES = ("gen", "score", "turns", "sim", "run", "report", "vendors", "dialogue")


def load(*names: str) -> list:
    kept, path = {n: sys.modules.pop(n) for n in NAMES if n in sys.modules}, list(sys.path)
    sys.path[0:0] = [str(FLEET), str(FLEET.parents[1] / "tests")]
    try:
        return [importlib.import_module(n) for n in names]
    finally:
        sys.path[:] = path
        for n in NAMES:
            sys.modules.pop(n, None)
        sys.modules.update(kept)
