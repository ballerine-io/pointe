"""The release workflow (.github/workflows/release.yml): the disk image and the iPhone build signed in GitHub Actions,
with the secrets of the environment "release", so a release needs nothing from the owner's Mac but `gh`.

tools/release dispatches it once per version on the tag, with the SHA-256 of the install.sh it pinned (the runner pins
the tag the same way and refuses a different result), and waits for each job. The workflow's token is read-only: the
disk image comes back as an artifact, which tools/release checks before it attaches it. A missing secret, or
--local-signing, sends the step to this Mac's keychain instead (the local path, docs/releasing.md).
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from . import github
from .core import REPO, Fail, Stop, sh

WORKFLOW = "release.yml"
ENVIRONMENT = "release"
TAG_RULE = "v*"
SECRETS = {
    "mac": ("MAC_DEVELOPER_ID_P12", "MAC_DEVELOPER_ID_P12_PASSWORD", "ASC_API_KEY_P8", "ASC_API_KEY_ID", "ASC_API_ISSUER_ID"),
    "iphone": ("IOS_DISTRIBUTION_P12", "IOS_DISTRIBUTION_P12_PASSWORD", "IOS_APP_PROFILE", "IOS_WIDGET_PROFILE",
               "ASC_API_KEY_P8", "ASC_API_KEY_ID", "ASC_API_ISSUER_ID"),
}
JOBS = {"mac": "mac", "iphone": "iphone"}


def _api(path: str):
    out = sh(["gh", "api", path], check=False, timeout=60)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout or "null")


def secret_names() -> set[str]:
    """The names of the environment's secrets (GitHub never returns a value)."""
    got = _api(f"repos/{REPO}/environments/{ENVIRONMENT}/secrets?per_page=100") or {}
    return {s["name"] for s in got.get("secrets", [])}


def protected() -> bool:
    """The environment admits only tags matching v*: no branch, pull request or fork reaches its secrets."""
    env = _api(f"repos/{REPO}/environments/{ENVIRONMENT}") or {}
    policy = env.get("deployment_branch_policy") or {}
    if not policy.get("custom_branch_policies"):
        return False
    rules = (_api(f"repos/{REPO}/environments/{ENVIRONMENT}/deployment-branch-policies") or {}).get("branch_policies", [])
    return [(r.get("name"), r.get("type")) for r in rules] == [(TAG_RULE, "tag")]


def missing(platform: str, names: set[str] | None = None) -> list[str]:
    have = secret_names() if names is None else names
    return [n for n in SECRETS[platform] if n not in have]


def use(ctx, platform: str) -> bool:
    """Whether this step signs in CI: every secret it needs is there, the environment is protected, and the person did
    not ask for the local path (--local-signing). The answer is kept, so a resume does not switch paths halfway."""
    key = f"ci_{platform}"
    if ctx.state.fact(key) is None:
        ok = not getattr(ctx.args, "local_signing", False) and not missing(platform) and protected()
        ctx.state.set(**{key: ok})
    return bool(ctx.state.fact(key))


def platforms(ctx) -> list[str]:
    from .steps import without_iphone

    return [p for p in ("mac", "iphone") if p == "mac" or not without_iphone(ctx)]


def install_sha(ctx) -> str:
    text = sh(["git", "show", f"{ctx.state.fact('pin_commit')}:install.sh"], cwd=ctx.tree).stdout
    return github.sha256(text.encode())


def dispatch(ctx, upload: bool) -> int:
    """Start the workflow on the tag and return its run's id. GitHub does not return it, so the newest dispatch on the
    tag created after this call is taken."""
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5)
    wanted = [p for p in platforms(ctx) if use(ctx, p)]
    sh(["gh", "workflow", "run", WORKFLOW, "-R", REPO, "--ref", ctx.tag, "-f", f"install_sha256={install_sha(ctx)}",
        "-f", f"platforms={','.join(wanted)}", "-f", f"upload={'true' if upload else 'false'}"])
    for _ in range(24):
        time.sleep(5)
        found = github.gh_json(["run", "list", "--workflow", WORKFLOW, "--event", "workflow_dispatch", "--branch", ctx.tag,
                                "--limit", "5", "--json", "databaseId,createdAt,url"]) or []
        fresh = [r for r in found if datetime.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= since]
        if fresh:
            run = max(fresh, key=lambda r: r["createdAt"])
            ctx.state.set(ci_run=run["databaseId"], ci_run_url=run["url"], ci_platforms=",".join(wanted), ci_upload=upload)
            ctx.say(f"    dispatched {WORKFLOW} on {ctx.tag}: {run['url']}")
            return run["databaseId"]
    raise Stop(f"{WORKFLOW} was dispatched on {ctx.tag} but its run did not show up", "tools/release resume", waiting=True)


def run_id(ctx, upload: bool) -> int:
    return ctx.state.fact("ci_run") or dispatch(ctx, upload)


def wait_job(ctx, platform: str, upload: bool, minutes: float = 100) -> str:
    """Wait for one job of the run: green returns its URL; red is re-run once (notarization and runners flake), then
    Fail; still running at the limit, Stop (resume waits again)."""
    run = run_id(ctx, upload)
    name = JOBS[platform]
    end = time.monotonic() + minutes * 60
    while True:
        got = github.gh_json(["run", "view", str(run), "--json", "status,conclusion,url,jobs"]) or {}
        job = next((j for j in got.get("jobs", []) if j["name"] == name), None)
        state = (job or {}).get("conclusion") or (job or {}).get("status") or "not started"
        url = (job or {}).get("url") or got.get("url", "")
        if state == "success":
            return url
        if state in ("failure", "cancelled", "timed_out", "skipped") and got.get("status") == "completed":
            reran = ctx.state.fact("ci_reran") or []
            if state != "skipped" and run not in reran:
                sh(["gh", "run", "rerun", str(run), "-R", REPO, "--failed"], check=False)
                ctx.state.set(ci_reran=reran + [run])
                ctx.say(f"    the {name} job {state} ({url}): its failed jobs re-run once")
                time.sleep(30)
                continue
            raise Fail(f"the {name} job of {WORKFLOW} {state} ({url})")
        if getattr(ctx.args, "no_wait", False) or time.monotonic() > end:
            raise Stop(f"the {name} job of {WORKFLOW} is {state} ({url})", "tools/release resume (it waits again)", waiting=True)
        ctx.say(f"    {WORKFLOW} {name}: {state}")
        time.sleep(60)


def download_dmg(ctx, folder: Path) -> Path:
    """The pointe-dmg artifact of the run, its SHA-256 checked against the .sha256 the job wrote."""
    if folder.exists():
        for f in folder.iterdir():
            f.unlink()
    sh(["gh", "run", "download", str(ctx.state.fact("ci_run")), "-R", REPO, "-n", "pointe-dmg", "-D", str(folder)], timeout=900)
    image = folder / f"Pointe-{ctx.version}.dmg"
    listed = folder / f"Pointe-{ctx.version}.dmg.sha256"
    if not image.exists() or not listed.exists():
        raise Fail(f"the pointe-dmg artifact holds {sorted(p.name for p in folder.iterdir())}, not Pointe-{ctx.version}.dmg and its .sha256")
    digest = github.sha256(image.read_bytes())
    if listed.read_text().split()[0] != digest:
        raise Fail(f"the artifact's Pointe-{ctx.version}.dmg is {digest}, its .sha256 says otherwise")
    return image
