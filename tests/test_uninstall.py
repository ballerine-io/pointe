"""`pointe` on the PATH, and `pointe uninstall` removing what Pointe added: each group listed first and asked for, keys
only on their own yes, and nothing another tool may share without a separate yes. Every run here has a throwaway HOME,
fake `security` and `claude` commands and a state dir of its own: the real Keychain, ~/.claude-voice and the live daemon
are never reached."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import uninstall  # noqa: E402
import vendors  # noqa: E402

LINK = ROOT / "bin" / "link-pointe"


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """A HOME with what an install and a few calls leave, and a Keychain held in a folder."""
    home = tmp_path / "home"
    fake = tmp_path / "fakebin"
    fake.mkdir()
    keychain = tmp_path / "keychain"
    keychain.mkdir()
    (fake / "security").write_text(f"""#!/bin/sh
case "$1" in
  find-generic-password) [ -f "{keychain}/$3" ] ;;
  delete-generic-password) rm "{keychain}/$3" ;;
  *) exit 2 ;;
esac
""")
    (fake / "claude").write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/claude-calls"\n')
    for f in fake.iterdir():
        f.chmod(0o755)
    state = home / ".claude-voice"
    (state / "bin").mkdir(parents=True)
    (state / "journal.jsonl").write_text("{}\n")
    (home / "Applications" / "Pointe.app").mkdir(parents=True)
    hub = home / ".cache" / "huggingface" / "hub" / "models--mlx-community--whisper-large-v3-turbo"
    hub.mkdir(parents=True)
    for name in ("pointe.gemini-api-key", "soniox-api-key"):
        (keychain / name).write_text("")
    env = {"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin", "CLAUDE_VOICE_STATE": str(state),
           "CLAUDE_VOICE_DAEMON_PORT": "7987"}
    subprocess.run([str(LINK), "--quiet"], env=env, check=True)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    return type("Mac", (), {"home": home, "state": state, "keychain": keychain, "hub": hub, "env": env,
                            "claude": lambda: (tmp_path / "claude-calls").read_text() if (tmp_path / "claude-calls").exists() else ""})


def run(mac, *args, answers=""):
    return subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "uninstall.py"), *args], env=mac.env, input=answers,
                          capture_output=True, text=True, timeout=60)


# ---------- pointe on the PATH ----------

def test_link_pointe_writes_a_script_that_runs_this_copy_and_says_so(tmp_path):
    home = tmp_path / "home"
    got = subprocess.run([str(LINK)], env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    link = home / ".local" / "bin" / "pointe"
    assert got.returncode == 0 and f"pointe is a command now: {link}" in got.stdout
    assert "not on this terminal's PATH yet" in got.stdout
    assert not link.is_symlink() and f"exec {ROOT / 'bin' / 'pointe'}" in link.read_text()
    out = subprocess.run([str(link), "help"], env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert out.returncode == 0 and "pointe key <vendor>" in out.stdout and "uninstall" in out.stdout


def test_link_pointe_leaves_a_pointe_it_did_not_write(tmp_path):
    link = tmp_path / "home" / ".local" / "bin" / "pointe"
    link.parent.mkdir(parents=True)
    link.write_text("#!/bin/sh\necho someone else's\n")
    got = subprocess.run([str(LINK)], env={"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert got.returncode == 0 and "is not Pointe's: left as it is" in got.stdout
    assert link.read_text() == "#!/bin/sh\necho someone else's\n"


def test_setup_and_each_start_link_pointe():
    install_uv = (ROOT / "bin" / "install-uv").read_text()
    assert install_uv.count('exec "$(dirname "${BASH_SOURCE[0]}")/link-pointe"') == 2, "both when uv is there and after installing it"
    assert '"$ROOT/bin/link-pointe" --at-start' in (ROOT / "bin" / "voice-daemon").read_text()
    assert "~/.local/bin/pointe" in (ROOT / "plugin" / "commands" / "setup.md").read_text()


# ---------- pointe uninstall ----------

def test_dry_run_lists_every_group_and_removes_nothing(mac):
    got = run(mac, "--dry-run")
    assert got.returncode == 0 and "Dry run: nothing removed." in got.stdout
    for expected in (".local/bin/pointe (the pointe command)", ".claude-voice (", "Pointe.app (the Mac app)",
                     "claude plugin uninstall", "Keychain item pointe.gemini-api-key",
                     "Keychain item soniox-api-key (the name pre-release builds of Pointe used; another tool may use the same name)",
                     "models--mlx-community--whisper-large-v3-turbo", "Kept: uv"):
        assert expected in got.stdout, expected
    assert mac.state.exists() and (mac.keychain / "pointe.gemini-api-key").exists() and not mac.claude()


def test_without_a_terminal_it_asks_for_yes_and_removes_nothing(mac):
    got = run(mac)
    assert got.returncode == 1 and "Nothing removed" in got.stdout and mac.state.exists()


def test_yes_removes_pointes_own_files_and_the_plugin_but_never_a_key(mac):
    got = run(mac, "--yes")
    assert got.returncode == 0, got.stdout + got.stderr
    assert not mac.state.exists() and not (mac.home / "Applications" / "Pointe.app").exists()
    assert not (mac.home / ".local" / "bin" / "pointe").exists()
    assert mac.claude() == "plugin uninstall pointe@pointe\nplugin marketplace remove pointe\n"
    assert (mac.keychain / "pointe.gemini-api-key").exists(), "a key goes only on its own yes"
    assert (mac.keychain / "soniox-api-key").exists() and mac.hub.exists(), "what another tool may share stays"
    done = [line for line in got.stdout.splitlines() if line.startswith("  done")]
    assert "plugin" in done[-1] and "Stop Pointe" in done[0], "stop first, the plugin (this code) last"


def test_delete_keys_removes_only_pointes_own_items(mac):
    got = run(mac, "--yes", "--delete-keys")
    assert got.returncode == 0
    assert not (mac.keychain / "pointe.gemini-api-key").exists() and (mac.keychain / "soniox-api-key").exists()


def test_each_group_has_its_own_question(mac, monkeypatch):
    """In a terminal: one answer per group, and a no keeps that group."""
    asked = []
    answers = iter(["y", "n", "y"])
    monkeypatch.setattr(uninstall.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(uninstall, "_ask", lambda q: asked.append(q) or next(answers) == "y")
    assert uninstall.main([]) == 0
    assert asked == ["Remove Pointe's own files, the plugin and the standalone install?", "Delete Pointe's keys from the Keychain?",
                     "Also remove the shared items listed above?"]
    assert (mac.keychain / "pointe.gemini-api-key").exists() and not (mac.keychain / "soniox-api-key").exists()
    assert not mac.hub.exists() and not mac.state.exists()


def test_the_lists_follow_their_sources():
    assert uninstall.KEY_VENDORS == tuple(vendors.KEYS)
    assert uninstall._hf_models() == list(__import__("assets").HF_MODELS)
    assert uninstall.LINK_MARK in LINK.read_text()


def test_the_install_docs_and_the_readme_say_what_it_does_to_your_mac():
    for doc in ("README.md", "docs/install.md"):
        text = (ROOT / doc).read_text()
        box = text[text.index("What this does to your Mac"):][:2500]
        for fact in ("~/.local/bin/pointe", "PermissionRequest", "SessionStart", "127.0.0.1:7860", "/pointe:stop",
                     "caffeinate", "Keychain", "pointe uninstall", "~/.claude-voice", "nothing to Ballerine"):
            assert fact in box, (doc, fact)
        assert re.search(r"pointe\.<vendor>-api-key|pointe\.gemini-api-key", box), doc


def test_the_install_docs_describe_the_pointe_script_and_the_uv_paths_as_they_are(tmp_path, mac):
    home = tmp_path / "linkhome"
    subprocess.run([str(LINK)], env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    lines = len((home / ".local" / "bin" / "pointe").read_text().splitlines())
    install = " ".join((ROOT / "docs" / "install.md").read_text().split())
    assert f"a {['zero', 'one', 'two', 'three', 'four'][lines]}-line script" in install
    hint = next(line for line in run(mac, "--dry-run").stdout.splitlines() if line.startswith("Kept: uv"))
    for path in ("~/.local/bin/uv", "~/.local/bin/uvx", "~/.local/share/uv"):
        assert path in hint and path in install, path


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="macOS's own python3")
def test_uninstall_runs_on_the_python_macos_ships(mac):
    """bin/pointe runs it with the python3 on the PATH, which on a new Mac is Apple's 3.9: the clean-install run found
    `Path | None` failing there at import."""
    got = subprocess.run(["/usr/bin/python3", "-I", str(ROOT / "pointe" / "uninstall.py"), "--dry-run"], env=mac.env,
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0 and "Dry run: nothing removed." in got.stdout, got.stderr


def _linked_to(home: Path) -> str:
    return (home / ".local" / "bin" / "pointe").read_text()


def test_a_start_from_a_checkout_leaves_a_working_pointe_command_alone(tmp_path):
    """A daemon started from a clone or a worktree used to take ~/.local/bin/pointe over; once that checkout was deleted
    every `pointe`, uninstall included, failed with rc 126."""
    home = tmp_path / "home"
    plugin = tmp_path / "home" / ".claude" / "plugins" / "cache" / "pointe" / "pointe" / "1.20.0" / "bin"
    plugin.mkdir(parents=True)
    for name in ("link-pointe", "pointe"):
        (plugin / name).write_text((ROOT / "bin" / name).read_text())
        (plugin / name).chmod(0o755)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    subprocess.run([str(plugin / "link-pointe"), "--at-start"], env=env, check=True)
    assert f"exec {plugin / 'pointe'}" in _linked_to(home)
    subprocess.run([str(LINK), "--at-start"], env=env, check=True)  # this checkout's daemon starts
    assert f"exec {plugin / 'pointe'}" in _linked_to(home)


def test_a_checkout_repairs_a_pointe_command_whose_copy_is_gone(tmp_path):
    home = tmp_path / "home"
    gone = tmp_path / "deleted-worktree" / "bin"
    gone.mkdir(parents=True)
    (gone / "link-pointe").write_text(LINK.read_text())
    (gone / "link-pointe").chmod(0o755)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    subprocess.run([str(gone / "link-pointe"), "--quiet"], env=env, check=True)
    subprocess.run(["rm", "-rf", str(gone.parent)], check=True)
    subprocess.run([str(LINK), "--at-start"], env=env, check=True)
    assert f"exec {ROOT / 'bin' / 'pointe'}" in _linked_to(home)


def test_keeping_pointes_own_files_is_not_called_removed(mac, monkeypatch, capsys):
    answers = iter(["n", "y", "n"])
    monkeypatch.setattr(uninstall.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(uninstall, "_ask", lambda q: next(answers) == "y")
    assert uninstall.main([]) == 0
    out = capsys.readouterr().out
    assert "Pointe is removed." not in out and "Pointe itself is still installed" in out
    assert mac.state.exists() and not (mac.keychain / "pointe.gemini-api-key").exists()


def test_the_mac_apps_settings_are_listed_and_removed_through_defaults(mac, capsys):
    prefs = mac.home / "Library" / "Preferences" / f"{uninstall.MAC_APP_ID}.plist"
    prefs.parent.mkdir(parents=True)
    prefs.write_text("<plist/>")
    fake = Path(mac.env["PATH"].split(":")[0])
    (fake / "defaults").write_text(f'#!/bin/sh\necho "$@" >> "{fake}/defaults-calls"\n')
    (fake / "defaults").chmod(0o755)
    assert run(mac, "--dry-run").stdout.count(f"{prefs} (the Mac app's settings)") == 1
    assert run(mac, "--yes").returncode == 0
    assert (fake / "defaults-calls").read_text() == f"delete {uninstall.MAC_APP_ID}\n"
    assert uninstall.MAC_APP_ID in (ROOT / "apps" / "macos" / "tools" / "make_project.py").read_text()


def test_the_disk_images_app_in_applications_is_removed_and_another_pointe_app_is_not(mac, tmp_path):
    apps = tmp_path / "Applications"
    ours, theirs = apps / "Pointe.app" / "Contents", tmp_path / "other" / "Pointe.app" / "Contents"
    for folder, bundle in ((ours, uninstall.MAC_APP_ID), (theirs, "com.example.pointe")):
        folder.mkdir(parents=True)
        (folder / "Info.plist").write_bytes(__import__("plistlib").dumps({"CFBundleIdentifier": bundle}))
    out = subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "uninstall.py"), "--yes"], capture_output=True, text=True,
                         env={**mac.env, "POINTE_SYSTEM_APPLICATIONS": str(apps)}, timeout=60)
    assert f"{apps / 'Pointe.app'} (the Mac app, from Pointe.dmg)" in out.stdout and not (apps / "Pointe.app").exists()
    out = subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "uninstall.py"), "--dry-run"], capture_output=True, text=True,
                         env={**mac.env, "POINTE_SYSTEM_APPLICATIONS": str(theirs.parent.parent)}, timeout=60)
    assert "Pointe.dmg" not in out.stdout and theirs.exists()


def test_a_throwaway_home_never_reaches_the_real_applications_folder(mac):
    """mac.env names a HOME that is not this account's: /Applications is left out, whatever is there."""
    assert "POINTE_SYSTEM_APPLICATIONS" not in mac.env
    got = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(ROOT / 'pointe')!r}); import uninstall; "
                          "print(uninstall.system_apps())"], env=mac.env, capture_output=True, text=True, timeout=30)
    assert got.stdout.strip() == "None"


