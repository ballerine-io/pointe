"""The version commit: every place that carries the version, moved together (docs/releasing.md, step 1)."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from .core import Fail, sh

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def parse(v: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(v):
        raise Fail(f"{v!r} is not a version X.Y.Z")
    a, b, c = (int(x) for x in v.split("."))
    return a, b, c


def current(tree: Path) -> str:
    return json.loads((tree / ".claude-plugin" / "plugin.json").read_text())["version"]


def next_versions(v: str) -> dict[str, str]:
    a, b, c = parse(v)
    return {"patch": f"{a}.{b}.{c + 1}", "minor": f"{a}.{b + 1}.0", "major": f"{a + 1}.0.0"}


def _sub(path: Path, pattern: str, repl, count: int, flags: int = re.M) -> None:
    """Replace every match; `count` is the exact number expected, or 0 for "every one, at least two" (the app and its
    widget extension, each Debug and Release, carry the same keys)."""
    text = path.read_text()
    new, n = re.subn(pattern, repl, text, flags=flags)
    if (count and n != count) or (not count and n < 2):
        raise Fail(f"{path.name}: expected {count or 'two or more'} match(es) of {pattern!r}, found {n}: the file's shape changed, update bump.py")
    path.write_text(new)


def changelog_line(version: str, summary: str, date: str) -> str:
    beta = ", beta" if version.startswith("0.") else ""
    return f"- **{version}** ({date}{beta}): {summary}"


UNRELEASED = "- **Unreleased**"


def unreleased_blocks(text: str) -> list[tuple[int, int]]:
    """(start, end) line ranges of each `- **Unreleased** …` entry: its line, its continuation and its paragraphs, up to the
    next entry or heading."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith(UNRELEASED):
            j = i + 1
            while j < len(lines) and not lines[j].startswith(("- **", "## ")):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def shipped(tree: Path, entry: str, last_tag: str) -> bool:
    """Whether the commit that added this Unreleased entry is already in the last tag: then it shipped, and the entry was
    left behind by that release (0.9.0 left the skip-permissions one)."""
    words = entry.split(":", 1)[-1].strip()[:60]
    added = sh(["git", "log", "--format=%H", "--reverse", "-S", words, "--", "CHANGELOG.md"], cwd=tree, check=False).stdout.split()
    if not added or not last_tag:
        return False
    return sh(["git", "merge-base", "--is-ancestor", added[0], last_tag], cwd=tree, check=False).returncode == 0


def unreleased(tree: Path, last_tag: str = "") -> tuple[list[str], list[str]]:
    """The Unreleased entries as (to fold into the next version's line, already shipped and to drop): first lines."""
    text = (tree / "CHANGELOG.md").read_text()
    lines = text.split("\n")
    fold, drop = [], []
    for a, _ in unreleased_blocks(text):
        (drop if shipped(tree, lines[a], last_tag) else fold).append(lines[a])
    return fold, drop


def fold_changelog(text: str, line: str, shipped_first_lines: list[str]) -> str:
    """The version's line on top; each Unreleased entry under it as a "What is in it" item (its detail kept), and the ones
    that already shipped removed."""
    lines = text.split("\n")
    blocks = unreleased_blocks(text)
    items: list[str] = []
    for a, b in blocks:
        if lines[a] in shipped_first_lines:
            continue
        head = "  - " + lines[a][len(UNRELEASED):].split(":", 1)[-1].strip()
        items.append("\n".join([head] + [("  " + x if x.strip() else "") for x in lines[a + 1:b]]))
    for a, b in reversed(blocks):
        del lines[a:b]
    text = "\n".join(lines)
    at = text.find("\n- **")
    if at < 0:
        raise Fail("CHANGELOG.md has no entry line to put the new one above")
    entry = line + ("\n\n  What is in it:\n" + "\n".join(items) + "\n" if items else "")
    version = re.match(r"- \*\*(\d+)\.(\d+)\.", line)
    heading = f"## {version.group(1)}.{version.group(2)}" if version else ""
    first = re.search(r"^## .*$", text, re.M)
    if heading and first and not first.group(0).startswith(heading + " ") and first.group(0) != heading:
        # a new minor version opens its own section above the newest one ("## 0.10 (beta)" over "## 0.9 (beta)")
        beta = " (beta)" if version.group(1) == "0" else ""
        return text[:first.start()] + f"{heading}{beta}\n\n{entry}\n" + text[first.start():]
    return text[:at + 1] + entry + "\n" + text[at + 1:]


