"""Does the phone's route reach this Mac? The Mac's half of "the iPhone app can't reach the Mac" (docs/phone.md).

Run before the page or the Mac app shows a pairing code (phone_pairing.py), and by `pointe doctor` for the route paired
now. Two steps, from this Mac: Pointe's own listener answers on its listen address, then the route's name reaches that
same listener, proved by its certificate's fingerprint in a TLS handshake. No request is made and no secret is sent.

The words for each route are the iPhone app's (`RouteCopy` in apps/PointeKit/Sources/PointeUI/ConnectionProblem.swift);
tests/test_phone_check.py holds the two to the same text.
"""

import hashlib
import ipaddress
import json
import socket
import ssl
from pathlib import Path

LABELS = {"wifi": "Wi-Fi", "tailscale": "Tailscale", "name": "a name you route yourself (Twingate, a VPN or a tunnel)"}
HINTS = {
    "name": ("Is your VPN app on, on both devices? Is the connector on the Mac running? With Docker or Colima it stops "
             "after a restart: run `colima start`."),
    "tailscale": "Is Tailscale connected on both?",
    "wifi": "Both must be on the same network; it stops working when either one moves.",
}
GUIDE = "https://github.com/ballerine-io/pointe/blob/main/docs/phone/"
HELP = {"wifi": GUIDE + "wifi.md#when-it-stops-working", "tailscale": GUIDE + "tailscale.md#when-it-stops-working",
        "name": GUIDE + "twingate.md#when-it-stops-working"}
START_POINTE = "Is Pointe running? /pointe:voice in a Claude Code session starts it; pointe restart starts it again."
TIMEOUT = 3.0
_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def route_kind(host: str) -> str:
    """How a phone reaches this address, the way `pointe pair` writes it: an IPv4 address is this Mac's on its Wi-Fi,
    unless it is in Tailscale's 100.64.0.0/10; a `.ts.net` name is Tailscale's; any other name is one the owner routes.
    The app reads a pairing's host the same way (`PhoneRoute`)."""
    host = host.strip().lower().rstrip(".")
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return "tailscale" if host.endswith(".ts.net") else "name"
    return "tailscale" if ip in _TAILSCALE else "wifi"


def _resolve(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except (OSError, UnicodeError):
        return []


def probe(host: str, port: int, fingerprint: str, timeout: float = TIMEOUT) -> str:
    """One TLS handshake with whatever answers at host:port: "ok" when it is the listener with this certificate,
    "no_name" (the name does not resolve here), "refused" (nothing listens), "no_answer" (no reply in time, or the
    connection dropped), "other_certificate" (something else answers)."""
    addresses = _resolve(host)
    if not addresses:
        return "no_name"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE  # the fingerprint is the check, as on the phone
    try:
        with socket.create_connection((addresses[0], port), timeout=timeout) as raw:
            raw.settimeout(timeout)
            with context.wrap_socket(raw, server_hostname=None if host == addresses[0] else host) as tls:
                der = tls.getpeercert(binary_form=True) or b""
    except ConnectionRefusedError:
        return "refused"
    except (OSError, ssl.SSLError):
        return "no_answer"
    return "ok" if hashlib.sha256(der).hexdigest() == fingerprint else "other_certificate"


def _result(ok, kind: str, host: str, said: str, fix: str | None) -> dict:
    return {"ok": ok, "kind": kind, "label": LABELS[kind], "host": host, "said": said, "fix": fix, "help": HELP[kind]}


def check(state: Path, port: int, host: str | None = None, wifi: str | None = None) -> dict | None:
    """The route `host` (else the one paired now, from remote.json), checked from this Mac. None when nothing is set up.
    `ok` is True (it reaches this Mac's Pointe), False (it does not: `said` is why, `fix` what to do) or None (this Mac
    cannot tell). `wifi`: this Mac's Wi-Fi address now, when known, for a Wi-Fi route paired at another one."""
    try:
        config = json.loads((state / "remote.json").read_text())
        fingerprint = _fingerprint(state)
    except (OSError, ValueError):
        return None
    host = (host or config.get("host") or "").strip().lower()
    if not host:
        return None
    kind = route_kind(host)
    listen = (config.get("listen") or ["127.0.0.1"])[0]
    if kind == "wifi" and wifi and wifi != host:
        return _result(False, kind, host, f"This Mac's Wi-Fi address is now {wifi}, not {host}.",
                       "Connect your phone again: Settings → Phone → Connect your phone.")
    at_listener = probe(listen, port, fingerprint)
    if at_listener != "ok":
        return _result(False, kind, host, f"Pointe's phone listener does not answer on {listen}:{port}.", START_POINTE)
    if kind != "name" and host == listen:
        return _result(True, kind, host, f"{host} reaches this Mac's Pointe.", None)
    seen = probe(host, port, fingerprint)
    if seen == "ok":
        return _result(True, kind, host, f"{host} reaches this Mac's Pointe.", None)
    if seen == "no_name":
        return _result(None, kind, host, f"This Mac can't look up {host}, so it can't check the route.",
                       f"If your phone can't reach it either: {HINTS[kind]}")
    if seen == "other_certificate":
        return _result(False, kind, host, f"{host} answers with another certificate: it does not reach this Mac's Pointe.",
                       f"Check where the name points: it must reach this Mac's port {port}.")
    return _result(False, kind, host, f"{host} does not reach this Mac.", HINTS[kind])


def _fingerprint(state: Path) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate((state / "tls" / "cert.pem").read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def lines(found: dict | None) -> list[str]:
    """For `pointe doctor`: the route paired now and what the check found."""
    if found is None:
        return ["  not set up: Settings → Phone → Connect your phone on the page, or pointe pair tailscale, wifi or host <name>"]
    out = [f"  route    {found['host']} ({found['label']})"]
    mark = {True: "ok      ", False: "PROBLEM ", None: "unknown "}[found["ok"]]
    out.append(f"  {mark} {found['said']}")
    if found["fix"]:
        out.append(f"  Fix: {found['fix']}")
    if found["ok"] is not True:
        out.append(f"  Help: {found['help']}")
    return out
