"""tools/release (docs/releasing.md): the rules each release-time failure taught, held in code. Nothing here reaches
GitHub, Apple or the site: those calls are replaced at the seam (releasekit.github, releasekit.core.sh)."""

import json
import os
import re
import socket
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from releasekit import bump, core, github, notes, preflight, steps  # noqa: E402
from releasekit.core import Ctx, Fail, Lock, State, Step, Stop  # noqa: E402

VERSION_FILES = [".claude-plugin/plugin.json", "pyproject.toml", "apps/ios/Pointe.xcodeproj/project.pbxproj",
                 "apps/macos/tools/make_project.py", "CHANGELOG.md"]


def ctx_for(tmp_path, dry=False, **args) -> Ctx:
    return Ctx(root=ROOT, version="9.9.9", dry_run=dry, state=State(tmp_path / "state.json"), work=tmp_path, tree=tmp_path / "tree",
               args=type("A", (), args)())


# ---------- the version commit ----------

def test_the_bump_moves_every_version_together_and_raises_both_builds(tmp_path, monkeypatch):
    for f in VERSION_FILES:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, tmp_path / f)
    monkeypatch.setattr(bump, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))  # uv lock, make_project.py, site_version.py: not under test here
    old = bump.current(tmp_path)
    new = bump.next_versions(old)["minor"]
    pbx = (tmp_path / VERSION_FILES[2]).read_text()
    ios_before = int(pbx.split("CURRENT_PROJECT_VERSION = ")[1].split(";")[0])
    got = bump.bump(tmp_path, new, "Talk to two machines at once", date="2026-12-01")
    assert json.loads((tmp_path / ".claude-plugin/plugin.json").read_text())["version"] == new
    assert f'version = "{new}"' in (tmp_path / "pyproject.toml").read_text()
    pbx = (tmp_path / VERSION_FILES[2]).read_text()
    assert set(re.findall(r"MARKETING_VERSION = ([0-9.]+);", pbx)) == {new}
    assert set(re.findall(r"CURRENT_PROJECT_VERSION = (\d+);", pbx)) == {str(ios_before + 1)} == {str(got["ios_build"])}
    assert f'VERSION, BUILD = "{new}", "{got["mac_build"]}"' in (tmp_path / VERSION_FILES[3]).read_text()
    assert f"- **{new}** (2026-12-01, beta): Talk to two machines at once" in (tmp_path / "CHANGELOG.md").read_text()
    with pytest.raises(Fail, match="not newer"):
        bump.bump(tmp_path, old, "again")


def test_unreleased_entries_fold_into_the_version_line_and_shipped_ones_are_dropped():
    text = "\n".join(["# Changelog", "", "## 0.9 (beta)", "",
                      "- **Unreleased** (beta): Machines say which side to update", "", "  The detail of it.",
                      "- **Unreleased** (beta): New sessions skip prompts", "  continued", "",
                      "- **0.9.0** (2026-11-26, beta): Linux hub", ""])
    out = bump.fold_changelog(text, "- **0.10.0** (2026-11-27, beta): Many machines", ["- **Unreleased** (beta): New sessions skip prompts"])
    assert "Unreleased" not in out
    assert out.index("- **0.10.0**") < out.index("What is in it:") < out.index("  - Machines say which side to update") < out.index("- **0.9.0**")
    assert "    The detail of it." in out and "New sessions skip prompts" not in out


def test_the_summary_never_says_beta_because_it_becomes_the_app_stores_whats_new(tmp_path):
    ctx = ctx_for(tmp_path, summary="The beta gets faster")
    with pytest.raises(Fail, match="beta"):
        steps.version_commit(ctx)


# ---------- the gates ----------

def run(workflow, status="completed", conclusion="success", sha="a" * 40, ref="main", event="push", at="2026-11-26T10:00:00Z"):
    return {"workflowName": workflow, "status": status, "conclusion": conclusion, "headSha": sha, "headBranch": ref, "event": event,
            "createdAt": at, "url": f"https://github.com/x/{workflow}"}


