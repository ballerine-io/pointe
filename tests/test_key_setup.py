"""Which keys a person needs, said the same way everywhere: /pointe:setup, the doctor, docs/install.md, the README, the
page's and the Mac app's Settings, and the voice's own help. Any one start set fills every role, and a key no role needs
is "optional", never "missing" (a new user read the old key list as "you need all of them")."""

import asyncio
import itertools
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import daemon  # noqa: E402  (at import: it reads the state dir conftest set, never a test's own)
import doctor  # noqa: E402
import vendors  # noqa: E402

ENVS = {vendor: env for vendor, (env, _) in vendors.KEYS.items()}
SWIFT = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeMacKit" / "KeyPlan.swift").read_text()
PAGE = (ROOT / "ui.html").read_text()


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """Only the keys a test gives, from the environment: the Keychain is never asked."""
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in [*vendors.KEY_ENVS, "CLAUDE_VOICE_BRAIN", "CLAUDE_VOICE_READER", "CLAUDE_VOICE_CHECKER", "CLAUDE_VOICE_EARS",
                "CLAUDE_VOICE_MOUTH", "CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_VOICE_LOCAL"]:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", ""))

    def give(*vendor_names):
        for v in vendor_names:
            monkeypatch.setenv(ENVS[v], f"synthetic-{v}")
    return give


def _vendors_of(setup: vendors.Setup) -> dict:
    return {r: getattr(setup, a).split(":")[0] for r, a in
            (("brain", "brain"), ("reader", "reader"), ("checker", "checker"), ("ears", "ears"), ("mouth", "mouth"))}


# ---------- the facts: which keys fill every role ----------

@pytest.mark.parametrize("start,expected", [
    (("gemini",), dict.fromkeys(("brain", "reader", "checker", "ears", "mouth"), "gemini")),
    (("openai",), dict.fromkeys(("brain", "reader", "checker", "ears", "mouth"), "openai")),
    (("soniox", "anthropic"), {"brain": "anthropic", "reader": "anthropic", "checker": "anthropic", "ears": "soniox",
                               "mouth": "soniox"}),
])
def test_each_start_set_alone_fills_every_role(keys, start, expected):
    assert start in vendors.START_KEYS
    keys(*start)
    assert _vendors_of(vendors.resolve()) == expected


def test_the_minimal_sets_are_the_three_offered_and_anthropic_with_elevenlabs(keys):
    """Every smallest set of keys that runs: the three the copy offers, and Anthropic + ElevenLabs, which works but is
    not offered (ElevenLabs' ears were not run through the audio suite)."""
    minimal = []
    for n in range(1, len(vendors.KEYS) + 1):
        for combo in itertools.combinations(sorted(vendors.KEYS), n):
            if any(set(m) <= set(combo) for m in minimal):
                continue
            if None not in vendors.filled(set(combo)).values():
                minimal.append(combo)
    assert sorted(minimal) == sorted([("gemini",), ("openai",), ("anthropic", "soniox"), ("anthropic", "elevenlabs")])
    assert {tuple(sorted(s)) for s in vendors.START_KEYS} <= set(minimal)


@pytest.mark.parametrize("alone", ["anthropic", "soniox", "elevenlabs"])
def test_these_keys_alone_do_not_run(keys, alone):
    keys(alone)
    with pytest.raises(SystemExit):
        vendors.resolve()


@pytest.mark.parametrize("combo", [c for n in range(1, 6) for c in itertools.combinations(sorted(vendors.KEYS), n)])
def test_filled_says_what_resolve_picks(keys, combo):
    keys(*combo)
    roles = vendors.filled(set(combo))
    if None in roles.values():
        with pytest.raises(SystemExit):
            vendors.resolve()
    else:
        assert _vendors_of(vendors.resolve()) == roles


