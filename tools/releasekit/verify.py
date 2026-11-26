"""What a stranger gets: the disk image Gatekeeper accepts, a clean standalone install from github.com on a Mac, and a
Linux hub and node installed in an empty Ubuntu container (a Colima VM of its own, so no other container is touched)."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from .core import Fail, Stop, sh

# Ubuntu 24.04, by digest: every download carries a pin (CLAUDE.md, supply chain). Move it on purpose, with the date.
UBUNTU = "ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b"  # 2026-11-26
COLIMA_PROFILE = "pointe-release"
HUB_PORT = 7871


def dmg(image: Path, version: str, work: Path) -> str:
    """spctl and stapler on the image and on the app in it, from a quarantined copy mounted as a download would be."""
    out = sh(["spctl", "-a", "-vvv", "-t", "install", str(image)], check=False)
    said = out.stdout + out.stderr
    if out.returncode != 0 or "accepted" not in said or "Notarized Developer ID" not in said:
        raise Fail(f"Gatekeeper does not accept {image.name}: {said.strip()[-300:]}")
    sh(["xcrun", "stapler", "validate", str(image)])
    copy = work / f"quarantined-{image.name}"
    shutil.copyfile(image, copy)
    sh(["xattr", "-w", "com.apple.quarantine", f"0083;{int(time.time()):x};Safari;", str(copy)])
    mount = Path(tempfile.mkdtemp(prefix="pointe-dmg-"))
    sh(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mount), str(copy)])
    try:
        app = mount / "Pointe.app"
        if not app.is_dir():
            raise Fail(f"{image.name} holds no Pointe.app")
        out = sh(["spctl", "-a", "-vvv", "-t", "exec", str(app)], check=False)
        said = out.stdout + out.stderr
        if out.returncode != 0 or "Notarized Developer ID" not in said:
            raise Fail(f"Gatekeeper does not accept the app in {image.name}: {said.strip()[-300:]}")
        sh(["xcrun", "stapler", "validate", str(app)])
        shown = sh(["defaults", "read", str(app / "Contents" / "Info.plist"), "CFBundleShortVersionString"]).stdout.strip()
        if shown != version:
            raise Fail(f"the app in {image.name} is {shown}, not {version}")
    finally:
        sh(["hdiutil", "detach", str(mount)], check=False)
        copy.unlink(missing_ok=True)
    return f"{image.name}: image and app accepted (Notarized Developer ID), both stapled, a quarantined copy mounts, the app is {version}"


def mac_install(installer: Path, version: str, work: Path) -> str:
    """install.sh as a stranger runs it: an empty environment, a new HOME, the system PATH, a `security` that finds
    nothing (no Keychain item is read), from github.com. Then version, update, uninstall. Nothing is started."""
    home = Path(tempfile.mkdtemp(prefix="pointe-clean-"))
    fake = home / "fakebin"
    fake.mkdir()
    (fake / "security").write_text("#!/bin/sh\necho 'security: The specified item could not be found in the keychain.' >&2\nexit 44\n")
    (fake / "security").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(home), "LANG": "en_US.UTF-8"}
    try:
        started = time.monotonic()
        out = sh(["bash", str(installer), "--yes"], env=env, check=False, timeout=1800)
        took = time.monotonic() - started
        (work / "mac-install.log").write_text(out.stdout + out.stderr)
        if out.returncode != 0 or "SHA-256 matches" not in out.stdout:
            raise Fail(f"install.sh --yes in a clean HOME failed (exit {out.returncode}): {(out.stdout + out.stderr).strip()[-400:]}")
        pointe = home / ".local" / "bin" / "pointe"
        shown = sh([str(pointe), "version"], env=env, check=False).stdout.strip()
        if f"Pointe {version}" not in shown:
            raise Fail(f"the clean install says {shown!r}, not Pointe {version}")
        update = sh([str(pointe), "update", "--yes"], env=env, check=False, timeout=600)
        gone = sh([str(pointe), "uninstall", "--yes"], env=env, check=False, timeout=300)
        if gone.returncode != 0 or (home / ".pointe").exists():
            raise Fail(f"pointe uninstall --yes left ~/.pointe: {gone.stdout.strip()[-200:]}")
        return (f"clean HOME, empty env, from github.com: installed {version} in {took:.0f} s (SHA-256 matched); "
                f"`pointe update`: {update.stdout.strip().splitlines()[-1][:90] if update.stdout.strip() else update.returncode}; uninstalled")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _docker_env() -> dict:
    return {**os.environ, "DOCKER_HOST": f"unix://{Path.home()}/.colima/{COLIMA_PROFILE}/docker.sock"}


def colima_up() -> dict:
    """The release's own Colima VM (profile pointe-release), started if it is not running. The default profile and its
    containers are never touched."""
    if not shutil.which("colima") or not shutil.which("docker"):
        raise Stop("colima and docker are not installed", "brew install colima docker, then tools/release resume")
    env = _docker_env()
    if sh(["docker", "info"], env=env, check=False, timeout=30).returncode != 0:
        out = sh(["colima", "start", "--profile", COLIMA_PROFILE, "--cpu", "4", "--memory", "6", "--disk", "30"], check=False, timeout=900)
        if out.returncode != 0:
            raise Stop(f"the Colima VM {COLIMA_PROFILE} did not start: {out.stderr.strip()[-200:]}", "colima start --profile pointe-release, then tools/release resume")
    return env


LINUX_SCRIPT = r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends curl ca-certificates tar gzip procps python3 iproute2 >/dev/null
useradd -m tester
cp /in/install.sh /home/tester/install.sh && chown tester /home/tester/install.sh
su - tester -c "bash ~/install.sh --$ROLE --yes $EXTRA" 2>&1 | tail -6
su - tester -c "~/.local/bin/pointe version"
if [ "$ROLE" = hub ]; then
  su - tester -c "GOOGLE_API_KEY=synthetic-release-check-not-a-key CLAUDE_VOICE_SKIP_KEY_CHECK=1 CLAUDE_VOICE_DAEMON_PORT=$PORT ~/.pointe/$VERSION/bin/voice-daemon ensure"
  su - tester -c "CLAUDE_VOICE_DAEMON_PORT=$PORT ~/.local/bin/pointe status" | grep -q '^running'
  test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/voice/health)" = 200
  T="$(cat /home/tester/.claude-voice/token)"; K="$(cat /home/tester/.claude-voice/page_key)"
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $T" http://127.0.0.1:$PORT/voice/status)" = 200
  test "$(curl -sL -b '' -o /dev/null -w '%{http_code}' "http://localhost:$PORT/voice?key=$K")" = 200
  curl -s -H "Authorization: Bearer $T" http://127.0.0.1:$PORT/voice/status | python3 -c 'import json,sys; v=json.load(sys.stdin)["version"]; assert v == sys.argv[1], v; print("hub status version", v)' "$VERSION"
  su - tester -c "CLAUDE_VOICE_DAEMON_PORT=$PORT ~/.pointe/$VERSION/bin/voice-daemon stop"
  echo "HUB-SMOKE-OK"
else
  su - tester -c "~/.local/bin/pointe node status" 2>&1 | tail -3 || true
  test -x /home/tester/.pointe/$VERSION/bin/voice-node
  echo "NODE-INSTALL-OK"
fi
su - tester -c "~/.local/bin/pointe uninstall --yes" | tail -1
"""


