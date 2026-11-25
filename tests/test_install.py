"""The standalone install (install.sh), `pointe update`, `pointe uninstall` of it, and the plugin and the standalone install
side by side (bin/pointe-installs). The installer runs for real against a test release built from this tree
(tools/release_tarball.py worktree) and served as a file:// URL, with a throwaway HOME for the shell parts only. uv's
cache and Python come from the real ones, read-only in practice (a sync from a warm cache downloads nothing). Nothing here
opens a browser or a window or reads the Keychain: `security` is a fake, and the terminal setup runs with --no-open."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
sys.path.insert(0, str(ROOT / "tools"))
import release_tarball  # noqa: E402
import terminal_setup  # noqa: E402
import uninstall  # noqa: E402

INSTALL = ROOT / "install.sh"
UV = shutil.which("uv")
pytestmark = pytest.mark.skipif(UV is None, reason="needs uv")


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    """Two test releases, 9.9.1 and 9.9.2, each with the .sha256 a GitHub Release carries."""
    out = tmp_path_factory.mktemp("releases")
    return {v: release_tarball.worktree(out, v) for v in ("9.9.1", "9.9.2")}


def uv_dir(*args: str) -> str:
    return subprocess.run([UV, *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def mac(tmp_path):
    """A throwaway HOME whose PATH holds the system's tools, uv, and fakes for `security` and `claude`."""
    home, fake = tmp_path / "home", tmp_path / "fakebin"
    home.mkdir()
    fake.mkdir()
    (fake / "uv").symlink_to(UV)
    (fake / "security").write_text("#!/bin/sh\nexit 44\n")  # never the real Keychain
    (fake / "security").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin:/usr/sbin:/sbin", "CLAUDE_VOICE_STATE": str(tmp_path / "state"),
           "CLAUDE_VOICE_DAEMON_PORT": "7991", "UV_CACHE_DIR": uv_dir("cache", "dir"),
           "UV_PYTHON_INSTALL_DIR": uv_dir("python", "dir"), "LANG": "C.UTF-8"}

    def sh(*args, **kw):
        return subprocess.run([str(a) for a in args], env=env, capture_output=True, text=True, timeout=600, **kw)

    return type("Mac", (), {"home": home, "env": env, "sh": staticmethod(sh), "fake": fake,
                            "link": home / ".local" / "bin" / "pointe", "pointe_home": home / ".pointe"})


def sha_of(archive: Path) -> str:
    return archive.with_name(archive.name + ".sha256").read_text().split()[0]


def install(mac, archive: Path, version: str, *extra: str):
    return mac.sh("bash", INSTALL, "--yes", "--version", version, "--url", archive.as_uri(), *extra)


# ---------- install ----------

