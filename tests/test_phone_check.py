"""The Mac's check of the phone's route (phone_check.py): before the page or the Mac app shows a pairing code, and in
`pointe doctor`. Every probe here goes to a listener this test starts on a free port: never the live 7443."""

import json
import re
import socket
import ssl
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import phone_check  # noqa: E402

NAME = "pointe.example.internal"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A state dir with a certificate made by `pointe pair host`, listening on loopback."""
    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    pair.setup(NAME, "127.0.0.1")
    return tmp_path


class Listener:
    """A TLS server with the state dir's certificate (or another), on 127.0.0.1 and a free port."""

    def __init__(self, cert: Path, key: Path, silent: bool = False):
        self.port, self.silent = free_port(), silent
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.listen(8)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.held = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            if self.silent:  # accepts, never answers the handshake: a connector that takes the connection and stalls
                self.held.append(conn)
                continue
            try:
                with self.context.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except (OSError, ssl.SSLError):
                pass

    def close(self):
        self.sock.close()
        for c in self.held:
            c.close()


@pytest.fixture
def listener(state):
    made = []

    def start(silent=False, other=None):
        tls = (other or state) / "tls"
        one = Listener(tls / "cert.pem", tls / "key.pem", silent=silent)
        made.append(one)
        return one
    yield start
    for one in made:
        one.close()


@pytest.fixture
def other_cert(tmp_path_factory, monkeypatch):
    import pair

    elsewhere = tmp_path_factory.mktemp("other")
    monkeypatch.setattr(pair, "STATE", elsewhere)
    pair._certificate(NAME)
    return elsewhere


def resolves(monkeypatch, table: dict):
    real = phone_check._resolve
    monkeypatch.setattr(phone_check, "_resolve", lambda host: table[host] if host in table else real(host))


# ---------- how the phone reaches the Mac ----------

@pytest.mark.parametrize("host,kind", [
    ("192.168.1.20", "wifi"), ("10.0.0.7", "wifi"), ("172.20.1.4", "wifi"), ("127.0.0.1", "wifi"),
    ("100.101.102.103", "tailscale"), ("studio.tail1234.ts.net", "tailscale"), ("Studio.Tail1234.TS.net.", "tailscale"),
    ("pointe.example.internal", "name"), ("mac.corp.example", "name"), ("100.example.com", "name"),
])
def test_the_route_is_read_from_the_address_as_pointe_pair_writes_it(host, kind):
    assert phone_check.route_kind(host) == kind


# ---------- one handshake ----------

def test_the_probe_knows_this_macs_listener_by_its_certificate(state, listener):
    import pair
    port = listener().port
    assert phone_check.probe("127.0.0.1", port, pair.fingerprint()) == "ok"


def test_the_probe_tells_another_certificate_from_this_macs(state, listener, other_cert):
    import pair
    pair.STATE = state
    port = listener(other=other_cert).port
    assert phone_check.probe("127.0.0.1", port, pair.fingerprint()) == "other_certificate"


def test_the_probe_tells_nothing_listening_from_no_answer_from_no_name(state, listener, monkeypatch):
    import pair
    fp = pair.fingerprint()
    assert phone_check.probe("127.0.0.1", free_port(), fp) == "refused"
    stall = listener(silent=True).port
    assert phone_check.probe("127.0.0.1", stall, fp, timeout=0.3) == "no_answer"
    resolves(monkeypatch, {NAME: []})
    assert phone_check.probe(NAME, stall, fp) == "no_name"
    assert phone_check.probe("nowhere.invalid", stall, fp) == "no_name", "a reserved name never resolves"


# ---------- the check, and its words ----------

def scripted(monkeypatch, answers: dict):
    """What each address answers, instead of a handshake: (host) -> a probe result."""
    seen = []

    def probe(host, port, fingerprint, timeout=phone_check.TIMEOUT):
        seen.append(host)
        return answers[host]
    monkeypatch.setattr(phone_check, "probe", probe)
    return seen


