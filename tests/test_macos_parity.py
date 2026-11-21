"""The Mac app follows the page and the iPhone app (docs/design/macos-app.md, "Parity").

Its words are the page's where the page says the same thing; the dictionaries the apps share (apple/PointeKit) are the
iPhone app's, word for word, while both copies exist; its colours are assets/theme.json's; the wire format, the vendors'
Keychain items and the brand's drawings are the daemon's and docs/brand's. These tests read the Swift sources, so keep
each string on one line in the form `static let name = "…"`.
"""

import json
import plistlib
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import phone  # noqa: E402
import vendors  # noqa: E402

KIT = ROOT / "apple" / "PointeKit" / "Sources"
MAC = ROOT / "macos"
PAGE = (ROOT / "ui.html").read_text()


def swift_enum(path: Path, name: str) -> dict:
    """`static let name = "…"` inside `enum <name>`, public or not."""
    text = path.read_text()
    block = text[re.search(rf"\benum {name}\b", text).start():]
    block = block[:block.index("\n}\n")]
    return dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block))


def page_dict(name: str) -> dict:
    block = PAGE[PAGE.index(f"const {name} = {{"):]
    block = block[:block.index("};")]
    return {k: v.replace("\\'", "'") for k, v in re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block)}


MAC_COPY = swift_enum(KIT / "PointeKit" / "MacCopy.swift", "MacCopy")
MAC_SOURCE = (KIT / "PointeKit" / "MacCopy.swift").read_text()


def test_connect_words_are_the_pages():
    page = page_dict("CONNECT_COPY")
    for key in ("connect", "tryAgain", "hangUp", "cancel", "notConnected", "elsewhere", "noMic", "busy", "elsewhereWhy", "idleHangup",
                "typeLater", "typeToo"):
        assert MAC_COPY[key] == page[key], key
    # the page's templates, with the Mac's values
    assert "does: device => `Starts the call on this ${device}'s microphone`" in PAGE and MAC_COPY["does"] == "Starts the call on this Mac's microphone"
    assert "connecting: where => `Connecting to ${where}…`" in PAGE and '"Connecting to \\(place)…"' in MAC_SOURCE
    assert "micFailed: why => `The microphone could not start: ${why}`" in PAGE and '"The microphone could not start: \\(why)"' in MAC_SOURCE
    assert "failed: why => `The call did not connect${why ? ': ' + why : ''}.`" in PAGE
    assert '"The call did not connect\\(why.isEmpty ? "" : ": " + why)."' in MAC_SOURCE


def test_the_state_line_and_the_session_tags_are_the_pages():
    for key in ("notAnswering", "reconnecting", "cannotHear", "muted", "speaking", "hearingYou", "listening", "challenging"):
        assert f"'{MAC_COPY[key]}'" in PAGE, f"{key}: the page's state line has no {MAC_COPY[key]!r}"
    tags = "away ? 'offline' : x.waiting ? 'approve' : x.needs ? 'needs you' : x.working ? 'working' : 'idle'"
    assert tags in PAGE
    assert [MAC_COPY[k] for k in ("tagOffline", "tagApprove", "tagNeedsYou", "tagWorking", "tagIdle")] == ["offline", "approve", "needs you", "working", "idle"]
    assert "[['Deny', 'deny'], ['Approve', 'allow']]" in PAGE and (MAC_COPY["deny"], MAC_COPY["approve"]) == ("Deny", "Approve")
    # the order of the cases is the page's too: the first of these that holds is the title
    store = (KIT / "PointeKit" / "PointeStore.swift").read_text()
    body = store[store.index("public var stateTitle: String"):store.index("public var menuBar: MenuBarState")]
    order = [body.index(word) for word in ("talkingLine", "BrainDumpCopy.state", "TurnsCopy.holding", "MacCopy.muted", "MacCopy.speaking",
                                           "MacCopy.hearingYou", "talkStyle.label", "MacCopy.listening")]
    assert order == sorted(order)


def shared(file: str, name: str, ios_file: str) -> tuple[dict, dict | None]:
    kit = swift_enum(KIT / "PointeKit" / file, name)
    ios = ROOT / "ios" / "Pointe" / ios_file
    return kit, (swift_enum(ios, name) if ios.exists() and re.search(rf"\benum {name}\b", ios.read_text()) else None)


def test_the_shared_dictionaries_are_the_pages_and_the_iphones():
    """Until the iPhone app takes each dictionary from the package, there are two copies: they must not differ."""
    for file, name, ios_file in (("Copy.swift", "ConnectCopy", "Connect.swift"), ("Copy.swift", "TurnsCopy", "Turns.swift"),
                                 ("Copy.swift", "AboutCopy", "About.swift"), ("BrainDumpCopy.swift", "BrainDumpCopy", "BrainDump.swift"),
                                 ("TalkGate.swift", "TalkDraft", "PushToTalk.swift"), ("TalkGate.swift", "TalkStyle", "PushToTalk.swift")):
        kit, ios = shared(file, name, ios_file)
        assert kit, name
        if ios is not None:
            assert kit == ios, f"{name}: apple/PointeKit and ios/Pointe differ"
    dump = swift_enum(KIT / "PointeKit" / "BrainDumpCopy.swift", "BrainDumpCopy")
    assert dump == page_dict("DUMP_COPY"), "the brain dump's words are the page's, all of them"
    turns = swift_enum(KIT / "PointeKit" / "Copy.swift", "TurnsCopy")
    assert turns["holding"] == "Holding" and "holding: 'Holding'" in PAGE
    about = swift_enum(KIT / "PointeKit" / "Copy.swift", "AboutCopy")
    assert about["body"] == page_dict("ABOUT_COPY")["body"]