def test_the_installer_installs_a_checked_release_end_to_end(mac, releases):
    got = install(mac, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"]))
    assert got.returncode == 0, got.stdout + got.stderr
    root = mac.pointe_home / "9.9.1"
    assert (root / ".pointe-install").read_text().startswith("standalone 9.9.1 sha256 ")
    assert (root / ".venv").is_dir() and not (root / "bench").exists()  # the release leaves out what a person never runs
    assert f"exec {root.resolve() / 'bin' / 'pointe'}" in mac.link.read_text()
    assert mac.sh(mac.link, "version").stdout == "Pointe 9.9.1\n"
    assert "SHA-256 matches" in got.stdout and "Next: ~/.local/bin/pointe setup" in got.stdout
    listed = mac.sh(root / "bin" / "pointe-installs", "list").stdout.split("\t")
    assert listed[:2] == ["standalone", "9.9.1"]
    assert not list(mac.pointe_home.glob(".download.*"))  # its temporary folder is gone


def test_the_installer_asks_first_and_changes_nothing_on_no(mac, releases):
    got = mac.sh("bash", INSTALL, "--version", "9.9.1", "--url", releases["9.9.1"].as_uri(), input="n\n")
    assert got.returncode == 1 and "Go ahead?" in got.stdout and "Nothing changed." in got.stdout
    for step in ("download", "check", "unpack", "uv", "Python packages", "~/.local/bin/pointe", "pointe uninstall"):
        assert step in got.stdout, step
    assert not mac.pointe_home.exists() and not mac.link.exists()


def test_a_tampered_tarball_is_refused_and_nothing_is_installed(mac, releases, tmp_path):
    bad = tmp_path / "pointe-9.9.1.tar.gz"
    data = bytearray(releases["9.9.1"].read_bytes())
    data[len(data) // 2] ^= 1
    bad.write_bytes(bytes(data))
    shutil.copy(releases["9.9.1"].with_name("pointe-9.9.1.tar.gz.sha256"), tmp_path / "pointe-9.9.1.tar.gz.sha256")
    for extra in (("--sha256", sha_of(releases["9.9.1"])), ()):  # the hash given, and the one published with the release
        got = install(mac, bad, "9.9.1", *extra)
        assert got.returncode == 1 and "does not match" in got.stderr and "not installing" in got.stderr, got.stderr
        assert not (mac.pointe_home / "9.9.1").exists() and not mac.link.exists()


def test_a_release_without_a_published_sha256_is_refused(mac, releases, tmp_path):
    lone = tmp_path / "pointe-9.9.1.tar.gz"
    shutil.copy(releases["9.9.1"], lone)
    got = install(mac, lone, "9.9.1")
    assert got.returncode == 1 and "publishes no SHA-256" in got.stderr and not mac.link.exists()


def test_the_installer_runs_without_sudo_and_never_pipes_a_download_into_a_shell():
    text = INSTALL.read_text()
    assert '[ "$(id -u)" != 0 ] || die' in text and "sudo " not in text.split("set -euo pipefail", 1)[1].replace("Nothing needs sudo", "")
    check, unpack = text.index('[ "$GOT" = "$SHA" ] || die'), text.index('tar -xzf')
    assert check < unpack, "the SHA-256 is checked before anything from the archive is unpacked"


# ---------- Linux: hub or node ----------

@pytest.fixture
def linux(mac):
    """The same throwaway HOME, with `uname` saying Linux."""
    (mac.fake / "uname").write_text('#!/bin/sh\n[ "$1" = -s ] && echo Linux || /usr/bin/uname "$@"\n')
    (mac.fake / "uname").chmod(0o755)
    return mac


def test_on_linux_yes_installs_a_hub_and_says_where_keys_go(linux, releases):
    got = install(linux, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"]))
    assert got.returncode == 0, got.stdout + got.stderr
    assert "1. hub" in got.stdout and "2. node" in got.stdout and "--yes: hub" in got.stdout
    assert "only run as a node of a Mac" not in got.stdout
    assert (linux.pointe_home / "9.9.1" / ".venv").is_dir()
    assert "Next: ~/.local/bin/pointe setup" in got.stdout and "login keyring" in got.stdout and "Keychain" not in got.stdout


def test_on_linux_a_node_skips_the_voice_packages_and_says_how_to_join(linux, releases):
    got = install(linux, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"]), "--node")
    assert got.returncode == 0, got.stdout + got.stderr
    root = linux.pointe_home / "9.9.1"
    assert (root / ".pointe-install").exists() and not (root / ".venv").exists()
    assert "skip      the voice packages" in got.stdout and "pointe hub invite" in got.stdout
    assert "node join" in got.stdout and "pointe setup" not in got.stdout
    assert linux.sh(linux.link, "version").stdout == "Pointe 9.9.1\n"


def test_on_linux_with_no_terminal_to_ask_on_nothing_changes(linux, releases):
    got = linux.sh("bash", INSTALL, "--version", "9.9.1", "--url", releases["9.9.1"].as_uri(), input="2\n",
                   start_new_session=True)
    assert got.returncode == 1 and "add --hub or --node" in got.stdout and not linux.pointe_home.exists()


# ---------- update and uninstall ----------

def test_pointe_update_installs_the_newer_release_checked_and_removes_the_older(mac, releases, tmp_path):
    assert install(mac, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"])).returncode == 0
    bad = tmp_path / "pointe-9.9.2.tar.gz"
    bad.write_bytes(releases["9.9.2"].read_bytes() + b"x")
    shutil.copy(releases["9.9.2"].with_name("pointe-9.9.2.tar.gz.sha256"), tmp_path / "pointe-9.9.2.tar.gz.sha256")
    refused = mac.sh(mac.link, "update", "--yes", "--version", "9.9.2", "--url", bad.as_uri())
    assert refused.returncode == 1 and "does not match the SHA-256 published with the release" in refused.stderr
    assert mac.sh(mac.link, "version").stdout == "Pointe 9.9.1\n"

    got = mac.sh(mac.link, "update", "--yes", "--version", "9.9.2", "--url", releases["9.9.2"].as_uri())
    assert got.returncode == 0, got.stdout + got.stderr
    assert "This updates Pointe 9.9.1 to 9.9.2" in got.stdout and "Pointe is updated to 9.9.2." in got.stdout
    assert mac.sh(mac.link, "version").stdout == "Pointe 9.9.2\n"
    assert sorted(p.name for p in mac.pointe_home.iterdir()) == ["9.9.2"]

    again = mac.sh(mac.link, "update", "--yes", "--version", "9.9.2")
    assert again.returncode == 0 and "Pointe 9.9.2 is up to date" in again.stdout
    older = install(mac, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"]))  # an old install.sh, run again
    assert older.returncode == 0 and "Pointe 9.9.2 is installed already, newer than 9.9.1" in older.stdout
    assert sorted(p.name for p in mac.pointe_home.iterdir()) == ["9.9.2"]


def test_pointe_update_finds_the_newest_release_by_githubs_redirect(mac, releases):
    """/releases/latest answers with a redirect to the newest tag: read through a fake curl, no network."""
    assert install(mac, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"])).returncode == 0
    (mac.fake / "curl").write_text('#!/bin/sh\necho "https://github.com/ballerine-io/pointe/releases/tag/v9.9.1"\n')
    (mac.fake / "curl").chmod(0o755)
    got = mac.sh(mac.link, "update")
    assert got.returncode == 0 and "Pointe 9.9.1 is up to date: 9.9.1 is not newer." in got.stdout


def test_pointe_uninstall_removes_the_standalone_install_and_the_command(mac, releases):
    assert install(mac, releases["9.9.1"], "9.9.1", "--sha256", sha_of(releases["9.9.1"])).returncode == 0
    listed = mac.sh(mac.link, "uninstall", "--dry-run").stdout
    assert f"{mac.pointe_home} (" in listed and "the standalone install" in listed
    got = mac.sh(mac.link, "uninstall", "--yes")
    assert got.returncode == 0 and "Pointe is removed." in got.stdout, got.stdout
    assert not mac.pointe_home.exists() and not mac.link.exists()


# ---------- three layouts, and the plugin beside the standalone install ----------

def copy_of(root: Path, version: str, *, marker: bool = False, daemon: str | None = None) -> Path:
    """A Pointe folder holding this tree's bin/ scripts and `version` in its manifest; `daemon` replaces voice-daemon."""
    shutil.copytree(ROOT / "bin", root / "bin")
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "pointe", "version": version}))
    if marker:
        (root / ".pointe-install").write_text(f"standalone {version}\n")
    if daemon is not None:
        (root / "bin" / "voice-daemon").write_text(f"#!/bin/sh\necho {daemon} \"$@\"\n")
    return root


def resolve(mac, root: Path, *args: str) -> str:
    return mac.sh(root / "bin" / "pointe-installs", *args).stdout.strip()


def test_each_layout_is_told_apart(mac, tmp_path):
    plugin = copy_of(mac.home / ".claude" / "plugins" / "cache" / "pointe" / "pointe" / "1.30.0", "1.30.0")
    standalone = copy_of(mac.pointe_home / "1.31.0", "1.31.0", marker=True)
    unfinished = copy_of(mac.pointe_home / "1.99.0", "1.99.0")  # no .pointe-install: never checked
    clone = copy_of(tmp_path / "src" / "pointe", "2.0.0")
    assert resolve(mac, plugin, "kind") == "plugin"
    assert resolve(mac, standalone, "kind") == "standalone"
    assert resolve(mac, unfinished, "kind") == "clone" and resolve(mac, clone, "kind") == "clone"
    rows = [line.split("\t")[:2] for line in resolve(mac, clone, "list").splitlines()]
    assert rows == [["standalone", "1.31.0"], ["plugin", "1.30.0"]]  # a clone is never an installed copy
    (plugin / ".orphaned_at").write_text("")  # Claude Code's mark on a version an update replaced
    assert resolve(mac, plugin, "kind") == "clone"


def test_the_plugin_recorded_by_claude_code_is_the_plugin(mac):
    cache = mac.home / ".claude" / "plugins" / "cache" / "pointe" / "pointe"
    old = copy_of(cache / "1.20.0", "1.20.0")
    copy_of(cache / "1.21.0", "1.21.0")  # left in the cache, not the installed one
    (mac.home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"pointe@pointe": [{"scope": "user", "installPath": str(old), "version": "1.20.0"}]}}, indent=2))
    assert resolve(mac, old, "newest") == str(old.resolve())


@pytest.mark.parametrize("newer", ["plugin", "standalone", "tie"])
def test_plugin_and_standalone_side_by_side_one_command_one_daemon_the_newer_wins(mac, newer):
    versions = {"plugin": ("1.31.0", "1.30.0"), "standalone": ("1.30.0", "1.31.0"), "tie": ("1.30.0", "1.30.0")}[newer]
    plugin = copy_of(mac.home / ".claude" / "plugins" / "cache" / "pointe" / "pointe" / versions[0], versions[0], daemon="plugin")
    standalone = copy_of(mac.pointe_home / versions[1], versions[1], marker=True, daemon="standalone")
    winner = {"plugin": plugin, "standalone": standalone, "tie": standalone}[newer]
    for starter in (plugin, standalone):
        assert mac.sh(starter / "bin" / "link-pointe", "--quiet").returncode == 0
        assert f"exec {winner.resolve() / 'bin' / 'pointe'}" in mac.link.read_text(), (newer, starter)
    # the real voice-daemon, run from the other copy, hands the start to the winner's (a stub that only says its name)
    loser = standalone if winner == plugin else plugin
    shutil.copy(ROOT / "bin" / "voice-daemon", loser / "bin" / "voice-daemon")
    got = mac.sh(loser / "bin" / "voice-daemon", "ensure")
    assert got.stdout.strip() == f"{'plugin' if winner == plugin else 'standalone'} ensure", got.stderr


def test_a_clone_starts_itself_and_leaves_the_installed_command(mac, tmp_path):
    standalone = copy_of(mac.pointe_home / "1.31.0", "1.31.0", marker=True)
    mac.sh(standalone / "bin" / "link-pointe", "--quiet")
    clone = copy_of(tmp_path / "src" / "pointe", "9.0.0")
    assert mac.sh(clone / "bin" / "link-pointe", "--at-start").returncode == 0
    assert f"exec {standalone.resolve() / 'bin' / 'pointe'}" in mac.link.read_text()


def test_doctor_says_which_copy_runs_and_that_a_newer_one_waits(mac, monkeypatch):
    import doctor

    plugin = copy_of(mac.home / ".claude" / "plugins" / "cache" / "pointe" / "pointe" / "1.30.0", "1.30.0")
    copy_of(mac.pointe_home / "1.31.0", "1.31.0", marker=True)
    state = Path(mac.env["CLAUDE_VOICE_STATE"])
    state.mkdir()
    (state / "daemon.pid").write_text(str(os.getpid()))  # a live pid: this test
    (state / "daemon.root").write_text(str(plugin))
    for name in ("HOME", "CLAUDE_VOICE_STATE"):
        monkeypatch.setenv(name, mac.env[name])
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("POINTE_HOME", raising=False)
    lines = "\n".join(doctor.install_lines())
    assert "standalone install 1.31.0" in lines and "(the newest: pointe and each start use it)" in lines
    assert "Claude Code plugin 1.30.0" in lines
    assert "running: the Claude Code plugin, 1.30.0" in lines and "The standalone install is newer (1.31.0): pointe restart runs it." in lines


# ---------- the terminal setup ----------

@pytest.fixture
def terminal(mac, monkeypatch):
    """terminal_setup with the Mac's checks, the Keychain and every command it runs replaced: `calls` records them."""
    calls = []
    monkeypatch.setenv("CLAUDE_VOICE_STATE", mac.env["CLAUDE_VOICE_STATE"])
    monkeypatch.setattr(terminal_setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(terminal_setup, "chrome", lambda: True)
    monkeypatch.setattr(terminal_setup, "run", lambda *a: calls.append(a) or 0)
    monkeypatch.setattr(terminal_setup.shutil, "which", lambda name: None)
    return calls


def test_the_terminal_setup_asks_one_question_and_opens_nothing_with_no_open(mac, terminal, monkeypatch, capsys):
    monkeypatch.setattr(terminal_setup, "missing", lambda s: list(s.keys))  # no key saved
    asked = []
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "")  # Enter: the default, Free start
    assert terminal_setup.main(["--no-open"]) == 0
    out = capsys.readouterr().out
    assert asked == ["Start with Free start? [Y/n] "]
    assert "Save the Gemini key: pointe key gemini" in out and "Then run pointe setup again" in out
    assert terminal == []  # no key window, no browser, no daemon without its key
    state = Path(mac.env["CLAUDE_VOICE_STATE"])
    assert json.loads((state / "config.json").read_text())["setup"] == "free" and not (state / "setup-done").exists()


def test_the_terminal_setup_uses_the_keys_there_and_starts_the_first_call(mac, terminal, monkeypatch, capsys):
    monkeypatch.setattr(terminal_setup, "missing", lambda s: [])  # every key saved
    monkeypatch.setattr("builtins.input", lambda q: pytest.fail(f"asked {q!r}"))
    assert terminal_setup.main(["--no-open"]) == 0
    out = capsys.readouterr().out
    assert "Your Anthropic and Soniox and ElevenLabs and Gemini keys fill the Fastest and most accurate voice setup." in out
    assert terminal == [("voice-daemon", "ensure")] and "The page: pointe open." in out
    assert (Path(mac.env["CLAUDE_VOICE_STATE"]) / "setup-done").exists()


def test_the_terminal_setup_runs_on_linux_and_names_the_keyring(mac, terminal, monkeypatch, capsys):
    monkeypatch.setattr(terminal_setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(terminal_setup, "missing", lambda s: list(s.keys))
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert terminal_setup.main(["--no-open"]) == 0
    out = capsys.readouterr().out
    assert "needs macOS" not in out and "Step 1 of 4: this machine." in out
    assert "pointe key gemini (asks with hidden typing; the key goes to your login keyring)" in out


def test_on_linux_with_no_desktop_the_first_call_is_from_the_phone_or_another_machine(mac, terminal, monkeypatch, capsys):
    monkeypatch.setattr(terminal_setup.platform, "system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(terminal_setup, "missing", lambda s: [])
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert terminal_setup.main([]) == 0
    out = capsys.readouterr().out
    assert "pointe pair link" in out and ("voice-open",) not in terminal and ("voice-daemon", "ensure") in terminal


def test_bin_pointe_setup_without_a_terminal_still_lists_the_setups(mac):
    got = subprocess.run([str(ROOT / "bin" / "pointe"), "setup"], env={**os.environ, "CLAUDE_VOICE_STATE": mac.env["CLAUDE_VOICE_STATE"]},
                         capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    assert got.returncode == 0 and "Setups (pointe setup <id> to use one)" in got.stdout, got.stderr


def test_setup_codex_starts_the_app_server_and_adds_the_alias_only_on_yes(mac, monkeypatch, capsys):
    (mac.fake / "codex").write_text(f'#!/bin/sh\necho "$@" >> "{mac.home}/codex-calls"\n')
    (mac.fake / "codex").chmod(0o755)
    monkeypatch.setenv("HOME", str(mac.home))
    monkeypatch.setenv("PATH", mac.env["PATH"])
    monkeypatch.setenv("SHELL", "/bin/zsh")
    rc = mac.home / ".zshrc"
    rc.write_text("export EDITOR=vi\n")
    monkeypatch.setattr("builtins.input", lambda q: "n")
    assert terminal_setup.codex() == 0
    assert rc.read_text() == "export EDITOR=vi\n" and terminal_setup.CODEX_ALIAS in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda q: "y")
    assert terminal_setup.codex() == 0
    assert rc.read_text() == f"export EDITOR=vi\n\n{terminal_setup.RC_MARK}\n{terminal_setup.CODEX_ALIAS}\n"
    assert terminal_setup.codex() == 0 and rc.read_text().count("alias codex=") == 1  # a second run adds nothing
    assert (mac.home / "codex-calls").read_text().splitlines() == ["app-server daemon start"] * 3
    assert uninstall._without_alias(rc.read_text()) == "export EDITOR=vi\n"


def test_the_marks_the_uninstaller_looks_for_are_the_ones_written():
    assert terminal_setup.RC_MARK.startswith(uninstall.RC_MARK)
    from harnesses import opencode

    assert uninstall.LINK_MARK in (ROOT / "bin" / "link-pointe").read_text()
    assert uninstall.LINK_MARK in Path(opencode.__file__).read_text()


def test_opencodes_voice_command_runs_the_pointe_command_that_follows_updates(tmp_path, monkeypatch):
    from harnesses import opencode

    monkeypatch.setenv("HOME", str(tmp_path))
    assert opencode.pointe_command() == ROOT / "bin" / "pointe"  # no ~/.local/bin/pointe: this copy
    subprocess.run([str(ROOT / "bin" / "link-pointe"), "--quiet"], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, check=True)
    assert opencode.pointe_command() == tmp_path / ".local" / "bin" / "pointe"


# ---------- the pin and the release ----------

def test_the_installer_pins_a_release_and_pin_rewrites_exactly_those_lines():
    import re

    text = INSTALL.read_text()
    version = re.search(r'^POINTE_VERSION="(\d+\.\d+\.\d+)"', text, re.M)
    digest = re.search(r'^POINTE_SHA256="([0-9a-f]{64})?"', text, re.M)
    assert version and digest
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert [int(x) for x in version[1].split(".")] <= [int(x) for x in manifest.split(".")]
    pinned = release_tarball.pin(text, "3.4.5", "a" * 64)
    assert 'POINTE_VERSION="3.4.5"' in pinned and f'POINTE_SHA256="{"a" * 64}"' in pinned
    assert len(pinned.splitlines()) == len(text.splitlines())
    with pytest.raises(SystemExit):
        release_tarball.pin(text, "3.4.5", "not-a-hash")


# ---------- the Mac app's installer: install.sh, built into Pointe.app ----------

APP_SCRIPT = ROOT / "apps" / "macos" / "PointeMac" / "install.sh"


def test_the_mac_app_bundles_this_install_sh_and_carries_its_sha256():
    """Pointe.app runs install.sh from its own Resources (the synced folder copies the file the link names) only when
    the bytes match the SHA-256 compiled into it: after any change to install.sh, tools/release_tarball.py app."""
    import hashlib
    import re

    assert APP_SCRIPT.is_symlink() and APP_SCRIPT.resolve() == INSTALL.resolve()
    pinned = re.search(r'static let scriptSHA256 = "([0-9a-f]{64})"', release_tarball.APP_INSTALLER.read_text())
    assert pinned and pinned[1] == hashlib.sha256(INSTALL.read_bytes()).hexdigest(), "run python3 tools/release_tarball.py app"


def test_release_tarball_app_writes_the_hash_the_app_checks(tmp_path, monkeypatch):
    import hashlib

    script, swift = tmp_path / "install.sh", tmp_path / "Installer.swift"
    script.write_text("#!/bin/bash\necho a test installer\n")
    swift.write_text(f'    public static let scriptSHA256 = "{"0" * 64}"\n')
    monkeypatch.setattr(release_tarball, "INSTALLER", script)
    monkeypatch.setattr(release_tarball, "APP_INSTALLER", swift)
    assert release_tarball.main(["app"]) == 0
    assert hashlib.sha256(script.read_bytes()).hexdigest() in swift.read_text()


def test_the_mac_app_asks_the_terminal_setups_one_question_word_for_word():
    assert f'freeStart = "{terminal_setup.FREE_START}"' in (ROOT / "apps" / "PointeKit" / "Sources" / "PointeMacKit" / "KeyPlan.swift").read_text()


def test_the_release_tarball_leaves_out_only_what_no_one_runs(releases):
    import tarfile

    names = {n.split("/", 1)[1] for n in tarfile.open(releases["9.9.1"]).getnames() if "/" in n}
    for needed in ("install.sh", "bin/pointe", "bin/pointe-installs", "bin/install-uv", "pointe/daemon.py", "pointe/ui.html", "uv.lock",
                   "pyproject.toml", ".claude-plugin/plugin.json", "hooks/hooks.json", "apps/macos/tools/make_project.py"):
        assert needed in names, needed
    assert not [n for n in names if n.startswith(("bench/", "site/", "evals/"))]
