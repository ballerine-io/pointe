"""Pair the Pointe phone app with this Mac. Usage:

  pointe pair tailscale      the Mac's Tailscale name (the phone needs Tailscale too)
  pointe pair wifi           this Mac's address on the current Wi-Fi (pair again if it changes)
  pointe pair host <name>    a name you route yourself (Twingate, a VPN); listens on 127.0.0.1
      --public               the name is on the internet, its port passed straight through: pairing and the pinned
                             certificate are what guard it
  pointe pair ssh <user@host>  a client's own SSH tunnel to this machine's 127.0.0.1 (the Mac app, other machines)
      --add                  (any route) beside the routes there are, with the same certificate: no client pairs again
                             (Cloudflare Tunnel with Access: the phone's browser only; the app pins this Mac's certificate)
      --listen <address>     also on this private address: `docker` is Docker's bridge, for a Twingate connector in a
                             container on the default bridge network (docs/linux.md)
  pointe pair show           the QR code again
  pointe pair link           the address that pairs a phone's browser page
  pointe pair rotate         a new certificate and pairing link; signs out every phone, browser and machine (pair again)
  pointe pair off            stop listening, and sign out every phone, browser and machine

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
import childenv  # noqa: E402
import nodelink  # noqa: E402
from remote import TLS_PORT  # noqa: E402

STATE = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))


PAIRING_VERSION = 1  # the QR code's format; the call protocol (phone.PROTOCOL) moves on its own
CODE_PAIRING_VERSION = 2  # the page's QR: a one-time code the app trades for the key, instead of the key itself


def _run(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10, env=childenv.child_env()).stdout.strip()
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
    if sys.platform != "darwin":
        ip = _lan_address()
        if ip:
            return ip, ip
        raise SystemExit("No local network address found: this machine has no private address on its default route.")
    for interface in ("en0", "en1"):
        ip = _run("ipconfig", "getifaddr", interface)
        if ip:
            return ip, ip
    raise SystemExit("No Wi-Fi address found.")


def _lan_address() -> str | None:
    """Linux has no `ipconfig getifaddr`: the private IPv4 address of the default route, the one a phone on the same
    network reaches. Connecting a UDP socket only picks the route; no packet is sent (192.0.2.1 is documentation space).
    Not 100.64/10 (Tailscale's and Twingate's own) and never a public address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            ip = probe.getsockname()[0]
    except OSError:
        return None
    address = ipaddress.ip_address(ip)
    return ip if address.is_private and not address.is_loopback and not address.is_link_local else None


def _docker_bridge() -> str | None:
    """Docker's default bridge address on this machine (docker0), which a container on that network reaches it at."""
    for line in _run("ip", "-4", "-o", "addr", "show", "docker0").splitlines():
        found = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)/", line)
        if found:
            return found.group(1)
    return None


def _bridged_connector() -> str | None:
    """The name of a running Twingate connector container on a Docker network other than the host's, or None. Such a
    connector reaches this machine at the bridge address, so 127.0.0.1 alone is out of its reach."""
    if not shutil.which("docker"):
        return None
    for line in _run("docker", "ps", "--filter", "ancestor=twingate/connector:1", "--format",
                     "{{.Names}} {{.Networks}}").splitlines():
        name, _, networks = line.partition(" ")
        if name and networks and "host" not in networks.split(","):
            return name
    return None


def _listen_address(typed: str) -> str:
    """An address `--listen` may add: `docker` (the bridge), or a private IPv4 or IPv6 address of this machine. Never
    0.0.0.0 or a public address: the listener would answer every network."""
    if typed == "docker":
        bridge = _docker_bridge()
        if bridge is None:
            raise SystemExit("No Docker bridge (docker0) on this machine. Nothing was changed.")
        return bridge
    try:
        address = ipaddress.ip_address(typed)
    except ValueError:
        address = None
    if address is None or address.is_unspecified or not address.is_private:
        raise SystemExit(f"--listen {typed}: give a private address of this machine, such as Docker's bridge "
                         "(--listen docker, usually 172.17.0.1). Nothing was changed.")
    return str(address)


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


ROUTE_KINDS = ("tailscale", "wifi", "host", "public", "ssh")
_SSH_TARGET = re.compile(r"(?:[a-z_][a-z0-9_.-]{0,31}@)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")


