"""The one summary at the end of a run: each platform's state, links, SHA-256s, and what waits for whom."""

from __future__ import annotations

from .core import REPO, Ctx

PLATFORMS = [
    ("Gate", ("preflight.tree", "preflight.ci", "preflight.wip", "preflight.generated", "preflight.skew", "preflight.join", "preflight.suite",
              "preflight.notes", "version.commit", "version.push", "version.ci", "tag", "tag.ci", "publish.ui")),
    ("Mac (disk image)", ("artifacts.dmg", "verify.assets", "verify.dmg", "publish.promote", "publish.apps-json")),
    ("Standalone install (Mac, Codex, OpenCode)", ("artifacts.tarball", "artifacts.pin", "verify.mac-install")),
    ("Linux (hub and node)", ("verify.linux",)),
    ("Site", ("publish.site", "publish.live")),
    ("iPhone", ("artifacts.ios", "dist.testflight", "dist.external", "dist.app-store", "dist.iphone")),
]
MARK = {"done": "ok", "skipped": "skip", "waiting": "WAIT", "stopped": "STOP", "failed": "FAIL", "blocked": "held", "": "-"}


def render(ctx: Ctx) -> str:
    o = ctx.outcomes
    title = f"Pointe {ctx.version}: release {'dry run' if ctx.dry_run else 'report'}"
    lines = [f"# {title}", ""]
    rel = f"https://github.com/{REPO}/releases/tag/{ctx.tag}"
    if not ctx.dry_run:
        lines += [f"Release: {rel}", ""]
    for platform, names in PLATFORMS:
        lines += [f"## {platform}", ""]
        for n in names:
            out = o.get(n)
            status = out.status if out else ctx.state.status(n)
            detail = out.detail if out else ctx.state.step(n).get("detail", "")
            lines.append(f"- {MARK.get(status, status)} `{n}`: {detail}")
        lines.append("")
    sums = ctx.state.fact("sha256s") or {}
    if sums:
        lines += ["## SHA-256", ""] + [f"- `{name}` {digest}" for name, digest in sums.items()] + [""]
    waiting = [(n, x) for n, x in o.items() if x.status in ("waiting", "stopped")]
    failed = [(n, x) for n, x in o.items() if x.status == "failed"]
    if failed:
        lines += ["## Failed (a defect: fix on main; a published tag or asset is never replaced)", ""]
        lines += [f"- `{n}`: {x.detail}" for n, x in failed] + [""]
    if waiting:
        lines += ["## Waiting", ""]
        lines += [f"- `{n}`: {x.detail}\n  - next: {x.how}" for n, x in waiting] + [""]
    if not ctx.dry_run and (waiting or failed or any(x.status == "blocked" for x in o.values())):
        lines += ["Then: `tools/release resume`", ""]
    return "\n".join(lines)
