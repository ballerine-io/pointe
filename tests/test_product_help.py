"""The voice answers "how do I…" about Pointe itself from product_help.json (docs/design/product-help.md).

The file is written by tools/product_help.py from the UI code (apps/ios/Pointe/*.swift, ui.html) and hand-written topics;
the brain reaches it through the how_to_use_pointe tool (howto.answer), and the send gate keeps such questions from a
session (daemon._howto_refusal). Offline: no model, no network.
"""

import asyncio
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import howto  # noqa: E402
from test_orchestrator import Params, add, d, open_gates, record_dispatch  # noqa: E402,F401  (d is the daemon fixture)

spec = importlib.util.spec_from_file_location("product_help", ROOT / "tools" / "product_help.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


# ---------- the lookup ----------

@pytest.mark.parametrize("question,topic", [
    ("How do I turn off push to talk on my iPhone?", "mic-mode"),
    ("איך מכבים את הלחץ ודבר באייפון?", "mic-mode"),
    ("What's the difference between hold and tap?", "talk-button"),
    ("Can I tap once instead of holding the button?", "talk-button"),
    ("How do I mute myself?", "mute"),
    ("איך משתיקים אותך?", "mute"),
    ("How do I pair the phone with my Mac?", "pair-phone"),
    ("איך מצמידים את הטלפון?", "pair-phone"),
    ("What is voice lock?", "voice-lock"),
    ("Can other people approve my requests?", "voice-lock"),
    ("מה זה נעילת קול?", "voice-lock"),
    ("How does brain dump work?", "brain-dump"),
    ("How do I close a session by voice?", "close-session"),
    ("איך סוגרים סשן?", "close-session"),
    ("How can I rename a session?", "rename-session"),
    ("איך משנים שם לסשן?", "rename-session"),
    ("It answers too fast. Can it wait longer before answering?", "patience"),
    ("אתה עונה מהר מדי, אפשר שתחכה?", "patience"),
    ("How do I switch to dark mode?", "appearance"),
    ("איך עוברים למצב כהה?", "appearance"),
    ("Where are the settings?", "settings"),
    ("How do I update Pointe?", "update"),
    ("How do I start a new session?", "new-session"),
    ("Can you start a new agent for me?", "new-session"),
    ("איך פותחים סשן חדש?", "new-session"),
    ("How do I join a session to the voice?", "join-session"),
    ("Which keys do I need?", "keys"),
    ("Can I use my Claude subscription instead of an API key?", "keys"),
    ("Do I need all the keys?", "keys"),
    ("איזה מפתחות צריך?", "keys"),
    ("How does the night shift work?", "night-shift"),
    ("Can my sessions keep working while I sleep?", "night-shift"),
    ("How do I stop the night shift?", "night-shift"),
    ("מה זה משמרת לילה?", "night-shift"),
    ("How do I talk to Pointe from the lock screen?", "talk-outside"),
    ("Can I add Pointe to Control Center?", "talk-outside"),
    ("Is there a home screen widget?", "talk-outside"),
    ("איך מדברים איתך ממסך הנעילה?", "talk-outside"),
])
def test_a_question_finds_its_topic_first(question, topic):
    found = howto.lookup(question)
    assert found and found[0]["id"] == topic, [e["id"] for e in found]
    assert len(found) <= howto.MAX_ENTRIES


@pytest.mark.parametrize("question", ["What did lantern do last night?", "Tell me about the weather",
                                      "How do I fix the failing test in billing?", "מה המצב?"])
def test_a_question_about_something_else_finds_nothing(question):
    assert howto.lookup(question) == []


def test_the_answer_gives_the_path_on_the_users_own_screen():
    phone = howto.answer("How do I turn off push to talk?", "iphone")
    page = howto.answer("How do I turn off push to talk?", "page")
    assert phone["screen"] == "the iPhone app" and page["screen"] == "the page"
    assert phone["answers"][0]["where"] == ("the Always on / Say “Pointe” / Hold to talk switch above the mic; "
                                            "or Settings (••• at the top) → Microphone → Always on / Only when I say Pointe / Push to talk")
    assert page["answers"][0]["where"].startswith("Settings → Microphone → Always on / Only when I say Pointe / Push to talk")
    assert "Sessions panel" in page["settings_are"] and "settings_are" not in phone
    assert "Settings" in gen.inventory()["page"]["side"], "settings_are names a button the page shows"


def test_hold_and_tap_on_each_surface():
    phone = howto.answer("hold vs tap", "iphone")["answers"][0]
    assert phone["where"] == "Settings (••• at the top) → Talk button → Hold to talk / Tap to talk"
    assert "Push to talk" in phone["note"], "the item is shown only in push to talk"
    assert howto.answer("hold vs tap", "page")["answers"][0]["where"] == \
        "Settings → Microphone → Talk button → Hold to talk / Tap to talk"


def test_a_feature_missing_on_this_screen_says_where_it_is():
    drive = howto.answer("How do I turn on drive mode?", "page")["answers"][0]
    assert drive["where"].startswith("not on the page; on the iPhone app: Drive button at the top")
    assert drive["say_instead"] == ["drive mode", "I've stopped"]


def test_the_mac_app_gets_its_own_paths_from_the_screens_it_shares_with_the_iphone():
    """The Mac app draws the iPhone app's screens, so its paths are read from the same sources as the Mac compiles them:
    the same Settings, a right-click where the phone has a long press, and no path for what a Mac does not have."""
    mac = howto.answer("How do I turn off push to talk?", "mac")
    assert mac["screen"] == "the Mac app"
    assert mac["answers"][0]["where"] == ("the Always on / Say “Pointe” / Hold to talk switch above the mic; "
                                          "or Settings (••• at the top, or ⌘,) → Microphone → Always on / Only when I say Pointe / Push to talk")
    rename = howto.answer("How do I rename a session?", "mac")["answers"][0]
    assert rename["where"] == "right-click a session → Rename"
    drive = howto.answer("How do I turn on drive mode?", "mac")["answers"][0]
    assert drive["where"].startswith("not on the Mac app; on the iPhone app: Drive button at the top")
    pair = howto.answer("How do I pair my phone?", "mac")["answers"][0]
    assert pair["where"] == "Settings (••• at the top, or ⌘,) → Phone" and "shows the code" in pair["note"]
    inv = gen.inventory()
    assert "Phone" in inv["mac"]["menu"] and "Phone" not in inv["iphone"]["menu"], "the Mac shows the code; the phone reads it"
    assert "Unpair this phone" in inv["iphone"]["menu"] and "Unpair this phone" not in inv["mac"]["menu"]
    assert "Drive" in inv["iphone"]["header"] and "Drive" not in inv["mac"]["header"]
    assert howto.answer("How do I bake bread?", "mac")["say"].endswith("the ••• button at the top right.")
    assert howto.answer("where is voice lock", "a new surface")["screen"] == "the page", "an unknown surface is answered as the page"


def test_the_surface_is_the_app_the_call_is_from():
    """The iPhone app's call is the phone's socket; the Mac app says "Mac" in its hello on the page's socket; anything
    else on that socket is the page."""
    import types

    import daemon
    was = (daemon.state.phone_socket, daemon.state.call_socket, daemon.state.call_client)
    try:
        daemon.state.phone_socket = daemon.state.call_socket = daemon.state.call_client = None
        assert daemon._surface() == "page"
        daemon.state.call_socket = object()
        daemon.state.call_client = types.SimpleNamespace(client={})
        assert daemon._surface() == "page", "the page sends no device"
        daemon.state.call_client = types.SimpleNamespace(client={"protocol": 4, "device": "Mac", "capabilities": ["ptt"]})
        assert daemon._surface() == "mac"
        daemon.state.call_socket = None
        assert daemon._surface() == "page", "a hello left from a call that ended names nothing"
        daemon.state.phone_socket = daemon.state.call_socket = object()
        daemon.state.call_client = types.SimpleNamespace(client={"device": "iPhone"})
        assert daemon._surface() == "iphone"
    finally:
        daemon.state.phone_socket, daemon.state.call_socket, daemon.state.call_client = was


def test_voice_and_tool_are_offered_where_they_exist():
    close = howto.answer("How do I close a session by voice?", "iphone")["answers"][0]
    assert close["your_tool"] == "disconnect_session" and close["say_instead"] == ["close lantern"]
    assert close["where"].startswith("long-press a session at the top → Disconnect from the voice")
    mute = howto.answer("How do I mute myself?", "iphone")["answers"][0]
    assert "say_instead" not in mute and "your_tool" not in mute, "there is no voice command for mute: none is offered"
    assert mute["where"] == "the mic button in the middle at the bottom (Turn mic off / Turn mic on)"


def test_nothing_found_points_to_the_settings_and_is_short():
    out = howto.answer("How do I bake bread?", "iphone")
    assert out["found"] == "nothing" and "••• button" in out["say"]


# ---------- the voice phrases it offers are the ones the code takes ----------

def _voice_checks(daemon):
    import braindump
    import challenge
    import meeting
    import drive
    import guards
    import turns
    import whisper
    import briefing
    import nightshift
    import mute
    import progress
    return {
        "hold": lambda p: turns.hold_intent(p) or turns.release_intent(p),
        "brain-dump": lambda p: braindump.start_intent(p) or braindump.done_intent(p),
        # starting it, a command said in it (a question names the session the code looks it up in), or the send after it
        "meeting": lambda p: daemon.meeting_intent(p) is not None or meeting.send_actions_intent(p) is not None
        or (meeting.addressed(p) is not None and (meeting.command(meeting.addressed(p))[0] != "ask"
                                                  or "session" in meeting.addressed(p))),
        "challenge": lambda p: challenge.start_intent(p) or challenge.end_intent(p),
        "drive": lambda p: drive.intent(p) is not None,
        "whisper": lambda p: whisper.intent(p) is not None,
        "mute": lambda p: mute.intent(p) is not None,
        "progress": lambda p: progress.intent(p) is not None,
        "briefing": lambda p: briefing.briefing_intent(p) is not None,
        "routing-mode": lambda p: guards.mode_intent(p) is not None,
        "switch-session": guards.switch_intent,
        "rename-session": guards.rename_intent,
        "close-session": guards.disconnect_intent,
        "new-session": guards.start_intent,
        "new-session-permissions": lambda p: daemon.newsession.permissions_intent(p) is not None
        or (guards.start_intent(p) and guards.asks_first(p)),
        "join-session": guards.attach_intent,
        "night-shift": lambda p: nightshift.shift_intent(p) is not None or nightshift.stop_intent(p),
        # "talk to hermes" is a switch; "give hermes's answer to openclaw" a relay, sent only on a spoken yes (agent_relay.py)
        "agents": lambda p: guards.switch_intent(p) or __import__("agent_relay").asks_relay(p),
        "polish": lambda p: (daemon.quick.intent(p) or ("",))[0] == "polish",
        "reply-length": lambda p: (daemon.quick.intent(p) or ("",))[0] == "replies.length",
        "speaking-speed": lambda p: (daemon.quick.intent(p) or ("",))[0] == "voice.speed",
    }


def test_every_phrase_offered_by_voice_is_one_the_code_acts_on(d):
    checks = _voice_checks(d)
    voiced = {t.id: t.voice for t in gen.TOPICS if t.voice}
    assert set(voiced) == set(checks), "a topic that offers words to say needs a check here: no new powers by prompt"
    for topic, phrases in voiced.items():
        for phrase in phrases:
            assert checks[topic](phrase), f"{topic}: {phrase!r} is not taken by the code"


def test_every_tool_named_is_one_the_brain_has(d):
    names = {t.name for t in d.TOOLS.standard_tools}
    assert {t.tool for t in gen.TOPICS if t.tool} <= names


# ---------- the file stays in step with the UI ----------

def test_the_committed_file_is_what_the_generator_writes():
    assert (ROOT / gen.OUT).read_text() == gen.dumps(gen.build(ROOT)), \
        "product_help.json is stale: run python3 tools/product_help.py and commit it"


def _copy(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI", tmp_path / "apps" / "PointeKit" / "Sources" / "PointeUI", ignore=shutil.ignore_patterns("Resources"))
    shutil.copytree(ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit", tmp_path / "apps" / "PointeKit" / "Sources" / "PointeKit")
    (tmp_path / "docs" / "features").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "features" / "README.md", tmp_path / "docs" / "features" / "README.md")
    (tmp_path / "pointe").mkdir()
    shutil.copy(ROOT / "pointe" / "ui.html", tmp_path / "pointe" / "ui.html")
    shutil.copy(ROOT / "pointe" / "ui_mute.html", tmp_path / "pointe" / "ui_mute.html")
    return tmp_path


def test_a_changed_label_makes_the_file_stale(tmp_path):
    """The check goes red: a label no topic names, renamed in the app's Settings, changes what the generator writes."""
    root = _copy(tmp_path)
    assert gen.dumps(gen.build(root)) == (ROOT / gen.OUT).read_text()
    view = root / "apps" / "PointeKit" / "Sources" / "PointeUI" / "CallSettings.swift"
    view.write_text(view.read_text().replace('row("The meeting that ended"', 'row("Last meeting"'))
    assert gen.dumps(gen.build(root)) != (ROOT / gen.OUT).read_text()
    page = root / "pointe" / "ui.html"
    page.write_text(page.read_text().replace('aria-label="More"', 'aria-label="Extras"'))
    assert "Extras" in json.dumps(gen.build(root)["ui"]["page"]["top"])


@pytest.mark.parametrize("file,old,new", [
    ("apps/PointeKit/Sources/PointeUI/Turns.swift", 'static let setting = "Wait before answering"', 'static let setting = "Pause"'),
    ("pointe/ui.html", '>Connect your phone</button>', '>Pair a phone</button>'),
    ("apps/PointeKit/Sources/PointeUI/CallSettings.swift", 'Text("Push to talk").tag("ptt")', 'Text("Press to talk").tag("ptt")'),
    ("apps/PointeKit/Sources/PointeUI/BottomBar.swift", 'Text("Always on").tag("always")', 'Text("Open mic").tag("always")'),
])
def test_a_renamed_label_a_topic_names_fails_the_generator(tmp_path, file, old, new):
    root = _copy(tmp_path)
    path = root / file
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, new))
    with pytest.raises(ValueError, match="not a label the code shows"):
        gen.build(root)


