"""pointe apps: build Pointe's iPhone and Mac apps from source and install them, one command each (bin/pointe-apps).

    pointe apps doctor       what this Mac has and lacks for each build, with the exact fix
    pointe apps mac          build the Mac app and put it in ~/Applications
    pointe apps ios          build the iPhone app, sign it for your team, install it on your iPhone
    pointe apps ios --sim    build it for the iPhone Simulator and open it there (no Apple account, no iPhone)

Runs on the Python that comes with Xcode (3.9), standard library only, and reaches no network itself: Xcode talks to
Apple when it signs. A Team ID is never printed: output says "your team". The team and the bundle ID are saved where they
outlast an update: in a clone, apps/ios/.team and apps/ios/.bundle-id (gitignored); in the plugin's copy, which Claude Code keeps
one folder per version of, ~/.claude-voice/apps (an older copy's are taken over once, so an update keeps the same app
and its pairing). The committed projects are not changed (the values go on xcodebuild's command line).
Docs: docs/phone.md "Getting the app", docs/mac-app.md "Getting it"."""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(os.environ.get("POINTE_APPS_ROOT") or Path(__file__).resolve().parents[1])
BASE_ID = "io.ballerine.pointe"  # registered to the team that publishes the app: no other team can sign it
TEAM_RE = re.compile(r"[A-Z0-9]{10}")
MIN_XCODE, MIN_IOS, MIN_MACOS = 16, 18, 15
CMD = "pointe apps"


class Stop(Exception):
    """A step failed in a way the person can fix: the message is what happened and what to do."""


# ---------- output ----------

def say(kind: str, text: str) -> None:
    lines = text.splitlines() or [""]
    print(f"{kind:<6}{lines[0]}" if len(kind) < 6 else f"{kind} {lines[0]}")  # "not yet" is longer than the column
    for line in lines[1:]:
        print(f"      {line}")
    sys.stdout.flush()


def ok(text): say("ok", text)
def note(text): say("note", text)
def fix(text): say("fix", text)
def step(text): say("...", text)


def redact(text: str, team: str | None) -> str:
    """Nothing this tool prints carries a Team ID."""
    return text.replace(team, "<your team>") if team else text


# ---------- running tools ----------

def run(cmd: list[str], timeout: float | None = 120) -> tuple[int, str]:
    """(exit code, stdout+stderr). A missing tool is exit 127, a hang is 124: callers explain, never crash."""
    try:
        got = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout, errors="replace")
        return got.returncode, got.stdout
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") if isinstance(e.stdout, str) else ""


def is_clone(root: Path | None = None) -> bool:
    """A git checkout (a clone or a worktree) keeps what it saves beside its sources. The plugin's copy has no .git."""
    return ((root or ROOT) / ".git").exists()


def saved_dir() -> Path:
    """Where the team, the bundle ID and the builds outlast the next plugin version."""
    return Path(os.environ.get("CLAUDE_VOICE_STATE") or Path.home() / ".claude-voice") / "apps"


def build_dir(platform: str) -> Path:
    base = os.environ.get("POINTE_APPS_BUILD")
    if base:
        return Path(base) / platform
    if not is_clone():
        return saved_dir() / "build" / platform
    folder, _, kind = platform.partition("-")  # "ios-sim": beside the device build, under apps/ios/build (gitignored)
    return ROOT / "apps" / folder / "build" / ("apps-" + kind if kind else "apps")


def team_file() -> Path:
    if os.environ.get("POINTE_TEAM_FILE"):
        return Path(os.environ["POINTE_TEAM_FILE"])
    return ROOT / "apps" / "ios" / ".team" if is_clone() else saved_dir() / ".team"


def take_over_saved() -> Path | None:
    """The plugin's copy, the first time it runs: the team and bundle ID an earlier version saved inside its own folder
    (in pre-release builds, ios/.team there), so the build updates the same app on the iPhone instead of adding a second one
    with a new pairing. A clone made before the apps moved under apps/ keeps its two files, untracked, in ios/.
    The newest such folder wins; its two files are copied together, as they belong together.
    Returns the folder taken from, if any."""
    if os.environ.get("POINTE_TEAM_FILE") or team_file().exists():
        return None
    if is_clone():
        found = [ROOT / "ios"]
    else:
        found = [ROOT / "ios", *(p / "ios" for p in ROOT.parent.iterdir() if p != ROOT and p.is_dir())] \
            if ROOT.parent.is_dir() else []
    found = [d for d in found if (d / ".team").is_file()]
    if not found:
        return None
    newest = max(found, key=lambda d: (d / ".team").stat().st_mtime)
    for name in (".team", ".bundle-id"):
        if (newest / name).is_file():
            _write(team_file().with_name(name), (newest / name).read_text().strip())
    return newest


def bundle_file() -> Path:
    return team_file().with_name(".bundle-id")


def profile_dirs() -> list[Path]:
    env = os.environ.get("POINTE_APPS_PROFILES")
    if env:
        return [Path(env)]
    home = Path.home() / "Library"
    return [home / "Developer/Xcode/UserData/Provisioning Profiles", home / "MobileDevice/Provisioning Profiles"]


# ---------- Xcode ----------

