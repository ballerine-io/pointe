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
IPHONE = os.environ.get("POINTE_IPHONE", "")  # the owner's iPhone, by its device identifier, when Xcode knows several


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
    if n == 0:
        # Xcode 27 ("Apple Accounts") keeps the account where this key no longer shows it: an empty list proves nothing.
        # The export and the upload are the real test; they stop with Xcode's own words when the account is missing.
        return Probe("xcode-account", True, "Xcode's account is not readable from its settings here: the export itself will tell",
                     "The owner: Xcode, Settings, Apple Accounts, sign in with team " + TEAM + "'s account. Then: tools/release resume")
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


PROFILES = {"io.ballerine.pointe": os.environ.get("POINTE_IOS_PROFILE", "Pointe App Store"),
            "io.ballerine.pointe.widget": os.environ.get("POINTE_WIDGET_PROFILE", "Pointe Widget App Store")}


def apple_distribution() -> Probe:
    """The iPhone export's manual signing: the Apple Distribution identity and the two App Store profiles by name."""
    out = sh(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"], check=False, timeout=30).stdout
    identity = any("Apple Distribution" in line and f"({TEAM})" in line for line in out.splitlines())
    folder = Path.home() / "Library" / "MobileDevice" / "Provisioning Profiles"
    names = set()
    for f in folder.glob("*.mobileprovision") if folder.is_dir() else []:
        decoded = sh(["/usr/bin/security", "cms", "-D", "-i", str(f)], check=False, timeout=30).stdout
        try:
            names.add(plistlib.loads(decoded.encode()).get("Name"))
        except Exception:  # noqa: BLE001: an unreadable profile is not one of ours
            continue
    missing = [n for n in PROFILES.values() if n not in names]
    ok = identity and not missing
    return Probe("apple-distribution", ok, "the Apple Distribution identity and both App Store profiles are installed" if ok else
                 ("no Apple Distribution identity of team " + TEAM if not identity else "") + (f" missing profiles: {missing}" if missing else ""),
                 'The owner, at developer.apple.com: an "Apple Distribution" certificate in the login keychain, and the App Store '
                 'profiles "Pointe App Store" and "Pointe Widget App Store" (group.io.ballerine.pointe) installed')


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
    """The App Store Connect API key in the login keychain (releasekit/asc.py). Developer role: reads (build processing,
    TestFlight state) work; creating an App Store version, the external group and submissions are refused, so those are
    the owner's, in App Store Connect."""
    from . import asc

    ok = asc.have_key()
    return Probe("asc-key", ok, f"App Store Connect API key {asc.KEY_ID} in the keychain (Developer role: reads only)" if ok
                 else "no App Store Connect API key in the keychain",
                 "The owner, in App Store Connect (appstoreconnect.apple.com): TestFlight, the build, add it to the external group "
                 "and submit it for Beta App Review; App Store, the version, choose the build, Add for Review")


def iphone() -> Probe:
    """The owner's iPhone, paired with Xcode and awake. Names are not printed."""
    out = sh(["xcrun", "devicectl", "list", "devices"], check=False, timeout=60)
    lines = [line for line in out.stdout.splitlines() if "iPhone" in line and (not IPHONE or IPHONE in line)]
    ready = [line for line in lines if "available" in line and "unavailable" not in line]
    return Probe("iphone", bool(ready), f"{len(ready)} iPhone reachable ({len(lines)} known to Xcode)",
                 "The owner unlocks the iPhone, on the same network or by cable, and trusts this Mac; then tools/release resume. "
                 "Otherwise the TestFlight build reaches it through the internal group.")


def docker() -> Probe:
    have = shutil.which("colima") and shutil.which("docker")
    return Probe("colima", bool(have), "colima and docker are installed" if have else "colima or docker is missing",
                 "brew install colima docker (the Linux checks run in a Colima VM of their own, profile pointe-release)")


def ci_signing() -> Probe:
    """The release workflow's secrets in the environment "release" (names only: GitHub never returns a value), and its
    rule that only tags matching v* deploy to it. With them, the disk image and the iPhone build sign in CI and the
    local identities below are the fallback (--local-signing)."""
    from . import ci

    names = ci.secret_names()
    lacking = sorted({n for p in ci.SECRETS for n in ci.missing(p, names)})
    ok = not lacking and ci.protected()
    detail = (f"CI signing: environment {ci.ENVIRONMENT} holds all {len(names)} secrets, deployments from tags {ci.TAG_RULE} only" if ok
              else f"CI signing: environment {ci.ENVIRONMENT} " + (f"lacks {', '.join(lacking)}" if lacking else f"admits more than tags {ci.TAG_RULE}"))
    return Probe("ci-signing", ok, detail, "tools/release_secrets.sh on the owner's Mac (docs/releasing.md, \"Where the secrets live\"); "
                 "until then this Mac signs")


def all_probes(network: bool = True) -> list[Probe]:
    found = [gh_signed_in(), xcode_tools(), keychain_unlocked(), developer_id(), apple_distribution()]
    if network:
        found.insert(1, ci_signing())
    if network and next(p for p in found if p.name == "keychain").ok:
        found.append(notary_profile())
    found += [asc_api_key(), docker()]
    if network:
        found += [wrangler(), iphone()]
    return found
