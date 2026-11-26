"""The checks before a version commit: main green, nothing half-done, everything generated is current, the versions agree,
the parity matrix has no unexplained gap, the integration join passes, and the whole suite passes on this Mac."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from . import github
from .core import Fail, Stop, sh

PYTEST = ["uv", "run", "--locked", "--group", "test-tools", "pytest", "tests/", "--ignore=tests/e2e", "--runslow"]
# The integration join (tests/test_integration_join.py): the daemon as hub, the page in headless Chrome, a phone client,
# and a node, joined. Its own run here, so its result is its own line in the report.
JOIN = ["uv", "run", "--locked", "--group", "test-tools", "pytest", "-q", "tests/test_integration_join.py", "--runslow", "-p", "no:cacheprovider"]
WIP_SUBJECT = re.compile(r"^(WIP\b|wip:|fixup!|squash!|amend!|DO NOT RELEASE)|\[wip\]", re.I)
WIP_MARK = "DO-NOT-" + "RELEASE"  # written split so this file does not hold the marker it looks for


def ci_main() -> str:
    """main green on test and apps; a red main stops the line: the fix goes in before any release (CLAUDE.md). `ui` on main
    is reported, not gated: newer pushes cancel it, so it rarely finishes there, and the tag's own ui run gates the
    promotion (docs/releasing.md, step 2)."""
    got = github.main_state()
    head = got.pop("head")[0]
    ui_state, ui_run = got.pop("ui")
    red = {w: r for w, (s, r) in got.items() if s == "failure"}
    if red:
        raise Fail(f"main is red at {head[:10]}: " + ", ".join(f"{w} failed ({r['headSha'][:8]}, {r['url']})" for w, r in red.items())
                   + ". Stop the line: fix main first.")
    pending = {w: s for w, (s, _) in got.items() if s != "success"}
    if pending:
        raise Stop(f"main at {head[:10]}: " + ", ".join(f"{w} {s}" for w, s in pending.items()),
                   "Wait for CI on main, then tools/release resume", waiting=True)
    ui = f"ui's newest finished main run: {ui_state}" + (f" at {ui_run['headSha'][:8]} ({ui_run['url']})" if ui_run else "")
    return (f"main {head[:10]}: " + ", ".join(f"{w} green ({r['headSha'][:8]})" for w, (_, r) in got.items())
            + f"; {ui} (the tag's ui run gates the promotion)")


def wip(tree: Path, base: str) -> str:
    """Nothing half-done: no WIP/fixup commit since the last release and no DO-NOT-RELEASE marker in a tracked file.
    (CHANGELOG entries marked Unreleased are not half-done: the version commit folds them into its line.)"""
    problems = []
    subjects = sh(["git", "log", "--format=%h %s", f"{base}..HEAD"], cwd=tree).stdout.splitlines()
    problems += [f"commit {s}" for s in subjects if WIP_SUBJECT.search(s.split(" ", 1)[1] if " " in s else s)]
    marked = sh(["git", "grep", "-n", "-I", "-F", WIP_MARK, "--", ".", ":!tools/releasekit", ":!docs/releasing.md", ":!site/pointe/docs/releasing", ":!tests/test_release_tool.py"],
                cwd=tree, check=False).stdout.splitlines()
    problems += [f"marker {line[:120]}" for line in marked]
    if problems:
        raise Fail("half-done work would ship:\n    " + "\n    ".join(problems)
                   + "\n    Finish it or take it out on main, then run again.")
    return f"no WIP commit since {base[:10]}, no {WIP_MARK} marker"


def generated(tree: Path) -> str:
    """Everything written by a tool is what the tool writes now: the parity matrix (with no gap on any surface), the
    product help, the site's docs pages, the version on the site, and the app cards."""
    checks = [
        (["python3", "tools/parity.py", "--check"], "parity matrix"),
        (["python3", "tools/product_help.py", "--check"], "product help"),
        (["uv", "run", "--locked", "python", "tools/build_docs.py", "--check"], "docs pages"),
        (["python3", "tools/site_version.py", "--check"], "site version"),
        (["python3", "tools/apps_status.py", "--check"], "app cards"),
    ]
    stale = []
    for cmd, what in checks:
        out = sh(cmd, cwd=tree, check=False, timeout=600)
        if out.returncode != 0:
            stale.append(f"{what}: {(out.stdout + out.stderr).strip()[-200:]}")
    matrix = json.loads(sh(["python3", "tools/parity.py", "--json"], cwd=tree).stdout)
    gaps = [f"{fid} on {s}" for fid, row in matrix["features"].items() for s, c in row.items() if c["state"] in ("no", "partial")]
    if gaps:
        stale.append("parity gaps without a reason: " + ", ".join(gaps))
    surfaces = sorted(matrix["counts"])
    if stale:
        raise Fail("not current:\n    " + "\n    ".join(stale) + "\n    Regenerate on main (the tool named), commit, and run again.")
    counts = ", ".join(f"{s} {matrix['counts'][s]['yes']} yes" for s in surfaces)
    return f"parity clean on {len(surfaces)} surfaces ({counts}, 0 gaps); product help, docs pages, site version and app cards current"


SKEW_FIXTURE = "tests/fixtures/skew_requests.json"


