"""Quick settings (docs/features/quick-settings.md): reply length, speaking speed per device, clean up my words, by tap
and by voice, and the keys-only change log. Offline: no vendor is called, no audio is played.

uv run --locked pytest -q tests/test_quick_settings.py
"""

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]

import conversation as cv  # noqa: E402
import quick  # noqa: E402
import whisper  # noqa: E402
from prefs import Prefs  # noqa: E402
from test_orchestrator import client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)

KEYS = {"GOOGLE_API_KEY": "g", "OPENAI_API_KEY": "o", "SONIOX_API_KEY": "s", "ELEVENLABS_API_KEY": "e"}


@pytest.fixture(autouse=True)
def _defaults_after():
    yield
    if "daemon" in sys.modules:
        sys.modules["daemon"].PREFS.update({"replies.length": "concise", "voice.speed": {}, "polish": False, "whisper": False})


# ---------- the phrases ----------

@pytest.mark.parametrize("said, wanted", [
    ("be more concise", ("replies.length", quick.DOWN)), ("Be more concise.", ("replies.length", quick.DOWN)),
    ("shorter answers", ("replies.length", quick.DOWN)), ("keep it shorter from now on", ("replies.length", quick.DOWN)),
    ("Pointe, be more concise please", ("replies.length", quick.DOWN)),
    ("be more detailed", ("replies.length", quick.UP)), ("more detail from now on", ("replies.length", quick.UP)),
    ("longer answers", ("replies.length", quick.UP)), ("be more thorough", ("replies.length", quick.UP)),
    ("brief answers", ("replies.length", "brief")), ("thorough replies", ("replies.length", "thorough")),
    ("detailed answers from now on", ("replies.length", "detailed")), ("concise answers", ("replies.length", "concise")),
    ("תהיה יותר תמציתי", ("replies.length", quick.DOWN)), ("תשובות קצרות יותר", ("replies.length", quick.DOWN)),
    ("תהיה יותר מפורט", ("replies.length", quick.UP)), ("יותר פירוט מעכשיו", ("replies.length", quick.UP)),
    ("תשובות מפורטות", ("replies.length", "detailed")), ("תשובות קצרות", ("replies.length", "brief")),
    ("speak faster", ("voice.speed", quick.UP)), ("talk faster", ("voice.speed", quick.UP)), ("faster voice", ("voice.speed", quick.UP)),
    ("slow down", ("voice.speed", quick.DOWN)), ("speak slower", ("voice.speed", quick.DOWN)),
    ("normal speed", ("voice.speed", 1.0)), ("fastest", ("voice.speed", 1.2)), ("slowest", ("voice.speed", 0.8)),
    ("תדבר יותר מהר", ("voice.speed", quick.UP)), ("תדבר לאט יותר", ("voice.speed", quick.DOWN)),
    ("מהירות רגילה", ("voice.speed", 1.0)),
    ("clean up my words", ("polish", True)), ("stop cleaning my words", ("polish", False)),
    ("clean my words off", ("polish", False)), ("תנקה את המילים שלי", ("polish", True)),
    ("תפסיק לנקות את המילים שלי", ("polish", False)),
])
def test_the_phrases_change_a_setting(said, wanted):
    assert quick.intent(said) == wanted


@pytest.mark.parametrize("said", [
    "tell me more", "explain", "elaborate", "longer", "more", "תפרט", "ספר לי עוד",  # one answer, longer: not the setting
    "speed up the tests", "billing, slow down", "tell billing to be more concise", "slow down the build",
    "what does concise mean", "the answers were shorter yesterday", "clean up the words in the readme",
    "whisper mode", "back to normal", "normal", "faster", "", "be more concise " * 10,
])
def test_other_words_change_nothing(said):
    assert quick.intent(said) is None


def test_a_step_holds_at_the_ends_and_normal_speed_is_not_a_step():
    assert quick.step(quick.LEVELS, "concise", quick.DOWN) == "brief"
    assert quick.step(quick.LEVELS, "brief", quick.DOWN) == "brief"
    assert quick.step(quick.LEVELS, "thorough", quick.UP) == "thorough"
    assert quick.step(quick.SPEEDS, 1.0, quick.UP) == 1.1
    assert quick.step(quick.SPEEDS, 1.2, quick.UP) == 1.2
    assert quick.step(quick.SPEEDS, 0.8, quick.DOWN) == 0.8
    assert quick.step(quick.SPEEDS, 1.2, 1.0) == 1.0  # 1.0 is "normal speed", never "one step up"
    assert quick.SPEEDS == (0.8, 0.9, 1.0, 1.1, 1.2)


