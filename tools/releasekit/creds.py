"""Every step of a release that needs a person or a secret, asked about without reading the secret.

Each probe answers whether the thing is there and, when it is not, the one thing the owner does. tools/release asks
before the step that needs it, and stops there with that fix and `tools/release resume`; it never signs another way.
Nothing here prints an account name, a team's certificate name or a key.
"""

from __future__ import annotations

import os
import plistlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from .core import sh

TEAM = os.environ.get("POINTE_TEAM", "PP445E78PD")  # the team that publishes Pointe (tools/build_dmg.sh's default)
NOTARY_PROFILE = os.environ.get("POINTE_NOTARY_PROFILE", "pointe-notary")
WRANGLER = "wrangler@4.166.0"  # site/deploy.sh's pin


@dataclass
class Probe:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def gh_signed_in() -> Probe:
    out = sh(["gh", "auth", "status"], check=False, timeout=30)
    return Probe("gh", out.returncode == 0, "gh is signed in" if out.returncode == 0 else "gh is not signed in",
                 "gh auth login (a GitHub account with write access to ballerine-io/pointe)")


def xcode_account() -> Probe:
    """Xcode's Apple Account: the Mac app's export to Apple's notary service and the iPhone upload go through it. 0.9.0
    stopped here when Xcode lost it (DVTDeveloperAccountManagerAppleIDLists empty)."""
    raw = sh(["defaults", "export", "com.apple.dt.Xcode", "-"], check=False, timeout=30).stdout
    try:
        lists = plistlib.loads(raw.encode()).get("DVTDeveloperAccountManagerAppleIDLists") if raw else None
    except Exception:  # noqa: BLE001: an unreadable plist is "no account"
        lists = None

    def count(x) -> int:
        return sum(count(y) for y in x.values()) if isinstance(x, dict) else len(x) if isinstance(x, list) else 0

    n = count(lists) if lists is not None else 0
    return Probe("xcode-account", n > 0, f"Xcode has {n} Apple Account(s)",
                 "The owner: Xcode, Settings, Accounts, +, Apple Account, sign in with the account of team "
                 f"{TEAM} (Account Holder or Admin, for the Developer ID export). Then: tools/release resume")


def keychain_unlocked() -> Probe:
    out = sh(["/usr/bin/security", "show-keychain-info", str(Path.home() / "Library/Keychains/login.keychain-db")], check=False, timeout=15)
    return Probe("keychain", out.returncode == 0, "the login keychain is unlocked" if out.returncode == 0 else "the login keychain is locked",
                 "The owner unlocks the Mac (a locked keychain makes codesign and notarytool hang). Then: tools/release resume")


def developer_id() -> Probe:
    out = sh(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"], check=False, timeout=30).stdout
    n = sum(1 for line in out.splitlines() if "Developer ID Application" in line and f"({TEAM})" in line)
    return Probe("developer-id", n > 0, f"{n} Developer ID Application identity of team {TEAM} in the keychain",
                 f"The owner: Xcode, Settings, Accounts, team {TEAM}, Manage Certificates, +, Developer ID Application")


def notary_profile() -> Probe:
    """notarytool's saved credentials (made once with store-credentials). Asking Apple for the history proves they work."""
    out = sh(["xcrun", "notarytool", "history", "--keychain-profile", NOTARY_PROFILE], check=False, timeout=90)
    return Probe("notary-profile", out.returncode == 0, f"notarytool profile {NOTARY_PROFILE} works" if out.returncode == 0
                 else f"notarytool profile {NOTARY_PROFILE} does not work ({'timed out' if out.returncode == 124 else 'refused or missing'})",
                 f"The owner, once, in a terminal: xcrun notarytool store-credentials {NOTARY_PROFILE} --apple-id <Apple Account> "
                 f"--team-id {TEAM} (it asks for an app-specific password from account.apple.com)")


def xcode_tools() -> Probe:
    missing = [t for t in ("xcodebuild", "hdiutil", "codesign", "ditto", "swift", "tiffutil", "osascript", "xcrun") if not shutil.which(t)]
    return Probe("xcode-tools", not missing, "Xcode's tools are here" if not missing else f"missing: {', '.join(missing)}",
                 "Install Xcode (the App Store) and run it once")


def wrangler() -> Probe:
    """The site deploy: Cloudflare Pages through wrangler, signed in to Ballerine's account."""
    out = sh(["npx", "-y", WRANGLER, "whoami"], check=False, timeout=180)
    ok = out.returncode == 0 and "not authenticated" not in (out.stdout + out.stderr).lower()
    return Probe("wrangler", ok, "wrangler is signed in" if ok else "wrangler is not signed in",
                 f"The owner: npx -y {WRANGLER} login (a Cloudflare user in Ballerine's account with Pages access)")


def asc_api_key() -> Probe:
    """An App Store Connect API key with the App Manager role, for TestFlight's external group, Beta App Review and the App
    Store submission. Kept in the Keychain (service pointe-asc-api-key), never on disk. Today there is none: those steps
    are the owner's, in App Store Connect."""
    out = sh(["/usr/bin/security", "find-generic-password", "-s", "pointe-asc-api-key"], check=False, timeout=15)
    return Probe("asc-key", out.returncode == 0, "an App Store Connect API key is in the Keychain" if out.returncode == 0
                 else "no App Store Connect API key in the Keychain",
                 "The owner, in App Store Connect (appstoreconnect.apple.com): TestFlight, the build, add it to the external group "
                 "and submit it for Beta App Review; App Store, the version, choose the build, Add for Review")


def iphone() -> Probe:
    """The owner's iPhone, paired with Xcode and awake. Names are not printed."""
    out = sh(["xcrun", "devicectl", "list", "devices"], check=False, timeout=60)
    lines = [line for line in out.stdout.splitlines() if "iPhone" in line]
    ready = [line for line in lines if "available" in line and "unavailable" not in line]
    return Probe("iphone", bool(ready), f"{len(ready)} iPhone reachable ({len(lines)} known to Xcode)",
                 "The owner unlocks the iPhone, on the same network or by cable, and trusts this Mac; then tools/release resume. "
                 "Otherwise the TestFlight build reaches it through the internal group.")


def docker() -> Probe:
    have = shutil.which("colima") and shutil.which("docker")
    return Probe("colima", bool(have), "colima and docker are installed" if have else "colima or docker is missing",
                 "brew install colima docker (the Linux checks run in a Colima VM of their own, profile pointe-release)")


def all_probes(network: bool = True) -> list[Probe]:
    found = [gh_signed_in(), xcode_tools(), xcode_account(), keychain_unlocked(), developer_id()]
    if network and found[3].ok:
        found.append(notary_profile())
    found += [asc_api_key(), docker()]
    if network:
        found += [wrangler(), iphone()]
    return found