def test_the_theme_tokens_are_the_sources():
    theme = json.loads((ROOT / "assets" / "theme.json").read_text())["tokens"]
    text = (KIT / "PointeKit" / "Theme.swift").read_text()
    block = text[text.index("// theme tokens"):text.index("// end of theme tokens")]
    found = {}
    for name, lhex, la, dhex, da in re.findall(
            r"static let (\w+) = Token\(light: 0x([0-9A-F]{6})(?:, ([\d.]+))?, dark: 0x([0-9A-F]{6})(?:, ([\d.]+))?\)", block):
        found[re.sub(r"(?<=[a-z])(?=[A-Z])", "-", name).lower()] = ((lhex, float(la or 1)), (dhex, float(da or 1)))

    def parts(value: str) -> tuple[str, float]:
        value = value.strip()
        if value.startswith("#"):
            return value[1:].upper(), 1.0
        r, g, b, a = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value).groups()
        return f"{int(r):02X}{int(g):02X}{int(b):02X}", float(a)

    assert set(found) == set(theme), sorted(set(found) ^ set(theme))
    for name, value in theme.items():
        assert found[name] == (parts(value["light"]), parts(value["dark"])), name


def test_the_wire_format_and_the_keys_are_the_daemons():
    wire = (KIT / "PointeKit" / "Wire.swift").read_text()
    assert f"protocolVersion = {phone.PROTOCOL}" in wire
    assert f"upRate = {phone.IN_RATE}.0" in wire and f"downRate = {phone.OUT_RATE}.0" in wire
    assert "chunk = 320" in wire and phone.IN_RATE * 20 // 1000 == 320, "20 ms up"
    link = (KIT / "PointeKit" / "CallLink.swift").read_text()
    assert "deadAfter: TimeInterval = 6" in link and "aliveEvery: Duration = .seconds(2)" in link, "phone.py: dead after 6 s, alive every 2 s"
    locator = (KIT / "PointeMacKit" / "DaemonLocator.swift").read_text()
    cases = re.search(r"enum Vendor: [^{]*\{\s*case ([^\n]+)", locator).group(1).replace(" ", "").split(",")
    assert sorted(cases) == sorted(vendors.KEYS) and 'var service: String { "\\(rawValue)-api-key" }' in locator
    assert all(item == f"{vendor}-api-key" for vendor, (_, item) in vendors.KEYS.items())
    client = (KIT / "PointeKit" / "DaemonClient.swift").read_text()
    import guards
    assert f'cookieName = "{guards.LOCAL_COOKIE}"' in client


def test_the_app_asks_for_one_entitlement_and_loopback_only():
    entitlements = plistlib.loads((MAC / "PointeMac" / "PointeMac.entitlements").read_bytes())
    assert entitlements == {"com.apple.security.device.audio-input": True}, "docs/design/macos-app.md: entitlements, all of them"
    info = plistlib.loads((MAC / "PointeMac" / "Info.plist").read_bytes())
    assert info["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True} and info["LSUIElement"] is True
    assert "CFBundleURLTypes" not in info and info["NSMicrophoneUsageDescription"]
    # every URL the app builds is on loopback; the others are shown, never fetched
    hosts = set()
    for source in [*KIT.rglob("*.swift"), *(MAC / "PointeMac").rglob("*.swift")]:
        hosts |= set(re.findall(r"(?:https?|wss?)://([A-Za-z0-9\\(][A-Za-z0-9.\\()-]*)", source.read_text()))
    assert hosts <= {"\\(Self.host)", "github.com", "ballerine.com"}, hosts
    assert 'public static let host = "127.0.0.1"' in (KIT / "PointeKit" / "DaemonClient.swift").read_text()
    # no secret ever goes to a logger: the sources that log never name a key, a cookie or a credential in a log call
    for source in (MAC / "PointeMac").rglob("*.swift"):
        for line in source.read_text().splitlines():
            if re.search(r"\blog\.(debug|info|notice|error|fault)\(|NSLog\(|print\(", line):
                assert not re.search(r"key\b(?!Code)|cookie|credential|token|secret", line, re.I) or "hot key" in line, f"{source.name}: {line.strip()}"


def test_the_icons_are_the_brands_drawings():
    circle = re.compile(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"')
    small = circle.findall((ROOT / "docs" / "brand" / "favicon.svg").read_text())  # 18 points high: the favicon drawing
    assets = MAC / "PointeMac" / "Assets.xcassets"
    for name in ("MenuOff", "MenuLive"):
        assert circle.findall((assets / f"{name}.imageset" / f"{name}.svg").read_text()) == small, f"{name}: the favicon drawing, unchanged"
        assert len(small) == 49
        looks = json.loads((assets / f"{name}.imageset" / "Contents.json").read_text())
        assert looks["properties"]["template-rendering-intent"] == "template", "one ink: the menu bar's"
    icon = assets / "AppIcon.appiconset"
    sizes = {}
    for image in json.loads((icon / "Contents.json").read_text())["images"]:
        data = (icon / image["filename"]).read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        points, scale = int(image["size"].split("x")[0]), int(image["scale"][0])
        assert (width, height) == (points * scale, points * scale), image["filename"]
        sizes[(points, scale)] = image["filename"]
    assert set(sizes) == {(p, s) for p in (16, 32, 128, 256, 512) for s in (1, 2)}, "every size macOS asks for"


def test_the_project_file_is_what_its_generator_writes():
    made = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'macos/tools'); import make_project; print(make_project.project(), end='')"],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert made == (MAC / "PointeMac.xcodeproj" / "project.pbxproj").read_text(), "run python3 macos/tools/make_project.py"