def test_every_confirmation_is_four_words_at_most():
    lines = [quick.length_line(a, b, he) for a in quick.LEVELS for b in quick.LEVELS for he in (False, True)]
    lines += [quick.speed_line(a, b, w, he) for a in quick.SPEEDS for b in quick.SPEEDS
              for w in (quick.UP, quick.DOWN, b) for he in (False, True)]
    lines += [quick.polish_line(on, he) for on in (True, False) for he in (False, True)] + list(quick.NO_SPEED_LINE)
    assert all(len(line.split()) <= 4 for line in lines), [line for line in lines if len(line.split()) > 4]
    assert quick.speed_line(1.0, 1.1, quick.UP, False) == "Faster now."
    assert quick.speed_line(1.2, 1.2, quick.UP, False) == "Already at fastest."
    assert quick.length_line("concise", "brief", True) == "תשובות קצרות מעכשיו."


def test_no_em_dash_in_what_a_person_reads_or_hears():
    words = list(quick.COPY.values()) + [cv.LENGTHS[level].rule for level in quick.LEVELS]
    assert not [w for w in words if "—" in w]


# ---------- the lengths ----------

def test_concise_is_exactly_the_length_pointe_always_had():
    concise = cv.LENGTHS["concise"]
    assert (concise.reply, concise.report, concise.status, concise.overview, concise.detail) == \
        (cv.REPLY, cv.REPORT, cv.STATUS, cv.OVERVIEW, cv.DETAIL)
    assert cv.REPLY == cv.Limit(30, 2, 3) and cv.DETAIL == cv.Limit(120, 8, None)
    for trigger, asked in [("what's billing doing", "what's billing doing"), ("tell me more", "tell me more"),
                           ("[voice connected] Active.", ""), ("compare the two", "compare the two")]:
        assert cv.limit_for(trigger, asked, level="concise") == cv.limit_for(trigger, asked)
    assert cv.length_rule("concise") is None  # the brain is told nothing new


@pytest.mark.parametrize("level, reply, detail", [
    ("brief", cv.Limit(12, 1, 2), cv.Limit(60, 4, None)),
    ("concise", cv.Limit(30, 2, 3), cv.Limit(120, 8, None)),
    ("detailed", cv.Limit(60, 4, 3), cv.Limit(160, 10, None)),
    ("thorough", cv.Limit(120, 8, 5), cv.Limit(200, 12, None)),
])
def test_each_level_sets_the_reply_and_tell_me_more_lengthens_one_answer(level, reply, detail):
    assert cv.limit_for("what's billing doing", "what's billing doing", level=level) == reply
    assert cv.limit_for("tell me more", "tell me more", level=level) == detail


def test_the_table_of_the_design():
    rows = {level: (L.reply.words, L.report.words, L.status.words, L.overview.words, L.detail.words)
            for level, L in cv.LENGTHS.items()}
    assert rows == {"brief": (12, 20, 30, 40, 60), "concise": (30, 45, 60, 60, 120), "detailed": (60, 70, 90, 90, 160),
                    "thorough": (120, 100, 120, 120, 200)}


def test_drive_and_whisper_always_win():
    assert cv.limit_for("hi", "hi", drive_words=25) == cv.Limit(25, 2)  # concise in drive mode: as it always was
    assert cv.limit_for("tell me more", "tell me more", drive_words=25) == cv.Limit(25, 2)
    assert cv.limit_for("hi", "hi", drive_words=25, level="thorough") == cv.Limit(25, 2)
    assert cv.limit_for("hi", "hi", drive_words=25, level="brief") == cv.Limit(12, 1, 2)  # the smaller of the two
    assert cv.limit_for("hi", "hi", whisper_words=whisper.MAX_WORDS, level="thorough").words == whisper.MAX_WORDS
    assert cv.limit_for("hi", "hi", drive_words=25, whisper_words=20).words == 20
    assert cv.limit_for("[briefing] all of it", "brief me", drive_words=25) is None  # asked for at length: never cut


def test_a_level_other_than_concise_tells_the_brain_its_limits():
    rule = cv.length_rule("detailed")
    assert "60 words" in rule and "4 sentences" in rule and "160 words" in rule and "replaces the length rule" in rule


# ---------- the saved settings and the change log ----------

