"""The UI tests' launch hooks are compiled out of a Release build. POINTE_PAIR adopts a pairing with no confirm, Face ID
or check that the Mac answers, and POINTE_FORGET deletes the pairing: a computer that can launch the app with an
environment (devicectl, an Xcode scheme) would otherwise point the phone at another Mac (SECURITY.md, "The iPhone app").
The Xcode scheme's TestAction builds Debug, so the UI tests keep them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCES = ["apple/PointeKit/Sources", "ios/Pointe", "macos/PointeMac"]
HOOKS = ("POINTE_PAIR", "POINTE_FORGET")
_IF = re.compile(r"^\s*#(if|elseif|else|endif)\b\s*(.*)$")


def debug_only_lines(text: str) -> set[int]:
    """Line numbers (1-based) that only a DEBUG build compiles: inside the first branch of an `#if DEBUG`."""
    stack, out = [], set()  # stack: is this branch DEBUG-only
    for n, line in enumerate(text.split("\n"), 1):
        m = _IF.match(line)
        if m:
            word, cond = m.group(1), m.group(2).split("//")[0].strip()
            if word == "if":
                stack.append(cond == "DEBUG")
            elif word in ("elseif", "else") and stack:
                stack[-1] = False
            elif word == "endif" and stack:
                stack.pop()
            continue
        if any(stack):
            out.add(n)
    return out


def test_the_scan_tells_a_debug_branch_from_the_rest():
    text = "a\n#if DEBUG\nb\n#if os(iOS)\nc\n#endif\n#else\nd\n#endif\n#if os(iOS)\ne\n#endif"
    assert debug_only_lines(text) == {3, 5}


def test_the_pairing_hooks_are_in_debug_builds_only():
    found = []
    for folder in APP_SOURCES:
        for path in sorted((ROOT / folder).rglob("*.swift")):
            text = path.read_text()
            debug = debug_only_lines(text)
            for n, line in enumerate(text.split("\n"), 1):
                if any(f'"{hook}"' in line for hook in HOOKS):
                    found.append(path.name)
                    assert n in debug, f"{path.relative_to(ROOT)}:{n} reads a test hook outside #if DEBUG"
    assert len(found) >= 2, "the hooks moved: point this test at them"


def test_the_ui_tests_build_debug():
    scheme = (ROOT / "ios/Pointe.xcodeproj/xcshareddata/xcschemes/Pointe.xcscheme").read_text()
    assert re.search(r'<TestAction buildConfiguration = "Debug"', scheme)
