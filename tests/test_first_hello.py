"""The first success, and a call that cannot work never looking like one that does. From the onboarding reviews: a new
user's first call greeted with "I'm still catching up on it" and setup moved on without knowing the call worked; with a
refused key the page said Listening with a green dot while nothing could hear; and a reconnect printed the greeting twice
in one bubble. Synthetic sessions, fake keys and the in-process test client only."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import InputTextRawFrame, LLMRunFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection

from test_orchestrator import add, d  # noqa: F401  (d is the daemon fixture)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
PAGE = (ROOT / "ui.html").read_text()


@pytest.fixture
def first(d, tmp_path, monkeypatch):
    """A Mac where no one has been answered yet; the model, if asked, says so."""
    monkeypatch.setattr(d, "FIRST_HELLO", tmp_path / "first-hello")
    asked = []

    async def step(*_a, **_k):
        asked.append(True)
        return SimpleNamespace(calls=[{"id": "c1", "name": "speak", "args": {"text": "A model reply."}}], said="",
                               raw=None, vendor="fake", usage={})
    monkeypatch.setattr(d.vendors, "step", step)
    return d, asked


def _front(d):
    front = d.BrainFront(d._opening_context())
    spoken = []

    async def push(frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TTSSpeakFrame):
            spoken.append(frame.text)
    front.push_frame = push
    tasks = []
    front.create_task = lambda coro, name=None: tasks.append(asyncio.ensure_future(coro))
    return front, spoken, tasks


def test_the_first_call_asks_for_hello_and_answers_it_without_a_model(first):
    d, asked = first
    add(d, "s1", "billing")
    d.REGISTRY.active_id = "s1"
    front, spoken, tasks = _front(d)

    async def run():
        await front.process_frame(LLMRunFrame(), FrameDirection.DOWNSTREAM)
        await front.process_frame(InputTextRawFrame(text="Hello"), FrameDirection.DOWNSTREAM)
        await asyncio.gather(*tasks)

    asyncio.run(run())
    assert spoken == ["Hi, I'm Pointe. Say hello so I know I can hear you.",
                      "I can hear you, and billing is joined. Ask me what it is doing."]
    assert not asked, "the first success waits on no model"
    assert d.FIRST_HELLO.exists() and not d.first_call()


def test_after_the_first_hello_the_model_answers_as_always(first):
    d, asked = first
    d.FIRST_HELLO.write_text("")
    add(d, "s1", "billing")
    d.REGISTRY.active_id = "s1"
    assert d.fixed_greeting() == "Connected to billing. I'm still catching up on it."
    front, spoken, tasks = _front(d)

    async def run():
        await front.process_frame(InputTextRawFrame(text="Hello"), FrameDirection.DOWNSTREAM)
        await asyncio.gather(*tasks)

    asyncio.run(run())
    assert asked, "the brain took the turn"


def test_the_first_reply_says_which_sessions_are_joined(first):
    d, _ = first
    assert d.first_hello_reply() == ("I can hear you. No session is joined yet: run slash pointe voice in a Claude Code "
                                     "session, and I'll pick it up.")
    add(d, "s1", "billing")
    add(d, "s2", "docs")
    assert d.first_hello_reply() == "I can hear you. 2 sessions are joined: billing, docs. Ask me what one of them is doing."


def test_setup_waits_for_the_file_the_first_hello_writes(first):
    d, _ = first
    attach = (ROOT / "bin" / "claude-voice-attach").read_text()
    assert d.FIRST_HELLO.name == "first-hello" and '"$STATE/first-hello"' in attach
    assert "Pointe heard you. You're set up." in attach


def test_a_reconnect_does_not_print_the_greeting_twice_in_one_bubble(d, monkeypatch):
    monkeypatch.setattr(d.state, "conversation", [])
    greeting = "Connected. Run slash pointe voice in Claude Code, or pointe join in another agent, and I'll pick it up."
    d._bot_says(greeting)
    d._bot_says(greeting)
    assert [text.strip() for _, text in d.state.conversation] == [greeting]
    d._bot_says("Billing finished.")
    assert d.state.conversation[-1][1].strip() == f"{greeting} Billing finished."


# ---------- a refused key ----------

def _refused(d, monkeypatch, vendor_line: str):
    monkeypatch.setattr(d, "_problem", (0.0, ""))
    d._note_problem(SimpleNamespace(record={"message": vendor_line}))


def test_a_refused_ears_key_is_reported_as_cannot_hear(d, monkeypatch):
    monkeypatch.setattr(d, "_setup", d.vendors.Setup(brain="gemini:b", reader="gemini:r", checker="gemini:c", ears="gemini",
                                                     mouth="gemini:m"))
    assert d.key_refused() is None
    _refused(d, monkeypatch, "GeminiSTTService#1 exception: Error setting up processor: 1007 None. API key not valid.")
    assert d.key_refused() == {"vendor": "gemini", "ears": True}


def test_a_refused_brain_key_is_reported_but_not_as_the_ears(d, monkeypatch):
    _refused(d, monkeypatch, "Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', "
                             "'message': 'invalid x-api-key'}} anthropic")
    assert d.key_refused() == {"vendor": "anthropic", "ears": False}  # the fixture's ears are Soniox


def test_the_page_never_says_listening_over_a_refused_key():
    state = PAGE[PAGE.index("function showState()"):PAGE.index("let subShown")]
    refused = state.index("s.key_refused")
    assert refused < state.index("['live', 'Listening']") and refused < state.index("[st, title] = ['bot', 'Speaking']")
    assert ("['broken', (s.key_refused || s.vendor_fault).ears ? CONNECT_COPY.cannotHear : CONNECT_COPY.cannotAnswer]"
            in state)  # a vendor out of quota, failing, or gone for the call: the same red state (tests/test_vendor_faults.py)
    assert "[data-state=broken] .top .dot { background: var(--danger); }" in PAGE
    assert 'id="fixkey"' in PAGE and "Fix the key" in PAGE


def test_the_key_check_at_start_stops_the_tab_from_opening_on_a_refused_key(d, monkeypatch, capsys):
    import doctor
    import keys

    monkeypatch.setattr(doctor.vendors, "resolve", lambda front: d.vendors.Setup(brain="gemini:b", reader="gemini:r",
                                                                                checker="gemini:c", ears="gemini",
                                                                                mouth="gemini:m"))
    monkeypatch.delenv("CLAUDE_VOICE_SKIP_KEY_CHECK", raising=False)
    monkeypatch.setattr(keys, "check", lambda vendor, secret=None: (False, d.vendors.refused_help(vendor)))
    assert doctor.preflight() == 1
    out = capsys.readouterr().out
    assert "The gemini key was refused" in out and "pointe key gemini" in out
    monkeypatch.setattr(keys, "check", lambda vendor, secret=None: (None, "could not be checked: no connection"))
    assert doctor.preflight() == 0, "offline is not refused: the call may still work"


# ---------- the page adds a key and switches the setup on the Mac ----------

@pytest.fixture
def client(d, monkeypatch):
    from fastapi.testclient import TestClient

    ran = []
    monkeypatch.setattr(d, "_run_on_the_mac", lambda *commands: ran.append(commands))
    return TestClient(d.app, base_url="http://127.0.0.1:7860", cookies={"pointe_local": d.PAGE_KEY}), ran


def test_add_a_key_from_the_page_runs_pointe_key_on_the_mac(d, client):
    c, ran = client
    assert c.post("/voice/key", json={"vendor": "gemini"}).json() == {"ok": True}
    assert ran == [([str(d.POINTE_CLI), "key", "gemini"],)]
    assert c.post("/voice/key", json={"vendor": "nope"}).status_code == 400


def test_use_a_setup_from_the_page_switches_and_restarts(d, client):
    c, ran = client
    assert c.post("/voice/setup", json={"id": "two"}).json() == {"ok": True}
    assert ran == [([str(d.POINTE_CLI), "setup", "two"], [str(d.POINTE_CLI), "restart"])]
    assert c.post("/voice/setup", json={"id": "best"}).status_code == 400


def test_a_page_off_the_mac_cannot_open_the_key_window(d, client, monkeypatch):
    c, ran = client
    monkeypatch.setattr(d, "_off_the_mac", lambda request: True)
    assert c.post("/voice/key", json={"vendor": "gemini"}).status_code == 403
    assert c.post("/voice/setup", json={"id": "free"}).status_code == 403 and not ran


def test_the_detached_commands_carry_no_key(d, monkeypatch):
    seen = {}
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic-gemini")
    monkeypatch.setattr(d.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, **kw))
    d._run_on_the_mac(["/x/bin/pointe", "setup", "two"], ["/x/bin/pointe", "restart"])
    assert seen["cmd"][:2] == ["/bin/sh", "-c"] and "/x/bin/pointe setup two && /x/bin/pointe restart" in seen["cmd"][2]
    assert seen["cmd"][2].rstrip().endswith("&"), "detached: voice-daemon stop ends the daemon's children"
    assert "GOOGLE_API_KEY" not in seen["env"] and seen["env"]["CLAUDE_VOICE_STATE"] == str(d.STATE_DIR)
    assert seen["start_new_session"]


def test_the_page_offers_add_and_use_this_setup_on_the_mac_only():
    keys = PAGE[PAGE.index("function showKeys()"):PAGE.index("async function openSettings()")]
    assert "remotePage" in keys and "'/voice/key'" in PAGE and "'/voice/setup'" in PAGE
    assert "KEYS_COPY.add" in keys and "KEYS_COPY.use" in keys
    assert "Best for ${x.pick_for}" in keys and "For ${x.pick_for}" not in keys.replace("Best for ${x.pick_for}", "")
    assert os.path.basename(str(ROOT / "bin" / "pointe")) == "pointe"


def test_a_mac_with_calls_before_the_marker_is_not_on_its_first_call(first, monkeypatch):
    """An update must not greet a daily user with "Say hello so I know I can hear you", or hide their controls."""
    d, _ = first
    monkeypatch.setattr(d, "HAD_CALLS", True)
    assert not d.first_call() and d.FIRST_HELLO.exists()


def test_before_the_first_hello_the_page_shows_only_connect_the_mic_type_settings_and_sessions():
    rule = PAGE[PAGE.index("/* Before Pointe has answered anyone on this Mac"):]
    rule = rule[:rule.index("}")]
    for hidden in ("#listen", "#meetbtn", "#briefbtn", ".micmode", "#chlbtn", "#whisperbtn", "#polishrow", "#ctx", "#modesec",
                   "#m-night"):
        assert f"body.firstrun {hidden}" in rule, hidden
    for kept in ("#mic", "#typebtn", "#sessbtn", "#m-new", "#topconnect"):
        assert kept not in rule, kept
    assert "document.body.classList.toggle('firstrun', !!(s && s.first_call));" in PAGE
