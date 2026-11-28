"""A port for a server a test starts in another process (a daemon, a node, a fake uv's server).

A port bound to 0 and released was the race: the kernel hands the next socket that binds 0, or connects out, any port
in its ephemeral range, so under xdist another worker's server or client took it between the check and the daemon's own
bind (tests/test_start_race.py: "port 49945 is taken by another process"). These come from below every ephemeral range
(Linux starts at 32768, macOS at 49152), where the kernel never picks one by itself, and each xdist worker draws from a
block of its own. A server in the test's own process binds port 0 and reads its port back instead (page_rig.StubMac).
"""

import os
import random
import socket

LIVE_PORTS = {7860, 7443}  # a Pointe somebody uses: never these
_FIRST, _BLOCK, _BLOCKS = 20000, 600, 20  # 20000 to 31999, under the lowest ephemeral port
_last: int | None = None


def _block_start() -> int:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")[2:]
    return _FIRST + (int(worker) % _BLOCKS if worker.isdigit() else 0) * _BLOCK


def free_port() -> int:
    """A port nothing listens on, the next of this worker's block: one is drawn again only after the block went round.
    Two pytest runs on one machine start at random places in the block, so they meet only by drawing the same port in
    the same moment."""
    global _last
    start = _block_start()
    if _last is None:
        _last = random.randrange(_BLOCK)
    for _ in range(_BLOCK):
        _last = (_last + 1) % _BLOCK
        port = start + _last
        if port in LIVE_PORTS:
            continue
        with socket.socket() as s:
            try:
                s.bind(("0.0.0.0", port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"no free port in {start}..{start + _BLOCK - 1}")
