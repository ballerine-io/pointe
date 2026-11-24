"""The release tarball that install.sh and `pointe update` install, and the pin in install.sh (docs/releasing.md, step 4).

    python3 tools/release_tarball.py build vX.Y.Z      dist/pointe-X.Y.Z.tar.gz and its .sha256, from the tag
    python3 tools/release_tarball.py pin vX.Y.Z        install.sh installs that release: its version and SHA-256,
                                                       read from the asset on the GitHub Release (gh), checked
                                                       against dist/ when it is there

The archive is `git archive` of the tag, with the folders a person never runs left out (.gitattributes, export-ignore):
GitHub's own "Source code" archives are not promised to keep their bytes, so the SHA-256 is of an asset we attach.
`worktree()` builds the same kind of archive from the working tree, for tests (tests/test_install.py).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
REPO = "ballerine-io/pointe"


def name(version: str) -> str:
    return f"pointe-{version}.tar.gz"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sum(archive: Path) -> Path:
    out = archive.with_name(archive.name + ".sha256")
    out.write_text(f"{sha256(archive)}  {archive.name}\n")  # the format of `shasum -a 256`; install.sh reads field 1
    return out


def build(tag: str, out: Path) -> Path:
    version = tag.removeprefix("v")
    manifest = json.loads(subprocess.run(["git", "-C", str(ROOT), "show", f"{tag}:.claude-plugin/plugin.json"],
                                         check=True, capture_output=True, text=True).stdout)
    if manifest["version"] != version:
        raise SystemExit(f"{tag} holds version {manifest['version']}, not {version}")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / name(version)
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", f"--prefix=pointe-{version}/", "-o", str(archive),
                    tag], check=True)
    write_sum(archive)
    return archive


def worktree(out: Path, version: str) -> Path:
    """The working tree as a release of `version` would hold it (tracked and new files, less export-ignore), with that
    version in its manifest: a test release, never published."""
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            check=True, capture_output=True).stdout.decode().split("\0")
    paths = [p for p in listed if p and (ROOT / p).is_file()]
    attrs = subprocess.run(["git", "-C", str(ROOT), "check-attr", "-z", "--stdin", "export-ignore"], input="\0".join(paths).encode(),
                           check=True, capture_output=True).stdout.decode().split("\0")
    ignored = {attrs[i] for i in range(0, len(attrs) - 2, 3) if attrs[i + 2] == "set"}
    out.mkdir(parents=True, exist_ok=True)
    archive = out / name(version)
    with tarfile.open(archive, "w:gz") as tar:
        for path in paths:
            if path in ignored:
                continue
            info = tar.gettarinfo(str(ROOT / path), f"pointe-{version}/{path}")
            if path == ".claude-plugin/plugin.json":
                data = re.sub(r'"version": *"[^"]*"', f'"version": "{version}"', (ROOT / path).read_text()).encode()
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                with open(ROOT / path, "rb") as f:
                    tar.addfile(info, f)
    write_sum(archive)
    return archive


def pin(text: str, version: str, digest: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit("pin needs a version X.Y.Z and a SHA-256 of 64 hex digits")
    text, n = re.subn(r'^POINTE_VERSION="[^"]*"', f'POINTE_VERSION="{version}"', text, count=1, flags=re.M)
    text, m = re.subn(r'^POINTE_SHA256="[^"]*"', f'POINTE_SHA256="{digest}"', text, count=1, flags=re.M)
    if n != 1 or m != 1:
        raise SystemExit("install.sh has no POINTE_VERSION and POINTE_SHA256 lines to pin")
    return text


def published(tag: str) -> str:
    """The SHA-256 the GitHub Release publishes for its tarball, downloaded through gh."""
    got = subprocess.run(["gh", "release", "download", tag, "--repo", REPO, "--pattern", name(tag.removeprefix("v")) + ".sha256",
                          "--output", "-"], check=True, capture_output=True, text=True).stdout
    return got.split()[0]


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("build", "pin") or not re.fullmatch(r"v\d+\.\d+\.\d+", argv[1]):
        print(__doc__)
        return 2
    command, tag = argv
    if command == "build":
        archive = build(tag, ROOT / "dist")
        print(f"{archive.relative_to(ROOT)}  {sha256(archive)}  ({archive.stat().st_size / 1e6:.1f} MB)")
        return 0
    digest = published(tag)
    local = ROOT / "dist" / name(tag.removeprefix("v"))
    if local.exists() and sha256(local) != digest:
        raise SystemExit(f"the release's SHA-256 ({digest}) is not that of {local.relative_to(ROOT)}: not pinned")
    INSTALLER.write_text(pin(INSTALLER.read_text(), tag.removeprefix("v"), digest))
    print(f"install.sh now installs {tag} ({digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
