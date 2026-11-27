"""The Mac app is the same product as the page and the iPhone app (docs/design/parity.md, docs/design/macos-app.md).

It draws the iPhone app's screens (apps/PointeKit, PointeUI), so the words, the colours and the rules those tests hold to
the page (test_copy_parity, test_theme and the others) are the Mac's too. These hold what is the Mac's own: the lines it
says differently (MacCopy: "press" for "tap", this Mac for your Mac) are the page's, its phone-pairing sheet says the
page's words, there is one copy of each shared dictionary, the wire format, the vendors' Keychain items and the brand's
drawings are the daemon's and docs/brand's, and the app asks for one entitlement and talks to loopback only. They read
the Swift sources, so keep each string on one line in the form `static let name = "…"`.
"""

import json
import plistlib
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import phone  # noqa: E402
import vendors  # noqa: E402

KIT = ROOT / "apps" / "PointeKit" / "Sources"
MAC = ROOT / "apps" / "macos"
PAGE = (ROOT / "pointe" / "ui.html").read_text()


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


UI = KIT / "PointeUI"


def test_the_mac_says_the_pages_lines_where_the_phones_would_be_wrong():
    """The shared screens ask ConnectCopy's `…Here` for a line; on the Mac that is MacCopy's, which the test above holds
    to the page. No screen shows the phone's own wording of one of them directly."""
    connect = (UI / "Connect.swift").read_text()
    for here, mac in (("doesHere", "MacCopy.does"), ("tapConnectHere", "MacCopy.pressConnect"), ("notPairedHere", "MacCopy.keyRefused"),
                      ("idleHangupHere", "MacCopy.idleHangup"), ("micDeniedHere", "MacCopy.micDenied"), ("elsewhereWhyHere", "MacCopy.elsewhereWhy"),
                      ("typeLaterHere", "MacCopy.typeLater")):
        assert re.search(rf"static var {here}: String \{{ Surface\.isMac \? {re.escape(mac)} : \w+ \}}", connect), here
    assert "static func unreachableHere(_ host: String) -> String { Surface.isMac ? MacCopy.daemonDown : unreachable(host) }" in connect
    assert MAC_COPY["pressConnect"] == "Press Connect to start talking" and "Press Connect" in PAGE
    shown = re.compile(r"ConnectCopy\.(does|tapConnect|notPaired|idleHangup|micDenied|elsewhereWhy|typeLaterTap|unreachable\()(?!Here)\b")
    for source in UI.glob("*.swift"):
        body = source.read_text()
        if source.name == "Connect.swift":
            body = body[body.index("struct ConnectFace"):]  # past the dictionary and its Mac lines
        assert not shown.search(body), f"{source.name} shows the phone's line on the Mac too: use the …Here form"
    for key in ("notAnswering", "reconnecting", "muted", "speaking", "listening"):
        assert f"'{MAC_COPY[key]}'" in PAGE, f"{key}: the page's state line has no {MAC_COPY[key]!r}"


def test_the_state_line_is_one_function_for_the_window_the_menu_bar_and_the_bubble():
    title = (UI / "CallTitle.swift").read_text()
    body = title[title.index("static func line("):title.index("/// What holds the call")]
    order = [body.index(word) for word in ("ChallengeCopy.state", "BrainDumpCopy.state", "TurnsCopy.holding", "talkingLine(call)",
                                           "MuteCopy.speaking", "MuteCopy.writing", "call.talkNote", "closedLine", 'MicCopy.off', '"Listening"')]
    assert order == sorted(order), "the first that holds is the line"
    assert "CallTitle.line(" in (UI / "CallView.swift").read_text() and "CallTitle.line(" in (UI / "MacShell.swift").read_text()
    tags = "away ? 'offline' : x.waiting ? 'approve' : x.needs ? 'needs you' : x.working ? 'working' : 'idle'"
    assert tags in PAGE
    assert "[['Deny', 'deny'], ['Approve', 'allow']]" in PAGE and (MAC_COPY["deny"], MAC_COPY["approve"]) == ("Deny", "Approve")


def test_each_shared_dictionary_has_one_copy():
    """The words, the models and the rules were once in the package and in the iPhone target both. Now a type is declared
    once: in PointeUI (the screens both apps draw) or under it in PointeKit, never in an app target."""
    declared: dict[str, list[str]] = {}
    for source in [*KIT.rglob("*.swift"), *(ROOT / "apps" / "ios" / "Pointe").glob("*.swift"), *(MAC / "PointeMac").glob("*.swift")]:
        for name in re.findall(r"^(?:public )?(?:final )?(?:enum|struct|class) (\w+)", source.read_text(), re.M):
            declared.setdefault(name, []).append(str(source.relative_to(ROOT)))
    # one file may declare a type once per platform (`#if os(iOS)` … `#else`): that is one type, not a copy
    twice = {name: where for name, where in declared.items() if len(set(where)) > 1}
    assert not twice, twice
    for name in ("ConnectCopy", "TurnsCopy", "AboutCopy", "BrainDumpCopy", "TalkDraft", "TalkStyle", "TalkGate", "API", "MachineView", "AlertPlan", "Theme"):
        assert len(set(declared[name])) == 1 and "/PointeUI/" in declared[name][0], (name, declared.get(name))
    for name in ("NewSessionCopy", "Harness", "Wire", "MacCopy", "NewSession"):
        assert len(set(declared[name])) == 1 and "/Sources/PointeKit/" in declared[name][0], (name, declared.get(name))
    dump = swift_enum(UI / "BrainDump.swift", "BrainDumpCopy")
    assert dump == page_dict("DUMP_COPY"), "the brain dump's words are the page's, all of them"
    assert swift_enum(UI / "About.swift", "AboutCopy")["body"] == page_dict("ABOUT_COPY")["body"]


