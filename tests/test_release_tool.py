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
    still = [run("ui", status="in_progress", conclusion="", at="2026-11-26T13:00:00Z")] + found
    assert github.verdict(still, "ui", skip_cancelled=True, finished=True)[0] == "success"  # main's ui: the newest finished run
    assert github.verdict([run("test", sha="b" * 40)], "test", sha="a" * 40)[0] == "missing"
    assert github.verdict([run("ui", ref="v1.0.0"), run("ui", ref="main", conclusion="failure")], "ui", ref="v1.0.0")[0] == "success"


def test_a_red_main_stops_the_line(monkeypatch):
    monkeypatch.setattr(github, "main_state", lambda: {"head": ("c" * 40, None), "test": ("failure", run("test", conclusion="failure")),
                                                       "apps": ("success", run("apps")), "ui": ("success", run("ui"))})
    with pytest.raises(Fail, match="main is red"):
        preflight.ci_main()
    monkeypatch.setattr(github, "main_state", lambda: {"head": ("c" * 40, None), "test": ("success", run("test")),
                                                       "apps": ("success", run("apps")), "ui": ("failure", run("ui", conclusion="failure"))})
    assert "the tag's ui run gates" in preflight.ci_main()  # ui on main is reported: the tag's run is the gate


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


def test_the_version_commit_adds_the_skew_matrix_entry_when_main_has_none(tmp_path):
    (tmp_path / "tests/fixtures").mkdir(parents=True)
    fixture = tmp_path / preflight.SKEW_FIXTURE
    data = {"what": "x", "releases": [{"release": "0.9.0", "requests": [1]}, {"release": "0.10.0", "requests": [2, 3]}]}
    fixture.write_text(json.dumps(data, indent=1) + "\n")
    assert "has an entry for 0.10.0" in preflight.skew_entry(tmp_path, "0.10.0")
    assert "copies 0.10.0's" in preflight.skew_entry(tmp_path, "0.10.1")
    assert "added" in bump.add_skew_entry(tmp_path, "0.10.1")
    assert json.loads(fixture.read_text())["releases"][-1] == {"release": "0.10.1", "requests": [2, 3]}
    assert "has 0.10.1" in bump.add_skew_entry(tmp_path, "0.10.1")  # once only


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


def test_an_openssl_der_signature_becomes_the_64_byte_jwt_form():
    from releasekit import asc

    r, s = b"\x00" + b"\x81" * 32, b"\x01" * 31  # r with DER's sign byte, s one byte short
    der = b"\x30" + bytes([4 + len(r) + len(s)]) + b"\x02" + bytes([len(r)]) + r + b"\x02" + bytes([len(s)]) + s
    assert asc._raw_signature(der) == b"\x81" * 32 + b"\x00" + b"\x01" * 31


def test_a_network_drop_is_a_wait_not_a_defect():
    """A fetch that cannot reach github.com stopped 0.10.0's push as "failed"; resume is the answer, not a fix."""
    with pytest.raises(Stop, match="network dropped"):
        core.sh(["sh", "-c", "echo \"fatal: unable to access: Failed to connect to github.com port 443\" >&2; exit 128"])
    with pytest.raises(Fail):
        core.sh(["sh", "-c", "exit 3"])


def test_a_red_ci_run_gets_one_rerun_of_its_failed_jobs_then_counts(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path, no_wait=False)
    red = ("failure", {**run("test", conclusion="failure"), "databaseId": 7})
    answers = iter([{"test": red}, {"test": ("success", run("test"))}, {"test": red}, {"test": red}])
    reruns = []
    monkeypatch.setattr(github, "commit_state", lambda *a, **k: next(answers))
    monkeypatch.setattr(github, "sh", lambda cmd, **k: reruns.append(cmd))
    monkeypatch.setattr(github.time, "sleep", lambda s: None)
    assert "test green" in github.wait_green(ctx, "a" * 40, ("test",), "main", "CI", 1)
    assert reruns == [["gh", "run", "rerun", "7", "-R", core.REPO, "--failed"]]
    with pytest.raises(Fail, match="failed again after one re-run"):  # the same run red again: no second re-run
        github.wait_green(ctx, "a" * 40, ("test",), "main", "CI", 1)
    assert len(reruns) == 1


def test_a_new_minor_version_opens_its_own_changelog_section_and_a_patch_joins_it():
    text = "# Changelog\n\n## 0.10 (beta)\n\n- **0.10.0** (2026-11-26, beta): Many machines\n\n## 0.9 (beta)\n\n- **0.9.0** (x, beta): Linux\n"
    patch = bump.fold_changelog(text, "- **0.10.1** (2026-11-27, beta): The iPhone app", [])
    assert patch.count("## 0.10 (beta)") == 1 and patch.index("## 0.10 (beta)") < patch.index("- **0.10.1**") < patch.index("- **0.10.0**")
    minor = bump.fold_changelog(text, "- **0.11.0** (2026-12-01, beta): Next", [])
    assert minor.index("## 0.11 (beta)") < minor.index("- **0.11.0**") < minor.index("## 0.10 (beta)")


