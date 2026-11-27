"""The release, step by step (docs/releasing.md). Each step: what `cut`/`resume` does, and what `--dry-run` does instead
(every check, nothing published: no push, no tag, no release, no upload, no deploy)."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import bump as bumpmod
from . import ci, creds, github, notes, preflight, verify
from .core import REPO, Ctx, Fail, Step, Stop, sh

ORIGIN = f"https://github.com/{REPO}.git"
PREVIEW = "https://{branch}.pointe-site-9tz.pages.dev/pointe/"
LIVE = "https://eng.ballerine.com/pointe/"
SCREENS = ("apps/PointeKit/Sources/PointeUI/", "apps/ios/Pointe/")  # what the App Store screenshots show


def git(ctx: Ctx, *args: str, check: bool = True) -> str:
    return sh(["git", *args], cwd=ctx.tree, check=check).stdout.strip()


def need(probe: creds.Probe) -> None:
    if not probe.ok:
        raise Stop(probe.detail, probe.fix, waiting=True)


def fetch(ctx: Ctx) -> None:
    git(ctx, "fetch", "-q", "--tags", "origin", "+refs/heads/main:refs/remotes/origin/main")


def on_main(ctx: Ctx, sha: str) -> bool:
    fetch(ctx)
    return sh(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=ctx.tree, check=False).returncode == 0


def push_to_main(ctx: Ctx, commit: str, subject: str) -> str:
    """Put `commit`'s change on main: cherry-picked onto the newest main and pushed, three tries when main moves under
    it. Returns the commit on main. Used for the pin and the Mac download, which touch files nothing else does."""
    for _ in range(3):
        fetch(ctx)
        git(ctx, "checkout", "-q", "--detach", "origin/main")
        git(ctx, "cherry-pick", commit)
        if sh(["git", "push", "origin", "HEAD:main"], cwd=ctx.tree, check=False).returncode == 0:
            return git(ctx, "rev-parse", "HEAD")
        ctx.say(f"    main moved while pushing {subject!r}: again")
    raise Stop(f"could not push {subject!r}: main kept moving", "tools/release resume", waiting=True)


# ---------- preflight ----------

def tree(ctx: Ctx) -> str:
    """The release worktree, detached at the newest main, clean. Refuses a version someone else is already cutting."""
    if not (ctx.tree / ".git").exists():
        sh(["git", "fetch", "-q", "--tags", "origin", "+refs/heads/main:refs/remotes/origin/main"], cwd=ctx.root)
        ctx.tree.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "worktree", "add", "-q", "--detach", str(ctx.tree), "origin/main"], cwd=ctx.root)
    fetch(ctx)
    if git(ctx, "status", "--porcelain"):
        raise Fail(f"the release worktree {ctx.tree} has changes: look, then remove it (git worktree remove) and run again")
    git(ctx, "checkout", "-q", "--detach", "origin/main")
    base = git(ctx, "rev-parse", "HEAD")
    old = bumpmod.current(ctx.tree)
    if bumpmod.parse(ctx.version) <= bumpmod.parse(old):
        raise Fail(f"{ctx.version} is not newer than main's {old}")
    tags = [t for t in git(ctx, "tag", "--list", "v*").split() if bumpmod.VERSION_RE.fullmatch(t[1:])]
    highest = max(tags, key=lambda t: bumpmod.parse(t[1:]), default="v0.0.0")
    if bumpmod.parse(ctx.version) <= bumpmod.parse(highest[1:]):
        raise Fail(f"{ctx.version} is not newer than the newest tag {highest}")
    taken = github.remote_tag(ctx.tag)
    if taken and not ctx.state.fact("tagged") and not getattr(ctx.args, "adopt", False):
        raise Stop(f"{ctx.tag} already exists on github.com (at {taken[:10]}), and this clone did not make it: another run "
                   "is cutting it (0.8.7 was tagged and published by a duplicate agent).",
                   "If that run is yours, resume it where it runs. To take it over here: tools/release resume --adopt")
    latest = github.latest() or {}
    ctx.state.set(base=base, previous=latest.get("tagName", highest), last_tag=highest)
    (ctx.tree / "apps" / "ios" / ".team").write_text(creds.TEAM + "\n")  # gitignored: release.sh needs it
    return f"worktree {ctx.tree} at main {base[:10]}; {old} -> {ctx.version}; Latest {latest.get('tagName', 'none')}, newest tag {highest}"


def ci_main(ctx: Ctx) -> str:
    """A cut waits up to 45 minutes for main's CI to finish (red fails at once); a dry run and --no-wait report it."""
    end = time.monotonic() + 45 * 60
    while True:
        try:
            return preflight.ci_main()
        except Stop as e:
            if ctx.dry_run or getattr(ctx.args, "no_wait", False) or time.monotonic() > end:
                raise
            ctx.say(f"    {e.why}: waiting")
            time.sleep(60)


def wip(ctx: Ctx) -> str:
    return preflight.wip(ctx.tree, ctx.state.fact("last_tag"))


def generated(ctx: Ctx) -> str:
    return preflight.generated(ctx.tree)


def skew(ctx: Ctx) -> str:
    return preflight.skew(ctx.tree, ctx.version)


def join(ctx: Ctx) -> str:
    return preflight.join(ctx.tree)


def suite(ctx: Ctx) -> str:
    """--suite-from-ci: when the Mac is too loaded for the local run, CI's full suite on this exact commit stands in (it
    runs everything with --runslow on Linux; the Mac-only tests are then not run, and the report says so)."""
    if getattr(ctx.args, "suite_from_ci", False):
        base = ctx.state.fact("base")
        state, run = github.commit_state(base, ("test",), "main")["test"]
        if state != "success":
            raise Stop(f"CI's suite on {base[:10]} is {state}", "Wait for it, or run the local suite, then tools/release resume", waiting=state == "pending")
        return f"the local suite was not run (--suite-from-ci): CI's full suite on {base[:10]} is green ({run['url']}); the Mac-only tests did not run"
    return preflight.suite(ctx.tree)


def draft_notes(ctx: Ctx) -> str:
    """The notes draft, from the commits since the Latest release (a prerelease never promoted is not a release people
    got). An edited file is never overwritten; --notes FILE takes that file instead."""
    since = ctx.state.fact("previous")
    found = notes.commits(ctx.tree, since, "HEAD")
    groups = notes.grouped(found)
    path = ctx.work / "notes.md"
    given = getattr(ctx.args, "notes", None)
    if given:
        shutil.copyfile(given, path)
    elif not path.exists() or notes.DRAFT in path.read_text():
        path.write_text(notes.draft(ctx.tree, ctx.version, groups, since))
    ctx.state.set(notes=str(path))
    user = sum(len(v) for k, v in groups.items() if k in notes.USER_FACING)
    state = "a draft: edit it before the release is promoted" if notes.DRAFT in path.read_text() else "edited"
    return f"{len(found)} commits since {since} ({user} user-facing; {notes.summary_line(groups)}); notes {path} ({state})"


