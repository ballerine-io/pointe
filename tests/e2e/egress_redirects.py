"""The hosts a download is redirected to are in docs/security/egress-allowlist.txt.

tests/test_supply_chain.py reads URL literals, so it cannot see where Hugging Face and GitHub send a download: those
hosts are chosen on the server side and can change without a change here. This script fetches through a local proxy
that records every CONNECT, from a fresh Hugging Face cache under /tmp: one small file of each pinned repository through
huggingface_hub (the first byte of a file over 50 MB), and the first byte of each pinned release asset. It fails when a
recorded host is not an allowlisted host. Free, no keys, a few MB.

    uv run --locked --extra local python -I tests/e2e/egress_redirects.py
"""

import asyncio
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import assets  # noqa: E402

SMALL = 50 << 20
seen: list[str] = []


def allowlisted() -> set[str]:
    hosts = set()
    for line in (ROOT / "docs" / "security" / "egress-allowlist.txt").read_text().splitlines():
        words = line.split()
        if words and not words[0].startswith("#") and words[0] != "link":
            hosts.add(words[0])
    return hosts


def allowed(host: str, hosts: set[str]) -> bool:
    return host in hosts or any(h.startswith("*.") and host.endswith(h[1:]) for h in hosts)


async def _pipe(r, w):
    try:
        while data := await r.read(1 << 16):
            w.write(data)
            await w.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        w.close()


async def _tunnel(cr, cw):
    request = (await cr.readline()).decode()
    while (await cr.readline()) not in (b"\r\n", b""):
        pass
    host, port = request.split()[1].rsplit(":", 1)
    seen.append(host)
    sr, sw = await asyncio.open_connection(host, int(port))
    cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await cw.drain()
    await asyncio.gather(_pipe(cr, sw), _pipe(sr, cw))


def start_proxy() -> int:
    ready, box = threading.Event(), {}

    async def serve():
        server = await asyncio.start_server(_tunnel, "127.0.0.1", 0)
        box["port"] = server.sockets[0].getsockname()[1]
        ready.set()
        await server.serve_forever()

    threading.Thread(target=lambda: asyncio.run(serve()), daemon=True).start()
    ready.wait(10)
    return box["port"]


def first_byte(url: str) -> None:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=60) as r:
        r.read(1)


def main() -> int:
    port = start_proxy()
    os.environ["HTTPS_PROXY"] = os.environ["https_proxy"] = f"http://127.0.0.1:{port}"
    os.environ.pop("NO_PROXY", None)
    os.environ.pop("no_proxy", None)
    os.environ["HF_HOME"] = cache = tempfile.mkdtemp(prefix="pointe-egress-hf-")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import HfApi, hf_hub_download, hf_hub_url

    try:
        for repo, rev in assets.HF_MODELS.items():
            info = HfApi().model_info(repo, revision=rev, files_metadata=True)
            f = min((s for s in info.siblings if s.lfs), key=lambda s: s.size)
            if f.size <= SMALL:
                hf_hub_download(repo, f.rfilename, revision=rev)
            else:
                first_byte(hf_hub_url(repo, f.rfilename, revision=rev))
        for asset in assets.ASSETS.values():
            first_byte(asset.url)
    finally:
        shutil.rmtree(cache, ignore_errors=True)

    hosts = allowlisted()
    strangers = sorted({h for h in seen if not allowed(h, hosts)})
    for host in sorted(set(seen)):
        print(f"{seen.count(host):4d}  {host}  {'ok' if allowed(host, hosts) else 'NOT ALLOWLISTED'}")
    print(("FAIL" if strangers else "PASS"), " every host a download reached is in docs/security/egress-allowlist.txt")
    return 1 if strangers else 0


if __name__ == "__main__":
    sys.exit(main())
