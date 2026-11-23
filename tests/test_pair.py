import json
import os
import ssl
import stat
import sys
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import d  # noqa: E402,F401


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    import importlib

    import pair as module
    importlib.reload(module)
    return module


@pytest.mark.parametrize("host", ["mac.tail1234.ts.net", "192.168.7.22"])
def test_setup_makes_a_private_certificate_for_that_name(pair, tmp_path, host):
    pair.setup(host, "100.64.0.1")
    for f in ("tls/key.pem", "remote_token", "remote.json"):
        assert stat.S_IMODE(os.stat(tmp_path / f).st_mode) & 0o077 == 0, f
    assert json.loads((tmp_path / "remote.json").read_text()) == {"host": host, "listen": ["100.64.0.1"]}
    context = ssl.create_default_context()
    context.load_verify_locations(tmp_path / "tls" / "cert.pem")  # a valid certificate the app can pin
    assert len(pair.fingerprint()) == 64


def test_the_link_carries_what_the_app_needs(pair, tmp_path):
    pair.setup("mac.tail1234.ts.net", "100.64.0.1")
    query = parse_qs(urlparse(pair.pairing_link()).query)
    from phone import phone_key
    assert urlparse(pair.pairing_link()).scheme == "pointe"
    assert query["host"] == ["mac.tail1234.ts.net"] and query["port"] == ["7443"] and query["v"] == ["1"]
    assert query["fp"] == [pair.fingerprint()] and query["key"] == [phone_key(tmp_path)]


def test_the_link_never_carries_the_daemon_token_or_page_key(pair, tmp_path):
    (tmp_path / "token").write_text("daemon-token-value")
    (tmp_path / "page_key").write_text("page-key-value")
    pair.setup("mac.tail1234.ts.net", "100.64.0.1")
    link = pair.pairing_link()
    assert "daemon-token-value" not in link and "page-key-value" not in link
    assert (tmp_path / "remote_token").read_text() not in link


def test_the_listener_uses_the_paired_address(tmp_path):
    from remote import Remote
    (tmp_path / "remote.json").write_text(json.dumps({"host": "mac.ts.net", "listen": ["100.64.0.1"]}))
    assert Remote(tmp_path).listen == ["100.64.0.1"]
    (tmp_path / "remote.json").write_text(json.dumps({"host": "phone.example.internal"}))
    assert Remote(tmp_path).listen == ["127.0.0.1"]  # a Twingate setup from before stays on loopback


def test_pairing_again_keeps_a_certificate_that_already_covers_the_name(tmp_path, monkeypatch):
    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    pair.setup("pointe.example.internal", "127.0.0.1")
    first = pair.fingerprint()
    pair.setup("pointe.example.internal", "127.0.0.1")
    assert pair.fingerprint() == first  # a browser that trusts it keeps working, and so does the app's pin
    pair.setup("other.example.internal", "127.0.0.1")
    assert pair.fingerprint() != first


def test_the_certificate_is_one_ios_accepts(tmp_path, monkeypatch):
    """iOS App Transport Security refuses a server certificate without serverAuth, pinned or not (-9802 on a real phone)."""
    from cryptography import x509

    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    pair.setup("pointe.example.internal", "127.0.0.1")
    cert = x509.load_pem_x509_certificate((tmp_path / "tls" / "cert.pem").read_bytes())
    usage = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in usage
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days <= 825  # Apple's limit for any TLS server certificate


# ---------- machines: the invite, and the browser link `bin/voice-remote` used to print ----------

def test_the_invite_line_round_trips_to_what_the_node_needs(pair, tmp_path):
    import nodelink

    pair.setup("studio.tail1234.ts.net", "100.64.0.1")
    line = pair.invite_link("K7PQ-2MXD")
    assert line.startswith("pointe://hub?")
    assert nodelink.parse_invite(line) == {"host": "studio.tail1234.ts.net", "port": 7443, "fp": pair.fingerprint(),
                                           "code": "K7PQ-2MXD"}
    assert (tmp_path / "remote_token").read_text() not in line and "key=" not in line  # nothing but the one-time code


