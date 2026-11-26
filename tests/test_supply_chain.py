"""Supply chain: the tree must match docs/security/supply-chain.md. Pinned Actions and uv, a current lockfile with a
SHA-256 for every package and nothing outside docs/security/dependencies-allowlist.txt, no install path that resolves
unpinned, every download through assets.py with a hash or a commit, no URL to a host outside
docs/security/egress-allowlist.txt, a page that loads nothing from outside the machine. Offline: files, plus `uv lock
--check` on the lockfile. Run it before any change to dependencies, workflows, bin/ or downloads (CLAUDE.md)."""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]

sys.path.insert(0, str(ROOT / "tools"))

import assets  # noqa: E402
import check_action_pins  # noqa: E402
import local  # noqa: E402
import vendors  # noqa: E402

SECURITY = ROOT / "docs" / "security"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
LOCK = tomllib.loads((ROOT / "uv.lock").read_text())
PACKAGES = [p for p in LOCK["package"] if "virtual" not in p.get("source", {})]
INSTALL_UV = (ROOT / "bin" / "install-uv").read_text()
UV_VERSION = re.search(r'^UV_VERSION="([^"]+)"', INSTALL_UV, re.M).group(1)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def files(*patterns: str) -> list[Path]:
    found = {f for pattern in patterns for f in ROOT.glob(pattern) if f.is_file() and ".venv" not in f.parts}
    return sorted(found)


def allowlist(name: str) -> dict[str, str]:
    """name -> reason, from a `name  reason` file with # comments."""
    out = {}
    for line in (SECURITY / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, reason = line.partition(" ")
            out[key] = reason.strip()
    return out


# ---------- GitHub: Actions, permissions, uv, Dependabot ----------

USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)[ \t]*(#.*)?$", re.M)


def test_every_action_is_pinned_to_a_commit_with_its_version_in_a_comment():
    seen = 0
    for wf in WORKFLOWS:
        for m in USES.finditer(wf.read_text()):
            ref, comment = m.group(1), m.group(2) or ""
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{wf.name}: {ref} is not pinned to a 40-hex commit"
            assert re.search(r"#\s*v\d", comment), f"{wf.name}: {ref} needs a '# vX.Y.Z' comment naming the version"
            seen += 1
    assert seen >= 3


def test_every_action_pin_is_the_commit_its_version_tag_points_to_not_the_tag_object():
    """An annotated tag's own SHA is 40 hex too. tests/fixtures/action_pins.json is what github.com answered
    (tools/check_action_pins.py --write records it; CI asks again); this reads it offline."""
    recorded = json.loads((ROOT / "tests" / "fixtures" / "action_pins.json").read_text())
    pins = check_action_pins.pins()
    assert len(pins) >= 3
    for repo, pin, version in pins:
        why = check_action_pins.problem(pin, recorded.get(f"{repo}@{version}"))
        assert why is None, f"{repo}@{pin} ({version}) {why}"
    assert set(recorded) == {f"{repo}@{version}" for repo, _, version in pins}, "tests/fixtures/action_pins.json records a tag no workflow uses"


def test_a_pin_to_an_annotated_tag_object_is_refused():
    tag = {"ref": "a" * 40, "commit": "c" * 40}  # annotated: the ref holds the tag object, which leads to the commit
    assert check_action_pins.problem("c" * 40, tag) is None
    assert "tag object" in check_action_pins.problem("a" * 40, tag)
    assert "not the commit" in check_action_pins.problem("b" * 40, tag)
    assert "not recorded" in check_action_pins.problem("c" * 40, None)
    assert check_action_pins.problem("d" * 40, {"ref": "d" * 40, "commit": "d" * 40}) is None  # a lightweight tag


def test_every_workflow_grants_the_token_read_only():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text())
        assert doc.get("permissions") == {"contents": "read"}, f"{wf.name}: top-level permissions must be contents: read"
        for name, job in doc["jobs"].items():
            assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}, f"{wf.name}: job {name} widens permissions"


