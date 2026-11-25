"""Which CI jobs a push starts (CONTRIBUTING.md, "How to test"). The offline suite and the supply-chain gate run on every
push; the macOS jobs (apps.yml, ui.yml) only when something they build or read changes, and on a release tag. A path
filter that misses a file the Swift tests read lets a daemon change break the apps unseen until the next apps push."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SWIFT_TESTS = ("apps/PointeKit/Tests", "apps/ios/PointeTests", "apps/macos/PointeMacTests")
# Literals in the Swift tests that name a repository path but are not read from the repository.
NOT_READ = {"bin/voice-daemon": "LocatorTests makes this file in a temporary folder"}


def triggers(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())[True]  # PyYAML reads the key `on` as True


def covered(path: str, patterns: list[str]) -> bool:
    return any(path.startswith(p[:-2]) if p.endswith("/**") else path == p for p in patterns)


def test_every_repository_file_a_swift_test_reads_starts_the_apps_jobs():
    paths = triggers("apps.yml")["push"]["paths"]
    read = set()
    for folder in SWIFT_TESTS:
        for swift in (ROOT / folder).rglob("*.swift"):
            for literal in re.findall(r'"([A-Za-z0-9_./-]+)"', swift.read_text()):
                path = re.sub(r"^(\.\./)+", "", literal)
                if path and path[0] not in "/." and not path.startswith("apps/") and path not in NOT_READ and (ROOT / path).is_file():
                    read.add(path)
    assert "pointe/ui.html" in read and "install.sh" in read  # the scan still finds what it is for
    missing = sorted(p for p in read if not covered(p, paths))
    assert not missing, f"read by a Swift test but missing from apps.yml's paths: {missing}"


def test_the_apps_and_ui_jobs_run_on_a_pull_request_by_the_same_paths_and_on_every_release_tag():
    for name in ("apps.yml", "ui.yml"):
        on = triggers(name)
        assert on["push"]["paths"] == on["pull_request"]["paths"], name
        assert covered(f".github/workflows/{name}", on["push"]["paths"]), f"{name}: its own edits must run it"
        assert on["push"]["tags"] == ["v*"], f"{name}: a release tag runs it whatever changed"


def test_the_offline_suite_the_page_and_the_supply_chain_gate_run_on_every_push_in_parallel_with_the_slow_tests():
    doc = yaml.safe_load((WORKFLOWS / "test.yml").read_text())
    assert doc[True] == ["push", "pull_request"], "no path filter: offline is a required check"
    assert {"offline", "page", "supply-chain"} <= doc["jobs"].keys()
    runs = {job: " ".join(step.get("run", "") for step in doc["jobs"][job]["steps"]) for job in ("offline", "page")}
    assert all("-n auto" in run and "--runslow" in run for run in runs.values())
    assert '-m "not chrome"' in runs["offline"] and "-m chrome" in runs["page"], "between them, every test"