def setup(host: str, listen: str, also: tuple[str, ...] = (), kind: str | None = None, add: bool = False) -> None:
    """`kind` (one of ROUTE_KINDS) goes into the pairing lines, so a client shows how it reaches this machine. `add`:
    beside the routes there are, keeping the certificate, so every pairing stays (docs/design/multi-machine-clients.md,
    1.2); the first route stays the one the lines name. Without it this route replaces them, as before."""
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    before = route_list() if add else []
    keep = add and bool(before) and (STATE / "tls" / "key.pem").exists()
    name = "127.0.0.1" if kind == "ssh" else host  # a tunnel arrives at this machine's loopback
    if not keep and not _covers(name):
        _certificate(name)
        _say_nodes_pair_again(_paired_nodes(), revoke=True)
    old = os.umask(0o077)
    try:
        if not (STATE / "remote_token").exists():
            (STATE / "remote_token").write_text(os.urandom(32).hex())
        addresses = [listen, *(a for a in also if a != listen)]
        route = {"kind": kind or "host", "host": host, "listen": addresses}
        routes = [r for r in before if (r["kind"], r["host"]) != (route["kind"], host)] + [route]
        first = routes[0]
        config = {"host": first["host"], "listen": list(dict.fromkeys(a for r in routes for a in r["listen"]))}
        if kind or len(routes) > 1:
            config["kind"] = first["kind"]
        if len(routes) > 1:
            config["routes"] = routes
        (STATE / "remote.json").write_text(json.dumps(config) + "\n")
    finally:
        os.umask(old)


def route_list(config: dict | None = None) -> list[dict]:
    """Every route to this machine, the one lines name first. A remote.json from before routes is one route."""
    if config is None:
        path = STATE / "remote.json"
        if not path.exists():
            return []
        config = json.loads(path.read_text())
    listed = config.get("routes")
    if isinstance(listed, list) and listed:
        return [r for r in listed if isinstance(r, dict) and r.get("kind") in ROUTE_KINDS and isinstance(r.get("host"), str)]
    if not config.get("host"):
        return []
    return [{"kind": config.get("kind") or "host", "host": config["host"], "listen": list(config.get("listen") or [])}]


def routes_status() -> list[dict]:
    """The status's `routes`: what a paired client stores to reach this machine another way (never a listen address)."""
    try:
        return [{"kind": r["kind"], "host": r["host"], "port": TLS_PORT} for r in route_list()]
    except (OSError, ValueError):
        return []


UNUSED = "phone_key.unused"  # a phone_key made here for a QR no phone has used yet: not listed as a paired phone


def pairing_link() -> str:
    from phone import phone_key  # not at the top: phone.py imports Pipecat, which logs a banner

    config = json.loads((STATE / "remote.json").read_text())
    if not (STATE / "phone_key").exists():
        (STATE / UNUSED).touch(mode=0o600)
    return "pointe://pair?" + urlencode({"v": PAIRING_VERSION, "host": config["host"], "port": TLS_PORT,
                                         "fp": fingerprint(), "key": phone_key(STATE), "via": config.get("kind") or "host"})


def invite_pairing_link(code: str) -> str:
    """The page's QR (Settings → Phone): where the Mac listens, its certificate, and a one-time code. No lasting secret:
    the app trades the code for the phone key over the pinned listener (phone_pairing.py)."""
    config = _config()
    kind = config.get("kind") or "host"
    # An SSH route: the client's tunnel arrives at this machine's loopback; `ssh` is the target it runs ssh to.
    where = {"host": "127.0.0.1", "ssh": config["host"]} if kind == "ssh" else {"host": config["host"]}
    return "pointe://pair?" + urlencode({"v": CODE_PAIRING_VERSION, **where, "port": TLS_PORT, "fp": fingerprint(),
                                         "code": code, "via": kind})


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


def _to_terminal() -> bool:
    """A person reads stdout. Not so under a pipe: /pointe:setup has an agent run these, and what they print goes into
    the session's transcript, so a pairing secret then only reaches a picture opened on this Mac."""
    return sys.stdout.isatty()


