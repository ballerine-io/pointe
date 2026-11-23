"""How the Mac app proves it holds the page key without sending it (SECURITY.md, "The Mac app").

The app checks who listens on the port before it talks to the daemon, but the daemon can stop and another program can
take the port before the app looks again. So the app never sends the key: each request carries an HMAC over that one
request, keyed by the page key and the token `bin/voice-daemon` writes anew at every start. A program on the port gets a
proof that works once, for a short while, for that request only, and only on the daemon that is no longer there.
`PointeKit/LocalProof.swift` builds the same header; tests/test_local_proof.py holds the two to one wire format.
"""

import hashlib
import hmac
import re
import time

HEADER = "x-pointe-proof"
VERSION = "v1"
WINDOW = 120  # seconds either way: one clock on one Mac, and a request can wait behind others in URLSession
_FORMAT = re.compile(r"v1\.(\d{1,12})\.([0-9a-f]{32})\.([0-9a-f]{64})\.([0-9a-f]{64})")


def _key(page_key: str, token: str) -> bytes:
    return hmac.new(page_key.encode(), b"pointe-mac-proof|" + token.encode(), hashlib.sha256).digest()


def _mac(key: bytes, ts: str, nonce: str, method: str, path: str, query: str, body_hash: str) -> str:
    text = "\n".join((VERSION, ts, nonce, method.upper(), path, query, body_hash))
    return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()


def sign(page_key: str, token: str, ts: int, nonce: str, method: str, path: str, query: str, body: bytes) -> str:
    """The header's value. The daemon never signs; tests and the Swift side's agreement do."""
    body_hash = hashlib.sha256(body).hexdigest()
    return f"{VERSION}.{ts}.{nonce}.{body_hash}.{_mac(_key(page_key, token), str(ts), nonce, method, path, query, body_hash)}"


class Proofs:
    """The check, and the nonces already used. Nothing is kept until a proof's HMAC holds, so no one without the key
    can fill the memory."""

    def __init__(self, page_key: str, token: str):
        self._key = _key(page_key, token) if page_key and token else None
        self._used: dict[str, float] = {}

    def check(self, value: str, method: str, path: str, query: str) -> str | None:
        """The body hash the request must match, or None: refuse it. Its nonce is spent from now on."""
        found = _FORMAT.fullmatch(value)
        if not self._key or not found:
            return None
        ts, nonce, body_hash, mac = found.groups()
        now = time.time()
        if abs(now - int(ts)) > WINDOW:
            return None
        if not hmac.compare_digest(_mac(self._key, ts, nonce, method, path, query, body_hash), mac):
            return None
        self._used = {n: until for n, until in self._used.items() if until > now}
        if nonce in self._used:
            return None
        self._used[nonce] = now + 2 * WINDOW
        return body_hash


async def read_body(receive):
    """The request's whole body, and a `receive` that hands it to the app as if it had not been read. None for a client
    that left before it sent all of it."""
    chunks, more = [], True
    while more:
        message = await receive()
        if message["type"] != "http.request":
            return None
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    body, sent = b"".join(chunks), False

    async def replay():
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return body, replay