def test_every_menu_item_and_settings_section_has_an_entry():
    data = json.loads((ROOT / gen.OUT).read_text())
    paths = {surface: " ".join(p for e in data["entries"] for p in e.get(surface, [])) for surface in ("iphone", "page")}
    for item in data["ui"]["iphone"]["menu"]:
        assert item in paths["iphone"], item
    for section in data["ui"]["page"]["settings"]:
        assert f"Settings → {section}" in paths["page"], section


# ---------- the brain: answered from the tool, never sent ----------

def _scripted_brain(d, monkeypatch, plan):
    """The daemon's own brain, with a model that follows `plan`: each item is a function of the history so far that
    returns the step's calls."""
    import brain as brain_module

    spoken = []

    async def speak(text, request_id=None):
        spoken.append(text)

    async def step(choice, instructions, messages, decls, **_):
        calls = plan.pop(0)(messages)
        return SimpleNamespace(calls=calls, said="", raw=None, vendor="fake", usage={})

    monkeypatch.setattr(brain_module.vendors, "step", step)
    b = d.make_brain(speak)
    b.may_stay_silent = lambda: False
    return b, spoken


def _result(messages, name="how_to_use_pointe"):
    found = [r["result"] for m in messages if m["role"] == "tool" for r in m["results"] if r["name"] == name]
    assert len(found) == 1, found
    return json.loads(found[0]) if isinstance(found[0], str) else found[0]


