"""Pair the Pointe phone app with this Mac. Usage:

  pointe pair tailscale      the Mac's Tailscale name (the phone needs Tailscale too)
  pointe pair wifi           this Mac's address on the current Wi-Fi (pair again if it changes)
  pointe pair host <name>    a name you route yourself (Twingate, Cloudflare Tunnel with Access); listens on 127.0.0.1
  pointe pair show           the QR code again
  pointe pair link           the address that pairs a phone's browser page
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
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import nodelink  # noqa: E402
from remote import TLS_PORT  # noqa: E402

STATE = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))


PAIRING_VERSION = 1  # the QR code's format; the call protocol (phone.PROTOCOL) moves on its own
CODE_PAIRING_VERSION = 2  # the page's QR: a one-time code the app trades for the key, instead of the key itself


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
        _say_nodes_pair_again()
    old = os.umask(0o077)
    try:
        if not (STATE / "remote_token").exists():
            (STATE / "remote_token").write_text(os.urandom(32).hex())
        (STATE / "remote.json").write_text(json.dumps({"host": host, "listen": [listen]}) + "\n")
    finally:
        os.umask(old)


UNUSED = "phone_key.unused"  # a phone_key made here for a QR no phone has used yet: not listed as a paired phone


def pairing_link() -> str:
    from phone import phone_key  # not at the top: phone.py imports Pipecat, which logs a banner

    config = json.loads((STATE / "remote.json").read_text())
    if not (STATE / "phone_key").exists():
        (STATE / UNUSED).touch(mode=0o600)
    return "pointe://pair?" + urlencode({"v": PAIRING_VERSION, "host": config["host"], "port": TLS_PORT,
                                         "fp": fingerprint(), "key": phone_key(STATE)})


def invite_pairing_link(code: str) -> str:
    """The page's QR (Settings → Phone): where the Mac listens, its certificate, and a one-time code. No lasting secret:
    the app trades the code for the phone key over the pinned listener (phone_pairing.py)."""
    config = _config()
    return "pointe://pair?" + urlencode({"v": CODE_PAIRING_VERSION, "host": config["host"], "port": TLS_PORT,
                                         "fp": fingerprint(), "code": code})


_HOST_NAME = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
INSTALL_ADVICE = ("Nothing can carry your phone to this Mac yet. Install Tailscale on this Mac and on your iPhone "
                  "(https://tailscale.com/download) and sign in to both with the same account, then check again. "
                  "Or put this Mac and the phone on the same Wi-Fi.")


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except (OSError, UnicodeError):
        return []


def _host_route(host: str) -> dict:
    """A name the owner routes (Twingate, a VPN, a tunnel): served on loopback, for a connector on this Mac."""
    route = {"kind": "host", "host": host, "listen": "127.0.0.1", "label": host, "problem": None, "usable": True}
    if not _HOST_NAME.fullmatch(host):
        return {**route, "usable": False, "problem": "That is not a host name.", "words": host}
    addresses = _resolve(host)
    ips = [ipaddress.ip_address(a.split("%")[0]) for a in addresses]
    if not ips:
        problem = ("This Mac can't look it up, so Pointe can't check it. Use it if your phone reaches it (a Twingate "
                   "name often resolves only on the phone).")
    elif all(ip.is_loopback for ip in ips):
        problem = (f"It points at this Mac itself ({addresses[0]}): your phone needs its own way to it, such as a "
                   "Twingate resource or a tunnel.")
    elif any(ip.is_global for ip in ips):
        problem = (f"It resolves to a public internet address ({addresses[0]}). Use it only if just you can reach it "
                   "(for example a tunnel behind Cloudflare Access).")
    else:
        problem = None
    shown = f" ({', '.join(addresses)})" if addresses else ""
    words = (f"{host}{shown}: the private network name you set up, such as Twingate or a VPN. It works wherever that "
             "network reaches your phone; a connector or tunnel on this Mac forwards it to Pointe.")
    return {**route, "problem": problem, "words": words, "checked": problem is None}


def routes(typed: str | None = None) -> dict:
    """What can carry the phone to this Mac, in plain words, with one recommended: the route paired now (nothing
    paired has to pair again, even when this Mac can't check it), else Tailscale, else a checked private name, else the Wi-Fi. `typed` adds a name to check."""
    current = json.loads((STATE / "remote.json").read_text()) if (STATE / "remote.json").exists() else None
    found = []
    try:
        name, ip = _tailscale()
        found.append({"kind": "tailscale", "host": name, "listen": ip, "label": "Tailscale", "usable": True,
                      "problem": None, "checked": True,
                      "words": f"Tailscale ({name}): works wherever this Mac and the phone have internet. The iPhone "
                               "needs the Tailscale app, signed in to the same account."})
    except SystemExit as e:
        found.append({"kind": "tailscale", "host": "", "listen": "", "label": "Tailscale", "usable": False,
                      "problem": str(e), "words": "Tailscale: works wherever this Mac and the phone have internet."})
    names = [] if current is None or current["host"] in (r["host"] for r in found) else [current["host"]]
    if typed and typed.strip().lower() not in names:
        names.append(typed.strip().lower())
    try:
        wifi, _ = _wifi()
    except SystemExit as e:
        wifi_route = {"kind": "wifi", "host": "", "listen": "", "label": "Same Wi-Fi", "usable": False,
                      "problem": str(e), "words": "Same Wi-Fi: only while the phone is on this Mac's Wi-Fi."}
    else:
        wifi_route = {"kind": "wifi", "host": wifi, "listen": wifi, "label": "Same Wi-Fi", "usable": True,
                      "problem": None, "checked": True,
                      "words": f"Same Wi-Fi ({wifi}): only while the phone is on this Wi-Fi, and until the Mac's address "
                               "changes (then connect again)."}
    if current is not None and current["host"] == wifi_route["host"]:
        names = [n for n in names if n != wifi]
    found += [_host_route(n) for n in names] + [wifi_route]
    has_cert = (STATE / "tls" / "cert.pem").exists()
    for r in found:
        r["current"] = bool(current and r["usable"] and r["host"] == current["host"])
        r["new_certificate"] = bool(has_cert and r["usable"] and not r["current"] and not _covers(r["host"]))
    order = ([r for r in found if r["current"]]
             + [r for r in found if r["kind"] == "tailscale"] + [r for r in found if r["kind"] == "host" and r.get("checked")]
             + [r for r in found if r["kind"] == "wifi"])
    best = next((r for r in order if r["usable"]), None)
    for r in found:
        r["recommended"] = r is best
        r.pop("checked", None)
    return {"current": current["host"] if current else None, "routes": found,
            "advice": None if any(r["usable"] for r in found) else INSTALL_ADVICE}


NOT_SET_UP = "Not set up yet: run `pointe pair tailscale`, `pointe pair wifi`, or `pointe pair host <name>`."


def _config() -> dict:
    if not (STATE / "remote.json").exists():
        raise SystemExit(NOT_SET_UP)
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


RESTART = "once Pointe restarts (pointe restart)"


def _paired_nodes() -> list[str]:
    """The names of the machines paired with this hub, read from nodes.json without changing it."""
    try:
        nodes = json.loads((STATE / "nodes.json").read_text()).get("nodes") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [str(n["name"]) for n in nodes if isinstance(n, dict) and n.get("name")]


def _say_nodes_pair_again() -> None:
    """A new certificate unpairs every node, and `pointe hub invite` alone fails while the old pairing is on both sides
    (QA round 2: "already paired", then "leave studio first"): the steps that work, per machine."""
    for name in _paired_nodes():
        print(f"{name} must pair again: here, pointe hub revoke {name}, then pointe hub invite --name {name}; on {name}, "
              f"pointe node leave, then pointe node join '<the invite>'.")


def _home_path(path: Path) -> str:
    return str(path).replace(str(Path.home()), "~", 1)


def rotate() -> None:
    _certificate(_config()["host"])
    print(f"New certificate {fingerprint()[:16]}..., used {RESTART}.")
    print("The phone app must pair again (pointe pair show), and a browser that trusted the old certificate must trust "
          "this one.")
    if not _paired_nodes():
        print("No node (another machine) is paired with this Mac, so none has to pair again.")
    _say_nodes_pair_again()


def off() -> None:
    shutil.rmtree(STATE / "tls", ignore_errors=True)
    for name in ("remote.json", "remote_token"):
        (STATE / name).unlink(missing_ok=True)
    print(f"The phone listener is off {RESTART}. A network connector (bin/voice-connector) and its tokens "
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
    print(f"This code holds a secret. To revoke it, Unpair the phone in Settings → Phone, or delete {_home_path(STATE / 'phone_key')}.")


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
        host, listen = argv[1].strip().lower(), "127.0.0.1"
        if not _HOST_NAME.fullmatch(host):  # checked before anything changes: a new certificate unpairs every phone and node
            raise SystemExit(f"{argv[1]!r} is not a host name: letters, digits, hyphens and dots only, such as "
                             "mac.example.internal. Nothing was changed.")
    else:
        raise SystemExit(__doc__.strip())
    setup(host, listen)
    print(f"Listening for the phone on {listen}:{TLS_PORT} {RESTART}.")
    show()


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # Pipecat logs a banner when imported (pointe pair show): this is a command for people, not a log
    main(sys.argv[1:])