def _open_picture(text: str, name: str) -> Path | None:
    """`text` as a QR code in a 0600 picture in the state folder, opened on this Mac (None where `open` is not)."""
    import segno

    if sys.platform != "darwin":
        return None
    image = STATE / name
    image.touch(mode=0o600)
    segno.make(text, error="m").save(str(image), scale=10)
    subprocess.run(["open", str(image)], check=False, env=childenv.child_env())
    return image


def link() -> None:
    host = _config()["host"]
    token = (STATE / "remote_token").read_text().strip()
    address = f"https://{host}:{TLS_PORT}/voice?pair={token}"
    if _to_terminal():
        import segno

        segno.make(address, error="m").terminal(compact=True)  # the phone's Camera opens it in the browser
        print(address)
        print("Open it once on the phone's browser (scan the code with the Camera, or send yourself the address). It "
              "holds a secret: only your own phone.")
    elif _open_picture(address, "pair-link-qr.png"):
        print(f"Opened a QR code on this Mac: scan it with the phone's Camera, which opens it in the phone's browser, once. "
              f"It holds a secret, so it is not printed here. The phone checks certificate {fingerprint()[:16]}...")
    else:
        print("The address holds a secret, so it is printed only in a terminal: run `pointe pair link` there.")


def _write_private(path: Path, text: str) -> None:
    old = os.umask(0o077)
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text)
        tmp.replace(path)
    finally:
        os.umask(old)


def _sign_everyone_out() -> list[str]:
    """Every credential the listener honours, gone: each phone's key (`phones.json`, the shared `phone_key`), each
    machine's (`nodes.json` keeps only the hub's id and the machines this voice dials, so a machine pairs again with a new code and nothing else) and
    each person's (`people.json` keeps only the sessions kept private). A running daemon reads these files at each
    check and closes the calls and links they held within seconds. The names of the people who were signed out."""
    people = STATE / "people.json"
    try:
        data = json.loads(people.read_text())
        names = [str(p["name"]) for p in data.get("people", {}).values() if isinstance(p, dict) and p.get("name")]
        private = [s for s in data.get("private") or [] if isinstance(s, str)]
    except (OSError, ValueError, AttributeError, TypeError):
        names, private = [], []
    if people.exists():
        _write_private(people, json.dumps({"people": {}, "private": private}) + "\n")
    for name in ("phone_key", "phones.json"):
        (STATE / name).unlink(missing_ok=True)
    nodes = STATE / "nodes.json"
    try:
        data = json.loads(nodes.read_text())
        hub_id = data.get("hub_id")
        # A machine somebody invited this voice to (machines.py) holds no credential of this Mac's: this voice dials
        # it, with a key that machine gave. It stays.
        dialed = [n for n in data.get("nodes") or [] if isinstance(n, dict) and n.get("dial")]
    except (OSError, ValueError, AttributeError):
        hub_id, dialed = None, []
    if nodes.exists():
        _write_private(nodes, json.dumps({**({"hub_id": hub_id} if isinstance(hub_id, str) else {}), "nodes": dialed}) + "\n")
    return names


def _say_people_invited_again(names: list[str]) -> None:
    """A person's voice holds this machine's old certificate and a key that is gone: each needs a new invite."""
    if names:
        count = "1 person" if len(names) == 1 else f"{len(names)} people"
        print(f"{count} invited to this machine must be invited again ({', '.join(names)}): pointe people invite <name>, "
              "and they add this machine again with the new line.")


def _paired_nodes() -> list[str]:
    """The names of the machines paired with this hub, read from nodes.json without changing it."""
    try:
        nodes = json.loads((STATE / "nodes.json").read_text()).get("nodes") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [str(n["name"]) for n in nodes if isinstance(n, dict) and n.get("name") and not n.get("dial")]


def _say_nodes_pair_again(names: list[str], revoke: bool = False) -> None:
    """A new certificate unpairs every node, and `pointe hub invite` alone fails while the old pairing is on both sides
    (QA round 2: "already paired", then "leave studio first"): the steps that work, per machine. `revoke` when this
    Mac still holds the machine's key (a new route); rotate has already signed it out here."""
    for name in names:
        here = f"pointe hub revoke {name}, then pointe hub invite --name {name}" if revoke else f"pointe hub invite --name {name}"
        print(f"{name} must pair again: here, {here}; on {name}, pointe node leave, then pointe node join '<the invite>'.")


def _home_path(path: Path) -> str:
    return str(path).replace(str(Path.home()), "~", 1)


