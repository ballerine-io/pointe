"""Talk to Pointe from outside the iPhone app (docs/features/push-to-talk.md): the Control, the Home Screen widget and the
Live Activity. What the Swift tests cannot see from inside one module: the widget's brand tokens against the app's, the
rule that nothing on this path approves a request, that the press opens the app, and the project's wiring of the
extension, its app group and its bundle ID.

uv run --locked pytest -q tests/test_widget.py
"""

import plistlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "apps" / "PointeKit" / "Sources"
WIDGET = ROOT / "apps" / "ios" / "PointeWidget"
SHARED = ROOT / "apps" / "ios" / "PointeShared"
PROJECT = (ROOT / "apps" / "ios" / "Pointe.xcodeproj" / "project.pbxproj").read_text()
TOKEN = re.compile(r"static let (\w+) = (Color\(light: 0x[0-9A-F]{6}(?:, [\d.]+)?, dark: 0x[0-9A-F]{6}(?:, [\d.]+)?\))")


def test_the_widget_draws_with_the_apps_own_tokens():
    brand = (KIT / "PointeUI" / "Brand.swift").read_text()
    app = dict(TOKEN.findall(brand[brand.index("// theme tokens"):brand.index("// end of theme tokens")]))
    widget = dict(TOKEN.findall((WIDGET / "WidgetBrand.swift").read_text()))
    assert widget and {"orange", "text", "muted"} <= set(widget)
    for name, value in widget.items():
        assert app.get(name) == value, f"WidgetBrand.{name} is {value}, Brand.{name} is {app.get(name)}"


def outside_path() -> dict[str, str]:
    files = [KIT / "PointeKit" / "TalkLaunch.swift", KIT / "PointeKit" / "TalkSnapshot.swift", KIT / "PointeUI" / "PhoneTalk.swift",
             *SHARED.glob("*.swift"), *WIDGET.glob("*.swift"), ROOT / "apps" / "ios" / "Pointe" / "TalkIntent.swift"]
    return {str(f.relative_to(ROOT)): f.read_text() for f in files}


def test_a_press_from_outside_never_approves_anything():
    """Approving stays a tap behind Face ID on the call screen, or a spoken yes behind the voice lock. The press only
    dials, changes the mode, opens and closes the push-to-talk gate and hangs up."""
    for path, text in outside_path().items():
        code = "\n".join(line.split("//")[0] for line in text.splitlines())  # what runs, not what the comments explain
        for word in ("answer(", "voice/approve", "allow:", "watchApprove", "evaluatePolicy", "AlertAnswer"):
            assert word not in code, f"{path} uses {word}"
    calls = set(re.findall(r"api\.(\w+)\(", outside_path()["apps/PointeKit/Sources/PointeUI/PhoneTalk.swift"]))
    assert calls <= {"status", "mode", "prefs", "hungUp"}, calls


def test_the_extension_is_embedded_and_shares_one_app_group_with_the_app():
    assert 'productType = "com.apple.product-type.app-extension"' in PROJECT and "PointeWidget.appex in Embed Foundation Extensions" in PROJECT
    assert PROJECT.count('PRODUCT_BUNDLE_IDENTIFIER = "$(POINTE_BUNDLE_ID)";') == 2
    assert PROJECT.count('PRODUCT_BUNDLE_IDENTIFIER = "$(POINTE_BUNDLE_ID).widget";') == 2
    assert PROJECT.count('POINTE_APP_GROUP = "group.$(POINTE_BUNDLE_ID)";') == 2
    assert PROJECT.count("SWIFT_ACTIVE_COMPILATION_CONDITIONS = \"POINTE_WIDGET $(inherited)\";") == 2
    for target in ("Pointe", "PointeWidget"):
        entitlements = plistlib.loads((ROOT / "apps" / "ios" / target / f"{target}.entitlements").read_bytes())
        assert entitlements == {"com.apple.security.application-groups": ["$(POINTE_APP_GROUP)"]}, target
        assert plistlib.loads((ROOT / "apps" / "ios" / target / "Info.plist").read_bytes())["PointeAppGroup"] == "$(POINTE_APP_GROUP)"
    assert plistlib.loads((ROOT / "apps" / "ios" / "Pointe" / "Info.plist").read_bytes())["NSSupportsLiveActivities"] is True


def test_the_app_group_is_signed_in_only_when_asked_for():
    """A free Personal Team's profiles carry no App Groups (seen on a real phone: the build fails for both targets), so the
    project signs without the group unless POINTE_SHARE_GROUP=YES: a plain Xcode build works on any team. The App Store
    build, the Simulator and `pointe apps ios` (first, then without it on that error) ask for it."""
    assert PROJECT.count("POINTE_SHARE_GROUP = NO;") == 2
    assert PROJECT.count('CODE_SIGN_ENTITLEMENTS = "$(POINTE_ENTITLEMENTS_APP_$(POINTE_SHARE_GROUP))";') == 2
    assert PROJECT.count('CODE_SIGN_ENTITLEMENTS = "$(POINTE_ENTITLEMENTS_WIDGET_$(POINTE_SHARE_GROUP))";') == 2
    assert PROJECT.count("POINTE_ENTITLEMENTS_APP_YES = Pointe/Pointe.entitlements;") == 2
    assert PROJECT.count("POINTE_ENTITLEMENTS_WIDGET_YES = PointeWidget/PointeWidget.entitlements;") == 2
    assert "POINTE_ENTITLEMENTS_APP_NO" not in PROJECT and "POINTE_ENTITLEMENTS_WIDGET_NO" not in PROJECT, "NO is no file"
    assert "CODE_SIGN_ENTITLEMENTS = Pointe" not in PROJECT, "never a fixed entitlements file"
    assert "POINTE_SHARE_GROUP=YES" in (ROOT / "apps" / "ios" / "release.sh").read_text()


def test_the_press_opens_the_app_and_the_buttons_run_in_it():
    """The press opens Pointe (openAppWhenRun): the microphone starts in front, the mic sends, and a locked iPhone asks to
    unlock first. Nothing records from the background, so no audio recording intent; the Live Activity's buttons are Live
    Activity intents, which run in the app's process too."""
    intents = (SHARED / "TalkIntents.swift").read_text()
    for name in ("TalkIntent", "SendTalkIntent", "CancelTalkIntent"):
        assert re.search(rf"struct {name}: LiveActivityIntent \{{", intents), name
    talk = intents[intents.index("struct TalkIntent"):intents.index("struct SendTalkIntent")]
    assert "static let openAppWhenRun = true" in talk
    assert "AudioRecordingIntent" not in intents and "ForegroundContinuableIntent" not in intents
    assert "openAppWhenRun" not in intents[intents.index("struct SendTalkIntent"):], "Send and Hang up act from the Lock Screen"
