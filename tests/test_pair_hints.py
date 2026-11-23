"""What `pointe pair` says to do next works. QA round 2: after `pointe pair rotate` the printed node step,
`pointe hub invite`, failed "already paired", and `pointe node join` failed "leave studio first"; the restart hint named
`pointe stop` then /pointe:voice although `pointe restart` exists; the revoke hint named ~/.claude-voice whatever the
state dir; `pointe pair --help` named bin/voice-remote."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _nodes(tmp_path, *names):
    (tmp_path / "nodes.json").write_text(json.dumps({"hub_id": "h", "nodes": [
        {"id": f"n{i}", "name": n, "key": "k"} for i, n in enumerate(names)]}))


def test_rotate_gives_each_paired_machine_the_steps_that_work(tmp_path, monkeypatch, capsys):
    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    pair.setup("pointe.example.internal", "127.0.0.1")
    _nodes(tmp_path, "devbox")
    capsys.readouterr()
    pair.rotate()
    out = capsys.readouterr().out
    assert "pointe restart" in out and "pointe stop" not in out
    assert "pointe hub revoke devbox, then pointe hub invite --name devbox" in out
    assert "on devbox, pointe node leave, then pointe node join" in out


def test_a_new_name_that_replaces_the_certificate_says_the_machines_must_pair_again(tmp_path, monkeypatch, capsys):
    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    pair.setup("pointe.example.internal", "127.0.0.1")
    _nodes(tmp_path, "devbox")
    capsys.readouterr()
    pair.setup("pointe.example.internal", "127.0.0.1")  # the same name: the certificate stays, nothing to redo
    assert "devbox" not in capsys.readouterr().out
    pair.setup("other.example.internal", "127.0.0.1")
    assert "devbox must pair again" in capsys.readouterr().out


def test_the_revoke_hint_names_this_state_dir(tmp_path, monkeypatch):
    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    assert pair._home_path(tmp_path / "phone_key") == str(tmp_path / "phone_key").replace(str(Path.home()), "~", 1)
    assert "{_home_path(STATE / 'phone_key')}" in (ROOT / "pair.py").read_text()


def test_pair_help_names_no_old_script(tmp_path):
    got = subprocess.run([sys.executable, "-I", str(ROOT / "pair.py"), "--help"], capture_output=True, text=True,
                         env={"CLAUDE_VOICE_STATE": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=60)
    assert "voice-remote" not in got.stdout
