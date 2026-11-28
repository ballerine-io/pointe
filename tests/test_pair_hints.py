"""What `pointe pair` says to do next works. QA round 2: after `pointe pair rotate` the printed node step,
`pointe hub invite`, failed "already paired", and `pointe node join` failed "leave studio first"; the restart hint named
`pointe stop` then /pointe:voice although `pointe restart` exists; the revoke hint named ~/.claude-voice whatever the
state dir; `pointe pair --help` named bin/voice-remote."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]


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
    # rotate signs every machine out here at once and a running daemon follows within seconds (Mythos review NP-5):
    # no restart, and no revoke step left for this side
    assert "signed out now" in out and "pointe stop" not in out and "pointe restart" not in out
    assert "here, pointe hub invite --name devbox;" in out and "pointe hub revoke" not in out
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
    assert "{_home_path(STATE / 'phone_key')}" in (ROOT / "pointe" / "pair.py").read_text()


def test_pair_help_names_no_old_script(tmp_path):
    got = subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "pair.py"), "--help"], capture_output=True, text=True,
                         env={"CLAUDE_VOICE_STATE": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=60)
    assert "voice-remote" not in got.stdout


def test_rotate_signs_people_out_and_keeps_the_owners_settings_for_people(tmp_path, monkeypatch):
    """Docs sweep: _sign_everyone_out wrote people.json without its "settings", so "approvals off" (and every other
    setting) went back to its default after `pointe pair rotate`. People go; the owner's choices stay."""
    import guests
    import pair

    monkeypatch.setattr(pair, "STATE", tmp_path)
    pair.setup("pointe.example.internal", "127.0.0.1")
    chosen = {"approve": "off", "start": "off", "sessions_ask": "ask", "owner_first_secs": 5.0, "people_hold_secs": 90.0}
    (tmp_path / "people.json").write_text(json.dumps({
        "people": {"p1": {"id": "p1", "name": "Dana", "key": "k", "grant": "send"}}, "private": ["ledger"],
        "settings": chosen}))
    pair.rotate()
    after = guests.People(tmp_path / "people.json")
    assert after.people == {} and after.private == {"ledger"}
    assert guests.settings_of(after.settings) == chosen