def test_a_how_to_question_is_answered_from_the_tool_with_the_iphone_path(d, monkeypatch):
    add(d, "s1", "lantern")
    sent = record_dispatch(d, monkeypatch)
    asked = "How do I turn off push to talk?"
    open_gates(d, monkeypatch, asked)
    d.state.phone_socket = object()  # the call is the iPhone app's
    b, spoken = _scripted_brain(d, monkeypatch, [
        lambda m: [{"id": "h1", "name": "how_to_use_pointe", "args": {"question": asked}}],
        lambda m: [{"id": "s1", "name": "speak", "args": {"text": "Use the switch above the mic: Always on."}}],
    ])
    asyncio.run(b.turn(asked))
    result = _result(b.messages)
    assert result["screen"] == "the iPhone app"
    assert result["answers"][0]["where"].startswith("the Always on / Say “Pointe” / Hold to talk switch above the mic")
    assert spoken == ["Use the switch above the mic: Always on."]
    assert sent == []


def test_a_how_to_question_sent_to_a_session_is_refused_and_answered_instead(d, monkeypatch):
    add(d, "s1", "lantern")
    sent = record_dispatch(d, monkeypatch)
    asked = "איך מכבים את הלחץ ודבר?"
    open_gates(d, monkeypatch, asked)
    b, spoken = _scripted_brain(d, monkeypatch, [
        lambda m: [{"id": "x1", "name": "send_to_claude_code", "args": {"message": "How does the user turn off push to talk?"}}],
        lambda m: [{"id": "h1", "name": "how_to_use_pointe", "args": {"question": asked}}],
        lambda m: [{"id": "s1", "name": "speak", "args": {"text": "בהגדרות, Microphone, ואז Always on."}}],
    ])
    asyncio.run(b.turn(asked))
    refusal = _result(b.messages, "send_to_claude_code")
    assert "how_to_use_pointe" in refusal["error"]
    assert _result(b.messages)["answers"][0]["where"].startswith("Settings → Microphone"), "the page, not the app"
    assert sent == [] and spoken == ["בהגדרות, Microphone, ואז Always on."]
    assert not d.state.blocked, "the refusal is not raised to the user as an unsent request"