def test_the_phone_sheet_says_the_pages_words():
    """Pair a phone from the Mac app: Settings → Phone, as on the page (ui.html)."""
    copy = swift_enum(UI / "PhoneSheet.swift", "PhoneCopy")
    for key in ("none", "connect", "connectAnother", "unpair", "unpairAll", "unpairAllSure", "how", "looking", "hostHint", "check", "show",
                "cancel", "scan", "copyLink", "copied", "expired", "noAnswer", "newCertificate", "recommended", "setUpNow", "allUnpaired",
                "certificate"):
        assert copy[key].replace("'", "\\'") in PAGE or copy[key] in PAGE, f"{key}: the page does not say {copy[key]!r}"
    rule = re.search(r"const PHONE_RULE = '([^']*)' \+\s*'([^']*)';", PAGE)
    assert copy["rule"] == rule.group(1) + rule.group(2)
    sheet = (UI / "PhoneSheet.swift").read_text()
    for route in ("voice/phone/routes", "voice/phone/invite", "voice/phone/unpair"):
        assert f'"{route}"' in sheet and f"'/{route}" in PAGE
    assert sheet.lstrip().startswith("//") and "#if os(macOS)" in sheet.split("import SwiftUI")[0], "the Mac's alone: the phone reads the code"


def test_the_theme_tokens_are_the_sources():
    theme = json.loads((ROOT / "assets" / "theme.json").read_text())["tokens"]
    text = (UI / "Brand.swift").read_text()  # one set of tokens: the Mac draws with the iPhone app's
    block = text[text.index("// theme tokens"):text.index("// end of theme tokens")]
    found = {}
    for name, lhex, la, dhex, da in re.findall(
            r"static let (\w+) = Color\(light: 0x([0-9A-F]{6})(?:, ([\d.]+))?, dark: 0x([0-9A-F]{6})(?:, ([\d.]+))?\)", block):
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
    link = (UI / "Call.swift").read_text()  # one call for both apps
    assert "deadAfter: TimeInterval = 6" in link and "aliveEvery: Duration = .seconds(2)" in link, "phone.py: dead after 6 s, alive every 2 s"
    assert "Wire.hello(device: link.device, resume: machine.token" in link, "the hello is the Wire's, protocol and all"
    assert 'capabilities = ["ptt", "resume", "adpcm"]' in wire and phone.ADPCM == "adpcm"
    daemon_link = (UI / "DaemonLink.swift").read_text()
    assert 'isLocal ? "Mac" : "iPhone"' in daemon_link and "hello.get(\"device\") == \"Mac\"" in (ROOT / "pointe" / "daemon.py").read_text()
    locator = (KIT / "PointeMacKit" / "DaemonLocator.swift").read_text()
    cases = re.search(r"enum Vendor: [^{]*\{\s*case ([^\n]+)", locator).group(1).replace(" ", "").split(",")
    assert sorted(cases) == sorted(vendors.KEYS) and 'var service: String { "pointe.\\(rawValue)-api-key" }' in locator
    assert 'var legacyService: String { "\\(rawValue)-api-key" }' in locator
    assert all(item == f"pointe.{vendor}-api-key" for vendor, (_, item) in vendors.KEYS.items())
    assert all(item == f"{vendor}-api-key" for vendor, item in vendors.LEGACY_ITEMS.items())
    client = (KIT / "PointeKit" / "DaemonClient.swift").read_text()
    assert "\"Cookie\"" not in client + daemon_link, "the app never sends the page key: a proof per request (local_proof.py)"
    import local_proof
    proof = (KIT / "PointeKit" / "LocalProof.swift").read_text()
    assert re.search(r'static let header = "([^"]+)"', proof).group(1).lower() == local_proof.HEADER


def test_the_app_asks_for_one_entitlement_and_loopback_only():
    entitlements = plistlib.loads((MAC / "PointeMac" / "PointeMac.entitlements").read_bytes())
    assert entitlements == {"com.apple.security.device.audio-input": True}, "docs/design/macos-app.md: entitlements, all of them"
    info = plistlib.loads((MAC / "PointeMac" / "Info.plist").read_bytes())
    assert info["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True} and info["LSUIElement"] is True
    assert "CFBundleURLTypes" not in info and info["NSMicrophoneUsageDescription"]
    # every URL the app builds is on loopback; the others are shown, never fetched
    # what only the phone compiles (its pairing, its listener's address) is not the Mac's code
    sys.path.insert(0, str(ROOT / "tools"))
    import parity
    hosts = set()
    for path, text in parity.sources("mac").items():
        if path.endswith(("Pairing.swift", "Demo.swift")):  # the phone's pairing with a Mac's TLS listener; the demo's invented one
            continue
        hosts |= set(re.findall(r"(?:https?|wss?)://([A-Za-z0-9\\(][A-Za-z0-9.\\()-]*)", text))
    assert hosts <= {"\\(Self.host)", "github.com", "ballerine.com"}, hosts
    link = (UI / "DaemonLink.swift").read_text()
    assert "case .local(let daemon): daemon.endpoint()?.base" in link and "daemon.endpoint()?.callRequest" in link, "the Mac's link is the verified loopback endpoint"
    assert 'public static let host = "127.0.0.1"' in (KIT / "PointeKit" / "DaemonClient.swift").read_text()
    # no secret ever goes to a logger: the sources that log never name a key, a cookie or a credential in a log call
    for source in [*(MAC / "PointeMac").rglob("*.swift"), *UI.glob("*.swift")]:
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
    made = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'apps/macos/tools'); import make_project; print(make_project.project(), end='')"],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert made == (MAC / "PointeMac.xcodeproj" / "project.pbxproj").read_text(), "run python3 apps/macos/tools/make_project.py"