def test_every_checkout_leaves_no_token_in_the_git_config():
    """actions/checkout writes the job's token into .git/config unless told not to, where the pull request's own code
    (pytest, xcodebuild) can read it. Read-only today; a leak the day a job gets a wider permission."""
    seen = 0
    for wf in WORKFLOWS:
        for name, job in yaml.safe_load(wf.read_text())["jobs"].items():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    seen += 1
                    assert (step.get("with") or {}).get("persist-credentials") is False, \
                        f"{wf.name}: job {name} checks out with persist-credentials left on"
    assert seen >= 2


def test_ci_and_the_e2e_images_install_the_uv_version_setup_installs():
    pinned = 0
    for wf in WORKFLOWS:
        for job in yaml.safe_load(wf.read_text())["jobs"].values():
            for step in job["steps"]:
                if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                    assert step.get("with", {}).get("version") == UV_VERSION, f"{wf.name}: setup-uv must name version {UV_VERSION}"
                    pinned += 1
    assert pinned >= 2
    for dockerfile in files("tests/e2e/linux_node/*Dockerfile"):
        assert f"ghcr.io/astral-sh/uv:{UV_VERSION}" in dockerfile.read_text(), rel(dockerfile)


def test_ci_runs_the_supply_chain_gate_with_pinned_tools():
    text = (ROOT / ".github" / "workflows" / "test.yml").read_text()
    job = yaml.safe_load(text)["jobs"]["supply-chain"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "uv lock --check" in runs
    assert "tests/test_supply_chain.py" in runs
    assert "tools/check_action_pins.py" in runs
    assert re.search(r"pip-audit@\d+\.\d+\.\d+", runs) and "tools/locked_requirements.py" in runs
    assert re.search(r"cyclonedx-bom@\d+\.\d+\.\d+", runs) and "uv export --locked" in runs
    for tool in re.findall(r"\buvx\s+(?:--from\s+)?(\S+)", runs):
        assert "@" in tool, f"uvx {tool}: name the version"


def test_dependabot_watches_every_ecosystem_weekly_in_groups():
    doc = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    updates = {u["package-ecosystem"]: u for u in doc["updates"]}
    assert set(updates) == {"uv", "github-actions", "npm"}
    assert updates["npm"]["directory"] == "/channel"
    for eco, u in updates.items():
        assert u["schedule"]["interval"] == "weekly" and u.get("groups"), eco


# ---------- the lockfile ----------

@pytest.mark.skipif(not shutil.which("uv"), reason="uv runs the lock check")
def test_the_lockfile_matches_pyproject():
    """`uv lock --check` resolves from uv's cache after a sync; a cold cache reads PyPI's metadata, as CI does."""
    got = subprocess.run(["uv", "lock", "--check", "--project", str(ROOT)], capture_output=True, text=True, timeout=600)
    assert got.returncode == 0, got.stderr[-800:]


def test_every_locked_package_comes_from_pypi_or_a_fixed_url_with_a_sha256():
    for p in PACKAGES:
        source = p["source"]
        assert set(source) <= {"registry", "url"}, f"{p['name']}: {source} (no git, path or editable sources)"
        if "registry" in source:
            assert source["registry"] == "https://pypi.org/simple", p["name"]
        hashes = [p["sdist"]["hash"]] if "sdist" in p else []
        hashes += [w["hash"] for w in p.get("wheels", [])]
        assert hashes, f"{p['name']}: no sdist or wheel"
        assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", h) for h in hashes), p["name"]


def test_the_locked_packages_are_exactly_the_allowlist_each_with_a_reason():
    allowed = allowlist("dependencies-allowlist.txt")
    locked = {p["name"] for p in PACKAGES}
    assert not locked - allowed.keys(), f"in uv.lock but not allowlisted; add each with a reason: {sorted(locked - allowed.keys())}"
    assert not allowed.keys() - locked, f"allowlisted but gone from uv.lock; remove: {sorted(allowed.keys() - locked)}"
    short = [n for n, reason in allowed.items() if len(reason) < 10]
    assert not short, f"a reason, not a word: {short}"


def test_third_party_md_names_every_locked_package():
    """The license inventory a user reads covers what the lockfile installs: a new package needs its line there too."""
    named = {word.strip(".,;:") for word in re.findall(r"[a-z0-9][a-z0-9._-]*", (ROOT / "THIRD_PARTY.md").read_text().lower())}
    missing = sorted(p["name"] for p in PACKAGES if p["name"] not in named)
    assert not missing, f"in uv.lock but not named in THIRD_PARTY.md, add each under its license: {missing}"


def test_the_text_model_server_is_installed_from_the_lockfile():
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]
    assert any(spec.startswith(local.MLX_LM) for spec in groups["mlx-lm"]), "pyproject's mlx-lm group must pin local.MLX_LM"
    assert "mlx-lm" in {p["name"] for p in PACKAGES}
    source = (ROOT / "pointe" / "local.py").read_text()
    assert '"--only-group", "mlx-lm"' in source and "--locked" in source and "uv pip" not in source