def test_a_ui_run_cancelled_by_a_newer_push_says_nothing_and_a_dispatch_does_not_count():
    found = [run("ui", conclusion="cancelled", at="2026-11-26T12:00:00Z"), run("ui", event="workflow_dispatch", conclusion="failure", at="2026-11-26T11:00:00Z"),
             run("ui", conclusion="success", at="2026-11-26T09:00:00Z")]
    assert github.verdict(found, "ui", skip_cancelled=True)[0] == "success"
    assert github.verdict(found, "ui")[0] == "failure"  # on a tag nothing may be cancelled: a cancelled run is not green
    assert github.verdict([run("test", status="in_progress", conclusion="")], "test")[0] == "pending"
    assert github.verdict([run("test", sha="b" * 40)], "test", sha="a" * 40)[0] == "missing"
    assert github.verdict([run("ui", ref="v1.0.0"), run("ui", ref="main", conclusion="failure")], "ui", ref="v1.0.0")[0] == "success"


def test_a_red_main_stops_the_line(monkeypatch):
    monkeypatch.setattr(github, "main_state", lambda: {"head": ("c" * 40, None), "test": ("failure", run("test", conclusion="failure")),
                                                       "apps": ("success", run("apps")), "ui": ("success", run("ui"))})
    with pytest.raises(Fail, match="main is red"):
        preflight.ci_main()