# ---------- signing in CI (.github/workflows/release.yml) ----------

def test_the_ci_image_is_checked_before_it_is_attached_because_an_asset_is_never_replaced(tmp_path, monkeypatch):
    from releasekit import ci, verify

    ctx = ctx_for(tmp_path)
    ctx.state.set(ci_mac=True, pin_commit="p" * 40)
    image = tmp_path / "ci-dmg" / "Pointe-9.9.9.dmg"
    monkeypatch.setattr(github, "release", lambda tag: {"assets": [{"name": "pointe-9.9.9.tar.gz"}]})
    monkeypatch.setattr(steps, "upload_wanted", lambda c: False)
    monkeypatch.setattr(ci, "wait_job", lambda c, platform, upload: "https://ci/job")
    monkeypatch.setattr(ci, "download_dmg", lambda c, folder: (image.parent.mkdir(exist_ok=True), image.write_bytes(b"image"), image)[2])
    ran = []
    monkeypatch.setattr(steps, "sh", lambda cmd, **k: ran.append(cmd))

    def refused(path, version, work):
        raise Fail("Gatekeeper does not accept Pointe-9.9.9.dmg")

    monkeypatch.setattr(verify, "dmg", refused)
    with pytest.raises(Fail, match="Gatekeeper"):
        steps.dmg(ctx)
    assert ran == [], "nothing attached"
    monkeypatch.setattr(verify, "dmg", lambda path, version, work: "accepted")
    assert "built in CI" in steps.dmg(ctx)
    upload = ran[-1]
    assert upload[:4] == ["gh", "release", "upload", "v9.9.9"]
    assert {Path(f).name for f in upload[6:]} == {"Pointe-9.9.9.dmg", "Pointe-9.9.9.dmg.sha256", "Pointe.dmg", "Pointe.dmg.sha256"}
    assert ctx.state.fact("dmg_sha") == github.sha256(b"image")


def test_ci_signing_needs_every_secret_and_the_tag_rule_and_the_choice_holds_on_resume(tmp_path, monkeypatch):
    from releasekit import ci

    every = {n for names in ci.SECRETS.values() for n in names}
    monkeypatch.setattr(ci, "protected", lambda: True)
    monkeypatch.setattr(ci, "secret_names", lambda: every - {"IOS_WIDGET_PROFILE"})
    ctx = ctx_for(tmp_path)
    assert ci.use(ctx, "mac") and not ci.use(ctx, "iphone"), "a missing iPhone secret sends only the iPhone to this Mac"
    monkeypatch.setattr(ci, "secret_names", lambda: every)
    assert not ci.use(ctx_for(tmp_path), "iphone"), "a resume keeps the path the release started on"
    monkeypatch.setattr(ci, "protected", lambda: False)
    assert not ci.use(ctx_for(tmp_path / "unprotected"), "mac"), "secrets an untagged ref could reach are not used"
    monkeypatch.setattr(ci, "protected", lambda: True)
    assert not ci.use(ctx_for(tmp_path / "local", local_signing=True), "mac")


def test_the_release_workflow_runs_only_by_dispatch_in_the_protected_environment_and_cleans_up():
    import yaml

    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    assert list(doc[True]) == ["workflow_dispatch"], "no push, pull_request or release trigger: tools/release dispatches it on the tag"
    assert doc["permissions"] == {"contents": "read"}
    for name, job in doc["jobs"].items():
        assert job["environment"] == "release", name
        assert "github.ref_type == 'tag'" in job["if"], name
        last = job["steps"][-1]
        assert last.get("if") == "always()" and "cleanup" in last["run"], f"{name}: the keychain and the key go, whatever happened"
        for step in job["steps"]:
            assert "secrets." not in step.get("run", ""), f"{name}: a secret reaches a step only through env"
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert not re.search(r"echo[^\n]*\$\{\{\s*secrets", text)


def test_a_test_tag_never_uploads_and_a_release_tag_must_name_its_version(tmp_path):
    script = ROOT / "tools" / "ci_signing.sh"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "RUNNER_TEMP": str(tmp_path)}
    out = subprocess.run([str(script), "pin"], env={**env, "TAG": "v0.0.0-ci-test", "UPLOAD": "true"}, capture_output=True, text=True)
    assert out.returncode == 1 and "nothing built from it is uploaded" in out.stderr
    out = subprocess.run([str(script), "pin"], env={**env, "TAG": "v0.0.0-ci-test", "UPLOAD": "false"}, capture_output=True, text=True)
    assert out.returncode == 0 and "no upload" in out.stdout
    out = subprocess.run([str(script), "pin"], env={**env, "TAG": "v99.0.0", "UPLOAD": "true"}, capture_output=True, text=True)
    assert out.returncode == 1 and "not the version at the tag" in out.stderr


def test_an_iphone_left_out_of_a_run_is_pending_not_done(tmp_path):
    ctx = ctx_for(tmp_path)
    ctx.state.set(platforms="linux,mac")
    with pytest.raises(Stop, match="pending") as stop:
        steps.ios(ctx)
    assert stop.value.waiting and "--platforms iphone,mac,linux" in stop.value.how