def test_the_settings_are_saved_and_survive_a_restart(tmp_path):
    prefs = Prefs(tmp_path / "prefs.json")
    assert (prefs.get("replies.length"), prefs.get("voice.speed"), prefs.get("polish")) == ("concise", {}, False)
    prefs.update({"replies.length": "thorough", "voice.speed": {"iphone": 1.1}, "polish": True})
    again = Prefs(tmp_path / "prefs.json")
    assert (again.get("replies.length"), again.get("voice.speed"), again.get("polish")) == ("thorough", {"iphone": 1.1}, True)


@pytest.mark.parametrize("bad", [{"replies.length": "long"}, {"voice.speed": {"iphone": 1.3}}, {"voice.speed": {"iphone": 0.85}},
                                 {"voice.speed": {"watch": 1.0}}, {"voice.speed": {"mac": True}}, {"voice.speed": 1.1},
                                 {"polish": "yes"}])
def test_a_wrong_value_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        Prefs(tmp_path / "prefs.json").update(bad)


def test_the_change_log_has_keys_and_never_values(tmp_path):
    prefs = Prefs(tmp_path / "prefs.json")
    prefs.update({"replies.length": "thorough", "voice.speed": {"iphone": 1.2}, "polish": True})
    prefs.update({"replies.length": "thorough"})  # no change, no line
    prefs.update({"voice.speed": {"iphone": 1.2, "mac": 0.9}}, by="voice")
    lines = (tmp_path / "settings-changes.log").read_text().splitlines()
    assert [line.split()[1:] for line in lines] == [["replies.length", "app"], ["voice.speed.iphone", "app"], ["polish", "app"],
                                                    ["voice.speed.mac", "voice"]]
    text = (tmp_path / "settings-changes.log").read_text()
    assert not re.search(r"thorough|1\.2|0\.9|true|True", text)
    assert oct((tmp_path / "settings-changes.log").stat().st_mode & 0o777) == "0o600"


def test_the_change_log_stays_on_this_mac():
    """Only prefs.py names it: no route serves it, no report or log line carries it, nothing uploads it."""
    named = [p.relative_to(ROOT) for folder in ("pointe", "bin", "hooks", "plugin", "channel", "tools")
             if (ROOT / folder).exists() for p in (ROOT / folder).rglob("*")
             if p.is_file() and p.suffix in (".py", ".html", ".sh", ".js", ".json", "") and "settings-changes" in p.read_text(errors="replace")]
    assert named == [Path("pointe/prefs.py")]


def test_the_change_log_keeps_its_newer_half(tmp_path, monkeypatch):
    import prefs as prefs_module
    monkeypatch.setattr(prefs_module, "CHANGES_MAX_BYTES", 200)
    prefs = Prefs(tmp_path / "prefs.json")
    for i in range(20):
        prefs.update({"polish": i % 2 == 0})
    assert (tmp_path / "settings-changes.log").stat().st_size < 400


# ---------- the daemon: by voice, by tap, the status ----------

def _ears(d, monkeypatch):
    ears = d.SonioxEars()
    reached, said = [], []

    async def push(frame, *a):
        reached.append(frame)

    async def exactly(line, tag, readback=False):
        said.append(line)
    ears.push_frame = push
    monkeypatch.setattr(d, "_say_exactly", exactly)
    return ears, reached, said


def test_be_more_concise_changes_the_setting_in_code_and_tell_me_more_does_not(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("be more concise"))
    assert d.PREFS.get("replies.length") == "brief" and not reached and said == ["Brief from now on."]
    assert d._reply_limit("what's billing doing", "what's billing doing") == cv.Limit(12, 1, 2)
    asyncio.run(ears._take("be more detailed"))
    asyncio.run(ears._take("be more detailed"))
    assert d.PREFS.get("replies.length") == "detailed" and said[-1] == "Detailed from now on."
    assert d.state.by_voice[0] == "replies.length"
    monkeypatch.setattr(d, "on_user_utterance", lambda text: asyncio.sleep(0))
    asyncio.run(ears._take("tell me more"))
    assert d.PREFS.get("replies.length") == "detailed" and reached  # one answer: the brain has the words


def test_hebrew_is_answered_in_hebrew(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("תהיה יותר מפורט"))
    assert d.PREFS.get("replies.length") == "detailed" and said == ["תשובות מפורטות מעכשיו."]


