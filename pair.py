"""Pair the Pointe phone app with this Mac. Usage:

  pointe pair tailscale      the Mac's Tailscale name (the phone needs Tailscale too)
  pointe pair wifi           this Mac's address on the current Wi-Fi (pair again if it changes)
  pointe pair host <name>    a name you route yourself (Twingate, Cloudflare Tunnel with Access); listens on 127.0.0.1
  pointe pair show           the QR code again
  pointe pair link           the address that pairs a phone's browser page (what bin/voice-remote link printed)
  pointe pair rotate         a new certificate: the phone and every machine paired with this Mac must pair again
  pointe pair off            stop listening: removes the certificate, remote.json and remote_token

The QR code holds a secret that opens a call into your sessions: show it only to your own phone. The app pins this
listener's certificate by its fingerprint, so nothing has to be installed on the phone.
"""

import datetime
import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import nodelink  # noqa: E402
from phone import phone_key  # noqa: E402
from remote import TLS_PORT  # noqa: E402

STATE = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))


PAIRING_VERSION = 1  # the QR code's format; the call protocol (phone.PROTOCOL) moves on its own


def _run(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _tailscale() -> tuple[str, str]:
    cli = shutil.which("tailscale") or "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    status = _run(cli, "status", "--json")
    if not status:
        raise SystemExit("Tailscale is not running on this Mac. Install it (https://tailscale.com/download), sign in, and retry.")
    me = json.loads(status).get("Self") or {}
    name, ips = (me.get("DNSName") or "").rstrip("."), [ip for ip in me.get("TailscaleIPs") or [] if "." in ip]
    if not name or not ips:
        raise SystemExit("Tailscale has no name or address for this Mac yet.")
    return name, ips[0]


def _wifi() -> tuple[str, str]:
    for interface in ("en0", "en1"):
        ip = _run("ipconfig", "getifaddr", interface)
        if ip:
            return ip, ip
    raise SystemExit("No Wi-Fi address found.")


def _certificate(host: str) -> None:
    """A self-signed certificate for this one name. The app trusts it by fingerprint, not through any CA."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    try:
        alt = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        alt = x509.DNSName(host)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=800))
            .add_extension(x509.SubjectAlternativeName([alt]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            # iOS refuses a TLS server certificate without it (error -9802), even one the app pins; localhost is exempt.
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    tls = STATE / "tls"
    tls.mkdir(parents=True, exist_ok=True, mode=0o700)
    old = os.umask(0o077)
    try:
        (tls / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
        (tls / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    finally:
        os.umask(old)


def fingerprint() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate((STATE / "tls" / "cert.pem").read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _covers(host: str) -> bool:
    """The certificate already here is for this name and not near its end: keep it, so a browser that trusts it still does."""
    from cryptography import x509

    try:
        cert = x509.load_pem_x509_certificate((STATE / "tls" / "cert.pem").read_bytes())
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    try:
        usage = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound:
        return False  # made before it was required: iOS would refuse it
    if x509.oid.ExtendedKeyUsageOID.SERVER_AUTH not in usage:
        return False
    left = cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)
    return (host in names.get_values_for_type(x509.DNSName) or host in map(str, names.get_values_for_type(x509.IPAddress))) \
        and left > datetime.timedelta(days=30) and (STATE / "tls" / "key.pem").exists()


def setup(host: str, listen: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not _covers(host):
        _certificate(host)
    old = os.umask(0o077)
    try:
        if not (STATE / "remote_token").exists():
            (STATE / "remote_token").write_text(os.urandom(32).hex())
        (STATE / "remote.json").write_text(json.dumps({"host": host, "listen": [listen]}) + "\n")
    finally:
        os.umask(old)


def pairing_link() -> str:
    config = json.loads((STATE / "remote.json").read_text())
    return "pointe://pair?" + urlencode({"v": PAIRING_VERSION, "host": config["host"], "port": TLS_PORT,
                                         "fp": fingerprint(), "key": phone_key(STATE)})


_NOT_SET_UP = "Not set up yet: run `pointe pair tailscale`, `pointe pair wifi`, or `pointe pair host <name>`."


def _config() -> dict:
    if not (STATE / "remote.json").exists():
        raise SystemExit(_NOT_SET_UP)
    return json.loads((STATE / "remote.json").read_text())


def invite_link(code: str) -> str:
    """The line `pointe node join` takes: the listener the phone uses, its certificate's fingerprint, a one-time code.
    No lasting secret: the code is single use and dies in ten minutes."""
    return "pointe://hub?" + urlencode({"v": nodelink.INVITE_VERSION, "host": _config()["host"], "port": TLS_PORT,
                                        "fp": fingerprint(), "code": code})


def link() -> None:
    host = _config()["host"]
    token = (STATE / "remote_token").read_text().strip()
    print(f"https://{host}:{TLS_PORT}/voice?pair={token}")
    print("Open it once on the phone's browser. It holds a secret: send it only to your own phone.")


def rotate() -> None:
    _certificate(_config()["host"])
    print(f"New certificate {fingerprint()[:16]}... for the next daemon start (`pointe stop`, then /pointe:voice).")
    print("The phone app and every node paired with this Mac must pair again: `pointe pair show` for the phone, "
          "`pointe hub invite` for each node. A browser that trusted the old certificate must trust this one.")


def off() -> None:
    shutil.rmtree(STATE / "tls", ignore_errors=True)
    for name in ("remote.json", "remote_token"):
        (STATE / name).unlink(missing_ok=True)
    print("The phone listener is off once the daemon restarts. A network connector (bin/voice-connector) and its tokens "
          "are left as they are.")


def show() -> None:
    import segno

    config = _config()
    code = segno.make(pairing_link(), error="m")
    code.terminal(compact=True)
    image = STATE / "pair-qr.png"  # a chat window cannot show the terminal code: open it as a picture instead
    image.touch(mode=0o600)
    code.save(str(image), scale=10)
    if sys.platform == "darwin":
        subprocess.run(["open", str(image)], check=False)
    print(f"Scan with the Pointe app. It connects to {config['host']}:{TLS_PORT} and checks certificate {fingerprint()[:16]}...")
    print("This code holds a secret. To revoke it, delete ~/.claude-voice/phone_key and restart the daemon.")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    commands = {"show": show, "link": link, "rotate": rotate, "off": off}
    if argv[0] in commands:
        return commands[argv[0]]()
    if argv[0] == "tailscale":
        host, listen = _tailscale()
    elif argv[0] == "wifi":
        host, listen = _wifi()
    elif argv[0] == "host" and len(argv) > 1:
        host, listen = argv[1].lower(), "127.0.0.1"
    else:
        raise SystemExit(__doc__.strip())
    setup(host, listen)
    print(f"Listening for the phone on {listen}:{TLS_PORT} once the daemon restarts (`pointe stop`, then /pointe:voice).")
    show()


if __name__ == "__main__":
    main(sys.argv[1:])
