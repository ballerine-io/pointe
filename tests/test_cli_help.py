"""`pointe <command> --help` says what the command does and runs nothing. From QA round 2: `pointe local --help` started
the 19 GB fully local install and switched the setup, `pointe stop --help` ended the call, `open --help` opened the page."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import local  # noqa: E402

COMMANDS = ["start", "attach", "open", "talk", "doctor", "status", "log", "context", "stop", "restart", "uninstall",
            "hub", "people", "share", "machine", "machines", "agent", "agents", "key", "setup", "join", "leave", "local", "apps"]


@pytest.fixture
def pointe(tmp_path):
    """bin/pointe beside scripts that only write down that they ran, and a uv that does the same."""
    bin_ = tmp_path / "plugin" / "bin"
    bin_.mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "pointe", bin_ / "pointe")
    calls = tmp_path / "calls"
    recorder = f'#!/bin/bash\necho "$(basename "$0") $*" >> {calls}\nexit 0\n'
    fake = tmp_path / "fake"
    fake.mkdir()
    for name in [p.name for p in (ROOT / "bin").iterdir() if p.name != "pointe"]:
        (bin_ / name).write_text(recorder)
    (fake / "uv").write_text(recorder)
    (fake / "python3").write_text(recorder)
    for f in (*bin_.iterdir(), *fake.iterdir()):
        f.chmod(0o755)
    env = {"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return bin_ / "pointe", calls, env


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_on_a_command_says_what_it_does_and_runs_nothing(pointe, command, flag):
    script, calls, env = pointe
    got = subprocess.run([str(script), command, flag], env=env, capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    assert got.stdout.startswith(f"pointe {command}"), got.stdout
    assert not calls.exists(), calls.read_text()


def test_help_after_a_subcommand_runs_nothing_either(pointe):
    script, calls, env = pointe
    got = subprocess.run([str(script), "local", "voice", "--help"], env=env, capture_output=True, text=True)
    assert got.returncode == 0 and "19 GB" in got.stdout and not calls.exists()


def test_pair_and_node_still_read_their_own_help(pointe):
    script, calls, env = pointe
    subprocess.run([str(script), "pair", "--help"], env=env, capture_output=True, text=True)
    assert "pair.py --help" in calls.read_text()


def test_local_py_never_installs_on_a_flag(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(local, "install", lambda *a: ran.append(a) or 0)
    assert local.main(["--help"]) == 0 and local.main(["-h"]) == 0
    assert local.main(["--yes"]) == 2
    assert not ran and "pointe local status" in capsys.readouterr().out


def _people_subcommands() -> set[str]:
    """Every word `pointe people <word>` acts on, read from guests._people: the commands it compares against and the
    settings words. A new subcommand without a line in bin/pointe's help fails here."""
    import inspect
    import re

    import guests

    said = set(re.findall(r'command == "([a-z]+)"', inspect.getsource(guests._people)))
    return (said | set(guests._SETTING_WORDS)) - {"list"}  # bare `pointe people` lists


def test_people_help_lists_every_people_subcommand_the_cli_accepts(pointe):
    script, calls, env = pointe
    got = subprocess.run([str(script), "people", "--help"], env=env, capture_output=True, text=True)
    subcommands = _people_subcommands()
    assert {"invite", "grant", "remove", "approvals", "starts", "sessions", "window", "hold"} <= subcommands
    missing = sorted(w for w in subcommands if f"people {w} " not in got.stdout)
    assert not missing, got.stdout


def test_uninstall_counts_the_hooks_the_plugin_adds():
    """The plugin's hooks are what hooks/hooks.json registers; uninstall said "two hooks" when it added four."""
    import json
    import re

    import uninstall

    count = sum(len(group["hooks"]) for groups in json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"].values()
                for group in groups)
    word = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}[count]
    assert f"its {word} hooks" in uninstall.PLUGIN_BY_HAND
    assert set(re.findall(r"its (\w+) hooks", (ROOT / "pointe" / "uninstall.py").read_text())) == {word}


@pytest.mark.parametrize("grant", __import__("nodelink").GRANTS)
def test_people_grant_says_the_grant_it_set(grant, monkeypatch, capsys):
    """`pointe people grant NAME mine` was accepted and printed "may now watch only": each grant in nodelink.GRANTS has
    its own line, and no other grant's."""
    import guests
    import hub_nodes

    posted = []
    monkeypatch.setattr(hub_nodes, "_daemon", lambda method, path, body=None: posted.append((path, body)) or {"ok": True})
    guests._people(["grant", "Dana", grant])
    said = capsys.readouterr().out
    assert posted == [("/voice/people/grant", {"name": "Dana", "grant": grant})]
    assert said.strip() == guests.GRANT_SAID[grant].format(name="Dana")
    assert set(guests.GRANT_SAID) == set(guests.GRANTS) and len(set(guests.GRANT_SAID.values())) == len(guests.GRANTS)


def test_people_help_offers_every_grant(pointe):
    import guests
    import nodelink

    script, calls, env = pointe
    got = subprocess.run([str(script), "people", "--help"], env=env, capture_output=True, text=True)
    grants = "|".join(nodelink.GRANTS)
    assert f"people grant NAME {grants} " in got.stdout, got.stdout
    assert f"pointe people grant <name> {grants} " in guests.__doc__
