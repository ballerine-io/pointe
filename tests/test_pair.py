import json
import os
import ssl
import stat
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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