def test_the_uv_hint_names_every_folder_uv_installs():
    assert "~/.local/share/uv" in (ROOT / "pointe" / "uninstall.py").read_text().split("Kept: uv", 1)[1][:200]


def test_without_a_claude_command_the_plugin_is_never_called_removed(mac):
    """QA round 2: with claude not on the PATH (a desktop-app install, or an alias), "Pointe is removed." was said while
    the plugin, its 530 MB Python and both hooks stayed."""
    (mac.home / ".claude" / "plugins" / "cache" / "pointe").mkdir(parents=True)
    env = {**mac.env, "PATH": f"{Path(mac.env['PATH'].split(':')[0])}-none:/usr/bin:/bin"}
    (Path(mac.env["PATH"].split(":")[0]) / "claude").unlink()
    got = subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "uninstall.py"), "--yes"], env=env, capture_output=True,
                         text=True, timeout=60)
    assert "Pointe is removed." not in got.stdout
    assert "/plugin uninstall pointe@pointe" in got.stdout and got.stdout.count("still installed") == 2


def test_a_claude_installed_where_claude_codes_installer_puts_it_is_used(mac):
    fake = Path(mac.env["PATH"].split(":")[0])
    local = mac.home / ".claude" / "local"
    local.mkdir(parents=True)
    (fake / "claude").rename(local / "claude")
    got = run(mac, "--yes")
    assert got.returncode == 0 and "Pointe is removed." in got.stdout
    assert mac.claude() == "plugin uninstall pointe@pointe\nplugin marketplace remove pointe\n"


def test_the_install_doc_counts_the_lines_link_pointe_writes(tmp_path):
    subprocess.run([str(LINK), "--quiet"], env={"POINTE_LINK_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}, check=True)
    lines = len((tmp_path / "pointe").read_text().splitlines())
    word = {2: "two", 3: "three", 4: "four"}[lines]
    assert f"`~/.local/bin/pointe`, a {word}-line script" in (ROOT / "docs" / "install.md").read_text()