def xcode_state() -> dict:
    """What `xcode-select -p` and `xcodebuild -version` say, as problems with their fixes. No problems: Xcode can build."""
    problems: list[tuple[str, str]] = []
    rc, path = run(["xcode-select", "-p"])
    path = path.strip()
    has_app = Path("/Applications/Xcode.app").exists()
    select = "sudo xcode-select -s /Applications/Xcode.app"
    if rc != 0:
        problems.append(("Xcode is not installed.", "Install Xcode from the App Store (free, about 12 GB), open it once, then run this again."
                         if not has_app else f"Xcode is installed but not selected. Run: {select}"))
        return {"problems": problems, "path": "", "version": None}
    rc, out = run(["xcodebuild", "-version"])
    found = re.search(r"Xcode (\d+)(?:\.(\d+))?", out)
    version = found.group(0)[6:] if found else None
    if "license" in out.lower():
        problems.append(("Xcode's license is not accepted yet, so it refuses to build.", "Run: sudo xcodebuild -license accept"))
    elif "CommandLineTools" in path or "requires Xcode" in out:
        problems.append(("The command line tools are selected, not Xcode: they cannot build an app.",
                         f"Run: {select}" if has_app else "Install Xcode from the App Store (free, about 12 GB), open it once, then run: " + select))
    elif rc != 0 or not found:
        problems.append(("xcodebuild does not run.", "Open Xcode once and let it finish installing its components, then run this again.\n"
                         + (out.strip().splitlines() or [""])[-1][:200]))
    elif int(found.group(1)) < MIN_XCODE:
        problems.append((f"Xcode {version} is too old: the apps need Xcode {MIN_XCODE} or newer.", "Update Xcode in the App Store."))
    else:
        rc, _ = run(["xcodebuild", "-checkFirstLaunchStatus"])
        if rc not in (0, 127):
            problems.append(("Xcode has not finished its first-launch setup.", "Run: sudo xcodebuild -runFirstLaunch   (or open Xcode once)"))
    return {"problems": problems, "path": path, "version": version}


def need_xcode() -> None:
    state = xcode_state()
    if state["problems"]:
        what, how = state["problems"][0]
        raise Stop(f"{what}\n{how}")


# ---------- signing: identities, teams, the bundle ID ----------

def _der_strings(der: bytes, oid: bytes) -> list[str]:
    """The values of one X.509 name attribute, in order (issuer first, then subject)."""
    out = []
    for m in re.finditer(re.escape(b"\x06\x03" + oid) + rb"[\x0c\x13\x14\x16]", der):
        size = der[m.end()]
        if size < 0x80:
            out.append(der[m.end() + 1:m.end() + 1 + size].decode("utf-8", "replace"))
    return out