# ---------- the version commit and the tag ----------

def version_commit(ctx: Ctx) -> str:
    summary = getattr(ctx.args, "summary", None) or ("A dry run of the release tool" if ctx.dry_run else None)
    if not summary:
        raise Stop("the version commit needs its subject", 'tools/release resume --summary "<what changed, in the words a user would use>"')
    if re.search(r"\bbeta\b", summary, re.I):
        raise Fail("the summary says 'beta': it becomes the App Store's What's New, which must not (App Review 2.2)")
    git(ctx, "checkout", "-q", "--detach", ctx.state.fact("base"))
    builds = bumpmod.bump(ctx.tree, ctx.version, summary, last_tag=ctx.state.fact("last_tag", ""))
    changed = sorted(f for f in sh(["git", "diff", "--name-only", "HEAD"], cwd=ctx.tree).stdout.split() if f)  # porcelain's columns break under strip()
    expected = {".claude-plugin/plugin.json", "pyproject.toml", "uv.lock", "CHANGELOG.md", "apps/ios/Pointe.xcodeproj/project.pbxproj",
                "apps/macos/tools/make_project.py", "apps/macos/PointeMac.xcodeproj/project.pbxproj"}
    expected.add("tests/fixtures/skew_requests.json")
    stray = [f for f in changed if f not in expected and not f.startswith(("site/", "docs/benchmarks/"))]
    if stray:
        raise Fail(f"the version bump changed files it should not: {stray}")
    checks = ["tests/test_version.py", "tests/test_site.py", "tests/test_site_apps.py"]
    checks += [t for t in ("tests/test_skew.py", "tests/test_bench_publish.py", "tests/test_docs_site.py") if (ctx.tree / t).exists()]
    out = sh(preflight.PYTEST[:6] + ["-q", *checks, "-p", "no:cacheprovider"], cwd=ctx.tree, check=False, timeout=900)
    if out.returncode != 0:
        raise Fail(f"the version tests fail on the bump: {out.stdout.strip()[-500:]}")
    git(ctx, "add", "-A")
    git(ctx, "commit", "-q", "-s", "-m", f"Version {ctx.version}: {summary}")
    sha = git(ctx, "rev-parse", "HEAD")
    ctx.state.set(version_commit=sha, **{k: v for k, v in builds.items() if k != "skew"})
    return f"{sha[:10]} Version {ctx.version} (iPhone build {builds['ios_build']}, Mac build {builds['mac_build']}); version tests pass"


def push_version(ctx: Ctx) -> str:
    sha = ctx.state.fact("version_commit")
    if on_main(ctx, sha):
        return f"{sha[:10]} is on main"
    if sh(["git", "push", "origin", f"{sha}:refs/heads/main"], cwd=ctx.tree, check=False).returncode != 0:
        # main moved after the checks: the version commit must sit on the commit that was checked, so check again
        for name in [s.name for s in STEPS if s.name.startswith("preflight.")] + ["version.commit"]:
            ctx.state.mark(name, "", "main moved: run again")
        ctx.state.set(version_commit=None)
        raise Stop("main moved after the preflight: the version commit must sit on the commit that was checked",
                   "tools/release resume (runs the preflight again on the new main)", waiting=True)
    if not on_main(ctx, sha):
        raise Fail(f"pushed, but {sha[:10]} is not an ancestor of origin/main")
    return f"{sha[:10]} pushed to main (ancestry checked)"


def dry_push_version(ctx: Ctx) -> str:
    out = sh(["git", "push", "--dry-run", "origin", "HEAD:refs/heads/main"], cwd=ctx.tree, check=False)
    if out.returncode != 0:
        raise Fail(f"a push to main would be refused: {out.stderr.strip()[-200:]}")
    return "dry run: the push to main would be accepted (fast-forward, signed in); nothing pushed"


DOCS_ONLY = ("docs/", "site/", "tests/", "tools/", "bench/", "README.md", "CHANGELOG.md")


def version_ci(ctx: Ctx) -> str:
    """test on the commit the tag will name; apps there too, unless that commit is the version commit plus changes apps
    does not build (docs, site, tests, tools: its path filter skips them), when the version commit's apps run counts."""
    target, bump = ctx.state.fact("version_commit"), ctx.state.fact("version_commit_bump")
    out = github.wait_green(ctx, target, ("test",), "main", "CI on the version commit", 45)
    apps_on = target
    if bump and bump != target:
        later = [f for f in sh(["git", "diff", "--name-only", bump, target], cwd=ctx.tree).stdout.split() if f]
        if all(f.startswith(DOCS_ONLY) for f in later):
            apps_on = sh(["git", "rev-parse", bump], cwd=ctx.tree).stdout.strip()
    return out + "; " + github.wait_green(ctx, apps_on, ("apps",), "main", f"apps on {apps_on[:10]}", 45)


def tag(ctx: Ctx) -> str:
    sha = ctx.state.fact("version_commit")
    at = github.remote_tag(ctx.tag)
    if at:
        if at != sha:
            raise Fail(f"{ctx.tag} on github.com points at {at[:10]}, not the version commit {sha[:10]}: someone else tagged it. "
                       "A pushed tag is never moved: cut the next patch version")
        ctx.state.set(tagged=True)
        return f"{ctx.tag} is on github.com at {sha[:10]}"
    if not git(ctx, "tag", "--list", ctx.tag):
        git(ctx, "tag", "-a", ctx.tag, "-m", f"Pointe {ctx.version}", sha)
    elif git(ctx, "rev-list", "-n", "1", ctx.tag) != sha:
        raise Fail(f"a local tag {ctx.tag} points elsewhere: delete it (never a pushed one) and resume")
    git(ctx, "push", "origin", ctx.tag)
    ctx.state.set(tagged=True)
    return f"{ctx.tag} -> {sha[:10]}, pushed"


def dry_tag(ctx: Ctx) -> str:
    if github.remote_tag(ctx.tag) or git(ctx, "tag", "--list", ctx.tag):
        raise Fail(f"{ctx.tag} already exists")
    return f"dry run: {ctx.tag} is free on github.com and here; nothing tagged"


def tag_ci(ctx: Ctx) -> str:
    return github.wait_green(ctx, ctx.state.fact("version_commit"), ("test", "apps"), ctx.tag, "CI on the tag", 45)


# ---------- artifacts ----------