def test_half_done_work_is_refused(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}

    def git(*a):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-q")
    (repo / "a.txt").write_text("one\n")
    git("add", "."), git("commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    (repo / "CHANGELOG.md").write_text("- **1.0.0** (x): y\n")
    git("add", "."), git("commit", "-q", "-m", "Clean subject")
    assert "no WIP" in preflight.wip(repo, base)
    (repo / "b.txt").write_text("half " + preflight.WIP_MARK + "\n")
    git("add", "."), git("commit", "-q", "-m", "WIP: the new screen")
    with pytest.raises(Fail) as e:
        preflight.wip(repo, base)
    assert "WIP: the new screen" in str(e.value) and "b.txt" in str(e.value)


def test_the_cut_version_needs_its_skew_matrix_entry(tmp_path):
    (tmp_path / "tests/fixtures").mkdir(parents=True)
    (tmp_path / preflight.SKEW_FIXTURE).write_text(json.dumps({"releases": [{"release": "0.9.0"}, {"release": "0.10.0"}]}))
    assert "0.10.0" in preflight.skew_entry(tmp_path, "0.10.0")
    with pytest.raises(Fail, match="no entry for 0.9.1"):
        preflight.skew_entry(tmp_path, "0.9.1")


# ---------- publishing ----------

def test_the_site_never_pins_a_prerelease(tmp_path, monkeypatch):
    """0.9.0: install.sh on the site pinned 0.9.0 while it was a prerelease and 0.8.7 was Latest."""
    installer = tmp_path / "install.sh"
    installer.write_text('POINTE_VERSION="0.9.0"\nPOINTE_SHA256="' + "a" * 64 + '"\n')
    page = "<p>Pointe 0.9.0 · macOS 15+ · 4.6 MB</p>".encode()
    answers = {steps.LIVE: (200, page), steps.LIVE + "install.sh": (200, installer.read_bytes()), github.LATEST_DMG: (200, b"dmg")}
    monkeypatch.setattr(github, "anonymous", lambda url, *a, **k: answers[url])
    monkeypatch.setattr(github, "latest", lambda: {"tagName": "v0.8.7"})
    problems = steps.live_checks("0.9.0", "a" * 64, installer, "4.6 MB")
    assert any("never pin a prerelease" in p for p in problems)
    monkeypatch.setattr(github, "latest", lambda: {"tagName": "v0.9.0"})
    assert steps.live_checks("0.9.0", "a" * 64, installer, "4.6 MB") == []


def test_never_latest_before_the_disk_image_and_never_with_draft_notes(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path)
    ctx.state.set(notes=str(tmp_path / "notes.md"), dmg_sha="d" * 64)
    edits = []
    monkeypatch.setattr(steps, "sh", lambda cmd, **k: edits.append(cmd))
    release = {"body": notes.DRAFT + "\nnotes", "isPrerelease": True, "assets": [{"name": "pointe-9.9.9.tar.gz"}]}
    monkeypatch.setattr(github, "release", lambda tag: release)
    with pytest.raises(Stop, match="still the draft"):
        steps.promote(ctx)
    release["body"] = "Rewritten notes"
    with pytest.raises(Fail, match="lacks"):
        steps.promote(ctx)
    assert edits == [], "nothing was promoted"


def test_a_release_found_latest_without_its_image_is_set_back(tmp_path, monkeypatch):
    """0.8.7: a duplicate agent published it Latest with the tarball only; releases/latest/download/Pointe.dmg was a 404."""
    ctx = ctx_for(tmp_path)
    ctx.state.set(previous="v9.9.8", notes=str(tmp_path / "n.md"))
    (ctx.tree / "dist").mkdir(parents=True)
    tarball = ctx.tree / "dist" / "pointe-9.9.9.tar.gz"
    tarball.write_bytes(b"tarball")
    ran = []
    monkeypatch.setattr(steps, "sh", lambda cmd, **k: ran.append(cmd))
    monkeypatch.setattr(github, "release", lambda tag: {"isPrerelease": False, "assets": [{"name": "pointe-9.9.9.tar.gz"}]})
    monkeypatch.setattr(github, "download_checked", lambda tag, name, folder: (folder / name, github.sha256(b"tarball")))
    assert "set back to prerelease" in steps.tarball(ctx)
    assert ["gh", "release", "edit", "v9.9.9", "-R", core.REPO, "--prerelease"] in ran
    assert ["gh", "release", "edit", "v9.9.8", "-R", core.REPO, "--latest"] in ran


def test_a_tag_someone_else_pushed_elsewhere_is_never_moved(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path)
    ctx.state.set(version_commit="a" * 40)
    monkeypatch.setattr(github, "remote_tag", lambda tag: "b" * 40)
    with pytest.raises(Fail, match="never moved"):
        steps.tag(ctx)


# ---------- resuming ----------

def test_resume_skips_done_steps_and_a_stop_holds_only_what_needs_it(tmp_path):
    ctx = ctx_for(tmp_path)
    calls = []

    def ok(name):
        return lambda c: calls.append(name) or f"{name} fine"

    def needs_owner(c):
        calls.append("sign")
        raise Stop("Xcode has 0 Apple Account(s)", "add the account", waiting=True)

    plan = [Step("a", "a", ok("a")), Step("sign", "sign", needs_owner, needs=("a",)), Step("upload", "upload", ok("upload"), needs=("sign",)),
            Step("linux", "linux", ok("linux"), needs=("a",))]
    out = core.run_steps(ctx, plan)
    assert [out[n].status for n in ("a", "sign", "upload", "linux")] == ["done", "waiting", "blocked", "done"]
    assert calls == ["a", "sign", "linux"]
    calls.clear()
    again = ctx_for(tmp_path)  # a later `resume`: a new process, the same state file
    core.run_steps(again, plan)
    assert calls == ["sign"], "done steps are not run again"


def test_one_release_run_at_a_time(tmp_path):
    lock = tmp_path / "lock"
    lock.write_text(json.dumps({"pid": os.getppid(), "host": socket.gethostname(), "since": "x", "version": "9.9.9"}))
    with pytest.raises(Stop, match="another release run"):
        Lock(lock).__enter__()
    lock.write_text(json.dumps({"pid": 2 ** 22 + 12345, "host": socket.gethostname()}))  # a run that died
    with Lock(lock):
        assert json.loads(lock.read_text())["pid"] == os.getpid()
    assert not lock.exists()


# ---------- the notes ----------

def test_commits_are_grouped_by_what_a_person_uses_and_test_only_commits_are_tooling():
    c = notes.Commit
    assert c("1", "Mute holds", ["pointe/ui.html", "tests/test_ui.py"]).group == "The page"
    assert c("2", "iPhone UI test: the lede", ["apps/ios/PointeUITests/NewSessionUITests.swift"]).group.startswith("Tests")
    assert c("3", "Keys in the login keyring on Linux", ["pointe/keys.py"]).group == "Linux"
    assert c("4", "CI runs the Linux hub smoke", [".github/workflows/test.yml"]).group.startswith("Tests")
    assert c("5", "Sheets say their title once", ["apps/PointeKit/Sources/PointeUI/Sheet.swift"]).group == "Both apps"