def test_the_words_are_not_a_setting_during_a_brain_dump_or_a_meeting(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    d._start_dump("let me think out loud")
    try:
        asyncio.run(ears._take("be more concise"))
    finally:
        d.state.dump = None
    assert d.PREFS.get("replies.length") == "concise" and not said


def test_the_brain_hears_the_level_and_the_limit_takes_whisper_mode(d):
    assert not any(line.startswith("[reply length") for line in d._brain_context().split("\n"))
    d.PREFS.update({"replies.length": "thorough"})
    assert cv.length_rule("thorough") in d._brain_context()
    assert d._reply_limit("hi", "hi") == cv.Limit(120, 8, 5)
    d.PREFS.update({"whisper": True})
    assert d._reply_limit("hi", "hi").words == whisper.MAX_WORDS


def _call(d, monkeypatch, mouth_choice: str):
    for env, value in KEYS.items():
        monkeypatch.setenv(env, value)
    monkeypatch.setattr(d, "_setup", d.vendors.Setup(brain="gemini:b", reader="gemini:r", checker="gemini:c", ears="soniox",
                                                     mouth=mouth_choice))
    pushed = []

    async def push(frame, *a):
        pushed.append(frame)
    d.state.conn = fake_conn()
    d.state.front = SimpleNamespace(push_frame=push)
    d.state.mouth = d.vendors.build_mouth(mouth_choice, 24000, None, speed=1.0)
    d.state.speed = 1.0
    return pushed


def test_speak_faster_sets_this_devices_speed_and_the_next_sentence_takes_it(d, monkeypatch):
    pushed = _call(d, monkeypatch, "elevenlabs:eleven_v4_turbo")
    d.state.phone_socket = object()  # the iPhone app holds the call
    ears, reached, said = _ears(d, monkeypatch)
    order = []
    monkeypatch.setattr(d, "_say_exactly", lambda line, tag, readback=False: asyncio.sleep(0, order.append(("say", line))))
    real = d._apply_speed

    async def applied():
        await real()
        order.append(("speed", d.state.speed))
    monkeypatch.setattr(d, "_apply_speed", applied)
    asyncio.run(ears._take("speak faster"))
    assert d.PREFS.get("voice.speed") == {"iphone": 1.1}  # the Mac and the page keep theirs
    assert [type(f).__name__ for f in pushed] == ["TTSUpdateSettingsFrame"] and pushed[0].delta.speed == 1.1
    assert pushed[0].service is d.state.mouth
    assert order == [("speed", 1.1), ("say", "Faster now.")]  # confirmed at the new speed
    asyncio.run(d.state.mouth._update_settings(pushed[0].delta))
    assert d.state.mouth._voice_settings == {"speed": 1.1}  # what ElevenLabs is sent from the next sentence


def test_a_voice_with_no_speed_number_hides_the_control_and_says_so(d, monkeypatch):
    pushed = _call(d, monkeypatch, "gemini:gemini-3.8-flash-lite-tts")
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("speak faster"))
    assert d.PREFS.get("voice.speed") == {} and not pushed and said == ["Not with this voice."]
    assert client_for(d).get("/voice/status").json()["quick"]["speed_shown"] is False


def test_a_realtime_front_hides_the_speed():
    assert not quick.speed_shown("gemini", "elevenlabs:eleven_v4_turbo")
    assert quick.speed_shown("brain", "elevenlabs:eleven_v4_turbo") and quick.speed_shown("brain", "local:kokoro-mlx")
    assert not quick.speed_shown("brain", "gemini:gemini-3.8-flash-lite-tts")


def test_each_device_sets_its_own_speed_through_the_prefs(d, monkeypatch):
    pushed = _call(d, monkeypatch, "soniox:tts-rt-v2")
    client = client_for(d)
    client.post("/voice/prefs", json={"voice.speed": {"mac": 0.9}})
    client.post("/voice/prefs", json={"voice.speed": {"iphone": 1.2}})
    quick_status = client.get("/voice/status").json()["quick"]
    assert quick_status["speeds"] == {"mac": 0.9, "iphone": 1.2} and quick_status["speed_shown"] is True
    assert not pushed  # the call is the page's: neither change is its speed
    client.post("/voice/prefs", json={"voice.speed": {"page": 0.8}})
    assert [f.delta.speed for f in pushed] == [0.8]
    assert client.post("/voice/prefs", json={"voice.speed": {"page": 1.5}}).status_code == 400


def test_the_row_reads_one_block_of_the_status(d):
    client = client_for(d)
    client.post("/voice/prefs", json={"replies.length": "detailed", "polish": True})
    status = client.get("/voice/status").json()
    assert status["quick"]["length"] == "detailed" and status["polish"] is True and status["quick"]["by_voice"] is None


