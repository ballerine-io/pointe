"""`pointe node status` and the doctor say why the hub is unreachable in words, and give no round trip for a link that
is down. QA round 2: "Link: down (cannot reach studio at ...: ClientConnectorError), round trip 1 ms"."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import node  # noqa: E402
import node_cli  # noqa: E402


def test_unreachable_is_said_in_words():
    refused = aiohttp.ClientConnectorError(SimpleNamespace(ssl=None, host="h", port=1), OSError(61, "refused"))
    assert "ClientConnectorError" not in node._unreachable(refused) and "nothing answers" in node._unreachable(refused)
    assert node._unreachable(asyncio.TimeoutError()) == "it did not answer in time"
    assert node._unreachable(ValueError("x")) == "the connection failed"


def test_a_link_that_is_down_shows_no_round_trip(tmp_path, monkeypatch, capsys):
    hub = {"id": "h1", "name": "studio", "host": "studio.example.internal", "port": 7443}
    monkeypatch.setattr(node_cli, "pairing", lambda state: ({"name": "devbox", "hub": hub}, "ab" * 32))
    monkeypatch.setattr(node_cli.nodelink, "fingerprint", lambda key: "fp")
    monkeypatch.setattr(node_cli, "_local", lambda *a: {"node": True, "link": "down", "link_error": "cannot reach studio",
                                                        "rtt_ms": 1, "connected": False})
    node_cli.status(tmp_path, 1)
    out = capsys.readouterr().out
    assert "Link: down (cannot reach studio)" in out and "round trip" not in out
