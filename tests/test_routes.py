"""Several routes to one machine (docs/design/multi-machine-clients.md, 1.2): a route only says where a client opens its
TCP connection; every route ends at the same listener and certificate, so adding one keeps the pin and every pairing.
`pointe pair <method> --add` adds; without it a route replaces the others, as before."""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pointe"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pair import pair  # noqa: E402,F401  (a fixture)


def remote(tmp_path) -> dict:
    return json.loads((tmp_path / "remote.json").read_text())


def test_adding_a_route_keeps_the_certificate_and_the_routes_before_it(pair, tmp_path):
    pair.setup("mac.tail1234.ts.net", "100.64.0.1", kind="tailscale")
    pin = pair.fingerprint()
    pair.setup("kite.example.internal", "127.0.0.1", kind="host", add=True)
    assert pair.fingerprint() == pin, "every pairing stays: the pin is the same certificate"
    got = remote(tmp_path)
    assert got["host"] == "mac.tail1234.ts.net" and got["kind"] == "tailscale", "the first route is still the one lines name"
    assert got["listen"] == ["100.64.0.1", "127.0.0.1"]
    assert [(r["kind"], r["host"]) for r in pair.route_list()] == [("tailscale", "mac.tail1234.ts.net"), ("host", "kite.example.internal")]
    pair.setup("kite.example.internal", "127.0.0.1", kind="host", add=True)
    assert len(pair.route_list()) == 2, "the same route again is not a second one"


def test_without_add_a_route_replaces_the_others_as_before(pair, tmp_path):
    pair.setup("mac.tail1234.ts.net", "100.64.0.1", kind="tailscale")
    pair.setup("kite.example.internal", "127.0.0.1", kind="host", add=True)
    pair.setup("192.168.7.22", "192.168.7.22", kind="wifi")
    assert [r["kind"] for r in pair.route_list()] == ["wifi"] and "routes" not in remote(tmp_path)


def test_a_remote_json_from_before_routes_is_one_route(pair, tmp_path):
    (tmp_path / "remote.json").write_text(json.dumps({"host": "mac.ts.net", "listen": ["100.64.0.1"]}))
    assert pair.route_list() == [{"kind": "host", "host": "mac.ts.net", "listen": ["100.64.0.1"]}]
    assert pair.route_list() and not (tmp_path / "nothing").exists()


def test_a_public_host_and_an_ssh_route(pair, tmp_path):
    pair.main(["host", "pointe.example.com", "--public"])
    assert pair.route_list()[0]["kind"] == "public"
    pair.main(["ssh", "alon@kite.example.com", "--add"])
    ssh = pair.route_list()[-1]
    assert ssh == {"kind": "ssh", "host": "alon@kite.example.com", "listen": ["127.0.0.1"]}, "the tunnel ends on this machine's loopback"
    with pytest.raises(SystemExit):
        pair.main(["ssh", "alon@kite; rm -rf /"])  # a target is a user and a host, nothing a shell would read


def test_the_status_lists_the_routes_and_a_client_line_names_an_ssh_target(pair, tmp_path):
    pair.setup("pointe.example.com", "127.0.0.1", kind="public")
    pair.setup("alon@kite.example.com", "127.0.0.1", kind="ssh", add=True)
    assert pair.routes_status() == [{"kind": "public", "host": "pointe.example.com", "port": pair.TLS_PORT},
                                    {"kind": "ssh", "host": "alon@kite.example.com", "port": pair.TLS_PORT}]
    q = parse_qs(urlparse(pair.invite_pairing_link("ABCD-EFGH")).query)
    assert q["via"] == ["public"] and q["host"] == ["pointe.example.com"]


def test_the_listener_answers_every_route_name_and_no_other(pair, tmp_path):
    from remote import Remote
    pair.setup("mac.tail1234.ts.net", "100.64.0.1", kind="tailscale")
    pair.setup("kite.example.internal", "127.0.0.1", kind="host", add=True)
    r = Remote(tmp_path)
    assert r._own_host({"host": "mac.tail1234.ts.net:7443"}) and r._own_host({"host": "kite.example.internal:7443"})
    assert not r._own_host({"host": "evil.example:7443"}) and not r._own_host({"host": "127.0.0.1:7443"})
    pair.setup("alon@kite.example.com", "127.0.0.1", kind="ssh", add=True)
    assert Remote(tmp_path)._own_host({"host": "127.0.0.1:17443"}), "through a tunnel the name is this machine's loopback"


def test_the_daemons_status_lists_this_machines_routes(tmp_path):
    from test_orchestrator import client_for
    import daemon as d
    (d.STATE_DIR / "remote.json").write_text(json.dumps({"host": "mac.ts.net", "listen": ["100.64.0.1"], "kind": "tailscale"}))
    try:
        got = client_for(d).get("/voice/status").json()["routes"]
        assert got == [{"kind": "tailscale", "host": "mac.ts.net", "port": d.remote.TLS_PORT}]
    finally:
        (d.STATE_DIR / "remote.json").unlink()


def test_a_line_for_an_ssh_route_points_at_the_tunnels_end_and_names_its_target(pair, tmp_path):
    pair.main(["ssh", "alon@kite.example.com"])
    q = parse_qs(urlparse(pair.invite_pairing_link("ABCD-EFGH")).query)
    assert q["host"] == ["127.0.0.1"] and q["ssh"] == ["alon@kite.example.com"] and q["via"] == ["ssh"]
