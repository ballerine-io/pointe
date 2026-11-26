"""App Store Connect, read through its API with the team's key from the login keychain.

The key is a generic password (service pointe-asc-api-key-p8, account: the key ID) holding the base64 of the .p8. It is
read into this process, handed to openssl on a pipe to sign one short-lived token, and never written, logged or printed.
The key has the Developer role: reads work (apps, builds, their processing and TestFlight state); creating an App Store
version or submitting is refused (403), so those stay the owner's, in the browser.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import Stop

SERVICE = os.environ.get("POINTE_ASC_SERVICE", "pointe-asc-api-key-p8")
KEY_ID = os.environ.get("POINTE_ASC_KEY_ID", "TSZHHBLM44")
ISSUER = os.environ.get("POINTE_ASC_ISSUER", "8cf5a727-9a2b-4847-a6d8-705dc2bcf84a")
APP_ID = os.environ.get("POINTE_ASC_APP_ID", "6838678047")  # Pointe: Voice Coding
API = "https://api.appstoreconnect.apple.com/v1"


def have_key() -> bool:
    """Whether the keychain item exists (asked without -w: the secret is not read)."""
    return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", KEY_ID],
                          capture_output=True).returncode == 0


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _raw_signature(der: bytes) -> bytes:
    """openssl's DER ECDSA signature as the 64-byte r||s a JWT carries."""
    if der[0] != 0x30:
        raise ValueError("not a DER signature")
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    out = b""
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("not a DER integer")
        n = der[i + 1]
        out += der[i + 2:i + 2 + n].lstrip(b"\x00").rjust(32, b"\x00")
        i += 2 + n
    return out


def token() -> str:
    got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", KEY_ID, "-w"], capture_output=True)
    if got.returncode != 0:
        raise Stop("no App Store Connect API key in the keychain", f"The owner adds it: service {SERVICE}, account {KEY_ID} (the base64 of the .p8)")
    pem = base64.b64decode(got.stdout.strip())
    now = int(time.time())
    head = _b64url(json.dumps({"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}).encode())
    body = _b64url(json.dumps({"iss": ISSUER, "iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"}).encode())
    read, write = os.pipe()
    try:
        os.write(write, pem)  # far below a pipe's buffer: no deadlock
        os.close(write)
        write = -1
        signed = subprocess.run(["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{read}"], input=f"{head}.{body}".encode(),
                                capture_output=True, pass_fds=(read,))
    finally:
        os.close(read)
        if write >= 0:
            os.close(write)
        del pem
    if signed.returncode != 0:
        raise Stop("openssl could not sign the App Store Connect token", "Check the keychain item holds the base64 of the .p8")
    return f"{head}.{body}.{_b64url(_raw_signature(signed.stdout))}"


def upload_ipa(ipa: str) -> subprocess.CompletedProcess:
    """altool --upload-package with the API key. altool reads the key only from a regular file (a pipe and a named pipe
    are refused), so it is written to a 0600 file in a 0700 folder and removed when altool ends. Only with the owner's
    yes (tools/release --asc-key-file); the repository's rule is that a secret never goes in a file."""
    import shutil
    import tempfile

    got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", KEY_ID, "-w"], capture_output=True)
    if got.returncode != 0:
        raise Stop("no App Store Connect API key in the keychain", f"service {SERVICE}, account {KEY_ID}")
    folder = tempfile.mkdtemp(prefix="pointe-asc-")
    os.chmod(folder, 0o700)
    path = os.path.join(folder, f"AuthKey_{KEY_ID}.p8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(got.stdout.strip()))
        return subprocess.run(["xcrun", "altool", "--upload-package", ipa, "--api-key", KEY_ID, "--api-issuer", ISSUER,
                               "--p8-file-path", path, "--output-format", "normal"], capture_output=True, text=True, timeout=3600)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def get(path: str, params: dict | None = None) -> dict:
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as reply:
            return json.loads(reply.read())
    except urllib.error.HTTPError as e:
        raise Stop(f"App Store Connect answered {e.code} to {path}", "Check the key's role and the app id") from None


def build(version: str, number: int) -> dict | None:
    """The build `number` of `version`: its processing state and its TestFlight state (internal, external)."""
    found = get("builds", {"filter[app]": APP_ID, "filter[version]": str(number), "filter[preReleaseVersion.version]": version,
                           "include": "buildBetaDetail", "limit": "5"})
    if not found.get("data"):
        return None
    b = found["data"][0]
    detail = next((x["attributes"] for x in found.get("included", []) if x["type"] == "buildBetaDetails"), {})
    return {"processing": b["attributes"].get("processingState"), "internal": detail.get("internalBuildState"),
            "external": detail.get("externalBuildState"), "uploaded": b["attributes"].get("uploadedDate")}


def app_store_versions() -> list[dict]:
    got = get(f"apps/{APP_ID}/appStoreVersions", {"limit": "5"})
    return [{"version": v["attributes"]["versionString"], "state": v["attributes"].get("appStoreState")} for v in got.get("data", [])]