def test_a_name_that_reaches_this_macs_listener_passes_end_to_end(state, listener, monkeypatch):
    port = listener().port
    resolves(monkeypatch, {NAME: ["127.0.0.1"]})
    found = phone_check.check(state, port)
    assert found["ok"] is True and found["kind"] == "name" and found["host"] == NAME
    assert found["said"] == f"{NAME} reaches this Mac's Pointe." and found["fix"] is None


@pytest.mark.parametrize("answer", ["no_answer", "refused"])
def test_a_name_whose_connector_is_down_says_so_with_the_connector_hint(state, monkeypatch, answer):
    """The owner's morning: the Twingate connector (Docker on Colima) stopped after a reboot. Pointe's listener answers
    on loopback, and the name does not reach it."""
    seen = scripted(monkeypatch, {"127.0.0.1": "ok", NAME: answer})
    found = phone_check.check(state, 7443)
    assert seen == ["127.0.0.1", NAME], "the listener first, then the route"
    assert found["ok"] is False
    assert found["said"] == f"{NAME} does not reach this Mac."
    assert found["fix"] == phone_check.HINTS["name"] and "colima start" in found["fix"] and "connector" in found["fix"]
    assert found["help"].startswith("https://github.com/ballerine-io/pointe/blob/main/docs/")


def test_a_name_this_mac_cannot_look_up_is_not_called_broken(state, monkeypatch):
    scripted(monkeypatch, {"127.0.0.1": "ok", NAME: "no_name"})
    found = phone_check.check(state, 7443)
    assert found["ok"] is None, "a Twingate name may resolve only on the phone: unknown, not failed"
    assert found["said"] == f"This Mac can't look up {NAME}, so it can't check the route."
    assert found["fix"].endswith(phone_check.HINTS["name"])


def test_a_name_that_reaches_another_server_says_so(state, monkeypatch):
    scripted(monkeypatch, {"127.0.0.1": "ok", NAME: "other_certificate"})
    found = phone_check.check(state, 7443)
    assert found["ok"] is False and found["said"] == f"{NAME} answers with another certificate: it does not reach this Mac's Pointe."


def test_pointes_own_listener_down_is_said_before_the_route(state, monkeypatch):
    seen = scripted(monkeypatch, {"127.0.0.1": "refused"})
    found = phone_check.check(state, 7443)
    assert seen == ["127.0.0.1"], "the route is not tried when nothing of Pointe's answers"
    assert found["ok"] is False and found["said"] == "Pointe's phone listener does not answer on 127.0.0.1:7443."
    assert found["fix"] == phone_check.START_POINTE


def test_tailscale_and_wifi_say_their_own_hint(state, monkeypatch):
    (state / "remote.json").write_text(json.dumps({"host": "studio.tail1234.ts.net", "listen": ["100.101.102.103"]}))
    scripted(monkeypatch, {"100.101.102.103": "ok", "studio.tail1234.ts.net": "no_answer"})
    found = phone_check.check(state, 7443)
    assert found["ok"] is False and found["kind"] == "tailscale" and found["fix"] == "Is Tailscale connected on both?"
    (state / "remote.json").write_text(json.dumps({"host": "192.168.1.20", "listen": ["192.168.1.20"]}))
    seen = scripted(monkeypatch, {"192.168.1.20": "ok"})
    assert phone_check.check(state, 7443, wifi="192.168.1.20")["ok"] is True
    assert seen == ["192.168.1.20"], "on Wi-Fi the listener's address is the route: one handshake"