def test_clean_up_my_words_is_a_saved_setting_and_the_old_route_still_works(d):
    assert client_for(d).post("/voice/polish", json={"on": True}).json() == {"polish": True}
    assert d.PREFS.get("polish") is True and Prefs(d.PREFS.path).get("polish") is True  # read again from the file


def test_the_voice_is_built_at_the_devices_speed_and_asked_nothing_new_at_normal(monkeypatch):
    import vendors
    for env, value in KEYS.items():
        monkeypatch.setenv(env, value)
    for choice in ("elevenlabs:eleven_v4_turbo", "soniox:tts-rt-v2", "openai:gpt-4o-mini-tts"):
        assert vendors.build_mouth(choice, 24000, None)._settings.speed is None, choice
        assert vendors.build_mouth(choice, 24000, None, speed=0.8)._settings.speed == 0.8, choice
    assert vendors.speed_delta(vendors.build_mouth("gemini:gemini-3.8-flash-lite-tts", 24000, None), 1.1) is None


def test_the_local_voice_takes_a_new_speed_mid_call():
    import kokoro_mlx
    import vendors
    mouth = kokoro_mlx.KokoroMLXTTSService(sample_rate=24000)
    assert mouth._settings.speed == 1.0
    asyncio.run(mouth._update_settings(vendors.speed_delta(mouth, 1.2)))
    assert mouth._settings.speed == 1.2


def test_the_settings_change_lines_name_keys_only():
    source = (ROOT / "pointe" / "daemon.py").read_text()
    body = source[source.index("async def _quick_by_voice"):source.index("# ---------- the wait for a reply")]
    assert re.findall(r'logger\.info\(f?"([^"]*)"', body) == ["quick setting changed by voice: {key}"]


def test_a_setting_phrase_never_starts_a_model_step_ahead(d):
    """Brain.foresee may start on settling words: a phrase the daemon answers itself must not reach the model early."""
    assert not d._foreseeable("be more concise") and not d._foreseeable("speak faster")
    assert not d._foreseeable("clean up my words")
    assert d._foreseeable("what is billing doing")


def test_the_local_voice_speaks_at_its_setting(monkeypatch):
    """Kokoro on the Mac's GPU takes the speed of its setting for each sentence, so a change mid-call is heard next."""
    import kokoro_mlx
    import vendors
    asked = []

    class Model:
        def generate(self, text, voice, lang_code, speed, verbose):
            asked.append(speed)
            return []
    monkeypatch.setattr(kokoro_mlx, "_model", lambda: Model())
    mouth = kokoro_mlx.KokoroMLXTTSService(sample_rate=24000)

    async def nothing(*a, **k):
        return None
    monkeypatch.setattr(mouth, "start_tts_usage_metrics", nothing)

    async def say():
        async for _ in mouth.run_tts("Ready.", "c1"):
            pass
        await mouth._update_settings(vendors.speed_delta(mouth, 0.8))
        async for _ in mouth.run_tts("Ready.", "c2"):
            pass
    asyncio.run(say())
    assert asked == [1.0, 0.8]


def test_the_voice_menus_keys_take_no_key_another_menu_has():
    """⌘1–⌘4, ⌥⌘1–⌥⌘5 and ⇧⌘K are the Voice menu's (PointeMacApp.swift); a menu key used twice runs only one of them."""
    source = (ROOT / "apps" / "macos" / "PointeMac" / "PointeMacApp.swift").read_text()
    commands = source[source.index("struct PointeCommands"):source.index("enum MacMenu")]
    found = []
    for line in commands.splitlines():
        if ".keyboardShortcut(" not in line:
            continue
        call = line[line.index(".keyboardShortcut(") + len(".keyboardShortcut("):]
        mods = frozenset(re.findall(r"\.(command|shift|option|control)", call.split("modifiers:", 1)[1])) if "modifiers:" in call \
            else frozenset({"command"})
        if "index + 1" in call:  # the Voice menu's digits: 1 to 4 with ⌘, 1 to 5 with ⌥⌘
            found += [(n, mods) for n in ("1234" if mods == {"command"} else "12345")]
        else:
            found.append((re.match(r'("[^"]*"|\.\w+)', call).group(1), mods))
    assert len(found) == len(set(found)), sorted(k for k in found if found.count(k) > 1)
    assert ('"k"', frozenset({"command", "shift"})) in found and ("4", frozenset({"command"})) in found
    assert ("5", frozenset({"command", "option"})) in found
