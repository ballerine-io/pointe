"""What a release would carry: the commits since the last release, grouped by what a person uses, and a notes draft in
the order docs/releasing.md asks for (what Pointe is, what changed, install and update, limits)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .core import sh

DRAFT = "<!-- DRAFT: tools/release wrote this from the commit subjects. Rewrite it for a person who has never seen Pointe, then delete this line. -->"

# (group, paths that put a commit in it). A commit goes to the first group one of its files matches, so the order is
# what a person meets first. Paths are prefixes; a trailing "*" is any file with that stem.
GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Linux", ("pointe/linux",)),
    ("The page", ("pointe/ui",)),
    ("Install, setup and the command line", ("install.sh", "bin/", "plugin/", "hooks/", "channel/", ".claude-plugin/")),
    ("The iPhone app", ("apps/ios/",)),
    ("The Mac app", ("apps/macos/", "apps/PointeKit/Sources/PointeMacKit/")),
    ("Both apps", ("apps/PointeKit/",)),
    ("The voice and sessions", ("pointe/",)),
    ("Docs and the site", ("docs/", "site/", "README.md", "SECURITY.md", "PRIVACY.md", "CONTRIBUTING.md", "ROADMAP.md")),
    ("Tests, benchmarks and tooling (not in the notes)", ("",)),
]
USER_FACING = {g for g, _ in GROUPS[:7]}
LINUX_WORDS = re.compile(r"\bLinux\b|\bUbuntu\b|\btmux\b|\bkeyring\b", re.I)
# Tests and their fixtures, wherever they live: a commit that touches only these is tooling, not something a user runs.
TESTS = re.compile(r"^(tests|bench|evals)/|/(PointeUITests|PointeTests|PointeMacTests|PointeMacUITests|Tests)/|^apps/(ios|macos)/e2e/|^\.github/")


@dataclass
class Commit:
    sha: str
    subject: str
    files: list[str]

    @property
    def group(self) -> str:
        files = [f for f in self.files if not TESTS.search(f)]
        found = next((name for name, prefixes in GROUPS if any(f.startswith(p) for f in files for p in prefixes)), GROUPS[-1][0])
        return "Linux" if found in USER_FACING and LINUX_WORDS.search(self.subject) else found


def commits(root: Path, base: str, head: str) -> list[Commit]:
    """First-parent commits in base..head with the files each touched. Version, pin and Mac-download commits (the release
    flow's own) are left out."""
    out = sh(["git", "log", "--first-parent", "--no-merges", "--format=\x1e%H\x1f%s", "--name-only", f"{base}..{head}"], cwd=root).stdout
    found = []
    for block in out.split("\x1e")[1:]:
        head_line, *rest = block.strip("\n").split("\n")
        sha, subject = head_line.split("\x1f", 1)
        if re.match(r"(Version \d+\.\d+\.\d+:|The installer pins \d|The Mac download is \d)", subject):
            continue
        found.append(Commit(sha, subject, [f for f in rest if f.strip()]))
    return found


def grouped(found: list[Commit]) -> dict[str, list[Commit]]:
    out: dict[str, list[Commit]] = {name: [] for name, _ in GROUPS}
    for c in found:
        out[c.group].append(c)
    return {k: v for k, v in out.items() if v}


def first_paragraph(readme: str) -> str:
    """The README's first prose paragraph: "Pointe is …"."""
    for para in re.split(r"\n\s*\n", readme):
        if para.startswith("Pointe is"):
            return " ".join(para.split())
    return ""


def draft(root: Path, version: str, groups: dict[str, list[Commit]], since: str) -> str:
    beta = version.startswith("0.")
    lines = [DRAFT, "", first_paragraph((root / "README.md").read_text()), ""]
    if beta:
        lines += [f"**Beta ({version}): work in progress.** It works and is used every day. Expect rough edges, and please "
                  "[report them](https://github.com/ballerine-io/pointe/issues).", ""]
    lines += [f"## What is in {version}", "", f"Since {since}, in the commits' words (rewrite in a user's):", ""]
    for name, items in groups.items():
        if name not in USER_FACING:
            continue
        lines += [f"{name}:", ""] + [f"- {c.subject} ({c.sha[:8]})" for c in items] + [""]
    internal = sum(len(v) for k, v in groups.items() if k not in USER_FACING)
    if internal:
        lines += [f"Also {internal} commits to the docs, site, tests, benchmarks and tooling.", ""]
    lines += [
        "## Install and update", "",
        f"- **Mac:** download `Pointe-{version}.dmg` below (or the site's Download for Mac), drag Pointe to Applications, open it.",
        "- **Claude Code plugin:** `claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe`.",
        "  To update: `claude plugin marketplace update pointe`, then `claude plugin update pointe@pointe`, then `/pointe:stop` and `/pointe:voice`.",
        "- **Codex, OpenCode, or Linux (hub or node):** `bash install.sh` from https://eng.ballerine.com/pointe/install.sh, checked against this "
        "release's SHA-256. To update a standalone install: `pointe update`.",
        "- **iPhone:** the App Store, or the next version early on TestFlight.", "",
        "## Limits", "", "The README's Limits section, and anything this version is known not to fix: (fill in)", "",
    ]
    return "\n".join(lines)


def summary_line(groups: dict[str, list[Commit]]) -> str:
    """How many commits per user-facing group, for the plan."""
    return ", ".join(f"{k}: {len(v)}" for k, v in groups.items())