@pytest.mark.parametrize("bad", ["https://hub?v=1", "pointe://pair?v=1&host=h&port=1&fp=" + "a" * 64 + "&code=X",
                                 "pointe://hub?v=2&host=h&port=7443&fp=" + "a" * 64 + "&code=K7PQ-2MXD",
                                 "pointe://hub?v=1&host=h&port=x&fp=" + "a" * 64 + "&code=K7PQ-2MXD",
                                 "pointe://hub?v=1&host=h&port=7443&fp=short&code=K7PQ-2MXD",
                                 "pointe://hub?v=1&port=7443&fp=" + "a" * 64 + "&code=K7PQ-2MXD"])
def test_a_line_that_is_not_an_invite_is_refused(bad):
    import nodelink

    with pytest.raises(ValueError):
        nodelink.parse_invite(bad)


def test_an_invite_needs_a_paired_address_first(pair):
    with pytest.raises(SystemExit, match="pointe pair tailscale"):
        pair.invite_link("K7PQ-2MXD")


def test_link_prints_the_browser_pairing_address(pair, tmp_path, capsys):
    pair.setup("pointe.example.internal", "127.0.0.1")
    pair.main(["link"])
    out = capsys.readouterr().out
    assert f"https://pointe.example.internal:7443/voice?pair={(tmp_path / 'remote_token').read_text()}" in out


def test_off_removes_the_listener_and_keeps_the_connector(pair, tmp_path, capsys):
    pair.setup("pointe.example.internal", "127.0.0.1")
    (tmp_path / "connector.json").write_text("{}")
    pair.main(["off"])
    assert not any((tmp_path / f).exists() for f in ("tls", "remote.json", "remote_token"))
    assert (tmp_path / "connector.json").exists() and "connector" in capsys.readouterr().out
    pair.main(["off"])  # twice is fine


def test_rotate_forces_a_new_certificate_and_says_who_must_pair_again(pair, tmp_path, capsys):
    pair.setup("pointe.example.internal", "127.0.0.1")
    first = pair.fingerprint()
    capsys.readouterr()
    pair.main(["rotate"])
    out = capsys.readouterr().out
    assert pair.fingerprint() != first and "phone" in out and "node" in out
    assert json.loads((tmp_path / "remote.json").read_text())["host"] == "pointe.example.internal"


def test_rotate_needs_a_paired_address(pair):
    with pytest.raises(SystemExit, match="pointe pair"):
        pair.main(["rotate"])


@pytest.mark.parametrize("name,refused", [("devbox", False), ("dev", True), ("main", True), ("shop", True),
                                          ("billing box", True), ("studio", True), ("laptop", True), ("", True)])
def test_node_names_must_be_speakable_and_apart_from_every_session_and_machine(name, refused):
    import hub_nodes
    from sessions import Session

    sessions = [Session(id="a", name="shop/main", cwd="/x"), Session(id="b", name="billing", cwd="/y")]
    problem = hub_nodes.name_problem(name, taken=["laptop"], sessions=sessions, hub_name="studio")
    assert (problem is not None) is refused


def test_the_pairing_result_carries_the_fingerprint_and_source_address(tmp_path):
    import hub_nodes
    import nodelink
    from sessions import Registry

    hub = hub_nodes.Hub(tmp_path, Registry(), SimpleNamespace())
    status, body = hub.pair({"code": hub.invites.make(), "name": "devbox", "os": "linux"}, "100.101.5.7")
    assert status == 200
    assert hub.invites.paired["key_fp"] == nodelink.fingerprint(body["node_key"])
    assert hub.invites.paired["address"] == "100.101.5.7" and hub.invites.paired["network"] == "Tailscale"
    assert hub_nodes.paired_line(hub.invites.paired).startswith("devbox paired from 100.101.5.7 (Tailscale), key ")


# ---------- rotate and off revoke every credential the listener honours, in a running daemon too ----------

def _everyone_paired(pair, tmp_path):
    """A browser pairing secret, the shared phone key, a phone paired from the page and a machine: each held in memory
    by a daemon that was already running."""
    import hub_nodes
    import phone_pairing

    pair.setup("pointe.example.internal", "127.0.0.1")
    (tmp_path / "phone_key").write_text("shared-phone-key")
    phones = phone_pairing.Phones(tmp_path)
    phone = phones.mint("Test iPhone", "device-1", "100.64.0.9")
    nodes = hub_nodes.NodesRegistry(tmp_path / "nodes.json")
    node = nodes.add("devbox", "linux")
    import remote
    listener = remote.Remote(tmp_path)
    assert phones.allowed(f"Bearer {phone}") and phones.allowed("Bearer shared-phone-key") == phone_pairing.LEGACY
    assert nodes.get(node["id"]) and listener.token == (tmp_path / "remote_token").read_text()
    return phones, phone, nodes, node, listener