def skew_releases(tree: Path) -> list[str]:
    path = tree / SKEW_FIXTURE
    return [r["release"] for r in json.loads(path.read_text())["releases"]] if path.exists() else []


def skew_entry(tree: Path, version: str) -> str:
    """The version-skew matrix replays each release's requests against newer ones (tests/test_skew.py). The version
    commit adds the cut version's entry, a copy of the newest one, when main has none (bump.add_skew_entry)."""
    found = skew_releases(tree)
    if not (tree / SKEW_FIXTURE).exists() or version in found:
        return f"{SKEW_FIXTURE} has an entry for {version}"
    return f"{SKEW_FIXTURE} has no {version} entry: the version commit copies {found[-1]}'s"


def skew(tree: Path, version: str | None = None) -> str:
    """The versions agree: manifest, pyproject, uv.lock, both apps, the changelog, the site, the phone protocol
    (tests/test_version.py, test_site.py, test_site_apps.py), the CI config's own pins, and the skew matrix has the cut
    version's requests."""
    entry = skew_entry(tree, version) if version else ""
    out = sh(PYTEST[:6] + ["-q", "tests/test_version.py", "tests/test_site.py", "tests/test_site_apps.py", "-p", "no:cacheprovider"],
             cwd=tree, check=False, timeout=900)
    if out.returncode != 0:
        raise Fail(f"version skew: {out.stdout.strip()[-600:]}")
    pins = sh(["python3", "tools/check_action_pins.py"], cwd=tree, check=False, timeout=300)
    if pins.returncode != 0:
        raise Fail(f"an Action pin is not the commit its tag names: {pins.stdout.strip()[-300:]}")
    return "manifest, pyproject, uv.lock, both apps, changelog, site and phone protocol agree; Action pins hold" + (f"; {entry}" if entry else "")


def join(tree: Path) -> str:
    if not (tree / "tests" / "test_integration_join.py").exists():
        raise Fail("tests/test_integration_join.py is missing: the integration gate cannot run")
    out = sh(JOIN, cwd=tree, check=False, timeout=1800, stream=True)
    if out.returncode != 0:
        raise Fail(f"the integration join failed: {out.stdout.strip()[-500:]}")
    return "integration join passed: " + (re.findall(r"\d+ passed[^\n]*", out.stdout) or ["?"])[-1]


def workers() -> str:
    """xdist workers for the local suite: other work shares this Mac, so never `auto`. At most 4, a quarter of the cores,
    or POINTE_RELEASE_WORKERS."""
    given = os.environ.get("POINTE_RELEASE_WORKERS", "")
    return given if given.isdigit() and int(given) > 0 else str(max(1, min(4, (os.cpu_count() or 4) // 4)))


def suite(tree: Path) -> str:
    """Every test, the slow ones too, on this Mac (CI's Ubuntu skips the Mac-only ones). A test that fails beside other
    workers and passes alone is reported as load-sensitive, not hidden; one that fails alone fails the release."""
    if sys.platform != "darwin":
        raise Fail("the release suite runs on a Mac: CI already ran it on Linux")
    first = sh(PYTEST + ["-q", "-n", workers(), "-m", "not serial", "--ignore=tests/test_integration_join.py"], cwd=tree, check=False, timeout=5400, stream=True)
    serial = sh(PYTEST + ["-q", "-m", "serial", "--ignore=tests/test_integration_join.py"], cwd=tree, check=False, timeout=1800, stream=True)
    flaky = []
    if first.returncode not in (0, 5):
        failed = sorted(set(re.findall(r"^FAILED (\S+)", first.stdout, re.M) + re.findall(r"^ERROR (\S+)", first.stdout, re.M)))
        if not failed:
            raise Fail(f"the suite failed without a FAILED line: {first.stdout.strip()[-400:]}")
        again = sh(PYTEST[:6] + ["-q", "--runslow", "-p", "no:xdist", *[f.split(" ")[0] for f in failed]], cwd=tree, check=False, timeout=1800)
        if again.returncode != 0:
            raise Fail("the suite failed, and these fail alone too: " + ", ".join(failed[:10]) + f" ({again.stdout.strip()[-300:]})")
        flaky = failed
    if serial.returncode not in (0, 5):
        raise Fail(f"the serial tests failed: {serial.stdout.strip()[-400:]}")
    passed = (re.findall(r"(\d+) passed", first.stdout) or ["?"])[-1]
    note = f"; {len(flaky)} failed beside other workers and passed alone: {', '.join(flaky)}" if flaky else ""
    return f"full suite --runslow on this Mac ({workers()} workers): {passed} passed{note}"


def published_pin_matches_latest(tree: Path) -> tuple[bool, str]:
    """install.sh on main pins the Latest release, never a prerelease (0.9.0's pin went out while 0.9.0 was one)."""
    text = (tree / "install.sh").read_text()
    pinned = re.search(r'^POINTE_VERSION="([^"]*)"', text, re.M).group(1)
    latest = github.latest()
    tag = (latest or {}).get("tagName", "")
    ok = tag == f"v{pinned}"
    return ok, f"install.sh on main pins {pinned}; the Latest release is {tag or 'none'}"