SKEW = "tests/fixtures/skew_requests.json"


def add_skew_entry(tree: Path, version: str) -> str:
    """tests/test_skew.py needs an entry for the version: when it has none, the newest release's requests are copied under
    it (what the scripts send changes rarely; a release that changes them edits the entry on main before the cut)."""
    path = tree / SKEW
    if not path.exists():
        return ""
    text = path.read_text()
    data = json.loads(text)
    if json.dumps(data, indent=1, ensure_ascii=False) + "\n" != text:
        raise Fail(f"{SKEW} is not in the shape bump.py writes back: add the {version} entry by hand")
    found = [r["release"] for r in data["releases"]]
    if version in found:
        return f"{SKEW} has {version}"
    newest = max(data["releases"], key=lambda r: parse(r["release"]) if VERSION_RE.fullmatch(r["release"]) else (0, 0, 0))
    data["releases"].append({**json.loads(json.dumps(newest)), "release": version})
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return f"{SKEW}: {version} added, a copy of {newest['release']}'s requests"


def bump(tree: Path, version: str, summary: str, date: str | None = None, last_tag: str = "") -> dict:
    """Write `version` everywhere; return the new build numbers. The caller commits and runs the version tests."""
    old = current(tree)
    if parse(version) <= parse(old):
        raise Fail(f"{version} is not newer than the current {old}")
    if not summary.strip() or "\n" in summary:
        raise Fail("the summary is one line, in the words a user would use (it is the commit subject and the changelog line)")
    date = date or datetime.date.today().isoformat()

    _sub(tree / ".claude-plugin" / "plugin.json", r'("version": *")[^"]*(")', rf"\g<1>{version}\g<2>", 1)
    _sub(tree / "pyproject.toml", r'^(version = ")[^"]*(")', rf"\g<1>{version}\g<2>", 1)

    pbx = tree / "apps" / "ios" / "Pointe.xcodeproj" / "project.pbxproj"
    builds = set(re.findall(r"CURRENT_PROJECT_VERSION = (\d+);", pbx.read_text()))
    if len(builds) != 1:
        raise Fail(f"the iPhone project's Debug and Release disagree on CURRENT_PROJECT_VERSION: {sorted(builds)}")
    ios_build = int(builds.pop()) + 1
    _sub(pbx, r"(MARKETING_VERSION = )[0-9.]+;", rf"\g<1>{version};", 0)
    _sub(pbx, r"(CURRENT_PROJECT_VERSION = )\d+;", rf"\g<1>{ios_build};", 0)

    maker = tree / "apps" / "macos" / "tools" / "make_project.py"
    m = re.search(r'^VERSION, BUILD = "[^"]*", "(\d+)"', maker.read_text(), re.M)
    if not m:
        raise Fail("apps/macos/tools/make_project.py has no `VERSION, BUILD = ...` line")
    mac_build = int(m.group(1)) + 1
    _sub(maker, r'^VERSION, BUILD = "[^"]*", "\d+"', f'VERSION, BUILD = "{version}", "{mac_build}"', 1)

    skew = add_skew_entry(tree, version)
    log = tree / "CHANGELOG.md"
    _, drop = unreleased(tree, last_tag)
    log.write_text(fold_changelog(log.read_text(), changelog_line(version, summary, date), drop))

    sh(["uv", "lock", "--offline"], cwd=tree)
    sh(["python3", "apps/macos/tools/make_project.py"], cwd=tree)
    sh(["python3", "tools/site_version.py"], cwd=tree)
    # The benchmark pages say which version is current and that it was not measured (tests/test_bench_publish.py): 0.10.0's
    # version commit left them at 0.9.0 and turned test red.
    measured = sorted(p for p in (tree / "bench" / "results").glob("20??-??-??-v*") if (p / "manifest.json").exists())
    if measured and (tree / "bench" / "publish.py").exists():
        sh(["uv", "run", "--locked", "python", "-I", "bench/publish.py", str(measured[-1].relative_to(tree))], cwd=tree, timeout=600)
    return {"ios_build": ios_build, "mac_build": mac_build, "date": date, "skew": skew}
