"""What App Review looks at that a test can hold in place (docs/ios/app-store.md): the privacy manifests name the
required-reason APIs the code calls, "Try a demo" is in a Release build, every permission the app asks for has its
purpose string, the app reaches no host but the paired Mac, and the listing fits App Store Connect's limits."""
import plistlib
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "apps" / "ios"
KIT = ROOT / "apps" / "PointeKit" / "Sources"
PROJECT = (IOS / "Pointe.xcodeproj" / "project.pbxproj").read_text()
LISTING = (ROOT / "docs" / "ios" / "app-store.md").read_text()
PRIVACY_URL = "https://github.com/ballerine-io/pointe/blob/main/PRIVACY.md"

# What each shipped target compiles: its folder, the folder both share, and the package library it links.
TARGETS = {
    "Pointe": [IOS / "Pointe", IOS / "PointeShared", KIT / "PointeUI", KIT / "PointeKit"],
    "PointeWidget": [IOS / "PointeWidget", IOS / "PointeShared", KIT / "PointeKit"],
}

# Apple's required-reason API categories, by the calls that put an app in them.
REASON_APIS = {
    "NSPrivacyAccessedAPICategoryUserDefaults": r"\bUserDefaults\b|@AppStorage|@SceneStorage",
    "NSPrivacyAccessedAPICategorySystemBootTime": r"\bsystemUptime\b|\bmach_absolute_time\b",
    "NSPrivacyAccessedAPICategoryFileTimestamp":
        r"\b(creationDate|modificationDate|contentModificationDate|fileModificationDate|attributesOfItem|getattrlist)\b",
    "NSPrivacyAccessedAPICategoryDiskSpace": r"\b(volumeAvailableCapacity\w*|volumeTotalCapacity|systemFreeSize|statfs)\b",
    "NSPrivacyAccessedAPICategoryActiveKeyboards": r"\bactiveInputModes\b",
}


def _code(path: Path) -> str:
    """The Swift with its comments taken out, so a comment that names an API does not count as a call."""
    text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    return re.sub(r"(?<![:\"])//.*", "", text)


def _sources(target: str) -> str:
    return "\n".join(_code(f) for d in TARGETS[target] for f in sorted(d.rglob("*.swift")))


def _target_block(name: str) -> str:
    native = PROJECT[PROJECT.index("/* Begin PBXNativeTarget section */"):PROJECT.index("/* End PBXNativeTarget section */")]
    start = native.index(f"/* {name} */ = {{")
    return native[start:native.index("productType", start)]


def _manifest(target: str) -> dict:
    return plistlib.loads((IOS / target / "PrivacyInfo.xcprivacy").read_bytes())


def _settings(key: str) -> list[str]:
    """The app target's value of a build setting, in each configuration (Debug and Release)."""
    return re.findall(rf"^\s*{key} = (.+);$", PROJECT[:PROJECT.index('PRODUCT_BUNDLE_IDENTIFIER = io.ballerine.pointe.tests')],
                      flags=re.M)


def test_each_target_compiles_what_this_file_says():
    assert "PointeUI" in _target_block("Pointe") and "PointeShared" in _target_block("Pointe")
    widget = _target_block("PointeWidget")
    assert "PointeKit" in widget and "PointeShared" in widget and "PointeUI" not in widget


def test_the_privacy_manifests_say_nothing_is_collected_or_tracked():
    for target in TARGETS:
        m = _manifest(target)
        assert m["NSPrivacyTracking"] is False and m["NSPrivacyTrackingDomains"] == [], target
        assert m["NSPrivacyCollectedDataTypes"] == [], f"{target}: App Privacy is Data Not Collected (PRIVACY.md)"


