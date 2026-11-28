"""Every route an app screen calls is open to the phone's key (guards._PHONE_PATHS), derived from the Swift client
itself, so a new screen cannot drift: the docs track found Approvals, Agents and People settings missing, each a 403
on the iPhone. The few routes only the Mac app calls (Settings, Phone: the page's own) are named here with why."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pointe"))
import guards  # noqa: E402

SOURCES = [ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI", ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit"]
# The Mac app's Settings, Phone: they make and show the phone's own pairing code, so a phone's key never reaches them
# (phone_pairing.install, the_page).
MAC_ONLY = {"/voice/phone/invite", "/voice/phone/routes", "/voice/phone/unpair"}


def app_paths() -> set[str]:
    found = set()
    for folder in SOURCES:
        for f in folder.rglob("*.swift"):
            for raw in re.findall(r'"(voice/[^"]*)"', f.read_text()):
                path = "/" + re.sub(r"\\\([^)]*\)", "x", raw).split("?")[0]
                found.add(path)
    return found


def test_the_client_is_read():
    paths = app_paths()
    assert {"/voice/status", "/voice/approvals", "/voice/agents/x/replies"} <= paths, sorted(paths)


def test_every_route_an_app_screen_calls_takes_the_phones_key():
    missing = sorted(p for p in app_paths() - MAC_ONLY if not guards.phone_path(p))
    assert not missing, f"open these to the phone in guards._PHONE_PATHS: {missing}"


def test_the_mac_only_routes_stay_closed_to_the_phone_and_a_name_is_one_segment():
    assert not any(guards.phone_path(p) for p in MAC_ONLY)
    assert guards.phone_path("/voice/agents/hermes") and guards.phone_path("/voice/agents/hermes/replies")
    assert not guards.phone_path("/voice/agents/hermes/token") and not guards.phone_path("/voice/agents/a/b/replies")
