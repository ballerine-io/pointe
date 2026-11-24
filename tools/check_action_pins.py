"""Check that every GitHub Action in .github/workflows is pinned to a commit, the one its `# vX.Y.Z` comment's tag
points to, and not to the tag object.

An annotated tag has a SHA of its own. It is 40 hex characters too, so the pattern in tests/test_supply_chain.py cannot
tell it from a commit, and a pin to it names a movable label's wrapper rather than the code.

    python3 tools/check_action_pins.py           ask github.com, compare with tests/fixtures/action_pins.json, exit 1 on a difference
    python3 tools/check_action_pins.py --write   ask github.com and record the answer in that file

It reads `git ls-remote`, so it needs git and the network, no token. The offline test reads the recorded file. After a
change to a `uses:` line (Dependabot's weekly pull request included), run it with --write and commit the file.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "action_pins.json"
USES = re.compile(r"^\s*-?\s*uses:\s*([\w.-]+/[\w.-]+)@(\S+)[ \t]*#\s*(v[\w.-]+)", re.M)


def pins() -> list[tuple[str, str, str]]:
    """(repository, pinned ref, version in the comment) for every `uses:` line, once each."""
    found = {m.groups() for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")) for m in USES.finditer(wf.read_text())}
    return sorted(found)


def tag_shas(repo: str, version: str) -> dict:
    """What the tag is on GitHub: `ref` is what refs/tags/<version> holds, `commit` the commit it leads to. They differ
    for an annotated tag, where `ref` is the tag object."""
    out = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}", f"refs/tags/{version}", f"refs/tags/{version}^{{}}"],
                         capture_output=True, text=True, check=True, timeout=60).stdout
    lines = dict(reversed(line.split("\t")) for line in out.splitlines() if line)
    ref = lines.get(f"refs/tags/{version}")
    if ref is None:
        raise SystemExit(f"{repo}: no tag {version}")
    return {"ref": ref, "commit": lines.get(f"refs/tags/{version}^{{}}", ref)}


def problem(pin: str, tag: dict | None) -> str | None:
    """Why this pin is refused, given the recorded tag; None when it is the tag's commit."""
    if tag is None:
        return "its tag is not recorded: run tools/check_action_pins.py --write"
    if pin == tag["commit"]:
        return None
    if pin == tag["ref"]:
        return f"is the tag object, not a commit: pin {tag['commit']}"
    return f"is not the commit its version comment names ({tag['commit']})"


def main() -> int:
    live = {f"{repo}@{version}": tag_shas(repo, version) for repo, _, version in pins()}
    if "--write" in sys.argv:
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n")
    recorded = json.loads(FIXTURE.read_text()) if FIXTURE.exists() else {}
    bad = [f"{repo}@{pin} ({version}) {why}" for repo, pin, version in pins() if (why := problem(pin, live[f"{repo}@{version}"]))]
    if recorded != live:
        bad.append(f"{FIXTURE.relative_to(ROOT)} differs from github.com (a tag moved, or a pin changed): look, then --write")
    print("\n".join(bad) or f"{len(live)} actions: each pin is the commit its tag points to")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
