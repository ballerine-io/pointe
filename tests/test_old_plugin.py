"""An older Pointe plugin for Claude Code next to a newer Pointe: found from any marketplace, named with the exact commands
that update or remove it (bin/pointe-installs advise, printed by install.sh and pointe doctor), and the attach script
that meets a status it cannot read says so in words instead of a traceback. Field report: plugin 0.1.6 from an old
"ballerine" marketplace beside the 0.8.7 standalone daemon; its /pointe:voice crashed on the daemon's 403."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
INSTALLS = ROOT / "bin" / "pointe-installs"


def copy_of(root: Path, version: str, standalone: bool = False) -> Path:
    """A folder that looks like an installed Pointe of `version`: its manifest and an executable voice-daemon."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "pointe", "version": version}, indent=2))
    (root / "bin").mkdir()
    (root / "bin" / "voice-daemon").write_text("#!/bin/sh\n")
    (root / "bin" / "voice-daemon").chmod(0o755)
    if standalone:
        (root / ".pointe-install").write_text(f"standalone {version} sha256 x\n")
    return root


def home_with(tmp_path: Path, plugins: dict[str, str], standalone: str = "0.8.7", record: bool = True) -> dict:
    """HOME with a standalone install and Claude Code plugins {marketplace: version}, recorded as Claude Code does."""
    home = tmp_path / "home"
    copy_of(home / ".pointe" / standalone, standalone, standalone=True)
    recorded = {}
    for market, version in plugins.items():
        root = copy_of(home / ".claude" / "plugins" / "cache" / market / "pointe" / version, version)
        recorded[f"pointe@{market}"] = [{"scope": "user", "installPath": str(root), "version": version}]
    if record:
        (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
        (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": recorded}, indent=2))
    return {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def run(env: dict, *args: str) -> str:
    got = subprocess.run([str(INSTALLS), *args], env=env, capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return got.stdout


def test_an_old_plugin_from_another_marketplace_is_found_and_named_with_how_to_remove_it(tmp_path):
    env = home_with(tmp_path, {"ballerine": "0.1.6"})
    stale = run(env, "stale").splitlines()
    assert len(stale) == 1 and stale[0].split("\t")[:2] == ["ballerine", "0.1.6"]
    advice = run(env, "advise")
    assert "0.1.6" in advice and '"ballerine"' in advice and "0.8.7" in advice
    assert "claude plugin uninstall pointe@ballerine" in advice
    assert "claude plugin install pointe@pointe" in advice


def test_an_old_plugin_only_in_the_cache_is_found_too(tmp_path):
    env = home_with(tmp_path, {"ballerine": "0.1.6"}, record=False)
    assert "pointe@ballerine" in run(env, "advise")


def test_an_older_plugin_from_pointes_own_marketplace_is_told_to_update(tmp_path):
    env = home_with(tmp_path, {"pointe": "0.8.1"})
    advice = run(env, "advise")
    assert "claude plugin update pointe@pointe" in advice and "uninstall" not in advice


def test_a_current_or_newer_plugin_and_an_orphaned_copy_say_nothing(tmp_path):
    env = home_with(tmp_path, {"pointe": "0.8.7"})
    orphan = copy_of(Path(env["HOME"]) / ".claude" / "plugins" / "cache" / "ballerine" / "pointe" / "0.1.5", "0.1.5")
    (orphan / ".orphaned_at").write_text("1")
    assert run(env, "stale") == "" and run(env, "advise") == ""


def test_pointe_doctor_prints_the_advice(tmp_path, monkeypatch):
    import doctor

    env = home_with(tmp_path, {"ballerine": "0.1.6"})
    monkeypatch.setenv("HOME", env["HOME"])
    monkeypatch.delenv("POINTE_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    lines = "\n".join(doctor.install_lines())
    assert "claude plugin uninstall pointe@ballerine" in lines


def test_install_sh_prints_the_advice_after_it_installs():
    text = (ROOT / "install.sh").read_text()
    assert '"$DEST/$INSTALLS" advise' in text


# ---------- the attach script meets a status it cannot read ----------

def attach_with(tmp_path: Path, status_answer: str) -> subprocess.CompletedProcess:
    """bin/claude-voice-attach in a folder of its own, beside fakes of the scripts it calls, with a fake curl whose
    /voice/status answers as `status_answer` says: "403" (curl -f prints nothing and fails), or a body."""
    bin_dir, fake = tmp_path / "bin", tmp_path / "fakebin"
    bin_dir.mkdir()
    fake.mkdir()
    shutil.copy(ROOT / "bin" / "claude-voice-attach", bin_dir)
    scripts = {"voice-daemon": "echo http://127.0.0.1:7999", "register-session": 'echo \'{"name": "shop", "active": true}\'',
               "voice-ours": "exit 0", "voice-open": f"touch {tmp_path / 'opened'}"}
    for name, body in scripts.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    answer = "exit 22" if status_answer == "403" else f"printf '%s' '{status_answer}'"
    (fake / "curl").write_text(f"#!/bin/sh\n{answer}\n")
    (fake / "curl").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    (state / "token").write_text("t")
    env = {"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_VOICE_STATE": str(state),
           "CLAUDE_CODE_SESSION_ID": "abc", "CLAUDE_CODE_MESSAGING_SOCKET": str(tmp_path / "sock"), "LANG": "C.UTF-8"}
    return subprocess.run([str(bin_dir / "claude-voice-attach")], env=env, capture_output=True, text=True, timeout=30)


def test_a_refused_status_is_said_in_words_and_the_page_still_opens(tmp_path):
    got = attach_with(tmp_path, "403")
    assert got.returncode == 0, got.stderr
    assert "Traceback" not in got.stderr and "JSONDecodeError" not in got.stderr
    assert "did not say whether a call is up" in got.stderr and "pointe doctor" in got.stderr
    assert (tmp_path / "opened").exists() and "this session joined Pointe" in got.stdout


def test_a_status_that_is_not_json_is_said_in_words_too(tmp_path):
    got = attach_with(tmp_path, "<html>Forbidden</html>")
    assert got.returncode == 0 and "Traceback" not in got.stderr and "did not say" in got.stderr


def test_a_call_already_up_keeps_the_page_closed_and_says_nothing(tmp_path):
    got = attach_with(tmp_path, '{"connected": true}')
    assert got.returncode == 0 and got.stderr == "" and not (tmp_path / "opened").exists()
    assert os.path.exists(tmp_path / "state" / "token")