def rotate() -> None:
    """For a lost phone or a pairing QR, link or invite seen by someone else: a new certificate and a new browser
    pairing secret, and every phone, browser and machine signed out."""
    _certificate(_config()["host"])
    nodes = _paired_nodes()
    people = _sign_everyone_out()
    _write_private(STATE / "remote_token", os.urandom(32).hex())
    print(f"New certificate {fingerprint()[:16]}... Every phone, browser and machine paired with this Mac is signed out "
          "now; a running daemon serves the new certificate within a few seconds.")
    print("Pair each again: Settings → Phone on the page (or `pointe pair show`) for a phone, and `pointe pair link` for a "
          "phone's browser, which must also trust the new certificate.")
    if not nodes:
        print("No node (another machine) is paired with this Mac, so none has to pair again.")
    _say_nodes_pair_again(nodes)
    _say_people_invited_again(people)


def off() -> None:
    shutil.rmtree(STATE / "tls", ignore_errors=True)
    for name in ("remote.json", "remote_token"):
        (STATE / name).unlink(missing_ok=True)
    people = _sign_everyone_out()
    print("The phone listener stops within a few seconds, and every phone, browser and machine paired with this Mac is "
          "signed out. A network connector (bin/voice-connector) and its tokens are left as they are.")
    _say_people_invited_again(people)


def show() -> None:
    import segno

    config = _config()
    if _to_terminal():
        segno.make(pairing_link(), error="m").terminal(compact=True)
    if not _open_picture(pairing_link(), "pair-qr.png") and not _to_terminal():
        print("The QR code holds this phone's lasting key, so it is drawn only in a terminal: run `pointe pair show` there.")
    print(f"Scan it inside the Pointe app, not with the Camera app: it holds this phone's lasting key, and a link the Camera "
          f"opens can reach another app. It connects to {config['host']}:{TLS_PORT} and checks certificate {fingerprint()[:16]}...")
    print(f"To revoke it, Unpair the phone in Settings → Phone, or delete {_home_path(STATE / 'phone_key')}. The page's "
          "Settings → Phone shows a one-time code instead, with no lasting key in it.")


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
    elif argv[0] == "ssh" and len(argv) > 1:
        host, listen = argv[1].strip().lower(), "127.0.0.1"
        if not _SSH_TARGET.fullmatch(host):
            raise SystemExit(f"{argv[1]!r} is not an SSH target: a user and a host name, such as alon@kite.example.com. "
                             "Nothing was changed.")
    elif argv[0] == "host" and len(argv) > 1:
        host, listen = argv[1].strip().lower(), "127.0.0.1"
        if not _HOST_NAME.fullmatch(host):  # checked before anything changes: a new certificate unpairs every phone and node
            raise SystemExit(f"{argv[1]!r} is not a host name: letters, digits, hyphens and dots only, such as "
                             "mac.example.internal. Nothing was changed.")
        rest = [a for a in argv[2:] if a not in ("--public", "--add")]
        if rest and (len(rest) != 2 or rest[0] != "--listen"):
            raise SystemExit(__doc__.strip())
        also = (_listen_address(rest[1]),) if rest else ()
    else:
        raise SystemExit(__doc__.strip())
    also = also if argv[0] == "host" else ()
    kind = "public" if argv[0] == "host" and "--public" in argv else argv[0]
    setup(host, listen, also, kind=kind, add="--add" in argv)
    if kind == "public":
        print("This name is on the internet: anyone can reach port 7443. Only a pairing code and the pinned certificate "
              "guard it; keep codes to yourself.")
    print(f"Listening for the phone on {', '.join([listen, *also])} port {TLS_PORT} within a few seconds if the daemon "
          "runs, else at its next start.")
    if argv[0] == "host" and not also and sys.platform != "darwin" and _to_terminal():
        connector, bridge = _bridged_connector(), _docker_bridge()
        if connector and bridge:
            print(f"The Twingate connector {connector} runs on Docker's bridge network: it reaches this machine at "
                  f"{bridge}, not 127.0.0.1. Run: pointe pair host {host} --listen docker (and give its resource the "
                  f"address {bridge}), or start the connector with --network host.")
    show()


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # Pipecat logs a banner when imported (pointe pair show): this is a command for people, not a log
    main(sys.argv[1:])