def test_the_privacy_manifests_name_exactly_the_required_reason_apis_the_code_calls():
    for target in TARGETS:
        code = _sources(target)
        used = {category for category, pattern in REASON_APIS.items() if re.search(pattern, code)}
        declared = {entry["NSPrivacyAccessedAPIType"]: entry["NSPrivacyAccessedAPITypeReasons"]
                    for entry in _manifest(target)["NSPrivacyAccessedAPITypes"]}
        assert set(declared) == used, f"{target}: declared {sorted(declared)}, the code calls {sorted(used)}"
        if "NSPrivacyAccessedAPICategoryUserDefaults" in used:
            reasons = set(declared["NSPrivacyAccessedAPICategoryUserDefaults"])
            assert ("1C8F.1" in reasons) == ("suiteName:" in code), f"{target}: 1C8F.1 is the app group's defaults"
            own = bool(re.search(r"@AppStorage|UserDefaults\.standard", code))
            assert ("CA92.1" in reasons) == own, f"{target}: CA92.1 is the app's own defaults"
        if "NSPrivacyAccessedAPICategorySystemBootTime" in used:
            assert declared["NSPrivacyAccessedAPICategorySystemBootTime"] == ["35F9.1"], target


def _debug_only(swift: str) -> list[bool]:
    """For each line, whether only a Debug build compiles it (inside an `#if DEBUG` branch)."""
    stack: list[bool] = []
    out = []
    for line in swift.splitlines():
        t = line.strip()
        if t.startswith("#if "):
            stack.append("DEBUG" in t and "!DEBUG" not in t)
        elif t.startswith("#elseif"):
            stack[-1] = "DEBUG" in t and "!DEBUG" not in t
        elif t.startswith("#else"):
            stack[-1] = False
        elif t.startswith("#endif"):
            stack.pop()
        out.append(any(stack))
    return out


def _in_release(file: str, needle: str) -> bool:
    swift = (KIT / "PointeUI" / file).read_text()
    lines = swift.splitlines()
    hits = [i for i, line in enumerate(lines) if needle in line]
    assert hits, f"{needle!r} is not in {file}"
    debug = _debug_only(swift)
    return all(not debug[i] for i in hits)


def test_try_a_demo_is_in_a_release_build():
    """App Review 2.1: the reviewer has no Mac to pair with, so the demo is the way in, and it must ship."""
    assert _in_release("PairView.swift", 'Label("No Mac yet? Try a demo"')
    assert _in_release("PointeRoot.swift", "tryDemo: { tried = Demo.tryIt }")
    assert _in_release("Demo.swift", "static var tryIt: Demo?")
    assert _in_release("Demo.swift", "static func make(_ screen: Screen")
    assert not _in_release("Demo.swift", 'args.firstIndex(of: "-demo")'), "the launch argument is for tests only"
    assert '"No Mac yet? Try a demo"' in LISTING, "the review notes name the button as the app shows it"


def test_every_permission_the_app_asks_for_has_its_purpose_string():
    code = _sources("Pointe")
    asks = {
        "NSCameraUsageDescription": r"AVCaptureDevice\.default\(for: \.video\)",
        "NSMicrophoneUsageDescription": r"requestRecordPermission",
        "NSFaceIDUsageDescription": r"\bLAContext\(\)",
        "NSLocalNetworkUsageDescription": r"\bURLSession\(",
    }
    for key, pattern in asks.items():
        assert re.search(pattern, code), f"{key}: the app no longer asks; drop the string"
        values = _settings(f"INFOPLIST_KEY_{key}")
        assert len(values) == 2 and values[0] == values[1] and values[0].startswith('"Pointe '), (key, values)
    assert re.search(r"CMMotionActivityManager", code)
    motion = plistlib.loads((IOS / "Pointe" / "Info.plist").read_bytes())["NSMotionUsageDescription"]
    assert motion.startswith("Pointe uses motion activity")


def test_the_app_uses_only_exempt_encryption():
    """`ITSAppUsesNonExemptEncryption` is false: TLS is Apple's (URLSession), and the app's own crypto only hashes and
    authenticates (SHA-256 of the Mac's certificate for the pin, an HMAC proof). A cipher here means answering
    App Store Connect's export questions again."""
    assert plistlib.loads((IOS / "Pointe" / "Info.plist").read_bytes())["ITSAppUsesNonExemptEncryption"] is False
    for target in TARGETS:
        ciphers = re.findall(r"\b(AES|ChaChaPoly|SealedBox|SecKeyCreateEncryptedData|CCCrypt)\b", _sources(target))
        assert not ciphers, (target, ciphers)