def _nothing_honoured(tmp_path, phones, phone, nodes, node, old_token):
    import hub_nodes
    import phone_pairing

    assert phones.allowed(f"Bearer {phone}") is None and phones.allowed("Bearer shared-phone-key") is None
    assert phones.status() == {"paired": []}
    assert nodes.get(node["id"]) is None and nodes.by_name("devbox") is None
    assert phone_pairing.Phones(tmp_path).paired == [] and not (tmp_path / "phone_key").exists()
    assert hub_nodes.NodesRegistry(tmp_path / "nodes.json").nodes == {}
    token = tmp_path / "remote_token"
    assert not token.exists() or token.read_text().strip() != old_token


@pytest.mark.parametrize("command", ["rotate", "off"])
def test_rotate_and_off_revoke_every_phone_browser_and_machine_in_the_running_daemon_too(pair, tmp_path, capsys, command):
    phones, phone, nodes, node, listener = _everyone_paired(pair, tmp_path)
    hub_id, old_token = nodes.hub_id, listener.token
    capsys.readouterr()
    pair.main([command])
    _nothing_honoured(tmp_path, phones, phone, nodes, node, old_token)
    assert nodes.hub_id == hub_id  # the hub stays the same hub: a machine pairs again with a new code, nothing else
    assert listener.changed()  # the daemon's watch restarts the listener on what is on disk now
    out = capsys.readouterr().out
    assert "phone" in out and "machine" in out


def test_after_rotate_a_new_pairing_does_not_bring_the_old_ones_back(pair, tmp_path):
    phones, phone, nodes, node, _ = _everyone_paired(pair, tmp_path)
    pair.main(["rotate"])
    fresh = phones.mint("Other iPhone", "device-2", "100.64.0.9")
    again = nodes.add("laptop", "macos")
    assert phones.allowed(f"Bearer {phone}") is None and phones.allowed(f"Bearer {fresh}")
    assert nodes.get(node["id"]) is None and nodes.get(again["id"])
    import hub_nodes
    import phone_pairing
    assert [p["name"] for p in phone_pairing.Phones(tmp_path).paired] == ["Other iPhone"]
    assert list(hub_nodes.NodesRegistry(tmp_path / "nodes.json").nodes) == [again["id"]]


def test_rotate_gives_the_browser_a_new_pairing_link(pair, tmp_path, capsys):
    pair.setup("pointe.example.internal", "127.0.0.1")
    old = (tmp_path / "remote_token").read_text()
    pair.main(["rotate"])
    capsys.readouterr()
    pair.main(["link"])
    assert old not in capsys.readouterr().out


def test_the_running_daemon_restarts_the_listener_and_ends_a_signed_out_phones_call(d, monkeypatch):
    """Its liveness loop, every few seconds: a listener restarted on what is on disk (a new certificate, or none), and a
    call held by a phone that is no longer paired ends, as Unpair on the page ends it."""
    import asyncio

    daemon = d
    restarted, closed = [], []

    class Listener:
        def changed(self):
            return True

        async def restart(self, only_if_changed=False):
            restarted.append(only_if_changed)

    class Socket:
        async def close(self, code, reason):
            closed.append(code)

    async def drop_unpaired():
        return None

    monkeypatch.setattr(daemon, "REMOTE", Listener())
    monkeypatch.setattr(daemon.HUB, "drop_unpaired", drop_unpaired)
    monkeypatch.setattr(daemon.PHONES, "holds", lambda phone_id: phone_id != "gone")
    daemon.state.phone_socket, daemon.state.phone_socket_id = Socket(), "kept"
    asyncio.run(daemon._follow_pairing())
    assert restarted == [True] and closed == []
    daemon.state.phone_socket_id = "gone"
    asyncio.run(daemon._follow_pairing())
    assert closed == [4401]
