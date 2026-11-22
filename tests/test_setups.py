"""The setups table (setups.py): each setup runs exactly its own vendors once chosen, each claim's numbers are in the
file it cites, every surface shows the same rows, and no setup is called "best"."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import local  # noqa: E402
import setups  # noqa: E402
import vendors  # noqa: E402

ALL_KEYS = {env: f"synthetic-{vendor}" for vendor, (env, _) in vendors.KEYS.items()}
SWIFT = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeMacKit" / "KeyPlan.swift").read_text()


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in [*vendors.KEY_ENVS, "CLAUDE_VOICE_BRAIN", "CLAUDE_VOICE_READER", "CLAUDE_VOICE_CHECKER", "CLAUDE_VOICE_EARS",
                "CLAUDE_VOICE_MOUTH", "CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_VOICE_LOCAL"]:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", ""))  # no Keychain
    return tmp_path


def _every_key(monkeypatch):
    for env, value in ALL_KEYS.items():
        monkeypatch.setenv(env, value)


def _running(s: vendors.Setup) -> dict:
    return {"brain": s.brain, "reader": s.reader, "checker": s.checker, "ears": s.ears, "mouth": s.mouth}


EXPECTED = {
    "free": {"brain": "gemini:gemini-3.8-flash", "reader": "gemini:gemini-3.8-flash", "checker": "gemini:gemini-3.5-flash-lite",
             "ears": "gemini", "mouth": "gemini:gemini-3.8-flash-lite-tts"},
    "openai": {"brain": "openai:gpt-6-sol", "reader": "openai:gpt-6-sol", "checker": "openai:gpt-5.6-luna", "ears": "openai",
               "mouth": "openai:gpt-4o-mini-tts"},
    "two": {"brain": "anthropic:claude-sonnet-5-5", "reader": "anthropic:claude-sonnet-5-5",
            "checker": "anthropic:claude-haiku-5-5", "ears": "soniox", "mouth": "soniox:tts-rt-v2"},
    "full": {"brain": "anthropic:claude-sonnet-5-5", "reader": "anthropic:claude-sonnet-5-5",
             "checker": "gemini:gemini-3.5-flash-lite", "ears": "soniox", "mouth": "elevenlabs:eleven_v4_turbo"},
}


@pytest.mark.parametrize("setup_id", list(EXPECTED))
def test_a_chosen_setup_runs_exactly_its_vendors_whatever_else_is_saved(state, monkeypatch, setup_id):
    _every_key(monkeypatch)
    setups.choose(setup_id)
    assert _running(vendors.resolve()) == EXPECTED[setup_id]


@pytest.mark.parametrize("setup_id", list(EXPECTED))
def test_a_chosen_setup_runs_on_its_own_keys_alone(state, monkeypatch, setup_id):
    for vendor in setups.BY_ID[setup_id].keys:
        monkeypatch.setenv(vendors.KEYS[vendor][0], "synthetic")
    setups.choose(setup_id)
    assert _running(vendors.resolve()) == EXPECTED[setup_id]


def test_voice_stays_local_uses_the_mac_for_audio_and_only_its_text_vendors(state, monkeypatch):
    _every_key(monkeypatch)
    local.write_voice_config()
    assert vendors.config()["setup"] == "voice-local"
    assert _running(vendors.resolve()) == {"brain": "anthropic:claude-sonnet-5-5", "reader": "anthropic:claude-sonnet-5-5",
                                           "checker": "gemini:gemini-3.5-flash-lite", "ears": vendors.LOCAL,
                                           "mouth": vendors.LOCAL_MOUTH}


def test_fully_local_is_written_as_its_setup_and_off_clears_it(state):
    local.write_config()
    assert vendors.config()["setup"] == "local" and vendors.local_only()
    local.restore_config()
    assert "setup" not in vendors.config()


def test_a_missing_key_of_the_chosen_setup_names_it(state, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic")  # would fill the ears with no setup chosen
    setups.choose("two")
    with pytest.raises(SystemExit, match="the setup Two keys needs its Soniox key"):
        vendors.resolve()
    s = vendors.key_status({"anthropic", "gemini"}, setup=setups.BY_ID["two"])
    assert s["needed"] == ["soniox"] and s["keys"]["gemini"] == "not used" and s["keys"]["openai"] == "optional"
    assert s["line"] == "Setup: Two keys. It needs a Soniox key: pointe key soniox."


def test_choosing_a_setup_replaces_hand_picked_roles_and_local_modes(state):
    (state / "config.json").write_text(json.dumps({"brain": "openai:gpt-6-sol", "voice_local": True, "machine": "desk"}))
    (state / "local").mkdir()
    (state / "local" / "config.before-local.json").write_text("{}")
    assert setups.choose("full") == {"machine": "desk", "setup": "full"}
    assert not (state / "local" / "config.before-local.json").exists()


def test_pointe_setup_lists_the_table_and_switches(state, capsys):
    assert setups.main([]) == 0
    out = capsys.readouterr().out
    assert setups.WHY_KEYS in out and all(s.name in out for s in setups.SETUPS) and "Recommended to start: pointe setup free" in out
    assert setups.main(["two"]) == 0
    out = capsys.readouterr().out
    assert "Setup: Two keys." in out and "pointe key check soniox" in out
    assert setups.main(["best"]) == 2


@pytest.mark.parametrize("s", setups.SETUPS, ids=lambda s: s.id)
def test_what_each_key_does_is_what_the_daemon_runs(s):
    roles = vendors.filled(set(s.keys) | set(s.optional), setup=s)
    got = {}
    for role, vendor in roles.items():
        got.setdefault("this Mac" if vendor == vendors.LOCAL else vendor, []).append(role)
    # the optional key fills the checker when present; the row says what its required keys do
    if s.optional:
        roles = vendors.filled(set(s.keys), setup=s)
        got = {}
        for role, vendor in roles.items():
            got.setdefault("this Mac" if vendor == vendors.LOCAL else vendor, []).append(role)
    assert {k: tuple(v) for k, v in got.items()} == s.does


@pytest.mark.parametrize("s", setups.SETUPS, ids=lambda s: s.id)
def test_every_number_is_in_the_file_it_cites(s):
    """No number made up: each decimal in a claim appears in the file the claim names, and each cost in the cost table."""
    for claim, source in (*s.measured, *s.speed):
        text = (ROOT / source.split(",")[0].strip()).read_text()
        for number in re.findall(r"\d+\.\d+", claim):
            assert number in text, f"{s.id}: {number} is not in {source}"
    costs = (ROOT / "docs" / "benchmarks.md").read_text()
    for number in re.findall(r"\d+\.\d+", s.cost):
        assert number in costs, f"{s.id}: ${number} is not in docs/benchmarks.md"


def test_no_setup_is_called_best_and_the_brain_tie_is_said():
    for s in setups.SETUPS:
        assert "best" not in s.name.lower()
    page = (ROOT / "docs" / "setups.md").read_text()
    assert "within the margin" in page and "No setup is best on every axis" in page


def test_the_written_tables_are_current():
    spec = importlib.util.spec_from_file_location("setups_tool", ROOT / "tools" / "setups.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.main(["--check"]) == 0, "run python3 tools/setups.py"
    for path in ("README.md", "plugin/commands/setup.md"):
        assert setups.table(full=False) in (ROOT / path).read_text()


def test_the_mac_apps_setup_menu_is_this_table():
    rows = re.findall(r'SetupChoice\(id: "([\w-]+)", name: "([^"]+)", keys: \[([^\]]*)\], optional: \[([^\]]*)\], '
                      r'local: "(\w*)", short: "([^"]+)", pickFor: "([^"]+)"\)', SWIFT)
    vendors_of = lambda text: tuple(v.strip().lstrip(".") for v in text.split(",") if v.strip())  # noqa: E731
    assert [(i, n, vendors_of(k), vendors_of(o), lo, sh, p) for i, n, k, o, lo, sh, p in rows] == \
        [(s.id, s.name, s.keys, s.optional, s.local, s.short, s.pick_for) for s in setups.SETUPS]


def test_the_page_lists_the_setups_from_the_daemon():
    page = (ROOT / "ui.html").read_text()
    assert "k.setups" in page and "pointe setup " in page and 'id="pref-setups"' in page


def test_setup_asks_one_question_and_only_the_chosen_keys():
    text = " ".join((ROOT / "plugin" / "commands" / "setup.md").read_text().split())
    assert 'Ask one question: "Which setup?"' in text and "pointe key check <vendor>" in text
    assert "ask only for the keys that setup needs" in text and setups.WHY_KEYS in text