def test_the_subscription_is_not_a_key(keys, monkeypatch):
    """A Claude.ai login is not read: only ANTHROPIC_API_KEY is (the copy says so; this holds the code to it)."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "synthetic-oauth")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "synthetic-auth")
    assert not vendors.has("anthropic")


# ---------- the status: covered means optional ----------

@pytest.mark.parametrize("start", vendors.START_KEYS)
def test_with_every_role_filled_each_absent_key_is_optional(start):
    s = vendors.key_status(set(start))
    assert not s["empty"] and s["fix"] is None
    assert {v: st for v, st in s["keys"].items() if v not in start} == dict.fromkeys(set(vendors.KEYS) - set(start), "optional")
    assert s["line"] == "Every role is filled. The other keys are optional: not needed with your current keys."


def test_no_status_says_missing():
    for n in range(0, 6):
        for combo in itertools.combinations(vendors.KEYS, n):
            s = vendors.key_status(set(combo))
            assert set(s["keys"].values()) <= {"in use", "not used", "needed", "optional"}
            assert "missing" not in s["line"].lower()
            assert list(s["keys"].values()).count("needed") == (1 if s["empty"] else 0)


@pytest.mark.parametrize("present,fix,line", [
    (set(), "gemini", "No model key yet. " + vendors.WHAT_YOU_NEED),
    ({"anthropic"}, "soniox", "Pointe cannot hear you or speak yet: add a Soniox key."),
    ({"soniox"}, "anthropic", "Pointe cannot think, read your sessions or check each send yet: add an Anthropic key."),
    ({"elevenlabs"}, "anthropic", "Pointe cannot think, read your sessions or check each send yet: add an Anthropic key."),
])
def test_an_empty_role_names_the_one_key_that_fills_it(present, fix, line):
    s = vendors.key_status(present)
    assert s["fix"] == fix and s["line"] == line
    assert None not in vendors.filled(present | {fix}).values()


def test_a_key_no_role_reaches_is_saved_not_used():
    s = vendors.key_status(set(vendors.KEYS))
    assert s["keys"]["openai"] == "not used" and s["keys"]["gemini"] == "in use" and s["line"] == "Every role is filled."


def test_voice_on_the_mac_needs_only_a_text_key():
    s = vendors.key_status({"anthropic"}, voice_on_mac=True)
    assert not s["empty"] and s["roles"]["ears"] == vendors.LOCAL


# ---------- the doctor ----------

def _doctor(capsys, monkeypatch, *argv):
    monkeypatch.setenv("CLAUDE_VOICE_DAEMON_PORT", "1")  # never the live daemon's port
    monkeypatch.setattr(doctor, "harnesses_here", lambda: [])
    monkeypatch.setattr(doctor.local, "status_lines", lambda: [])
    monkeypatch.setattr(sys, "argv", ["voice-doctor", *argv])
    doctor.main()
    return capsys.readouterr().out


def test_the_doctor_lists_unneeded_keys_as_optional(keys, capsys, monkeypatch):
    keys("gemini")
    out = _doctor(capsys, monkeypatch)
    assert "  found    gemini (brain, reader, checker, ears, mouth)" in out
    for v in ("openai", "anthropic", "soniox", "elevenlabs"):
        assert f"  optional {v} (not needed with your current keys)" in out
    assert "missing" not in out.split("Roles:")[0]


def test_the_doctor_names_the_one_key_an_empty_role_needs(keys, capsys, monkeypatch):
    keys("anthropic")
    out = _doctor(capsys, monkeypatch)
    assert "  needed   soniox (the one key that fills ears, mouth)" in out
    assert "  optional elevenlabs\n" in out and "  optional gemini\n" in out


def test_preflight_with_part_of_a_set_says_which_key_and_what_is_enough(keys, capsys):
    keys("anthropic")
    assert doctor.preflight() == 1
    out = " ".join(capsys.readouterr().out.split())
    assert "Pointe cannot hear you or speak yet: add a Soniox key." in out and "key soniox" in out
    assert vendors.WHAT_YOU_NEED in out and vendors.WHY_KEYS in out


def test_preflight_with_no_key_shows_what_is_enough(keys, capsys):
    assert doctor.preflight() == 1
    out = " ".join(capsys.readouterr().out.split())
    assert vendors.WHAT_YOU_NEED in out and vendors.WHY_KEYS in out


# ---------- the daemon's status, for the page ----------

def test_the_daemons_key_status_marks_unneeded_keys_optional(keys, monkeypatch):
    keys("soniox", "anthropic")
    monkeypatch.setattr(daemon, "_setup", None)
    monkeypatch.setattr(daemon, "_keys_cache", None)
    got = daemon._keys_status()
    assert got["keys"] == {"gemini": "optional", "openai": "optional", "anthropic": "in use", "soniox": "in use",
                           "elevenlabs": "optional"}
    assert got["uses"]["anthropic"] == ["brain", "reader", "checker"] and got["uses"]["soniox"] == ["ears", "mouth"]
    assert "not needed with your current keys" in got["line"]
    assert not any("synthetic" in json.dumps(v) for v in got.values()), "presence only, never a value"


@pytest.mark.skipif(not os.path.exists(__import__("page_rig").CHROME), reason="headless Chrome is not installed here")
def test_the_page_shows_optional_not_missing():
    from page_rig import Browser, StubMac, fixture, free_port

    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = {**fixture(sessions=1), "keys": {
            "line": "Every role is filled. The other keys are optional: not needed with your current keys.",
            "keys": {"gemini": "in use", "openai": "optional", "anthropic": "optional", "soniox": "optional", "elevenlabs": "optional"},
            "uses": {"gemini": ["brain", "reader", "checker", "ears", "mouth"]}}}
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.wait_for_page()
                await asyncio.sleep(0.6)
                await page.eval("(async () => { await openSettings(); settingsJump('g-keys'); return true; })()")
                await asyncio.sleep(0.4)
                return await page.eval("""(() => ({rows: [...document.querySelectorAll('#pref-keys .r')].map(r => r.innerText),
                  line: document.getElementById('pref-keys-line').textContent,
                  need: document.getElementById('pref-keys-need').textContent}))()""")
        finally:
            await stub.stop()
    got = asyncio.run(run())
    assert got["rows"][0].split("\n") == ["Google Gemini", "In use: brain, reader, checker, ears, mouth"], got
    assert all(r.endswith("Optional") for r in got["rows"][1:]) and len(got["rows"]) == 5, got
    assert got["need"] == vendors.WHAT_YOU_NEED and "Missing" not in json.dumps(got)


# ---------- one answer on every surface ----------

def _flat(text: str) -> str:
    return " ".join(text.replace("**", "").split())


def _swift(name: str) -> str:
    return re.search(rf'static let {name} = "((?:[^"\\]|\\.)*)"', SWIFT).group(1).replace('\\"', '"')


def _page(name: str) -> str:
    block = PAGE[PAGE.index("const KEYS_COPY = {"):]
    block = block[:block.index("};")]
    return dict(re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block))[name].replace("\\'", "'")


@pytest.mark.parametrize("where", ["README.md", "docs/install.md"])
def test_the_docs_say_what_is_enough_word_for_word(where):
    text = _flat((ROOT / where).read_text())
    assert f"What do I need? {vendors.WHAT_YOU_NEED}" in text
    assert "Best quality" not in text
    assert vendors.WHY_KEYS in text


def test_the_doctor_the_page_the_mac_app_and_the_help_say_it_too():
    assert vendors.WHAT_YOU_NEED in _flat(doctor.NO_KEY) and vendors.WHY_KEYS in _flat(doctor.NO_KEY)
    assert _page("need") == _swift("whatYouNeed") == vendors.WHAT_YOU_NEED
    assert _page("why") == _swift("whyKeys") == vendors.WHY_KEYS
    assert _page("title") == _swift("whatYouNeedTitle") == "What do I need?"
    for label in ("inUse", "notUsed", "needed", "optional"):
        assert _page(label) == _swift(label)
    help_entry = next(e for e in json.loads((ROOT / "product_help.json").read_text())["entries"] if e["id"] == "keys")
    assert help_entry["how"] == f"{vendors.WHAT_YOU_NEED} {vendors.WHY_KEYS} Switch setups with pointe setup on the Mac."


def test_the_mac_app_fills_roles_in_the_daemons_order():
    swift_roles = dict(re.findall(r'\("(\w+)", \[([^\]]+)\]\)', SWIFT))
    for role, order in vendors.ROLE_ORDERS.items():
        assert swift_roles[role].replace(".", "").replace(" ", "").split(",") == [c.split(":")[0] for c in order], role
    fix = re.search(r"fixOrder: \[Vendor\] = \[([^\]]+)\]", SWIFT).group(1)
    assert fix.replace(".", "").replace(" ", "").split(",") == list(vendors.FIX_ORDER)
    words = dict(re.findall(r'"(\w+)": "([^"]+)"', re.search(r"roleWords = \[([^\]]+)\]", SWIFT).group(1)))
    assert words == vendors.ROLE_WORDS
    assert f"{_swift('allFilled')} {_swift('othersOptional')}" == vendors.key_status({"gemini"})["line"]
    assert _swift("noKey") + " " + vendors.WHAT_YOU_NEED == vendors.key_status(set())["line"]
    names = dict(re.findall(r'case \.(\w+): "(\w+)"', SWIFT[SWIFT.index("shortName"):]))
    assert names == vendors.NAMES


def test_no_surface_calls_an_unneeded_key_missing():
    mac = (ROOT / "macos" / "PointeMac" / "MacSettings.swift").read_text()
    assert '"Missing"' not in mac and "KeyRow.text(state)" in mac
    assert textwrap.dedent("""\
        No model key yet. What do I need?""") in doctor.NO_KEY


# ---------- pointe key check: one tiny live call, the key never shown ----------

def test_key_check_says_works_refused_or_unreachable_and_never_shows_the_key(keys, monkeypatch):
    import urllib.error
    import urllib.request

    import keys as keys_cli

    keys("soniox", "gemini")
    asked = []

    def fake_open(request, timeout):
        asked.append((request.full_url, request.headers))
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    ok, said = keys_cli.check("soniox")
    assert not ok and said == vendors.refused_help("soniox") and "synthetic" not in said
    assert asked[0][0] == "https://api.soniox.com/v1/models" and asked[0][1]["Authorization"] == "Bearer synthetic-soniox"

    async def answers(model, *rest):
        assert model == "gemini-3.5-flash-lite"  # the cheapest model the key can use: the checker's
        return "ok"
    monkeypatch.setitem(vendors._TEXT, "gemini", answers)
    assert keys_cli.check("gemini") == (True, "The gemini key works.")

    async def refuses(*a):
        raise RuntimeError("Incorrect API key provided: synthetic-ge***ini. invalid_api_key")
    monkeypatch.setitem(vendors._TEXT, "gemini", refuses)
    ok, said = keys_cli.check("gemini")
    assert not ok and "synthetic" not in said and "refused" in said
    assert keys_cli.check("openai") == (False, "No openai key found: save one with pointe key openai.")


# ---------- pointe key: opens the vendor's page, asks, checks, asks again when refused, saves, restarts ----------

@pytest.fixture
def key_cli(keys, monkeypatch):
    """`pointe key` with the Mac window, the browser, the Keychain and the daemon replaced by records."""
    import keys as keys_cli

    seen = {"opened": [], "asked": [], "checked": [], "saved": [], "restarted": 0}
    answers, verdicts = [], []
    monkeypatch.setattr(keys_cli, "open_page", lambda vendor: seen["opened"].append(vendor))

    def ask(vendor, refused=False):
        seen["asked"].append((vendor, refused, keys_cli.prompt(vendor, refused)))
        return answers.pop(0) if answers else None
    monkeypatch.setattr(keys_cli, "ask", ask)

    def check(vendor, secret=None):
        seen["checked"].append((vendor, secret))
        return verdicts.pop(0)
    monkeypatch.setattr(keys_cli, "check", check)
    monkeypatch.setattr(keys_cli, "save", lambda item, secret: seen["saved"].append((item, secret)) or True)
    monkeypatch.setattr(keys_cli, "running", lambda: True)

    def restart():
        seen["restarted"] += 1
        return True
    monkeypatch.setattr(keys_cli, "restart", restart)
    return keys_cli, seen, answers, verdicts


def test_pointe_key_opens_the_page_asks_again_when_refused_then_saves_and_restarts(key_cli, capsys):
    keys_cli, seen, answers, verdicts = key_cli
    answers += ["synthetic-wrong", "synthetic-right"]
    verdicts += [(False, vendors.refused_help("gemini")), (True, "The gemini key works.")]
    assert keys_cli.main(["gemini"]) == 0
    assert seen["opened"] == ["gemini"]
    assert [(v, r) for v, r, _ in seen["asked"]] == [("gemini", False), ("gemini", True)]
    first, again = seen["asked"][0][2], seen["asked"][1][2]
    assert "1. Open aistudio.google.com/apikey" in first and "\\n2. Sign in, press Create API key" in first
    assert "\\n3. Paste it here and press Save." in first and "refused" not in first
    assert again.startswith("Google Gemini refused that key")
    assert seen["checked"] == [("gemini", "synthetic-wrong"), ("gemini", "synthetic-right")]
    assert seen["saved"] == [("pointe.gemini-api-key", "synthetic-right")], "only the key that works is saved"
    assert seen["restarted"] == 1
    out = capsys.readouterr().out
    assert out == "The Google Gemini key works. It is saved in your Keychain, and Pointe restarted to use it.\n"
    assert "synthetic" not in out


def test_pointe_key_cancelled_saves_nothing(key_cli, capsys):
    keys_cli, seen, answers, verdicts = key_cli
    answers += ["synthetic-wrong"]
    verdicts += [(False, vendors.refused_help("soniox"))]
    assert keys_cli.main(["soniox", "--no-open"]) == 1
    assert seen["opened"] == [] and seen["saved"] == [] and seen["restarted"] == 0
    assert capsys.readouterr().out == "Cancelled: nothing saved. Soniox refused the last key.\n"


def test_pointe_key_saves_a_key_it_could_not_check_and_says_so(key_cli, capsys):
    keys_cli, seen, answers, verdicts = key_cli
    answers += ["synthetic-offline"]
    verdicts += [(None, "The openai key could not be checked: no connection to openai.")]
    assert keys_cli.main(["openai", "--no-restart"]) == 0
    assert seen["saved"] == [("pointe.openai-api-key", "synthetic-offline")] and seen["restarted"] == 0
    assert capsys.readouterr().out == ("Saved the OpenAI key, but it could not be checked (The openai key could not be "
                                       "checked: no connection to openai.). It is saved in your Keychain.\n")


def test_check_tries_a_key_before_it_is_saved_and_leaves_the_environment_as_it_was(keys, monkeypatch):
    import keys as keys_cli

    seen = []

    async def answers(model, *rest):
        seen.append(os.environ.get("GOOGLE_API_KEY"))
        return "ok"
    monkeypatch.setitem(vendors._TEXT, "gemini", answers)
    assert keys_cli.check("gemini", "synthetic-new") == (True, "The gemini key works.")
    assert seen == ["synthetic-new"] and "GOOGLE_API_KEY" not in os.environ


def test_keys_are_saved_under_pointes_own_name_and_the_old_name_still_reads(tmp_path, monkeypatch):
    """1.19.0 moved the Keychain items to pointe.<vendor>-api-key: a key saved before then must keep working, and an item
    another tool keeps under the plain name is read only when Pointe has none of its own."""
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in vendors.KEY_ENVS:
        monkeypatch.delenv(env, raising=False)
    store = {"gemini-api-key": "synthetic-old", "pointe.soniox-api-key": "synthetic-new", "soniox-api-key": "synthetic-other"}
    asked = []

    def security(cmd, **kw):
        asked.append(cmd[3])
        found = store.get(cmd[3])
        return subprocess.CompletedProcess(cmd, 0 if found else 44, (found or "") + "\n", "")
    monkeypatch.setattr(subprocess, "run", security)
    assert vendors.key("gemini") == "synthetic-old" and asked == ["pointe.gemini-api-key", "gemini-api-key"]
    asked.clear()
    assert vendors.key("soniox") == "synthetic-new" and asked == ["pointe.soniox-api-key"]
    asked.clear()
    assert vendors.key("openai") is None and asked == ["pointe.openai-api-key", "openai-api-key"]