def test_the_app_reaches_only_the_paired_mac():
    """App Privacy is Data Not Collected: the only hosts the app names are links a person taps, opened in Safari.
    Every connection is built on the paired Mac's host (`https://\\(host)`), or loopback on the Mac app."""
    links = {"https://github.com/ballerine-io/pointe", "https://ballerine.com", PRIVACY_URL,
             "https://github.com/ballerine-io/pointe/blob/main/docs/phone/wifi.md#when-it-stops-working",
             "https://github.com/ballerine-io/pointe/blob/main/docs/phone/tailscale.md#when-it-stops-working",
             "https://github.com/ballerine-io/pointe/blob/main/docs/phone/twingate.md#when-it-stops-working",
             "https://github.com/ballerine-io/pointe.git"}  # MacCopy.installCommand, a command shown to copy
    for target in TARGETS:
        named = set(re.findall(r"https?://[^\s\"\\]+", _sources(target)))
        assert named <= links, f"{target}: a new host {sorted(named - links)}; check App Privacy and PRIVACY.md"
        assert re.findall(r'"http://\\\((\w+)', _sources(target)) in ([], ["Self"]), "plain http is the Mac's loopback only"


def test_the_iphone_app_is_iphone_only_and_its_screenshots_are_the_69_inch_size():
    """TARGETED_DEVICE_FAMILY 1: no iPad build, so App Store Connect asks for iPhone screenshots only."""
    assert _settings("TARGETED_DEVICE_FAMILY") == ["1", "1"]
    shots = sorted((ROOT / "docs" / "ios" / "screenshots").glob("*.png"))
    assert 3 <= len(shots) <= 10
    for shot in shots:
        width, height = struct.unpack(">II", shot.read_bytes()[16:24])
        assert (width, height) == (1320, 2868), (shot.name, width, height)


def test_the_background_modes_are_the_call_and_the_alerts():
    """App Review 2.5.4: audio keeps a call up with the screen locked; fetch is Background App Refresh for alerts."""
    info = plistlib.loads((IOS / "Pointe" / "Info.plist").read_bytes())
    assert sorted(info["UIBackgroundModes"]) == ["audio", "fetch"]
    assert info["BGTaskSchedulerPermittedIdentifiers"] == ["io.ballerine.pointe.alerts"]


def _quoted(label: str) -> str:
    """A listing field written as a quote block under its bold label."""
    block = LISTING[LISTING.index(f"**{label}"):].split("\n", 1)[1].lstrip("\n")
    lines = []
    for line in block.splitlines():
        if not line.startswith(">"):
            break
        lines.append(line[1:].lstrip(" "))
    paragraphs = " ".join(line if line else "\n\n" for line in lines)
    return re.sub(r" ?\n\n ?", "\n\n", paragraphs).strip()


def _row(field: str) -> str:
    return re.search(rf"^\| {re.escape(field)} \| (.+?) \|$", LISTING, flags=re.M).group(1)


def test_the_listing_fits_app_store_connects_limits():
    assert len(_row("Name (30 max)")) <= 30 and len(_row("Subtitle (30 max)")) <= 30
    assert len(_quoted("Promotional text")) <= 170
    keywords = _quoted("Keywords")
    assert len(keywords) <= 100 and ", " not in keywords and " " not in keywords
    assert len(_quoted("Description")) <= 4000
    assert len(_quoted("App Review notes")) <= 4000
    assert _row("Privacy Policy URL") == PRIVACY_URL, "the URL the app's About links (AboutCopy.privacyURL)"


def test_the_listing_does_not_call_the_app_a_beta():
    """App Review 2.2: betas belong on TestFlight. The listing describes the shipped app."""
    for label in ("Promotional text", "Description"):
        assert not re.search(r"\b(beta|preview|test ?flight)\b", _quoted(label), flags=re.I), label