def test_locked_requirements_lists_every_package_for_the_audit():
    got = subprocess.run([sys.executable, str(ROOT / "tools" / "locked_requirements.py")], capture_output=True, text=True, check=True)
    lines = got.stdout.split()
    assert len(lines) == len(PACKAGES) and all(re.fullmatch(r"[a-z0-9][a-z0-9._-]*==\S+", line) for line in lines)
    assert "mlx-lm==0.32.2" in lines  # a package only Apple silicon installs is audited too


# ---------- install paths ----------

# Files whose commands a person or Claude runs. Prose files are reduced to their code spans and fenced blocks first.
INSTALL_PATHS = ("install.sh", "bin/*", "hooks/**/*", "plugin/**/*", ".claude-plugin/*", ".github/workflows/*.yml", "pointe/local.py", "pointe/node_cli.py",
                 "pointe/harnesses/*.py", "docs/**/*.md", "README.md", "CONTRIBUTING.md", "THIRD_PARTY.md")
RULE_DOCS = {"docs/security/supply-chain.md", "SECURITY.md", "CLAUDE.md"}  # they name the forbidden commands to forbid them
CODE = re.compile(r"```.*?```|`[^`\n]+`", re.S)


def commands_in(path: Path) -> str:
    text = path.read_text()
    return "\n".join(CODE.findall(text)) if path.suffix == ".md" else text


def test_no_install_path_resolves_unpinned():
    bad = []
    for path in files(*INSTALL_PATHS):
        if rel(path) in RULE_DOCS:
            continue
        for n, line in enumerate(commands_in(path).splitlines(), 1):
            where = f"{rel(path)}:{n}: {line.strip()[:90]}"
            if re.search(r"\b(pip3?|uv pip) install\b", line):
                bad.append(f"{where}  (pip install: add the package to pyproject.toml and uv lock)")
            if re.search(r"\b(curl|wget)\b[^|\n]*\|\s*(ba|z)?sh\b", line):
                bad.append(f"{where}  (curl | sh: fetch to a file and check a SHA-256, as bin/install-uv does)")
            for tool in re.findall(r"\b(?:uvx|uv tool run)\s+(?:--from\s+)?(\S+)", line):
                if "@" not in tool and not tool.startswith("-"):
                    bad.append(f"{where}  (uvx {tool}: name the version, uvx {tool}@X.Y.Z)")
            if re.search(r"\buv (run|sync)\b", line) and not re.search(r"--(locked|no-sync|frozen)\b", line):
                bad.append(f"{where}  (uv run/sync without --locked)")
            if re.search(r"\bnpm (install|i|add)\b", line):
                bad.append(f"{where}  (npm install: npm ci --ignore-scripts from the lockfile)")
    assert not bad, "\n" + "\n".join(bad)


def test_nothing_the_plugin_runs_fetches_remote_code():
    """hooks/, plugin/ and bin/ reach only the daemon on loopback; the one download, bin/install-uv, is pinned above."""
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    for event in hooks["hooks"].values():
        for group in event:
            for hook in group["hooks"]:
                assert hook["command"].startswith('"${CLAUDE_PLUGIN_ROOT}"/bin/'), hook["command"]
    for path in files("bin/*", "channel/*.mjs"):
        for n, line in enumerate(path.read_text().replace("\\\n", " ").splitlines(), 1):  # a command continued with \\ is one line
            if line.lstrip().startswith("#") or line.lstrip().startswith("//"):
                continue
            assert not re.search(r"\beval\b|source\s*<\(|bash\s+-c\s+\"\$\(", line), f"{rel(path)}:{n}"
            if path.name != "install-uv" and re.search(r"\b(curl|wget|fetch\()", line):
                assert "127.0.0.1" in line or "$URL" in line or "DAEMON_URL" in line, f"{rel(path)}:{n}: reaches past loopback: {line.strip()[:100]}"