def teams_from_pem(pem: str) -> dict[str, str]:
    """{Team ID: team name} for each Apple Development certificate. The team is the subject's OU; the ten characters
    in the certificate's name are the person's ID, not the team's."""
    teams: dict[str, str] = {}
    for block in re.findall(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", pem, re.S):
        try:
            der = base64.b64decode(block)
        except ValueError:
            continue
        units = [u for u in _der_strings(der, b"\x55\x04\x0b") if TEAM_RE.fullmatch(u)]
        orgs = _der_strings(der, b"\x55\x04\x0a")
        if units:
            teams.setdefault(units[-1], orgs[-1] if orgs else "")
    return teams


def signing_state() -> dict:
    """Code-signing identities in the keychain and the teams they belong to."""
    rc, out = run(["security", "find-identity", "-v", "-p", "codesigning"])
    names = re.findall(r'^\s*\d+\) [0-9A-F]{40} "((?:Apple|iPhone|Mac) Develop[^"]*)"', out, re.M) if rc == 0 else []
    teams: dict[str, str] = {}
    if names:
        for common in ("Apple Development", "iPhone Developer", "Mac Developer"):
            rc, pem = run(["security", "find-certificate", "-a", "-c", common, "-p"])
            if rc == 0:
                for team, name in teams_from_pem(pem).items():
                    teams.setdefault(team, name)
    return {"identities": len(names), "teams": teams}


NO_IDENTITY = """No Apple Development certificate on this Mac yet. A free Apple Account is enough. Once:
  1. Open Xcode, then Settings (Cmd-,), Accounts, the + button, Apple Account, and sign in.
  2. Select the account, press Manage Certificates, the + button, Apple Development.
Xcode then holds a signing certificate in your keychain, and this command finds your team by itself."""


def stored_team() -> str | None:
    try:
        team = "".join(team_file().read_text().split())
    except OSError:
        return None
    return team if TEAM_RE.fullmatch(team) else None


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n")
    path.chmod(0o600)


def resolve_team(args, signing: dict | None = None, quiet: bool = False) -> str | None:
    """--team, else the saved team, else the one team this Mac has a certificate for, else ask. None: no team at all."""
    saved = stored_team()
    chosen, how = None, ""
    if args.team:
        if not TEAM_RE.fullmatch(args.team):
            raise Stop("--team takes a Team ID: ten capital letters and digits (Xcode shows it under Signing & Capabilities).")
        chosen, how = args.team, "from --team"
    elif saved:
        return saved
    else:
        teams = (signing or signing_state())["teams"]
        if len(teams) == 1:
            chosen, how = next(iter(teams)), "the only team with a certificate on this Mac"
        elif len(teams) > 1:
            chosen, how = ask_team(teams), "your choice"
    if chosen and chosen != saved and not args.dry_run:
        _write(team_file(), chosen)
        if saved and bundle_file().exists() and not os.environ.get("POINTE_BUNDLE_ID"):
            bundle_file().unlink()  # a bundle ID registered to the old team cannot be signed by the new one
        if not quiet:
            ok(f"Using your team ({how}); saved in {shown(team_file())}" + (", which git ignores." if is_clone() else "."))
    return chosen


def ask_team(teams: dict[str, str]) -> str:
    ids = sorted(teams, key=lambda t: (teams[t].lower(), t))
    labels = [teams[t] or "a team" for t in ids]
    labels = [f"{label} (ID ending {t[-3:]})" if labels.count(label) > 1 else label for label, t in zip(labels, ids)]
    listing = "\n".join(f"  {n}. {label}" for n, label in enumerate(labels, 1))
    if not sys.stdin.isatty():
        raise Stop(f"This Mac has certificates for {len(ids)} teams:\n{listing}\nChoose one: run again in a terminal, or pass --team <Team ID>.")
    print(f"This Mac has certificates for {len(ids)} teams:\n{listing}")
    while True:
        answer = input(f"Which team signs Pointe? [1-{len(ids)}] ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(ids):
            return ids[int(answer) - 1]


def read_profile(path: Path) -> dict | None:
    """A .mobileprovision is a signed envelope around a property list: take the list out."""
    try:
        blob = path.read_bytes()
        return plistlib.loads(blob[blob.index(b"<?xml"):blob.index(b"</plist>") + 8])
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def team_owns_base_id(team: str) -> bool:
    """True when Xcode already made this team a profile for io.ballerine.pointe: only the team that owns the ID has one."""
    for folder in profile_dirs():
        for path in sorted(folder.glob("*.mobileprovision")) if folder.is_dir() else []:
            profile = read_profile(path) or {}
            if (profile.get("Entitlements") or {}).get("application-identifier") == f"{team}.{BASE_ID}":
                return True
    return False


def derived_bundle_id(team: str) -> str:
    """A bundle ID of your own: Apple gives each ID to one team, and io.ballerine.pointe is taken."""
    return f"{BASE_ID}.dev{hashlib.sha256(team.encode()).hexdigest()[:8]}"


def resolve_bundle_id(args, team: str) -> tuple[str, str]:
    """(bundle ID, why). Saved in apps/ios/.bundle-id so every later build updates the same app."""
    explicit = args.bundle_id or os.environ.get("POINTE_BUNDLE_ID")
    if explicit:
        if not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", explicit):
            raise Stop(f"'{explicit}' is not a bundle ID: use letters, digits, hyphens and dots, like com.example.pointe.")
        chosen, why = explicit, "the one you gave"
    else:
        try:
            saved = bundle_file().read_text().strip()
        except OSError:
            saved = ""
        if saved:
            return saved, f"saved in {shown(bundle_file())}"
        if team_owns_base_id(team):
            chosen, why = BASE_ID, "your team owns it"
        else:
            chosen, why = derived_bundle_id(team), f"your own: {BASE_ID} belongs to the team that publishes the app"
    if not args.dry_run:
        _write(bundle_file(), chosen)
    return chosen, why


def shown(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path).replace(str(Path.home()), "~", 1)


# ---------- devices ----------

def list_iphones() -> tuple[list[dict], str]:
    """Physical iPhones and iPads Xcode knows, from `devicectl list devices`. (devices, error text)."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "devices.json"
        rc, out = run(["xcrun", "devicectl", "list", "devices", "--json-output", str(target)], timeout=60)
        try:
            data = json.loads(target.read_text())
        except (OSError, ValueError):
            return [], out.strip() or "devicectl gave no device list"
    return parse_devices(data), ""


def parse_devices(data: dict) -> list[dict]:
    devices = []
    for raw in (data.get("result") or {}).get("devices") or []:
        props = raw.get("properties") or {}
        hardware = props.get("hardware") or raw.get("hardwareProperties") or {}
        if hardware.get("reality", "physical") != "physical" or hardware.get("platform") not in ("iOS", "iPadOS"):
            continue
        connection = props.get("connection") or raw.get("connectionProperties") or {}
        state = props.get("state") or {}
        old = raw.get("deviceProperties") or {}
        mode = state.get("developerModeStatus", old.get("developerModeStatus"))
        if isinstance(mode, dict):
            mode = next(iter(mode), None)
        version = (props.get("software") or {}).get("osVersionNumber") or old.get("osVersionNumber") or ""
        if isinstance(version, dict):
            version = version.get("stringValue", "")
        devices.append({
            "udid": hardware.get("udid") or raw.get("identifier") or "",
            "name": state.get("name") or old.get("name") or hardware.get("marketingName") or "iPhone",
            "model": hardware.get("marketingName") or hardware.get("deviceType") or "iPhone",
            "os": version,
            "paired": connection.get("pairingState") == "paired",
            "connected": (connection.get("state") or connection.get("tunnelState")) == "connected",
            "transport": connection.get("transportType") or "",
            "developer_mode": mode,
        })
    return devices


UNAVAILABLE = """Xcode knows this iPhone but cannot reach it right now. Do these, then run the command again:
  - Unlock the iPhone and keep its screen on.
  - Plug it into this Mac with a cable, or put both on the same Wi-Fi (a VPN on either one can block it).
  - If the iPhone asks "Trust This Computer?", tap Trust and enter its passcode."""
NO_DEVICE = """No iPhone found. Plug the iPhone into this Mac with a cable, unlock it, and tap Trust when it asks
"Trust This Computer?". Then run the command again. No iPhone at hand: `{cmd} ios --sim` runs the app in the Simulator."""
DEVELOPER_MODE = """Developer Mode is off on the iPhone, and iOS runs an app built from source only with it on.
On the iPhone: Settings, Privacy & Security, Developer Mode (at the bottom), turn it on, restart when it asks, then
confirm after the restart. The row appears only after the iPhone has been connected to a Mac with Xcode."""
NOT_PAIRED = """The iPhone has not trusted this Mac. Plug it in with a cable and unlock it. When it asks
"Trust This Computer?", tap Trust and enter its passcode. Then run the command again."""
TRUST_DEVELOPER = """iOS has not been told to trust apps signed by you (it asks once per Apple Account, on a free team).
On the iPhone: Settings, General, VPN & Device Management, your Apple Account under Developer App, Trust.
Then open Pointe from the home screen."""


def device_problem(device: dict) -> str | None:
    if not device["paired"]:
        return NOT_PAIRED
    if not device["connected"]:
        return UNAVAILABLE
    if device["developer_mode"] == "disabled":
        return DEVELOPER_MODE
    major = re.match(r"\d+", device["os"] or "")
    if major and int(major.group()) < MIN_IOS:
        return f"This iPhone runs iOS {device['os']}; Pointe needs iOS {MIN_IOS} or newer. Update it in Settings, General, Software Update."
    return None


def pick_iphone(args) -> dict:
    devices, error = list_iphones()
    if args.device:
        wanted = [d for d in devices if args.device in (d["udid"], d["name"])]
        if not wanted:
            raise Stop(f"No iPhone called or identified '{args.device}'. `{CMD} doctor` lists the ones Xcode sees.")
        return wanted[0]
    if not devices:
        raise Stop(NO_DEVICE.format(cmd=CMD) + (f"\n(devicectl said: {error.splitlines()[-1][:160]})" if error else ""))
    ready = [d for d in devices if not device_problem(d)]
    pool = ready or devices
    if len(pool) == 1:
        return pool[0]
    listing = "\n".join(f"  {n}. {d['name']} ({d['model']})" for n, d in enumerate(pool, 1))
    if not sys.stdin.isatty():
        raise Stop(f"More than one iPhone:\n{listing}\nRun again in a terminal to choose, or pass --device <name>.")
    print(f"More than one iPhone:\n{listing}")
    while True:
        answer = input(f"Which one? [1-{len(pool)}] ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(pool):
            return pool[int(answer) - 1]


def runtime_version(runtime: str) -> list[int]:
    """[27, 2] from "com.apple.CoreSimulator.SimRuntime.iOS-27-2"; a device-specific runtime adds a suffix, ignored."""
    found = re.search(r"iOS-(\d+)(?:-(\d+))?(?:-(\d+))?(?![\d])", runtime)
    return [int(n) for n in found.groups() if n] if found else [0]


def pick_simulator(args) -> dict:
    rc, out = run(["xcrun", "simctl", "list", "devices", "available", "-j"])
    try:
        runtimes = json.loads(out)["devices"]
    except (ValueError, KeyError):
        raise Stop("The Simulator's device list could not be read. Open Xcode once, then run this again.")
    phones = []
    for runtime in sorted((r for r in runtimes if "iOS" in r), key=lambda r: (runtime_version(r), -len(r)), reverse=True):
        phones += [dict(sim, runtime=runtime) for sim in runtimes[runtime] if sim.get("name", "").startswith("iPhone")]
    if args.device:
        phones = [s for s in phones if args.device in (s["udid"], s["name"])]
    if not phones:
        raise Stop(f"No iPhone simulator called '{args.device}'." if args.device else
                   "No iPhone simulator is installed. Open Xcode, Settings, Components, and get iOS; or run: xcodebuild -downloadPlatform iOS")
    booted = [s for s in phones if s.get("state") == "Booted"]
    return (booted or phones)[0]


# ---------- building ----------

DIAGNOSES = [  # (pattern in xcodebuild's or devicectl's output, what it means and what to do)
    (r"not agreed to the Xcode license|license requires admin|xcodebuild -license",
     "Xcode's license is not accepted yet.\nRun: sudo xcodebuild -license accept"),
    (r"requires Xcode, but active developer directory",
     "The command line tools are selected, not Xcode.\nRun: sudo xcode-select -s /Applications/Xcode.app"),
    (r"cannot be registered to your development team because it is not available|Failed to register bundle identifier",
     "Apple says this bundle ID is taken by another team: each ID belongs to one team.\n"
     "Delete {bundle_file} and run the command again to get an ID of your own, or pass --bundle-id com.<yourname>.pointe."),
    (r"application-groups",
     "The profile has no App Groups even for the build without the group: open apps/ios/Pointe.xcodeproj in Xcode once, pick\n"
     "your team under Signing & Capabilities for Pointe and PointeWidget, then run the command again."),
    (r"maximum App ID limit|may create up to \d+ App IDs",
     "A free Apple Account may register 10 new bundle IDs every 7 days, and this account reached that.\n"
     "Run the command again without --bundle-id so it reuses the saved one, or wait until the oldest one is 7 days old."),
    (r"No Accounts?: Add a new account|No Account for Team|Unable to log in with account|session has expired|Please log in",
     "Xcode is not signed in to the Apple Account of your team (or the sign-in expired).\n"
     "Open Xcode, Settings (Cmd-,), Accounts: add the account or sign in again. If the saved team is wrong, pass --team <Team ID>."),
    (r"No signing certificate|No .*(Development|Developer).* signing certificate|no valid signing identit",
     NO_IDENTITY),
    (r"requires a development team", "No team was given to Xcode.\n" + NO_IDENTITY),
    (r"has no devices from which to generate a provisioning profile|doesn't include the currently selected device",
     "Apple has not registered this iPhone for your team yet, so there is no profile to sign with.\n"
     "Connect and unlock the iPhone, then run the command again: it registers the iPhone while it builds."),
    (r"errSecInternalComponent|User interaction is not allowed",
     "The keychain that holds your signing certificate is locked (common over SSH).\n"
     "Run: security unlock-keychain ~/Library/Keychains/login.keychain-db   then run the command again."),
    (r"is not installed\. .*download and install the platform|Unable to find a destination matching",
     "Xcode lacks the iOS version this build needs.\nOpen Xcode, Settings, Components, and get iOS; or run: xcodebuild -downloadPlatform iOS"),
    (r"Developer Mode", DEVELOPER_MODE),
    (r"profile has not been explicitly trusted|invalid code signature, inadequate entitlements", TRUST_DEVELOPER),
    (r"provisioning profile.*(expired|has expired)|profile .* expired|A valid provisioning profile for this executable was not found|ApplicationVerificationFailed",
     "The signature the iPhone has is not valid for this build: on a free team a profile lasts 7 days.\n"
     "Run the command again: it signs with a fresh profile and installs over the old copy, keeping the app's data."),
    (r"device is locked|could not be,? unlocked|DeviceLocked|passcode protected",
     "The iPhone is locked. Unlock it, keep the screen on, and run the command again."),
    (r"not paired|pairing|trust this computer", NOT_PAIRED),
    (r"\b4016\b|device is unavailable|device (was )?not connected|not connected|tunnel|timed out|kAMDMuxConnect|unavailable", UNAVAILABLE),
    (r"No space left on device", "The disk is full. Free about 10 GB (the build's own files go in {build}) and run the command again."),
]


def diagnose(output: str) -> str | None:
    for pattern, advice in DIAGNOSES:
        if re.search(pattern, output, re.I):
            return advice.format(bundle_file=shown(bundle_file()), build="apps/ios/build and apps/macos/build")
    return None


def printable(cmd: list[str], team: str | None) -> str:
    def quote(word):
        return word if re.fullmatch(r"[\w@%+=:,./-]+", word) else "'" + word.replace("'", "'\\''") + "'"
    return redact(" ".join(quote(w) for w in cmd), team)


def xcodebuild(cmd: list[str], log: Path, team: str | None, what: str) -> tuple[bool, str]:
    """Run one build with its whole output in a log file; on failure the caller explains from the output."""
    log.parent.mkdir(parents=True, exist_ok=True)
    step(f"{what} (the first build takes a few minutes; later ones are quick)")
    started = time.time()
    rc, out = run(cmd, timeout=None)
    log.write_text(out)
    if rc == 0:
        ok(f"Built in {int(time.time() - started)} s.")
    return rc == 0, out


def explain_failure(out: str, log: Path, team: str | None, what: str) -> Stop:
    errors = [line.strip() for line in out.splitlines() if re.search(r"\berror:|ERROR:|\*\* BUILD FAILED", line)]
    shown_errors = "\n".join(dict.fromkeys(redact(e, team)[:300] for e in errors[:6]))
    advice = diagnose(out)
    text = f"{what} failed."
    if shown_errors:
        text += f"\n{shown_errors}"
    text += f"\n\n{advice}" if advice else f"\nNothing here matched a known cause; `{CMD} doctor` checks the setup."
    return Stop(text + f"\nFull log: {shown(log)}")


def plan(args, cmd: list[str], team: str | None, lines: list[str]) -> int:
    print("Dry run: nothing is built, installed or saved. This is what would happen:\n")
    for line in lines:
        print(f"  {line}")
    print(f"\n  $ {printable(cmd, team)}\n")
    return 0


# ---------- mac ----------

def mac_build_cmd(out: Path, team: str | None, bundle: str | None) -> list[str]:
    cmd = ["xcodebuild", "build", "-project", str(ROOT / "apps" / "macos" / "PointeMac.xcodeproj"), "-scheme", "PointeMac",
           "-configuration", "Release", "-derivedDataPath", str(out / "dd"), "-destination", "platform=macOS", "-quiet",
           # a plain build signs in get-task-allow: any process of the user could attach and record under the mic grant
           "CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO"]
    if team:  # your certificate: macOS remembers the microphone permission across rebuilds
        return cmd + ["-allowProvisioningUpdates", f"DEVELOPMENT_TEAM={team}", "CODE_SIGN_IDENTITY=Apple Development",
                      "CODE_SIGN_STYLE=Automatic", f"PRODUCT_BUNDLE_IDENTIFIER={bundle}.mac"]
    return cmd + ["CODE_SIGN_IDENTITY=-", "DEVELOPMENT_TEAM="]  # "Sign to Run Locally": no Apple Account at all


def install_dir(args) -> Path:
    return Path(args.dest or os.environ.get("POINTE_APPS_INSTALL_DIR") or Path.home() / "Applications").expanduser()


def cmd_mac(args) -> int:
    if not args.dry_run:
        need_xcode()
    signing = signing_state()
    team = None
    if not args.adhoc:
        if signing["identities"] or args.team:
            team = resolve_team(args, signing)
        elif stored_team():
            note("The saved team has no certificate on this Mac, so this build is signed to run locally instead.")
    bundle = resolve_bundle_id(args, team)[0] if team else None
    out = build_dir("macos")
    target = install_dir(args) / "Pointe.app"
    cmd = mac_build_cmd(out, team, bundle)
    signed = "your team's Apple Development certificate" if team else "an ad hoc signature (Sign to Run Locally: no Apple Account needed)"
    if args.dry_run:
        return plan(args, cmd, team, [f"Signing: {signed}.", f"Bundle ID: {bundle + '.mac' if team else BASE_ID + '.mac'}",
                                      f"Install: quit a running copy, then replace {shown(target)}."])
    good, output = xcodebuild(cmd, out / "build.log", team, f"Building the Mac app, signed with {signed}")
    if not good and team:
        note("Signing with your team did not work, so this build is signed to run locally instead. Why it failed:\n"
             + str(explain_failure(output, out / "build-team.log", team, "The signed build")).split("\n\n", 1)[-1])
        (out / "build-team.log").write_text(output)
        team = None
        good, output = xcodebuild(mac_build_cmd(out, None, None), out / "build.log", None, "Building the Mac app again, signed to run locally")
    if not good:
        raise explain_failure(output, out / "build.log", team, "The Mac build")
    app = out / "dd" / "Build" / "Products" / "Release" / "Pointe.app"
    if not app.is_dir():
        raise Stop(f"The build finished but {shown(app)} is not there. Full log: {shown(out / 'build.log')}")
    was_running = quit_app(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    rc, text = run(["ditto", str(app), str(target)])
    if rc != 0:
        raise Stop(f"Copying the app to {shown(target)} failed: {text.strip()[-200:]}")
    ok(f"Installed {shown(target)}" + (" (replaced the older copy, which was running: it was quit first)." if was_running else "."))
    note("macOS opens it without a Gatekeeper warning: Gatekeeper checks downloads, and this app was built on this Mac.\n"
         + ("The microphone permission is kept across rebuilds, because your certificate signs each one."
            if team else "It is signed for this Mac only, without a certificate, so macOS asks for the microphone again after each rebuild.")
         + "\nTo start it at login: in the app, Settings, General, \"Open Pointe at login\"."
         + "\nThe app needs the Pointe plugin too (README, Install): it talks to the plugin's daemon on this Mac.")
    if args.open or was_running or (sys.stdin.isatty() and not args.no_open and input("Open Pointe now? [Y/n] ").strip().lower() in ("", "y", "yes")):
        run(["open", str(target)])
        ok("Opened Pointe: look for its mark in the menu bar.")
    else:
        note(f"Open it from Spotlight, or: open {shown(target)}")
    return 0


def quit_app(target: Path) -> bool:
    """Stop the copy that runs from the install path (and only that one: a simulator's Pointe is another process)."""
    binary = re.escape(str(target / "Contents" / "MacOS" / "Pointe"))  # pgrep -f takes a pattern
    rc, out = run(["pgrep", "-f", binary])
    pids = [p for p in out.split() if p.isdigit()] if rc == 0 else []
    if not pids:
        return False
    step("Pointe is running: quitting it to replace it")
    run(["kill"] + pids)
    for _ in range(50):
        if run(["pgrep", "-f", binary])[0] != 0:
            break
        time.sleep(0.1)
    return True


# ---------- ios ----------

def ios_build_cmd(out: Path, destination: str, team: str | None, bundle: str | None, group: bool = True) -> list[str]:
    """POINTE_BUNDLE_ID, not PRODUCT_BUNDLE_IDENTIFIER: the project derives the app's ID, its widget's (.widget) and their
    app group (group.<ID>) from it. PRODUCT_BUNDLE_IDENTIFIER on the command line gives every target the app's ID.
    `group`: sign with the app group the widget reads (POINTE_SHARE_GROUP). A free Personal Team's profiles carry none,
    so its build is made again without it (cmd_ios); the Simulator needs no profile and always has it."""
    cmd = ["xcodebuild", "build", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe",
           "-derivedDataPath", str(out / "dd"), "-destination", destination, "-quiet", f"POINTE_SHARE_GROUP={'YES' if group else 'NO'}"]
    if team:
        return cmd + ["-configuration", "Release", "-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration",
                      f"DEVELOPMENT_TEAM={team}", "CODE_SIGN_STYLE=Automatic", f"POINTE_BUNDLE_ID={bundle}"]
    return cmd + ["-configuration", "Debug"]


NO_APP_GROUP = re.compile(r"application-groups")  # the profile lacks the entitlement: a free Personal Team

def cmd_ios(args) -> int:
    if args.sim:
        return ios_sim(args)
    if not args.dry_run:
        need_xcode()
    signing = signing_state()
    team = resolve_team(args, signing)
    if not team:
        raise Stop(NO_IDENTITY + f"\nNo Apple Account at all: `{CMD} ios --sim` runs the app in the Simulator.")
    out = build_dir("ios")
    if args.dry_run:
        bundle, why = resolve_bundle_id(args, team)
        devices, _ = list_iphones()
        device = next((d for d in devices if args.device in (None, d["udid"], d["name"])), None)
        cmd = ios_build_cmd(out, "id=" + (device["udid"] if device else "<your iPhone>"), team, bundle)
        return plan(args, cmd, team, [
            "Signing: your team, automatic. Xcode makes the certificate and profile and registers the iPhone.",
            f"Bundle ID: {bundle} ({why}).",
            "iPhone: " + (f"{device['name']} ({device['model']})" + (": not ready, see doctor" if device_problem(device) else "") if device else "none connected: the real run stops here and says what to do"),
            "Then: xcrun devicectl device install app --device <your iPhone> " + shown(out / "dd/Build/Products/Release-iphoneos/Pointe.app"),
        ])
    device = pick_iphone(args)
    problem = device_problem(device)
    if problem:
        raise Stop(f"{device['name']} ({device['model']}) is not ready.\n{problem}")
    ok(f"iPhone: {device['name']} ({device['model']}, iOS {device['os']}), over {'Wi-Fi' if device['transport'] == 'localNetwork' else 'cable'}.")
    bundle, why = resolve_bundle_id(args, team)
    ok(f"Bundle ID: {bundle} ({why}).")
    log = out / "build.log"
    good, output = xcodebuild(ios_build_cmd(out, f"id={device['udid']}", team, bundle), log, team, "Building the iPhone app and signing it for your team")
    if not good and NO_APP_GROUP.search(output):
        note("Your team's profiles have no App Groups (a free Personal Team has none), so the app is built again without the\n"
             "group it shares with its widget. Talk to Pointe works the same (the Control, the Action button, the Live\n"
             "Activity); the Home Screen widget cannot show your Mac's status and says to tap to talk.")
        good, output = xcodebuild(ios_build_cmd(out, f"id={device['udid']}", team, bundle, group=False), log, team,
                                  "Building the iPhone app again, without the app group")
    if not good:
        raise explain_failure(output, log, team, "The iPhone build")
    app = out / "dd" / "Build" / "Products" / "Release-iphoneos" / "Pointe.app"
    if not app.is_dir():
        raise Stop(f"The build finished but {shown(app)} is not there. Full log: {shown(log)}")
    step(f"Installing on {device['name']}")
    rc, text = run(["xcrun", "devicectl", "device", "install", "app", "--device", device["udid"], str(app)], timeout=600)
    (out / "install.log").write_text(text)
    if rc != 0:
        raise explain_failure(text, out / "install.log", team, "Installing on the iPhone")
    ok("Installed. An older copy is replaced in place: pairing and settings stay.")
    expiry_note(app)
    if not args.no_launch:
        rc, text = run(["xcrun", "devicectl", "device", "process", "launch", "--device", device["udid"], bundle], timeout=60)
        if rc == 0:
            ok("Opened Pointe on the iPhone.")
        else:
            note("Pointe is installed but did not open by itself.\n" + (diagnose(text) or "Unlock the iPhone and open Pointe from the home screen.")
                 + ("" if "VPN & Device Management" in (diagnose(text) or "") else
                    "\nIf iOS says \"Untrusted Developer\": Settings, General, VPN & Device Management, your Apple Account, Trust."))
    note("Next: pair it with this Mac. On Pointe's page: Settings, Phone, Connect your phone (docs/phone.md, Pairing).")
    return 0


def expiry_note(app: Path, now: datetime.datetime | None = None) -> None:
    """Say when this build stops opening, from the profile Xcode put inside it."""
    profile = read_profile(app / "embedded.mobileprovision") or {}
    made, ends = profile.get("CreationDate"), profile.get("ExpirationDate")
    if not (isinstance(made, datetime.datetime) and isinstance(ends, datetime.datetime)):
        return
    ends = ends.replace(tzinfo=datetime.timezone.utc)
    left = ends - (now or datetime.datetime.now(datetime.timezone.utc))
    until = ends.astimezone().strftime("%A %d %B, %H:%M")
    remaining = f"{left.days} days" if left.days >= 2 else f"{max(int(left.total_seconds() // 3600), 0)} hours"
    if ends.replace(tzinfo=None) - made <= datetime.timedelta(days=8):
        note(f"Free Apple Account: Apple signs for 7 days at a time. This build opens until {until} ({remaining} from now).\n"
             "Xcode keeps one profile until it ends, so a rebuild inside those 7 days ends at the same moment.\n"
             f"When the app stops opening, run `{CMD} ios` again: it signs for 7 more days and installs over the old copy, keeping its data.")
    else:
        note(f"This build opens until {until} (your team's development profile). Run the command again after that to renew it.")


def ios_sim(args) -> int:
    if not args.dry_run:
        need_xcode()
    sim = pick_simulator(args)
    out = build_dir("ios-sim")
    cmd = ios_build_cmd(out, f"id={sim['udid']}", None, None)
    label = f"{sim['name']} (iOS {'.'.join(str(n) for n in runtime_version(sim['runtime']))})"
    if args.dry_run:
        return plan(args, cmd, None, ["Signing: none needed, the Simulator runs unsigned builds. No Apple Account, no iPhone.",
                                      f"Simulator: {label}.", f"Then: boot it, install the app, open it ({BASE_ID})."])
    log = out / "build.log"
    good, output = xcodebuild(cmd, log, None, f"Building the iPhone app for the Simulator, {label}")
    if not good:
        raise explain_failure(output, log, None, "The Simulator build")
    app = out / "dd" / "Build" / "Products" / "Debug-iphonesimulator" / "Pointe.app"
    if sim.get("state") != "Booted":
        run(["xcrun", "simctl", "boot", sim["udid"]])
    run(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", sim["udid"]])
    run(["xcrun", "simctl", "bootstatus", sim["udid"]], timeout=180)
    rc, text = run(["xcrun", "simctl", "install", sim["udid"], str(app)], timeout=180)
    if rc != 0:
        raise Stop(f"Installing in the Simulator failed: {text.strip()[-300:]}\nFull build log: {shown(log)}")
    rc, text = run(["xcrun", "simctl", "launch", sim["udid"], BASE_ID] + (["-demo"] if args.demo else []), timeout=60)
    if rc != 0:
        raise Stop(f"The app is installed in the Simulator but did not open: {text.strip()[-300:]}")
    ok(f"Pointe is open in the Simulator, on {label}.")
    note("The Simulator uses this Mac's microphone and reaches Pointe on this Mac directly. It has no Face ID hardware:\n"
         "Features, Face ID, Enrolled in the Simulator's menu, then Matching Face when the app asks."
         + ("" if args.demo else f"\nTo look around without a daemon: `{CMD} ios --sim --demo` opens it with invented sessions."))
    return 0


# ---------- doctor ----------

def cmd_doctor(args) -> int:
    ready = {"mac": True, "ios --sim": True, "ios": True}
    blockers: dict[str, list[str]] = {name: [] for name in ready}

    def block(names, why):
        for name in names:
            ready[name] = False
            blockers[name].append(why)

    xcode = xcode_state()
    if xcode["problems"]:
        for what, how in xcode["problems"]:
            fix(f"{what}\n{how}")
        block(ready, "Xcode")
    else:
        ok(f"Xcode {xcode['version']}, selected and licensed.")

    mac = [int(n) for n in re.findall(r"\d+", (run(["sw_vers", "-productVersion"])[1] or "0"))[:1]] or [0]
    if mac[0] and mac[0] < MIN_MACOS:
        fix(f"macOS {mac[0]}: the Mac app needs macOS {MIN_MACOS} or newer.")
        block(["mac"], f"macOS {MIN_MACOS}")

    free = shutil.disk_usage(Path.home()).free / 1e9
    if free < 4:
        fix(f"Disk: {free:.0f} GB free. A build needs about 4 GB. Free some space.")
        block(ready, "disk space")
    elif free < 10:
        note(f"Disk: {free:.0f} GB free. Enough to build, but Xcode slows down when a disk is nearly full.")
    else:
        ok(f"Disk: {free:.0f} GB free.")

    signing = signing_state()
    team = stored_team()
    if signing["identities"]:
        many = len(signing["teams"])
        ok(f"Signing: an Apple Development certificate is in your keychain ({'one team' if many == 1 else f'{many} teams'}).")
        if team:
            ok(f"Team: saved in {shown(team_file())}" + ("." if team in signing["teams"] or not signing["teams"] else ", but this Mac has no certificate for it: pass --team to change it."))
        elif many == 1:
            ok("Team: the one team is picked by itself on the first build.")
        else:
            note(f"Team: more than one. The first build asks which, or pass --team <Team ID>.")
    else:
        note(NO_IDENTITY + "\nThe Mac app and the Simulator do not need this: only a real iPhone does.")
        block(["ios"], "a signing certificate")
    effective = team or (next(iter(signing["teams"])) if len(signing["teams"]) == 1 else None)
    if effective:
        args.dry_run = True  # doctor saves nothing
        bundle, why = resolve_bundle_id(args, effective)
        ok(f"Bundle ID for your builds: {bundle} ({why}).")

    if not xcode["problems"]:
        rc, out = run(["xcrun", "simctl", "list", "devices", "available", "-j"])
        try:
            has_sim = any(s.get("name", "").startswith("iPhone") for r, sims in json.loads(out)["devices"].items() if "iOS" in r for s in sims)
        except (ValueError, KeyError):
            has_sim = False
        if has_sim:
            ok("Simulator: an iPhone simulator is installed.")
        else:
            fix("Simulator: no iPhone simulator. Open Xcode, Settings, Components, and get iOS; or run: xcodebuild -downloadPlatform iOS")
            block(["ios --sim"], "an iOS simulator")
        devices, error = list_iphones()
        if not devices:
            note(NO_DEVICE.format(cmd=CMD))
            block(["ios"], "an iPhone")
        for device in devices:
            problem = device_problem(device)
            title = f"iPhone: {device['name']} ({device['model']}, iOS {device['os'] or '?'})"
            if problem:
                fix(f"{title}: not ready.\n{problem}")
            else:
                ok(f"{title}: paired, reachable over {'Wi-Fi' if device['transport'] == 'localNetwork' else 'cable'}, Developer Mode on.")
        if devices and all(device_problem(d) for d in devices):
            block(["ios"], "the iPhone to be ready")

    print()
    for name, good in ready.items():
        line = f"{CMD} {name}"
        say("ready" if good else "not yet", f"{line:<22}" + ("" if good else "needs " + ", ".join(dict.fromkeys(blockers[name]))))
    return 0 if ready["mac"] or ready["ios --sim"] else 1


# ---------- entry ----------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=CMD, description="Build Pointe's iPhone and Mac apps from source and install them.",
                                epilog="Docs: docs/phone.md (Getting the app), docs/mac-app.md (Getting it).")
    sub = p.add_subparsers(dest="command", metavar="doctor | mac | ios")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--team", help="your Apple Team ID, when this Mac has more than one (saved for next time)")
    common.add_argument("--bundle-id", help="a bundle ID of your own instead of the derived one (saved for next time)")
    common.add_argument("--dry-run", action="store_true", help="show what would run; build, install and save nothing")
    sub.add_parser("doctor", parents=[common], help="check Xcode, signing, the iPhone and disk space, with the fix for each")
    mac = sub.add_parser("mac", parents=[common], help="build the Mac app and install it in ~/Applications")
    mac.add_argument("--adhoc", action="store_true", help="sign to run locally even when a team is available")
    mac.add_argument("--dest", help="the folder to install into instead of ~/Applications (only a copy running from there is quit)")
    mac.add_argument("--open", action="store_true", help="open the app when it is installed")
    mac.add_argument("--no-open", action="store_true", help="do not ask to open it")
    ios = sub.add_parser("ios", parents=[common], help="build the iPhone app and install it on your iPhone (or --sim)")
    ios.add_argument("--sim", action="store_true", help="build for the iPhone Simulator and open it there")
    ios.add_argument("--demo", action="store_true", help="with --sim: open with invented sessions, no daemon needed")
    ios.add_argument("--device", help="the iPhone (or simulator) to use, by name or identifier")
    ios.add_argument("--no-launch", action="store_true", help="install without opening the app on the iPhone")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not args.command:
        p.print_help()
        return 2
    try:
        if args.command != "doctor" and not getattr(args, "dry_run", False) and take_over_saved():
            note(f"Using the team and bundle ID an earlier version of Pointe saved; now kept in {shown(team_file().parent)}.")
        return {"doctor": cmd_doctor, "mac": cmd_mac, "ios": cmd_ios}[args.command](args)
    except Stop as stop:
        print()
        fix(redact(str(stop), stored_team()))
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