def linux(installer: Path, version: str, work: Path, tarball: Path | None = None) -> str:
    """A Linux hub (installed, started on a synthetic key it never sends, health/status/page answer, its status names the
    version) and a node (installed without the voice packages), each in an empty Ubuntu container. With `tarball`, that
    file is installed through --url and its SHA-256 (a candidate not yet published); without, the pinned release from
    github.com."""
    env = colima_up()
    # Under HOME: Colima shares only the home folder with its VM, so a folder in /var/folders mounts empty.
    shared = work / "linux-in"
    shutil.rmtree(shared, ignore_errors=True)
    shared.mkdir(parents=True)
    shutil.copyfile(installer, shared / "install.sh")
    extra = ""
    if tarball:
        shutil.copyfile(tarball, shared / tarball.name)
        digest = (tarball.with_name(tarball.name + ".sha256")).read_text().split()[0]
        extra = f"--version {version} --url file:///in/{tarball.name} --sha256 {digest}"
    results = []
    try:
        for role in ("hub", "node"):
            out = sh(["docker", "run", "--rm", "-v", f"{shared}:/in:ro", "-e", f"ROLE={role}", "-e", f"VERSION={version}",
                      "-e", f"PORT={HUB_PORT}", "-e", f"EXTRA={extra}", UBUNTU, "bash", "-c", LINUX_SCRIPT],
                     env=env, check=False, timeout=2400)
            (work / f"linux-{role}.log").write_text(out.stdout + out.stderr)
            mark = "HUB-SMOKE-OK" if role == "hub" else "NODE-INSTALL-OK"
            if out.returncode != 0 or mark not in out.stdout or f"Pointe {version}" not in out.stdout:
                raise Fail(f"Linux {role} ({'candidate tarball' if tarball else 'github.com'}) failed: {(out.stdout + out.stderr).strip()[-500:]}")
            results.append(role)
    finally:
        shutil.rmtree(shared, ignore_errors=True)
    source = "the candidate tarball by its SHA-256" if tarball else "github.com, by the pinned SHA-256"
    return f"Ubuntu 24.04 container, from {source}: hub installed {version}, started, health/status/page 200, status says {version}; node installed"