def _tarball(ctx: Ctx, ref: str) -> Path:
    """dist/pointe-X.Y.Z.tar.gz and .sha256: `git archive` of the ref, as tools/release_tarball.py build writes it."""
    dist = ctx.tree / "dist"
    dist.mkdir(exist_ok=True)
    name = f"pointe-{ctx.version}.tar.gz"
    sh(["git", "archive", "--format=tar.gz", f"--prefix=pointe-{ctx.version}/", "-o", str(dist / name), ref], cwd=ctx.tree)
    digest = github.sha256((dist / name).read_bytes())
    (dist / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    return dist / name


def tarball(ctx: Ctx) -> str:
    """The tarball, and the release created as a prerelease with it. Never Latest here: that waits for the disk image."""
    sh(["python3", "tools/release_tarball.py", "build", ctx.tag], cwd=ctx.tree)
    local = ctx.tree / "dist" / f"pointe-{ctx.version}.tar.gz"
    digest = github.sha256(local.read_bytes())
    rel = github.release(ctx.tag)
    if rel is None:
        sh(["gh", "release", "create", ctx.tag, "-R", REPO, "--prerelease", "--verify-tag", "--title", f"Pointe {ctx.version}",
            "--notes-file", ctx.state.fact("notes"), str(local), f"{local}.sha256"], cwd=ctx.tree)
        ctx.state.set(tarball_sha=digest)
        return f"prerelease {ctx.tag} created with {local.name} ({digest[:12]}…)"
    names = github.asset_names(rel)
    note = ""
    if not rel["isPrerelease"] and f"Pointe-{ctx.version}.dmg" not in names:
        # 0.8.7: published as Latest with the tarball only, so releases/latest/download/Pointe.dmg was a 404
        previous = ctx.state.fact("previous")
        sh(["gh", "release", "edit", ctx.tag, "-R", REPO, "--prerelease"])
        if previous:
            sh(["gh", "release", "edit", previous, "-R", REPO, "--latest"])
        note = f"; it was Latest without its disk image: set back to prerelease, {previous} Latest again"
    if local.name in names:
        _, published = github.download_checked(ctx.tag, local.name, ctx.work / "check")
        if published != digest:
            raise Fail(f"the release's {local.name} is {published}, the tag builds {digest}: never replace an asset; cut a new patch")
    else:
        sh(["gh", "release", "upload", ctx.tag, "-R", REPO, str(local), f"{local}.sha256"])
    ctx.state.set(tarball_sha=digest)
    return f"{ctx.tag} exists; {local.name} {digest[:12]}… matches the tag byte for byte{note}"


def dry_tarball(ctx: Ctx) -> str:
    if github.release(ctx.tag):
        raise Fail(f"a GitHub Release {ctx.tag} already exists")
    path = _tarball(ctx, "HEAD")
    digest = github.sha256(path.read_bytes())
    ctx.state.set(tarball_sha=digest, candidate=str(path))
    return f"dry run: {path.name} built from the version commit ({path.stat().st_size / 1e6:.1f} MB, {digest[:12]}…); no release created"


def pin(ctx: Ctx) -> str:
    """install.sh pinned to this release, on a commit that is the tag plus the pin and nothing else (the disk image and the
    iPhone build come from it), and the same change on main."""
    digest = ctx.state.fact("tarball_sha")
    if not ctx.state.fact("pin_commit"):
        git(ctx, "checkout", "-q", "--detach", ctx.tag)
        sh(["python3", "tools/release_tarball.py", "pin", ctx.tag], cwd=ctx.tree)
        git(ctx, "add", "install.sh", "apps/PointeKit/Sources/PointeMacKit/Installer.swift")
        git(ctx, "commit", "-q", "-s", "-m", f"The installer pins {ctx.version}")
        ctx.state.set(pin_commit=git(ctx, "rev-parse", "HEAD"))
    pinned = sh(["git", "show", "origin/main:install.sh"], cwd=ctx.tree).stdout
    if f'POINTE_VERSION="{ctx.version}"' in pinned and digest in pinned:
        main_sha = "already on main"
    else:
        main_sha = push_to_main(ctx, ctx.state.fact("pin_commit"), f"The installer pins {ctx.version}")[:10]
        ctx.state.set(pin_main=main_sha)
    git(ctx, "checkout", "-q", "--detach", ctx.state.fact("pin_commit"))
    return f"install.sh pins {ctx.version} ({digest[:12]}…): build commit {ctx.state.fact('pin_commit')[:10]}, main {main_sha}"


def dry_pin(ctx: Ctx) -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_tarball", ctx.tree / "tools" / "release_tarball.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    text = mod.pin((ctx.tree / "install.sh").read_text(), ctx.version, ctx.state.fact("tarball_sha"))
    if f'POINTE_VERSION="{ctx.version}"' not in text:
        raise Fail("the pin did not write the version")
    if not re.search(r'static let scriptSHA256 = "[0-9a-f]{64}"', mod.APP_INSTALLER.read_text()):
        raise Fail("Installer.swift has no scriptSHA256 line for the pin to write")
    return f"dry run: install.sh would pin {ctx.version} and the Mac app's Installer.swift its SHA-256; nothing written"


def _dmg_probes() -> None:
    for probe in (creds.xcode_tools, creds.keychain_unlocked, creds.developer_id, creds.notary_profile):
        need(probe())


def dmg(ctx: Ctx) -> str:
    rel = github.release(ctx.tag) or {}
    names = github.asset_names(rel)
    versioned = f"Pointe-{ctx.version}.dmg"
    wanted = {versioned, f"{versioned}.sha256", "Pointe.dmg", "Pointe.dmg.sha256"}
    if wanted <= names:
        return f"{versioned} and Pointe.dmg are attached (checked in verify)"
    if {versioned, f"{versioned}.sha256"} <= names:  # the copy under the stable name is missing: attach it from the asset
        path, _ = github.download_checked(ctx.tag, versioned, ctx.work / "dmg")
        stable = path.with_name("Pointe.dmg")
        shutil.copyfile(path, stable)
        stable.with_name("Pointe.dmg.sha256").write_text(f"{github.sha256(stable.read_bytes())}  Pointe.dmg\n")
        sh(["gh", "release", "upload", ctx.tag, "-R", REPO, str(stable), f"{stable}.sha256"])
        return "Pointe.dmg attached from the versioned image"
    given = getattr(ctx.args, "mac_app", None)
    if not given and ci.use(ctx, "mac"):
        return dmg_in_ci(ctx)
    if given:  # a Pointe.app notarized elsewhere (Xcode's Organizer, when xcodebuild cannot use the account)
        need(creds.keychain_unlocked())
        need(creds.notary_profile())
    else:
        _dmg_probes()
    if Path("/Volumes/Pointe").exists():
        raise Stop("a volume named Pointe is mounted", "Eject it (Finder lays the new image out by that name), then tools/release resume")
    git(ctx, "checkout", "-q", "--detach", ctx.state.fact("pin_commit"))
    out = sh(["tools/build_dmg.sh", "--upload", *(["--app", str(Path(given).expanduser())] if given else [])], cwd=ctx.tree,
             check=False, timeout=7200, stream=True)
    if out.returncode == 3:
        raise Stop("build_dmg.sh stopped before signing or notarizing the image: " + preflight_tail(out.stdout), creds.developer_id().fix, waiting=True)
    if out.returncode != 0:
        said = out.stdout
        if "No Accounts" in said or "No signing certificate" in said:
            raise Stop("Xcode has no Apple Account to export the app with", creds.xcode_account().fix, waiting=True)
        raise Fail(f"build_dmg.sh failed: {preflight_tail(said)}")
    image = ctx.tree / "dist" / versioned
    ctx.state.set(dmg_sha=github.sha256(image.read_bytes()), dmg_bytes=image.stat().st_size)
    return f"{versioned} built from {ctx.state.fact('pin_commit')[:10]}: signed, notarized, stapled, attached with Pointe.dmg"


def upload_wanted(ctx) -> bool:
    """The workflow uploads the iPhone build unless the release leaves the iPhone out or App Store Connect has it."""
    if without_iphone(ctx) or not ci.use(ctx, "iphone"):
        return False
    from . import asc

    return not (asc.have_key() and asc.build(ctx.version, ctx.state.fact("ios_build")))


def dmg_in_ci(ctx: Ctx) -> str:
    """The release workflow's mac job: the image it built from the tag plus the pin, checked here (spctl, stapler, a
    quarantined mount) before it is attached, since a published asset is never replaced."""
    url = ci.wait_job(ctx, "mac", upload_wanted(ctx))
    image = ci.download_dmg(ctx, ctx.work / "ci-dmg")
    checked = verify.dmg(image, ctx.version, ctx.work)
    dist = ctx.tree / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    digest = github.sha256(image.read_bytes())
    files = []
    for name in (image.name, "Pointe.dmg"):  # the same bytes under the stable name releases/latest/download/Pointe.dmg needs
        shutil.copyfile(image, dist / name)
        (dist / f"{name}.sha256").write_text(f"{digest}  {name}\n")
        files += [str(dist / name), str(dist / f"{name}.sha256")]
    sh(["gh", "release", "upload", ctx.tag, "-R", REPO, *files])
    ctx.state.set(dmg_sha=digest, dmg_bytes=image.stat().st_size, dmg_ci=url)
    return f"{image.name} built in CI ({url}) from the tag plus the pin; {checked}; attached with Pointe.dmg ({digest[:12]}…)"


def preflight_tail(text: str) -> str:
    return " / ".join(line.strip() for line in text.strip().splitlines()[-4:])[:400]


def dry_ci(ctx: Ctx, platform: str) -> str | None:
    """A dry run's word on the CI path: None when this release would sign on this Mac instead."""
    if getattr(ctx.args, "local_signing", False):
        return None
    lacking = ci.missing(platform)
    if lacking:
        ctx.say(f"    CI signing for {platform}: the environment {ci.ENVIRONMENT} lacks {', '.join(lacking)}; this Mac signs")
        return None
    if not ci.protected():
        raise Fail(f"the environment {ci.ENVIRONMENT} holds the signing secrets but does not admit only tags matching {ci.TAG_RULE}")
    return (f"dry run: CI signs it ({ci.WORKFLOW} on the tag, environment {ci.ENVIRONMENT}: all {len(ci.SECRETS[platform])} "
            f"secrets, deployments from tags {ci.TAG_RULE} only); nothing dispatched")


def dry_dmg(ctx: Ctx) -> str:
    sh(["bash", "-n", "tools/build_dmg.sh"], cwd=ctx.tree)
    said = dry_ci(ctx, "mac")
    if said:
        return said
    probes = [p() for p in (creds.xcode_tools, creds.keychain_unlocked, creds.developer_id, creds.notary_profile)]
    sh(["bash", "-n", "tools/build_dmg.sh"], cwd=ctx.tree)
    missing = [p for p in probes if not p.ok]
    if missing:
        raise Stop("dry run: a cut would stop here: " + "; ".join(p.detail for p in missing), "\n".join(p.fix for p in missing), waiting=True)
    return "dry run: Xcode's account, the Developer ID identity, the notary profile and the keychain are ready; nothing built"


def ios(ctx: Ctx) -> str:
    if without_iphone(ctx):
        return f"skip: the iPhone app is not in {ctx.version} (--platforms {ctx.state.fact('platforms')})"
    if ctx.state.fact("ios_uploaded"):
        return ctx.state.fact("ios_uploaded")
    from . import asc

    if asc.have_key() and asc.build(ctx.version, ctx.state.fact("ios_build")):  # uploaded already: another run, or Xcode's Organizer
        done = f"App Store Connect already has {ctx.version} ({ctx.state.fact('ios_build')}); not uploaded again"
        ctx.state.set(ios_uploaded=done)
        return done
    if ci.use(ctx, "iphone"):
        return ios_in_ci(ctx)
    need(creds.xcode_tools())
    need(creds.keychain_unlocked())
    need(creds.apple_distribution())
    build = ctx.state.fact("ios_build")
    ipa = ctx.tree / "apps" / "ios" / "build" / "export" / "Pointe.ipa"
    if not ipa.exists() or ctx.state.fact("ipa_build") != build:
        git(ctx, "checkout", "-q", "--detach", ctx.state.fact("pin_commit"))
        (ctx.tree / "apps" / "ios" / ".team").write_text(creds.TEAM + "\n")
        # manual signing: the Apple Distribution identity and the App Store profiles installed on this Mac, no Xcode account
        out = sh(["apps/ios/release.sh", "--manual"], cwd=ctx.tree, check=False, timeout=5400, stream=True)
        if out.returncode != 0 or not ipa.exists():
            said = out.stdout + out.stderr
            if re.search(r"No signing certificate|no .*profile|doesn't match|Provisioning profile", said, re.I):
                raise Stop("the manual iPhone export needs the Apple Distribution identity and the two App Store profiles",
                           'The owner: an "Apple Distribution" certificate of team ' + creds.TEAM + ' in the login keychain, and the '
                           'App Store profiles "Pointe App Store" and "Pointe Widget App Store" installed', waiting=True)
            raise Fail(f"the iPhone export failed: {preflight_tail(said)}")
        ctx.state.set(ipa_build=build)
    if not getattr(ctx.args, "asc_key_file", False):
        raise Stop(f"Pointe.ipa {ctx.version} ({build}) is exported ({ipa}); the upload needs the API key as a file, which needs the owner's yes",
                   f"The owner approves it once: tools/release resume --asc-key-file. Or uploads {ipa} with Transporter.", waiting=True)
    from . import asc as asc_

    out = asc_.upload_ipa(str(ipa))
    said = out.stdout + out.stderr
    if out.returncode == 0 and re.search(r"No errors uploading|UPLOAD SUCCEEDED|Delivery UUID", said, re.I):
        done = f"Pointe {ctx.version} ({build}) uploaded to App Store Connect (manual signing, API key)"
    elif re.search(r"bundle version must be higher|already been (used|uploaded)|redundant binary upload", said, re.I):
        done = f"App Store Connect already has {ctx.version} ({build}): uploaded by another run; not uploaded again"
    else:
        raise Fail(f"the iPhone upload failed: {preflight_tail(said)}")
    ctx.state.set(ios_uploaded=done)
    return done


def ios_in_ci(ctx: Ctx) -> str:
    """The release workflow's iphone job: archived, exported with Apple Distribution and uploaded with the API key."""
    build = ctx.state.fact("ios_build")
    try:
        url = ci.wait_job(ctx, "iphone", upload_wanted(ctx))
    except Fail:
        from . import asc

        if asc.have_key() and asc.build(ctx.version, build):  # the upload went through before a later step failed
            url = ctx.state.fact("ci_run_url")
        else:
            raise
    done = (f"Pointe {ctx.version} ({build}) built, signed and uploaded to App Store Connect in CI ({url})" if ctx.state.fact("ci_upload")
            else f"Pointe {ctx.version} ({build}) built and signed in CI ({url}); App Store Connect had it already, so not uploaded")
    ctx.state.set(ios_uploaded=done)
    return done


def dry_ios(ctx: Ctx) -> str:
    sh(["bash", "-n", "apps/ios/release.sh"], cwd=ctx.tree)
    said = dry_ci(ctx, "iphone")
    if said:
        return said.replace("nothing dispatched", f"build {ctx.state.fact('ios_build')}; nothing dispatched or uploaded")
    probes = [creds.xcode_tools(), creds.keychain_unlocked(), creds.apple_distribution()]
    missing = [p for p in probes if not p.ok]
    if missing:
        raise Stop("dry run: a cut would stop here: " + "; ".join(p.detail for p in missing), "\n".join(p.fix for p in missing), waiting=True)
    return f"dry run: ready to archive and upload build {ctx.state.fact('ios_build')}; nothing uploaded"


# ---------- verify ----------

def assets(ctx: Ctx) -> str:
    """Every file of the release, downloaded as a stranger, against its published .sha256, the local build and the pin."""
    rel = github.release(ctx.tag)
    folder = ctx.work / "download"
    out = []
    for name in (f"pointe-{ctx.version}.tar.gz", f"Pointe-{ctx.version}.dmg", "Pointe.dmg"):
        _, digest = github.download_checked(ctx.tag, name, folder)
        listed = next((a.get("digest") for a in rel["assets"] if a["name"] == name), None)
        if listed and listed != f"sha256:{digest}":
            raise Fail(f"{name}: GitHub lists {listed}, the download is {digest}")
        out.append((name, digest))
    digests = dict(out)
    if digests[f"pointe-{ctx.version}.tar.gz"] != ctx.state.fact("tarball_sha"):
        raise Fail("the published tarball is not the one the tag builds and install.sh pins")
    if digests["Pointe.dmg"] != digests[f"Pointe-{ctx.version}.dmg"]:
        raise Fail("Pointe.dmg is not the same image as the versioned one (0.8.2's first held the previous app)")
    ctx.state.set(dmg_sha=digests["Pointe.dmg"], dmg_bytes=(folder / "Pointe.dmg").stat().st_size, sha256s=digests)
    return "anonymous downloads match their .sha256: " + ", ".join(f"{n} {d[:12]}…" for n, d in out)


def dry_assets(ctx: Ctx) -> str:
    """Against the current Latest release (the candidate has none yet), and a word on any prerelease left unfinished."""
    latest = github.latest()
    if not latest:
        raise Fail("there is no Latest release")
    tag_ = latest["tagName"]
    v = tag_[1:]
    rel = github.release(tag_)
    folder = ctx.work / "download"
    found = []
    for name in (f"pointe-{v}.tar.gz", f"Pointe-{v}.dmg", "Pointe.dmg"):
        if name not in github.asset_names(rel):
            raise Fail(f"the Latest release {tag_} has no {name}")
        _, digest = github.download_checked(tag_, name, folder)
        found.append(f"{name} {digest[:12]}…")
    ctx.state.set(dry_latest=tag_, dry_dmg=str(folder / f"Pointe-{v}.dmg"))
    stuck = [r["tagName"] for r in github.releases(10) if r["isPrerelease"] and bumpmod.parse(r["tagName"][1:]) > bumpmod.parse(v)]
    tail = ""
    for t in stuck:
        missing = {f"Pointe-{t[1:]}.dmg", "Pointe.dmg"} - github.asset_names(github.release(t))
        tail += f"; {t} is a prerelease never promoted" + (f" (no {', '.join(sorted(missing))})" if missing else "")
    return f"dry run, on the Latest release {tag_}: " + ", ".join(found) + " match their published .sha256" + tail


def dmg_check(ctx: Ctx) -> str:
    return verify.dmg(ctx.work / "download" / f"Pointe-{ctx.version}.dmg", ctx.version, ctx.work)


def dry_dmg_check(ctx: Ctx) -> str:
    v = ctx.state.fact("dry_latest", "")[1:]
    return "dry run, on the Latest release: " + verify.dmg(Path(ctx.state.fact("dry_dmg")), v, ctx.work)


def mac_install(ctx: Ctx) -> str:
    git(ctx, "checkout", "-q", "--detach", ctx.state.fact("pin_commit"))
    return verify.mac_install(ctx.tree / "install.sh", ctx.version, ctx.work)


def dry_mac_install(ctx: Ctx) -> str:
    """main's install.sh as published: what a stranger installs today."""
    pinned = re.search(r'^POINTE_VERSION="([^"]*)"', (ctx.tree / "install.sh").read_text(), re.M).group(1)
    return "dry run, main's install.sh: " + verify.mac_install(ctx.tree / "install.sh", pinned, ctx.work)


def linux(ctx: Ctx) -> str:
    git(ctx, "checkout", "-q", "--detach", ctx.state.fact("pin_commit"))
    return verify.linux(ctx.tree / "install.sh", ctx.version, ctx.work)


def dry_linux(ctx: Ctx) -> str:
    """The candidate (this main as version X, not published) by its SHA-256, and main's pinned release from github.com."""
    candidate = verify.linux(ctx.tree / "install.sh", ctx.version, ctx.work, tarball=Path(ctx.state.fact("candidate")))
    pinned = re.search(r'^POINTE_VERSION="([^"]*)"', (ctx.tree / "install.sh").read_text(), re.M).group(1)
    published = verify.linux(ctx.tree / "install.sh", pinned, ctx.work)
    return f"dry run: candidate: {candidate} | published: {published}"


# ---------- publish ----------

MAC_UI_JOBS = ("mac-smoke", "mac-xcuitest")


def without_iphone(ctx: Ctx) -> bool:
    return "iphone" not in (ctx.state.fact("platforms") or "iphone,mac,linux").split(",")


def ui(ctx: Ctx) -> str:
    """The tag's own ui run (no push cancels a tag's). Red on a real bug: the fix is the next patch; the tag stays. A
    release without the iPhone app (--platforms mac,linux) gates on the Mac jobs only."""
    if without_iphone(ctx):
        return github.wait_jobs(ctx, ctx.state.fact("version_commit"), "ui", ctx.tag, MAC_UI_JOBS, "the tag's ui run, Mac jobs", 150)
    return github.wait_green(ctx, ctx.state.fact("version_commit"), ("ui",), ctx.tag, "the tag's ui run", 150)


def dry_ui(ctx: Ctx) -> str:
    last = ctx.state.fact("last_tag")
    sha = sh(["git", "rev-list", "-n", "1", last], cwd=ctx.tree).stdout.strip()
    state, run = github.commit_state(sha, ("ui",), last)["ui"]
    return f"skip: dry run: no tag to wait for. For reference, the newest tag {last}'s ui run: {state}" + (f" ({run['url']})" if run else "")


def promote(ctx: Ctx) -> str:
    """Latest only now: the disk image attached and checked, every check above green, the notes rewritten for a person."""
    rel = github.release(ctx.tag)
    if notes.DRAFT in (rel.get("body") or ""):
        raise Stop("the release notes are still the draft", f"Rewrite {ctx.state.fact('notes')} for a person who has never seen Pointe, "
                   f"then: gh release edit {ctx.tag} -R {REPO} --notes-file {ctx.state.fact('notes')}; tools/release resume", waiting=True)
    missing = {f"Pointe-{ctx.version}.dmg", "Pointe.dmg", f"pointe-{ctx.version}.tar.gz"} - github.asset_names(rel)
    if missing:
        raise Fail(f"not promoted: {ctx.tag} lacks {sorted(missing)}")
    if rel["isPrerelease"]:
        sh(["gh", "release", "edit", ctx.tag, "-R", REPO, "--prerelease=false", "--latest"])
    for _ in range(12):  # the CDN behind latest/download follows within a minute
        status, body = github.anonymous(github.LATEST_DMG)
        if status == 200 and github.sha256(body) == ctx.state.fact("dmg_sha"):
            return f"{ctx.tag} is Latest; {github.LATEST_DMG} answers 200 with this image's SHA-256"
        time.sleep(10)
    raise Fail(f"{ctx.tag} is Latest but {github.LATEST_DMG} answers {status} / another image: set the previous release Latest again")


def dry_promote(ctx: Ctx) -> str:
    status, body = github.anonymous(github.LATEST_DMG)
    if status != 200:
        raise Fail(f"today's {github.LATEST_DMG} answers {status}")
    draft = notes.DRAFT in Path(ctx.state.fact("notes")).read_text()
    return (f"dry run: today's Latest download answers 200 ({github.sha256(body)[:12]}…). A cut would promote after the tag's ui "
            f"run and the checks above" + ("; it would wait for the notes, still a draft" if draft else ""))


def _mac_size(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"  # decimal megabytes, as Finder and browsers show them (docs/releasing.md)


def apps_json(ctx: Ctx) -> str:
    fetch(ctx)
    current = json.loads(sh(["git", "show", "origin/main:site/pointe/apps.json"], cwd=ctx.tree).stdout)
    size = _mac_size(ctx.state.fact("dmg_bytes"))
    if current["mac"].get("version") == ctx.version and current["mac"].get("size") == size:
        return f"apps.json on main already says {ctx.version}, {size}"
    git(ctx, "checkout", "-q", "--detach", "origin/main")
    path = ctx.tree / "site" / "pointe" / "apps.json"
    data = json.loads(path.read_text())
    data["mac"].update(status="open", download_url=github.LATEST_DMG, version=ctx.version, size=size)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    sh(["python3", "tools/apps_status.py"], cwd=ctx.tree)
    git(ctx, "add", "site/pointe/apps.json", "site/pointe/index.html")
    git(ctx, "commit", "-q", "-s", "-m", f"The Mac download is {ctx.version}: Pointe-{ctx.version}.dmg, {size}")
    sha = push_to_main(ctx, git(ctx, "rev-parse", "HEAD"), "the Mac download")
    return f"apps.json: Mac {ctx.version}, {size} ({sha[:10]} on main)"


def dry_apps_json(ctx: Ctx) -> str:
    path = ctx.tree / "site" / "pointe" / "apps.json"
    data = json.loads(path.read_text())
    data["mac"].update(version=ctx.version, size="4.6 MB")
    page = ctx.tree / "site" / "pointe" / "index.html"
    before = (path.read_text(), page.read_text())
    try:
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        sh(["python3", "tools/apps_status.py"], cwd=ctx.tree)
        sh(["python3", "tools/apps_status.py", "--check"], cwd=ctx.tree)
        line = f"Pointe {ctx.version} · macOS 15+ · 4.6 MB"
        if line not in page.read_text():
            raise Fail(f"the hero line would not read {line!r}")
    finally:
        path.write_text(before[0])
        page.write_text(before[1])
    return f"dry run: apps.json and the hero would say {line!r}; restored"


GENERATED_SITE = ("site/pointe/docs/", "site/pointe/roadmap/", "site/pointe/apps.json", "site/pointe/bench")


def site_changes(ctx: Ctx, since: str) -> list[str]:
    """The site's files a person wrote that changed since the last release, beyond what the tools write (the docs pages,
    the roadmap, the app cards, the version spans). Those need the owner to see a preview first (docs/releasing.md)."""
    changed = [f for f in sh(["git", "diff", "--name-only", f"{since}..HEAD", "--", "site/"], cwd=ctx.tree).stdout.split() if f]
    hand = []
    strip = re.compile(r"<span data-version>[^<]*</span>|<span[^>]*data-beta[^>]*>[^<]*</span>|<!-- ([\w-]+):begin.*?<!-- \1:end -->", re.S)
    for f in changed:
        if f.startswith(GENERATED_SITE):
            continue
        old = sh(["git", "show", f"{since}:{f}"], cwd=ctx.tree, check=False).stdout
        new = (ctx.tree / f).read_text(errors="replace") if (ctx.tree / f).exists() else ""
        if strip.sub("", old) != strip.sub("", new):
            hand.append(f)
    return hand


def site(ctx: Ctx) -> str:
    fetch(ctx)
    git(ctx, "checkout", "-q", "--detach", "origin/main")
    hand = site_changes(ctx, ctx.state.fact("previous"))
    branch = f"rel-{ctx.version.replace('.', '-')}"
    need(creds.wrangler())
    if hand and not (getattr(ctx.args, "site_approved", False) or ctx.state.fact("site_approved")):
        if not ctx.state.fact("preview"):
            sh(["site/deploy.sh", branch], cwd=ctx.tree, timeout=900)
            ctx.state.set(preview=PREVIEW.format(branch=branch))
        raise Stop(f"{len(hand)} hand-written site file(s) changed since {ctx.state.fact('previous')}: " + ", ".join(hand[:6]),
                   f"The owner looks at {ctx.state.fact('preview')}, then: tools/release resume --site-approved", waiting=True)
    if getattr(ctx.args, "site_approved", False):
        ctx.state.set(site_approved=True)
    sh(["python3", "tools/roadmap.py"], cwd=ctx.tree, timeout=300)
    if git(ctx, "status", "--porcelain", "--", "ROADMAP.md", "site/pointe/roadmap"):
        git(ctx, "add", "ROADMAP.md", "site/pointe/roadmap")
        git(ctx, "commit", "-q", "-s", "-m", f"The roadmap's votes at {ctx.version}")
        push_to_main(ctx, git(ctx, "rev-parse", "HEAD"), "the roadmap")
    sh(["site/deploy.sh"], cwd=ctx.tree, timeout=900)
    seen = f"the owner's look at {ctx.state.fact('preview')}" if ctx.state.fact("preview") else "the owner's approval (--site-approved)"
    return "site deployed to production" + (f" ({len(hand)} hand-written page(s), after {seen})" if hand else " (only generated changes)")


def dry_site(ctx: Ctx) -> str:
    hand = site_changes(ctx, ctx.state.fact("previous"))
    probe = creds.wrangler()
    words = (f"{len(hand)} hand-written site file(s) changed since {ctx.state.fact('previous')} ({', '.join(hand[:5])}): a cut deploys a "
             "preview and waits for the owner's look" if hand else "only generated site changes: a cut deploys production")
    if not probe.ok:
        raise Stop(f"dry run: {words}; and {probe.detail}", probe.fix, waiting=True)
    return f"dry run: {words}; wrangler is signed in; nothing deployed"


def live_checks(version: str, tarball_sha: str | None, installer: Path, size: str | None) -> list[str]:
    """What the live site says: the hero line, install.sh (the repository's bytes, pinning `version`, which must be
    Latest), and the download. Returns the problems."""
    problems = []
    status, page = github.anonymous(LIVE)
    text = page.decode(errors="replace")
    want = f"Pointe {version} · macOS 15+ · {size}" if size else f"Pointe {version} · macOS 15+"
    if status != 200 or want not in text:
        found = re.search(r"Pointe [0-9.]+ · macOS 15\+ · [0-9.]+ MB", text)
        problems.append(f"the hero line reads {found.group(0) if found else 'nothing'!r}, not {want!r}")
    status, served = github.anonymous(LIVE + "install.sh")
    pinned = re.search(rb'^POINTE_VERSION="([^"]*)"', served, re.M)
    pinned_v = pinned.group(1).decode() if pinned else "nothing"
    if status != 200 or pinned_v != version:
        problems.append(f"/pointe/install.sh pins {pinned_v}, not {version}")
    if tarball_sha and tarball_sha.encode() not in served:
        problems.append("/pointe/install.sh does not carry the release's SHA-256")
    if served and served != installer.read_bytes():
        problems.append("/pointe/install.sh differs from install.sh on main")
    latest = (github.latest() or {}).get("tagName")
    if pinned_v != "nothing" and latest != f"v{pinned_v}":
        problems.append(f"the site's install.sh pins {pinned_v}, but the Latest release is {latest}: never pin a prerelease")
    status, _ = github.anonymous(github.LATEST_DMG)
    if status != 200:
        problems.append(f"{github.LATEST_DMG} answers {status}")
    return problems


def live(ctx: Ctx) -> str:
    fetch(ctx)
    git(ctx, "checkout", "-q", "--detach", "origin/main")
    size = _mac_size(ctx.state.fact("dmg_bytes"))
    for _ in range(12):
        problems = live_checks(ctx.version, ctx.state.fact("tarball_sha"), ctx.tree / "install.sh", size)
        if not problems:
            return f"live: hero 'Pointe {ctx.version} · macOS 15+ · {size}', /pointe/install.sh pins {ctx.version} (Latest), download 200"
        time.sleep(10)
    raise Fail("the live site is not right: " + "; ".join(problems))


def dry_live(ctx: Ctx) -> str:
    """The checks a cut runs after its deploy, against today's site and today's Latest."""
    latest = (github.latest() or {}).get("tagName", "v?")[1:]
    apps = json.loads((ctx.tree / "site" / "pointe" / "apps.json").read_text())
    main_installer = ctx.work / "main-install.sh"
    main_installer.write_text(sh(["git", "show", "origin/main:install.sh"], cwd=ctx.tree).stdout)
    problems = live_checks(latest, None, main_installer, apps["mac"].get("size"))
    if problems:
        raise Fail(f"dry run, today's live site against the Latest release v{latest}: " + "; ".join(problems))
    return f"dry run: the live site matches the Latest release v{latest}"


# ---------- distribution ----------

def testflight(ctx: Ctx) -> str:
    """Apple's processing of the upload, read with the keychain's API key: VALID, and the internal group testing it."""
    if without_iphone(ctx):
        return f"skip: the iPhone app is not in {ctx.version} (--platforms {ctx.state.fact('platforms')})"
    from . import asc

    if not asc.have_key():
        return f"{ctx.state.fact('ios_uploaded')}. The internal group gets it once Apple has processed it (not checked: no API key)"
    build = ctx.state.fact("ios_build")
    end = time.monotonic() + 60 * 60
    while True:
        got = asc.build(ctx.version, build)
        if got and got["processing"] == "VALID" and got["internal"] in ("IN_BETA_TESTING", "READY_FOR_BETA_TESTING"):
            return f"TestFlight {ctx.version} ({build}): processing VALID, internal {got['internal']}"
        if got and got["processing"] in ("FAILED", "INVALID"):
            raise Fail(f"App Store Connect could not process {ctx.version} ({build}): {got['processing']}")
        if getattr(ctx.args, "no_wait", False) or time.monotonic() > end:
            raise Stop(f"TestFlight {ctx.version} ({build}): {got or 'not listed yet'}", "tools/release resume (waits again)", waiting=True)
        ctx.say(f"    App Store Connect: {got or 'not listed yet'}")
        time.sleep(60)


def external(ctx: Ctx) -> str:
    if without_iphone(ctx):
        return f"skip: the iPhone app is not in {ctx.version} (--platforms {ctx.state.fact('platforms')})"
    from . import asc

    state = ""
    if asc.have_key():
        got = asc.build(ctx.version, ctx.state.fact("ios_build")) or {}
        state = f" (external state now: {got.get('external')})"
    raise Stop(f"TestFlight's external group and Beta App Review for {ctx.version} ({ctx.state.fact('ios_build')}){state}: the API key "
               "has the Developer role, which Apple refuses for these writes",
               "The owner, in App Store Connect: TestFlight, the build, add it to the group 'Beta testers', submit for Beta App Review",
               waiting=True)


def screenshots_age(tree: Path) -> str:
    """When the App Store screenshots were taken, and how many commits changed the iPhone's screens since."""
    shot = sh(["git", "log", "-1", "--format=%h %cs", "--", "docs/ios/screenshots"], cwd=tree).stdout.strip()
    if not shot:
        return "no App Store screenshots in docs/ios/screenshots"
    since = sh(["git", "rev-list", "--count", f"{shot.split()[0]}..HEAD", "--", *SCREENS], cwd=tree).stdout.strip()
    return f"taken at {shot}; {since} commit(s) changed the iPhone's screens since"


def app_store(ctx: Ctx) -> str:
    """The App Store needs the owner's yes each time: the What's New text (the changelog line, never "beta"), the build,
    and screenshots from the tag's ui run when the screens changed."""
    if without_iphone(ctx):
        return f"skip: the iPhone app is not in {ctx.version} (--platforms {ctx.state.fact('platforms')})"
    from . import asc

    whats_new = getattr(ctx.args, "summary", None) or "(the version's CHANGELOG line)"
    versions = ", ".join(f"{v['version']} {v['state']}" for v in asc.app_store_versions()) if asc.have_key() else "not read"
    raise Stop(f"App Store submission of {ctx.version} ({ctx.state.fact('ios_build')}): needs the owner's yes; the API key cannot "
               f"create the version (Developer role). App Store versions now: {versions}. Screenshots: "
               + screenshots_age(ctx.tree),
               f"The owner, in App Store Connect: App Store, + version {ctx.version}, What's New: \"{whats_new}\", choose build "
               f"{ctx.state.fact('ios_build')}, Add for Review. If the screens changed, take the six shots from the tag's ui run "
               f"(gh run download -R {REPO} -n ios-ui-screenshots) per docs/ios/app-store.md", waiting=True)


def iphone(ctx: Ctx) -> str:
    if without_iphone(ctx):
        return f"skip: the iPhone app is not in {ctx.version} (--platforms {ctx.state.fact('platforms')})"
    probe = creds.iphone()
    if not probe.ok:  # not a blocker: TestFlight's internal group puts the build on the owner's iPhone
        return f"skip: {probe.detail}; TestFlight's internal group reaches the owner's iPhone"
    git(ctx, "checkout", "-q", "--detach", ctx.state.fact("pin_commit"))
    device = ["--device", creds.IPHONE] if creds.IPHONE else []
    out = sh(["bin/pointe", "apps", "ios", "--team", creds.TEAM, "--no-launch", *device], cwd=ctx.tree, check=False, timeout=3600, stream=True)
    if out.returncode != 0:
        return f"skip: the direct install failed ({preflight_tail(out.stdout)}); TestFlight's internal group reaches the owner's iPhone"
    return f"Pointe {ctx.version} built from the release commit and installed on the owner's iPhone (not opened)"


def dry_iphone(ctx: Ctx) -> str:
    probe = creds.iphone()
    out = sh(["bin/pointe", "apps", "ios", "--dry-run", "--team", creds.TEAM, "--no-launch"], cwd=ctx.tree, check=False, timeout=300)
    plan = "the install plan runs" if out.returncode == 0 else f"the install plan stops: {preflight_tail(out.stdout + out.stderr)}"
    if not probe.ok:
        raise Stop(f"dry run: {probe.detail}; {plan}", probe.fix, waiting=True)
    return f"dry run: {probe.detail}; {plan}; nothing installed"


def dry_dist(ctx: Ctx) -> str:
    asc = creds.asc_api_key()
    raise Stop(f"dry run: TestFlight external and the App Store are the owner's ({asc.detail}). App Store screenshots: "
               + screenshots_age(ctx.tree), asc.fix, waiting=True)


STEPS: list[Step] = [
    Step("preflight.tree", "the release worktree at the newest main", tree, tree, dry_needs=()),
    Step("preflight.ci", "main green on test, apps and ui", ci_main, needs=("preflight.tree",)),
    Step("preflight.wip", "nothing half-done", wip, needs=("preflight.tree",)),
    Step("preflight.generated", "parity matrix (no gap, four surfaces), product help, docs, site version, app cards current", generated, needs=("preflight.tree",)),
    Step("preflight.skew", "the versions agree", skew, needs=("preflight.tree",)),
    Step("preflight.join", "the integration join: hub, page, phone client, node", join, needs=("preflight.tree",)),
    Step("preflight.suite", "the full suite with --runslow on this Mac", suite, needs=("preflight.tree",)),
    Step("preflight.notes", "the changelog since the last release, grouped, and the notes draft", draft_notes, needs=("preflight.tree",)),
    Step("version.commit", "the version, in lockstep, and the CHANGELOG", version_commit,
         needs=("preflight.ci", "preflight.wip", "preflight.generated", "preflight.skew", "preflight.join", "preflight.suite", "preflight.notes")),
    Step("version.push", "the version commit on main", push_version, dry_push_version, needs=("version.commit",), dry_needs=("version.commit",)),
    Step("version.ci", "test and apps green on the version commit", version_ci, lambda c: "skip: dry run: nothing pushed", needs=("version.push",)),
    Step("tag", "the annotated tag", tag, dry_tag, needs=("version.ci",)),
    Step("tag.ci", "test and apps green on the tag", tag_ci, lambda c: "skip: dry run: no tag", needs=("tag",)),
    Step("artifacts.tarball", "the tarball, on a prerelease", tarball, dry_tarball, needs=("tag.ci",), dry_needs=("version.commit",)),
    Step("artifacts.pin", "install.sh pinned (build commit and main)", pin, dry_pin, needs=("artifacts.tarball",), dry_needs=("artifacts.tarball",)),
    Step("artifacts.dmg", "the Mac disk image: signed, notarized, stapled, attached", dmg, dry_dmg, needs=("artifacts.pin",)),
    Step("artifacts.ios", "the iPhone build to App Store Connect", ios, dry_ios, needs=("artifacts.pin",)),
    Step("verify.assets", "anonymous downloads and SHA-256s", assets, dry_assets, needs=("artifacts.dmg",)),
    Step("verify.dmg", "spctl and stapler, a quarantined mount", dmg_check, dry_dmg_check, needs=("verify.assets",), dry_needs=("verify.assets",)),
    Step("verify.mac-install", "a clean standalone install from github.com on this Mac", mac_install, dry_mac_install, needs=("artifacts.pin",)),
    Step("verify.linux", "Linux hub (smoke) and node, installed in an empty Ubuntu container", linux, dry_linux, needs=("artifacts.pin",),
         dry_needs=("artifacts.tarball",)),
    Step("publish.ui", "the tag's ui run green", ui, dry_ui, needs=("tag",)),
    Step("publish.promote", "prerelease to Latest, then the anonymous download", promote, dry_promote,
         needs=("verify.assets", "verify.dmg", "verify.mac-install", "verify.linux", "publish.ui"), dry_needs=("preflight.notes",)),
    Step("publish.apps-json", "the Mac download on the site's cards", apps_json, dry_apps_json, needs=("publish.promote",)),
    Step("publish.site", "the site deploy (a preview for the owner first when hand-written pages changed)", site, dry_site, needs=("publish.apps-json",)),
    Step("publish.live", "the live page: hero line, install.sh pin, download", live, dry_live, needs=("publish.site",)),
    Step("dist.testflight", "TestFlight internal", testflight, dry_dist, needs=("artifacts.ios",)),
    Step("dist.external", "TestFlight external and Beta App Review", external, lambda c: "skip: dry run: see dist.testflight", needs=("dist.testflight",)),
    Step("dist.app-store", "the App Store submission", app_store, lambda c: "skip: dry run: see dist.testflight", needs=("artifacts.ios",)),
    Step("dist.iphone", "the release on the owner's iPhone, if it is reachable", iphone, dry_iphone, needs=("tag",)),
]
