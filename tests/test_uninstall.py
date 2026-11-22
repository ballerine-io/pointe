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
sys.path.insert(0, str(ROOT))
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
    return subprocess.run([sys.executable, "-I", str(ROOT / "uninstall.py"), *args], env=mac.env, input=answers,
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
    assert '"$ROOT/bin/link-pointe" --quiet' in (ROOT / "bin" / "voice-daemon").read_text()
    assert "~/.local/bin/pointe" in (ROOT / "plugin" / "commands" / "setup.md").read_text()


# ---------- pointe uninstall ----------

def test_dry_run_lists_every_group_and_removes_nothing(mac):
    got = run(mac, "--dry-run")
    assert got.returncode == 0 and "Dry run: nothing removed." in got.stdout
    for expected in (".local/bin/pointe (the pointe command)", ".claude-voice (", "Pointe.app (the Mac app)",
                     "claude plugin uninstall", "Keychain item pointe.gemini-api-key",
                     "Keychain item soniox-api-key (Pointe's name before 1.20.0; another tool may use the same name)",
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
    assert asked == ["Remove Pointe's own files and the plugin?", "Delete Pointe's keys from the Keychain?",
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
