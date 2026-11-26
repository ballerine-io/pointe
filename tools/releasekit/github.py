"""GitHub, through `gh` (signed in) and anonymous HTTPS (what a stranger sees): CI runs, releases, assets, downloads."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .core import REPO, Fail, Stop, sh

SITE = "https://github.com/ballerine-io/pointe"
LATEST_DMG = f"{SITE}/releases/latest/download/Pointe.dmg"
WORKFLOWS = ("test", "apps", "ui")


def gh_json(args: list[str]):
    out = sh(["gh", *args, "-R", REPO], check=False, timeout=120)
    if out.returncode != 0:
        if "not found" in (out.stdout + out.stderr).lower() or "release not found" in out.stderr.lower():
            return None
        raise Stop(f"gh failed: {(out.stderr or out.stdout).strip()[:300]}",
                   "Is gh signed in (`gh auth status`) and github.com reachable? Then: tools/release resume")
    return json.loads(out.stdout or "null")


RUN_FIELDS = "workflowName,status,conclusion,headSha,headBranch,event,createdAt,databaseId,url"


def runs(*, commit: str | None = None, branch: str | None = None, limit: int = 60) -> list[dict]:
    args = ["run", "list", "--limit", str(limit), "--json", RUN_FIELDS]
    if commit:
        args += ["--commit", commit]
    if branch:
        args += ["--branch", branch]
    return gh_json(args) or []


def verdict(found: list[dict], workflow: str, *, sha: str | None = None, ref: str | None = None,
            skip_cancelled: bool = False, finished: bool = False) -> tuple[str, dict | None]:
    """The state of one workflow: success, failure, pending or missing. Newest run first; on main a `ui` run cancelled by a
    newer push says nothing about the code, so `skip_cancelled` looks past it (docs/releasing.md, step 2). Only push runs
    count: a dispatch may run a subset."""
    mine = [r for r in found if r["workflowName"] == workflow and r["event"] == "push"
            and (sha is None or r["headSha"] == sha) and (ref is None or r["headBranch"] == ref)]
    mine.sort(key=lambda r: r["createdAt"], reverse=True)
    for r in mine:
        if r["status"] != "completed":
            if finished:  # main's apps and ui: the newest finished run speaks, a newer one still running does not yet
                continue
            return "pending", r
        if r["conclusion"] in ("cancelled", "skipped") and skip_cancelled:
            continue
        return ("success" if r["conclusion"] == "success" else "failure"), r
    return "missing", None


def main_state() -> dict[str, tuple[str, dict | None]]:
    """main's CI as the release gate reads it: `test` on main's newest commit exactly (it runs on every push), `apps` and
    `ui` by their newest finished run on main (they are path-filtered, and `ui` is cancelled by newer pushes)."""
    head = sh(["git", "ls-remote", f"{SITE}.git", "refs/heads/main"]).stdout.split()[0]
    found = runs(branch="main", limit=100)
    return {"head": (head, None), "test": verdict(found, "test", sha=head),
            "apps": verdict(found, "apps", skip_cancelled=True, finished=True), "ui": verdict(found, "ui", skip_cancelled=True, finished=True)}


def commit_state(sha: str, workflows: tuple[str, ...], ref: str | None = None) -> dict[str, tuple[str, dict | None]]:
    found = runs(commit=sha, limit=60)
    return {w: verdict(found, w, sha=sha, ref=ref) for w in workflows}


def wait_green(ctx, sha: str, workflows: tuple[str, ...], ref: str | None, what: str, minutes: float) -> str:
    """Wait until each workflow's run on `sha` (on `ref`) is green. Red: Fail. Still running at the limit: Stop (waiting),
    and resume waits again. --no-wait stops at once."""
    end = time.monotonic() + minutes * 60
    while True:
        got = commit_state(sha, workflows, ref)
        red = {w: r for w, (s, r) in got.items() if s == "failure"}
        if red:
            raise Fail(f"{what}: " + ", ".join(f"{w} failed ({r['url']})" for w, r in red.items())
                       + ". A real bug is fixed in a new commit and a new patch version; a pushed tag is never moved.")
        left = [w for w, (s, _) in got.items() if s != "success"]
        if not left:
            return f"{what}: " + ", ".join(f"{w} green" for w in workflows)
        if getattr(ctx.args, "no_wait", False) or time.monotonic() > end:
            raise Stop(f"{what}: still running or not started: " + ", ".join(f"{w} ({got[w][0]})" for w in left),
                       "tools/release resume (it waits again)", waiting=True)
        ctx.say(f"    waiting for {', '.join(left)} on {sha[:10]} ({what})")
        time.sleep(60)


def jobs(run_id: int) -> dict[str, str]:
    """Each job of a run and its state: its conclusion, or its status while it runs."""
    got = gh_json(["run", "view", str(run_id), "--json", "jobs"]) or {}
    return {j["name"]: (j.get("conclusion") or j.get("status") or "") for j in got.get("jobs", [])}


def wait_jobs(ctx, sha: str, workflow: str, ref: str, names: tuple[str, ...], what: str, minutes: float) -> str:
    """Like wait_green, for some jobs of one workflow's run: the others may fail (a platform left out of the release)."""
    end = time.monotonic() + minutes * 60
    while True:
        state, run = commit_state(sha, (workflow,), ref)[workflow]
        got = jobs(run["databaseId"]) if run else {}
        red = {n: got[n] for n in names if got.get(n) in ("failure", "cancelled", "timed_out")}
        if red:
            raise Fail(f"{what}: " + ", ".join(f"{n} {s}" for n, s in red.items()) + f" ({run['url']})")
        if all(got.get(n) == "success" for n in names):
            others = {n: s for n, s in got.items() if n not in names}
            return f"{what}: " + ", ".join(f"{n} green" for n in names) + (f" (not gating: {others})" if others else "")
        if getattr(ctx.args, "no_wait", False) or time.monotonic() > end:
            raise Stop(f"{what}: " + ", ".join(f"{n} {got.get(n, 'not started')}" for n in names), "tools/release resume (it waits again)", waiting=True)
        ctx.say(f"    waiting for {', '.join(n for n in names if got.get(n) != 'success')} ({what})")
        time.sleep(60)


