"""Every headless Chrome a test or demo starts stays off the login Keychain: without a mock keychain and a basic password
store, Chrome reaches for it, and macOS once offered the owner to reset a keychain it could not find."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_headless_chrome_uses_a_mock_keychain_and_its_own_profile():
    bad = []
    sources = [*ROOT.glob("tests/**/*.py"), *ROOT.glob("tools/demo-video/**/*.py"), *ROOT.glob("bench/**/*.py"), *ROOT.glob("tools/*.py")]
    for path in (p for p in sources if p.name != Path(__file__).name):
        text = path.read_text()
        for found in re.finditer(r'"--headless[^"]*"', text):
            call = text[found.start():text.find("]", found.start())]  # the rest of the argument list
            if not all(flag in call for flag in ("--use-mock-keychain", "--password-store=basic", "--user-data-dir")):
                bad.append(f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, found.start()) + 1}")
    assert not bad, bad
