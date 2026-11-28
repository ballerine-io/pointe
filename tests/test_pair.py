import json
import os
import ssl
import stat
import sys
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parent.parent / "pointe"), str(Path(__file__).resolve().parent.parent)]
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


def test_link_prints_the_browser_pairing_address(pair, tmp_path, capsys, monkeypatch):
    pair.setup("pointe.example.internal", "127.0.0.1")
    monkeypatch.setattr(pair, "_to_terminal", lambda: True)  # a person's terminal
    pair.main(["link"])
    out = capsys.readouterr().out
    assert f"https://pointe.example.internal:7443/voice?pair={(tmp_path / 'remote_token').read_text()}" in out


def test_show_says_to_scan_inside_the_app_never_with_the_camera(pair, tmp_path, capsys, monkeypatch):
    """The terminal's code holds the phone's lasting key, and a pointe:// link the Camera opens can reach another app."""
    pair.setup("pointe.example.internal", "127.0.0.1")
    monkeypatch.setattr(pair.subprocess, "run", lambda *a, **k: None)  # no picture opens
    pair.main(["show"])
    out = capsys.readouterr().out
    assert "inside the Pointe app" in out and "not with the Camera" in out and "lasting key" in out


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


@pytest.mark.parametrize("command", ["rotate", "off"])
def test_rotate_and_off_delete_every_persons_key_and_say_how_many_must_be_invited_again(pair, tmp_path, capsys, command):
    import guests

    pair.setup("pointe.example.internal", "127.0.0.1")
    people = guests.People(tmp_path / "people.json")  # held in memory by a daemon that was already running
    dana = people.add("Dana", "send", "100.64.0.7", ["Anthropic"], 5.0)
    people.add("Erin", "watch", "100.64.0.8", [], 6.0)
    people.set_private("s1", True, {"s1"})
    capsys.readouterr()
    pair.main([command])
    assert people.get(dana["id"]) is None and people.by_name("Erin") is None
    on_disk = json.loads((tmp_path / "people.json").read_text())
    assert on_disk == {"people": {}, "private": ["s1"]} and dana["key"] not in (tmp_path / "people.json").read_text()
    assert people.private == {"s1"}  # what the owner keeps private stays private
    assert "2 people invited to this machine must be invited again (Dana, Erin): pointe people invite" in capsys.readouterr().out
    pair.main([command]) if command == "off" else pair.main(["rotate"])
    assert "invited again" not in capsys.readouterr().out  # nobody is left to say it of



@pytest.mark.parametrize("add", [False, True])
def test_choosing_another_route_signs_no_person_out(pair, tmp_path, add):
    """SECURITY.md: a new route chosen with `pointe pair tailscale`, `wifi` or `host` does not sign people out; only
    rotate and off do. Their keys stay on disk and in the running daemon's list, whether the route replaces the old
    one or is added beside it."""
    import guests

    pair.setup("pointe.example.internal", "127.0.0.1")
    people = guests.People(tmp_path / "people.json")
    dana = people.add("Dana", "send", "100.64.0.7", ["Anthropic"], 5.0)
    before = (tmp_path / "people.json").read_text()
    pair.setup("studio.tail0000.ts.net", "127.0.0.1", kind="tailscale", add=add)
    assert people.get(dana["id"])["key"] == dana["key"]
    assert (tmp_path / "people.json").read_text() == before

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


def test_rotate_gives_the_browser_a_new_pairing_link(pair, tmp_path, capsys, monkeypatch):
    pair.setup("pointe.example.internal", "127.0.0.1")
    old = (tmp_path / "remote_token").read_text()
    pair.main(["rotate"])
    capsys.readouterr()
    monkeypatch.setattr(pair, "_to_terminal", lambda: True)
    pair.main(["link"])
    out = capsys.readouterr().out
    assert old not in out and (tmp_path / "remote_token").read_text() in out


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


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_no_secret_is_printed_where_an_agent_reads_the_output(pair, tmp_path, capsys, monkeypatch, platform):
    """/pointe:setup phone has the agent run these: its Bash output goes into the session transcript. Under a pipe the
    lasting phone key and the browser pairing secret only reach a picture opened on the Mac, never stdout."""
    opened = []
    monkeypatch.setattr(pair.subprocess, "run", lambda argv, **k: opened.append(argv))  # no picture opens
    monkeypatch.setattr(pair.sys, "platform", platform)
    pair.main(["host", "pointe.example.internal"])
    pair.main(["show"])
    pair.main(["link"])
    got = capsys.readouterr()
    out = got.out + got.err
    token, key = (tmp_path / "remote_token").read_text().strip(), (tmp_path / "phone_key").read_text().strip()
    assert token not in out and key not in out and "pair=" not in out and "key=" not in out
    assert not set("█▀▄") & set(out)  # no terminal QR code: it is the phone key, drawn
    assert pair.fingerprint()[:16] in out  # what to compare stays
    if platform == "darwin":
        assert [a[0] for a in opened] == ["open"] * 3
        for picture in {Path(a[1]) for a in opened}:
            assert stat.S_IMODE(picture.stat().st_mode) == 0o600
    else:
        assert not opened and "terminal" in out
