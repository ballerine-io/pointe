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
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import local  # noqa: E402
import setups  # noqa: E402
import vendors  # noqa: E402

ALL_KEYS = {env: f"synthetic-{vendor}" for vendor, (env, _) in vendors.KEYS.items()}
SWIFT = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeMacKit" / "KeyPlan.swift").read_text()


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
    assert "Setup: Two keys." in out and "pointe key soniox opens the key page" in out and "pointe restart" in out
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


def test_a_voice_start_time_from_the_voice_benchmark_says_it_is_the_voice_alone():
    """tts_bench times the voice by itself: 213 ms. In a call the voice's first audio waits on the network and the
    machine, and came later, so the table may not read as if a caller hears it that soon."""
    timed = [(s.id, claim) for s in setups.SETUPS for claim, source in s.speed if "mouth table" in source]
    assert timed
    for setup_id, claim in timed:
        assert "voice benchmark" in claim and "the voice alone, not a call" in claim, f"{setup_id}: {claim}"


def test_no_setup_is_called_best_and_the_brain_tie_is_said():
    for s in setups.SETUPS:
        assert "best" not in s.name.lower()
    page = (ROOT / "docs" / "setups.md").read_text()
    assert "within the margin" in page and "No setup is best on every axis" in page


def test_the_written_tables_are_current():
    spec = importlib.util.spec_from_file_location("setups_tool", ROOT / "tools" / "write_setups.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.main(["--check"]) == 0, "run python3 tools/write_setups.py"
    for path in ("plugin/commands/setup.md",):
        assert setups.table(full=False) in (ROOT / path).read_text()


def test_the_mac_apps_setup_menu_is_this_table():
    rows = re.findall(r'SetupChoice\(id: "([\w-]+)", name: "([^"]+)", keys: \[([^\]]*)\], optional: \[([^\]]*)\], '
                      r'local: "(\w*)", short: "([^"]+)", pickFor: "([^"]+)"\)', SWIFT)
    vendors_of = lambda text: tuple(v.strip().lstrip(".") for v in text.split(",") if v.strip())  # noqa: E731
    assert [(i, n, vendors_of(k), vendors_of(o), lo, sh, p) for i, n, k, o, lo, sh, p in rows] == \
        [(s.id, s.name, s.keys, s.optional, s.local, s.short, s.pick_for) for s in setups.SETUPS]


def test_the_openai_setup_says_its_ears_take_english_only():
    """OpenAI's realtime ears misheard mixed Hebrew and English ("The speedlyvavakasha, ...") with or without a language
    set, where Soniox's took both. The page, the apps and the docs must say so before someone picks it."""
    s = setups.BY_ID["openai"]
    assert "English speech only" in s.short and "English speech only" in s.needs
    assert "Needs headphones; English speech only" in setups.table()


def test_the_local_setups_disk_figures_count_the_libraries_too():
    """`pointe setup voice-local` installs the local libraries (bin/pointe: 1.1 GB on disk) and then 2.0 GB of models."""
    install = " ".join((ROOT / "docs" / "install.md").read_text().split())
    libs = float(re.search(r"the libraries below are ([\d.]+) GB on disk", (ROOT / "bin" / "pointe").read_text())[1])
    voice = float(re.search(r'"Voice stays on your Mac" adds ([\d.]+) GB of models', install)[1])
    full = float(re.search(r'"Fully local" adds ([\d.]+) GB, and a ([\d.]+) GB text-model server', install)[1])
    server = float(re.search(r'"Fully local" adds [\d.]+ GB, and a ([\d.]+) GB text-model server', install)[1])
    want = f"about {round(libs + voice)} GB of disk"
    assert want in setups.BY_ID["voice-local"].needs
    assert want in " ".join((ROOT / "docs" / "features" / "voice-stays-local.md").read_text().split())
    assert f"| Voice stays on your Mac | an Apple-silicon Mac, {want}," in install
    assert f"about {round(libs + full + server)} GB of disk" in setups.BY_ID["local"].needs


def test_the_page_lists_the_setups_from_the_daemon():
    page = (ROOT / "pointe" / "ui.html").read_text()
    assert "k.setups" in page and "pointe setup " in page and 'id="pref-setups"' in page


def test_setup_asks_one_yes_or_no_and_shows_the_setups_only_when_asked():
    """The onboarding review: about 400 words and a six-row table came before the first action. Now one short paragraph,
    one question with Free start first, the table behind "Show me the other setups", and four steps before the extras."""
    text = " ".join((ROOT / "plugin" / "commands" / "setup.md").read_text().split())
    assert 'ask one question, "Start with Free start?"' in text
    assert '"Yes, Free start (recommended)", "Show me the other setups", "I already have keys"' in text
    said = text[text.index("Otherwise say this, word for word: ") + 35:text.index(" Then ask one question")]
    assert len(said.split()) < 60 and "Free start" in said and "not confidential" in said
    details = text[text.index("<details><summary>The six setups: only when they ask</summary>"):text.index("</details>")]
    assert setups.table(full=False).split("\n")[2] in details, "the table is behind the question"
    assert text.index("<details>") > text.index("Start with Free start?")
    for n, name in enumerate(("this Mac", "your setup", "your key", "your first call"), 1):
        assert f"Step {n} of 4: {name}." in text
    assert "Step 5" not in text and "of 7" not in text
    assert setups.DEFAULT == "free"


def test_the_doctor_step_reads_back_the_verdict_not_the_first_line():
    """bin/voice-doctor prints "ok uv", the node line and, on a first run, about 40 lines of download before the
    doctor's verdict, so "its first line" read back "ok uv"."""
    import doctor
    text = " ".join((ROOT / "plugin" / "commands" / "setup.md").read_text().split())
    step = text[text.index("Step 2 of 4"):text.index("Step 3 of 4")]
    assert "first line" not in step
    ready = doctor.verdict(0, {"needed": [], "fix": None}, None, [])[0]
    not_ready = doctor.verdict(1, {"needed": ["gemini"], "fix": "gemini"}, None, [])
    assert ready.startswith("Pointe is ready") and not_ready[0].startswith("Pointe is not ready")
    assert not_ready[1].startswith("Fix:")
    assert '"Pointe is ready" or "Pointe is not ready"' in step and '"Fix:"' in step


def test_the_key_step_is_one_command_that_opens_checks_asks_again_and_restarts():
    text = " ".join((ROOT / "plugin" / "commands" / "setup.md").read_text().split())
    step = text[text.index("Step 3 of 4"):text.index("Step 4 of 4")]
    assert "bin/pointe key <vendor>" in step and "pointe key check" not in step and "/pointe:stop" not in step
    for does in ("opens the page and the window itself", "checks the key with one tiny live call",
                 "opens the window again when the vendor refuses the key", "restarts Pointe if it runs"):
        assert does in step, does


def test_the_first_call_ends_on_pointe_heard_you():
    text = " ".join((ROOT / "plugin" / "commands" / "setup.md").read_text().split())
    step = text[text.index("Step 4 of 4"):text.index("**Done.**")]
    assert '"Put on headphones, allow the microphone, press Connect, and say hello."' in step
    assert "claude-voice-attach heard 180" in step and "Pointe heard you. You're set up." in step
    assert text.index("**Done.**") < text.index("**Your phone.**") < text.index("**The Mac app and the iPhone app.**")


def test_pointe_voice_sends_a_first_run_to_setup(tmp_path):
    """/pointe:voice no longer runs setup itself: it would need setup's whole allow list on every join
    (tests/test_plugin_permissions.py). It tells the person to run /pointe:setup and stops."""
    voice = (ROOT / "plugin" / "commands" / "voice.md").read_text()
    assert "bin/voice-first-run --needed" in voice and "run `/pointe:setup`" in voice
    run = lambda: subprocess.run([str(ROOT / "bin" / "voice-first-run"), "--needed"], capture_output=True, text=True,
                                 env={"CLAUDE_VOICE_STATE": str(tmp_path), "PATH": "/usr/bin:/bin"}).stdout  # noqa: E731
    assert run() == "needed\n"
    (tmp_path / "token").write_text("x")
    assert run() == "done\n", "the voice ran here before"


def test_every_best_for_line_reads_as_a_sentence():
    """The onboarding review: "For you already pay for OpenAI.", "For nothing may leave the Mac; no budget with a 32 GB
    Mac." and "Fully local: none. $0 a busy hour." in the doctor, `pointe setup` and the page."""
    table = setups.text_table()
    for s in setups.SETUPS:
        assert f"Best for {s.pick_for}." in table and not s.pick_for.startswith(("you ", "nothing ", "just "))
        assert ";" not in s.pick_for
    assert "Fully local: no key. A busy hour: $0." in table and "For " not in table
    page = (ROOT / "pointe" / "ui.html").read_text()
    assert "For ${x.pick_for}" not in page.replace("Best for ${x.pick_for}", "")
    mac = (ROOT / "apps" / "macos" / "PointeMac" / "MacSettings.swift").read_text()
    assert ': best for \\(choice.pickFor)"' in mac


def test_a_setup_with_openai_ears_is_refused_while_openai_url_sends_the_key_elsewhere(state, monkeypatch):
    (state / "config.json").write_text(json.dumps({"openai_url": "https://example-resource.openai.azure.com/openai/v1/"}))
    with pytest.raises(SystemExit, match="openai_url"):
        setups.choose("openai")
    assert json.loads((state / "config.json").read_text()).get("setup") is None
    assert setups.choose("two")["openai_url"].startswith("https://example-resource")


def test_the_env_setting_guards_the_same_way(state, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_OPENAI_URL", "https://example-resource.openai.azure.com/openai/v1/")
    with pytest.raises(SystemExit):
        setups.choose("openai")


def test_no_tool_shares_a_module_name_with_pointe():
    """tools/ and pointe/ are both put first on sys.path by different tests: a tool named like a Pointe module is
    imported in its place ("import vendors" with tools/ first took tools/write_setups.py and failed on setups.WHY_KEYS)."""
    tools = {p.stem for p in (ROOT / "tools").glob("*.py")}
    assert not tools & {p.stem for p in (ROOT / "pointe").glob("*.py")}


def test_config_is_read_again_only_when_the_file_changed(state, monkeypatch):
    """Name matching asks for this Mac's name per session: a route at 300 sessions read config.json 900 times."""
    path = state / "config.json"
    path.write_text(json.dumps({"machine": "desk"}))
    reads = []
    real = vendors.json.loads
    monkeypatch.setattr(vendors.json, "loads", lambda text, *a, **k: (reads.append(1), real(text, *a, **k))[1])
    assert [vendors.config()["machine"] for _ in range(50)] == ["desk"] * 50 and len(reads) == 1
    got = vendors.config()
    got["machine"] = "changed by a caller"
    assert vendors.config()["machine"] == "desk"  # a caller's change never reaches the next one
    path.write_text(json.dumps({"machine": "studio-two"}))
    assert vendors.config()["machine"] == "studio-two" and len(reads) == 2
    path.unlink()
    assert vendors.config() == {}