PY_INLINE = re.compile(r"(?:\bpython3?|\"\$PY\")((?:\s+-[A-Za-z]+)*?)\s+(-c\b|-(?=\s|$))")


def test_no_script_runs_python_code_with_the_current_folder_on_its_path():
    """`python3 -c` and `python3 -` put the folder they run in first on the import path: a session's repo with a
    `json.py` would run as you, with the token at hand. `-I` leaves it out (and ignores PYTHON* variables)."""
    bad = []
    for path in files("bin/*", "hooks/**/*", "plugin/**/*"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for flags, _ in PY_INLINE.findall(line):
                if "-I" not in flags.split():
                    bad.append(f"{rel(path)}:{n}: {line.strip()[:90]}")
    assert not bad, "use python3 -I -c / python3 -I -:\n" + "\n".join(bad)
    assert PY_INLINE.findall("x | python3 -c 'import json'") == [("", "-c")]
    assert PY_INLINE.findall('python3 - "$J" <<PY') == [("", "-")]
    assert PY_INLINE.findall('"$PY" -c "print(1)"') == [("", "-c")]


SHIPPED_PY = ("pointe/*.py", "pointe/harnesses/*.py")


def test_the_keychain_and_dialog_tools_are_run_by_their_absolute_path():
    """`security` gives out a key (`-w`) and takes one (`add-generic-password`), `osascript` returns the key typed in its
    dialog: none of these is looked up on PATH, where a folder earlier in it could hold another program of that name.
    Both tools are macOS-only, in /usr/bin. (uninstall.py and apps.py only ask whether an item exists, delete one, or
    list signing identities; their tests put a stand-in `security` on PATH, so they keep the name.)"""
    bad = []
    for path in files(*SHIPPED_PY):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            named = re.search(r"[\[(]\s*[\"'](security|osascript)[\"']", line)
            if named and "/usr/bin/" not in line and (named.group(1) == "osascript" or re.search(r"[\"']-w[\"']|add-generic-password", line)):
                bad.append(f"{rel(path)}:{n}: {line.strip()[:90]}")
    assert not bad, "use /usr/bin/security and /usr/bin/osascript:\n" + "\n".join(bad)
def test_only_the_two_installers_reach_past_loopback_and_each_checks_a_sha256_first():
    """install.sh (the standalone install and `pointe update`) and bin/install-uv are the only scripts that download.
    install.sh fetches only github.com (a release by version, its .sha256, the /releases/latest redirect), over https
    with no redirect to another scheme, and unpacks only after the hash matched: the pin in the file, or the one
    published with the release."""
    text = (ROOT / "install.sh").read_text()
    assert re.search(r'^POINTE_SHA256="([0-9a-f]{64})?"', text, re.M) and re.search(r'^POINTE_VERSION="\d+\.\d+\.\d+"', text, re.M)
    assert 'REPO="https://github.com/ballerine-io/pointe"' in text
    curls = [line for line in text.splitlines() if re.search(r"\bcurl\b", line) and not line.lstrip().startswith(("#", "for "))]
    assert len(curls) == 2 and all("--proto '=https" in line and "--tlsv1.2" in line for line in curls), curls
    assert "--proto-redir '=https'" in text
    assert text.index('[ "$GOT" = "$SHA" ] || die') < text.index("tar -xzf") < text.index('"$DEST/install.sh" --activate')
    assert not re.search(r"\beval\b|\|\s*(ba|z)?sh\b|source\s*<\(", text)
    assert '"$ROOT/$INSTALL_UV"' in text  # uv only through the pinned installer
    pointe = (ROOT / "bin" / "pointe").read_text()
    assert '"$STANDALONE/install.sh" --update' in pointe and "curl" not in pointe


def test_setup_installs_uv_through_the_pinned_installer_only():
    assert re.fullmatch(r"\d+\.\d+\.\d+", UV_VERSION)
    assert re.search(r'^INSTALLER_SHA256="[0-9a-f]{64}"', INSTALL_UV, re.M)
    assert f"https://astral.sh/uv/$UV_VERSION/install.sh" in INSTALL_UV and "shasum -a 256" in INSTALL_UV
    setup = (ROOT / "plugin" / "commands" / "setup.md").read_text()
    assert "bin/install-uv" in setup and "astral.sh" not in setup and "curl" not in setup


def test_install_uv_refuses_an_installer_with_another_hash(tmp_path):
    """A `curl` that returns something else (a tampered mirror, a changed script) must stop it before anything runs."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "curl").write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done\necho "echo pwned >$HOME/pwned" >"$out"\n')
    (fake / "curl").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    got = subprocess.run([str(ROOT / "bin" / "install-uv")], env={"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin"},
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 1 and "does not match its pinned SHA-256" in got.stderr
    assert not (home / "pwned").exists() and not (home / ".local").exists()


@pytest.mark.parametrize("found, says", [(UV_VERSION, "ok "), ("0.1.0", "note ")])
def test_install_uv_says_when_the_uv_it_finds_is_not_the_pinned_one(tmp_path, found, says):
    """A uv already on the PATH is used as it is (docs/security/supply-chain.md): another version is said, not hidden."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "uv").write_text(f'#!/bin/sh\necho "uv {found} (synthetic)"\n')
    (fake / "uv").chmod(0o755)
    (fake / "curl").write_text("#!/bin/sh\nexit 99\n")
    (fake / "curl").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    got = subprocess.run([str(ROOT / "bin" / "install-uv")], capture_output=True, text=True, timeout=60,
                         env={"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin", "POINTE_LINK_DIR": str(tmp_path / "link")})
    assert got.returncode == 0, got.stderr
    first = got.stdout.splitlines()[0]
    assert first.startswith(says) and found in first, first
    if found != UV_VERSION:
        assert UV_VERSION in first


def test_the_channel_installs_from_its_lockfile_with_integrity_and_no_scripts():
    lock = json.loads((ROOT / "channel" / "package-lock.json").read_text())
    assert lock["lockfileVersion"] >= 2
    for name, entry in lock["packages"].items():
        if name:
            assert entry["resolved"].startswith("https://registry.npmjs.org/"), name
            assert entry["integrity"].startswith("sha512-"), name
    assert "npm ci --prefix \"$ROOT/channel\" --ignore-scripts" in (ROOT / "bin" / "claude-voice").read_text()


def test_the_apple_apps_pull_no_packages():
    """The iPhone app and the Mac app depend on Apple frameworks and on one package in this repository
    (apps/PointeKit, what the two share), which itself depends on nothing: no package is fetched from anywhere."""
    for project in ("apps/ios/Pointe.xcodeproj", "apps/macos/PointeMac.xcodeproj"):
        text = (ROOT / project / "project.pbxproj").read_text()
        assert "XCRemoteSwiftPackageReference" not in text, project
        local = re.findall(r"relativePath = ([^;]+);", text)
        assert set(local) <= {"../PointeKit"}, f"{project}: the only package is the one in this repository"
        assert ("XCSwiftPackageProductDependency" in text) == bool(local), project
    manifest = (ROOT / "apps" / "PointeKit" / "Package.swift").read_text()
    assert ".package(" not in manifest and "dependencies: [\n" not in manifest and "url:" not in manifest
    assert set(re.findall(r'dependencies: \[([^\]]*)\]', manifest)) <= {'"PointeKit"', '"PointeUI"', '"PointeMacKit"'}, "targets depend on each other only"
    assert not files("apps/ios/**/Package.swift", "**/Package.resolved", "apps/ios/**/Podfile*", "apps/macos/**/Podfile*", "apps/macos/**/Package.swift")


# ---------- downloads ----------

def test_every_runtime_download_is_pinned_in_assets():
    for key, asset in assets.ASSETS.items():
        assert asset.url.startswith("https://") and re.fullmatch(r"[0-9a-f]{64}", asset.sha256), key
    for repo, commit in assets.HF_MODELS.items():
        assert re.fullmatch(r"[0-9a-f]{40}", commit), repo
    for repo in (vendors.LOCAL_EARS_MODEL, vendors.LOCAL_EARS_MODEL_CT2, local.TEXT_MODEL, local.VOICE_MODEL):
        assert repo in assets.HF_MODELS, f"{repo}: pin its commit in assets.HF_MODELS"
    third_party = (ROOT / "THIRD_PARTY.md").read_text()
    for repo in assets.HF_MODELS:
        assert repo in third_party, f"THIRD_PARTY.md: a row for {repo}"
    for asset in assets.ASSETS.values():
        assert asset.name in third_party, f"THIRD_PARTY.md: a row for {asset.name}"


def test_no_module_downloads_around_assets():
    for path in files("pointe/*.py", "pointe/harnesses/*.py"):
        if path.name == "assets.py":
            continue
        source = path.read_text()
        for forbidden in ("snapshot_download(", "hf_hub_download(", "_ensure_model_files", "urlretrieve("):
            assert forbidden not in source, f"{rel(path)}: {forbidden} bypasses the pins; use assets.snapshot / assets.fetch"
        if "KokoroTTSService(" in source:
            assert "model_path=" in source and "voices_path=" in source, f"{rel(path)}: hand Pipecat the verified Kokoro files by path"
        assert "revision=" not in source.replace("revision=revision(repo)", ""), f"{rel(path)}: a revision belongs in assets.HF_MODELS"


def test_fetch_keeps_only_a_file_whose_hash_is_the_pinned_one(tmp_path, monkeypatch):
    good = b"model bytes " * 1000
    asset = assets.Asset("m.onnx", "https://github.com/x/releases/download/v1/m.onnx", hashlib.sha256(good).hexdigest(), 1, "test")
    served = {"body": good}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda url, timeout: Response(served["body"]))
    target = tmp_path / "models" / "m.onnx"
    assert assets.fetch(asset, target) == target and target.read_bytes() == good
    assert not list(tmp_path.rglob("*.part"))

    served["body"] = good + b"!"  # one byte more: a replaced release asset
    target.unlink()
    with pytest.raises(ValueError, match="does not match"):
        assets.fetch(asset, target)
    assert not target.exists() and not list(tmp_path.rglob("*.part")), "nothing with the asset's name may stay on disk"

    target.write_bytes(b"left by an older downloader that checked nothing")
    served["body"] = good
    assert assets.ensure(asset, target) == target and target.read_bytes() == good, "an unverified copy is replaced"
    served["body"] = b"never asked for"
    assert assets.ensure(asset, target).read_bytes() == good, "a verified copy is not fetched again"