def release(tag: str) -> dict | None:
    return gh_json(["release", "view", tag, "--json", "tagName,isPrerelease,isDraft,assets,url,publishedAt,body,targetCommitish"])


def releases(limit: int = 30) -> list[dict]:
    return gh_json(["release", "list", "--limit", str(limit), "--json", "tagName,isLatest,isPrerelease,isDraft,publishedAt"]) or []


def latest() -> dict | None:
    return next((r for r in releases() if r.get("isLatest")), None)


def asset_names(rel: dict | None) -> set[str]:
    return {a["name"] for a in (rel or {}).get("assets", [])}


def remote_tag(tag: str) -> str | None:
    """The commit a tag on github.com points to (peeled), or None."""
    out = sh(["git", "ls-remote", f"{SITE}.git", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], check=False).stdout.split("\n")
    pairs = dict(reversed(line.split("\t")) for line in out if "\t" in line)
    return pairs.get(f"refs/tags/{tag}^{{}}") or pairs.get(f"refs/tags/{tag}")


def anonymous(url: str, dest: Path | None = None, timeout: float = 120) -> tuple[int, bytes]:
    """GET as a stranger: no token, redirects followed. Returns (final status, body)."""
    request = urllib.request.Request(url, headers={"User-Agent": "pointe-release-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read()
            status = reply.status
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError) as e:
        raise Stop(f"could not reach {url}: {e}", "Check the network, then tools/release resume", waiting=True) from e
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    return status, body


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_checked(tag: str, name: str, folder: Path) -> tuple[Path, str]:
    """Download an asset and its .sha256 anonymously; the file's SHA-256 must be the published one. Returns (path, sha)."""
    base = f"{SITE}/releases/download/{tag}"
    status, body = anonymous(f"{base}/{name}", folder / name)
    if status != 200:
        raise Fail(f"{base}/{name} answers {status} to an anonymous download")
    status, published = anonymous(f"{base}/{name}.sha256")
    if status != 200:
        raise Fail(f"{base}/{name}.sha256 answers {status}")
    want = published.decode().split()[0] if published.strip() else ""
    got = sha256(body)
    if got != want:
        raise Fail(f"{name}: downloaded SHA-256 {got} is not the published {want}")
    return folder / name, got