def test_the_refusal_comes_once_and_never_for_code_or_a_named_session(d, monkeypatch):
    add(d, "s1", "lantern")
    sent = record_dispatch(d, monkeypatch)

    def send(words, message):
        open_gates(d, monkeypatch, words)
        p = Params(message=message)
        asyncio.run(d.send_to_claude_code(p))
        return p.results[-1]

    assert "error" in send("How do I turn off push to talk?", "Explain push to talk.")
    p = Params(message="Explain push to talk.")
    asyncio.run(d.send_to_claude_code(p))  # the same utterance, sent again: they meant the session
    assert "error" not in p.results[-1] and len(sent) == 1
    assert "error" not in send("How do I add push to talk to the iOS code?", "Add push to talk to the iOS code.")
    assert "error" not in send("Ask lantern how do I turn off push to talk?", "How does one turn off push to talk?")
    assert len(sent) == 3


def test_the_tool_is_read_only_and_works_in_a_meeting(d):
    assert d.modes.MEETING_LISTENING.allows_tool("how_to_use_pointe") and d.modes.CHALLENGE.allows_tool("how_to_use_pointe")
    assert all(d.modes.narrows(m) for m in d.modes.ALL)


# ---------- the context budget ----------

def test_the_help_costs_one_tool_and_one_rule_not_the_file(d):
    tool = next(t for t in d.TOOLS.standard_tools if t.name == "how_to_use_pointe")
    assert len(tool.description) + len(json.dumps(tool.properties)) < 400
    rule = next(line for line in d.INSTRUCTIONS.split("\n- ") if "how_to_use_pointe" in line)
    assert len(rule) < 450 and "Never send" in rule and "in English" in rule
    prompt = d.INSTRUCTIONS + d.BRAIN_RULES + d._brain_context()
    for e in json.loads((ROOT / gen.OUT).read_text())["entries"]:
        assert e["how"] == "" or e["how"] not in prompt, f"{e['id']}: help text belongs in the tool, not the prompt"


@pytest.mark.parametrize("question", ["How do I turn off push to talk?", "settings", "session", "how do I use pointe?",
                                      "איך משתמשים בזה?", "voice lock brain dump meeting challenge drive whisper"])
def test_a_result_is_small_whatever_the_question(question):
    import brain
    for surface in ("iphone", "page"):
        size = len(json.dumps(howto.answer(question, surface), ensure_ascii=False))
        assert size < 1800 < brain.MAX_RESULT_CHARS, (question, size)