# ---------- egress ----------

URL_HOST = re.compile(r"(?:https?|wss?)://([A-Za-z0-9][A-Za-z0-9.-]*)")
EGRESS_SOURCES = ("install.sh", "pointe/*.py", "pointe/harnesses/*.py", "bench/**/*.py", "bench/**/*.sh", "bench/**/*.ts", "evals/**/*.py", "tools/demo-video/**/*.py",
                  "apps/ios/e2e/*.py", "apps/ios/*.sh", "apps/macos/e2e/*", "tools/*.py", "tools/*.sh", "tools/release", "tools/releasekit/*.py", "bin/*", "hooks/**/*", "plugin/**/*", ".claude-plugin/*",
                  "channel/*.mjs", "channel/package.json", "pointe/ui*.html", "site/**/*", "apps/ios/Pointe/**/*.swift", "apps/ios/PointeShared/*.swift", "apps/ios/PointeWidget/*.swift", "apps/PointeKit/Package.swift",
                  "apps/PointeKit/Sources/**/*.swift", "apps/macos/PointeMac/**/*.swift", "apps/macos/*.sh",
                  "apps/macos/tools/*", ".github/**/*.yml", "tools/*.swift", "apps/macos/PointeMac/*.sh")


def test_every_scanned_pattern_finds_files():
    """A pattern that matches nothing passes every scan above vacuously: after a file moves, its scan must move too."""
    empty = [p for p in (*EGRESS_SOURCES, *INSTALL_PATHS, *SHIPPED_PY) if not files(p)]
    assert not empty, f"these patterns match no file: {empty}"