def test_a_wifi_route_paired_at_an_old_address_says_pair_again(state, monkeypatch):
    (state / "remote.json").write_text(json.dumps({"host": "192.168.1.20", "listen": ["192.168.1.20"]}))
    seen = scripted(monkeypatch, {})
    found = phone_check.check(state, 7443, wifi="192.168.1.31")
    assert seen == [], "nothing to try: the Mac is no longer at that address"
    assert found["ok"] is False and found["kind"] == "wifi"
    assert found["said"] == "This Mac's Wi-Fi address is now 192.168.1.31, not 192.168.1.20."
    assert "Connect your phone" in found["fix"]


def test_a_route_being_chosen_is_checked_instead_of_the_one_paired(state, monkeypatch):
    seen = scripted(monkeypatch, {"127.0.0.1": "ok", "other.example.internal": "ok"})
    assert phone_check.check(state, 7443, host="Other.Example.Internal")["host"] == "other.example.internal"
    assert seen == ["127.0.0.1", "other.example.internal"]


def test_nothing_set_up_is_none(tmp_path):
    assert phone_check.check(tmp_path, free_port()) is None


# ---------- pointe doctor ----------

def test_doctor_prints_the_paired_route_and_the_fix(state, monkeypatch):
    import doctor

    monkeypatch.setattr(doctor, "state_dir", lambda: state)
    scripted(monkeypatch, {"127.0.0.1": "ok", NAME: "no_answer"})
    out = "\n".join(doctor.phone_lines())
    assert out.startswith("Phone:")
    assert f"route    {NAME} (a name you route yourself" in out
    assert f"PROBLEM  {NAME} does not reach this Mac." in out and "Fix: " + phone_check.HINTS["name"] in out
    assert "Help: https://github.com/ballerine-io/pointe/blob/main/docs/" in out
    scripted(monkeypatch, {"127.0.0.1": "ok", NAME: "ok"})
    out = "\n".join(doctor.phone_lines())
    assert f"ok       {NAME} reaches this Mac's Pointe." in out and "Fix:" not in out and "Help:" not in out


def test_doctor_with_no_phone_route_says_how_to_set_one_up(tmp_path, monkeypatch):
    import doctor

    monkeypatch.setattr(doctor, "state_dir", lambda: tmp_path)
    out = "\n".join(doctor.phone_lines())
    assert "not set up" in out and "Connect your phone" in out


def test_doctor_shows_the_phone_section_in_its_details(state, monkeypatch, capsys):
    import doctor

    monkeypatch.setattr(doctor, "state_dir", lambda: state)
    monkeypatch.setattr(doctor, "phone_lines", lambda: ["Phone:", "  route    sentinel.example.internal (x)"])
    monkeypatch.setattr(sys, "argv", ["doctor.py"])
    monkeypatch.setenv("CLAUDE_VOICE_DAEMON_PORT", str(free_port()))  # never the live daemon's 7860
    doctor.main()
    assert "sentinel.example.internal" in capsys.readouterr().out


# ---------- the same words on the phone ----------

def _swift(name: str) -> dict:
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "ConnectionProblem.swift").read_text()
    block = swift[swift.index(f"enum {name}"):]
    block = block[:block.index("\n}\n")]
    return dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block))


def test_the_phone_and_the_mac_say_each_routes_hint_and_name_in_the_same_words():
    app = _swift("RouteCopy")
    for kind in ("wifi", "tailscale", "name"):
        assert app[f"{kind}Hint"] == phone_check.HINTS[kind], kind
        assert app[f"{kind}Label"] == phone_check.LABELS[kind], kind
        assert app[f"{kind}Help"] == phone_check.HELP[kind], kind


def test_each_routes_guide_link_is_a_page_and_a_section_in_the_repository():
    for kind, link in phone_check.HELP.items():
        path, anchor = link.removeprefix("https://github.com/ballerine-io/pointe/blob/main/").split("#")
        text = (ROOT / path).read_text()
        headings = {re.sub(r"[^a-z0-9 -]", "", h.strip().lower()).replace(" ", "-")
                    for h in re.findall(r"^#+ (.+)$", text, re.M)}
        assert anchor in headings, (kind, link, sorted(headings))