def egress() -> tuple[set[str], set[str]]:
    """(hosts the software may contact, hosts only shown to a person)."""
    contacted, shown = set(), set()
    for line in (SECURITY / "egress-allowlist.txt").read_text().splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0] == "link":
            shown.add(words[1])
        else:
            contacted.add(words[0])
    return contacted, shown


def allowed(host: str, hosts: set[str]) -> bool:
    return host in hosts or any(h.startswith("*.") and host.endswith(h[1:]) for h in hosts)


def test_every_url_in_the_source_names_a_host_in_the_egress_allowlist():
    contacted, shown = egress()
    strangers = []
    for path in files(*EGRESS_SOURCES):
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for host in URL_HOST.findall(line):
                if not allowed(host, contacted | shown):
                    strangers.append(f"{rel(path)}:{n}: {host}")
    assert not strangers, "hosts not in docs/security/egress-allowlist.txt (add with a reason, or `link` if only shown):\n" + "\n".join(strangers)


def test_the_egress_scan_reads_every_source_file():
    """"Every URL literal in the source" means every file: a new folder of code must not fall outside the scan. Test
    targets are left out: they name made-up hosts on purpose."""
    tracked = subprocess.run(["git", "ls-files", "*.py", "*.sh", "*.mjs", "*.ts", "*.swift", "bin/*"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
    tests = re.compile(r"^tests/|/Tests/|Tests/")
    scanned = {rel(p) for p in files(*EGRESS_SOURCES)}
    missed = sorted(t for t in tracked if t not in scanned and not tests.search(t))
    assert not missed, "add to EGRESS_SOURCES:\n" + "\n".join(missed)
def test_every_host_a_dependency_was_seen_to_contact_is_in_the_egress_allowlist():
    """The URL grep sees only literals in our source; hf-xet is told its hosts by the server at runtime."""
    contacted, _ = egress()
    seen = [line.split()[0] for line in (ROOT / "tests" / "fixtures" / "dependency_hosts.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    assert seen, "tests/fixtures/dependency_hosts.txt lists no host"
    missing = [h for h in seen if not allowed(h, contacted)]
    assert not missing, f"contacted at runtime but not in docs/security/egress-allowlist.txt: {missing}"


def test_the_egress_table_in_the_doc_and_the_allowlist_agree():
    doc = (ROOT / "docs" / "security" / "supply-chain.md").read_text()
    section = doc.split("## Outbound hosts", 1)[1].split("\n## ", 1)[0]
    dns = re.compile(r"[a-z0-9*][a-z0-9.*-]*\.[a-z]{2,}")
    in_doc = {h for h in re.findall(r"`([^`]+)`", section) if dns.fullmatch(h)}
    contacted, _ = egress()
    listed = {h for h in contacted if dns.fullmatch(h)}
    assert in_doc == listed, f"only in the doc: {sorted(in_doc - listed)}; only in the allowlist: {sorted(listed - in_doc)}"


def test_the_page_and_the_site_load_nothing_from_outside_the_machine():
    loads = re.compile(r"<(?:script|link|img|iframe|source|video|audio|object|embed)\b[^>]*\b(?:src|href)=[\"'](?:https?:)?//", re.I)
    css = re.compile(r"@import\b|url\(\s*[\"']?(?:https?:)?//", re.I)
    for path in files("pointe/ui*.html", "site/**/*.html", "site/**/*.css"):
        text = path.read_text()
        assert not loads.search(text), f"{rel(path)}: loads a resource from another host"
        assert not css.search(text), f"{rel(path)}: CSS fetches from another host"


# ---------- the rules agents follow ----------

def test_claude_md_states_the_supply_chain_rules_and_agents_md_is_its_mirror():
    claude = ROOT / "CLAUDE.md"
    assert "## Supply chain" in claude.read_text()
    agents = ROOT / "AGENTS.md"
    assert agents.is_symlink() and os.readlink(agents) == "CLAUDE.md"
